"""
Orchestration for Field Mapping Validation.

  1. Document Parsing   -> utils/extraction.py (called by the page)
  2. Instance Pairing   -> utils/field_mapping.pair_instances()
  3. Field Extraction   -> utils/field_mapping.flatten_record()
  4. Field Comparison   -> deterministic first (utils/field_compare), AI only
                           for what the rules could not resolve
  5. Findings & Summary -> deterministic rollup + one small AI summary call
  6. Report             -> utils/mapping_report.py

Every AI call is bounded to one document instance's text and a batch of
unresolved fields, so prompt size stays flat no matter how large the feed or
the output document is. A batch that fails degrades those fields to REVIEW
with a clean reason instead of sinking the run.
"""

import json
import re
import concurrent.futures as cf

from utils.json_utils import safe_json, safe_json_object
from utils.llm_client import classify_api_error
from utils.field_mapping import pair_instances, display_names, normalize_records
from utils.field_compare import compare_field, evidence_snippet, MATCH, MISMATCH, GAP, REVIEW

# Placeholder answers that carry no evidence — treated as "no quote supplied"
# so the snippet gets re-derived from the document instead.
_WEAK_OUTPUT = {"", "-", "—", "n/a", "na", "none", "yes", "no", "present",
                "rendered", "rendered in output", "ok", "correct", "match"}
from prompts.field_mapping_prompt import FIELD_COMPARE_PROMPT, MAPPING_SUMMARY_PROMPT

AGENT_DEFS = [
    {"key": "parsing", "icon": "document", "name": "1. Document Parsing",
     "desc": "Reads the source feed and the generated output, runs OCR where needed, splits both into records and pages."},
    {"key": "pairing", "icon": "map", "name": "2. Instance Pairing",
     "desc": "Locates the document each source record produced, by matching its identifier values against the output pages."},
    {"key": "fields", "icon": "database", "name": "3. Field Extraction",
     "desc": "Flattens every record into its mapped fields — the field list comes from the real feed, not a guessed spec."},
    {"key": "compare", "icon": "shield", "name": "4. Field Comparison",
     "desc": "Reconciles each field against its own document — exact, case, currency, date and absence resolve as rules; only transformed values go to AI."},
    {"key": "findings", "icon": "flask", "name": "5. Findings & Summary",
     "desc": "Rolls up mismatches and gaps, then writes the executive summary and recommendations."},
    {"key": "report", "icon": "chart", "name": "6. Report Generator",
     "desc": "Builds the field mapping validation report as PDF and HTML."},
]

# XML/JSON plumbing that is never a mapped business field. `_text` is the key
# utils.extraction._xml_to_dict() actually emits for an element carrying both
# attributes and text — an earlier version of this pattern looked for "#text"
# and therefore never matched.
_SKIP_LEAF = re.compile(r"^(@?xmlns.*|@?xsi.*|@schemaLocation|#text|_text)$", re.I)

OUTPUT_TEXT_CAP = 14000
FIELDS_PER_BATCH = 40


def new_zero_usage():
    return {"input": 0, "output": 0, "total": 0}


def _is_reportable(path: str) -> bool:
    return not _SKIP_LEAF.match(path.split("/")[-1])


