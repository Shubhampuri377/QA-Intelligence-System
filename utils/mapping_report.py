"""PDF and HTML builders for the Field Mapping Validation report.

This is a different shape from the requirement-oriented validation report in
`report_export.py`. Instead of one row per requirement ("field X must be
present") with a Pass/Fail + confidence, this reports one row per MAPPED
FIELD per DOCUMENT INSTANCE, with the source value and the rendered output
value side by side and a MATCH / MISMATCH / GAP / REVIEW verdict.

That grouping matters: when a data feed holds several records that each
produce their own document (2 invoices in one XML), the same field legitimately
appears once per instance. A flat requirement list reads those as duplicates;
a field x instance grid reads them correctly.
"""

import html
from datetime import date
from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
                                HRFlowable)
from reportlab.lib.enums import TA_CENTER

NAVY = "#1F3A5F"
DARK = "#1F2937"
GRAY = "#5B6370"
LIGHT_BG = "#F2F3F5"
BORDER = "#B9C0CB"

STATUS_FG = {"MATCH": "#15803D", "MISMATCH": "#B42318", "GAP": "#B54708", "REVIEW": "#3748A6"}
STATUS_BG = {"MATCH": "#EAF7EE", "MISMATCH": "#FBEAEA", "GAP": "#FEF6E7", "REVIEW": "#EEF1F6"}

FINDING_FG = {"Mismatch": "#B42318", "Gap": "#B54708", "Observation": "#3748A6"}


def _norm_status(s: str) -> str:
    s = (s or "").strip().upper()
    if s.startswith("MATCH"):
        return "MATCH"
    if s.startswith("MISMATCH"):
        return "MISMATCH"
    if s.startswith("GAP"):
        return "GAP"
    if s.startswith("REVIEW"):
        return "REVIEW"
    return "REVIEW"


def _clip(v, n=300) -> str:
    s = "—" if v in (None, "") else str(v)
    return s if len(s) <= n else s[: n - 1] + "…"


