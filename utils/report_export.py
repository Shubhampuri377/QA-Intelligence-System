"""PDF and HTML report builders for the QA Validation agentic pipeline.

Order matters here: requirements always appear in their original BRD/REQ-ID
sequence, never regrouped by outcome — a "table of contents" coverage table
sits right at the top (after the Executive Summary) so pass/fail is visible
at a glance, and the full detailed section below it walks through every
requirement in that same order."""

from datetime import date
from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
                                 PageBreak, HRFlowable, KeepTogether)
from reportlab.lib.enums import TA_CENTER

STATUS_COLORS_PDF = {
    "Pass": colors.HexColor("#16a34a"), "Fail": colors.HexColor("#dc2626"),
    "Warning": colors.HexColor("#d97706"), "Not Applicable": colors.HexColor("#6b7280"),
}
STATUS_BG_PDF = {
    "Pass": colors.HexColor("#f0fdf4"), "Fail": colors.HexColor("#fff0f0"),
    "Warning": colors.HexColor("#fffbeb"), "Not Applicable": colors.HexColor("#f3f4f6"),
}


def _pdf_requirement_card(r: dict, label_style, body_style, detail_style) -> list:
    """One requirement's full detail block, in the full Detailed Results section."""
    block = []
    status = r.get("Status", "")
    fg = STATUS_COLORS_PDF.get(status, colors.black)
    source_label = "Rule-Checked" if r.get("Validated_By") == "Deterministic" else "AI-Verified"
    header_data = [[
        Paragraph(f"<b>{r.get('Requirement_ID', '')}</b>  ·  {r.get('Validation_Type', '')}  ·  {source_label}", label_style),
        Paragraph(f"<b>{status}</b>", ParagraphStyle("StX", parent=label_style, textColor=fg, alignment=TA_CENTER)),
        Paragraph(f"Confidence: {r.get('Confidence', 0)}%", ParagraphStyle("CfX", parent=label_style, alignment=TA_CENTER)),
    ]]
    h_tbl = Table(header_data, colWidths=[8.6 * cm, 2.9 * cm, 3.5 * cm])
    h_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), STATUS_BG_PDF.get(status, colors.HexColor("#f9fafb"))),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (0, 0), 8),
    ]))
    block.append(h_tbl)
    block.append(Spacer(1, 4))
    block.append(Paragraph(f"<b>{r.get('Requirement_Text', '')}</b>", body_style))
    if r.get("Business_Rule"):
        block.append(Spacer(1, 2))
        block.append(Paragraph(f"<b>Business Rule:</b> {r['Business_Rule']}", detail_style))
    block.append(Spacer(1, 3))
    block.append(Paragraph(f"<b>Reason:</b> {r.get('Reason', '—')}", detail_style))
    ev = r.get("Evidence") or {}
    for k, v in ev.items():
        if v:
            block.append(Paragraph(f"<b>{k}:</b> {str(v)[:220]}", detail_style))
    block.append(Spacer(1, 4))
    block.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#eaecf5")))
    block.append(Spacer(1, 8))
    return block