def _compare_batch_task(bi, inst_idx, batch, output_text, mapping_rules, client, dbg):
    """One AI comparison call for a batch of unresolved fields in one instance.

    `batch` items are (path, label, value, mechanical_finding) — the finding is
    "ABSENT" for fields the rules already proved missing, so the model spends
    its judgement on WHY they are missing rather than searching again."""
    fields_payload = []
    for p, lbl, v, finding in batch:
        entry = {"Field_Path": p, "Field": lbl, "Source_Value": (v[:300] if v else "")}
        if finding:
            entry["Mechanical_Finding"] = finding
        fields_payload.append(entry)
    prompt = FIELD_COMPARE_PROMPT.format(
        mapping_rules=(mapping_rules or "NONE PROVIDED")[:6000],
        output_text=output_text[:OUTPUT_TEXT_CAP],
        fields=json.dumps(fields_payload, indent=2),
    )
    dbg.add("info", "FIELD-COMPARE",
            f"Instance {inst_idx + 1} batch {bi} — {len(batch)} field(s), prompt {len(prompt):,} chars")
    try:
        result = client.run(prompt, dbg)
        parsed = [r for r in safe_json(result.get("text", ""), dbg) if isinstance(r, dict)]
        usage = {"input": result["input_tokens"], "output": result["output_tokens"],
                 "total": result["total_tokens"]}
        by_path = {}
        for r in parsed:
            st = str(r.get("Status", "")).strip().upper()
            if st not in (MATCH, MISMATCH, GAP, REVIEW):
                st = REVIEW
            by_path[r.get("Field_Path")] = {"status": st, "notes": str(r.get("Notes", "") or ""),
                                            "output": str(r.get("Output_Value", "") or "")[:160],
                                            "by": "AI"}
        return by_path, usage, None
    except Exception as e:
        err = classify_api_error(str(e), client.provider)
        dbg.add("err", "FIELD-COMPARE", f"Instance {inst_idx + 1} batch {bi} failed: {err}", str(e)[:600])
        return {}, new_zero_usage(), err


