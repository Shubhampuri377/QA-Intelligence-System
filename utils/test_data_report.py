"""Test Data Map — the report that makes generated data auditable.

Every value the generator wrote is listed with the BRD requirement it came from,
what it proves, and exactly where it sits in the emitted file: a line number for
Ctrl+G in Notepad++, plus the path, which survives reformatting.

The report also lists what could NOT be generated. A data set that silently skips
requirements looks complete while covering less than it claims, so blocked cases
are a first-class section rather than an omission.

Presentation is deliberate — this workbook goes to a client alongside the data, so
it carries a title block, document control, a KPI strip, a legend and print setup
rather than reading as a raw export. All of that comes from utils.xlsx_style, so it
matches the PDF and HTML deliverables exactly instead of drifting into its own look.
"""

from datetime import date as _date
from io import BytesIO

from openpyxl import Workbook

from utils import xlsx_style as X
from utils.test_data_builder import display_path

_MAP_COLS = ["Record", "Line", "BRD Reference", "What This Value Tests",
             "Value Written", "Path In File"]
_MAP_W = [9, 8, 26, 54, 30, 56]


def build_test_data_report(rows: list, blocked: list, locations: dict, expected: list,
                           meta: dict) -> bytes:
    """rows/blocked come from build_records(); locations from the located writer."""
    wb = Workbook()
    project = (meta.get("project") or "Client Engagement").strip()
    fmt = str(meta.get("format", "JSON"))
    data_filename = meta.get("data_filename", f"{project}_TestData.{fmt.lower()}")
    covered = len({r.get("brd_ref") for r in rows if r.get("brd_ref")})

    _cover(wb, project, fmt, data_filename, rows, blocked, expected, meta, covered)
    _data_map(wb, rows, locations)
    _not_covered(wb, blocked)
    _expected(wb, expected)

    wb.active = 0
    out = BytesIO()
    wb.save(out)
    out.seek(0)
    return out.read()


# ── Cover ────────────────────────────────────────────────────────

def _cover(wb, project, fmt, data_filename, rows, blocked, expected, meta, covered):
    ws = wb.active
    ws.title = "Cover"
    X.sheet(ws, landscape=False)
    X.widths(ws, [2, 30, 20, 16, 18, 14, 14, 14])

    r = X.title_block(ws, "TEST DATA MAP", project, row=2, col=2, span=7)

    docs = sum(len(e.get("letters") or []) for e in expected)
    r = X.kpi_strip(ws, [
        ("Records generated", meta.get("record_count", len(expected)), None),
        ("Values mapped", len(rows), None),
        ("Requirements covered", covered, "PASS"),
        ("Not covered", len(blocked), "BLOCKED" if blocked else "PASS"),
        ("Documents expected", docs, None),
    ], row=r, col=2, box_w=1)

    r = X.section(ws, "Document Control", r, col=2)
    r = X.kv_rows(ws, [
        ("Document title", "Test Data Map"),
        ("Project", project),
        ("Generated", _date.today().strftime("%B %d, %Y")),
        ("Prepared by", "Data Generation"),
        ("Requirements source", meta.get("brd_files", "—")),
        ("Mapping document", meta.get("mapping_file", "—")),
        ("Schema sample", meta.get("sample_file", "—")),
        ("Generated data file", data_filename),
        ("Data format", fmt),
        ("Classification", "Confidential — Internal & Client Use Only"),
    ], r, col=2)

    r = X.section(ws, "How To Read This Workbook", r, col=2)
    r = X.kv_rows(ws, [
        ("Data Map", "Every value written into the generated file, the requirement it came "
                     "from, and where to find it."),
        ("Not Covered", "Requirements the generator could not exercise, and why. Read this "
                        "before treating the data set as complete."),
        ("Expected Outcomes", "What each record should produce, so the fixture states its own "
                              "acceptance criteria."),
    ], r, col=2)

    r = X.legend(ws, [
        ("PASS", "Covered — a value was written to exercise this requirement"),
        ("BLOCKED", "Not covered — the sample never showed the shape this case needs"),
    ], r, col=2)

    X.note(ws, "The Line column is a Ctrl+G target in the generated data file named above. "
               "Reformatting that file shifts its line numbers; the Path In File column stays "
               "valid either way, so trust the path when the two disagree.",
           r, col=2, span=7, height=32)


# ── Data Map ─────────────────────────────────────────────────────

def _data_map(wb, rows, locations):
    ws = wb.create_sheet("Data Map")
    X.sheet(ws)
    X.widths(ws, _MAP_W)
    r = X.header(ws, _MAP_COLS)
    if not rows:
        X.empty_note(ws, r, "No values were generated.", span=len(_MAP_COLS))
        return
    for row in rows:
        key = f"{row['record_index']}/{row['path']}"
        X.data_row(ws, r, [
            row["record_index"],
            locations.get(key, ""),          # blank rather than a guessed line
            row.get("brd_ref", ""),
            row.get("describes", ""),
            str(row.get("value", ""))[:200],
            display_path(row["path"], row["record_index"]),
        ], wrap=(4,), mono=(2, 6), center=(1, 2), text=(5,))
        r += 1


# ── Not Covered ──────────────────────────────────────────────────

def _not_covered(wb, blocked):
    ws = wb.create_sheet("Not Covered")
    # An amber tab when something was skipped. Colour here is a signal, not
    # decoration: a reader scanning the tab strip should see that this sheet has
    # content without opening it, because an unread gap sheet is how a data set
    # gets signed off as complete when it isn't.
    X.sheet(ws, tab_color=X.WARN_FG if blocked else X.NAVY)
    cols = ["Status", "BRD Reference", "What Could Not Be Tested", "Why"]
    X.widths(ws, [15, 26, 54, 54])
    r = X.header(ws, cols)
    if not blocked:
        X.empty_note(ws, r, "Every derived case was generated — nothing was skipped.",
                     span=len(cols))
        return
    for c in blocked:
        X.data_row(ws, r, ["BLOCKED", getattr(c, "brd_ref", ""),
                           getattr(c, "describes", ""), getattr(c, "blocked", "")],
                   wrap=(3, 4), status=(1,))
        r += 1


# ── Expected Outcomes ────────────────────────────────────────────

def _expected(wb, expected):
    ws = wb.create_sheet("Expected Outcomes")
    X.sheet(ws)
    cols = ["Record", "Documents Expected", "Expected Addressees", "Correctly Suppressed"]
    X.widths(ws, [9, 20, 50, 50])
    r = X.header(ws, cols)
    if not expected:
        X.empty_note(ws, r, "No expected outcomes were computed.", span=len(cols))
        return
    for e in expected:
        X.data_row(ws, r, [
            e["record_index"],
            len(e["letters"]),
            " · ".join(f"{l.get('label', '')}: {l.get('addressee_name', '')}"
                       for l in e["letters"]) or "—",
            " · ".join(f"{l.get('label', '')} ({l.get('skip_reason', '')})"
                       for l in e["suppressed"]) or "—",
        ], wrap=(3, 4), center=(1, 2))
        r += 1
