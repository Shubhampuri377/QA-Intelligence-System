import json

import pandas as pd
import streamlit as st

from styles.theme import (inject_theme, nav_buttons, page_header, tbox, stats_row,
                          agent_stepper, icon)
from utils.debug_log import DebugLog
from utils.llm_client import LLMClient, PROVIDER_MODELS, KEY_PLACEHOLDERS, estimate_cost
from utils.extraction import (extract_multi_document, extract_mapping_file,
                              extract_input_records, INPUT_DATA_FORMATS)
from utils.field_mapping import normalize_records
from utils.spec_validation import run_mapping_spec_agent
from utils.mapping_spec import spec_summary
from utils.test_data_builder import build_records, expected_letters, display_path
from utils.located_writer import write as write_located
from utils.test_data_report import build_test_data_report
from utils.naming import safe_filename_part

st.set_page_config(page_title="Data Generation", layout="wide", page_icon="🗃️",
                   initial_sidebar_state="expanded")
inject_theme()
nav_buttons("data")

AGENT_DEFS = [
    {"key": "parsing", "icon": "document", "name": "1. Document Parsing",
     "desc": "Reads the BRD, the mapping document, and the sample data file."},
    {"key": "spec", "icon": "map", "name": "2. Mapping Spec Agent",
     "desc": "Reads the BRD's field table once into machine-evaluable rules — the only stage that interprets the BRD."},
    {"key": "cases", "icon": "layers", "name": "3. Coverage Cases",
     "desc": "Derives what must be varied: both sides of every rule, each name part in isolation, format boundaries, and declared field lengths."},
    {"key": "build", "icon": "database", "name": "4. Record Generation",
     "desc": "Clones the richest sample record and overwrites only the paths each case needs, then packs independent cases into shared records."},
    {"key": "report", "icon": "chart", "name": "5. Data Map",
     "desc": "Records the line number of every generated value while writing the file, and lists anything that could not be covered."},
]

