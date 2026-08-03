"""Builds a lightweight sign-off Checklist (.xlsx) directly from an FRS —
no LLM call involved. Two views, in the same workbook:

  1. Rule Checklist  — every Business Rule, Condition, Validation, and
     Mapped Field becomes one tickable line. Verifies LOGIC.
  2. Field Checklist — every literal Input/Output field becomes one
     tickable line ("Account Number — checked", "Statement Date — checked").
     Verifies that each field actually renders correctly in the output —
     the field-by-field walkthrough QA does against a generated document.

Meant for projects/change requests that don't need a full formal Test Case
suite, just a fast "did we cover everything" walkthrough."""

from datetime import date as _date
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, PatternFill, Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.formatting.rule import CellIsRule

from utils.excel_export import NAVY, DARK, GRAY, LIGHT_BG, WHITE, _hex_fill, _thin_border, _cal, _align


def _rule_items_for_fr(fr: dict) -> list:
    """Flattens one FR's Business Rules / Conditions / Validations / Mapped
    Fields into (category, item_text) pairs. Falls back to a single general
    item if the FR has none of those — every requirement gets at least one
    checklist line."""
    items = []
    for rule in fr.get("Business Rules", []) or []:
        items.append(("Business Rule", str(rule)))
    for cond in fr.get("Conditions", []) or []:
        items.append(("Condition", str(cond)))
    for val in fr.get("Validations", []) or []:
        items.append(("Validation", str(val)))
    mapped = fr.get("Mapped Fields", {}) or {}
    if isinstance(mapped, dict):
        for k, v in mapped.items():
            if k and v:
                items.append(("Data Mapping", f"{k} correctly maps to {v}"))
    if not items:
        feature = fr.get("Feature", "") or fr.get("FR_ID", "")
        desc = (fr.get("Description", "") or "").strip()
        text = f"{feature} behaves as described" + (f": {desc}" if desc else "")
        items.append(("General", text))
    return items


def _field_items_for_fr(fr: dict) -> list:
    """Flattens one FR's Outputs and Inputs into (direction, field_text)
    pairs — one line per literal field, for a field-by-field 'does this
    render correctly' walkthrough. Outputs listed first since that's what
    gets visually checked against the generated document; Inputs follow
    for traceability back to the source data."""
    items = []
    for f in fr.get("Outputs", []) or []:
        items.append(("Output", str(f)))
    for f in fr.get("Inputs", []) or []:
        items.append(("Input", str(f)))
    return items


def _add_status_column(ws, status_col_letter: str, last_row: int):
    """Adds a Pass/Fail/Blocked/N/A dropdown plus auto color-coding to the
    Status column so it reads like a real defect-tracking sheet once filled in."""
    dv = DataValidation(type="list", formula1='"Pass,Fail,Blocked,N/A"', allow_blank=True)
    ws.add_data_validation(dv)
    rng = f"{status_col_letter}2:{status_col_letter}{last_row}"
    dv.add(rng)
    ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=['"Pass"'],
        fill=PatternFill("solid", fgColor="EAF7EE"), font=Font(name="Calibri", size=9, bold=True, color="15803D")))
    ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=['"Fail"'],
        fill=PatternFill("solid", fgColor="FBEAEA"), font=Font(name="Calibri", size=9, bold=True, color="B42318")))
    ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=['"Blocked"'],
        fill=PatternFill("solid", fgColor="FEF6E7"), font=Font(name="Calibri", size=9, bold=True, color="B54708")))
    return dv


