"""
Agent orchestration for the QA Validation pipeline.

  1. Document Parsing Agent  -> utils/extraction.py (called directly by the page)
  2. BRD Agent                -> run_brd_agent()
  3. Requirement Store        -> RequirementStore (utils/requirement_store.py)
  4. Validation Agent         -> run_validation_agent()
  5. Evidence Agent           -> folded into retrieval + validation (the
                                  retrieved chunks ARE the evidence)
  6. Reviewer Agent           -> run_reviewer_agent()
  7. Report Generator         -> utils/report_export.py + build_executive_summary()

Every agent call is deliberately kept small and bounded (batched requirements,
retrieved-not-whole-file evidence) so the pipeline stays reliable even when
the Data file or Output document is huge.
"""

import json
import concurrent.futures as cf

from utils.json_utils import safe_json
from utils.llm_client import classify_api_error
from utils.requirement_store import RequirementStore
from utils.retrieval import data_records_to_chunks, output_pages_to_chunks, retrieve, render_chunks
from utils.deterministic_checks import try_deterministic
from prompts.brd_agent_prompt import BRD_AGENT_PROMPT
from prompts.validation_agent_prompt import VALIDATION_AGENT_PROMPT
from prompts.reviewer_prompt import REVIEWER_PROMPT

AGENT_DEFS = [
    {"key": "parsing", "icon": "document", "name": "1. Document Parsing Agent",
     "desc": "Reads all uploaded files, runs OCR where needed, detects document type, extracts structured content."},
    {"key": "brd", "icon": "layers", "name": "2. BRD Agent",
     "desc": "Extracts business requirements and rules, identifies input/output fields and calculations, assigns Requirement IDs."},
    {"key": "store", "icon": "database", "name": "3. Requirement Store",
     "desc": "Builds the structured, addressable requirement list every later agent works from."},
    {"key": "validation", "icon": "shield", "name": "4. Validation Agent",
     "desc": "For each requirement, retrieves relevant Data + Output evidence and validates mapping, rules, calculations, formatting — batches run in parallel."},
    {"key": "evidence", "icon": "search", "name": "5. Evidence Agent",
     "desc": "Packages the input record, output value, BRD section, and calculation behind every result."},
    {"key": "reviewer", "icon": "flask", "name": "6. Reviewer Agent",
     "desc": "Audits results for coverage gaps, duplicates, low confidence, contradictions, and hallucinated evidence."},
    {"key": "report", "icon": "chart", "name": "7. Report Generator",
     "desc": "Builds the executive summary, coverage stats, risks, and the detailed PDF/HTML validation report."},
]


def new_zero_usage():
    return {"input": 0, "output": 0, "total": 0}


# ── 2. BRD Agent ────────────────────────────────────────────────

def run_brd_agent(brd_text, mapping_text, client, dbg):
    prompt = BRD_AGENT_PROMPT.format(brd=brd_text, mapping=mapping_text or "NO MAPPING PROVIDED")
    dbg.add("info", "BRD-AGENT", f"Prompt assembled — {len(prompt):,} chars")
    result = client.run(prompt, dbg)
    raw = safe_json(result.get("text", ""), dbg)
    store = RequirementStore.from_raw(raw)
    dbg.add("ok", "BRD-AGENT", f"Requirement Store built — {len(store)} requirement(s)")
    return store, result


# ── 4/5. Validation Agent + Evidence Agent (retrieval-backed) ───

def _dedup_chunks(chunks):
    seen, out = set(), []
    for c in chunks:
        if c.ref not in seen:
            seen.add(c.ref)
            out.append(c)
    return out