def run_field_mapping_validation(records, pages, mapping_rules, client, dbg,
                                  include_empty=False, max_workers=4, progress_cb=None):
    """Returns (instances_payload, stats, usage_total, failed_batches)."""
    records, unstructured = normalize_records(records)
    if unstructured:
        dbg.add("warn", "FIELD-EXTRACTION",
                f"{unstructured} of {len(records)} record(s) carry no field structure "
                f"(Print Image / no record layout supplied) — field mapping cannot be "
                f"performed on those")

    instances = pair_instances(records, pages)
    located = sum(1 for i in instances if i.found_in_output)
    dbg.add("ok", "INSTANCE-PAIRING",
            f"{len(instances)} source record(s) → {located} located in output "
            f"({len(pages)} output page(s))")

    # ── Deterministic pass ──
    # A deterministic MATCH is final: a value found verbatim (or reformatted) is
    # genuinely rendered, and no business rule can make that untrue.
    #
    # A deterministic GAP is only PROVISIONAL. The rules can see that a value is
    # missing, but not whether the BRD/mapping spec intended it to be missing —
    # a conditional section whose condition wasn't met, or a field the spec says
    # is never printed. So when rules context exists, GAPs are re-checked by the
    # AI pass against those rules before being reported as defects. Without any
    # rules there is nothing to adjudicate against, so the GAP stands and the
    # caller warns the user.
    adjudicate_gaps = bool((mapping_rules or "").strip())

    prepared = []      # per instance: list of (path, label, value, resolved_or_None, finding)
    excluded_empty = 0
    truncated_any = False
    provisional_gaps = 0
    for inst in instances:
        pairs = [(p, v) for p, v in inst.pairs if _is_reportable(p)]
        if not include_empty:
            before = len(pairs)
            pairs = [(p, v) for p, v in pairs if str(v).strip() != ""]
            excluded_empty += before - len(pairs)
        names = display_names([p for p, _ in pairs])
        rows = []
        for p, v in pairs:
            label = names.get(p, p.split("/")[-1])
            res = compare_field(v, inst.output_text, label)
            finding = ""
            if res is not None and res["status"] == GAP and adjudicate_gaps:
                finding = "ABSENT"        # hand to AI to judge whether a rule explains it
                provisional_gaps += 1
                res = None
            rows.append((p, label, v, res, finding))
        prepared.append(rows)
        truncated_any = truncated_any or inst.truncated

    det_count = sum(1 for rows in prepared for r in rows if r[3] is not None)
    unresolved = [(ii, [(p, lbl, v, finding) for p, lbl, v, res, finding in rows if res is None])
                  for ii, rows in enumerate(prepared)]
    ai_total = sum(len(u) for _, u in unresolved)
    dbg.add("ok", "FIELD-COMPARE",
            f"Deterministic pass resolved {det_count} field(s) instantly, for free — "
            f"{ai_total} require AI reasoning"
            + (f" (including {provisional_gaps} absent field(s) sent for rule adjudication)"
               if provisional_gaps else ""))
    if not adjudicate_gaps:
        dbg.add("warn", "FIELD-COMPARE",
                "No BRD or mapping rules provided — absent fields are reported as gaps without "
                "checking whether a business rule intended them to be suppressed.")

    # ── AI pass, batched per instance and dispatched concurrently ──
    usage_total = new_zero_usage()
    failed_batches = 0
    ai_results: dict = {}

    jobs = []
    for ii, fields in unresolved:
        for bi, start in enumerate(range(0, len(fields), FIELDS_PER_BATCH), start=1):
            jobs.append((bi, ii, fields[start:start + FIELDS_PER_BATCH]))

    if jobs:
        completed = 0
        with cf.ThreadPoolExecutor(max_workers=max(1, max_workers)) as ex:
            futures = {ex.submit(_compare_batch_task, bi, ii, batch,
                                 instances[ii].output_text, mapping_rules, client, dbg): ii
                       for bi, ii, batch in jobs}
            for fut in cf.as_completed(futures):
                ii = futures[fut]
                by_path, usage, err = fut.result()
                for k in usage_total:
                    usage_total[k] += usage[k]
                ai_results.setdefault(ii, {}).update(by_path)
                if err:
                    failed_batches += 1
                completed += 1
                if progress_cb:
                    progress_cb(completed, len(jobs))

    # ── Assemble instance payloads ──
    instances_payload = []
    for ii, (inst, rows) in enumerate(zip(instances, prepared)):
        got = ai_results.get(ii, {})
        out_rows = []
        for p, lbl, v, res, finding in rows:
            r = res or got.get(p)
            unverified = r is None      # its AI call never returned a verdict
            if r is None:
                # Its batch failed outright. For a field already proven absent,
                # fall back to the mechanical GAP rather than losing the finding;
                # otherwise say plainly that it needs a manual check.
                if finding == "ABSENT":
                    r = {"status": GAP, "by": "Deterministic", "output": "Not present in output",
                         "notes": "Present in source but not rendered in the output. Rule "
                                  "adjudication unavailable — confirm no business rule suppresses it."}
                else:
                    r = {"status": REVIEW, "by": "AI", "output": "Could not be determined",
                         "notes": "AI comparison unavailable for this field — needs a manual check."}
            # The model is asked to quote the document, but if it returned a
            # verdict without a quote (or something useless like "rendered"),
            # re-derive the real snippet mechanically. The report's Output Value
            # column should hold document text, never a generic phrase.
            out_val = str(r.get("output") or "").strip()
            if not out_val or out_val.lower().strip(" .") in _WEAK_OUTPUT:
                out_val = evidence_snippet(v, inst.output_text) or _output_hint(r["status"])

            out_rows.append({
                "field": lbl,
                "field_path": p,
                "source": v,
                "output": out_val,
                "status": r["status"],
                "notes": r.get("notes", ""),
                "by": r.get("by", ""),
                "unverified": unverified,
            })
        subtitle = f"{inst.page_label}"
        if inst.truncated:
            subtitle += f" · field list capped at {len(inst.pairs)} leaves"
        if not inst.found_in_output:
            subtitle += " · no matching document found — every field reported as a gap"
        instances_payload.append({"title": inst.label, "subtitle": subtitle, "rows": out_rows})

    unverified_total = sum(1 for inst in instances_payload
                           for r in inst["rows"] if r.get("unverified"))
    if unverified_total:
        dbg.add("err", "FIELD-COMPARE",
                f"{unverified_total} field(s) have NO verdict — their AI call failed. "
                f"These are reported as unverified, not as findings.")

    stats = {"records": len(instances), "instances_located": located,
             "deterministic": det_count, "ai": ai_total,
             "excluded_empty": excluded_empty, "truncated": truncated_any,
             "output_pages": len(pages), "rules_provided": adjudicate_gaps,
             "adjudicated_gaps": provisional_gaps,
             "unstructured": unstructured, "unverified": unverified_total}
    return instances_payload, stats, usage_total, failed_batches


