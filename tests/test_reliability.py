"""Reliability suite for Field Mapping Validation. Synthetic data only, so
this always runs — no client files required.

Part 1 — FORMAT PARITY: the same logical feed expressed as JSON, XML, CSV and
Excel must produce identical verdicts. A field that validates as JSON and fails
as CSV is the bug class this guards.

Part 2 — FAILURE HONESTY: a run whose AI calls die must be reported as
INCOMPLETE with every affected field marked UNVERIFIED, never as PASS.

Part 3 — HOSTILE INPUT: malformed feeds, unstructured records, empty feeds.
"""
import io, json, sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd
from utils.debug_log import DebugLog
from utils.extraction import extract_input_records
from utils.field_mapping import normalize_records
from utils.mapping_agents import run_field_mapping_validation, build_findings, run_summary_agent
from utils.mapping_report import mapping_report_to_pdf, mapping_report_to_html, _rollup

PASS = FAIL = 0


def check(label, got, want):
    global PASS, FAIL
    ok = got == want
    PASS, FAIL = PASS + ok, FAIL + (not ok)
    print(f"  [{'ok  ' if ok else 'FAIL'}] {label}")
    if not ok:
        print(f"          got={got!r}\n          want={want!r}")


class Upload(io.BytesIO):
    """Minimal stand-in for a Streamlit UploadedFile."""
    def __init__(self, data: bytes, name: str):
        super().__init__(data)
        self.name = name


# ── The same logical feed in four formats ────────────────────────
ROWS = [
    # Fields 1-5 resolve deterministically. `legacyCode` is absent from the
    # output (-> provisional GAP -> needs rule adjudication) and `unitCount` is
    # two characters (-> too weak to judge mechanically). Both therefore require
    # an AI call, which is what makes the failure paths reachable.
    {"policyId": "0004073361", "billingPacAmount": "1050.50",
     "firstName": "George", "lastName": "Garst", "activityDate": "2026-04-23",
     "legacyCode": "ZZZ9988771", "unitCount": "15"},
    {"policyId": "0004074652", "billingPacAmount": "887.00",
     "firstName": "Michael", "lastName": "Brown", "activityDate": "2026-04-23",
     "legacyCode": "QQQ1122334", "unitCount": "22"},
]
PAGES = [
    "Certificate # 0004073361\nDear GEORGE GARST,\namount of $1,050.50 drafted\n04-23-2026",
    "Certificate # 0004074652\nDear MICHAEL BROWN,\namount of $887.00 drafted\n04-23-2026",
]

json_bytes = json.dumps({"records": ROWS}).encode()
xml_bytes = ("<feed>" + "".join(
    "<record>" + "".join(f"<{k}>{v}</{k}>" for k, v in r.items()) + "</record>"
    for r in ROWS) + "</feed>").encode()
csv_bytes = pd.DataFrame(ROWS).to_csv(index=False).encode()
xl_buf = io.BytesIO()
pd.DataFrame(ROWS).to_excel(xl_buf, index=False)


class OfflineClient:
    """No AI available — every call fails, as in the real quota-exhausted run."""
    provider = "Offline"
    def run(self, prompt, dbg=None):
        raise RuntimeError("429 RESOURCE_EXHAUSTED: quota exceeded")


class GoodClient:
    provider = "Mock"
    def run(self, prompt, dbg=None):
        if "narrative" in prompt:
            body = json.dumps({"narrative": "n", "assessment": "PASS — ok",
                               "recommendations": ["r"]})
        else:
            body = "[]"      # returns no verdicts -> exercises re-derivation
        return {"text": body, "input_tokens": 1, "output_tokens": 1, "total_tokens": 2}


def verdicts(records, pages, client):
    inst, stats, _, _ = run_field_mapping_validation(
        records, pages, mapping_rules="", client=client, dbg=DebugLog())
    flat = {}
    for n, i in enumerate(inst):
        for r in i["rows"]:
            flat[f"{n}:{r['field']}"] = (r["status"], bool(r.get("unverified")))
    return flat, stats, inst