def _esc_pdf(v, n=300) -> str:
    """Escape for reportlab's mini-HTML Paragraph markup."""
    return (_clip(v, n).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _instance_counts(inst: dict) -> dict:
    c = {"MATCH": 0, "MISMATCH": 0, "GAP": 0, "REVIEW": 0}
    for r in inst.get("rows", []) or []:
        c[_norm_status(r.get("status"))] += 1
    return c


def _rollup(payload: dict) -> dict:
    total = {"MATCH": 0, "MISMATCH": 0, "GAP": 0, "REVIEW": 0}
    fields = 0
    for inst in payload.get("instances", []) or []:
        c = _instance_counts(inst)
        for k in total:
            total[k] += c[k]
        fields += len(inst.get("rows", []) or [])
    total["fields"] = fields
    return total


# ═══════════════════════════════════════════════════════════════
# PDF
# ═══════════════════════════════════════════════════════════════

def mapping_report_to_pdf(payload: dict) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=1.7 * cm, bottomMargin=1.7 * cm,
                             leftMargin=1.6 * cm, rightMargin=1.6 * cm,
                             title="Field Mapping Validation Report")
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("T", parent=styles["Title"], fontSize=21, leading=25,
                                  textColor=colors.HexColor(NAVY), alignment=TA_CENTER, spaceAfter=4)
    sub_style = ParagraphStyle("S", parent=styles["Normal"], fontSize=9.5, leading=13,
                                textColor=colors.HexColor(GRAY), alignment=TA_CENTER)
    h2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=13.5,
                         textColor=colors.HexColor(NAVY), spaceBefore=15, spaceAfter=7)
    h3 = ParagraphStyle("H3", parent=styles["Heading3"], fontSize=10.5, leading=14,
                         textColor=colors.HexColor(NAVY), spaceBefore=13, spaceAfter=5)
    body = ParagraphStyle("B", parent=styles["Normal"], fontSize=9, leading=12.5,
                           textColor=colors.HexColor(DARK))
    small = ParagraphStyle("Sm", parent=styles["Normal"], fontSize=7.8, leading=10.5,
                            textColor=colors.HexColor(DARK))
    small_gray = ParagraphStyle("SmG", parent=styles["Normal"], fontSize=7.5, leading=10,
                                 textColor=colors.HexColor(GRAY))
    th = ParagraphStyle("Th", parent=styles["Normal"], fontSize=8, leading=10.5,
                         textColor=colors.white, fontName="Helvetica-Bold")
    bullet = ParagraphStyle("Bu", parent=styles["Normal"], fontSize=8.6, leading=12,
                             textColor=colors.HexColor(DARK), leftIndent=10, spaceAfter=4)

    roll = _rollup(payload)
    totals = payload.get("totals") or {}
    story = []

    # ── Title block ──
    story += [
        Paragraph("FIELD MAPPING VALIDATION REPORT", title_style),
        Paragraph("Source data &rarr; generated output, reconciled field by field", sub_style),
        Spacer(1, 8),
        HRFlowable(width="100%", thickness=2, color=colors.HexColor(NAVY)),
        Spacer(1, 12),
    ]

    info = [
        ["Project", _esc_pdf(payload.get("project") or "—")],
        ["Source data", _esc_pdf(payload.get("source_file") or "—")],
        ["Generated output", _esc_pdf(payload.get("output_file") or "—")],
        ["Mapping reference", _esc_pdf(payload.get("mapping_reference") or "—")],
        ["Generated", date.today().strftime("%B %d, %Y")],
        ["Validated by", f"{payload.get('provider', '—')} · {payload.get('model', '—')}"],
    ]
    info_tbl = Table([[Paragraph(f"<b>{k}</b>", small), Paragraph(v, small)] for k, v in info],
                      colWidths=[4.0 * cm, 13.8 * cm])
    info_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor(LIGHT_BG)),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor(BORDER)),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story += [info_tbl, Spacer(1, 6)]

    # ── Incomplete-run banner ──
    # Printed before anything else: a run where fields were never verified must
    # never be read as a result.
    unverified = int((payload.get("totals") or {}).get("unverified") or 0)
    if unverified:
        warn = Table([[Paragraph(
            f'<b>INCOMPLETE RUN — DO NOT SIGN OFF.</b> {unverified} field(s) carry no verdict '
            f'because their AI comparison call failed. Their rows are marked '
            f'<b>UNVERIFIED</b> in the tables below and must not be read as findings.',
            ParagraphStyle("W", parent=body, textColor=colors.HexColor(STATUS_FG["MISMATCH"])))]],
            colWidths=[17.8 * cm])
        warn.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(STATUS_BG["MISMATCH"])),
            ("BOX", (0, 0), (-1, -1), 1.2, colors.HexColor(STATUS_FG["MISMATCH"])),
            ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ]))
        story += [warn, Spacer(1, 10)]

    # ── Executive Summary ──
    story.append(Paragraph("Executive Summary", h2))
    if payload.get("narrative"):
        story += [Paragraph(_esc_pdf(payload["narrative"], 1200), body), Spacer(1, 8)]

    metric_rows = [
        ["Records in source feed", str(totals.get("source_records", "—"))],
        ["Document instances located in output", str(totals.get("instances_matched", len(payload.get("instances", []))))],
        ["Mapped fields validated", str(roll["fields"])],
        ["Fields matching source → output", str(roll["MATCH"])],
        ["Mismatches identified", str(roll["MISMATCH"])],
        ["Gaps (in source, not rendered)", str(roll["GAP"])],
        ["Flagged for review", str(roll["REVIEW"])],
    ]
    if totals.get("deterministic") is not None:
        metric_rows.append(["Resolved without AI (rule-based)",
                            f"{totals['deterministic']} of {roll['fields']}"])
    metric_rows.append(["Overall assessment", payload.get("assessment") or "—"])

    m_tbl = Table([[Paragraph(f"<b>{k}</b>", small), Paragraph(_esc_pdf(v, 400), small)]
                   for k, v in metric_rows], colWidths=[7.4 * cm, 10.4 * cm])
    m_style = [
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor(LIGHT_BG)),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor(BORDER)),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]
    if roll["MISMATCH"]:
        i = 4
        m_style += [("TEXTCOLOR", (1, i), (1, i), colors.HexColor(STATUS_FG["MISMATCH"])),
                    ("FONTNAME", (1, i), (1, i), "Helvetica-Bold")]
    if roll["GAP"]:
        i = 5
        m_style += [("TEXTCOLOR", (1, i), (1, i), colors.HexColor(STATUS_FG["GAP"])),
                    ("FONTNAME", (1, i), (1, i), "Helvetica-Bold")]
    m_tbl.setStyle(TableStyle(m_style))
    story += [m_tbl]

    # ── Key Findings ──
    findings = payload.get("findings") or []
    if findings:
        story.append(Paragraph("Key Findings At A Glance", h2))
        for f in findings:
            ftype = f.get("type", "Observation")
            fg = FINDING_FG.get(ftype, GRAY)
            story.append(Paragraph(
                f'<font color="{fg}"><b>{_esc_pdf(ftype, 40)}</b></font> &nbsp;&mdash;&nbsp; {_esc_pdf(f.get("text"), 700)}',
                bullet, bulletText="•"))

    # ── Per-instance field tables ──
    story.append(Paragraph("Field Mapping Detail", h2))
    has_expected = any(r.get("expected") for inst in (payload.get("instances") or [])
                       for r in (inst.get("rows") or []))
    col_w = ([3.2 * cm, 3.9 * cm, 3.9 * cm, 1.9 * cm, 4.9 * cm] if has_expected
             else [3.5 * cm, 4.3 * cm, 4.3 * cm, 2.0 * cm, 3.7 * cm])
    src_header = "Expected Value" if has_expected else "Source Value"
    src_key = "expected" if has_expected else "source"

    for inst in payload.get("instances", []) or []:
        c = _instance_counts(inst)
        story.append(Paragraph(_esc_pdf(inst.get("title") or "Document instance", 300), h3))
        meta_bits = []
        if inst.get("subtitle"):
            meta_bits.append(_esc_pdf(inst["subtitle"], 200))
        meta_bits.append(f'<font color="{STATUS_FG["MATCH"]}">{c["MATCH"]} match</font> · '
                         f'<font color="{STATUS_FG["MISMATCH"]}">{c["MISMATCH"]} mismatch</font> · '
                         f'<font color="{STATUS_FG["GAP"]}">{c["GAP"]} gap</font> · '
                         f'<font color="{STATUS_FG["REVIEW"]}">{c["REVIEW"]} review</font>')
        story += [Paragraph(" &nbsp;|&nbsp; ".join(meta_bits), small_gray), Spacer(1, 4)]

        data = [[Paragraph("Mapped Field", th), Paragraph(src_header, th),
                 Paragraph("Output Value", th), Paragraph("Status", th), Paragraph("Notes", th)]]
        row_styles = []
        for i, r in enumerate(inst.get("rows", []) or [], start=1):
            st = _norm_status(r.get("status"))
            # An unverified row shows UNVERIFIED in place of a verdict it never earned.
            if r.get("unverified"):
                status_cell = (f'<b><font color="{STATUS_FG["MISMATCH"]}">UNVERIFIED</font></b><br/>'
                               f'<font size="6" color="{GRAY}">({st} unconfirmed)</font>')
            else:
                status_cell = f'<b><font color="{STATUS_FG[st]}">{st}</font></b>'
            data.append([
                Paragraph(f'<b>{_esc_pdf(r.get("field"), 120)}</b>', small),
                Paragraph(_esc_pdf(r.get(src_key) or r.get("source"), 260), small),
                Paragraph(_esc_pdf(r.get("output"), 260), small),
                Paragraph(status_cell,
                          ParagraphStyle(f"st{i}", parent=small, alignment=TA_CENTER)),
                Paragraph(_esc_pdf(r.get("notes"), 300), small_gray),
            ])
            row_styles.append(("BACKGROUND", (3, i), (3, i), colors.HexColor(STATUS_BG[st])))
            if i % 2 == 0:
                row_styles.append(("BACKGROUND", (0, i), (2, i), colors.HexColor("#FAFBFC")))
                row_styles.append(("BACKGROUND", (4, i), (4, i), colors.HexColor("#FAFBFC")))

        tbl = Table(data, colWidths=col_w, repeatRows=1)
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(NAVY)),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor(BORDER)),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ] + row_styles))
        story += [tbl, Spacer(1, 6)]

    # ── Requirements not verifiable from these inputs ──
    # Listed explicitly: if they vanished, coverage would look complete when it is not.
    nv = payload.get("not_verifiable") or []
    if nv:
        story.append(Paragraph("Declared Requirements Not Verifiable From These Inputs", h2))
        story.append(Paragraph(
            "These come from the BRD but cannot be checked against a data feed and extracted "
            "document text. They need a physical or process check — see the project checklist.",
            small_gray))
        story.append(Spacer(1, 5))
        nv_data = [[Paragraph("Ref", th), Paragraph("Requirement", th)]]
        for item in nv:
            nv_data.append([Paragraph(_esc_pdf(item.get("ref"), 40), small),
                            Paragraph(_esc_pdf(item.get("text"), 500), small)])
        nv_tbl = Table(nv_data, colWidths=[2.4 * cm, 15.4 * cm], repeatRows=1)
        nv_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(NAVY)),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor(BORDER)),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ]))
        story += [nv_tbl, Spacer(1, 6)]

    # ── Recommendations ──
    recs = payload.get("recommendations") or []
    if recs:
        story.append(Paragraph("Recommendations", h2))
        for rec in recs:
            story.append(Paragraph(_esc_pdf(rec, 700), bullet, bulletText="•"))

    def _footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor(GRAY))
        canvas.drawCentredString(A4[0] / 2.0, 1.0 * cm,
                                 f"Confidential — For Internal & Client Use Only     |     Page {doc_.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    buf.seek(0)
    return buf.read()


# ═══════════════════════════════════════════════════════════════
# HTML
# ═══════════════════════════════════════════════════════════════

def _html_status_cell(r: dict) -> str:
    """A row whose AI call never returned shows UNVERIFIED rather than a verdict
    it did not earn."""
    st = _norm_status(r.get("status"))
    if r.get("unverified"):
        return (f'<td class="stcell st-MISMATCH">UNVERIFIED'
                f'<br><small>({st} unconfirmed)</small></td>')
    return f'<td class="stcell st-{st}">{st}</td>'


def mapping_report_to_html(payload: dict) -> str:
    e = lambda v, n=400: html.escape(_clip(v, n))
    roll = _rollup(payload)
    totals = payload.get("totals") or {}

    info = [
        ("Project", payload.get("project")),
        ("Source data", payload.get("source_file")),
        ("Generated output", payload.get("output_file")),
        ("Mapping reference", payload.get("mapping_reference")),
        ("Generated", date.today().strftime("%B %d, %Y")),
        ("Validated by", f"{payload.get('provider', '—')} · {payload.get('model', '—')}"),
    ]
    info_html = "".join(f"<tr><th>{e(k)}</th><td>{e(v)}</td></tr>" for k, v in info)

    metrics = [
        ("Records in source feed", totals.get("source_records", "—"), None),
        ("Document instances located in output",
         totals.get("instances_matched", len(payload.get("instances", []))), None),
        ("Mapped fields validated", roll["fields"], None),
        ("Fields matching source → output", roll["MATCH"], "MATCH"),
        ("Mismatches identified", roll["MISMATCH"], "MISMATCH" if roll["MISMATCH"] else None),
        ("Gaps (in source, not rendered)", roll["GAP"], "GAP" if roll["GAP"] else None),
        ("Flagged for review", roll["REVIEW"], "REVIEW" if roll["REVIEW"] else None),
    ]
    if totals.get("deterministic") is not None:
        metrics.append(("Resolved without AI (rule-based)",
                        f"{totals['deterministic']} of {roll['fields']}", None))
    metrics.append(("Overall assessment", payload.get("assessment") or "—", None))
    metrics_html = "".join(
        f'<tr><th>{e(k)}</th><td{f" class=st-{cls}" if cls else ""}><b>{e(v)}</b></td></tr>'
        for k, v, cls in metrics)

    findings_html = ""
    if payload.get("findings"):
        rows = "".join(
            f'<li><span class="ftag f-{html.escape(f.get("type", "Observation"))}">'
            f'{e(f.get("type"), 40)}</span> {e(f.get("text"), 800)}</li>'
            for f in payload["findings"])
        findings_html = f'<h2>Key Findings At A Glance</h2><ul class="findings">{rows}</ul>'

    has_expected = any(r.get("expected") for inst in (payload.get("instances") or [])
                       for r in (inst.get("rows") or []))
    src_header = "Expected Value" if has_expected else "Source Value"
    src_key = "expected" if has_expected else "source"

    nav_items, inst_html = [], []
    for idx, inst in enumerate(payload.get("instances", []) or [], start=1):
        c = _instance_counts(inst)
        anchor = f"inst-{idx}"
        nav_items.append(f'<a href="#{anchor}">{e(inst.get("title") or f"Instance {idx}", 90)}</a>')
        rows = "".join(
            "<tr>"
            f"<td class=fld><b>{e(r.get('field'), 140)}</b></td>"
            f"<td>{e(r.get(src_key) or r.get('source'), 400)}</td>"
            f"<td>{e(r.get('output'), 400)}</td>"
            f"{_html_status_cell(r)}"
            f"<td class=notes>{e(r.get('notes'), 400)}</td>"
            "</tr>"
            for r in inst.get("rows", []) or [])
        inst_html.append(f"""
        <section id="{anchor}" class="inst">
          <h3>{e(inst.get("title") or f"Instance {idx}", 300)}</h3>
          <div class="imeta">{e(inst.get("subtitle") or "", 300)}
            <span class="pill st-MATCH">{c['MATCH']} match</span>
            <span class="pill st-MISMATCH">{c['MISMATCH']} mismatch</span>
            <span class="pill st-GAP">{c['GAP']} gap</span>
            <span class="pill st-REVIEW">{c['REVIEW']} review</span>
          </div>
          <div class="tblwrap"><table class="grid">
            <thead><tr><th>Mapped Field</th><th>{src_header}</th><th>Output Value</th>
                       <th>Status</th><th>Notes</th></tr></thead>
            <tbody>{rows}</tbody>
          </table></div>
        </section>""")

    nv_html = ""
    if payload.get("not_verifiable"):
        nv_rows = "".join(f"<tr><td class=fld>{e(i.get('ref'), 40)}</td>"
                          f"<td>{e(i.get('text'), 600)}</td></tr>"
                          for i in payload["not_verifiable"])
        nv_html = ("<h2>Declared Requirements Not Verifiable From These Inputs</h2>"
                   "<p class=narrative>From the BRD, but not checkable against a data feed and "
                   "extracted document text — these need a physical or process check.</p>"
                   f'<div class="tblwrap"><table class="grid"><thead><tr><th>Ref</th>'
                   f"<th>Requirement</th></tr></thead><tbody>{nv_rows}</tbody></table></div>")

    recs_html = ""
    if payload.get("recommendations"):
        items = "".join(f"<li>{e(r, 800)}</li>" for r in payload["recommendations"])
        recs_html = f"<h2>Recommendations</h2><ul class=recs>{items}</ul>"

    narrative_html = f'<p class="narrative">{e(payload["narrative"], 1500)}</p>' if payload.get("narrative") else ""

    unverified = int((payload.get("totals") or {}).get("unverified") or 0)
    banner_html = ""
    if unverified:
        banner_html = (
            f'<div class="banner"><b>INCOMPLETE RUN — DO NOT SIGN OFF.</b> {unverified} field(s) '
            f'carry no verdict because their AI comparison call failed. Their rows are marked '
            f'<b>UNVERIFIED</b> below and must not be read as findings.</div>')

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Field Mapping Validation Report</title>
<style>
  :root{{--navy:{NAVY};--dark:{DARK};--gray:{GRAY};--light:{LIGHT_BG};--border:{BORDER};}}
  *{{box-sizing:border-box}}
  body{{margin:0;padding:32px 20px;background:#F6F7FA;color:var(--dark);
       font:14px/1.55 Calibri,Segoe UI,system-ui,sans-serif}}
  .page{{max-width:1180px;margin:0 auto;background:#fff;border:1px solid var(--border);
        border-radius:10px;padding:34px 38px}}
  h1{{font-size:1.55rem;color:var(--navy);margin:0 0 4px;letter-spacing:.01em}}
  .sub{{color:var(--gray);font-size:.9rem;margin-bottom:16px}}
  .rule{{height:3px;background:var(--navy);margin:0 0 20px}}
  h2{{font-size:1.08rem;color:var(--navy);margin:26px 0 10px;
     border-bottom:1px solid var(--border);padding-bottom:5px}}
  h3{{font-size:.98rem;color:var(--navy);margin:22px 0 6px}}
  table{{border-collapse:collapse;width:100%}}
  .kv th,.kv td{{border:1px solid var(--border);padding:6px 9px;font-size:.83rem;text-align:left}}
  .kv th{{background:var(--light);width:270px;font-weight:700}}
  .narrative{{font-size:.9rem;color:var(--dark);margin:0 0 12px}}
  .tblwrap{{overflow-x:auto}}
  table.grid{{font-size:.8rem}}
  table.grid th{{background:var(--navy);color:#fff;text-align:left;padding:7px 8px;
                font-weight:700;position:sticky;top:0}}
  table.grid td{{border:1px solid var(--border);padding:6px 8px;vertical-align:top}}
  table.grid tbody tr:nth-child(even) td{{background:#FAFBFC}}
  td.fld{{white-space:nowrap}}
  td.notes{{color:var(--gray);font-size:.76rem}}
  .stcell{{text-align:center;font-weight:800;font-size:.72rem;letter-spacing:.03em;white-space:nowrap}}
  .st-MATCH{{background:{STATUS_BG['MATCH']}!important;color:{STATUS_FG['MATCH']}}}
  .st-MISMATCH{{background:{STATUS_BG['MISMATCH']}!important;color:{STATUS_FG['MISMATCH']}}}
  .st-GAP{{background:{STATUS_BG['GAP']}!important;color:{STATUS_FG['GAP']}}}
  .st-REVIEW{{background:{STATUS_BG['REVIEW']}!important;color:{STATUS_FG['REVIEW']}}}
  .imeta{{color:var(--gray);font-size:.78rem;margin-bottom:8px}}
  .pill{{display:inline-block;padding:2px 9px;border-radius:99px;font-size:.7rem;
        font-weight:700;margin-left:6px}}
  ul.findings{{list-style:none;padding:0;margin:0}}
  ul.findings li{{border-left:3px solid var(--border);padding:7px 12px;margin-bottom:7px;
                 background:#FAFBFC;font-size:.85rem}}
  .ftag{{font-weight:800;font-size:.72rem;text-transform:uppercase;letter-spacing:.04em;
        margin-right:8px}}
  .f-Mismatch{{color:{STATUS_FG['MISMATCH']}}} .f-Gap{{color:{STATUS_FG['GAP']}}}
  .f-Observation{{color:{STATUS_FG['REVIEW']}}}
  ul.recs li{{font-size:.85rem;margin-bottom:6px}}
  .banner{{margin:14px 0;padding:11px 14px;border:1.5px solid {STATUS_FG['MISMATCH']};
          background:{STATUS_BG['MISMATCH']};color:{STATUS_FG['MISMATCH']};font-size:.86rem;
          border-radius:5px}}
  .nav{{margin:10px 0 4px;font-size:.8rem}}
  .nav a{{color:var(--navy);margin-right:14px;text-decoration:none;border-bottom:1px dotted}}
  footer{{text-align:center;color:var(--gray);font-size:.74rem;margin-top:26px;
         border-top:1px solid var(--border);padding-top:12px}}
  @media print{{body{{background:#fff;padding:0}}.page{{border:none;border-radius:0}}
               table.grid th{{position:static}}}}
</style></head><body><div class="page">
  <h1>Field Mapping Validation Report</h1>
  <div class="sub">Source data &rarr; generated output, reconciled field by field</div>
  <div class="rule"></div>
  <table class="kv">{info_html}</table>
  {banner_html}
  <h2>Executive Summary</h2>
  {narrative_html}
  <table class="kv">{metrics_html}</table>
  {findings_html}
  <h2>Field Mapping Detail</h2>
  <div class="nav">{"".join(nav_items)}</div>
  {"".join(inst_html)}
  {nv_html}
  {recs_html}
  <footer>Confidential — For Internal &amp; Client Use Only</footer>
</div></body></html>"""