def _output_hint(status: str) -> str:
    """Last resort, only when no snippet could be quoted or re-derived. Worded so
    it can never be mistaken for the document's actual text, and never
    fabricates a value."""
    return {
        MATCH: "(rendered — exact text not captured)",
        MISMATCH: "(rendered but does not reconcile — exact text not captured)",
        GAP: "Not present in output",
        REVIEW: "Could not be determined",
    }.get(status, "—")


def build_findings(instances_payload: list, limit: int = 40) -> list:
    """Turns every failing row into a Key Findings bullet.

    There is one severity now. A field that does not render its source value in
    full is a failure, so the list is not ranked into softer tiers — sorting a
    dropped address line below a wrong amount only invited someone to stop reading
    partway down."""
    from utils.mapping_report import _norm_status
    items = []
    for inst in instances_payload:
        for r in inst["rows"]:
            if _norm_status(r.get("status")) != "FAIL":
                continue
            # Out-of-scope slots (logos, barcodes) are listed once in the
            # not-verifiable section — repeating them per letter buries the
            # findings that actually need attention.
            if r.get("by") == "Out of scope":
                continue
            note = r.get("notes") or ""
            want = r.get("expected") or r.get("source")
            items.append((0, {
                "type": "Failure",
                "text": f"{r['field']} ({inst['title'].split('—')[0].strip()}) — "
                        f"expected \"{str(want)[:70]}\". {note}".strip(),
            }))
    items.sort(key=lambda t: t[0])
    return [d for _, d in items[:limit]]


def run_summary_agent(payload_meta: dict, instances_payload: list, findings: list, client, dbg,
                      stats: dict | None = None):
    """One small call for narrative + assessment + recommendations. Falls back to
    a deterministic summary if it fails — the report must still build."""
    from utils.mapping_report import _rollup
    roll = _rollup({"instances": instances_payload})
    unverified = sum(1 for inst in instances_payload for r in inst["rows"] if r.get("unverified"))
    fallback = _fallback_summary(roll, unverified, stats or {})

    # If fields went unverified the run is incomplete, and no AI-written prose
    # may paper over that — the computed INCOMPLETE assessment stands.
    # An incomplete run, or one where nothing paired, must keep its computed
    # wording — there is no narrative worth generating about a run that did not
    # compare anything.
    if unverified or not findings or (stats or {}).get("instances_located") == 0:
        return fallback, new_zero_usage()

    prompt = MAPPING_SUMMARY_PROMPT.format(
        source_file=payload_meta.get("source_file", "—"),
        output_file=payload_meta.get("output_file", "—"),
        record_count=payload_meta.get("record_count", "—"),
        instance_count=len(instances_payload),
        field_count=roll["checked"], matches=roll["PASS"], mismatches=roll["FAIL"],
        gaps=0, reviews=roll["NOT VERIFIABLE"],
        findings=json.dumps(findings[:30], indent=2),
    )
    dbg.add("info", "SUMMARY-AGENT", f"Summarising {len(findings)} finding(s)")
    try:
        result = client.run(prompt, dbg)
        obj = safe_json_object(result.get("text", ""), dbg)
        if not obj:
            raise ValueError("summary agent did not return a usable object")
        usage = {"input": result["input_tokens"], "output": result["output_tokens"],
                 "total": result["total_tokens"]}
        out = {
            "narrative": str(obj.get("narrative") or fallback["narrative"]),
            # The verdict is arithmetic, never prose. Left to the model it produced
            # "PASS WITH FINDINGS" over a run containing a wrong premium amount and
            # a wrong sales-rep name. One failing field fails the run.
            "assessment": fallback["assessment"],
            "recommendations": [str(r) for r in (obj.get("recommendations") or [])
                                 if str(r).strip()] or fallback["recommendations"],
        }
        dbg.add("ok", "SUMMARY-AGENT", "Executive summary generated")
        return out, usage
    except Exception as e:
        dbg.add("warn", "SUMMARY-AGENT",
                f"Summary generation failed ({classify_api_error(str(e), client.provider)}) — "
                f"using a computed summary instead")
        return fallback, new_zero_usage()