def _add_checklist_sheet(wb, name: str, rows: list, col3_label: str):
    """rows: list of (item_id, fr_id, col3_value, text) tuples."""
    ws = wb.create_sheet(name)
    ws.sheet_view.showGridLines = False
    COLS = ["Item ID", "FR ID", col3_label, "Item", "Status", "Bug ID", "Jira Link", "Notes"]
    WIDTHS = [10, 10, 14, 54, 10, 12, 24, 22]
    ws.row_dimensions[1].height = 26
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(COLS))}1"
    for ci, (col, w) in enumerate(zip(COLS, WIDTHS), 1):
        ws.column_dimensions[get_column_letter(ci)].width = w
        cell = ws.cell(1, ci, col)
        cell.fill = _hex_fill(NAVY)
        cell.font = _cal(10, bold=True, color=WHITE)
        cell.alignment = _align("center")
        cell.border = _thin_border(NAVY)

    for ri, (item_id, fr_id, col3_val, text) in enumerate(rows, 2):
        is_even = ri % 2 == 0
        row_bg = WHITE if is_even else LIGHT_BG
        ws.row_dimensions[ri].height = max(24, 18 + (len(text) // 60) * 14)
        values = [item_id, fr_id, col3_val, text, "", "", "", ""]
        for ci, val in enumerate(values, 1):
            cell = ws.cell(ri, ci, val)
            cell.border = _thin_border()
            wrap = ci == 4
            cell.alignment = Alignment(horizontal=("left" if ci in (4, 7, 8) else "center"),
                                        vertical="center", wrap_text=wrap)
            if ci == 1:
                cell.fill = _hex_fill(row_bg); cell.font = _cal(9, bold=True, color=NAVY)
            elif ci == 2:
                cell.fill = _hex_fill(row_bg); cell.font = _cal(9, bold=True, color=DARK)
            elif ci == 3:
                cell.fill = _hex_fill(row_bg); cell.font = _cal(9, color=GRAY)
            elif ci == 4:
                cell.fill = _hex_fill(row_bg); cell.font = _cal(9.5, color=DARK)
            elif ci == 5:
                cell.fill = _hex_fill(row_bg); cell.font = _cal(9, bold=True, color=DARK)
            else:
                cell.fill = _hex_fill(row_bg); cell.font = _cal(9, color=DARK)

    if rows:
        _add_status_column(ws, "E", len(rows) + 1)
    return ws


def build_checklist_excel(frs: list, project_name: str = "") -> bytes:
    wb = Workbook()
    project_label = project_name.strip() if project_name and project_name.strip() else "Client Engagement"
    today_str = _date.today().strftime("%B %d, %Y")

    rule_rows, counter = [], 1
    for fr in frs:
        fr_id = fr.get("FR_ID", "")
        for category, text in _rule_items_for_fr(fr):
            rule_rows.append((f"CHK-{counter:03d}", fr_id, category, text))
            counter += 1

    field_rows, counter = [], 1
    for fr in frs:
        fr_id = fr.get("FR_ID", "")
        for direction, text in _field_items_for_fr(fr):
            field_rows.append((f"FLD-{counter:03d}", fr_id, direction, text))
            counter += 1

    # ── Cover / Document Info sheet ──
    cover = wb.active
    cover.title = "Cover"
    cover.sheet_view.showGridLines = False
    for col, w in [("A", 2), ("B", 26), ("C", 20), ("D", 2)]:
        cover.column_dimensions[col].width = w

    cover.row_dimensions[2].height = 28
    cover.merge_cells("B2:C2")
    title = cover["B2"]
    title.value = "REQUIREMENT CHECKLIST"
    title.font = _cal(20, bold=True, color=NAVY)
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
        ("Document Title", "Requirement Checklist"),
        ("Project", project_label),
        ("Document Version", "1.0"),
        ("Status", "Draft"),
        ("Date", today_str),
        ("Classification", "Confidential — Internal & Client Use Only"),
        ("Total Requirements", str(len(frs))),
        ("Rule Checklist Items", str(len(rule_rows))),
        ("Field Checklist Items", str(len(field_rows))),
    ]
    r = 6
    for label, value in info_rows:
        cover.row_dimensions[r].height = 20
        lc = cover.cell(r, 2, label)
        lc.fill = _hex_fill(LIGHT_BG); lc.font = _cal(9, bold=True); lc.alignment = _align("left")
        lc.border = _thin_border()
        vc = cover.cell(r, 3, value)
        vc.font = _cal(9.5); vc.alignment = _align("left"); vc.border = _thin_border()
        r += 1

    r += 2
    note = cover.cell(r, 2, "Rule Checklist verifies business rules, conditions, and validations. "
                             "Field Checklist verifies every individual field renders correctly in "
                             "the generated document — a field-by-field walkthrough in place of a "
                             "full formal test case suite.")
    note.font = _cal(9, italic=True, color=GRAY)
    cover.merge_cells(start_row=r, start_column=2, end_row=r, end_column=3)
    cover.row_dimensions[r].height = 44
    note.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)

    _add_checklist_sheet(wb, "Rule Checklist", rule_rows, "Category")
    _add_checklist_sheet(wb, "Field Checklist", field_rows, "Direction")

    wb.active = cover
    out = BytesIO()
    wb.save(out)
    out.seek(0)
    return out.read()


