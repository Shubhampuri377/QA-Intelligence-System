"""
Coverage & Test Data agents for Requirements Studio.

  1. Coverage Agent   -> run_coverage_agent()   — one call, maps every FRS
                          Input/Output field description onto the real field
                          names found in an uploaded sample data file.
  2. Test Data Agent  -> run_test_data_agent()  — batched + parallel (same
                          pattern as the QA Validation Agent), generates one
                          data record per test case, grounded in the sample's
                          real schema and linked back to TC_ID/FR_ID.
"""

import json
import concurrent.futures as cf

from utils.json_utils import safe_json
from utils.llm_client import classify_api_error
from prompts.test_data_prompt import COVERAGE_PROMPT, TEST_DATA_GEN_PROMPT


def new_zero_usage():
    return {"input": 0, "output": 0, "total": 0}


# ── 1. Coverage Agent ────────────────────────────────────────────

def run_coverage_agent(frs, sample_records, client, dbg):
    frs_fields = []
    for fr in frs:
        fr_id = fr.get("FR_ID", "")
        for f in fr.get("Inputs", []) or []:
            frs_fields.append({"FR_ID": fr_id, "Field": f, "Direction": "Input"})
        for f in fr.get("Outputs", []) or []:
            frs_fields.append({"FR_ID": fr_id, "Field": f, "Direction": "Output"})

    prompt = COVERAGE_PROMPT.format(
        frs_fields=json.dumps(frs_fields, indent=2),
        sample_schema=json.dumps(sample_records[:3], indent=2, default=str),
    )
    dbg.add("info", "COVERAGE-AGENT", f"Mapping {len(frs_fields)} FRS field description(s) against the sample")
    result = client.run(prompt, dbg)
    coverage = [c for c in safe_json(result.get("text", ""), dbg) if isinstance(c, dict)]
    usage = {"input": result["input_tokens"], "output": result["output_tokens"], "total": result["total_tokens"]}
    found = sum(1 for c in coverage if c.get("Status") == "Found")
    dbg.add("ok", "COVERAGE-AGENT", f"Coverage mapping complete — {found}/{len(coverage)} field(s) found in sample")
    return coverage, usage


# ── 2. Test Data Agent ───────────────────────────────────────────

def _test_data_batch_task(bi, batch_tcs, frs_by_id, coverage, sample_records, client, dbg):
    fr_ids_in_batch = {tc.get("FR_ID") for tc in batch_tcs}
    frs_context = [frs_by_id[fid] for fid in fr_ids_in_batch if fid in frs_by_id]
    relevant_coverage = [c for c in coverage if c.get("FR_ID") in fr_ids_in_batch]

    prompt = TEST_DATA_GEN_PROMPT.format(
        frs_context=json.dumps(frs_context, indent=2),
        field_mapping=json.dumps(relevant_coverage, indent=2),
        sample_schema=json.dumps(sample_records[:2], indent=2, default=str),
        test_cases_batch=json.dumps(batch_tcs, indent=2),
    )
    dbg.add("info", "TEST-DATA-AGENT", f"Batch {bi} — {len(batch_tcs)} test case(s), prompt {len(prompt):,} chars")

    try:
        result = client.run(prompt, dbg)
        records = [r for r in safe_json(result.get("text", ""), dbg) if isinstance(r, dict)]
        usage = {"input": result["input_tokens"], "output": result["output_tokens"], "total": result["total_tokens"]}
        error = None
    except Exception as e:
        records, usage = [], new_zero_usage()
        error = classify_api_error(str(e), client.provider)
        dbg.add("err", "TEST-DATA-AGENT", f"Batch {bi} failed: {error}", str(e)[:600])

    return records, usage, error


def run_test_data_agent(frs, test_cases, sample_records, coverage, client, dbg,
                         batch_size=100, max_workers=4, progress_cb=None):
    """Runs the Test Data Agent in batches, dispatched concurrently (same
    reasoning as the Validation Agent: these are network-bound calls, so
    running several at once cuts wall-clock time with no quality tradeoff)."""
    frs_by_id = {fr.get("FR_ID"): fr for fr in frs}
    batches = [test_cases[i:i + batch_size] for i in range(0, len(test_cases), batch_size)]

    all_records = []
    usage_total = new_zero_usage()
    failed_batches = 0
    completed = 0

    if batches:
        with cf.ThreadPoolExecutor(max_workers=max(1, max_workers)) as executor:
            futures = [executor.submit(_test_data_batch_task, bi, batch, frs_by_id, coverage, sample_records, client, dbg)
                       for bi, batch in enumerate(batches, start=1)]
            for future in cf.as_completed(futures):
                records, usage, error = future.result()
                usage_total["input"] += usage["input"]
                usage_total["output"] += usage["output"]
                usage_total["total"] += usage["total"]
                all_records.extend(records)
                if error:
                    failed_batches += 1
                completed += 1
                if progress_cb:
                    progress_cb(completed, len(batches))

    if failed_batches == len(batches) and batches:
        raise RuntimeError("Every Test Data Agent batch failed — check your API key, quota, or network connection.")

    dbg.add("ok", "TEST-DATA-AGENT",
            f"Generated {len(all_records)} record(s) across {len(batches)} batch(es) "
            f"({max_workers}x parallel, {failed_batches} batch failure(s))")
    return all_records, usage_total, failed_batches
