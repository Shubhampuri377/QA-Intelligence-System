"""Known-good numbers on real client runs.

These are the guardrail. Every number here was adjudicated by hand against the
source feed and the composed PDF, so a change to any of them means either a real
improvement or a regression — and either way it has to be explained, not merged.

Both feeds are validated with a HAND-WRITTEN Mapping Spec so the checks measure
the comparison engine rather than an LLM's reading of the BRD. The third case
uses a spec shaped like the live agent's actual output, which is what caught the
pairing collapse: the agent set the addressee to the bill-to block, whose address
is the very field the composition renders wrong.
"""

import sys

from _harness import check, skip, summary, load_feed, load_pages

from utils.debug_log import DebugLog
from utils.mapping_report import _rollup
from utils.spec_validation import run_spec_validation

sys.path.insert(0, __file__.rsplit("\\", 1)[0] + "\\fixtures")
sys.path.insert(0, __file__.rsplit("/", 1)[0] + "/fixtures")

WML_JSON = "MAX_CASH_VALUE_LETTER_01_T_20260519_085406.JSON"
WML_PDF = "768620_WMLMAXCASHVALUELETTER_#10_1.PDF"
ORA_XML = "ORACLEARINVOICES_20260722.xml"
ORA_PDF = "ORACLEARINVOICES_20260722 PDF Output.pdf"


def _run(spec, recs, pages):
    inst, stats, _, _ = run_spec_validation(spec, recs, pages, "", None, DebugLog())
    return inst, stats, _rollup({"instances": inst})


def wml():
    print("\n=== WML MAX Cash Value — 11 records, 18 letters ===")
    recs, _ = load_feed(WML_JSON, "JSON")
    pages = load_pages(WML_PDF)
    if not recs or not pages:
        return skip("WML regression", f"{WML_JSON} / {WML_PDF} not in the data folder")
    from wml_spec import WML_SPEC
    inst, stats, roll = _run(WML_SPEC, recs, pages)
    check("18 letters expected", stats["letters_expected"], 18)
    check("18 letters paired to a page", stats["instances_located"], 18)
    check("4 letters suppressed by rule", stats["letters_suppressed"], 4)
    check("zero AI calls needed", stats["ai"], 0)
    check("575 fields pass", roll["PASS"], 575)
    check("34 fields FAIL", roll["FAIL"], 34)
    check("36 not verifiable", roll["NOT VERIFIABLE"], 36)
    check("nothing left unverified", stats["unverified"], 0)
    # Guards a regression that shipped once: a same-shape probe gated on finding
    # the field's label nearby stopped catching "Amount applied $15.00 rendered as
    # $50.00", because those words appear nowhere near the figure. It became
    # "NOT CHECKED" instead of a failure.
    amounts = [r for i in inst for r in i["rows"]
               if r["field"] == "Amount applied" and r["status"] == "MISMATCH"]
    check("wrong premium amount caught on every affected letter", len(amounts), 4)
    check("and it quotes what was actually rendered",
          all("found" in (r["notes"] or "") for r in amounts), True)


def oracle_hand_spec():
    print("\n=== Oracle AR Invoices — hand-written spec ===")
    recs, note = load_feed(ORA_XML, "XML")
    pages = load_pages(ORA_PDF)
    if not recs or not pages:
        return skip("Oracle regression", f"{ORA_XML} / {ORA_PDF} not in the data folder")
    # The repeating element is the record; header and trailer are file metadata.
    check("2 records, not 4", len(recs), 2)
    check("note names the skipped metadata", "File_Header" in (note or ""), True)
    from oracle_spec import ORACLE_SPEC
    inst, stats, roll = _run(ORACLE_SPEC, recs, pages)
    check("2 of 2 paired", stats["instances_located"], 2)
    check("35 pass", roll["PASS"], 35)
    check("9 FAIL", roll["FAIL"], 9)
    check("2 not verifiable", roll["NOT VERIFIABLE"], 2)


def oracle_live_spec():
    print("\n=== Oracle AR Invoices — spec shaped like the live agent's output ===")
    recs, _ = load_feed(ORA_XML, "XML")
    pages = load_pages(ORA_PDF)
    if not recs or not pages:
        return skip("Oracle live-spec regression", f"{ORA_XML} / {ORA_PDF} not in the data folder")
    from oracle_live_spec import LIVE_SPEC
    inst, stats, roll = _run(LIVE_SPEC, recs, pages)
    # Pairing must survive an addressee block whose own address is defective.
    check("2 of 2 paired despite a defective anchor field", stats["instances_located"], 2)
    check("34 pass", roll["PASS"], 34)
    check("10 FAIL", roll["FAIL"], 10)
    check("4 not verifiable", roll["NOT VERIFIABLE"], 4)
    fails = {r["field"] for i in inst for r in i["rows"]
             if r["status"] == "MISMATCH"}
    for f in ("Formatted Bill-To Address", "Ship To Site Number",
              "Transaction Class", "Account Discount"):
        check(f"still reports the real defect: {f}", f in fails, True)


if __name__ == "__main__":
    wml()
    oracle_hand_spec()
    oracle_live_spec()
    sys.exit(0 if summary("REGRESSION") else 1)