# ── SESSION STATE ──────────────────────────────────────────────
for k, v in {
    "td_spec": None, "td_records": None, "td_rows": None, "td_blocked": None,
    "td_locs": None, "td_expected": None, "td_text": None, "td_report": None,
    "td_meta": None, "td_status": None, "last_debug_td": None,
    "token_usage_td": {"input": 0, "output": 0, "total": 0},
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

has_data = st.session_state.td_records is not None
usage = st.session_state.token_usage_td

page_header("database", "Data Generation", "Coverage-Driven Generation",
            "BRD + Mapping + Sample Schema → test data that proves every rule, with a line-by-line map")

pn_col, _ = st.columns([2, 5])
with pn_col:
    project_name = st.text_input("Project Name", key="project_name_td",
                                 placeholder="e.g. Credit union Project",
                                 help="Used to name your downloaded files — e.g. ProjectName_TestData.json")
project_slug = safe_filename_part(project_name)

# ── CONFIG ROW ──────────────────────────────────────────────────
p_col, m_col, k_col, t1, t2, t3, t4 = st.columns([1.8, 2, 2.4, 1, 1, 1, 1])
with p_col:
    llm_provider = st.selectbox("AI Provider", list(PROVIDER_MODELS.keys()), key="llm_provider_td")
with m_col:
    model_name = st.selectbox("Model", PROVIDER_MODELS[llm_provider], key="model_td")
with k_col:
    api_key = st.text_input(f"{llm_provider.split('(')[0].strip()} API Key", type="password",
                             placeholder=KEY_PLACEHOLDERS[llm_provider], key="api_k_td")
with t1: st.markdown(tbox("Input", f"{usage['input']:,}"), unsafe_allow_html=True)
with t2: st.markdown(tbox("Output", f"{usage['output']:,}"), unsafe_allow_html=True)
with t3: st.markdown(tbox("Total", f"{usage['total']:,}"), unsafe_allow_html=True)
with t4:
    st.markdown(tbox("Est. Cost", f"${estimate_cost(llm_provider, usage['input'], usage['output']):.4f}",
                     "tbox-green"), unsafe_allow_html=True)

st.markdown("<div style='margin-bottom:10px;'></div>", unsafe_allow_html=True)

# ── UPLOADS ─────────────────────────────────────────────────────
st.markdown('<div class="section-label">Upload Project Files</div>', unsafe_allow_html=True)
st.markdown('<div class="page-heading">Generate Test Data That Proves Every Requirement</div>',
            unsafe_allow_html=True)
st.caption("The BRD decides what to vary. The sample supplies the record shape — field names, "
           "nesting and format are copied from it, so nothing is invented. Values are computed "
           "from the rules, not guessed by a model.")

oc1, oc2 = st.columns(2)
with oc1:
    st.markdown(f'<div class="upload-label" style="margin-top:10px;">{icon("document", 14)} 1 · BRD Document(s) <span style="color:var(--danger);font-weight:700;">(required)</span></div>', unsafe_allow_html=True)
    brd_files = st.file_uploader("BRD", type=["pdf", "docx", "txt"], label_visibility="collapsed",
                                 key="brd_up_td", accept_multiple_files=True)
    st.markdown('<div class="upload-hint">The field table and rules are read from here — they decide which fields get varied and what values to use.</div>', unsafe_allow_html=True)
    if brd_files:
        st.markdown("".join(f'<div class="file-pill">{f.name}</div>' for f in brd_files),
                    unsafe_allow_html=True)
with oc2:
    st.markdown(f'<div class="upload-label" style="margin-top:10px;">{icon("map", 14)} Mapping Doc <span style="color:var(--text-faint);font-weight:500;text-transform:none;letter-spacing:0">(optional)</span></div>', unsafe_allow_html=True)
    mapping_file = st.file_uploader("Mapping", type=["pdf", "docx", "xlsx", "xls", "csv", "txt"],
                                     label_visibility="collapsed", key="map_up_td")
    st.markdown('<div class="upload-hint">Field-name alignment and expected transformations</div>',
                unsafe_allow_html=True)
    if mapping_file:
        st.markdown(f'<div class="file-pill">{mapping_file.name}</div>', unsafe_allow_html=True)

st.markdown(f'<div class="upload-label" style="margin-top:16px;">{icon("database", 14)} 2 · Sample Data <span style="color:var(--danger);font-weight:700;">(required)</span></div>', unsafe_allow_html=True)
st.caption("A real feed — one record per block ideally. A branch can only be generated if the "
           "sample shows its shape, so the richest sample gives the widest coverage.")
dc1, dc2, dc3 = st.columns([1, 2, 1])
with dc1:
    in_format = st.selectbox("Sample format", [l for l, _ in INPUT_DATA_FORMATS], key="in_fmt_td")
with dc2:
    sample_file = st.file_uploader("Sample", type=["json", "xml", "csv", "xlsx", "xls", "txt", "dat"],
                                    label_visibility="collapsed", key="sample_up_td")
    if sample_file:
        st.markdown(f'<div class="file-pill">{sample_file.name}</div>', unsafe_allow_html=True)
with dc3:
    out_format = st.selectbox("Generate as", ["JSON", "XML", "CSV"], key="out_fmt_td",
                               help="Format of the generated data file. Line numbers in the Data "
                                    "Map refer to this file.")

with st.expander("Advanced", expanded=False):
    max_records = st.slider("Maximum records", 5, 200, 60, key="td_max",
                            help="Independent cases share records, so this is rarely reached. "
                                 "Anything dropped is listed under Not Covered.")

st.markdown("")
gc1, gc2 = st.columns([2, 5])
with gc1:
    run = st.button("Generate Test Data", use_container_width=True, key="run_td")
with gc2:
    debug_mode = st.toggle("Debug Mode", value=False, key="debug_td",
                           help="Show the BRD-reading call and generation trace")


def _status_list(st_map):
    return [{**a, "status": st_map[a["key"]]} for a in AGENT_DEFS]


if run:
    if not api_key: st.error("Enter your API key above."); st.stop()
    if not brd_files: st.error("Upload the BRD — the rules are read from it."); st.stop()
    if not sample_file: st.error("Upload a sample data file — it supplies the record shape."); st.stop()

    dbg = DebugLog()
    client = LLMClient(llm_provider, api_key, model_name)
    statuses = {a["key"]: "idle" for a in AGENT_DEFS}
    st.markdown('<div class="section-label">Pipeline</div>', unsafe_allow_html=True)
    ph = st.empty()
    with ph.container():
        agent_stepper(_status_list(statuses))

    def refresh():
        with ph.container():
            agent_stepper(_status_list(statuses))

    usage_total = {"input": 0, "output": 0, "total": 0}

    # 1 · Parsing
    statuses["parsing"] = "running"; refresh()
    try:
        brd_text = extract_multi_document(brd_files)
        map_text = extract_mapping_file(mapping_file) if mapping_file else ""
        rules = brd_text + (("\n\n=== MAPPING DOCUMENT ===\n" + map_text) if map_text else "")
        raw, note = extract_input_records(sample_file, in_format)
        sample_records, unstructured = normalize_records(raw)
        dbg.add("ok", "PARSING", f"BRD: {len(brd_text):,} chars · Sample: {note}")
        if unstructured:
            st.warning(f"{unstructured} sample record(s) carry no field structure — field-level "
                       f"generation is not possible for those.")
    except Exception as e:
        statuses["parsing"] = "failed"; refresh()
        st.error(f"Parsing failed: {e}")
        if debug_mode: dbg.render()
        st.stop()
    statuses["parsing"] = "done"; refresh()

    # 2 · Mapping Spec
    statuses["spec"] = "running"; refresh()
    try:
        spec, s_usage = run_mapping_spec_agent(rules, mapping_file.name if mapping_file else "",
                                                sample_records[0], client, dbg)
        for k in usage_total: usage_total[k] += s_usage[k]
    except Exception as e:
        statuses["spec"] = "failed"; refresh()
        st.error(f"Mapping Spec Agent failed: {e}")
        if debug_mode: dbg.render()
        else: st.info("Enable **Debug Mode** to see the full trace.")
        st.stop()
    statuses["spec"] = "done"; refresh()
    summ = spec_summary(spec)
    if spec.get("truncated"):
        st.error(f"**The BRD spec response was cut off.** {summ['slots']} rule(s) recovered; anything "
                 f"after the cut is missing, so coverage is incomplete. Try a model with a larger "
                 f"output limit and re-run.")
    st.success(f"Read {summ['slots']} field rule(s) and {summ['letters']} document definition(s) "
               f"from the BRD.")

    # 3/4 · Cases + records
    statuses["cases"] = "running"; statuses["build"] = "running"; refresh()
    try:
        records, rows, blocked = build_records(spec, sample_records, max_records=max_records)
        if not records:
            raise ValueError("No coverage cases could be generated from this BRD and sample.")
    except Exception as e:
        statuses["cases"] = statuses["build"] = "failed"; refresh()
        st.error(f"Generation failed: {e}")
        if debug_mode: dbg.render()
        st.stop()
    statuses["cases"] = statuses["build"] = "done"; refresh()

    # 5 · Write with locations + report
    statuses["report"] = "running"; refresh()
    text, locs = write_located(records, out_format)
    expected = expected_letters(spec, records)
    data_filename = f"{project_slug}_TestData.{out_format.lower()}"
    meta = {"project": project_name or "Client Engagement", "format": out_format,
            "data_filename": data_filename, "record_count": len(records),
            "brd_files": ", ".join(f.name for f in brd_files),
            "mapping_file": mapping_file.name if mapping_file else "—",
            "sample_file": sample_file.name}
    report = build_test_data_report(rows, blocked, locs, expected, meta)
    statuses["report"] = "done"; refresh()

    for k in usage_total:
        st.session_state.token_usage_td[k] += usage_total[k]
    st.session_state.update(td_spec=spec, td_records=records, td_rows=rows, td_blocked=blocked,
                            td_locs=locs, td_expected=expected, td_text=text, td_report=report,
                            td_meta=meta, td_status=statuses, last_debug_td=dbg)
    st.rerun()

if st.session_state.get("last_debug_td") and debug_mode:
    with st.expander("Last generation — debug log", expanded=False):
        st.session_state.last_debug_td.render()

if st.session_state.td_status and not run:
    st.markdown('<div class="section-label">Pipeline</div>', unsafe_allow_html=True)
    agent_stepper(_status_list(st.session_state.td_status))

# ── RESULTS ─────────────────────────────────────────────────────
if has_data:
    records = st.session_state.td_records
    rows = st.session_state.td_rows
    blocked = st.session_state.td_blocked
    locs = st.session_state.td_locs
    expected = st.session_state.td_expected
    meta = st.session_state.td_meta
    spec = st.session_state.td_spec

    st.markdown('<div class="section-label">Summary</div>', unsafe_allow_html=True)
    stats_row([
        ("sb-purple", str(len(records)), "Records Generated", "sv-purple"),
        ("sb-green", str(len(rows)), "Values Mapped to a Rule", "sv-green"),
        ("sb-red", str(len(blocked)), "Not Covered", "sv-red"),
        ("sb-blue", str(len(st.session_state.td_text.splitlines())), "Lines in Data File", "sv-blue"),
    ])
    if blocked:
        st.warning(f"{len(blocked)} case(s) could not be generated — see **Not Covered** below and "
                   f"in the report. Coverage is incomplete until those are resolved.")

    if spec:
        with st.expander(f"Rules read from the BRD — {spec_summary(spec)['slots']} field rule(s)  ·  "
                         f"review this first", expanded=False):
            st.caption("The only stage that interprets the BRD. If a rule is wrong here, the data "
                       "generated from it is wrong too.")
            st.dataframe(pd.DataFrame([{
                "Rule": sl.get("slot_name", ""), "BRD Ref": sl.get("brd_ref", ""),
                "Value From": (sl.get("expected") or {}).get("kind", ""),
                "Format": (sl.get("expected") or {}).get("format", "") or "—",
            } for sl in spec.get("slots") or []]), use_container_width=True, hide_index=True)

    st.markdown('<div class="section-label">Data Map</div>', unsafe_allow_html=True)
    st.caption("Every generated value, the requirement it came from, and where it sits in the data "
               "file. The Line column is a Ctrl+G target in Notepad++; the Path stays valid even if "
               "you reformat the file.")
    df = pd.DataFrame([{
        "Record": r["record_index"],
        "Line": locs.get(f"{r['record_index']}/{r['path']}", ""),
        "BRD Reference": r.get("brd_ref", ""),
        "What This Value Tests": r.get("describes", ""),
        "Value Written": str(r.get("value", ""))[:120],
        "Path": display_path(r["path"], r["record_index"]),
    } for r in rows])
    st.dataframe(df, use_container_width=True, hide_index=True,
                 column_config={
                     "Record": st.column_config.NumberColumn("Rec", width="small"),
                     "Line": st.column_config.NumberColumn("Line", width="small"),
                     "BRD Reference": st.column_config.TextColumn("BRD Ref", width="small"),
                     "What This Value Tests": st.column_config.TextColumn("What This Value Tests", width="large"),
                     "Value Written": st.column_config.TextColumn("Value", width="medium"),
                     "Path": st.column_config.TextColumn("Path", width="large"),
                 })

    if blocked:
        st.markdown('<div class="section-label">Not Covered</div>', unsafe_allow_html=True)
        st.dataframe(pd.DataFrame([{
            "BRD Reference": getattr(c, "brd_ref", ""),
            "What Could Not Be Tested": getattr(c, "describes", ""),
            "Why": getattr(c, "blocked", ""),
        } for c in blocked]), use_container_width=True, hide_index=True)

    st.markdown('<div class="section-label">Expected Outcomes</div>', unsafe_allow_html=True)
    st.caption("What each record should produce — feed this alongside the data into Quality "
               "Intelligence and every finding is pre-labelled with what it proves.")
    st.dataframe(pd.DataFrame([{
        "Record": e["record_index"], "Documents Expected": len(e["letters"]),
        "Expected Addressees": " · ".join(f"{l.get('label','')}: {l.get('addressee_name','')}"
                                           for l in e["letters"]),
        "Correctly Suppressed": " · ".join(f"{l.get('label','')}" for l in e["suppressed"]) or "—",
    } for e in expected]), use_container_width=True, hide_index=True)

    st.markdown('<div class="export-box"><div class="export-title">Download</div>',
                unsafe_allow_html=True)
    mime = {"JSON": "application/json", "XML": "application/xml", "CSV": "text/csv"}[meta["format"]]
    d1, d2, d3 = st.columns(3)
    with d1:
        st.download_button(f"Download Test Data — {meta['format']}", data=st.session_state.td_text,
                           file_name=meta["data_filename"], mime=mime, use_container_width=True)
    with d2:
        st.download_button("Download Data Map — Excel", data=st.session_state.td_report,
                           file_name=f"{project_slug}_TestDataMap.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           use_container_width=True)
    with d3:
        st.download_button("Download Rules — JSON", data=json.dumps(spec, indent=2, default=str),
                           file_name=f"{project_slug}_MappingSpec.json", mime="application/json",
                           use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)
