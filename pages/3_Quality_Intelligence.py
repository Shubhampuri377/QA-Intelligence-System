import json

import pandas as pd
import streamlit as st

from styles.theme import (inject_theme, nav_buttons, page_header, tbox, stats_row,
                          agent_stepper, format_pill, icon)
from utils.debug_log import DebugLog
from utils.llm_client import LLMClient, PROVIDER_MODELS, KEY_PLACEHOLDERS, estimate_cost
from utils.extraction import (extract_multi_document, extract_mapping_file, extract_pdf_pages,
                              extract_input_records, INPUT_DATA_FORMATS)
from utils.mapping_agents import build_findings, run_summary_agent
from utils.spec_validation import run_mapping_spec_agent, run_spec_validation
from utils.mapping_spec import spec_summary

from utils.mapping_report import (mapping_report_to_pdf, mapping_report_to_html,
                                  _rollup, _norm_status, DETAIL_ALL, DETAIL_FAILURES)
from utils.mapping_excel import mapping_detail_to_excel
from utils.naming import safe_filename_part

AGENT_DEFS = [
    {"key": "parsing", "icon": "document", "name": "1. Document Parsing",
     "desc": "Reads the BRD, the source feed and the generated output."},
    {"key": "spec", "icon": "map", "name": "2. Mapping Spec Agent",
     "desc": "Reads the BRD's field table once into machine-evaluable slots — the only stage that interprets the BRD."},
    {"key": "plan", "icon": "layers", "name": "3. Letter Plan & Pairing",
     "desc": "Applies the BRD's generation rules to decide which letters each record should produce, then pairs each to its own output page."},
    {"key": "compare", "icon": "shield", "name": "4. Expected vs Actual",
     "desc": "Computes each slot's expected value from the BRD rules and compares it to the rendered text — conditional logic resolved in code, at zero AI cost."},
    {"key": "findings", "icon": "flask", "name": "5. Findings & Summary",
     "desc": "Rolls up mismatches and gaps, then writes the executive summary."},
    {"key": "report", "icon": "chart", "name": "6. Report Generator",
     "desc": "Builds the mapping validation report as PDF and HTML."},
]

st.set_page_config(page_title="Quality Intelligence", layout="wide", page_icon="🛡️",
                   initial_sidebar_state="expanded")
inject_theme()
nav_buttons("quality")

