"""Builds a formal, enterprise-style Excel (.xlsx) test-case report — cover/
document info, data sheet, and FR coverage matrix — in the same navy/gray
corporate palette as the FRS Word deliverable."""

from datetime import date as _date
from io import BytesIO

import streamlit as st
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

NAVY = "1F3A5F"
DARK = "1F2937"
GRAY = "5B6370"
LIGHT_BG = "F2F3F5"
WHITE = "FFFFFF"
BORDER_CLR = "B9C0CB"


def _hex_fill(h):
    return PatternFill(start_color=h, end_color=h, fill_type="solid")


def _thin_border(c=BORDER_CLR):
    s = Side(style="thin", color=c)
    return Border(left=s, right=s, top=s, bottom=s)


def _cal(size=9, bold=False, color=DARK, italic=False):
    return Font(name="Calibri", size=size, bold=bold, color=color, italic=italic)


def _align(h="left", v="center", wrap=False):
    return Alignment(horizontal=h, vertical=v, wrap_text=wrap)


def _p_colors(p):
    p = (p or "").lower()
    if p == "high":
        return ("FBEAEA", "B42318")
    if p == "medium":
        return ("FEF6E7", "B54708")
    return ("EAF7EE", "15803D")


def _s_colors(s):
    s = (s or "").lower()
    if s == "critical":
        return ("FBEAEA", "B42318")
    if s == "major":
        return ("FEF6E7", "B54708")
    return ("EAF7EE", "15803D")


