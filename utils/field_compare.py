"""
Deterministic (non-AI) comparison of one mapped field against the output text.

Most mapped fields reconcile mechanically: the value is there verbatim, or
uppercased, or with punctuation/currency/date formatting applied, or it is
plainly absent. Routing those through an LLM is slower, costs tokens, and is
less reliable than plain code. Every rule here resolves only what it can
resolve with real confidence and returns None otherwise, so the caller falls
back to the AI comparison pass instead of a rule quietly guessing.

Each rule also reports WHAT it found in the document — the actual rendered
text, not a paraphrase — so the report can show source and output side by
side. The snippet is always lifted verbatim from the output; nothing is
reconstructed or prettified.

Two failure modes are treated as expensive and guarded against explicitly:
  * a false MATCH hides a genuine rendering defect, so short/ambiguous values
    are never matched on a loose normalized-substring basis;
  * a false GAP creates noise, so GAP is only returned when the value shares
    no tokens at all with the output.
"""

import re
from datetime import datetime

MATCH, MISMATCH, GAP, REVIEW = "MATCH", "MISMATCH", "GAP", "REVIEW"

# The verdict is binary: a mapped field either renders its source value in full
# (PASS) or it does not (FAIL). "Partly rendered", "close enough" and
# "standardised by some downstream process" are all FAIL — whether a difference is
# acceptable is the tester's call to make from the evidence, not a call this tool
# should quietly make on their behalf, and any leniency rule would have to encode
# knowledge of one specific project.
#
# NOT_VERIFIABLE is the only third state, and it is not a soft pass: it means the
# inputs cannot answer the question at all — the BRD names no text and no data
# field for the element, or the element is not text (logo, barcode). These rows
# are excluded from the pass rate and listed on their own so they can never be
# mistaken for verified.
NOT_VERIFIABLE = "NOT VERIFIABLE"
FAIL_STATES = (MISMATCH, GAP, REVIEW)

_DATE_IN = ["%m-%d-%Y", "%m/%d/%Y", "%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y",
            "%m-%d-%y", "%m/%d/%y", "%d/%m/%Y", "%Y%m%d", "%B %d, %Y", "%b %d, %Y"]
# Only separator-bearing / word-bearing forms — a bare "07222026" would match
# inside a scan line and produce a false MATCH.
_DATE_OUT = ["%m-%d-%Y", "%m/%d/%Y", "%m-%d-%y", "%m/%d/%y", "%Y-%m-%d", "%Y/%m/%d",
             "%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y"]

_NUM_TOKEN = re.compile(r"(?<![\d.])\(?-?\$?\s?\d{1,3}(?:,\d{3})*(?:\.\d+)?\)?(?![\d])")

NOT_PRESENT = "Not present in output"
MAX_SNIPPET = 110


def _res(status, notes="", output=""):
    return {"status": status, "notes": notes, "output": output, "by": "Deterministic"}


