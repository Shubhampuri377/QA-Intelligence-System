"""Full field-by-field detail as Excel, written in streaming mode.

The PDF and HTML reports carry the failures — the part a human reads and a client
signs. This carries EVERYTHING, for the runs where "everything" is 46,000 rows and
neither of those formats is a sensible container: at 2,000 records the full PDF is
roughly 4,400 pages.

openpyxl's write_only mode keeps one row in memory at a time instead of building a
cell object for every value, so the file grows with the run while memory does not.
That is what makes a large validation exportable at all, rather than a report the
server runs out of room to build.
"""

from io import BytesIO

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from utils.mapping_report import _norm_status, _rollup, _rate_text

NAVY = "1F3A5F"
WHITE = "FFFFFF"
PASS_BG = "EAF7EE"
FAIL_BG = "FBEAEA"
NV_BG = "F2F3F5"

_COLS = [("Document", 34), ("Status", 15), ("Mapped Field", 30), ("BRD Reference", 22),
         ("Expected Value", 40), ("Output Value", 40), ("Checked By", 13), ("Notes", 70)]


def _txt(v) -> str:
    """Excel rejects control characters, and a single cell caps at 32,767 chars."""
    s = "" if v is None else str(v)
    s = "".join(ch for ch in s if ch >= " " or ch in "\n\t")
    return s[:32000]


# Style objects are built ONCE and shared. Constructing a Font, PatternFill and
# Alignment per cell cost 150 seconds on a 46,000-row export — 368,000 throwaway
# style objects — which defeated the point of a streaming writer. Reusing them
# takes the same export to a few seconds.
_FONT = Font(name="Calibri", size=10, color="131720")
_FONT_B = Font(name="Calibri", size=10, bold=True, color="131720")
_FONT_HDR = Font(name="Calibri", size=10, bold=True, color=WHITE)
_FONT_TITLE = Font(name="Calibri", size=14, bold=True, color=NAVY)
_FONT_NOTE = Font(name="Calibri", size=9, color="5B6370")
_AL = Alignment(horizontal="left", vertical="top")
_AL_WRAP = Alignment(horizontal="left", vertical="top", wrap_text=True)
_AL_CTR = Alignment(horizontal="center", vertical="top")
_FILLS = {k: PatternFill("solid", fgColor=k) for k in (NAVY, PASS_BG, FAIL_BG, NV_BG)}


def _c(ws, value, font=None, fill=None, align=None):
    """A styled cell bound to THIS worksheet.

    WriteOnlyCell carries a style id resolved against its own workbook, so a cell
    built against some other sheet produces a file Excel and openpyxl both refuse
    to open. The worksheet has to be passed in.
    """
    c = WriteOnlyCell(ws, value=value)
    c.font = font or _FONT
    if fill:
        c.fill = _FILLS[fill]
    c.alignment = align or _AL
    return c


def _widths(ws, widths):
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w


def mapping_detail_to_excel(payload: dict) -> bytes:
    """Every row of every instance, one sheet, streamed."""
    wb = Workbook(write_only=True)
    roll = _rollup(payload)
    stats = payload.get("stats") or {}
    meta = payload.get("meta") or {}

    # ── Summary ──
    ws = wb.create_sheet("Summary")
    _widths(ws, [40, 66])
    ws.append([_c(ws, "FIELD MAPPING VALIDATION — FULL DETAIL", font=_FONT_TITLE)])
    ws.append([])
    for k, v in [
        ("Project", meta.get("project", "—")),
        ("Source data", meta.get("source_file", "—")),
        ("Generated output", meta.get("output_file", "—")),
        ("Mapping reference", meta.get("mapping_file", "—")),
        ("Documents expected from the feed", stats.get("letters_expected", "—")),
        ("Documents paired to an output page", stats.get("instances_located", "—")),
        ("Fields checked", roll["checked"]),
        ("Passed — source value rendered in full", roll["PASS"]),
        ("FAILED — missing, incomplete or wrong", roll["FAIL"]),
        ("Pass rate", _rate_text(roll, stats)),
        ("Not verifiable from these inputs (excluded)", roll["NOT VERIFIABLE"]),
        ("Overall assessment", payload.get("assessment", "—")),
    ]:
        ws.append([_c(ws, k, font=_FONT_B), _c(ws, _txt(v), align=_AL_WRAP)])
    ws.append([])
    ws.append([_c(ws, "This workbook lists every checked field. The PDF and HTML reports list "
                      "the failures only, so they stay readable at any volume.",
                  font=_FONT_NOTE, align=_AL_WRAP)])

    # ── Detail ──
    ws = wb.create_sheet("Field Detail")
    _widths(ws, [w for _, w in _COLS])
    ws.freeze_panes = "A2"
    ws.append([_c(ws, h, font=_FONT_HDR, fill=NAVY, align=_AL_CTR) for h, _ in _COLS])

    for inst in payload.get("instances", []) or []:
        doc = inst.get("title") or "Document"
        for r in inst.get("rows", []) or []:
            st = "UNVERIFIED" if r.get("unverified") else _norm_status(r.get("status"))
            bg = {"PASS": PASS_BG, "FAIL": FAIL_BG}.get(st, NV_BG)
            ws.append([
                _c(ws, _txt(doc), fill=bg),
                _c(ws, st, font=_FONT_B, fill=bg, align=_AL_CTR),
                _c(ws, _txt(r.get("field")), fill=bg),
                _c(ws, _txt(r.get("field_path")), fill=bg),
                _c(ws, _txt(r.get("expected") or r.get("source")), fill=bg, align=_AL_WRAP),
                _c(ws, _txt(r.get("output")), fill=bg, align=_AL_WRAP),
                _c(ws, _txt(r.get("by")), fill=bg),
                _c(ws, _txt(r.get("notes")), fill=bg, align=_AL_WRAP),
            ])

    out = BytesIO()
    wb.save(out)
    out.seek(0)
    return out.read()