def build_excel(df, frs_lookup_source=None, project_name: str = "") -> bytes:
    """frs_lookup_source: optional list of FR dicts (FR_ID/Feature/Description) used
    to enrich the FR Coverage sheet with a feature description column."""
    wb = Workbook()

    project_label = project_name.strip() if project_name and project_name.strip() else "Client Engagement"
    today_str = _date.today().strftime("%B %d, %Y")

    total = len(df)
    high = len(df[df["Priority"].str.lower() == "high"]) if "Priority" in df.columns else 0
    med = len(df[df["Priority"].str.lower() == "medium"]) if "Priority" in df.columns else 0
    low = len(df[df["Priority"].str.lower() == "low"]) if "Priority" in df.columns else 0
    crit = len(df[df["Severity"].str.lower() == "critical"]) if "Severity" in df.columns else 0
    fr_cov = df["FR_ID"].nunique() if "FR_ID" in df.columns else 0
    tt_counts = df["Test Type"].value_counts() if "Test Type" in df.columns else {}

    # ── Cover / Document Info sheet ──
    cover = wb.active
    cover.title = "Cover"
    cover.sheet_view.showGridLines = False
    for col, w in [("A", 2), ("B", 26), ("C", 20), ("D", 2)]:
        cover.column_dimensions[col].width = w

    cover.row_dimensions[2].height = 28
    cover.merge_cells("B2:C2")
    title = cover["B2"]
    title.value = "TEST CASE SPECIFICATION"
    title.font = Font(name="Calibri", size=20, bold=True, color=NAVY)
    title.alignment = _align("left", "center")

    cover.row_dimensions[3].height = 20
    cover.merge_cells("B3:C3")
    sub = cover["B3"]
    sub.value = project_label
    sub.font = _cal(13, bold=True, color=GRAY)
    sub.alignment = _align("left")

    cover.row_dimensions[4].height = 6
    for c in range(2, 4):
        cover.cell(4, c).fill = _hex_fill(NAVY)

    info_rows = [
        ("Document Title", "Test Case Specification"),
        ("Project", project_label),
        ("Document Version", "1.0"),
        ("Status", "Draft"),
        ("Date", today_str),
        ("Classification", "Confidential — Internal & Client Use Only"),
        ("Total Test Cases", str(total)),
        ("Requirements Covered", str(fr_cov)),
    ]
    r = 6
    for label, value in info_rows:
        cover.row_dimensions[r].height = 20
        lc = cover.cell(r, 2, label)
        lc.fill = _hex_fill(LIGHT_BG)
        lc.font = _cal(9, bold=True)
        lc.alignment = _align("left")
        lc.border = _thin_border()
        vc = cover.cell(r, 3, value)
        vc.font = _cal(9.5)
        vc.alignment = _align("left")
        vc.border = _thin_border()
        r += 1

    r += 1
    cover.row_dimensions[r].height = 18
    h1 = cover.cell(r, 2, "Priority Breakdown")
    h1.font = _cal(10, bold=True, color=NAVY)
    r += 1
    for label, count, (bg, fg) in [("High", high, _p_colors("high")),
                                     ("Medium", med, _p_colors("medium")),
                                     ("Low", low, _p_colors("low"))]:
        cover.row_dimensions[r].height = 18
        lc = cover.cell(r, 2, label)
        lc.fill = _hex_fill(LIGHT_BG); lc.font = _cal(9); lc.border = _thin_border()
        vc = cover.cell(r, 3, str(count))
        vc.fill = _hex_fill(bg); vc.font = _cal(9, bold=True, color=fg); vc.alignment = _align("center")
        vc.border = _thin_border()
        r += 1

    r += 1
    cover.row_dimensions[r].height = 18
    h2 = cover.cell(r, 2, "Test Type Coverage")
    h2.font = _cal(10, bold=True, color=NAVY)
    r += 1
    for tt, cnt_val in tt_counts.items():
        cover.row_dimensions[r].height = 18
        lc = cover.cell(r, 2, str(tt))
        lc.fill = _hex_fill(LIGHT_BG); lc.font = _cal(9); lc.border = _thin_border()
        vc = cover.cell(r, 3, str(cnt_val))
        vc.font = _cal(9, bold=True); vc.alignment = _align("center")
        vc.border = _thin_border()
        r += 1

    r += 2
    footer = cover.cell(r, 2, f"Confidential — For Internal & Client Use Only  |  Generated {today_str}")
    footer.font = _cal(8, italic=True, color=GRAY)

    # ── Test case data sheet ──
    ws = wb.create_sheet("Test Cases")
    ws.sheet_view.showGridLines = False
    COLS = ["TC_ID", "FR_ID", "Description", "Expected Result", "Priority", "Severity", "Test Type", "QA Status"]
    WIDTHS = [10, 10, 54, 44, 12, 12, 20, 12]
    HALIGN = ["center", "center", "left", "left", "center", "center", "center", "center"]
    ws.row_dimensions[1].height = 26
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(COLS))}1"
    for ci, (col, w, ha) in enumerate(zip(COLS, WIDTHS, HALIGN), 1):
        ws.column_dimensions[get_column_letter(ci)].width = w
        cell = ws.cell(1, ci, col)
        cell.fill = _hex_fill(NAVY)
        cell.font = Font(name="Calibri", size=10, bold=True, color=WHITE)
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = _thin_border(NAVY)
    for ri, (_, row_data) in enumerate(df.iterrows(), 2):
        desc = str(row_data.get("Description", "") or "")
        expected = str(row_data.get("Expected Result", "") or "")
        ws.row_dimensions[ri].height = max(25, min(100, 20 + (max(len(desc), len(expected)) // 40) * 15))
        is_even = ri % 2 == 0
        row_bg = WHITE if is_even else LIGHT_BG
        for ci, (col, ha) in enumerate(zip(COLS, HALIGN), 1):
            val = str(row_data.get(col, "") or "")
            cell = ws.cell(ri, ci, val)
            cell.alignment = Alignment(horizontal=ha, vertical="center", wrap_text=(col in ["Description", "Expected Result"]))
            cell.border = _thin_border()
            if col == "TC_ID":
                cell.fill = _hex_fill(row_bg)
                cell.font = _cal(9, bold=True, color=NAVY)
            elif col == "FR_ID":
                cell.fill = _hex_fill(row_bg)
                cell.font = _cal(9, bold=True, color=DARK)
            elif col == "Priority":
                bg, fg = _p_colors(val)
                cell.fill = _hex_fill(bg)
                cell.font = _cal(9, bold=True, color=fg)
            elif col == "Severity":
                bg, fg = _s_colors(val)
                cell.fill = _hex_fill(bg)
                cell.font = _cal(9, bold=True, color=fg)
            elif col == "QA Status":
                cell.fill = _hex_fill(row_bg)
                cell.font = _cal(9, italic=True, color=GRAY)
            else:
                cell.fill = _hex_fill(row_bg)
                cell.font = _cal(9, color=DARK)

    # ── FR coverage matrix ──
    matrix = wb.create_sheet("FR Coverage")
    matrix.sheet_view.showGridLines = False
    matrix.row_dimensions[1].height = 30
    matrix.merge_cells("A1:H1")
    mh = matrix["A1"]
    mh.value = "FR Coverage Matrix"
    mh.font = Font(name="Calibri", size=13, bold=True, color=NAVY)
    mh.fill = _hex_fill(LIGHT_BG)
    mh.alignment = _align("left", "center")
    matrix.row_dimensions[3].height = 26
    m_cols = ["FR ID", "Feature / Description", "Total TCs", "Functional", "Negative", "Edge/Boundary", "High Priority", "Critical"]
    m_widths = [12, 36, 10, 12, 12, 14, 14, 12]
    for ci, (c, w) in enumerate(zip(m_cols, m_widths), 1):
        matrix.column_dimensions[get_column_letter(ci)].width = w
        cell = matrix.cell(3, ci, c)
        cell.fill = _hex_fill(NAVY)
        cell.font = _cal(9, bold=True, color=WHITE)
        cell.alignment = _align("center")
        cell.border = _thin_border(NAVY)

    frs_lookup = {}
    source_frs = frs_lookup_source
    if source_frs is None and hasattr(st, "session_state"):
        source_frs = st.session_state.get("frs")
    if source_frs:
        for fr in source_frs:
            fid = fr.get("FR_ID", "")
            feat = fr.get("Feature", "")
            desc = fr.get("Description", "")
            if fid:
                frs_lookup[fid] = f"{feat} — {desc[:60]}…" if len(desc) > 60 else (f"{feat} — {desc}" if desc else feat)

    fr_groups = df.groupby("FR_ID") if "FR_ID" in df.columns else {}
    for ri, (fr_id, grp) in enumerate(fr_groups, 4):
        matrix.row_dimensions[ri].height = 32
        is_even = ri % 2 == 0
        bg2 = WHITE if is_even else LIGHT_BG
        total_n = len(grp)
        func_n2 = len(grp[grp["Test Type"].str.lower().str.contains("functional", na=False)]) if "Test Type" in grp.columns else 0
        neg_n = len(grp[grp["Test Type"].str.lower().str.contains("negative", na=False)]) if "Test Type" in grp.columns else 0
        rule_n = len(grp[grp["Test Type"].str.lower().str.contains("edge|boundary", na=False)]) if "Test Type" in grp.columns else 0
        high_n = len(grp[grp["Priority"].str.lower() == "high"]) if "Priority" in grp.columns else 0
        crit_n = len(grp[grp["Severity"].str.lower() == "critical"]) if "Severity" in grp.columns else 0
        feature_desc = frs_lookup.get(fr_id, "")
        row_vals = [fr_id, feature_desc, total_n, func_n2, neg_n, rule_n, high_n, crit_n]
        for ci, val in enumerate(row_vals, 1):
            cell = matrix.cell(ri, ci, val)
            cell.border = _thin_border()
            if ci == 1:
                cell.fill = _hex_fill(bg2)
                cell.font = _cal(9, bold=True, color=NAVY)
                cell.alignment = _align("center")
            elif ci == 2:
                cell.fill = _hex_fill(bg2)
                cell.font = _cal(8, color=DARK)
                cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
            elif ci == 3:
                cell.fill = _hex_fill(bg2)
                cell.font = _cal(9, bold=True, color=NAVY)
                cell.alignment = _align("center")
            elif ci == 7:
                bg, fg = _p_colors("high") if high_n > 0 else (bg2, GRAY)
                cell.fill = _hex_fill(bg)
                cell.font = _cal(9, bold=(high_n > 0), color=fg)
                cell.alignment = _align("center")
            elif ci == 8:
                bg, fg = _s_colors("critical") if crit_n > 0 else (bg2, GRAY)
                cell.fill = _hex_fill(bg)
                cell.font = _cal(9, bold=(crit_n > 0), color=fg)
                cell.alignment = _align("center")
            else:
                cell.fill = _hex_fill(bg2)
                cell.font = _cal(9, color=DARK)
                cell.alignment = _align("center")

    wb.active = cover
    out = BytesIO()
    wb.save(out)
    out.seek(0)
    return out.read()