def agentic_report_to_pdf(results: list, issues: list, summary: dict, meta: dict) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=1.8 * cm, bottomMargin=1.8 * cm,
                             leftMargin=1.8 * cm, rightMargin=1.8 * cm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("TitleX", parent=styles["Title"], fontSize=26,
                                  textColor=colors.HexColor("#1e1b4b"), alignment=TA_CENTER, spaceAfter=6)
    sub_style = ParagraphStyle("SubX", parent=styles["Normal"], fontSize=11,
                                textColor=colors.HexColor("#6b7280"), alignment=TA_CENTER, spaceAfter=4)
    h2 = ParagraphStyle("H2X", parent=styles["Heading2"], fontSize=14,
                         textColor=colors.HexColor("#1e1b4b"), spaceBefore=14, spaceAfter=8)
    label_style = ParagraphStyle("LabelX", parent=styles["Normal"], fontSize=8,
                                  textColor=colors.HexColor("#6b7280"), fontName="Helvetica-Bold")
    body_style = ParagraphStyle("BodyX", parent=styles["Normal"], fontSize=9.5,
                                 textColor=colors.HexColor("#1f2937"), leading=13)
    detail_style = ParagraphStyle("DetailX", parent=styles["Normal"], fontSize=8.5,
                                   textColor=colors.HexColor("#6b7280"), leading=12)

    story = [Spacer(1, 40),
             Paragraph("QA VALIDATION REPORT", title_style),
             Paragraph("Agentic BRD · Data · Output Cross-Validation", sub_style),
             Spacer(1, 6),
             HRFlowable(width="100%", thickness=2, color=colors.HexColor("#6366f1")),
             Spacer(1, 20),
             Paragraph(f"Generated: {date.today().strftime('%B %d, %Y')}", sub_style),
             Paragraph(f"AI Provider: {meta.get('provider', '—')}  ·  Model: {meta.get('model', '—')}", sub_style),
             Spacer(1, 24)]

    # ── Executive Summary ──
    story.append(Paragraph("Executive Summary", h2))
    exec_data = [
        ["Requirements", "Passed", "Failed", "Warnings", "N/A", "Pass Rate", "Avg. Confidence"],
        [str(summary["total_requirements"]), str(summary["passed"]), str(summary["failed"]),
         str(summary["warning"]), str(summary["not_applicable"]),
         f"{summary['pass_rate']}%", f"{summary['avg_confidence']}%"],
    ]
    exec_tbl = Table(exec_data, colWidths=[2.4 * cm] * 7)
    exec_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e1b4b")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#f5f3ff")),
        ("TOPPADDING", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e0e3f7")),
        ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"), ("FONTSIZE", (0, 1), (-1, 1), 12),
        ("TEXTCOLOR", (2, 1), (2, 1), colors.HexColor("#dc2626") if summary["failed"] > 0 else colors.HexColor("#1f2937")),
    ]))
    story.append(exec_tbl)
    if summary["critical_risks"] > 0:
        story.append(Spacer(1, 10))
        crit_style = ParagraphStyle("CritX", parent=styles["Normal"], fontSize=10,
                                     textColor=colors.HexColor("#dc2626"), fontName="Helvetica-Bold")
        story.append(Paragraph(f"Warning: {summary['critical_risks']} failed requirement(s) — review before sign-off.", crit_style))
    if summary["missing_requirements"] > 0:
        story.append(Spacer(1, 6))
        story.append(Paragraph(f"Warning: {summary['missing_requirements']} requirement(s) have no validation result — see Reviewer Findings.", detail_style))
    if summary.get("deterministic_count", 0) > 0:
        story.append(Spacer(1, 6))
        eff_style = ParagraphStyle("EffX", parent=styles["Normal"], fontSize=9,
                                    textColor=colors.HexColor("#059669"), fontName="Helvetica-Bold")
        story.append(Paragraph(
            f"{summary['deterministic_count']} of {summary['total_requirements']} requirements were "
            f"validated by deterministic rule-based checks (instant, zero AI cost) — only "
            f"{summary.get('ai_count', 0)} required AI reasoning.", eff_style))
    story.append(PageBreak())

    # ── Table of Contents — full coverage table, in REQ order, right up front ──
    story.append(Paragraph("Requirement Coverage", h2))
    story.append(Paragraph("Every requirement, in its original order — scan Status for what failed or needs a look; full detail for each follows below.", detail_style))
    story.append(Spacer(1, 8))
    tbl_data = [["ID", "Requirement", "Status", "Confidence"]]
    for r in results:
        tbl_data.append([
            r.get("Requirement_ID", ""),
            Paragraph(str(r.get("Requirement_Text", "")), detail_style),
            r.get("Status", ""), f"{r.get('Confidence', 0)}%",
        ])
    sum_tbl = Table(tbl_data, colWidths=[2.2 * cm, 9.8 * cm, 2.6 * cm, 2.4 * cm], repeatRows=1)
    tbl_style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e1b4b")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e5e7eb")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    for i, r in enumerate(results, start=1):
        bg = STATUS_BG_PDF.get(r.get("Status"), colors.white)
        fg = STATUS_COLORS_PDF.get(r.get("Status"), colors.black)
        tbl_style.append(("BACKGROUND", (2, i), (2, i), bg))
        tbl_style.append(("TEXTCOLOR", (2, i), (2, i), fg))
        tbl_style.append(("FONTNAME", (2, i), (2, i), "Helvetica-Bold"))
    sum_tbl.setStyle(TableStyle(tbl_style))
    story.append(sum_tbl)
    story.append(PageBreak())

    # ── Reviewer Findings / Risks ──
    story.append(Paragraph("Reviewer Findings &amp; Risks", h2))
    if not issues:
        story.append(Paragraph("No reviewer issues were flagged.", body_style))
    for i in issues:
        block = [
            Paragraph(f"<b>{i.get('Issue_Type', '')}</b>  ·  {i.get('Requirement_ID', '')}", body_style),
            Spacer(1, 2),
            Paragraph(i.get("Description", ""), detail_style),
        ]
        if i.get("Recommended_Action"):
            block.append(Paragraph(f"<i>Recommended action: {i['Recommended_Action']}</i>", detail_style))
        block.append(Spacer(1, 6))
        block.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#eaecf5")))
        block.append(Spacer(1, 8))
        story.append(KeepTogether(block))
    story.append(PageBreak())

    # ── Detailed Validation Results — every requirement, original REQ order ──
    story.append(Paragraph("Detailed Validation Results", h2))
    story.append(Paragraph(f"All {len(results)} requirement(s), in original order.", detail_style))
    story.append(Spacer(1, 10))
    for r in results:
        story.append(KeepTogether(_pdf_requirement_card(r, label_style, body_style, detail_style)))

    doc.build(story)
    buf.seek(0)
    return buf.read()