def _validation_batch_task(bi, batch, data_chunks, output_chunks, client, dbg):
    """Builds the retrieval context and runs one Validation Agent batch call.
    Returns a result even on failure — a failed batch degrades to a
    per-requirement "Warning" instead of aborting the whole pipeline, since
    with concurrent batches a single rate-limited call shouldn't sink an
    otherwise-successful run."""
    per_req_data, per_req_output = {}, {}
    for req in batch:
        kws = req.keywords
        per_req_data[req.id] = retrieve(data_chunks, kws, top_k=4)
        per_req_output[req.id] = retrieve(output_chunks, kws, top_k=3)

    combined_data = _dedup_chunks([c for lst in per_req_data.values() for c in lst])
    combined_output = _dedup_chunks([c for lst in per_req_output.values() for c in lst])

    req_json = json.dumps([r.to_dict() for r in batch], indent=2)
    prompt = VALIDATION_AGENT_PROMPT.format(
        requirements=req_json,
        data_evidence=render_chunks(combined_data),
        output_evidence=render_chunks(combined_output),
    )
    dbg.add("info", "VALIDATION-AGENT", f"Batch {bi} — {len(batch)} requirement(s), prompt {len(prompt):,} chars")

    try:
        result = client.run(prompt, dbg)
        parsed = safe_json(result.get("text", ""), dbg)
        usage = {"input": result["input_tokens"], "output": result["output_tokens"], "total": result["total_tokens"]}
        error = None
    except Exception as e:
        parsed, usage = [], new_zero_usage()
        error = classify_api_error(str(e), client.provider)
        dbg.add("err", "VALIDATION-AGENT", f"Batch {bi} failed: {error}", str(e)[:600])

    # Combined (not per-requirement) evidence — this is what the model
    # actually saw in the shared batch prompt, so the Reviewer Agent's
    # hallucination check compares against the real context, not a
    # narrower slice that would flag genuine batch-shared evidence as
    # invented.
    batch_evidence_text = render_chunks(combined_data + combined_output)

    by_id = {p.get("Requirement_ID"): p for p in parsed if isinstance(p, dict)}
    entries, evidence = {}, {}
    for req in batch:
        r = by_id.get(req.id) or {}
        ev = r.get("Evidence") or {}
        entries[req.id] = {
            "Requirement_ID": req.id,
            "Requirement_Text": req.text,
            "Business_Rule": req.business_rule,
            "Validation_Type": req.validation_type,
            "Status": (r.get("Status") if not error else "Warning") or "Not Applicable",
            "Confidence": (r.get("Confidence", 0) if not error else 0),
            "Reason": (r.get("Reason") if not error else
                       f"Validation Agent call failed for this batch ({error}) — needs a manual re-check.")
                      or "No result returned by the Validation Agent for this requirement.",
            "Evidence": {"BRD Section": req.brd_section or "—", **{k: v for k, v in ev.items() if v}},
            "Validated_By": "AI",
        }
        evidence[req.id] = batch_evidence_text
    return entries, evidence, usage, error


