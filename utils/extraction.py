"""
Shared document extraction helpers used across all workflows.
Covers: PDF (text + tables + form fields + OCR fallback), Word (text + tables +
checkboxes), PDF annotations/comments, and mapping/data files (Excel/CSV/JSON/XML).
"""

import io
import json
import xml.dom.minidom as minidom
import xml.etree.ElementTree as ET
import concurrent.futures as cf

import fitz
import pandas as pd
import pytesseract
from PIL import Image
from pdf2image import convert_from_bytes
from pypdf import PdfReader
from docx import Document as DocxDoc
from docx.oxml.ns import qn


# ── PDF ──────────────────────────────────────────────────────────

def _ocr_scanned_pages(file_bytes: bytes, scanned_pages: set) -> dict:
    """Rasterizes only the page RANGE spanning the scanned pages (not the
    whole document) and OCRs them in parallel. On a large document where
    only a handful of pages are actually scanned images, this avoids
    converting/OCR-ing hundreds of pages that don't need it."""
    if not scanned_pages:
        return {}
    sorted_pages = sorted(scanned_pages)
    first, last = sorted_pages[0], sorted_pages[-1]
    try:
        images = convert_from_bytes(file_bytes, dpi=200, first_page=first + 1, last_page=last + 1)
    except Exception as e:
        return {pn: f"[OCR ERROR] {e}" for pn in sorted_pages}

    def ocr_one(pn):
        idx = pn - first
        if 0 <= idx < len(images):
            return pn, (pytesseract.image_to_string(images[idx], lang="eng") or "").strip()
        return pn, ""

    texts = {}
    with cf.ThreadPoolExecutor(max_workers=min(4, len(sorted_pages))) as executor:
        for pn, text in executor.map(ocr_one, sorted_pages):
            if text:
                texts[pn] = text
    return texts

def extract_pdf_full(file, include_form_fields: bool = True) -> str:
    """Full PDF extraction: text, table-like blocks, optional form fields, and
    OCR fallback for pages that are scanned images with no extractable text."""
    if not file:
        return ""
    file.seek(0)
    file_bytes = file.read()
    file.seek(0)
    parts = []
    scanned_pages = set()

    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text("text") or ""
            images = page.get_images(full=True)
            if text.strip():
                parts.append(f"[PAGE {page_num + 1} TEXT]\n{text.strip()}")
            if not text.strip() and len(images) > 0:
                scanned_pages.add(page_num)
            if text.strip():
                try:
                    blocks = page.get_text("blocks")
                    table_text = "\n".join(b[4] for b in blocks if len(b) > 3 and b[4].strip())
                    if table_text.strip():
                        parts.append(f"[PAGE {page_num + 1} BLOCKS]\n{table_text}")
                except Exception:
                    pass
        doc.close()
    except Exception as e:
        parts.append(f"[PDF READ ERROR] {e}")

    if include_form_fields:
        try:
            from PyPDF2 import PdfReader as PR2
            reader = PR2(io.BytesIO(file_bytes))
            fields = reader.get_fields() or {}
            if fields:
                form_lines = ["[FORM FIELDS]"]
                for name, field in fields.items():
                    val = field.get("/V", "")
                    ftype = field.get("/FT", "")
                    if ftype == "/Btn":
                        val = "☑ Checked" if str(val) not in ["/Off", "Off", "False", "", "None"] else "☐ Unchecked"
                    form_lines.append(f"{name} ({ftype}): {val}")
                parts.append("\n".join(form_lines))
        except Exception as e:
            parts.append(f"[FORM ERROR] {e}")

    ocr_texts = _ocr_scanned_pages(file_bytes, scanned_pages)
    for pn in sorted(ocr_texts):
        parts.append(f"[PAGE {pn + 1} OCR]\n{ocr_texts[pn]}")

    return "\n\n".join(parts) if parts else "[EMPTY DOCUMENT]"


