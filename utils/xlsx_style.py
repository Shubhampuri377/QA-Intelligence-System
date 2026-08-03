"""Shared styling for generated Excel deliverables.

A workbook that goes to a client is a document, not a data dump. What separates
one that reads as professional from one that reads as an export is unglamorous and
entirely mechanical: a single type family, gridlines off, a title block with real
hierarchy, one frozen header row with a filter, restrained zebra striping, colour
used only to carry meaning, column widths that do not clip, and print setup that
survives Ctrl+P.

All of it lives here so every sheet in every module looks like the same product,
and so the palette matches the PDF and HTML reports exactly — a deliverable set
whose colours disagree looks assembled rather than authored.
"""

from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.properties import WorksheetProperties, PageSetupProperties

# ── palette (identical to mapping_report.py / the PDF deliverables) ──
NAVY = "1F3A5F"
NAVY_DK = "162C48"
INK = "131720"
GRAY = "5B6370"
GRAY_LT = "8A93A3"
RULE = "CBD2DD"
BAND = "F7F8FA"
WHITE = "FFFFFF"

OK_FG, OK_BG = "15803D", "EAF7EE"
BAD_FG, BAD_BG = "B42318", "FBEAEA"
WARN_FG, WARN_BG = "B45309", "FEF6E7"
MUTE_FG, MUTE_BG = "5B6370", "F2F3F5"

FAMILY = "Calibri"

# ── type scale ──
F_TITLE = Font(name=FAMILY, size=20, bold=True, color=NAVY)
F_SUB = Font(name=FAMILY, size=11, color=GRAY)
F_H2 = Font(name=FAMILY, size=12, bold=True, color=NAVY)
F_LABEL = Font(name=FAMILY, size=9.5, bold=True, color=INK)
F_BODY = Font(name=FAMILY, size=9.5, color=INK)
F_BODY_B = Font(name=FAMILY, size=9.5, bold=True, color=INK)
F_MONO = Font(name="Consolas", size=9, color=NAVY)
F_NOTE = Font(name=FAMILY, size=9, italic=True, color=GRAY)
F_HDR = Font(name=FAMILY, size=9.5, bold=True, color=WHITE)
F_KPI = Font(name=FAMILY, size=18, bold=True, color=NAVY)
F_KPI_LBL = Font(name=FAMILY, size=8.5, bold=True, color=GRAY_LT)

# ── fills ──
FILL_NAVY = PatternFill("solid", fgColor=NAVY)
FILL_BAND = PatternFill("solid", fgColor=BAND)
FILL_WHITE = PatternFill("solid", fgColor=WHITE)
FILL_RULE = PatternFill("solid", fgColor=NAVY)

# ── borders: hairlines in a light grey, never black ──
_HAIR = Side(style="thin", color=RULE)
BORDER_CELL = Border(left=_HAIR, right=_HAIR, top=_HAIR, bottom=_HAIR)
BORDER_UNDER = Border(bottom=_HAIR)
BORDER_HDR = Border(left=Side(style="thin", color=NAVY), right=Side(style="thin", color=NAVY),
                    top=Side(style="thin", color=NAVY), bottom=Side(style="thin", color=NAVY))

AL_L = Alignment(horizontal="left", vertical="center")
AL_LT = Alignment(horizontal="left", vertical="top")
AL_WRAP = Alignment(horizontal="left", vertical="top", wrap_text=True)
AL_C = Alignment(horizontal="center", vertical="center")
AL_CT = Alignment(horizontal="center", vertical="top")
AL_R = Alignment(horizontal="right", vertical="center")

STATUS_COLOURS = {
    "PASS": (OK_FG, OK_BG), "MATCH": (OK_FG, OK_BG), "POSITIVE": (OK_FG, OK_BG),
    "FAIL": (BAD_FG, BAD_BG), "MISMATCH": (BAD_FG, BAD_BG), "NEGATIVE": (WARN_FG, WARN_BG),
    "BLOCKED": (WARN_FG, WARN_BG), "NOT COVERED": (WARN_FG, WARN_BG),
    "NOT VERIFIABLE": (MUTE_FG, MUTE_BG), "UNVERIFIED": (BAD_FG, BAD_BG),
}


def sheet(ws, tab_color=NAVY, landscape=True):
    """Baseline setup every sheet gets: no gridlines, a tab colour, print-ready."""
    ws.sheet_view.showGridLines = False
    ws.sheet_properties.tabColor = tab_color
    ws.page_setup.orientation = "landscape" if landscape else "portrait"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    ws.print_options.horizontalCentered = True
    ws.oddFooter.center.text = "Confidential — For Internal && Client Use Only    |    Page &P of &N"
    ws.oddFooter.center.size = 8
    ws.oddFooter.center.color = GRAY
    return ws


def widths(ws, spec, first_col=1):
    for i, w in enumerate(spec, first_col):
        ws.column_dimensions[get_column_letter(i)].width = w