def run_validation_agent(store, data_records, output_pages, client, dbg, batch_size=100, max_workers=4, progress_cb=None):
    """Hybrid validation: attempts a deterministic (non-AI) resolution for
    every requirement FIRST — instant, free, and exact for Field Presence /
    Format / Calculation checks with confidently-resolved evidence. Only
    requirements that genuinely need reasoning (Business Rule, Conditional
    Logic, Mapping, or a mechanical check whose evidence couldn't be
    confidently resolved) go to the AI Validation Agent, batched and
    dispatched concurrently (thread pool) so those calls aren't sequential
    either."""
    data_chunks = data_records_to_chunks(data_records)
    output_chunks = output_pages_to_chunks(output_pages)

    results_by_req = {}
    evidence_pool = {}
    needs_ai = []

    for req in store:
        kws = req.keywords
        req_data = retrieve(data_chunks, kws, top_k=4)
        req_output = retrieve(output_chunks, kws, top_k=3)
        evidence_pool[req.id] = render_chunks(req_data + req_output)

        det = try_deterministic(req, req_data, req_output)
        if det is not None:
            results_by_req[req.id] = {
                "Requirement_ID": req.id,
                "Requirement_Text": req.text,
                "Business_Rule": req.business_rule,
                "Validation_Type": req.validation_type,
                "Status": det.get("Status", "Not Applicable"),
                "Confidence": det.get("Confidence", 100),
                "Reason": det.get("Reason", ""),
                "Evidence": {"BRD Section": req.brd_section or "—", **(det.get("Evidence") or {})},
                "Validated_By": "Deterministic",
            }
        else:
            needs_ai.append(req)

    deterministic_count = len(results_by_req)
    dbg.add("ok", "VALIDATION-AGENT",
            f"Deterministic pass resolved {deterministic_count}/{len(store)} requirement(s) instantly, "
            f"for free — {len(needs_ai)} require AI reasoning")

    usage_total = new_zero_usage()
    failed_batches = 0

    if needs_ai:
        ai_batches = [needs_ai[i:i + batch_size] for i in range(0, len(needs_ai), batch_size)]
        completed = 0
        with cf.ThreadPoolExecutor(max_workers=max(1, max_workers)) as executor:
            futures = [executor.submit(_validation_batch_task, bi, batch, data_chunks, output_chunks, client, dbg)
                       for bi, batch in enumerate(ai_batches, start=1)]
            for future in cf.as_completed(futures):
                entries, evidence, usage, error = future.result()
                usage_total["input"] += usage["input"]
                usage_total["output"] += usage["output"]
                usage_total["total"] += usage["total"]
                results_by_req.update(entries)
                evidence_pool.update(evidence)
                if error:
                    failed_batches += 1
                completed += 1
                if progress_cb:
                    progress_cb(completed, len(ai_batches))

    # Note: every requirement always gets an entry — deterministic results,
    # successful AI results, or (if its batch's API call failed outright) a
    # "Warning" placeholder with a clean reason (see _validation_batch_task).
    # So even a total API outage still returns a complete, honest report
    # instead of throwing everything away; `failed_batches` below tells the
    # caller how many batches to warn the user about.
    all_results = [results_by_req[req.id] for req in store if req.id in results_by_req]
    dbg.add("ok", "VALIDATION-AGENT",
            f"Validated {len(all_results)} requirement(s) total — {deterministic_count} deterministic, "
            f"{len(needs_ai)} via AI ({max_workers}x parallel, {failed_batches} batch failure(s))")
    return all_results, evidence_pool, usage_total, failed_batches, deterministic_count


# ── 6. Reviewer Agent ────────────────────────────────────────────

def _reviewer_batch_task(bi, batch, evidence_pool, client, dbg):
    ev_subset = {r["Requirement_ID"]: evidence_pool.get(r["Requirement_ID"], "") for r in batch}
    prompt = REVIEWER_PROMPT.format(
        results=json.dumps(batch, indent=2),
        evidence=json.dumps(ev_subset, indent=2),
    )
    dbg.add("info", "REVIEWER-AGENT", f"Auditing batch {bi} — {len(batch)} result(s)")
    try:
        result = client.run(prompt, dbg)
        usage = {"input": result["input_tokens"], "output": result["output_tokens"], "total": result["total_tokens"]}
        issues = [i for i in safe_json(result.get("text", ""), dbg) if isinstance(i, dict)]
    except Exception as e:
        err_type = classify_api_error(str(e), client.provider)
        dbg.add("err", "REVIEWER-AGENT", f"Audit batch {bi} failed: {err_type} — skipping this batch's audit",
                str(e)[:600])
        usage, issues = new_zero_usage(), []
    return issues, usage


