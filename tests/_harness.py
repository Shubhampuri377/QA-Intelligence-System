"""Shared plumbing for the regression checks.

Client feeds and composed output PDFs are NOT copied into this repo — they are
production data for named customers. The checks read them from wherever they
already live and SKIP with a clear message when they are absent, so the suite
still runs on a machine that has none of them.

Point QA_TEST_DATA_DIR at the folder holding them; it defaults to the user's
Downloads.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATA_DIR = os.environ.get(
    "QA_TEST_DATA_DIR",
    os.path.join(os.path.expanduser("~"), "Downloads"))

_state = {"pass": 0, "fail": 0, "skip": 0}


def check(label, got, want):
    ok = got == want
    _state["pass" if ok else "fail"] += 1
    print(f"  [{'ok  ' if ok else 'FAIL'}] {label}")
    if not ok:
        print(f"          got  = {got!r}")
        print(f"          want = {want!r}")
    return ok


def skip(label, why):
    _state["skip"] += 1
    print(f"  [skip] {label} — {why}")


def totals():
    return dict(_state)


def summary(title="TOTAL"):
    s = _state
    print("=" * 54)
    print(f"{title}: {s['pass']} passed, {s['fail']} failed, {s['skip']} skipped")
    print("=" * 54)
    return s["fail"] == 0


def data_file(name):
    """Absolute path to a client file, or None when it is not on this machine."""
    p = os.path.join(DATA_DIR, name)
    return p if os.path.isfile(p) else None


class Upload:
    """Minimal stand-in for a Streamlit UploadedFile."""

    def __init__(self, path):
        self.name = os.path.basename(path)
        with open(path, "rb") as fh:
            self._b = fh.read()
        self._i = 0

    def read(self, n=-1):
        d = self._b[self._i:] if n < 0 else self._b[self._i:self._i + n]
        self._i += len(d)
        return d

    def seek(self, i, whence=0):
        self._i = i

    def getvalue(self):
        return self._b


def load_feed(name, fmt):
    """(records, note) from a client feed, or (None, None) if absent."""
    from utils.extraction import extract_input_records
    from utils.field_mapping import normalize_records
    p = data_file(name)
    if not p:
        return None, None
    raw, note = extract_input_records(Upload(p), fmt)
    recs, _ = normalize_records(raw)
    return recs, note


def load_pages(name):
    """Page texts from a composed output PDF, or None if absent."""
    import fitz
    p = data_file(name)
    if not p:
        return None
    return [pg.get_text() for pg in fitz.open(p)]
