"""
Spec-driven validation: BRD slots -> expected values -> compare to each letter.

The BRD decides what is checked. A field the spec does not map is out of scope,
not a gap — which is what removes the ~78% noise a data-driven walk produces.

Because every slot yields an EXPECTED value, two defect classes that a
"does this value appear anywhere" check can never express become detectable:

  * TRUNCATION — expected "…HEIMGARTNER-JOHNSONVILLE III", rendered
    "…HEIMGARTNER-JOHNS". A prefix probe finds it.
  * WRONG VALUE — expected "$123,456,789.99", rendered "$55.55". A same-shape
    probe finds the competing value and quotes it.

Both are deterministic. AI is only consulted for slots the rules genuinely
cannot settle.
"""

import json
import re
import concurrent.futures as cf

from utils.json_utils import safe_json
from utils.llm_client import classify_api_error
from utils.field_compare import (MATCH, MISMATCH, GAP, REVIEW, NOT_VERIFIABLE, norm, _norm_map,
                                 _best_span, _snippet, _tokens, _best_line, NOT_PRESENT,
                                 _to_number, _parse_date, _NUM_TOKEN)
from utils.json_utils import safe_json_object
from utils.mapping_spec import (ABSENT, plan_letters, slots_for_letter, eval_expected,
                                slot_checks)
from prompts.field_mapping_prompt import FIELD_COMPARE_PROMPT
from prompts.mapping_spec_prompt import MAPPING_SPEC_PROMPT

SHAPES = {
    "currency": re.compile(r"\$\s?-?[\d,]+(?:\.\d{2})?"),
    "date": re.compile(r"\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b"),
    "phone": re.compile(r"\b\d{3}-\d{3}-\d{4}\b"),
}
SLOTS_PER_BATCH = 30


def _res(status, notes="", output="", by="Deterministic"):
    return {"status": status, "notes": notes, "output": output, "by": by}


# ── Mapping Spec Agent — the only place the BRD is interpreted ────

def run_mapping_spec_agent(brd_text, mapping_text, sample_record, client, dbg):
    """One call: BRD -> slot specs. Everything downstream is deterministic, so
    this output is worth reviewing before a validation run."""
    prompt = MAPPING_SPEC_PROMPT.format(
        brd=(brd_text or "")[:60000],
        mapping=(mapping_text or "NONE PROVIDED")[:20000],
        sample_record=json.dumps(sample_record, indent=2, default=str)[:6000])
    dbg.add("info", "MAPPING-SPEC", f"Reading BRD into slot specs — prompt {len(prompt):,} chars")
    result = client.run(prompt, dbg)
    spec = safe_json_object(result.get("text", ""), dbg)
    if not isinstance(spec, dict) or not spec.get("slots"):
        raise ValueError("The Mapping Spec Agent did not return a usable spec. If the debug log shows "
                         "a truncated response, the model ran out of output budget — try a model with "
                         "a larger output limit, or split the BRD. Enable Debug to see the raw text.")
    spec["truncated"] = bool(spec.pop("_truncated", False))
    if spec["truncated"]:
        dbg.add("warn", "MAPPING-SPEC",
                f"The spec response was CUT OFF. {len(spec.get('slots') or [])} slot(s) were "
                f"recovered, but any BRD row after the cut is MISSING and will not be validated. "
                f"Review the spec before trusting coverage.")
    spec.setdefault("letters", [{"id": "letter", "label": "Document",
                                 "addressee": {"kind": "root"},
                                 "counterparty": {"kind": "root"},
                                 "presence": {"kind": "always"}}])
    usage = {"input": result["input_tokens"], "output": result["output_tokens"],
             "total": result["total_tokens"]}
    dbg.add("ok", "MAPPING-SPEC",
            f"{len(spec.get('slots') or [])} slot(s), {len(spec.get('letters') or [])} letter "
            f"definition(s), {len(spec.get('not_verifiable_requirements') or [])} requirement(s) "
            f"flagged as not verifiable from these inputs")
    return spec, usage