def norm(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def _norm_map(s: str):
    """Normalized form plus, for each normalized char, its index in the raw
    string — lets a normalized hit be traced back to the real text."""
    chars, idx = [], []
    for i, ch in enumerate(s):
        c = ch.lower()
        if c.isalnum():
            chars.append(c)
            idx.append(i)
    return "".join(chars), idx


def _snippet(out: str, start: int, end: int, pad: int = 34) -> str:
    """The output text immediately around a match, verbatim. Windowed rather
    than whole-line so the quote stays about THIS field instead of dragging in
    whatever else shares the line."""
    ls = out.rfind("\n", 0, start) + 1
    le = out.find("\n", end)
    if le == -1:
        le = len(out)
    a, b = max(ls, start - pad), min(le, end + pad)
    while a > ls and out[a - 1].isalnum():      # never cut mid-token
        a -= 1
    while b < le and out[b].isalnum():
        b += 1
    frag = " ".join(out[a:b].split())
    return (("…" if a > ls else "") + frag + ("…" if b < le else ""))[:MAX_SNIPPET]


def _occurrences(out: str, needle: str, ci: bool = False, limit: int = 60):
    hay, ndl = (out.lower(), needle.lower()) if ci else (out, needle)
    spans, st = [], 0
    while len(spans) < limit:
        i = hay.find(ndl, st)
        if i == -1:
            break
        spans.append((i, i + len(ndl)))
        st = i + 1
    return spans


def _boundary_score(ch: str | None) -> float:
    """Whitespace (or a line edge) means the value stands alone — the strongest
    evidence it is really this field. Punctuation is weaker: "PROPANE" inside
    "1-800-PROPANE" is bounded, but it is part of a phone number."""
    if ch is None or ch.isspace():
        return 3.0
    if not ch.isalnum():
        return 1.0
    return 0.0


def _score_span(out: str, s: int, e: int) -> float:
    """Prefers the occurrence a human would point at: one standing as its own
    token on a short line, not one buried inside a scan line or long ID."""
    score = _boundary_score(out[s - 1] if s > 0 else None) \
        + _boundary_score(out[e] if e < len(out) else None)
    ls = out.rfind("\n", 0, s) + 1
    le = out.find("\n", e)
    if le == -1:
        le = len(out)
    line = out[ls:le]
    longest_run = max((len(m.group()) for m in re.finditer(r"[A-Za-z0-9]{8,}", line)), default=0)
    if longest_run >= 24:          # scan line / packed identifier
        score -= 3
    score -= min(len(line), 200) / 200.0
    return score


def _best_span(out: str, needle: str, ci: bool = False):
    spans = _occurrences(out, needle, ci)
    if not spans:
        return None
    return max(spans, key=lambda sp: _score_span(out, sp[0], sp[1]))


def _tokens(s):
    return [t for t in re.findall(r"[A-Za-z0-9]+", str(s)) if len(t) >= 3]


def _best_line(out: str, toks) -> tuple:
    """The single output line sharing the most tokens with the source value."""
    best, best_score = "", 0
    for line in out.splitlines():
        nl = norm(line)
        sc = sum(1 for t in toks if norm(t) in nl)
        if sc > best_score:
            best, best_score = " ".join(line.split()), sc
    return best[:MAX_SNIPPET], best_score


def _to_number(s):
    t = str(s).strip()
    neg = t.startswith("(") and t.endswith(")")
    t = re.sub(r"[^\d.\-]", "", t)
    if t in ("", "-", ".", "-."):
        return None
    try:
        v = float(t)
    except ValueError:
        return None
    return -abs(v) if neg else v


def _parse_date(s):
    t = str(s).strip()
    for f in _DATE_IN:
        try:
            return datetime.strptime(t, f)
        except ValueError:
            continue
    return None


def compare_field(source_value: str, output_text: str, field_label: str = "") -> dict | None:
    """Returns {'status','notes','output','by'} when the comparison resolves
    with confidence, else None to hand the field to the AI pass."""
    src = ("" if source_value is None else str(source_value)).strip()
    out = output_text or ""

    # 1. Nothing in the source — nothing is expected in the output.
    if src == "":
        return _res(MATCH, "No source value — nothing expected in the output.", "—")

    if not out.strip():
        return _res(GAP, "No output text available for this record.", NOT_PRESENT)

    # 1b. Values of one or two characters ("6", "0", "NY") carry almost no
    # signal: a bare digit will word-boundary-match inside "$6.59" or a date and
    # produce a confident-looking MATCH that is meaningless. No text rule can
    # tell a real rendering from a coincidence at that length, so these always
    # go to the AI pass, which has the surrounding document for context.
    if len(norm(src)) < 3:
        return None

    low_out = out.lower()

    # 2/3. Verbatim, then case-insensitive. Raw substrings keep their original
    # punctuation, which makes them specific enough to trust at any length.
    sp = _best_span(out, src)
    if sp:
        return _res(MATCH, "", _snippet(out, sp[0], sp[1]))
    sp = _best_span(out, src, ci=True)
    if sp:
        return _res(MATCH, "Case differs on render.", _snippet(out, sp[0], sp[1]))

    n_src = norm(src)
    n_out, raw_idx = _norm_map(out)

    # 4. Punctuation/spacing-insensitive — only for values long enough that an
    # accidental hit inside a scan line or ID string is implausible.
    if len(n_src) >= 6:
        p = n_out.find(n_src)
        if p != -1:
            return _res(MATCH, "Punctuation or spacing differs on render.",
                        _snippet(out, raw_idx[p], raw_idx[p + len(n_src) - 1] + 1))

    # 5. Short values: require a word-boundary hit rather than a loose one.
    if len(n_src) < 6:
        m = re.search(r"(?<![A-Za-z0-9])" + re.escape(src) + r"(?![A-Za-z0-9])", out, re.I)
        if m:
            return _res(MATCH, "", _snippet(out, m.start(), m.end()))

    # 6. Numeric / currency formatting (6.59 -> $6.59, -201 -> -$201.00).
    sn = _to_number(src)
    if sn is not None and re.fullmatch(r"[\d.,()\-$\s]+", src):
        for m in _NUM_TOKEN.finditer(out):
            on = _to_number(m.group())
            if on is not None and abs(on - sn) < 0.005:
                return _res(MATCH, "Rendered with currency or decimal formatting.",
                            _snippet(out, m.start(), m.end()))
        # Absent numbers are reported as a GAP, never a MISMATCH: this rule can
        # see that the value is missing, but not whether the field was rendered
        # with a wrong value instead. Short numbers ("0", "12") are too weak a
        # signal either way, so they go to the AI pass.
        if len(re.sub(r"\D", "", src)) >= 3:
            return _res(GAP, "Present in source but not rendered anywhere in the output.", NOT_PRESENT)
        return None

    # 7. Date formatting differences.
    sd = _parse_date(src)
    if sd is not None:
        for f in _DATE_OUT:
            try:
                cand = sd.strftime(f)
            except ValueError:
                continue
            dsp = _best_span(out, cand, ci=True)
            if dsp:
                return _res(MATCH, "Date format differs on render.",
                            _snippet(out, dsp[0], dsp[1]))
        return None

    # 8. Multi-token values (addresses, names) — score token overlap.
    toks = _tokens(src)
    if len(toks) >= 2:
        hit = sum(1 for t in toks if norm(t) in n_out)
        ratio = hit / len(toks)
        if ratio >= 0.7:
            line, _ = _best_line(out, toks)
            note = ("Rendered with formatting differences." if ratio == 1.0
                    else f"Rendered with formatting differences ({hit} of {len(toks)} tokens matched).")
            return _res(MATCH, note, line or "Rendered in output")
        if ratio == 0.0:
            return _res(GAP, "Present in source but not rendered anywhere in the output.", NOT_PRESENT)
        return None  # partial overlap is exactly the ambiguous case AI should judge

    # 9. Single distinctive token that appears nowhere at all.
    if len(n_src) >= 5 and n_src not in n_out:
        return _res(GAP, "Present in source but not rendered anywhere in the output.", NOT_PRESENT)

    return None


def evidence_snippet(source_value: str, output_text: str) -> str:
    """Best-effort verbatim quote of where `source_value` appears in the
    document, independent of any verdict.

    The AI pass is asked to quote the document, but a model may return a verdict
    and omit the quote. Rather than printing a generic phrase in the report's
    Output Value column, re-derive the real text here with the same matching
    machinery the rules use. Returns "" only when nothing plausible is found."""
    src = ("" if source_value is None else str(source_value)).strip()
    out = output_text or ""
    if not src or not out.strip():
        return ""

    for ci in (False, True):
        sp = _best_span(out, src, ci=ci)
        if sp:
            return _snippet(out, sp[0], sp[1])

    n_src = norm(src)
    if len(n_src) >= 6:
        n_out, raw_idx = _norm_map(out)
        p = n_out.find(n_src)
        if p != -1:
            return _snippet(out, raw_idx[p], raw_idx[p + len(n_src) - 1] + 1)

    toks = _tokens(src)
    if len(toks) >= 2:
        line, hits = _best_line(out, toks)
        if hits >= max(1, len(toks) // 2):
            return line
    return ""


def summarize(rows: list) -> dict:
    c = {MATCH: 0, MISMATCH: 0, GAP: 0, REVIEW: 0}
    for r in rows:
        c[r.get("status", REVIEW)] = c.get(r.get("status", REVIEW), 0) + 1
    return c