def _html_requirement_card(r: dict, status_class: dict) -> str:
    sc = status_class.get(r.get("Status"), "st-na")
    ev = r.get("Evidence") or {}
    ev_html = "".join(f'<div class="evidence-item"><b>{k}:</b> {v}</div>' for k, v in ev.items() if v)
    by_det = r.get("Validated_By") == "Deterministic"
    source_badge = ('<span class="vc-source vc-source-det">Rule-Checked</span>' if by_det
                   else '<span class="vc-source vc-source-ai">AI-Verified</span>')
    return f"""
    <div class="vc-card" id="{r.get('Requirement_ID', '')}">
      <div class="vc-top">
        <span class="vc-id">{r.get('Requirement_ID', '')}</span>
        <span class="vc-cat">{r.get('Validation_Type', '')}</span>
        <span class="vc-status {sc}">{r.get('Status', '')}</span>
        {source_badge}
      </div>
      <div class="vc-req">{r.get('Requirement_Text', '')}</div>
      <div class="vc-text" style="margin-bottom:8px;">{r.get('Reason', '')}</div>
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
        <div style="flex:1;height:7px;border-radius:99px;background:#EEF0FA;overflow:hidden;">
          <div style="height:100%;width:{r.get('Confidence', 0)}%;border-radius:99px;background:linear-gradient(90deg,#4F46E5,#7C3AED);"></div>
        </div>
        <span style="font-size:0.72rem;font-weight:700;color:#6b7280;">{r.get('Confidence', 0)}% confidence</span>
      </div>
      {f'<div class="evidence-box">{ev_html}</div>' if ev_html else ''}
    </div>"""