def _truncation_probe(expected: str, out: str):
    """Finds the longest leading chunk of `expected` that IS rendered. A long
    prefix present while the whole value is absent means the slot was truncated."""
    n_out, raw_idx = _norm_map(out)
    n_exp = norm(expected)
    if len(n_exp) < 12:
        return None
    lo, hi, best = int(len(n_exp) * 0.45), len(n_exp) - 1, None
    for cut in range(hi, lo, -1):
        p = n_out.find(n_exp[:cut])
        if p != -1:
            best = (cut, p, raw_idx[p], raw_idx[p + cut - 1] + 1)
            break
    if not best:
        return None
    cut, _, rs, re_ = best
    return {"kept": cut, "total": len(n_exp), "snippet": _snippet(out, rs, re_)}


def _label_span(out: str, slot_name: str):
    """Where this field's own label appears in the output, if it does.

    A same-shape probe with no anchor will always find something: asked for a due
    date it returned the transaction date, then the invoice date. Both belong to
    other fields. Humans do not read a document that way — they find the label and
    read what sits next to it. Matching the label first is what makes a claim of
    "found X" attributable to THIS field instead of merely shape-compatible.
    """
    words = [w for w in re.split(r"[^A-Za-z0-9]+", slot_name or "") if len(w) > 2]
    if not words:
        return None
    low = out.lower()
    best, best_hits = None, 0
    for m in re.finditer(r"[A-Za-z][A-Za-z .#/&-]{2,40}", out):
        seg = m.group().lower()
        hits = sum(1 for w in words if w.lower() in seg)
        if hits > best_hits:
            best, best_hits = m, hits
    if best is None or best_hits < max(1, len(words) - 1):
        return None
    return best.end()


def _shape_probe(expected: str, out: str, fmt: str, others=(), slot_name: str = ""):
    """A competing value of the same shape as the expected one, ATTRIBUTED to this
    field — the actual text for a wrong-value defect.

    `others` removes values that belong to other mapped fields. The label anchor
    then requires the candidate to sit near this field's own label. If neither can
    attribute a candidate, no value is quoted: the caller falls through to NOT
    RENDERED, which is the honest answer, and the note still records that
    same-shape values exist elsewhere on the page.
    """
    rx = SHAPES.get((fmt or "").lower())
    if not rx:
        return None
    want = norm(expected)
    taken = {norm(o) for o in others if o}
    taken_dates = {d for d in (_parse_date(o) for o in others if o) if d}
    taken_nums = {n for n in (_to_number(o) for o in others if o) if n is not None}

    cands = []
    for m in rx.finditer(out):
        got = m.group()
        if norm(got) == want or norm(got) in taken:
            continue
        gd, gn = _parse_date(got), _to_number(got)
        if (gd and gd in taken_dates) or (gn is not None and gn in taken_nums):
            continue
        cands.append(m)
    if not cands:
        return None

    anchor = _label_span(out, slot_name)
    if anchor is not None:
        near = [m for m in cands if 0 <= m.start() - anchor <= 60]
        if near:
            m = min(near, key=lambda x: x.start() - anchor)
            return {"found": m.group().strip(), "snippet": _snippet(out, m.start(), m.end())}

    return {"unattributed": [m.group().strip() for m in cands[:3]]}


_DATE_TOKEN = re.compile(r"\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b")


def _equal_value_elsewhere(expected: str, out: str):
    """Finds a token in the output that IS the expected value, written differently.

    A date given as 07-21-2026 and printed as 07-21-26 is not missing — it is
    reformatted. Reporting it as NOT RENDERED sends a tester hunting for a value
    that is on the page in front of them. Still a failure under a no-loss rule
    (the year was shortened), but the reason has to be accurate.
    """
    d_exp = _parse_date(expected)
    if d_exp:
        for m in _DATE_TOKEN.finditer(out):
            if _parse_date(m.group()) == d_exp and norm(m.group()) != norm(expected):
                return {"found": m.group().strip(), "why": "same date, shorter form",
                        "snippet": _snippet(out, m.start(), m.end())}
    n_exp = _to_number(expected)
    if n_exp is not None:
        for m in _NUM_TOKEN.finditer(out):
            if _to_number(m.group()) == n_exp and norm(m.group()) != norm(expected):
                return {"found": m.group().strip(), "why": "same amount, different formatting",
                        "snippet": _snippet(out, m.start(), m.end())}
    return None


