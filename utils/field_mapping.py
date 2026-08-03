"""
Structural layer for Field Mapping Validation.

Two jobs, both deterministic (no LLM):

  1. flatten_record()  — turn one parsed source record (XML/JSON/CSV row) into
     a flat list of (field_path, value) pairs. Every leaf in the record IS a
     mapped field, so the field list is grounded in the real feed rather than
     guessed from a spec — nothing to hallucinate and nothing missed.

  2. pair_instances()  — decide which Output page(s) each source record
     produced. A feed with two invoice records generates two documents; every
     field must be compared against ITS OWN document, not the whole output.
     Pairing is done by locating each record's distinctive identifier values
     (account number, invoice number, scan line) in the page text.
"""

import re
from dataclasses import dataclass, field as _dc_field
from typing import List, Tuple, Any

# Field names that usually carry a record's identity — weighted up when
# choosing the anchors used to locate a record's page(s) in the output.
_ID_HINT = re.compile(r"(number|num|no$|id$|acct|account|invoice|scan|policy|member|customer)", re.I)

MAX_FIELDS_PER_RECORD = 400


def norm(s: Any) -> str:
    """Alphanumeric-only lowercase form, for tolerant containment checks."""
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


# The extractors report a failed parse by returning a single string record
# containing one of these markers. Left unchecked it would be flattened into a
# field and "validated", producing a clean-looking report built on an error
# message — so it is caught here and raised instead.
_PARSE_ERROR = re.compile(
    r"\[(JSON|XML|TABULAR|IMAGE OCR|PDF READ) (PARSE )?ERROR\]", re.I)


def normalize_records(records: list) -> tuple:
    """Coerces whatever an extractor returned into a list of dict records.

    Returns (records, unstructured_count). Raises ValueError when the feed did
    not parse at all — a validation run on an error string is worse than no run.

    `unstructured_count` is the number of records that carried no field
    structure (a Print Image page, a fixed-length line with no layout supplied).
    Field mapping cannot be performed on those, so the caller must surface the
    count rather than emit one meaningless field per record."""
    if not records:
        raise ValueError("The source feed produced no records.")

    for r in records:
        if isinstance(r, str) and _PARSE_ERROR.search(r):
            raise ValueError(f"The source feed could not be parsed — {r.strip()}")

    out, unstructured = [], 0
    for r in records:
        if isinstance(r, dict):
            out.append(r)
        elif isinstance(r, (list, tuple)):
            out.append({"item": list(r)})
        else:
            unstructured += 1
            out.append({"_unstructured_text": str(r)})
    return out, unstructured


# ── 1. Flattening ────────────────────────────────────────────────

def _walk(node: Any, prefix: str, out: list, cap: int) -> None:
    if len(out) >= cap:
        return
    if isinstance(node, dict):
        for k, v in node.items():
            key = str(k)
            path = f"{prefix}/{key}" if prefix else key
            _walk(v, path, out, cap)
    elif isinstance(node, (list, tuple)):
        for i, item in enumerate(node, start=1):
            _walk(item, f"{prefix}[{i}]" if prefix else f"[{i}]", out, cap)
    else:
        out.append((prefix or "value", "" if node is None else str(node).strip()))


def flatten_record(rec: Any, cap: int = MAX_FIELDS_PER_RECORD) -> Tuple[List[Tuple[str, str]], bool]:
    """Returns (pairs, truncated). `truncated` is True when the record had more
    leaves than `cap` — surfaced in the report rather than silently dropped."""
    out: list = []
    _walk(rec, "", out, cap)
    return out, len(out) >= cap


def display_names(paths: List[str]) -> dict:
    """Maps each full path to the shortest readable label that stays unique
    within the record — 'Account_Number' rather than the whole path, but
    'LineCluster[2]/Amount' when a bare leaf name would be ambiguous."""
    leaves = [p.split("/")[-1] for p in paths]
    counts: dict = {}
    for lf in leaves:
        counts[lf] = counts.get(lf, 0) + 1
    names = {}
    for p, lf in zip(paths, leaves):
        if counts[lf] == 1:
            names[p] = lf
        else:
            names[p] = "/".join(p.split("/")[-2:])
    return names


