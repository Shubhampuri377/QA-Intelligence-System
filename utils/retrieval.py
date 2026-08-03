"""
Evidence retrieval layer.

The naive approach to validation — paste the entire Data file and the entire
Output document into one giant prompt — breaks down the moment either file is
large (a data extract with tens of thousands of records, or a hundred-page
generated PDF). Instead, Data and Output are pre-split into small addressable
chunks (one per record / one per page), and for each requirement we do a fast,
local, non-AI keyword match to pull out only the chunks that are actually
relevant to it.

This keeps every Validation Agent call small and bounded regardless of total
file size, and the retrieved chunks double as the raw material for the
Evidence Agent — the "Input Record" / "Output Value" evidence shown in the
report is exactly what was retrieved here.
"""

import json
import re
from dataclasses import dataclass
from typing import List


@dataclass
class Chunk:
    ref: str
    text: str


def data_records_to_chunks(records: list) -> List[Chunk]:
    """Turns a list of parsed Data records (dicts, lists, or strings) into
    one retrievable chunk per record."""
    chunks = []
    for i, rec in enumerate(records, start=1):
        if isinstance(rec, (dict, list)):
            text = json.dumps(rec, indent=2, default=str)
        else:
            text = str(rec)
        if text.strip():
            chunks.append(Chunk(ref=f"Data Record {i}", text=text))
    return chunks


def output_pages_to_chunks(pages: List[str]) -> List[Chunk]:
    """Turns a list of per-page Output text into one retrievable chunk per page."""
    return [Chunk(ref=f"Output Page {i + 1}", text=t) for i, t in enumerate(pages) if t and t.strip()]


def _score(text: str, keywords: List[str]) -> int:
    low = text.lower()
    return sum(low.count(k) for k in keywords if k)


def retrieve(chunks: List[Chunk], keywords: List[str], top_k: int = 4, max_chars: int = 2200) -> List[Chunk]:
    """Returns the top_k chunks most relevant to `keywords`, each capped to
    max_chars. Falls back to the first few chunks if nothing scores above
    zero, so a requirement is never validated against an empty context —
    it's instead flagged by the LLM as unable to find matching evidence."""
    if not chunks:
        return []
    scored = sorted(chunks, key=lambda c: _score(c.text, keywords), reverse=True)
    top = [c for c in scored if _score(c.text, keywords) > 0][:top_k]
    if not top:
        top = chunks[:min(top_k, len(chunks))]
    return [Chunk(ref=c.ref, text=c.text[:max_chars]) for c in top]


def render_chunks(chunks: List[Chunk]) -> str:
    if not chunks:
        return "[NO RELEVANT CONTENT FOUND — requirement's fields did not match any record/page]"
    return "\n\n".join(f"[{c.ref}]\n{c.text}" for c in chunks)


def build_evidence_refs(data_chunks: List[Chunk], output_chunks: List[Chunk]) -> dict:
    return {
        "Input Record": ", ".join(c.ref for c in data_chunks) or "—",
        "Output Value": ", ".join(c.ref for c in output_chunks) or "—",
    }