def run_reviewer_agent(store, results, evidence_pool, client, dbg, batch_size=100, max_workers=4):
    """Programmatic QA checks (coverage, duplicates, low confidence) run
    first — free and deterministic, so they always succeed even if the LLM
    audit pass below has trouble. The LLM pass then checks batches of
    results for contradictions and hallucinated evidence CONCURRENTLY — a
    batch that fails (e.g. rate limit) just contributes no issues rather
    than aborting the whole Reviewer stage, since the programmatic checks
    already computed above are the more load-bearing part of this agent."""
    issues = []

    validated_ids = {r["Requirement_ID"] for r in results}
    for rid in [req.id for req in store if req.id not in validated_ids]:
        issues.append({"Requirement_ID": rid, "Issue_Type": "Missing Validation",
                        "Description": "This requirement has no validation result.",
                        "Recommended_Action": "Re-run the Validation Agent for this requirement."})

    dup_groups = store.find_duplicates()
    for group in dup_groups:
        issues.append({"Requirement_ID": ", ".join(group), "Issue_Type": "Duplicate Requirement",
                        "Description": "These requirement IDs have near-identical text and may be redundant.",
                        "Recommended_Action": "Confirm with the BRD author whether these should be merged."})

    low_conf = [r for r in results if isinstance(r.get("Confidence"), (int, float))
                and r["Confidence"] < 40 and r.get("Status") in ("Pass", "Fail")]
    for r in low_conf:
        issues.append({"Requirement_ID": r["Requirement_ID"], "Issue_Type": "Low Confidence",
                        "Description": f"Result marked \"{r['Status']}\" with only {r['Confidence']}% confidence.",
                        "Recommended_Action": "Manually review before sign-off."})

    dbg.add("info", "REVIEWER-AGENT",
            f"Programmatic checks — {len(store) - len(validated_ids)} missing, "
            f"{len(dup_groups)} duplicate group(s), {len(low_conf)} low-confidence")

    usage_total = new_zero_usage()
    # Deterministic results are correct by construction (exact code, not a
    # guess) — auditing them for "hallucinated evidence" would just spend AI
    # tokens re-checking arithmetic. Only AI-reasoned results need this pass.
    scored = [r for r in results if r.get("Status") in ("Pass", "Fail") and r.get("Validated_By") != "Deterministic"]
    batches = [scored[i:i + batch_size] for i in range(0, len(scored), batch_size)]

    if batches:
        with cf.ThreadPoolExecutor(max_workers=max(1, max_workers)) as executor:
            futures = [executor.submit(_reviewer_batch_task, bi, batch, evidence_pool, client, dbg)
                       for bi, batch in enumerate(batches, start=1)]
            for future in cf.as_completed(futures):
                batch_issues, usage = future.result()
                usage_total["input"] += usage["input"]
                usage_total["output"] += usage["output"]
                usage_total["total"] += usage["total"]
                issues.extend(batch_issues)

    dbg.add("ok", "REVIEWER-AGENT", f"Review complete — {len(issues)} total issue(s) flagged")
    return issues, usage_total


# ── 7. Report Generator support ─────────────────────────────────

def build_executive_summary(store, results, issues, deterministic_count=0) -> dict:
    total = len(store)
    passed = sum(1 for r in results if r.get("Status") == "Pass")
    failed = sum(1 for r in results if r.get("Status") == "Fail")
    warning = sum(1 for r in results if r.get("Status") == "Warning")
    na = sum(1 for r in results if r.get("Status") == "Not Applicable")
    scored = total - na
    pass_rate = round((passed / scored) * 100, 1) if scored > 0 else 0.0
    confidences = [r.get("Confidence", 0) for r in results if isinstance(r.get("Confidence"), (int, float))]
    avg_confidence = round(sum(confidences) / len(confidences), 1) if confidences else 0.0
    missing = [i for i in issues if i.get("Issue_Type") == "Missing Validation"]
    return {
        "total_requirements": total, "passed": passed, "failed": failed,
        "warning": warning, "not_applicable": na, "pass_rate": pass_rate,
        "avg_confidence": avg_confidence, "reviewer_issues": len(issues),
        "missing_requirements": len(missing), "critical_risks": failed,
        "deterministic_count": deterministic_count,
        "ai_count": max(0, len(results) - deterministic_count),
    }