# ── SESSION STATE ──────────────────────────────────────────────
for k, v in {
    "qa_instances": None, "qa_stats": None, "qa_spec": None, "qa_findings": None, "qa_summary": None,
    "qa_meta": None, "qa_agent_status": None,
    "token_usage_qa": {"input": 0, "output": 0, "total": 0},
    "last_debug_qa": None, "qa_html_report": None, "qa_pdf_report": None,
    "qa_excel_report": None, "qa_report_scope_built": None,
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

has_results = st.session_state.qa_instances is not None
usage = st.session_state.token_usage_qa

page_header("shield", "Quality Intelligence", "Field Mapping Validation",
            "Source Data + Generated Output → field-by-field reconciliation → Mapping Validation Report")

pn_col, _ = st.columns([2, 5])
with pn_col:
    project_name = st.text_input("Project Name", key="project_name_qa",
                                 placeholder="e.g. Credit union Project",
                                 help="Used to name your downloaded files — e.g. ProjectName_MappingValidationReport.pdf")
project_slug = safe_filename_part(project_name)

# ── CONFIG ROW ──────────────────────────────────────────────────
provider_col, model_col, key_col, t1, t2, t3, t4 = st.columns([1.8, 2, 2.4, 1, 1, 1, 1])
with provider_col:
    llm_provider = st.selectbox("AI Provider", list(PROVIDER_MODELS.keys()), key="llm_provider_qa")
with model_col:
    model_name = st.selectbox("Model", PROVIDER_MODELS[llm_provider], key="model_qa")
with key_col:
    api_key = st.text_input(f"{llm_provider.split('(')[0].strip()} API Key", type="password",
                             placeholder=KEY_PLACEHOLDERS[llm_provider], key="api_k_qa")
with t1: st.markdown(tbox("Input", f"{usage['input']:,}"), unsafe_allow_html=True)
with t2: st.markdown(tbox("Output", f"{usage['output']:,}"), unsafe_allow_html=True)
with t3: st.markdown(tbox("Total", f"{usage['total']:,}"), unsafe_allow_html=True)
with t4:
    cost = estimate_cost(llm_provider, usage["input"], usage["output"])
    st.markdown(tbox("Est. Cost", f"${cost:.4f}", "tbox-green"), unsafe_allow_html=True)

st.markdown("<div style='margin-bottom:10px;'></div>", unsafe_allow_html=True)

# ── UPLOAD ZONE ──────────────────────────────────────────────────
st.markdown('<div class="section-label">Upload Project Files</div>', unsafe_allow_html=True)
st.markdown('<div class="page-heading">Reconcile Every Mapped Field Against the Generated Document</div>', unsafe_allow_html=True)
st.caption("The BRD decides what gets checked. Its field-mapping table is read once into slots, each slot's "
           "expected value is computed from the BRD's own rules, and that is compared against the letter it "
           "belongs to. A field the BRD does not map is out of scope, not a gap.")

# Upload order mirrors the pipeline: the BRD decides what is checked, the feed
# supplies the values, the output is where they are looked for.

# ── 1. BRD + Mapping ──
oc1, oc2 = st.columns(2)
with oc1:
    st.markdown(f'<div class="upload-label" style="margin-top:10px;">{icon("document", 14)} 1 · BRD Document(s) <span style="color:var(--danger);font-weight:700;">(required)</span></div>', unsafe_allow_html=True)
    brd_files = st.file_uploader("BRD", type=["pdf", "docx", "txt"], label_visibility="collapsed",
                                 key="brd_up_val", accept_multiple_files=True)
    st.markdown('<div class="upload-hint">The field-mapping table is read from here — it defines which fields are checked and the rules for computing each expected value. Upload more than one to combine them.</div>', unsafe_allow_html=True)
    if brd_files:
        brd_pills = "".join(f'<div class="file-pill">{f.name}</div>' for f in brd_files)
        st.markdown(brd_pills, unsafe_allow_html=True)
with oc2:
    st.markdown(f'<div class="upload-label" style="margin-top:10px;">{icon("map", 14)} Mapping Doc <span style="color:var(--text-faint);font-weight:500;text-transform:none;letter-spacing:0">(optional)</span></div>', unsafe_allow_html=True)
    mapping_file = st.file_uploader("Mapping", type=["pdf", "docx", "xlsx", "xls", "csv", "txt"],
                                     label_visibility="collapsed", key="map_up_val")
    st.markdown('<div class="upload-hint">Field-name alignment and expected transformations (suppressed country codes, formatting rules) so a reformatted value is not reported as a defect</div>', unsafe_allow_html=True)
    if mapping_file: st.markdown(f'<div class="file-pill">{mapping_file.name}</div>', unsafe_allow_html=True)

if not brd_files and not mapping_file:
    st.warning("Upload the BRD to continue — the field-mapping spec is read from it, so it decides what "
               "gets validated and what each field's expected value should be.")

# ── 2. Source Data ──
st.markdown(f'<div class="upload-label" style="margin-top:16px;">{icon("database", 14)} 2 · Source Data <span style="color:var(--danger);font-weight:700;">(required)</span></div>', unsafe_allow_html=True)
pills = "".join(format_pill(label, ready) for label, ready in INPUT_DATA_FORMATS)
st.markdown(f'<div style="margin-bottom:8px;">{pills}</div>', unsafe_allow_html=True)

dc1, dc2 = st.columns([1, 2.4])
with dc1:
    data_format = st.selectbox("Format", [label for label, _ in INPUT_DATA_FORMATS], key="data_format_qa")
with dc2:
    data_file = st.file_uploader("Data", type=["json", "xml", "csv", "xlsx", "xls", "pdf", "png", "jpg", "jpeg", "txt", "dat"],
                                 label_visibility="collapsed", key="data_up_val")
    if data_file: st.markdown(f'<div class="file-pill">{data_file.name}</div>', unsafe_allow_html=True)

# ── 3. Generated Output ──
st.markdown(f'<div class="upload-label" style="margin-top:16px;">{icon("document", 14)} 3 · Generated Output <span style="color:var(--danger);font-weight:700;">(required)</span></div>', unsafe_allow_html=True)
output_file = st.file_uploader("Output", type=["pdf"], label_visibility="collapsed", key="output_up_val")
st.markdown('<div class="upload-hint">PDF — the generated document to validate</div>', unsafe_allow_html=True)
if output_file: st.markdown(f'<div class="file-pill">{output_file.name}</div>', unsafe_allow_html=True)

with st.expander("Advanced — speed & scope", expanded=False):
    ac1, ac2 = st.columns(2)
    with ac1:
        max_workers = st.slider("Parallel requests", 1, 8, 4, key="qa_max_workers",
                                help="How many AI comparison batches run at once. Higher = faster, but raises "
                                     "your chance of hitting the provider's rate limit.")
    with ac2:
        include_empty = st.toggle("Include empty source fields", value=False, key="qa_include_empty",
                                   help="Off by default — fields with no value in the source have nothing to "
                                        "validate and would flood the report. The excluded count is always "
                                        "reported in the summary.")

st.markdown("")
gc1, gc2 = st.columns([2, 5])
with gc1:
    run_validation = st.button("Run Validation Pipeline", use_container_width=True, key="run_validation_btn")
with gc2:
    debug_mode = st.toggle("Debug Mode", value=False, key="debug_mode_val",
                           help="Show detailed logs for every stage's LLM calls and JSON parsing")

# ── PIPELINE EXECUTION ──────────────────────────────────────────


def _status_list(statuses):
    return [{**a, "status": statuses[a["key"]]} for a in AGENT_DEFS]


if run_validation:
    if not api_key: st.error("Enter your API key above."); st.stop()
    if not data_file: st.error("Please upload a Source Data file."); st.stop()
    if not output_file: st.error("Please upload the generated Output PDF to validate."); st.stop()
    if not brd_files and not mapping_file:
        st.error("Please upload the BRD (or a mapping document). The field mapping spec is read "
                 "from it — without it there is nothing to validate against.")
        st.stop()

    dbg = DebugLog()
    client = LLMClient(llm_provider, api_key, model_name)
    statuses = {a["key"]: "idle" for a in AGENT_DEFS}

    st.markdown('<div class="section-label">Pipeline</div>', unsafe_allow_html=True)
    stepper_ph = st.empty()
    with stepper_ph.container():
        agent_stepper(_status_list(statuses))

    def refresh():
        with stepper_ph.container():
            agent_stepper(_status_list(statuses))

    usage_total = {"input": 0, "output": 0, "total": 0}

    # 1. Document Parsing
    statuses["parsing"] = "running"; refresh()
    try:
        data_records, data_note = extract_input_records(data_file, data_format)
        output_pages = extract_pdf_pages(output_file)

        # BRD and mapping doc are combined into one rules context — the AI pass
        # uses it to decide whether an absent field is a defect or an intended
        # suppression, so both sources belong in the same block.
        rule_parts = []
        if brd_files:
            brd_text = extract_multi_document(brd_files)
            if brd_text and brd_text.strip() not in ("", "[EMPTY DOCUMENT]"):
                rule_parts.append("=== BUSINESS REQUIREMENT DOCUMENT ===\n" + brd_text)
        if mapping_file:
            map_text = extract_mapping_file(mapping_file)
            if map_text and map_text.strip():
                rule_parts.append("=== MAPPING DOCUMENT ===\n" + map_text)
        mapping_rules = "\n\n".join(rule_parts)

        dbg.add("ok", "PARSING",
                f"Data: {data_note} · Output: {len(output_pages)} page(s)"
                + (f" · Rules context: {len(mapping_rules):,} chars from "
                   f"{len(brd_files or [])} BRD file(s)"
                   + (" + mapping doc" if mapping_file else "")
                   if mapping_rules else " · no rules context provided"))
        if not data_records:
            raise ValueError("Could not extract any records from the Source Data file.")
        if not output_pages:
            raise ValueError("Could not extract text from the Output PDF.")
    except Exception as e:
        statuses["parsing"] = "failed"; refresh()
        st.error(f"Document Parsing failed: {e}")
        if debug_mode: dbg.render()
        st.stop()
    statuses["parsing"] = "done"; refresh()

    # 2. Mapping Spec Agent — the only stage that interprets the BRD
    statuses["spec"] = "running"; refresh()
    try:
        spec, spec_usage = run_mapping_spec_agent(
            mapping_rules, mapping_file.name if mapping_file else "", data_records[0], client, dbg)
        for k in usage_total:
            usage_total[k] += spec_usage[k]
    except Exception as e:
        statuses["spec"] = "failed"; refresh()
        st.error(f"Mapping Spec Agent failed: {e}")
        if debug_mode: dbg.render()
        else: st.info("Enable **Debug Mode** above to see the full error trace.")
        st.stop()
    statuses["spec"] = "done"; refresh()
    summ = spec_summary(spec)
    if spec.get("truncated"):
        st.error(f"**The BRD spec response was cut off.** {summ['slots']} slot(s) were recovered, but "
                 f"any BRD row after the cut is MISSING and will not be validated — coverage is "
                 f"incomplete. Try a model with a larger output limit (e.g. gemini-2.5-pro) or split "
                 f"the BRD, then re-run. Review the Mapping Spec panel below before trusting results.")
    st.success(f"Read {summ['slots']} slot(s) and {summ['letters']} letter definition(s) from the "
               f"BRD. {summ['slots'] - summ['verifiable']} slot(s) flagged as not verifiable from "
               f"text. Expand **Mapping Spec** below to review what it understood.")

    # 3/4. Letter plan, pairing, and expected-vs-actual comparison
    statuses["plan"] = "running"; statuses["compare"] = "running"; refresh()
    batch_ph = st.empty()

    def progress_cb(done, total):
        batch_ph.progress(done / total, text=f"AI comparison batch {done}/{total}…")

    try:
        instances, stats, cmp_usage, failed_batches = run_spec_validation(
            spec, data_records, output_pages, mapping_rules, client=client, dbg=dbg,
            max_workers=max_workers, progress_cb=progress_cb)
        for k in usage_total:
            usage_total[k] += cmp_usage[k]
    except Exception as e:
        statuses["plan"] = statuses["compare"] = "failed"; refresh()
        st.error(f"Validation failed: {e}")
        if debug_mode: dbg.render()
        st.stop()
    batch_ph.empty()
    statuses["plan"] = statuses["compare"] = "done"; refresh()

    st.success(f"{stats['deterministic']} of {stats['deterministic'] + stats['ai']} slot-check(s) "
               f"settled by rule — zero AI tokens. {stats['letters_expected']} letter(s) expected "
               f"from {stats['records']} record(s), {stats['letters_suppressed']} correctly "
               f"suppressed by rule.")
    if not stats["page_count_matches"]:
        st.warning(f"Letter count does not reconcile: the BRD's rules expect "
                   f"{stats['letters_expected']} letter(s) and {stats['instances_located']} were "
                   f"paired, but the output has {stats['output_pages']} page(s). Investigate before "
                   f"trusting per-field results.")
    if failed_batches:
        st.warning(f"{failed_batches} AI comparison batch(es) failed — affected slots are marked "
                   f"UNVERIFIED. Lower **Parallel requests** and re-run if this persists.")

    # 5. Findings & Summary
    statuses["findings"] = "running"; refresh()
    findings = build_findings(instances)
    meta_for_summary = {"source_file": data_file.name, "output_file": output_file.name,
                        "record_count": stats["records"]}
    summary, s_usage = run_summary_agent(meta_for_summary, instances, findings, client, dbg,
                                            stats)
    for k in usage_total:
        usage_total[k] += s_usage[k]
    statuses["findings"] = "done"; refresh()

    # 6. Report
    statuses["report"] = "running"; refresh()
    statuses["report"] = "done"; refresh()

    for k in usage_total:
        st.session_state.token_usage_qa[k] += usage_total[k]
    st.session_state.qa_instances = instances
    st.session_state.qa_stats = stats
    st.session_state.qa_spec = spec
    st.session_state.qa_findings = findings
    st.session_state.qa_summary = summary
    st.session_state.qa_meta = {
        "project": project_name or "Client Engagement",
        "source_file": data_file.name, "output_file": output_file.name,
        "mapping_reference": ", ".join(
            [f.name for f in (brd_files or [])] + ([mapping_file.name] if mapping_file else [])) or "none provided",
        "provider": llm_provider, "model": model_name,
    }
    st.session_state.qa_agent_status = statuses
    st.session_state.qa_html_report = None
    st.session_state.qa_pdf_report = None
    st.session_state.qa_excel_report = None
    st.session_state.last_debug_qa = dbg
    st.rerun()

if st.session_state.get("last_debug_qa") and debug_mode:
    with st.expander("Last validation run — full pipeline debug log", expanded=False):
        st.session_state.last_debug_qa.render()

if st.session_state.qa_agent_status and not run_validation:
    st.markdown('<div class="section-label">Pipeline</div>', unsafe_allow_html=True)
    agent_stepper(_status_list(st.session_state.qa_agent_status))

# ── RESULTS ─────────────────────────────────────────────────────
if has_results:
    instances = st.session_state.qa_instances
    stats = st.session_state.qa_stats
    findings = st.session_state.qa_findings
    summary = st.session_state.qa_summary
    roll = _rollup({"instances": instances})

    st.markdown('<div class="section-label">Executive Summary</div>', unsafe_allow_html=True)
    stats_row([
        ("sb-purple", str(roll["checked"]), "Fields Checked", "sv-purple"),
        ("sb-green", str(roll["PASS"]), "Pass", "sv-green"),
        ("sb-red", str(roll["FAIL"]), "FAIL", "sv-red"),
        ("sb-purple", f"{roll['pass_rate']:.1f}%", "Pass Rate", "sv-purple"),
        ("sb-blue", str(roll["NOT VERIFIABLE"]), "Not Verifiable (excluded)", "sv-blue"),
    ])
    stats_row([
        ("sb-purple", f"{stats['instances_located']}/{stats.get('letters_expected', stats['records'])}", "Letters Paired", "sv-purple"),
        ("sb-green", str(stats["deterministic"]), "Rule-Checked (0 AI tokens)", "sv-green"),
        ("sb-blue", str(stats["ai"]), "AI-Compared", "sv-blue"),
        ("sb-amber", str(stats.get("letters_suppressed", 0)), "Letters Suppressed by Rule", "sv-amber"),
    ])

    if stats.get("unverified"):
        st.error(f"**Incomplete run — do not sign off.** {stats['unverified']} of {roll['fields']} "
                 f"field(s) carry no verdict because their AI comparison call failed. They are "
                 f"marked UNVERIFIED below and in the report. Lower **Parallel requests** in "
                 f"Advanced options, or use a provider without a free-tier daily cap, and re-run.")
    if stats.get("unstructured"):
        st.warning(f"{stats['unstructured']} record(s) carry no field structure (Print Image, or a "
                   f"fixed-length feed with no record layout supplied) — field mapping cannot be "
                   f"performed on those.")
    st.info(summary.get("assessment", ""))
    if summary.get("narrative"):
        st.markdown(f'<div class="vc-text" style="margin-bottom:10px;">{summary["narrative"]}</div>',
                    unsafe_allow_html=True)
    if roll["FAIL"]:
        st.error(f"**VALIDATION FAILED** — {roll['FAIL']} of {roll['checked']} checked field(s) do "
                 f"not render their source value in full. Every one is listed below with what is "
                 f"missing.")
    elif roll["checked"]:
        st.success(f"**VALIDATION PASSED** — all {roll['checked']} checked field(s) render their "
                   f"source value in full.")

    if findings:
        st.markdown('<div class="section-label">Key Findings At A Glance</div>', unsafe_allow_html=True)
        cls = {"Failure": "rc-critical", "Not verifiable": "rc-info"}
        for f in findings:
            st.markdown(f"""<div class="reviewer-card {cls.get(f.get('type'), '')}">
              <div class="reviewer-title">{f.get('type', '')}</div>
              <div class="reviewer-desc">{f.get('text', '')}</div>
            </div>""", unsafe_allow_html=True)

    if st.session_state.qa_spec:
        spec = st.session_state.qa_spec
        summ = spec_summary(spec)
        with st.expander(f"Mapping Spec read from the BRD — {summ['slots']} slot(s), "
                         f"{summ['letters']} letter definition(s)  ·  review this first", expanded=False):
            st.caption("This is the only stage that interprets the BRD. If a slot is wrong here, every "
                       "verdict derived from it is wrong — check it before trusting the results.")
            st.dataframe(pd.DataFrame([{
                "Slot": sl.get("slot_name", ""), "BRD Ref": sl.get("brd_ref", ""),
                "Letters": ", ".join(sl.get("letters") or ["all"]),
                "Expected From": (sl.get("expected") or {}).get("kind", ""),
                "Format": (sl.get("expected") or {}).get("format", "") or "—",
                "Verifiable": "yes" if sl.get("verifiable", True) else "no",
            } for sl in spec.get("slots") or []]), use_container_width=True, hide_index=True)
            if spec.get("not_verifiable_requirements"):
                st.markdown("**Declared requirements not verifiable from these inputs**")
                for it in spec["not_verifiable_requirements"]:
                    st.markdown(f'<div class="t-rule">• <b>{it.get("ref","")}</b> — {it.get("text","")}</div>',
                                unsafe_allow_html=True)

    st.markdown('<div class="section-label">Field Mapping Detail</div>', unsafe_allow_html=True)
    fc1, fc2 = st.columns([3, 2])
    with fc1:
        status_filter = st.multiselect("Filter by status", ["PASS", "FAIL", "NOT VERIFIABLE"],
                                        default=["FAIL"], key="qa_status_filter")
    with fc2:
        show_all_docs = st.toggle("Show every document", value=False, key="qa_show_all_docs",
                                   help="Off: documents containing a failure are listed first and "
                                        "the list is capped, so a 500-record run stays usable in "
                                        "the browser. The downloads always contain everything.")

    # A run can produce hundreds of documents; one expander with a table each is
    # what makes the page crawl, not the validation. Failures first, then a cap —
    # and the cap is stated, because a silently shortened list reads as a complete one.
    DOC_CAP = 25
    ordered = sorted(instances,
                     key=lambda i: -sum(1 for r in i["rows"] if _norm_status(r["status"]) == "FAIL"))
    shown = ordered if show_all_docs else ordered[:DOC_CAP]
    if len(shown) < len(ordered):
        hidden = len(ordered) - len(shown)
        clean = sum(1 for i in ordered[DOC_CAP:]
                    if not any(_norm_status(r["status"]) == "FAIL" for r in i["rows"]))
        st.caption(f"Showing {len(shown)} of {len(ordered)} documents, those with failures first. "
                   f"{hidden} not shown ({clean} of them passed every checked field) — "
                   f"turn on **Show every document**, or use the Excel export for the full list.")

    for inst in shown:
        rows = [r for r in inst["rows"]
                if not status_filter or _norm_status(r["status"]) in status_filter]
        c = {"PASS": 0, "FAIL": 0, "NOT VERIFIABLE": 0}
        for r in inst["rows"]:
            c[_norm_status(r["status"])] += 1
        head = (f"{inst['title']}  —  {c['PASS']} pass · {c['FAIL']} FAIL · "
                f"{c['NOT VERIFIABLE']} not verifiable")
        with st.expander(head, expanded=bool(c["FAIL"])):
            st.caption(inst["subtitle"])
            if not rows:
                st.info("No fields match the selected status filter for this document.")
            else:
                df = pd.DataFrame([{
                    "Field": r["field"], "Expected Value": str(r.get("expected", r["source"]))[:200],
                    "Output Value": str(r.get("output", ""))[:200],
                    "Status": ("UNVERIFIED" if r.get("unverified") else r["status"]),
                    "Checked By": r.get("by", ""),
                    "Notes": r.get("notes", ""), "Path": r["field_path"],
                } for r in rows])
                st.dataframe(df, use_container_width=True, hide_index=True,
                             column_config={
                                 "Field": st.column_config.TextColumn("Field", width="medium"),
                                 "Expected Value": st.column_config.TextColumn("Expected Value", width="medium"),
                                 "Output Value": st.column_config.TextColumn("Output Value", width="medium"),
                                 "Status": st.column_config.TextColumn("Status", width="small"),
                                 "Checked By": st.column_config.TextColumn("By", width="small"),
                                 "Notes": st.column_config.TextColumn("Notes", width="large"),
                                 "Path": st.column_config.TextColumn("Source Path", width="medium"),
                             })

    if summary.get("recommendations"):
        st.markdown('<div class="section-label">Recommendations</div>', unsafe_allow_html=True)
        for rec in summary["recommendations"]:
            st.markdown(f'<div class="t-rule">• {rec}</div>', unsafe_allow_html=True)

    st.markdown('<div class="export-box"><div class="export-title">Export Report</div>', unsafe_allow_html=True)
    meta = st.session_state.qa_meta or {}
    payload = {
        **meta,
        "narrative": summary.get("narrative", ""),
        "assessment": summary.get("assessment", ""),
        "recommendations": summary.get("recommendations", []),
        "totals": {"source_records": stats["records"],
                   "instances_matched": stats["instances_located"],
                   "deterministic": stats["deterministic"],
                   "unverified": stats.get("unverified", 0)},
        "not_verifiable": (st.session_state.qa_spec or {}).get("not_verifiable_requirements") or [],
        "findings": findings,
        "instances": instances,
    }
    # The full field-by-field PDF is ~1,100 pages at 500 records and 26 seconds to
    # build. Failures-only keeps it a document someone will actually open, at any
    # volume; the Excel export carries every row for the runs where that matters.
    scope_label = st.radio(
        "Report detail", ["Failures only (recommended)", "Every checked field"],
        horizontal=True, key="qa_report_scope",
        help="Applies to the PDF and HTML reports. Summary counts always cover the "
             "whole run. The Excel export always contains every row.")
    scope = DETAIL_FAILURES if scope_label.startswith("Failures") else DETAIL_ALL
    if st.session_state.get("qa_report_scope_built") != scope:
        st.session_state.qa_html_report = None
        st.session_state.qa_pdf_report = None
        st.session_state.qa_report_scope_built = scope

    if st.session_state.qa_html_report is None:
        try:
            st.session_state.qa_html_report = mapping_report_to_html(payload, detail=scope)
        except Exception as e:
            st.error(f"HTML export error: {e}")
    if st.session_state.qa_pdf_report is None:
        with st.spinner("Building PDF report…"):
            try:
                st.session_state.qa_pdf_report = mapping_report_to_pdf(payload, detail=scope)
            except Exception as e:
                st.error(f"PDF export error: {e}")
    if st.session_state.get("qa_excel_report") is None:
        try:
            st.session_state.qa_excel_report = mapping_detail_to_excel(payload)
        except Exception as e:
            st.error(f"Excel export error: {e}")

    edc1, edc2, edc3, edc4 = st.columns(4)
    with edc1:
        if st.session_state.qa_pdf_report:
            st.download_button("Download Report — PDF", data=st.session_state.qa_pdf_report,
                file_name=f"{project_slug}_MappingValidationReport.pdf", mime="application/pdf",
                use_container_width=True)
    with edc2:
        if st.session_state.qa_html_report:
            st.download_button("Download Report — HTML", data=st.session_state.qa_html_report,
                file_name=f"{project_slug}_MappingValidationReport.html", mime="text/html",
                use_container_width=True)
    with edc3:
        if st.session_state.get("qa_excel_report"):
            # No help= on this one: it wraps the button in a tooltip container the
            # other three do not have, which makes it render and hover differently
            # in a row that should look uniform. The explanation is a caption below.
            st.download_button("Download Detail — Excel",
                data=st.session_state.qa_excel_report,
                file_name=f"{project_slug}_MappingValidationDetail.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True)
    with edc4:
        st.download_button("Download Raw — JSON", data=json.dumps({
            "meta": meta, "stats": stats, "summary": summary,
            "findings": findings, "instances": instances,
        }, indent=2, default=str), file_name=f"{project_slug}_MappingValidationResults.json",
            mime="application/json", use_container_width=True)
    st.caption("The Excel detail contains every checked field regardless of the report detail "
               "setting above. The PDF and HTML follow that setting.")
    st.markdown('</div>', unsafe_allow_html=True)
