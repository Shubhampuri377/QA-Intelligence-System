"""Builds a formal, enterprise-consulting-style Word (.docx) FRS deliverable
from a list of functional requirements — cover page, document control &
approval sign-off, table of contents, and each requirement as a structured
table, in a conservative navy/gray corporate layout."""

from datetime import date as dt_date
from io import BytesIO

from docx import Document as DocxDoc
from docx.shared import Pt, RGBColor, Inches, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT, WD_TAB_LEADER
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

NAVY = RGBColor(0x1F, 0x3A, 0x5F)
DARK = RGBColor(0x1F, 0x29, 0x37)
GRAY = RGBColor(0x5B, 0x63, 0x70)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
HEADER_BG = "1F3A5F"
LIGHT_BG = "F2F3F5"
BORDER = "B9C0CB"
FONT = "Calibri"


def _set_cell_bg(cell, hex_color):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color)
    tcPr.append(shd)


def _set_cell_borders(cell, color=BORDER):
    tcPr = cell._tc.get_or_add_tcPr()
    tcBorders = OxmlElement("w:tcBorders")
    for side in ["top", "left", "bottom", "right"]:
        border = OxmlElement(f"w:{side}")
        border.set(qn("w:val"), "single")
        border.set(qn("w:sz"), "4")
        border.set(qn("w:color"), color)
        tcBorders.append(border)
    tcPr.append(tcBorders)


def _add_field(paragraph, field_code):
    run = paragraph.add_run()
    fld1 = OxmlElement("w:fldChar"); fld1.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText"); instr.set(qn("xml:space"), "preserve"); instr.text = field_code
    fld2 = OxmlElement("w:fldChar"); fld2.set(qn("w:fldCharType"), "end")
    run._r.append(fld1); run._r.append(instr); run._r.append(fld2)


def _run(paragraph, text, size=10, bold=False, italic=False, color=DARK):
    r = paragraph.add_run(text)
    r.font.size = Pt(size); r.bold = bold; r.italic = italic
    r.font.color.rgb = color; r.font.name = FONT
    return r


def _para(doc, text="", size=10, bold=False, color=DARK, align=None, space_before=0, space_after=6):
    p = doc.add_paragraph()
    if align is not None:
        p.alignment = align
    p.paragraph_format.space_before = Pt(space_before)
    p.paragraph_format.space_after = Pt(space_after)
    if text:
        _run(p, text, size=size, bold=bold, color=color)
    return p


def _heading(doc, text, level=1):
    """Uses real Word Heading styles so the Navigation Pane / TOC field works."""
    h = doc.add_heading(level=level)
    h.paragraph_format.space_before = Pt(16 if level == 1 else 10)
    h.paragraph_format.space_after = Pt(8)
    size = 16 if level == 1 else (12.5 if level == 2 else 11)
    _run(h, text, size=size, bold=True, color=NAVY)
    return h


def _header_cell(cell, text, width):
    cell.width = Inches(width)
    _set_cell_bg(cell, HEADER_BG)
    _set_cell_borders(cell)
    p = cell.paragraphs[0]
    p.paragraph_format.space_before = Pt(4); p.paragraph_format.space_after = Pt(4)
    _run(p, text, size=9.5, bold=True, color=WHITE)


def _kv_table(doc, rows, col_widths=(2.3, 4.8)):
    tbl = doc.add_table(rows=0, cols=2)
    tbl.style = "Table Grid"
    for label, value in rows:
        row = tbl.add_row().cells
        row[0].width = Inches(col_widths[0]); row[1].width = Inches(col_widths[1])
        _set_cell_bg(row[0], LIGHT_BG); _set_cell_borders(row[0])
        _set_cell_borders(row[1])
        p0 = row[0].paragraphs[0]
        p0.paragraph_format.space_before = Pt(3); p0.paragraph_format.space_after = Pt(3)
        _run(p0, label, size=9, bold=True)
        p1 = row[1].paragraphs[0]
        p1.paragraph_format.space_before = Pt(3); p1.paragraph_format.space_after = Pt(3)
        _run(p1, str(value) if value else "—", size=9.5)
    return tbl