def extract_pdf_comments(file) -> str:
    """Extracts annotation/comment text (used for lightweight mapping documents)."""
    if not file:
        return ""
    comments = []
    try:
        file.seek(0)
        reader = PdfReader(io.BytesIO(file.read()))
        for page in reader.pages:
            annots = page.get("/Annots", [])
            if not annots:
                continue
            for annot in annots:
                obj = annot.get_object() if hasattr(annot, "get_object") else annot
                subtype = obj.get("/Subtype")
                if subtype in ["/Text", "/FreeText", "/Popup", "/Highlight", "/Underline", "/StrikeOut", "/Squiggly"]:
                    content = obj.get("/Contents")
                    if content:
                        text = str(content).strip()
                        if text:
                            comments.append(text)
    except Exception:
        pass
    return "\n".join(comments)


# ── Word ─────────────────────────────────────────────────────────

def extract_word_full(file) -> str:
    """Full Word extraction: headings/paragraphs, tables, checkboxes, image count."""
    if not file:
        return ""
    parts = []
    try:
        doc = DocxDoc(io.BytesIO(file.read()))
        lines = []
        for p in doc.paragraphs:
            t = (p.text or "").strip()
            if t:
                style = p.style.name if p.style else ""
                lines.append(f"\n## {t}" if "Heading" in style else t)
        if lines:
            parts.append("[DOCUMENT TEXT]\n" + "\n".join(lines))

        for ti, table in enumerate(doc.tables):
            rows = [" | ".join(c.text.strip().replace("\n", " ") for c in row.cells) for row in table.rows]
            if rows:
                parts.append(f"[TABLE {ti + 1}]\n" + "\n".join(rows))

        cbs = []
        for elem in doc.element.body.iter():
            if "sdt" in elem.tag.lower():
                ve = elem.findall(".//{http://schemas.microsoft.com/office/word/2010/wordml}checked")
                le = elem.findall(".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")
                if ve:
                    checked = ve[0].get("{http://schemas.microsoft.com/office/word/2010/wordml}val", "0") == "1"
                    label = " ".join(e.text for e in le if e.text).strip()
                    if label:
                        cbs.append(f"  {'☑' if checked else '☐'} {label}")
        if cbs:
            parts.append("[CHECKBOXES]\n" + "\n".join(cbs))

        ic = sum(1 for r in doc.part.rels.values() if "image" in r.reltype)
        if ic:
            parts.append(f"[IMAGES] {ic} embedded image(s) noted.")
    except Exception as e:
        parts.append(f"[WORD WARNING: {e}]")
    return "\n\n".join(parts) if parts else "[EMPTY DOCUMENT]"


# ── Generic dispatchers ─────────────────────────────────────────

def extract_document(file) -> str:
    """Generic BRD/spec-style document extraction: PDF, Word, or plain text."""
    if not file:
        return ""
    ext = file.name.rsplit(".", 1)[-1].lower()
    if ext == "pdf":
        return extract_pdf_full(file)
    if ext in ("docx", "doc"):
        return extract_word_full(file)
    if ext == "txt":
        return file.read().decode("utf-8", errors="ignore")
    return ""


def extract_multi_document(files) -> str:
    """Extracts and concatenates multiple BRD-style files into one labeled
    corpus, preserving upload order so downstream ordering rules (FR/REQ IDs
    following document sequence) still apply across sources."""
    if not files:
        return ""
    parts = []
    for f in files:
        text = extract_document(f)
        parts.append(f"=== BRD SOURCE: {f.name} ===\n{text or '[EMPTY DOCUMENT]'}")
    return "\n\n".join(parts)


def extract_mapping_file(file) -> str:
    """Mapping/lookup document: PDF, Word, Excel, CSV, or text. Used only to
    align field names/terminology — never as a source of new requirements."""
    if not file:
        return ""
    ext = file.name.rsplit(".", 1)[-1].lower()
    try:
        if ext == "pdf":
            return extract_pdf_full(file)
        if ext in ("docx", "doc"):
            return extract_word_full(file)
        if ext in ("xlsx", "xls"):
            file.seek(0)
            sheets = pd.read_excel(io.BytesIO(file.read()), sheet_name=None,
                                    engine="openpyxl" if ext == "xlsx" else None)
            parts = []
            for name, df in sheets.items():
                df = df.fillna("")
                parts.append(f"[SHEET: {name}]\n" + df.to_csv(sep="|", index=False))
            return "\n\n".join(parts) if parts else "[EMPTY MAPPING FILE]"
        if ext == "csv":
            file.seek(0)
            df = pd.read_csv(file).fillna("")
            return df.to_csv(sep="|", index=False)
        if ext == "txt":
            return file.read().decode("utf-8", errors="ignore")
    except Exception as e:
        return f"[MAPPING READ ERROR] {e}"
    return ""


