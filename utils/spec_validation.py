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
from utils.field_compare import (MATCH, MISMATCH, GAP, REVIEW, norm, _norm_map,
                                 _best_span, _snippet, _tokens, _best_line, NOT_PRESENT)
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


def _shape_probe(expected: str, out: str, fmt: str):
    """A competing value of the same shape as the expected one — the actual text
    for a wrong-value defect."""
    rx = SHAPES.get((fmt or "").lower())
    if not rx:
        return None
    want = norm(expected)
    for m in rx.finditer(out):
        if norm(m.group()) != want:
            return {"found": m.group().strip(), "snippet": _snippet(out, m.start(), m.end())}
    return None


def compare_slot(expected, out: str, slot: dict):
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
        return _res(GAP, "No output text available for this letter.", NOT_PRESENT)

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

    # 3. Multi-token values (addresses, names) are scored on TOKEN presence before
    #    any truncation claim. A rendered "321 N 76TH STREET, OMAHA, NE 68114-3627"
    #    is a standardised form of "321 N 76th St, Omaha, NE 68114", not a
    #    truncation — but its normalised text does not match contiguously, so a
    #    prefix probe run first would wrongly report it as cut short.
    toks = _tokens(expected)
    if len(toks) >= 2:
        missing = [t for t in toks if norm(t) not in n_out]
        ratio = 1 - (len(missing) / len(toks))
        line, _ = _best_line(out, toks)
        if not missing:
            return _res(MATCH, "Rendered with formatting differences.",
                        line or "Rendered in output")
        if ratio >= 0.5:
            # Most of the value is there but part of it is not — name the missing
            # piece rather than guessing whether it is a defect or a standardisation.
            return _res(REVIEW,
                        f"Rendered, but {len(missing)} of {len(toks)} part(s) not found: "
                        f"{', '.join(missing[:4])}. Expected \"{expected[:70]}\".",
                        line or "Rendered in output")

    # 4. Truncated — a long leading chunk is rendered and the rest is absent.
    tr = _truncation_probe(expected, out)
    if tr:
        return _res(MISMATCH,
                    f"Rendered but TRUNCATED — only {tr['kept']} of {tr['total']} characters "
                    f"appear. Expected \"{expected[:70]}\".", tr["snippet"])

    # 5. Wrong value — something of the same shape is rendered instead.
    sh = _shape_probe(expected, out, fmt)
    if sh:
        return _res(MISMATCH,
                    f"Rendered value does not reconcile — expected \"{expected}\", "
                    f"found \"{sh['found']}\".", sh["snippet"])

    if len(toks) >= 2:
        return _res(GAP, "Expected value does not appear anywhere in this letter.", NOT_PRESENT)

    if len(n_exp) >= 5:
        return _res(GAP, "Expected value does not appear anywhere in this letter.", NOT_PRESENT)
    return None


# ── letter <-> page pairing, per LETTER not per record ────────────

def pair_letters_to_pages(planned: list, pages: list) -> None:
    """Assigns each planned letter its own output page.

    Pairing on the letter's own addressee name is what keeps the control letter
    and the Payor letter separate — validating them as one merged blob is how
    a payor field could previously 'match' text belonging to the owner letter."""
    used = set()
    for L in planned:
        anchors = [a for a in [L.get("addressee_name"), L.get("policy_anchor")] if a]
        best, best_score = None, 0
        for pi, ptext in enumerate(pages):
            if pi in used:
                continue
            np = norm(ptext)
            score = sum(2 if norm(a) and norm(a) in np else 0 for a in anchors)
            if score > best_score:
                best, best_score = pi, score
        if best is not None and best_score > 0:
            used.add(best)
            L["page_index"] = best
            L["output_text"] = pages[best]
        else:
            L["page_index"] = None
            L["output_text"] = ""


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
                    "status": st if st in (MATCH, MISMATCH, GAP, REVIEW) else REVIEW,
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
            if not slot.get("verifiable", True):
                rows.append((slot, {"label": slot.get("slot_name", ""), "expected": "",
                                    "why": "", "kind": "single"},
                             _res(REVIEW,
                                  slot.get("not_verifiable_reason", "Not verifiable from these inputs."),
                                  "Not verifiable", "Out of scope"), True))
                continue
            for chk in slot_checks(slot, L["record"], L, spec):
                res = compare_slot(chk["expected"], L.get("output_text", ""), slot)
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
                r = _res(REVIEW, "AI comparison unavailable for this slot — needs a manual check.",
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