def _is_label_leak(slot: dict) -> bool:
    """True when a slot's expected value is just the BRD row's own label.

    A BRD row reading `Footer | Template. Static.` names an element but never says
    what text it holds. Read literally it becomes constant "Footer", and since no
    document contains the word "Footer" it fails on every page — 18 of 40 findings
    in one real run. The row is unanswerable from these inputs, so it is excluded
    rather than reported. Kept as a rule here, not only in the prompt, because a
    prompt cannot be relied on and the failure mode is silent and large.
    """
    exp = slot.get("expected") or {}
    if exp.get("kind") != "constant":
        return False
    val = norm(str(exp.get("value", "")))
    name = norm(str(slot.get("slot_name", "")))
    return bool(val) and bool(name) and val == name


def compare_slot(expected, out: str, slot: dict, others=()):
    """Compares one slot's expected value against a letter's text.
    Returns a verdict dict, or None to defer to AI."""
    exp_spec = slot.get("expected") or {}
    fmt = exp_spec.get("format", "")
    prefix = str(exp_spec.get("prefix", "") or "").strip()

    # 1. The slot must render nothing.
    if expected == ABSENT:
        probe = prefix or (slot.get("absence_probe") or "")
        if probe and re.search(re.escape(probe), out, re.I):
            sp = _best_span(out, probe, ci=True)
            return _res(MISMATCH, "Expected to be suppressed by rule, but is rendered.",
                        _snippet(out, sp[0], sp[1]) if sp else probe)
        return _res(MATCH, "Correctly suppressed per business rule.", "Not rendered (as required)")

    expected = "" if expected is None else str(expected).strip()
    if expected == "":
        return _res(MATCH, "No source value — nothing expected in the output.", "—")
    if not out.strip():
        return _res(MISMATCH, "No output text available for this letter — nothing could "
                              "be verified against it.", NOT_PRESENT)

    # 2. Rendered as expected (verbatim, case, or punctuation/spacing).
    for ci in (False, True):
        sp = _best_span(out, expected, ci=ci)
        if sp:
            note = "" if not ci else "Case differs on render."
            return _res(MATCH, note, _snippet(out, sp[0], sp[1]))
    n_exp, (n_out, raw_idx) = norm(expected), _norm_map(out)
    if len(n_exp) >= 6:
        p = n_out.find(n_exp)
        if p != -1:
            return _res(MATCH, "Punctuation or spacing differs on render.",
                        _snippet(out, raw_idx[p], raw_idx[p + len(n_exp) - 1] + 1))

    # 3. Multi-token values (addresses, names): every part of the source must be
    #    present. Anything missing is a FAIL and the missing part is named, so the
    #    tester can see at a glance whether it is a dropped line, a substituted
    #    word or a shortened one. This layer deliberately makes NO judgement about
    #    whether a difference is "acceptable" — that would mean encoding one
    #    project's conventions, and the next project's would be different.
    toks = _tokens(expected)
    if len(toks) >= 2:
        missing = [t for t in toks if norm(t) not in n_out]
        line, _ = _best_line(out, toks)
        if not missing:
            return _res(MATCH, "Rendered in full; formatting differs.",
                        line or "Rendered in output")
        rendered = len(toks) - len(missing)
        if rendered:
            return _res(MISMATCH,
                        f"Rendered INCOMPLETE — {rendered} of {len(toks)} part(s) present, "
                        f"missing: {', '.join(missing[:6])}. Expected \"{expected[:70]}\".",
                        line or "Rendered in output")

    # 4. Truncated — a long leading chunk is rendered and the rest is absent.
    tr = _truncation_probe(expected, out)
    if tr:
        return _res(MISMATCH,
                    f"Rendered but TRUNCATED — only {tr['kept']} of {tr['total']} characters "
                    f"appear. Expected \"{expected[:70]}\".", tr["snippet"])

    # 5. Wrong value — something of the same shape is rendered instead.
    sh = _shape_probe(expected, out, fmt, others, slot.get("slot_name", ""))
    if sh and sh.get("found"):
        return _res(MISMATCH,
                    f"Rendered value does not reconcile — expected \"{expected}\", "
                    f"found \"{sh['found']}\".", sh["snippet"])
    unattributed = (sh or {}).get("unattributed") or []

    # 6. Same value, different formatting. Still a FAIL — the source value did not
    #    render as given — but saying NOT RENDERED about a date that is plainly on
    #    the page, in a shorter form, is simply false, and a tester triaging fifty
    #    rows needs to see the difference between "absent" and "reformatted".
    eq = _equal_value_elsewhere(expected, out)
    if eq:
        return _res(MISMATCH,
                    f"Rendered in a DIFFERENT FORMAT — expected \"{expected}\", "
                    f"found \"{eq['found']}\" ({eq['why']}).", eq["snippet"])

    # 7. Nothing of the source reached the output. A mapped field that does not
    #    render is a failure, not a softer "gap" — the BRD said it must print.
    if len(toks) >= 2 or len(n_exp) >= 5:
        extra = ""
        if unattributed:
            extra = (" Other value(s) of the same shape appear elsewhere on the page ("
                     + ", ".join(unattributed) + ") but none next to this field's label; "
                     "check the label position by eye.")
        return _res(MISMATCH, "NOT RENDERED — the expected value does not appear anywhere "
                              f"in this letter. Expected \"{expected[:70]}\".{extra}", NOT_PRESENT)
    return None


