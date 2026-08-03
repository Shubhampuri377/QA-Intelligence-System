"""Export builders for generated Test Data records (Coverage & Test Data
step) — JSON, XML, CSV, and styled Excel, each record traceable back to its
TC_ID / FR_ID / Scenario."""

import io
import json
import re
import xml.etree.ElementTree as ET
import xml.dom.minidom as minidom

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment


def _flatten_record(rec: dict) -> dict:
    flat = {"TC_ID": rec.get("TC_ID", ""), "FR_ID": rec.get("FR_ID", ""), "Scenario": rec.get("Scenario", "")}
    data = rec.get("Record")
    if isinstance(data, dict):
        flat.update({str(k): v for k, v in data.items()})
    return flat


def records_to_dataframe(records: list) -> pd.DataFrame:
    rows = [_flatten_record(r) for r in records]
    return pd.DataFrame(rows).fillna("") if rows else pd.DataFrame(columns=["TC_ID", "FR_ID", "Scenario"])


def records_to_json(records: list) -> str:
    return json.dumps(records, indent=2, default=str)


def records_to_csv(records: list) -> bytes:
    return records_to_dataframe(records).to_csv(index=False).encode("utf-8")


def records_to_excel(records: list) -> bytes:
    df = records_to_dataframe(records)
    wb = Workbook()
    ws = wb.active
    ws.title = "Test Data"

    header_fill = PatternFill("solid", fgColor="0D9488")
    header_font = Font(bold=True, color="FFFFFF", size=10)
    ws.append(list(df.columns))
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")

    for _, row in df.iterrows():
        ws.append(list(row))

    for i, col in enumerate(df.columns, start=1):
        max_len = df[col].astype(str).map(len).max() if len(df) else 0
        width = max(12, min(40, int(max_len) + 4))
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = width
    ws.freeze_panes = "A2"

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()


def _xml_safe_tag(name: str) -> str:
    tag = re.sub(r"[^A-Za-z0-9_]", "_", name.strip()) or "field"
    if tag[0].isdigit():
        tag = f"f_{tag}"
    return tag


def records_to_xml(records: list) -> str:
    root = ET.Element("TestData")
    for rec in records:
        rec_el = ET.SubElement(root, "Record", {
            "TC_ID": str(rec.get("TC_ID", "")),
            "FR_ID": str(rec.get("FR_ID", "")),
            "Scenario": str(rec.get("Scenario", "")),
        })
        data = rec.get("Record")
        if isinstance(data, dict):
            for k, v in data.items():
                field_el = ET.SubElement(rec_el, _xml_safe_tag(str(k)))
                field_el.text = "" if v is None else str(v)
    raw = ET.tostring(root, encoding="unicode")
    return minidom.parseString(raw).toprettyxml(indent="  ")