def _add_direct_checklist_sheet(wb, name: str, rows: list):
    """rows: list of (item_id, section, category, text) tuples."""
    ws = wb.create_sheet(name)
    ws.sheet_view.showGridLines = False
    COLS = ["Item ID", "Section", "Category", "Item", "Status", "Bug ID", "Jira Link", "Notes"]
    WIDTHS = [10, 22, 14, 44, 10, 12, 24, 20]
    ws.row_dimensions[1].height = 26
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(COLS))}1"
    for ci, (col, w) in enumerate(zip(COLS, WIDTHS), 1):
        ws.column_dimensions[get_column_letter(ci)].width = w
        cell = ws.cell(1, ci, col)
        cell.fill = _hex_fill(NAVY)
        cell.font = _cal(10, bold=True, color=WHITE)
        cell.alignment = _align("center")
        cell.border = _thin_border(NAVY)

    for ri, (item_id, section, category, text) in enumerate(rows, 2):
        is_even = ri % 2 == 0
        row_bg = WHITE if is_even else LIGHT_BG
        ws.row_dimensions[ri].height = max(24, 18 + (len(text) // 50) * 14)
        values = [item_id, section, category, text, "", "", "", ""]
        for ci, val in enumerate(values, 1):
            cell = ws.cell(ri, ci, val)
            cell.border = _thin_border()
            wrap = ci == 4
            cell.alignment = Alignment(horizontal=("left" if ci in (2, 4, 7, 8) else "center"),
                                        vertical="center", wrap_text=wrap)
            if ci == 1:
                cell.fill = _hex_fill(row_bg); cell.font = _cal(9, bold=True, color=NAVY)
            elif ci == 2:
                cell.fill = _hex_fill(row_bg); cell.font = _cal(9, color=DARK)
            elif ci == 3:
                cell.fill = _hex_fill(row_bg); cell.font = _cal(9, color=GRAY)
            elif ci == 4:
                cell.fill = _hex_fill(row_bg); cell.font = _cal(9.5, color=DARK)
            elif ci == 5:
                cell.fill = _hex_fill(row_bg); cell.font = _cal(9, bold=True, color=DARK)
            else:
                cell.fill = _hex_fill(row_bg); cell.font = _cal(9, color=DARK)

    if rows:
        _add_status_column(ws, "E", len(rows) + 1)
    return ws


def build_direct_checklist_excel(items: list, project_name: str = "") -> bytes:
    """items: list of (section, category, text) tuples from run_checklist_agent —
    generated directly from BRD + Mapping text, no FRS involved."""
    wb = Workbook()
    project_label = project_name.strip() if project_name and project_name.strip() else "Client Engagement"
    today_str = _date.today().strftime("%B %d, %Y")

    rows = [(f"CHK-{i + 1:03d}", section, category, text) for i, (section, category, text) in enumerate(items)]

    cover = wb.active
    cover.title = "Cover"
    cover.sheet_view.showGridLines = False
    for col, w in [("A", 2), ("B", 26), ("C", 20), ("D", 2)]:
        cover.column_dimensions[col].width = w

    cover.row_dimensions[2].height = 28
    cover.merge_cells("B2:C2")
    title = cover["B2"]
    title.value = "VERIFICATION CHECKLIST"
    title.font = _cal(20, bold=True, color=NAVY)
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
        ("Document Title", "Verification Checklist"),
        ("Project", project_label),
        ("Document Version", "1.0"),
        ("Status", "Draft"),
        ("Date", today_str),
        ("Classification", "Confidential — Internal & Client Use Only"),
        ("Total Checklist Items", str(len(rows))),
        ("Source", "Generated directly from BRD + Mapping (no FRS)"),
    ]
    r = 6
    for label, value in info_rows:
        cover.row_dimensions[r].height = 20
        lc = cover.cell(r, 2, label)
        lc.fill = _hex_fill(LIGHT_BG); lc.font = _cal(9, bold=True); lc.alignment = _align("left")
        lc.border = _thin_border()
        vc = cover.cell(r, 3, value)
        vc.font = _cal(9.5); vc.alignment = _align("left"); vc.border = _thin_border()
        r += 1

    r += 2
    note = cover.cell(r, 2, "Every item below is drawn directly from the BRD — business rules, "
                             "conditions, validations, and data fields — plus a fixed set of "
                             "standard print-production checks, for a fast, complete walkthrough "
                             "without generating a formal FRS.")
    note.font = _cal(9, italic=True, color=GRAY)
    cover.merge_cells(start_row=r, start_column=2, end_row=r, end_column=3)
    cover.row_dimensions[r].height = 44
    note.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)

    _add_direct_checklist_sheet(wb, "Checklist", rows)

    wb.active = cover
    out = BytesIO()
    wb.save(out)
    out.seek(0)
    return out.read()
