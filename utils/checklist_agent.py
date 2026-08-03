"""Runs the direct-from-BRD Checklist generation — no FRS involved. One LLM
call extracts checkable items from the BRD/Mapping text; a fixed baseline
set of standard print-production checks is then appended deterministically,
so those are always present regardless of what the BRD happens to mention."""

from utils.json_utils import safe_json
from prompts.checklist_prompt import CHECKLIST_PROMPT

BASELINE_PRODUCTION_ITEMS = [
    "Logo is correct — correct company logo present, correct size/placement",
    "Inserts are correct — correct insert(s) included, correct quantity",
    "Backer is present if required for this document type",
    "Return address block is correct and complete",
    "Mailing address prints correctly within the envelope window",
    "Postal barcode/OMR marks are correct for mail sorting",
    "Total page count is within the expected range — no missing or extra pages",
    "Printed single/double-sided (duplex/simplex) as specified",
    "Correct paper stock and perforation lines (if applicable)",
]


def run_checklist_agent(brd_text, mapping_text, client, dbg):
    prompt = CHECKLIST_PROMPT.format(brd=brd_text, mapping=mapping_text or "NO MAPPING PROVIDED")
    dbg.add("info", "CHECKLIST-AGENT", f"Prompt assembled — {len(prompt):,} chars")
    result = client.run(prompt, dbg)
    parsed = [i for i in safe_json(result.get("text", ""), dbg) if isinstance(i, dict)]

    items = []
    for i in parsed:
        section = str(i.get("Section", "") or "General").strip() or "General"
        category = str(i.get("Category", "") or "Business Rule").strip() or "Business Rule"
        text = str(i.get("Item", "") or "").strip()
        if text:
            items.append((section, category, text))

    for text in BASELINE_PRODUCTION_ITEMS:
        items.append(("Print Production (Standard)", "Production", text))

    usage = {"input": result["input_tokens"], "output": result["output_tokens"], "total": result["total_tokens"]}
    dbg.add("ok", "CHECKLIST-AGENT",
            f"Extracted {len(parsed)} item(s) from BRD + {len(BASELINE_PRODUCTION_ITEMS)} standard production check(s)")
    return items, usage