def agentic_report_to_html(results: list, issues: list, summary: dict, meta: dict) -> str:
    status_class = {"Pass": "st-pass", "Fail": "st-fail", "Warning": "st-warn", "Not Applicable": "st-na"}

    # Table of contents — every requirement, original order, status visible at a glance
    toc_rows = "".join(f"""
        <tr class="toc-row">
          <td class="toc-id"><a href="#{r.get('Requirement_ID', '')}">{r.get('Requirement_ID', '')}</a></td>
          <td class="toc-text">{r.get('Requirement_Text', '')}</td>
          <td><span class="vc-status {status_class.get(r.get('Status'), 'st-na')}">{r.get('Status', '')}</span></td>
          <td class="toc-conf">{r.get('Confidence', 0)}%</td>
        </tr>""" for r in results)

    # Full detail — same original order, no regrouping by outcome
    detail_html = "".join(_html_requirement_card(r, status_class) for r in results)

    issue_rows = "".join(f"""
        <div class="reviewer-card">
          <div class="reviewer-title">{i.get('Issue_Type', '')} · {i.get('Requirement_ID', '')}</div>
          <div class="reviewer-desc">{i.get('Description', '')}</div>
          {f'<div class="reviewer-desc"><i>Recommended: {i.get("Recommended_Action")}</i></div>' if i.get('Recommended_Action') else ''}
        </div>""" for i in issues) or '<p style="color:#6b7280;font-size:0.85rem;">No reviewer issues were flagged.</p>'

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>QA Validation Report</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&family=JetBrains+Mono:wght@500;600&display=swap');
*{{box-sizing:border-box;margin:0;padding:0;}}
body{{font-family:'Inter',sans-serif;background:#f4f5fb;color:#111827;padding:36px;}}
.wrap{{max-width:980px;margin:0 auto;}}
.header{{background:linear-gradient(135deg,#1e1b4b,#2d2a6e);border-radius:18px;padding:28px 32px;margin-bottom:24px;color:#fff;}}
.header h1{{font-size:1.6rem;font-weight:800;}}
.header p{{font-size:0.8rem;color:#a5b4fc;margin-top:6px;}}
.stats-row{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:14px;}}
.stat-box{{background:#fff;border:1px solid #eaecf5;border-radius:16px;padding:16px;text-align:center;box-shadow:0 2px 8px rgba(0,0,0,0.04);}}
.stat-val{{font-size:1.7rem;font-weight:900;font-family:'JetBrains Mono',monospace;}}
.stat-lbl{{font-size:0.62rem;font-weight:700;text-transform:uppercase;letter-spacing:0.6px;color:#9ca3af;margin-top:4px;}}
.v-purple{{color:#4f46e5;}}.v-green{{color:#059669;}}.v-red{{color:#e11d48;}}.v-amber{{color:#d97706;}}.v-gray{{color:#6b7280;}}.v-blue{{color:#2563eb;}}
.section-title{{font-size:0.68rem;font-weight:700;text-transform:uppercase;letter-spacing:1.4px;color:#6366f1;margin:24px 0 12px;}}
.section-note{{font-size:0.78rem;color:#6b7280;margin:-6px 0 12px;}}
.toc-table{{width:100%;border-collapse:collapse;background:#fff;border:1px solid #eaecf5;border-radius:14px;overflow:hidden;font-size:0.82rem;}}
.toc-table th{{background:#1e1b4b;color:#fff;text-align:left;padding:9px 12px;font-size:0.68rem;text-transform:uppercase;letter-spacing:0.05em;}}
.toc-table td{{padding:8px 12px;border-top:1px solid #eaecf5;vertical-align:top;}}
.toc-id a{{font-family:'JetBrains Mono',monospace;font-size:0.74rem;font-weight:700;color:#4f46e5;text-decoration:none;}}
.toc-id a:hover{{text-decoration:underline;}}
.toc-conf{{font-family:'JetBrains Mono',monospace;color:#6b7280;white-space:nowrap;}}
.toc-table-wrap{{overflow-x:auto;margin-bottom:8px;}}
.vc-card{{border:1px solid #eaecf5;border-radius:14px;padding:16px 18px;margin-bottom:10px;background:#fff;box-shadow:0 1px 4px rgba(0,0,0,0.04);scroll-margin-top:16px;}}
.vc-top{{display:flex;align-items:center;gap:10px;margin-bottom:8px;flex-wrap:wrap;}}
.vc-id{{font-size:0.66rem;font-weight:700;color:#6366f1;font-family:'JetBrains Mono',monospace;text-transform:uppercase;letter-spacing:1px;background:#eef2ff;border:1px solid #c7d2fe;border-radius:6px;padding:2px 8px;}}
.vc-cat{{font-size:0.64rem;font-weight:700;padding:3px 9px;border-radius:20px;background:#f5f3ff;color:#6d28d9;border:1px solid #ddd6fe;}}
.vc-status{{font-size:0.66rem;font-weight:800;padding:3px 11px;border-radius:20px;text-transform:uppercase;letter-spacing:0.5px;margin-left:auto;}}
.st-pass{{background:#f0fdf4;color:#16a34a;border:1px solid #bbf7d0;}}
.st-fail{{background:#fff0f0;color:#dc2626;border:1px solid #fecaca;}}
.st-warn{{background:#fffbeb;color:#d97706;border:1px solid #fde68a;}}
.st-na{{background:#f3f4f6;color:#6b7280;border:1px solid #e5e7eb;}}
.vc-source{{font-size:0.62rem;font-weight:700;padding:3px 10px;border-radius:20px;white-space:nowrap;}}
.vc-source-det{{background:#f0fdf4;color:#16a34a;border:1px solid #bbf7d0;}}
.vc-source-ai{{background:#eef2ff;color:#4f46e5;border:1px solid #c7d2fe;}}
.vc-req{{font-size:0.9rem;font-weight:700;color:#111827;margin-bottom:6px;}}
.vc-text{{font-size:0.82rem;color:#374151;line-height:1.5;}}
.evidence-box{{margin-top:8px;padding:10px 12px;background:#f7f8fc;border-radius:10px;border:1px solid #eaecf5;}}
.evidence-item{{font-size:0.76rem;color:#4b5563;line-height:1.6;}}
.evidence-item b{{color:#111827;}}
.reviewer-card{{border:1px solid #eaecf5;border-left:4px solid #f59e0b;border-radius:12px;padding:12px 16px;margin-bottom:8px;background:#fff;}}
.reviewer-title{{font-size:0.84rem;font-weight:700;color:#111827;}}
.reviewer-desc{{font-size:0.78rem;color:#6b7280;margin-top:3px;line-height:1.5;}}
.footer{{margin-top:30px;text-align:center;font-size:0.72rem;color:#9ca3af;}}
</style></head>
<body><div class="wrap">
  <div class="header">
    <h1>QA Validation Report</h1>
    <p>Generated {date.today().strftime('%B %d, %Y')} · AI Provider: {meta.get('provider', '—')} · Model: {meta.get('model', '—')}</p>
  </div>
  <div class="stats-row">
    <div class="stat-box"><div class="stat-val v-purple">{summary['total_requirements']}</div><div class="stat-lbl">Requirements</div></div>
    <div class="stat-box"><div class="stat-val v-green">{summary['passed']}</div><div class="stat-lbl">Passed</div></div>
    <div class="stat-box"><div class="stat-val v-red">{summary['failed']}</div><div class="stat-lbl">Failed</div></div>
    <div class="stat-box"><div class="stat-val v-amber">{summary['warning']}</div><div class="stat-lbl">Warnings</div></div>
  </div>
  <div class="stats-row">
    <div class="stat-box"><div class="stat-val v-gray">{summary['pass_rate']}%</div><div class="stat-lbl">Pass Rate</div></div>
    <div class="stat-box"><div class="stat-val v-blue">{summary['avg_confidence']}%</div><div class="stat-lbl">Avg. Confidence</div></div>
    <div class="stat-box"><div class="stat-val v-green">{summary.get('deterministic_count', 0)}</div><div class="stat-lbl">Rule-Checked</div></div>
    <div class="stat-box"><div class="stat-val v-blue">{summary.get('ai_count', 0)}</div><div class="stat-lbl">AI-Verified</div></div>
  </div>
  <div class="section-title">Requirement Coverage</div>
  <div class="section-note">Every requirement, in its original order — click an ID to jump to its full detail below.</div>
  <div class="toc-table-wrap">
    <table class="toc-table">
      <tr><th>ID</th><th>Requirement</th><th>Status</th><th>Confidence</th></tr>
      {toc_rows}
    </table>
  </div>
  <div class="section-title">Reviewer Findings &amp; Risks</div>
  {issue_rows}
  <div class="section-title">Detailed Validation Results</div>
  <div class="section-note">All {len(results)} requirement(s), in original order.</div>
  {detail_html}
  <div class="footer">Generated by QA Validation &nbsp;·&nbsp; {summary['total_requirements']} requirements validated</div>
</div></body></html>"""