def title_block(ws, title, subtitle="", classification="Confidential — Internal & Client Use Only",
                row=2, col=2, span=6):
    """Title, subtitle, a navy rule under them. The rule is what makes it read as
    letterhead rather than as row 1 of a spreadsheet."""
    ws.row_dimensions[row].height = 30
    c = ws.cell(row, col, title)
    c.font = F_TITLE
    c.alignment = AL_L
    if subtitle:
        ws.row_dimensions[row + 1].height = 17
        s = ws.cell(row + 1, col, subtitle)
        s.font = F_SUB
        s.alignment = AL_L
    rule_row = row + 2
    ws.row_dimensions[rule_row].height = 4
    for cc in range(col, col + span):
        ws.cell(rule_row, cc).fill = FILL_RULE
    if classification:
        k = ws.cell(rule_row + 1, col, classification)
        k.font = F_KPI_LBL
        ws.row_dimensions[rule_row + 1].height = 15
    return rule_row + 3


def kpi_strip(ws, items, row, col=2, box_w=2):
    """Big-number tiles: value above a small caps label. Cheap, and it gives a
    reader the shape of the run before they scroll into 11,000 rows."""
    ws.row_dimensions[row].height = 26
    ws.row_dimensions[row + 1].height = 14
    c = col
    for label, value, tone in items:
        v = ws.cell(row, c, value)
        v.font = F_KPI if tone is None else Font(name=FAMILY, size=18, bold=True,
                                                 color=STATUS_COLOURS.get(tone, (NAVY,))[0])
        v.alignment = AL_L
        l = ws.cell(row + 1, c, label.upper())
        l.font = F_KPI_LBL
        l.alignment = AL_L
        c += box_w
    return row + 3


def section(ws, text, row, col=2):
    ws.row_dimensions[row].height = 20
    c = ws.cell(row, col, text)
    c.font = F_H2
    c.border = BORDER_UNDER
    return row + 1


def kv_rows(ws, pairs, row, col=2):
    """Document-control block: bold label, plain value, hairline separators."""
    for k, v in pairs:
        ws.row_dimensions[row].height = 17
        a = ws.cell(row, col, k)
        a.font = F_LABEL
        a.fill = FILL_BAND
        a.border = BORDER_CELL
        a.alignment = AL_L
        b = ws.cell(row, col + 1, v)
        b.font = F_BODY
        b.border = BORDER_CELL
        b.alignment = AL_WRAP
        row += 1
    return row + 1


def note(ws, text, row, col=2, span=6, height=30):
    ws.merge_cells(start_row=row, start_column=col, end_row=row, end_column=col + span - 1)
    c = ws.cell(row, col, text)
    c.font = F_NOTE
    c.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
    ws.row_dimensions[row].height = height
    return row + 2


def legend(ws, entries, row, col=2):
    """A chip and its meaning. Colour that is not explained is decoration."""
    for tone, meaning in entries:
        fg, bg = STATUS_COLOURS.get(tone, (MUTE_FG, MUTE_BG))
        c = ws.cell(row, col, tone)
        c.font = Font(name=FAMILY, size=9, bold=True, color=fg)
        c.fill = PatternFill("solid", fgColor=bg)
        c.alignment = AL_C
        c.border = BORDER_CELL
        m = ws.cell(row, col + 1, meaning)
        m.font = F_BODY
        m.alignment = AL_WRAP
        ws.row_dimensions[row].height = 16
        row += 1
    return row + 1


def header(ws, cols, row=1, col=1, freeze=True, autofilter=True):
    """One frozen, filtered header row. Taller than the data rows so the grid has
    a clear top edge without needing gridlines."""
    ws.row_dimensions[row].height = 26
    for i, text in enumerate(cols, col):
        c = ws.cell(row, i, text)
        c.font = F_HDR
        c.fill = FILL_NAVY
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = BORDER_HDR
    last = get_column_letter(col + len(cols) - 1)
    if autofilter:
        ws.auto_filter.ref = f"{get_column_letter(col)}{row}:{last}{row}"
    if freeze:
        ws.freeze_panes = ws.cell(row + 1, col)
    ws.print_title_rows = f"{row}:{row}"
    return row + 1


def data_row(ws, row, values, col=1, wrap=(), mono=(), center=(), status=(), text=()):
    """One body row. Column indexes in the tuples are 1-based within `values`."""
    band = FILL_BAND if row % 2 == 0 else FILL_WHITE
    for i, v in enumerate(values, 1):
        c = ws.cell(row, col + i - 1, v)
        c.font = F_BODY
        c.fill = band
        c.border = BORDER_CELL
        c.alignment = AL_WRAP if i in wrap else (AL_CT if i in center else AL_LT)
        if i in mono:
            c.font = F_MONO
        if i in text:
            # Identifiers must stay text: Excel will happily turn 0004073361 into
            # 4073361 and a scan line into scientific notation.
            c.number_format = "@"
        if i in status:
            key = str(v or "").strip().upper()
            if key in STATUS_COLOURS:
                fg, bg = STATUS_COLOURS[key]
                c.font = Font(name=FAMILY, size=9, bold=True, color=fg)
                c.fill = PatternFill("solid", fgColor=bg)
                c.alignment = AL_C
    return row + 1


def empty_note(ws, row, text, span=3, col=1):
    ws.merge_cells(start_row=row, start_column=col, end_row=row, end_column=col + span - 1)
    c = ws.cell(row, col, text)
    c.font = F_NOTE
    c.alignment = AL_L
    c.fill = FILL_WHITE
    c.border = BORDER_CELL
    ws.row_dimensions[row].height = 20
    return row + 1