# ── letter <-> page pairing, per LETTER not per record ────────────

def pair_letters_to_pages(planned: list, pages: list) -> None:
    """Assigns each planned letter its own output page.

    Scored on HOW MANY of the letter's expected values appear on a page, not on one
    anchor being perfect. The single-anchor version picked whatever looked most
    distinctive in the addressee block — on a Suburban Propane run that was the
    bill-to address, which is exactly the field the composition renders wrong
    ("Amphitheatre" as "AMPHITEATER", country dropped). It matched nothing, all 2
    letters failed to pair, and 44 fields came back "no output text available".
    A tool whose job is to find defective values must not depend on a value being
    correct in order to find the page at all.

    Declared anchors and the addressee name still count triple, so an explicit
    anchor wins ties; the remaining evidence is every other expected value.

    Scaling: pages are normalised once and indexed by token, so candidate pages are
    looked up rather than scanned. Cost grows with the feed, not with its square.
    """
    n_pages = [norm(p) for p in pages]
    index = {}
    for pi, np_text in enumerate(n_pages):
        for tok in set(re.findall(r"[a-z0-9]+", np_text)):
            index.setdefault(tok, set()).add(pi)

    def pages_for(value: str):
        """Pages containing every token of `value` — a cheap candidate filter."""
        toks = re.findall(r"[a-z0-9]+", value)
        if not toks:
            return set()
        hit = None
        for t in toks:
            pset = index.get(t)
            if not pset:
                return set()
            hit = set(pset) if hit is None else (hit & pset)
            if not hit:
                return set()
        return hit or set()

    used = set()
    for L in planned:
        strong = [norm(a) for a in (list(L.get("anchor_values") or [])
                                    + [L.get("addressee_name"), L.get("policy_anchor")]) if a]
        strong = [a for a in strong if a]
        weak = [n for n in (norm(v) for v in (L.get("match_values") or [])) if len(n) >= 4]

        cands = set()
        for v in strong + weak:
            cands |= pages_for(v)
        if not cands:
            cands = set(range(len(pages)))

        best, best_score = None, 0
        for pi in sorted(cands):
            if pi in used:
                continue
            np_text = n_pages[pi]
            score = (3 * sum(1 for a in strong if a in np_text)
                     + sum(1 for v in weak if v in np_text))
            if score > best_score:
                best, best_score = pi, score
        if best is not None and best_score > 0:
            used.add(best)
            L["page_index"] = best
            L["output_text"] = pages[best]
            L["pair_score"] = best_score
        else:
            L["page_index"] = None
            L["output_text"] = ""
            L["pair_score"] = 0


def _ai_batch(bi, batch, out_text, rules, client, dbg):
    payload = [{"Field_Path": sid, "Field": nm, "Source_Value": str(exp)[:300]}
               for sid, nm, exp in batch]
    prompt = FIELD_COMPARE_PROMPT.format(
        mapping_rules=(rules or "NONE PROVIDED")[:6000],
        output_text=out_text[:14000], fields=json.dumps(payload, indent=2))
    dbg.add("info", "SLOT-COMPARE", f"AI batch {bi} — {len(batch)} slot(s)")
    try:
        result = client.run(prompt, dbg)
        by = {}
        for r in safe_json(result.get("text", ""), dbg):
            if isinstance(r, dict):
                st = str(r.get("Status", "")).strip().upper()
                by[r.get("Field_Path")] = {
                    "status": st if st in (MATCH, MISMATCH, NOT_VERIFIABLE) else MISMATCH,
                    "notes": str(r.get("Notes", "") or ""),
                    "output": str(r.get("Output_Value", "") or "")[:160], "by": "AI"}
        return by, {"input": result["input_tokens"], "output": result["output_tokens"],
                    "total": result["total_tokens"]}, None
    except Exception as e:
        err = classify_api_error(str(e), client.provider)
        dbg.add("err", "SLOT-COMPARE", f"AI batch {bi} failed: {err}", str(e)[:400])
        return {}, {"input": 0, "output": 0, "total": 0}, err