# ── 2. Instance pairing ──────────────────────────────────────────

def record_anchors(pairs: List[Tuple[str, str]], limit: int = 12) -> List[str]:
    """Picks the most distinctive values in a record — the ones most likely to
    appear verbatim in the document the record produced."""
    scored = []
    seen = set()
    for path, val in pairs:
        v = (val or "").strip()
        if len(v) < 4 or len(v) > 80:
            continue
        n = norm(v)
        if len(n) < 4 or n in seen:
            continue
        seen.add(n)
        score = min(len(n), 24) / 24.0
        if _ID_HINT.search(path.split("/")[-1]):
            score += 3.0
        if any(c.isdigit() for c in v):
            score += 2.0
        scored.append((score, v))
    scored.sort(key=lambda t: -t[0])
    return [v for _, v in scored[:limit]]


@dataclass
class Instance:
    """One source record paired with the output page(s) it produced."""
    index: int
    record: Any
    pairs: List[Tuple[str, str]] = _dc_field(default_factory=list)
    page_indexes: List[int] = _dc_field(default_factory=list)
    truncated: bool = False
    output_text: str = ""
    label: str = ""

    @property
    def found_in_output(self) -> bool:
        return bool(self.page_indexes)

    @property
    def page_label(self) -> str:
        if not self.page_indexes:
            return "not located in output"
        nums = [i + 1 for i in sorted(self.page_indexes)]
        if len(nums) == 1:
            return f"Output page {nums[0]}"
        if nums == list(range(nums[0], nums[-1] + 1)):
            return f"Output pages {nums[0]}–{nums[-1]}"
        return "Output pages " + ", ".join(str(n) for n in nums)


def _instance_label(pairs: List[Tuple[str, str]], idx: int) -> str:
    """A human-readable title for the instance, built from whichever identity
    fields the record actually has."""
    want = [("invoice", "Invoice"), ("account", "Account"), ("name", None),
            ("policy", "Policy"), ("member", "Member")]
    bits = []
    for key, prefix in want:
        for path, val in pairs:
            leaf = path.split("/")[-1].lower()
            if key in leaf and val and len(str(val)) < 60:
                bits.append(f"{prefix} {val}" if prefix else str(val))
                break
        if len(bits) >= 3:
            break
    head = " · ".join(dict.fromkeys(bits))
    return f"Record {idx + 1}" + (f" — {head}" if head else "")


def pair_instances(records: list, pages: List[str], cap: int = MAX_FIELDS_PER_RECORD) -> List[Instance]:
    """Assigns every output page to exactly one record, so a record spanning
    several pages keeps them all and no page gets double-counted.

    Unmatched pages carry forward to the last matched record — that is how
    continuation pages behave in a print stream (page 2 of an invoice often
    repeats none of the identifiers that page 1 carries)."""
    instances: List[Instance] = []
    for i, rec in enumerate(records):
        pairs, trunc = flatten_record(rec, cap)
        instances.append(Instance(index=i, record=rec, pairs=pairs, truncated=trunc,
                                   label=_instance_label(pairs, i)))

    if not pages:
        return instances

    if len(instances) == 1:
        instances[0].page_indexes = list(range(len(pages)))
        instances[0].output_text = "\n".join(pages)
        return instances

    anchors = [record_anchors(inst.pairs) for inst in instances]
    norm_pages = [norm(p) for p in pages]

    # Page-centric: each page goes to whichever record its text best supports.
    owner_of_page: List[int] = []
    for np in norm_pages:
        best, best_score = -1, 0
        for ri, anc in enumerate(anchors):
            score = sum(1 for a in anc if len(norm(a)) >= 4 and norm(a) in np)
            if score > best_score:
                best, best_score = ri, score
        owner_of_page.append(best)

    # Continuation pages inherit the previous page's owner.
    last = -1
    for pi, owner in enumerate(owner_of_page):
        if owner == -1:
            owner_of_page[pi] = last
        else:
            last = owner

    for pi, owner in enumerate(owner_of_page):
        if owner >= 0:
            instances[owner].page_indexes.append(pi)

    for inst in instances:
        inst.output_text = "\n".join(pages[i] for i in sorted(inst.page_indexes))
    return instances