def _fallback_summary(roll: dict, unverified: int = 0, stats: dict | None = None) -> dict:
    """The computed verdict. Binary by design.

    A mapped field either renders its source value in full or it does not. If any
    field does not, the run FAILED — a half-rendered address is a defect whether it
    is one field or fifty, and no percentage of passes offsets it. Rows the inputs
    cannot answer are excluded from the rate and reported separately, never as
    passes.
    """
    f, p, nv = roll["FAIL"], roll["PASS"], roll["NOT VERIFIABLE"]
    checked, rate = roll["checked"], roll["pass_rate"]
    stats = stats or {}

    # If no record could be paired to an output page, nothing was compared against
    # anything. Reporting a pass rate then is worse than useless: one real run
    # printed "97.3% pass" with 0 of 4 instances located, because a field whose
    # expected value was empty counted as a pass without an output to check.
    located = stats.get("instances_located")
    expected_docs = stats.get("letters_expected")
    if located == 0 and expected_docs:
        return {
            "narrative": (f"No comparison was performed. {expected_docs} document(s) were expected "
                          f"from the source feed, but none could be matched to a page in the output "
                          f"file, so no field had an output value to be checked against."),
            "assessment": ("INCOMPLETE — 0 of "
                           f"{expected_docs} expected document(s) could be matched to a page in the "
                           f"output. No field was actually compared, so this run carries no verdict. "
                           f"Check that the output file corresponds to this source feed, and that "
                           f"the record grain is right — a feed split into the wrong records cannot "
                           f"pair to anything."),
            "recommendations": [
                "Confirm the output PDF was generated from this exact source feed.",
                "Check the record count in the debug log against the feed's own trailer count — if "
                "they disagree, the feed is being split at the wrong level.",
                "Review the Mapping Spec: if its addressee block cannot be resolved, there is no "
                "anchor value to pair a record to a page.",
            ],
        }

    if unverified:
        total = roll["fields"]
        pct = round(unverified / total * 100) if total else 0
        return {
            "narrative": (f"This run did not complete. Of {total} mapped field(s), "
                          f"{total - unverified} were compared and {unverified} were left "
                          f"unverified after their AI comparison call failed. Within those "
                          f"checked: {p} passed, {f} failed."),
            "assessment": (f"INCOMPLETE — {unverified} of {total} field(s) ({pct}%) were never "
                           f"verified because their AI comparison call failed. Do not sign off; "
                           f"re-run with fewer parallel requests or a provider that is not "
                           f"rate-limited."),
            "recommendations": [
                "Re-run this validation before drawing any conclusion — some fields carry no verdict.",
                "Lower Parallel requests in Advanced options, or switch to a provider without a "
                "free-tier daily cap, to avoid the rate limit that caused the failures."],
        }

    if f:
        assessment = (f"FAIL — {f} of {checked} checked field(s) do not render their source value "
                      f"in full. Pass rate {rate:.1f}%. Every failure is listed below with the "
                      f"source value, what rendered, and what is missing.")
        narrative = (f"{checked} mapped field(s) were reconciled between the source feed and the "
                     f"generated output. {p} rendered the source value in full; {f} did not — "
                     f"missing, incomplete, or a different value. "
                     + (f"{nv} field(s) could not be verified from these inputs and are excluded "
                        f"from the rate." if nv else ""))
    else:
        assessment = (f"PASS — all {checked} checked field(s) render their source value in full."
                      + (f" {nv} field(s) could not be verified from these inputs and are listed "
                         f"separately." if nv else ""))
        narrative = (f"{checked} mapped field(s) were reconciled between the source feed and the "
                     f"generated output and all of them rendered in full. "
                     + (f"{nv} field(s) are not verifiable from these inputs — the BRD names no "
                        f"text or data field for them, or they are not text — and are excluded "
                        f"from the pass rate." if nv else ""))
    return {
        "narrative": narrative,
        "assessment": assessment,
        "recommendations": ["Review each FAIL in the detail tables below with the "
                            "mapping owner to confirm whether it is a defect or an intended rule."],
    }