def _label_row(tbl, label, items):
    row = tbl.add_row().cells
    _set_cell_bg(row[0], LIGHT_BG); _set_cell_borders(row[0])
    lp = row[0].paragraphs[0]
    lp.paragraph_format.space_before = Pt(4); lp.paragraph_format.space_after = Pt(4)
    _run(lp, label, size=9, bold=True)
    _set_cell_borders(row[1])
    first = row[1].paragraphs[0]
    first.paragraph_format.space_before = Pt(4); first.paragraph_format.space_after = Pt(2)
    if items:
        for i, item in enumerate(items):
            target = first if i == 0 else row[1].add_paragraph()
            target.paragraph_format.space_before = Pt(0); target.paragraph_format.space_after = Pt(2)
            _run(target, f"•  {item}", size=9.5)
    else:
        _run(first, "—", size=9.5, color=GRAY)
    return row


def frs_to_word(frs: list, project_name: str = "") -> bytes:
    doc = DocxDoc()

    normal = doc.styles["Normal"]
    normal.font.name = FONT
    normal.font.size = Pt(10)
    normal.font.color.rgb = DARK

    for section in doc.sections:
        section.top_margin = Cm(2.0)
        section.bottom_margin = Cm(2.0)
        section.left_margin = Cm(2.2)
        section.right_margin = Cm(2.2)

    project_label = project_name.strip() if project_name and project_name.strip() else "Client Engagement"
    today_str = dt_date.today().strftime("%B %d, %Y")

    # ── Footer ──
    section = doc.sections[0]
    fp = section.footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _run(fp, "Confidential — For Internal & Client Use Only     |     Page ", size=8, color=GRAY)
    _add_field(fp, "PAGE")
    _run(fp, " of ", size=8, color=GRAY)
    _add_field(fp, "NUMPAGES")

    # ── Cover page ──
    for _ in range(5):
        doc.add_paragraph()
    _para(doc, "FUNCTIONAL REQUIREMENT SPECIFICATION", size=24, bold=True, color=NAVY,
          align=WD_ALIGN_PARAGRAPH.CENTER, space_after=6)
    _para(doc, project_label, size=15, bold=True, color=GRAY,
          align=WD_ALIGN_PARAGRAPH.CENTER, space_after=30)

    rule = doc.add_paragraph()
    rule.alignment = WD_ALIGN_PARAGRAPH.CENTER
    pPr = rule._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    bot = OxmlElement("w:bottom")
    bot.set(qn("w:val"), "single"); bot.set(qn("w:sz"), "12")
    bot.set(qn("w:color"), HEADER_BG); bot.set(qn("w:space"), "1")
    pBdr.append(bot); pPr.append(pBdr)

    for _ in range(3):
        doc.add_paragraph()

    _kv_table(doc, [
        ("Document Title", "Functional Requirement Specification"),
        ("Project", project_label),
        ("Document Version", "1.0"),
        ("Status", "Draft"),
        ("Date", today_str),
        ("Classification", "Confidential — Internal & Client Use Only"),
        ("Total Requirements", str(len(frs))),
    ])
    doc.add_page_break()

    # ── Document Control ──
    _heading(doc, "Document Control", level=1)
    _para(doc, "Revision History", size=10, bold=True, color=NAVY, space_before=4, space_after=4)
    rh = doc.add_table(rows=1, cols=4)
    rh.style = "Table Grid"
    for cell, txt, w in zip(rh.rows[0].cells, ["Version", "Date", "Prepared By", "Description"],
                             [1.0, 1.6, 1.8, 4.4]):
        _header_cell(cell, txt, w)
    row = rh.add_row().cells
    for cell, txt in zip(row, ["1.0", today_str, "Document Generation", "Initial baseline version generated from source BRD"]):
        _set_cell_borders(cell)
        p = cell.paragraphs[0]
        p.paragraph_format.space_before = Pt(3); p.paragraph_format.space_after = Pt(3)
        _run(p, txt, size=9)

    _para(doc, "Approval", size=10, bold=True, color=NAVY, space_before=18, space_after=4)
    ap = doc.add_table(rows=1, cols=4)
    ap.style = "Table Grid"
    for cell, txt, w in zip(ap.rows[0].cells, ["Role", "Name", "Signature", "Date"], [2.8, 2.0, 2.0, 2.0]):
        _header_cell(cell, txt, w)
    for role in ["Prepared By (Business Analyst)", "Reviewed By (QA Lead)", "Approved By (Project Manager)"]:
        row = ap.add_row().cells
        _set_cell_borders(row[0])
        p = row[0].paragraphs[0]
        p.paragraph_format.space_before = Pt(3); p.paragraph_format.space_after = Pt(16)
        _run(p, role, size=9)
        for cell in row[1:]:
            _set_cell_borders(cell)
            cp = cell.paragraphs[0]
            cp.paragraph_format.space_before = Pt(3); cp.paragraph_format.space_after = Pt(16)
    doc.add_page_break()

    # ── Table of Contents ──
    _heading(doc, "Table of Contents", level=1)
    for num, title in [("1.", "Introduction"), ("2.", "Requirements Overview"), ("3.", "Functional Requirements")]:
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(4)
        _run(p, f"{num}  {title}", size=10.5)

    if frs:
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(10)
        _run(p, "3.x  Functional Requirement Index", size=10.5, bold=True)

        for fr in frs:
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(2); p.paragraph_format.space_after = Pt(2)
            p.paragraph_format.tab_stops.add_tab_stop(Inches(6.3), WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS)
            _run(p, f"{fr.get('FR_ID', '')}\t{fr.get('Feature', '')}", size=9.5)
    doc.add_page_break()

    # ── 1. Introduction ──
    _heading(doc, "1. Introduction", level=1)
    _para(doc, "1.1 Purpose", size=11, bold=True, color=NAVY, space_before=8, space_after=4)
    _para(doc, "This document defines the functional requirements for the system described in "
               "the accompanying Business Requirement Document (BRD). It is intended to guide "
               "development and quality assurance activities and serves as the basis for test "
               "case design and validation.", size=10)
    _para(doc, "1.2 Scope", size=11, bold=True, color=NAVY, space_before=8, space_after=4)
    _para(doc, f"This specification covers {len(frs)} functional requirement(s) derived from the "
               "source BRD, presented in the same sequence as the source document to preserve "
               "traceability.", size=10)
    doc.add_page_break()

    # ── 2. Requirements Overview ──
    _heading(doc, "2. Requirements Overview", level=1)
    tbl = doc.add_table(rows=1, cols=3)
    tbl.style = "Table Grid"
    for cell, txt, w in zip(tbl.rows[0].cells, ["FR ID", "Feature", "Description"], [1.1, 2.2, 6.4]):
        _header_cell(cell, txt, w)
    for idx, fr in enumerate(frs):
        row = tbl.add_row().cells
        bg = "FFFFFF" if idx % 2 == 0 else LIGHT_BG
        for cell in row:
            _set_cell_bg(cell, bg); _set_cell_borders(cell)
            cell.paragraphs[0].paragraph_format.space_before = Pt(3)
            cell.paragraphs[0].paragraph_format.space_after = Pt(3)
        _run(row[0].paragraphs[0], fr.get("FR_ID", ""), size=9, bold=True, color=NAVY)
        _run(row[1].paragraphs[0], fr.get("Feature", ""), size=9, bold=True)
        desc = (fr.get("Description", "") or "")
        desc = desc[:120] + "…" if len(desc) > 120 else desc
        _run(row[2].paragraphs[0], desc, size=9, color=GRAY)
    doc.add_page_break()

    # ── 3. Functional Requirements (detail) ──
    _heading(doc, "3. Functional Requirements", level=1)
    for idx, fr in enumerate(frs):
        _heading(doc, f"3.{idx + 1}  {fr.get('FR_ID', '')} — {fr.get('Feature', '')}", level=2)

        tbl = doc.add_table(rows=0, cols=2)
        tbl.style = "Table Grid"
        _label_row(tbl, "Description", [fr.get("Description", "")] if fr.get("Description") else [])
        _label_row(tbl, "Actors", fr.get("Actors", []))
        _label_row(tbl, "Inputs", fr.get("Inputs", []))
        _label_row(tbl, "Outputs", fr.get("Outputs", []))
        _label_row(tbl, "Business Rules", fr.get("Business Rules", []))
        _label_row(tbl, "Conditions", fr.get("Conditions", []))
        _label_row(tbl, "Validations", fr.get("Validations", []))
        _label_row(tbl, "Preconditions", fr.get("Preconditions", []))
        _label_row(tbl, "Postconditions", fr.get("Postconditions", []))
        mapped = fr.get("Mapped Fields", {})
        if mapped and isinstance(mapped, dict) and any(v for v in mapped.values()):
            _label_row(tbl, "Mapped Fields", [f"{k} → {v}" for k, v in mapped.items() if k and v])

        for row in tbl.rows:
            row.cells[0].width = Inches(2.0)
            row.cells[1].width = Inches(6.7)

        doc.add_paragraph().paragraph_format.space_after = Pt(6)
        if idx < len(frs) - 1:
            doc.add_page_break()

    buf = BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.read()
