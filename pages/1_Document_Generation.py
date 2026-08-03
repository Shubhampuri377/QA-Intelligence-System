import json

import pandas as pd
import streamlit as st
from docx import Document as DocxDoc

from styles.theme import inject_theme, nav_buttons, page_header, tbox, pipeline_bar, stats_row, icon
from utils.debug_log import DebugLog
from utils.llm_client import LLMClient, PROVIDER_MODELS, KEY_PLACEHOLDERS, estimate_cost
from utils.json_utils import safe_json
from utils.extraction import extract_multi_document, extract_pdf_comments, enforce_validations
from utils.word_export import frs_to_word
from utils.excel_export import build_excel
from utils.checklist_export import build_checklist_excel, build_direct_checklist_excel
from utils.checklist_agent import run_checklist_agent
from utils.naming import safe_filename_part
from prompts.frs_prompt import FRS_PROMPT
from prompts.test_case_prompt import TC_PROMPT

st.set_page_config(page_title="Document Generation", layout="wide", page_icon="📄",
                   initial_sidebar_state="expanded")
inject_theme()
nav_buttons("docs")

# ── SESSION STATE ──────────────────────────────────────────────
for k, v in {
    "frs": None, "frs_word_bytes": None, "test_cases": None, "tc_excel_bytes": None,
    "checklist_excel_bytes": None,
    "direct_checklist_bytes": None, "direct_checklist_count": None, "last_debug_checklist": None,
    "token_usage_studio": {"input": 0, "output": 0, "total": 0},
    "last_debug_frs": None, "last_debug_tc": None,
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

has_frs = st.session_state.frs is not None
has_tc = st.session_state.test_cases is not None
usage = st.session_state.token_usage_studio

page_header("layers", "Document Generation", "Requirements Engineering & QA",
            "One guided flow — Business Requirement Document → Functional Requirements → Test Cases / Checklist")

pn_col, _ = st.columns([2, 5])
with pn_col:
    project_name = st.text_input("Project Name", key="project_name_studio",
                                 placeholder="e.g. Credit Union Project",
                                 help="Used to name your downloaded files — e.g. ProjectName_FRS.docx")
project_slug = safe_filename_part(project_name)

# ── SHARED CONFIG ROW ───────────────────────────────────────────
provider_col, model_col, key_col, t1, t2, t3, t4 = st.columns([1.8, 2, 2.4, 1, 1, 1, 1])
with provider_col:
    llm_provider = st.selectbox("AI Provider", list(PROVIDER_MODELS.keys()), key="llm_provider_studio")
with model_col:
    model_name = st.selectbox("Model", PROVIDER_MODELS[llm_provider], key="model_studio")
with key_col:
    api_key = st.text_input(f"{llm_provider.split('(')[0].strip()} API Key", type="password",
                             placeholder=KEY_PLACEHOLDERS[llm_provider], key="api_k_studio")
with t1: st.markdown(tbox("Input", f"{usage['input']:,}"), unsafe_allow_html=True)
with t2: st.markdown(tbox("Output", f"{usage['output']:,}"), unsafe_allow_html=True)
with t3: st.markdown(tbox("Total", f"{usage['total']:,}"), unsafe_allow_html=True)
with t4:
    cost = estimate_cost(llm_provider, usage["input"], usage["output"])
    st.markdown(tbox("Est. Cost", f"${cost:.4f}", "tbox-green"), unsafe_allow_html=True)

st.markdown("<div style='margin-bottom:4px;'></div>", unsafe_allow_html=True)

# ── PIPELINE ──────────────────────────────────────────────────
s_frs = "done" if has_frs else "active"
s_tc = "done" if has_tc else ("active" if has_frs else "idle")
pipeline_bar([("document", "BRD", s_frs), ("layers", "FRS", "done" if has_frs else s_frs),
              ("flask", "Test Cases", "done" if has_tc else s_tc)])

# ═══════════════════════════════════════════════════════════════
# STEP 1 — BRD → FRS
# ═══════════════════════════════════════════════════════════════

st.markdown('<div class="section-label">Step 1 · BRD → FRS</div>', unsafe_allow_html=True)
st.markdown('<div class="page-heading">Convert a Business Requirement Document into Functional Requirements</div>', unsafe_allow_html=True)

uc1, uc2, uc3 = st.columns([2.2, 2.2, 1])
with uc1:
    st.markdown(f'<div class="upload-label">{icon("document", 14)} Business Requirement Document(s)</div>', unsafe_allow_html=True)
    brd_files = st.file_uploader("BRD", type=["pdf", "docx", "txt"], label_visibility="collapsed", key="brd_up",
                                 accept_multiple_files=True)
    st.markdown('<div class="upload-hint">PDF (text, tables, images, checkboxes, scanned+OCR) · Word · Plain text. Upload more than one to combine them into a single FRS, processed in upload order.</div>', unsafe_allow_html=True)
    if brd_files:
        pills = "".join(f'<div class="file-pill">{f.name}</div>' for f in brd_files)
        st.markdown(pills, unsafe_allow_html=True)
with uc2:
    st.markdown(f'<div class="upload-label">{icon("map", 14)} Mapping Document <span style="color:var(--text-faint);font-weight:500;text-transform:none;letter-spacing:0">(optional)</span></div>', unsafe_allow_html=True)
    mapping_file = st.file_uploader("Mapping", type=["pdf"], label_visibility="collapsed", key="map_up")
    st.markdown('<div class="upload-hint">PDF annotations only — for field name alignment</div>', unsafe_allow_html=True)
    if mapping_file:
        st.markdown(f'<div class="file-pill">{mapping_file.name}</div>', unsafe_allow_html=True)
with uc3:
    st.markdown('<div class="upload-label">Options</div>', unsafe_allow_html=True)
    debug_mode_frs = st.toggle("Debug", value=False, key="debug_mode_frs",
                                help="Show detailed logs for the LLM call and JSON parsing")

st.markdown("")
gc1, gc1b, _ = st.columns([2, 2, 3])
with gc1:
    gen_frs = st.button("Generate FRS", use_container_width=True, key="gen_frs_btn")
with gc1b:
    gen_checklist_direct = st.button("Generate Checklist Directly", use_container_width=True,
                                      key="gen_checklist_direct_btn")
st.caption("\"Generate Checklist Directly\" skips FRS entirely — extracts a verification checklist straight from the BRD + Mapping.")

if gen_checklist_direct:
    if not api_key:
        st.error("Enter your API key above.")
        st.stop()
    if not brd_files:
        st.error("Please upload at least one BRD file.")
        st.stop()

    dbg_c = DebugLog()

    with st.spinner("Reading documents…"):
        try:
            dbg_c.add("info", "EXTRACT", f"Reading BRD: {len(brd_files)} file(s)")
            brd_text_c = extract_multi_document(brd_files)
            dbg_c.add("ok", "EXTRACT", f"BRD extracted — {len(brd_text_c):,} chars")
            if not brd_text_c or brd_text_c.strip() in ["", "[EMPTY DOCUMENT]"]:
                dbg_c.add("err", "EXTRACT", "BRD text is empty — check file format")
                st.error("Could not extract text from BRD.")
                if debug_mode_frs: dbg_c.render()
                st.stop()
            mapping_text_c = "NO MAPPING PROVIDED"
            if mapping_file:
                dbg_c.add("info", "EXTRACT", f"Reading mapping: {mapping_file.name}")
                mapping_text_c = extract_pdf_comments(mapping_file) or "NO MAPPING PROVIDED"
                dbg_c.add("ok", "EXTRACT", f"Mapping extracted — {len(mapping_text_c):,} chars")
        except Exception as e:
            dbg_c.add("err", "EXTRACT", f"File read error: {e}")
            st.error(f"Error reading files: {e}")
            if debug_mode_frs: dbg_c.render()
            st.stop()

    with st.spinner(f"Generating checklist with {llm_provider}…"):
        try:
            client_c = LLMClient(llm_provider, api_key, model_name)
            items, usage_c = run_checklist_agent(brd_text_c, mapping_text_c, client_c, dbg_c)
            st.session_state.token_usage_studio["input"] += usage_c["input"]
            st.session_state.token_usage_studio["output"] += usage_c["output"]
            st.session_state.token_usage_studio["total"] += usage_c["total"]
        except Exception as e:
            st.error(f"LLM Error: {e}")
            if debug_mode_frs: dbg_c.render()
            else: st.info("Enable **Debug** above to see the full error trace.")
            st.stop()

    if not items:
        st.error("Failed to generate a checklist from the BRD. See debug log for details.")
        if debug_mode_frs: dbg_c.render()
        else: st.info("Enable **Debug** above for the full trace.")
        st.stop()

    dbg_c.add("ok", "COMPLETE", f"Checklist generation successful — {len(items)} item(s)")
    st.session_state.direct_checklist_bytes = build_direct_checklist_excel(items, project_name=project_name)
    st.session_state.direct_checklist_count = len(items)
    st.session_state.last_debug_checklist = dbg_c
    st.rerun()

if st.session_state.get("last_debug_checklist") and debug_mode_frs:
    with st.expander("Last direct-checklist generation debug log", expanded=False):
        st.session_state.last_debug_checklist.render()

if st.session_state.direct_checklist_bytes:
    st.markdown('<div class="export-box"><div class="export-title">Checklist — Generated Directly from BRD</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="file-pill">{st.session_state.direct_checklist_count} checklist item(s)</div>', unsafe_allow_html=True)
    st.download_button("Download Checklist — Excel (.xlsx)", data=st.session_state.direct_checklist_bytes,
        file_name=f"{project_slug}_BRD_Checklist.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True, key="dl_direct_checklist")
    st.markdown('</div>', unsafe_allow_html=True)

if gen_frs:
    if not api_key:
        st.error("Enter your API key above.")
        st.stop()
    if not brd_files:
        st.error("Please upload at least one BRD file.")
        st.stop()

    dbg = DebugLog()

    with st.spinner("Reading documents…"):
        try:
            dbg.add("info", "EXTRACT", f"Reading BRD: {len(brd_files)} file(s)")
            brd_text = extract_multi_document(brd_files)
            dbg.add("ok", "EXTRACT", f"BRD extracted — {len(brd_text):,} chars")
            if not brd_text or brd_text.strip() in ["", "[EMPTY DOCUMENT]"]:
                dbg.add("err", "EXTRACT", "BRD text is empty — check file format")
                st.error("Could not extract text from BRD.")
                if debug_mode_frs: dbg.render()
                st.stop()
            mapping_text = "NO MAPPING PROVIDED"
            if mapping_file:
                dbg.add("info", "EXTRACT", f"Reading mapping: {mapping_file.name}")
                mapping_text = extract_pdf_comments(mapping_file) or "NO MAPPING PROVIDED"
                dbg.add("ok", "EXTRACT", f"Mapping extracted — {len(mapping_text):,} chars")
        except Exception as e:
            dbg.add("err", "EXTRACT", f"File read error: {e}")
            st.error(f"Error reading files: {e}")
            if debug_mode_frs: dbg.render()
            st.stop()

    with st.spinner(f"Generating FRS with {llm_provider}…"):
        try:
            prompt = FRS_PROMPT.format(brd=brd_text, mapping=mapping_text)
            dbg.add("info", "PROMPT", f"Prompt assembled — {len(prompt):,} chars total")
            client = LLMClient(llm_provider, api_key, model_name)
            result = client.run(prompt, dbg)
            st.session_state.token_usage_studio["input"] += result["input_tokens"]
            st.session_state.token_usage_studio["output"] += result["output_tokens"]
            st.session_state.token_usage_studio["total"] += result["total_tokens"]
        except Exception as e:
            st.error(f"LLM Error: {e}")
            if debug_mode_frs: dbg.render()
            else: st.info("Enable **Debug** above to see the full error trace.")
            st.stop()

    dbg.add("info", "PARSE", "Parsing LLM response as JSON…")
    raw_text = result.get("text", "")
    frs = safe_json(raw_text, dbg)

    if not isinstance(frs, list) or not frs:
        st.error("Failed to parse FRS from model output. See debug log for details.")
        if debug_mode_frs: dbg.render()
        else:
            st.info("Enable **Debug** above for the full parse trace.")
            with st.expander("Raw model output (first 1000 chars)"):
                st.code(raw_text[:1000])
        st.stop()

    dbg.add("ok", "COMPLETE", f"FRS generation successful — {len(frs)} requirements")
    st.session_state.frs = enforce_validations(frs)
    st.session_state.frs_word_bytes = None
    st.session_state.test_cases = None
    st.session_state.tc_excel_bytes = None
    st.session_state.checklist_excel_bytes = None
    st.session_state.last_debug_frs = dbg
    st.rerun()

if st.session_state.get("last_debug_frs") and debug_mode_frs:
    with st.expander("Last FRS generation debug log", expanded=False):
        st.session_state.last_debug_frs.render()

if st.session_state.frs:
    frs = st.session_state.frs
    st.markdown('<div class="section-label">Results</div>', unsafe_allow_html=True)
    total_rules = sum(len(fr.get("Business Rules", [])) for fr in frs)
    total_vals = sum(len(fr.get("Validations", [])) for fr in frs)
    all_actors = {a for fr in frs for a in fr.get("Actors", [])}
    stats_row([
        ("sb-purple", str(len(frs)), "Requirements", "sv-purple"),
        ("sb-amber", str(total_rules), "Business Rules", "sv-amber"),
        ("sb-green", str(total_vals), "Validations", "sv-green"),
        ("sb-red", str(len(all_actors)), "Actors", "sv-red"),
    ])

    st.markdown('<div class="section-label">Functional Requirements</div>', unsafe_allow_html=True)
    for fr in frs:
        tags = "".join(f'<span class="fr-tag">{a}</span>' for a in fr.get("Actors", [])[:4])
        with st.expander(f"{fr.get('FR_ID', '')}  ·  {fr.get('Feature', '')}", expanded=False):
            st.markdown(f"""<div style="margin-bottom:10px;">
              <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
                <span class="fr-id">{fr.get('FR_ID', '')}</span>
                <span class="fr-feature">{fr.get('Feature', '')}</span>
              </div>
              <div class="fr-desc">{fr.get('Description', '')}</div>
              <div class="fr-tags">{tags}</div>
            </div>""", unsafe_allow_html=True)
            ec1, ec2, ec3 = st.columns(3)
            with ec1:
                st.markdown('<div class="data-caption">Inputs / Outputs</div>', unsafe_allow_html=True)
                for i in fr.get("Inputs", []): st.markdown(f'<div class="t-io">→ {i}</div>', unsafe_allow_html=True)
                for o in fr.get("Outputs", []): st.markdown(f'<div class="t-io">← {o}</div>', unsafe_allow_html=True)
            with ec2:
                st.markdown('<div class="data-caption">Business Rules</div>', unsafe_allow_html=True)
                for r in fr.get("Business Rules", []): st.markdown(f'<div class="t-rule">{r}</div>', unsafe_allow_html=True)
            with ec3:
                st.markdown('<div class="data-caption">Validations</div>', unsafe_allow_html=True)
                for v in fr.get("Validations", []): st.markdown(f'<div class="t-val">{v}</div>', unsafe_allow_html=True)

    st.markdown('<div class="export-box"><div class="export-title">Export FRS</div>', unsafe_allow_html=True)
    if st.session_state.frs_word_bytes is None:
        with st.spinner("Building Word document…"):
            try:
                st.session_state.frs_word_bytes = frs_to_word(frs, project_name=project_name)
            except Exception as e:
                st.error(f"Word export error: {e}")
    dc1, dc2 = st.columns(2)
    with dc1:
        if st.session_state.frs_word_bytes:
            st.download_button("Download FRS — Word (.docx)", data=st.session_state.frs_word_bytes,
                file_name=f"{project_slug}_FRS.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True)
    with dc2:
        st.download_button("Download FRS — JSON", data=json.dumps(frs, indent=2),
            file_name=f"{project_slug}_FRS.json", mime="application/json", use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)

st.markdown('<hr class="divider-soft">', unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════
# STEP 2 — FRS → TEST CASES
# ═══════════════════════════════════════════════════════════════

st.markdown('<div class="section-label">Step 2 · FRS → Test Cases</div>', unsafe_allow_html=True)
st.markdown('<div class="page-heading">Generate an Enterprise QA Test Suite from the FRS</div>', unsafe_allow_html=True)

if not st.session_state.frs:
    st.info("Generate an FRS in **Step 1** above, or upload an existing FRS file below to skip straight to test cases.")

if st.session_state.frs:
    st.markdown(f'<div class="file-pill">Using FRS from Step 1 &nbsp;·&nbsp; {len(st.session_state.frs)} requirements</div>', unsafe_allow_html=True)
    st.markdown("<div style='margin-bottom:6px;'></div>", unsafe_allow_html=True)

tuc1, tuc2 = st.columns([3, 1])
with tuc1:
    st.markdown(f'<div class="upload-label">{icon("layers", 14)} Or upload a Functional Requirement Specification</div>', unsafe_allow_html=True)
    frs_file = st.file_uploader("FRS", type=["json", "docx"], label_visibility="collapsed", key="frs_up")
    st.markdown('<div class="upload-hint">JSON from Step 1, or a DOCX version</div>', unsafe_allow_html=True)
with tuc2:
    st.markdown('<div class="upload-label">Options</div>', unsafe_allow_html=True)
    debug_mode_tc = st.toggle("Debug", value=False, key="debug_mode_tc",
                              help="Show detailed logs for the LLM call and JSON parsing")

if frs_file:
    try:
        if frs_file.name.endswith(".json"):
            loaded = json.loads(frs_file.read().decode("utf-8"))
            st.session_state.frs = loaded if isinstance(loaded, list) else []
        else:
            d = DocxDoc(frs_file)
            text = "\n".join((p.text or "").strip() for p in d.paragraphs if (p.text or "").strip())
            dummy_dbg = DebugLog()
            st.session_state.frs = safe_json(text, dummy_dbg)
        if st.session_state.frs:
            st.markdown(f'<div class="file-pill">{frs_file.name} &nbsp;·&nbsp; {len(st.session_state.frs)} requirements</div>', unsafe_allow_html=True)
        else:
            st.warning("Could not parse FRS from file. Ensure it is a valid JSON array.")
    except Exception as e:
        st.error(f"Error loading FRS file: {e}")

st.markdown("")
gc2, _ = st.columns([2, 5])
with gc2:
    gen_tc = st.button("Generate Test Cases", use_container_width=True, key="gen_tc_btn",
                       disabled=not st.session_state.frs)

if gen_tc:
    if not api_key:
        st.error("Enter your API key above.")
        st.stop()
    if not st.session_state.frs:
        st.error("Please provide an FRS (from Step 1, or upload a file) first.")
        st.stop()

    dbg = DebugLog()

    with st.spinner(f"Generating test cases with {llm_provider}…"):
        try:
            frs_json = json.dumps(st.session_state.frs, indent=2)
            prompt = TC_PROMPT.format(frs=frs_json)
            dbg.add("info", "PROMPT", f"TC prompt assembled — FRS has {len(st.session_state.frs)} FRs")
            client = LLMClient(llm_provider, api_key, model_name)
            result = client.run(prompt, dbg)
            st.session_state.token_usage_studio["input"] += result["input_tokens"]
            st.session_state.token_usage_studio["output"] += result["output_tokens"]
            st.session_state.token_usage_studio["total"] += result["total_tokens"]
        except Exception as e:
            st.error(f"LLM Error: {e}")
            if debug_mode_tc: dbg.render()
            else: st.info("Enable **Debug** above to see the full error trace.")
            st.stop()

    dbg.add("info", "PARSE", "Parsing test cases from LLM response…")
    raw_text = result.get("text", "")
    tc_list = safe_json(raw_text, dbg)

    if not tc_list:
        st.error("Failed to generate test cases. See debug log for details.")
        if debug_mode_tc: dbg.render()
        else:
            st.info("Enable **Debug** above for the full trace.")
            with st.expander("Raw model output (first 1000 chars)"):
                st.code(raw_text[:1000])
        st.stop()

    dbg.add("ok", "COMPLETE", f"Test case generation successful — {len(tc_list)} test cases")
    df = pd.DataFrame(tc_list).reindex(
        columns=["TC_ID", "FR_ID", "Description", "Expected Result", "Priority", "Severity", "Test Type", "QA Status"])
    df["TC_ID"] = [f"TC_{i + 1:03d}" for i in range(len(df))]
    df["QA Status"] = "Draft"
    df.fillna("", inplace=True)
    st.session_state.test_cases = df
    st.session_state.tc_excel_bytes = None
    st.session_state.last_debug_tc = dbg

    st.rerun()

if st.session_state.get("last_debug_tc") and debug_mode_tc:
    with st.expander("Last test case generation debug log", expanded=False):
        st.session_state.last_debug_tc.render()

if st.session_state.test_cases is not None:
    df = st.session_state.test_cases
    st.markdown('<div class="section-label">Coverage Summary</div>', unsafe_allow_html=True)
    high_c = len(df[df["Priority"].str.lower() == "high"]) if "Priority" in df.columns else 0
    crit_c = len(df[df["Severity"].str.lower() == "critical"]) if "Severity" in df.columns else 0
    fr_c = df["FR_ID"].nunique() if "FR_ID" in df.columns else 0
    stats_row([
        ("sb-purple", str(len(df)), "Test Cases", "sv-purple"),
        ("sb-red", str(high_c), "High Priority", "sv-red"),
        ("sb-amber", str(crit_c), "Critical", "sv-amber"),
        ("sb-green", str(fr_c), "FRs Covered", "sv-green"),
    ])

    if "Test Type" in df.columns:
        chips = "".join(f'<div class="chip"><span>{t}</span><span class="chip-count">{c}</span></div>'
                        for t, c in df["Test Type"].value_counts().items())
        st.markdown(f'<div class="chips-row">{chips}</div>', unsafe_allow_html=True)

    st.markdown('<div class="section-label">Test Cases</div>', unsafe_allow_html=True)
    st.dataframe(df, use_container_width=True, hide_index=True,
        column_config={
            "TC_ID": st.column_config.TextColumn("TC ID", width="small"),
            "FR_ID": st.column_config.TextColumn("FR ID", width="small"),
            "Description": st.column_config.TextColumn("Description", width="large"),
            "Expected Result": st.column_config.TextColumn("Expected Result", width="large"),
            "Priority": st.column_config.TextColumn("Priority", width="small"),
            "Severity": st.column_config.TextColumn("Severity", width="small"),
            "Test Type": st.column_config.TextColumn("Test Type", width="medium"),
            "QA Status": st.column_config.TextColumn("Status", width="small"),
        })

    st.markdown('<div class="export-box"><div class="export-title">Export Test Cases</div>', unsafe_allow_html=True)
    if not st.session_state.tc_excel_bytes:
        with st.spinner("Building Excel report…"):
            try:
                st.session_state.tc_excel_bytes = build_excel(df, frs_lookup_source=st.session_state.frs,
                                                               project_name=project_name)
            except Exception as e:
                st.error(f"Excel export error: {e}")
    edc1, edc2 = st.columns(2)
    with edc1:
        if st.session_state.tc_excel_bytes:
            st.download_button("Download Test Cases — Excel (.xlsx)", data=st.session_state.tc_excel_bytes,
                file_name=f"{project_slug}_TestCases.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True)
    with edc2:
        if st.session_state.checklist_excel_bytes is None and st.session_state.frs:
            try:
                st.session_state.checklist_excel_bytes = build_checklist_excel(st.session_state.frs,
                                                                                project_name=project_name)
            except Exception as e:
                st.error(f"Checklist export error: {e}")
        if st.session_state.checklist_excel_bytes:
            st.download_button("Download Checklist — Excel (.xlsx)", data=st.session_state.checklist_excel_bytes,
                file_name=f"{project_slug}_Checklist.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                help="A lightweight sign-off checklist derived directly from the FRS — for projects that don't need a full formal test case suite.")
    st.markdown('</div>', unsafe_allow_html=True)

st.markdown('<hr class="divider-soft">', unsafe_allow_html=True)
st.info("Need test data? It now has its own page — **Data Generation** in the sidebar. It reads the BRD "
        "directly, so you don't need to generate an FRS first.")