def run_spec_validation(spec: dict, records: list, pages: list, rules: str,
                        client=None, dbg=None, max_workers=4, progress_cb=None):
    """Returns (instances_payload, stats, usage, failed_batches)."""
    usage = {"input": 0, "output": 0, "total": 0}
    planned_all, id_field = [], (spec.get("record_id_field") or "policyId")

    for ri, rec in enumerate(records):
        for L in plan_letters(spec, rec):
            L["record_index"], L["record"] = ri, rec
            L["policy_anchor"] = str(rec.get(id_field, "") or "")
            planned_all.append(L)

    active = [L for L in planned_all if not L.get("skipped")]
    suppressed = [L for L in planned_all if L.get("skipped")]

    # Every value this letter should contain, computed before pairing because it
    # depends only on the record. Used both as pairing evidence and, later, to stop
    # a probe offering one field's value as evidence about another.
    letter_expected = {}
    for L in active:
        vals = []
        for slot in slots_for_letter(spec, L["id"]):
            try:
                for chk in slot_checks(slot, L["record"], L, spec):
                    v = str(chk.get("expected") or "").strip()
                    if v and v != ABSENT:
                        vals.append(v)
            except Exception:
                pass
        letter_expected[L["id"]] = tuple(vals)
        L["match_values"] = vals

    pair_letters_to_pages(active, pages)
    located = sum(1 for L in active if L.get("page_index") is not None)
    dbg.add("ok", "LETTER-PLAN",
            f"{len(records)} record(s) -> {len(active)} letter(s) expected "
            f"({len(suppressed)} suppressed by rule); {located} paired to an output page; "
            f"output has {len(pages)} page(s)")

    # ── deterministic pass ──
    prepared, unresolved = [], []
    for L in active:
        rows = []
        for slot in slots_for_letter(spec, L["id"]):
            if _is_label_leak(slot):
                rows.append((slot, {"label": slot.get("slot_name", ""), "expected": "",
                                    "why": "", "kind": "single"},
                             _res(NOT_VERIFIABLE,
                                  f"The BRD row \"{slot.get('slot_name', '')}\" names no text and no "
                                  f"data field, so there is nothing to verify. Its own label was read "
                                  f"as the expected value; that has been rejected.",
                                  "Not verifiable", "Out of scope"), True))
                continue
            if not slot.get("verifiable", True):
                rows.append((slot, {"label": slot.get("slot_name", ""), "expected": "",
                                    "why": "", "kind": "single"},
                             _res(NOT_VERIFIABLE,
                                  slot.get("not_verifiable_reason", "Not verifiable from these inputs."),
                                  "Not verifiable", "Out of scope"), True))
                continue
            for chk in slot_checks(slot, L["record"], L, spec):
                miss = chk.get("unresolved") or []
                if miss and not str(chk.get("expected") or "").strip():
                    # The mapping names fields this feed does not contain. Nothing
                    # can be compared, and calling it a pass would be a lie about
                    # coverage — the mapping and the data disagree, which is the
                    # finding worth reporting.
                    rows.append((slot, chk,
                                 _res(NOT_VERIFIABLE,
                                      "NOT CHECKED — the mapping names "
                                      + ", ".join(miss[:4])
                                      + (" and others" if len(miss) > 4 else "")
                                      + ", which do not exist in this source record. "
                                        "Fix the mapping or the feed before trusting coverage.",
                                      "No source field", "Out of scope"), True))
                    continue
                res = compare_slot(chk["expected"], L.get("output_text", ""), slot,
                                   others=letter_expected.get(L["id"], ()))
                rows.append((slot, chk, res, False))
                if res is None:
                    unresolved.append((L, slot, chk))
        prepared.append((L, rows))

    det = sum(1 for _, rows in prepared for _, _, r, _ in rows if r is not None)
    dbg.add("ok", "SLOT-COMPARE",
            f"Deterministic pass settled {det} slot-check(s); {len(unresolved)} need AI")

    # ── AI pass, batched per letter ──
    ai_by_letter, failed = {}, 0
    jobs = {}
    for L, slot, chk in unresolved:
        key = f"{slot.get('slot_id', slot.get('slot_name', '?'))}|{chk['label']}"
        jobs.setdefault(id(L), (L, []))[1].append((key, chk["label"], chk["expected"]))
    if jobs and client is not None:
        tasks = []
        for key, (L, items) in jobs.items():
            for bi, s in enumerate(range(0, len(items), SLOTS_PER_BATCH), start=1):
                tasks.append((bi, key, L, items[s:s + SLOTS_PER_BATCH]))
        done = 0
        with cf.ThreadPoolExecutor(max_workers=max(1, max_workers)) as ex:
            futs = {ex.submit(_ai_batch, bi, batch, L.get("output_text", ""), rules, client, dbg): key
                    for bi, key, L, batch in tasks}
            for f in cf.as_completed(futs):
                by, u, err = f.result()
                for k in usage:
                    usage[k] += u[k]
                ai_by_letter.setdefault(futs[f], {}).update(by)
                failed += bool(err)
                done += 1
                if progress_cb:
                    progress_cb(done, len(tasks))

    # ── assemble ──
    instances, unverified = [], 0
    for L, rows in prepared:
        got = ai_by_letter.get(id(L), {})
        out_rows = []
        for slot, chk, res, out_of_scope in rows:
            sid = slot.get("slot_id", slot.get("slot_name", "?"))
            key = f"{sid}|{chk['label']}"
            expected = chk["expected"]
            r = res or got.get(key)
            unv = res is None and key not in got and not out_of_scope
            if r is None:
                # A tool failure, not a verdict. It must not count as a pass, and it
                # must not be asserted as a defect either — it is excluded from the
                # pass rate and the run is marked INCOMPLETE by the unverified flag.
                r = _res(NOT_VERIFIABLE, "AI comparison unavailable for this slot — "
                                         "NOT CHECKED, needs a manual review.",
                         "Could not be determined", "AI")
            unverified += bool(unv)
            out_rows.append({
                "field": chk["label"],
                "field_path": f"{sid} · {slot.get('brd_ref', '')}".strip(" ·"),
                "source": ("(suppressed by rule)" if expected == ABSENT else expected),
                "expected": ("ABSENT — must not render" if expected == ABSENT else expected),
                "output": r.get("output", ""), "status": r["status"],
                "notes": r.get("notes", ""), "by": r.get("by", ""), "unverified": unv,
            })
        page = L.get("page_index")
        sub = (f"{L['label']} · "
               + (f"Output page {page + 1}" if page is not None else "NO MATCHING PAGE FOUND"))
        instances.append({
            "title": f"Record {L['record_index'] + 1} — {L.get('addressee_name') or L['label']}"
                     + (f" · {L['policy_anchor']}" if L.get("policy_anchor") else ""),
            "subtitle": sub, "rows": out_rows})

    for L in suppressed:
        instances.append({
            "title": f"Record {L['record_index'] + 1} — {L['label']} letter NOT generated",
            "subtitle": f"Correctly suppressed · {L.get('skip_reason', '')}",
            "rows": [{"field": f"{L['label']} letter", "field_path": "letter generation rule",
                      "source": "(suppressed by rule)", "expected": "ABSENT — must not be generated",
                      "output": "Not generated (as required)", "status": MATCH,
                      "notes": L.get("skip_reason", ""), "by": "Deterministic", "unverified": False}]})

    stats = {"records": len(records), "letters_expected": len(active),
             "letters_suppressed": len(suppressed), "instances_located": located,
             "output_pages": len(pages), "deterministic": det, "ai": len(unresolved),
             "unverified": unverified, "rules_provided": bool((rules or "").strip()),
             "slots": len(spec.get("slots") or []),
             "page_count_matches": located == len(pages) == len(active)}
    return instances, stats, usage, failed