def extract_data_file(file):
    """Structured source-of-truth data file (JSON or XML). Returns (pretty_text, record_count)."""
    if not file:
        return "", 0
    ext = file.name.rsplit(".", 1)[-1].lower()
    raw = file.read()
    try:
        raw_str = raw.decode("utf-8", errors="ignore")
    except Exception:
        raw_str = str(raw)

    if ext == "json":
        try:
            parsed = json.loads(raw_str)
            pretty = json.dumps(parsed, indent=2)
            count = len(parsed) if isinstance(parsed, list) else 1
            return pretty, count
        except Exception as e:
            return f"[JSON PARSE ERROR] {e}\n\nRAW CONTENT:\n{raw_str}", 0

    if ext == "xml":
        try:
            pretty = minidom.parseString(raw_str).toprettyxml(indent="  ")
            pretty = "\n".join(l for l in pretty.split("\n") if l.strip())
            root = ET.fromstring(raw_str)
            count = len(list(root))
            return pretty, count
        except Exception as e:
            return f"[XML PARSE ERROR] {e}\n\nRAW CONTENT:\n{raw_str}", 0

    return raw_str, 0


def extract_pdf_pages(file) -> list:
    """Per-page PDF extraction (text + OCR fallback for scanned pages), kept
    addressable by page number. Used for the Output document and for
    Print-Image data sources, so the retrieval layer can pull individual
    pages instead of the whole document."""
    if not file:
        return []
    file.seek(0)
    file_bytes = file.read()
    file.seek(0)
    pages = []
    scanned = set()
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        for page_num in range(len(doc)):
            page = doc[page_num]
            text = (page.get_text("text") or "").strip()
            pages.append(text)
            if not text and page.get_images(full=True):
                scanned.add(page_num)
        doc.close()
    except Exception as e:
        return [f"[PDF READ ERROR] {e}"]

    ocr_texts = _ocr_scanned_pages(file_bytes, scanned)
    for pn, text in ocr_texts.items():
        pages[pn] = text
    return pages


# ── Input Data (QA Validation — multi-format) ──────────────────────

INPUT_DATA_FORMATS = [
    ("JSON", True),
    ("XML", True),
    ("CSV / Excel", True),
    ("Print Image", True),
    ("Fixed-Length", False),
    ("Multi-Length", False),
    ("Symitar", False),
]


def extract_input_records(file, fmt: str):
    """Dispatches a Data source file to the right parser based on the
    user-selected format. Returns (records: list, note: str). JSON, XML,
    CSV/Excel and Print Image are parsed into individually addressable
    records/pages. Fixed-Length, Multi-Length and Symitar have no record
    layout/copybook available yet, so they fall back to best-effort raw
    line ingestion — still usable, just lower fidelity until a layout
    spec is added."""
    if not file:
        return [], ""
    fmt = (fmt or "").strip()
    if fmt == "JSON":
        return _records_from_json(file)
    if fmt == "XML":
        return _records_from_xml(file)
    if fmt == "CSV / Excel":
        return _records_from_tabular(file)
    if fmt == "Print Image":
        return _records_from_print_image(file)
    return _records_from_raw_lines(file, fmt)


def _records_from_json(file):
    file.seek(0)
    raw = file.read().decode("utf-8", errors="ignore")
    try:
        parsed = json.loads(raw)
    except Exception as e:
        return [f"[JSON PARSE ERROR] {e}"], f"Could not parse JSON — {e}"
    if isinstance(parsed, list):
        return parsed, f"{len(parsed)} record(s) parsed from JSON array"
    if isinstance(parsed, dict):
        for k, v in parsed.items():
            if isinstance(v, list) and v:
                return v, f"{len(v)} record(s) parsed from JSON key '{k}'"
        return [parsed], "1 record parsed (single JSON object)"
    return [parsed], "1 record parsed"


