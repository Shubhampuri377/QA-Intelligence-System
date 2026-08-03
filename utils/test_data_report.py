"""
Test Data Map — the report that makes generated data auditable.

Every value the generator wrote is listed with the BRD requirement it came from,
what it proves, and exactly where it sits in the emitted file (line number for
Ctrl+G in Notepad++, plus the path, which survives reformatting).

The report also lists what could NOT be generated. A data set that silently skips
requirements looks complete while covering less than it claims, so blocked cases
are a first-class section rather than an omission.
"""

from datetime import date as _date
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment
from openpyxl.utils import get_column_letter

from utils.excel_export import (NAVY, DARK, GRAY, LIGHT_BG, WHITE,
                                _hex_fill, _thin_border, _cal, _align)
from utils.test_data_builder import display_path


def _header(ws, cols, widths, row=1):
    ws.row_dimensions[row].height = 24
    for ci, (c, w) in enumerate(zip(cols, widths), 1):
        ws.column_dimensions[get_column_letter(ci)].width = w
        cell = ws.cell(row, ci, c)
        cell.fill = _hex_fill(NAVY)
        cell.font = _cal(9.5, bold=True, color=WHITE)
        cell.alignment = _align("center")
        cell.border = _thin_border(NAVY)


def _row(ws, r, values, wrap_cols=(), mono_cols=()):
    bg = WHITE if r % 2 == 0 else LIGHT_BG
    for ci, v in enumerate(values, 1):
        cell = ws.cell(r, ci, v)
        cell.fill = _hex_fill(bg)
        cell.border = _thin_border()
        cell.font = _cal(9, color=DARK)
        cell.alignment = Alignment(horizontal="left", vertical="top",
                                    wrap_text=(ci in wrap_cols))
        if ci in mono_cols:
            cell.font = _cal(9, color=NAVY, bold=True)


def build_test_data_report(rows: list, blocked: list, locations: dict, expected: list,
                           meta: dict) -> bytes:
    """rows/blocked come from build_records(); locations from the located writer."""
    wb = Workbook()
    project = (meta.get("project") or "Client Engagement").strip()
    fmt = meta.get("format", "JSON")
    data_filename = meta.get("data_filename", f"{project}_TestData.{fmt.lower()}")

    # ── Cover ──
    cov = wb.active
    cov.title = "Cover"
    cov.sheet_view.showGridLines = False
    for col, w in [("A", 2), ("B", 30), ("C", 62)]:
        cov.column_dimensions[col].width = w
    cov.row_dimensions[2].height = 28
    t = cov.cell(2, 2, "TEST DATA MAP")
    t.font = _cal(20, bold=True, color=NAVY)
    s = cov.cell(3, 2, project)
    s.font = _cal(13, bold=True, color=GRAY)
    for c in range(2, 4):
        cov.cell(4, c).fill = _hex_fill(NAVY)
    cov.row_dimensions[4].height = 5

    info = [
        ("Document Title", "Test Data Map"),
        ("Project", project),
        ("Generated", _date.today().strftime("%B %d, %Y")),
        ("Requirements source", meta.get("brd_files", "—")),
        ("Mapping document", meta.get("mapping_file", "—")),
        ("Schema sample", meta.get("sample_file", "—")),
        ("Generated data file", data_filename),
        ("Data format", fmt),
        ("Records generated", str(meta.get("record_count", "—"))),
        ("Values mapped to a requirement", str(len(rows))),
        ("Requirements NOT covered", str(len(blocked))),
        ("Classification", "Confidential — Internal & Client Use Only"),
    ]
    r = 6
    for k, v in info:
        cov.row_dimensions[r].height = 19
        a = cov.cell(r, 2, k)
        a.fill = _hex_fill(LIGHT_BG); a.font = _cal(9, bold=True); a.border = _thin_border()
        b = cov.cell(r, 3, v)
        b.font = _cal(9.5); b.border = _thin_border(); b.alignment = _align("left")
        r += 1
    r += 1
    note = cov.cell(r, 2, "The Line column is a Ctrl+G target in Notepad++ for the generated data "
                         "file. If you reformat that file the line numbers shift — use the Path "
                         "column, which stays valid.")
    note.font = _cal(9, italic=True, color=GRAY)
    cov.merge_cells(start_row=r, start_column=2, end_row=r, end_column=3)
    cov.row_dimensions[r].height = 42
    note.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)

    # ── Data Map ──
    ws = wb.create_sheet("Data Map")
    ws.sheet_view.showGridLines = False
    cols = ["Record", "Line", "BRD Reference", "What This Value Tests", "Value Written", "Path"]
    _header(ws, cols, [9, 8, 24, 52, 26, 54])
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(cols))}1"
    for i, row in enumerate(rows, start=2):
        key = f"{row['record_index']}/{row['path']}"
        _row(ws, i, [
            row["record_index"],
            locations.get(key, ""),                       # blank rather than a guessed line
            row.get("brd_ref", ""),
            row.get("describes", ""),
            str(row.get("value", ""))[:120],
            display_path(row["path"], row["record_index"]),
        ], wrap_cols=(4, 6), mono_cols=(2,))

    # ── Not Covered ──
    nc = wb.create_sheet("Not Covered")
    nc.sheet_view.showGridLines = False
    _header(nc, ["BRD Reference", "What Could Not Be Tested", "Why"], [24, 54, 54])
    nc.freeze_panes = "A2"
    for i, c in enumerate(blocked, start=2):
        _row(nc, i, [getattr(c, "brd_ref", ""), getattr(c, "describes", ""),
                     getattr(c, "blocked", "")], wrap_cols=(2, 3))
    if not blocked:
        _row(nc, 2, ["—", "Every derived case was generated.", ""], wrap_cols=(2, 3))

    # ── Expected Outcomes ──
    eo = wb.create_sheet("Expected Outcomes")
    eo.sheet_view.showGridLines = False
    _header(eo, ["Record", "Documents Expected", "Expected Addressees",
                 "Correctly Suppressed"], [9, 20, 46, 46])
    eo.freeze_panes = "A2"
    for i, e in enumerate(expected, start=2):
        _row(eo, i, [
            e["record_index"], len(e["letters"]),
            " · ".join(f"{l.get('label','')}: {l.get('addressee_name','')}" for l in e["letters"]),
            " · ".join(f"{l.get('label','')} ({l.get('skip_reason','')})" for l in e["suppressed"]),
        ], wrap_cols=(3, 4))

    wb.active = cov
    out = BytesIO()
    wb.save(out)
    out.seek(0)
    return out.read()