print("\n=== PART 1 · FORMAT PARITY ===")
parsed = {}
for label, data, name, fmt in [
    ("JSON",  json_bytes,        "feed.json",  "JSON"),
    ("XML",   xml_bytes,         "feed.xml",   "XML"),
    ("CSV",   csv_bytes,         "feed.csv",   "CSV / Excel"),
    ("Excel", xl_buf.getvalue(), "feed.xlsx",  "CSV / Excel"),
]:
    recs, note = extract_input_records(Upload(data, name), fmt)
    recs, _ = normalize_records(recs)
    parsed[label] = recs
    check(f"{label}: 2 records parsed", len(recs), 2)

print("\n  -- identifier fidelity (leading zeros / trailing decimals) --")
for label, recs in parsed.items():
    check(f"{label}: policyId preserved", str(recs[0].get("policyId")), "0004073361")
    check(f"{label}: amount preserved", str(recs[0].get("billingPacAmount")), "1050.50")

print("\n  -- verdict parity across formats --")
base = None
for label, recs in parsed.items():
    v, stats, _ = verdicts(recs, PAGES, GoodClient())
    if base is None:
        base, base_label = v, label
        print(f"     baseline ({label}): {sorted(set(v.values()))} over {len(v)} fields")
    else:
        check(f"{label} verdicts identical to {base_label}", v, base)

print("\n=== PART 2 · FAILURE HONESTY ===")
inst, stats, _, failed = run_field_mapping_validation(
    parsed["JSON"], PAGES, mapping_rules="Some rule.", client=OfflineClient(), dbg=DebugLog())
roll = _rollup({"instances": inst})
findings = build_findings(inst)
summary, _ = run_summary_agent({"source_file": "f", "output_file": "o", "record_count": 2},
                               inst, findings, OfflineClient(), DebugLog())
unv = stats["unverified"]
check("some fields went unverified", unv > 0, True)
check("every unverified row is flagged",
      sum(1 for i in inst for r in i["rows"] if r.get("unverified")), unv)
check("assessment starts with INCOMPLETE", summary["assessment"].startswith("INCOMPLETE"), True)
check("assessment does NOT claim PASS", "PASS" in summary["assessment"], False)

payload = {"project": "T", "source_file": "f", "output_file": "o", "provider": "Offline",
           "model": "-", "narrative": summary["narrative"], "assessment": summary["assessment"],
           "recommendations": summary["recommendations"], "findings": findings,
           "instances": inst,
           "totals": {"source_records": 2, "instances_matched": 2,
                      "deterministic": stats["deterministic"], "unverified": unv}}
pdf, html = mapping_report_to_pdf(payload), mapping_report_to_html(payload)
import fitz
ptxt = "".join(p.get_text("text") for p in fitz.open(stream=pdf, filetype="pdf"))
check("PDF carries INCOMPLETE banner", "DO NOT SIGN OFF" in ptxt, True)
check("PDF marks rows UNVERIFIED", "UNVERIFIED" in ptxt, True)
check("HTML carries INCOMPLETE banner", "DO NOT SIGN OFF" in html, True)
check("HTML marks rows UNVERIFIED", "UNVERIFIED" in html, True)

print("\n=== PART 3 · HOSTILE INPUT ===")
bad_json = Upload(b"{not valid json", "bad.json")
recs, note = extract_input_records(bad_json, "JSON")
try:
    normalize_records(recs)
    check("malformed JSON is rejected", "no error raised", "ValueError")
except ValueError as ex:
    check("malformed JSON is rejected", "could not be parsed" in str(ex), True)

bad_xml = Upload(b"<feed><record>", "bad.xml")
recs, _ = extract_input_records(bad_xml, "XML")
try:
    normalize_records(recs)
    check("malformed XML is rejected", "no error raised", "ValueError")
except ValueError as ex:
    check("malformed XML is rejected", "could not be parsed" in str(ex), True)

recs, n = normalize_records(["a raw fixed-length line", "another line"])
check("unstructured records counted", n, 2)
check("unstructured records still dicts", all(isinstance(r, dict) for r in recs), True)

try:
    normalize_records([])
    check("empty feed is rejected", "no error", "ValueError")
except ValueError:
    check("empty feed is rejected", True, True)

# A record with no matching output page must not silently vanish.
inst, stats, _, _ = run_field_mapping_validation(
    parsed["JSON"], ["totally unrelated page text"], mapping_rules="",
    client=GoodClient(), dbg=DebugLog())
check("unmatched records still reported", len(inst), 2)

print(f"\n{'=' * 52}\n{PASS} passed, {FAIL} failed\n{'=' * 52}")
sys.exit(1 if FAIL else 0)