def _xml_to_dict(elem):
    d = {}
    if elem.attrib:
        d.update({f"@{k}": v for k, v in elem.attrib.items()})
    if len(elem) == 0:
        text = (elem.text or "").strip()
        return {**d, "_text": text} if d else text
    for child in elem:
        val = _xml_to_dict(child)
        if child.tag in d:
            if not isinstance(d[child.tag], list):
                d[child.tag] = [d[child.tag]]
            d[child.tag].append(val)
        else:
            d[child.tag] = val
    return d


def _records_from_xml(file):
    file.seek(0)
    raw = file.read().decode("utf-8", errors="ignore")
    try:
        root = ET.fromstring(raw)
    except Exception as e:
        return [f"[XML PARSE ERROR] {e}"], f"Could not parse XML — {e}"
    children = list(root)
    if not children:
        return [_xml_to_dict(root)], "1 record parsed (root element)"

    # The record element is the one that REPEATS. Taking every root child made
    # <File_Header> and <File_Trailer> into records alongside the real invoices —
    # a 2-invoice feed reported as 4 records, with two of them carrying no
    # document fields at all and every verdict against them meaningless.
    # Non-repeating siblings are file-level metadata, so they are excluded and
    # named in the note rather than dropped silently.
    counts = {}
    for c in children:
        counts[c.tag] = counts.get(c.tag, 0) + 1
    repeating = [t for t, n in counts.items() if n > 1]

    if not repeating:
        # Nothing repeats: the whole document describes one thing.
        return [_xml_to_dict(root)], ("1 record parsed — no repeating element under "
                                      f"<{root.tag}>, so the document is treated as a single record")

    tag = max(repeating, key=lambda t: counts[t])
    records = [_xml_to_dict(c) for c in children if c.tag == tag]
    skipped = [t for t in counts if t != tag]
    note = f"{len(records)} record(s) parsed from XML — one per <{tag}> element"
    if skipped:
        note += f"; treated as file-level metadata, not records: {', '.join('<' + t + '>' for t in skipped)}"
    return records, note


def _records_from_tabular(file):
    ext = file.name.rsplit(".", 1)[-1].lower()
    file.seek(0)
    # dtype=str is essential, not a preference: pandas otherwise infers types and
    # silently corrupts identifiers — policyId "0004073361" becomes 4073361 and
    # an amount "1050.50" becomes 1050.5. Both would then fail to match a document
    # that renders them correctly, so the same feed would validate as JSON and
    # break as CSV. Every value stays exactly as written in the file.
    try:
        if ext in ("xlsx", "xls"):
            df = pd.read_excel(io.BytesIO(file.read()),
                               engine="openpyxl" if ext == "xlsx" else None, dtype=str)
        else:
            df = pd.read_csv(file, dtype=str)
    except Exception as e:
        return [f"[TABULAR PARSE ERROR] {e}"], f"Could not parse file — {e}"
    df = df.fillna("")
    records = df.to_dict(orient="records")
    return records, f"{len(records)} row(s) parsed from {ext.upper()}"


def _records_from_print_image(file):
    ext = file.name.rsplit(".", 1)[-1].lower()
    file.seek(0)
    if ext == "pdf":
        pages = extract_pdf_pages(file)
    else:
        try:
            img = Image.open(io.BytesIO(file.read()))
            pages = [(pytesseract.image_to_string(img, lang="eng") or "").strip()]
        except Exception as e:
            pages = [f"[IMAGE OCR ERROR] {e}"]
    records = [p for p in pages if p and p.strip()]
    return records, f"{len(records)} page(s) OCR'd from Print Image source"


def _records_from_raw_lines(file, fmt: str = ""):
    file.seek(0)
    raw = file.read()
    try:
        text = raw.decode("utf-8", errors="ignore")
    except Exception:
        text = str(raw)
    lines = [l for l in text.splitlines() if l.strip()]
    note = (f"{len(lines)} raw line(s) ingested as \"{fmt}\" — no record layout/copybook supplied yet, "
            "so this format is treated as unstructured text. Structured field-level parsing coming soon.")
    return lines, note


def enforce_validations(frs: list) -> list:
    """Ensures every FR has at least a minimal Validations list (defensive
    post-processing for FRS generation)."""
    for fr in frs:
        if not fr.get("Validations"):
            rules = fr.get("Business Rules", [])
            fr["Validations"] = [f"System must enforce: {r}" for r in rules] or [
                "Validate all required input fields", "Ensure data integrity before processing"]
    return frs
