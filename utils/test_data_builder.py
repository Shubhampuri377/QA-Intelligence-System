"""
Coverage-driven test data generation.

The BRD decides WHAT to vary; the uploaded sample decides the SHAPE. Records are
never built from scratch — a real sample record is cloned and specific paths are
overwritten, so field names, nesting, ordering and format always match the real
feed and nothing can be invented.

Cases are derived from Mapping Spec constructs, so the same code serves any
project:

    absent_if_equal rule  -> equal (suppressed) + differ + differ-on-one-field
    first_present block   -> each candidate present in turn, and none present
    org_switch            -> the ORG branch and the person branch
    format currency/date/phone -> that format's boundary set
    declared max_length   -> at the limit and over it

Independent cases are packed into shared records (they touch different paths), so
a project needs ~20 records rather than one per case.
"""

import copy
import re
from dataclasses import dataclass, field as _f
from typing import Any

from utils.mapping_spec import (NAME_FIELDS, get_path, resolve_block, plan_letters,
                                slots_for_letter)


# ── path helpers ─────────────────────────────────────────────────

def set_path(obj: dict, path: str, value) -> bool:
    """Sets a '/'-separated path, creating nothing. Returns False if the parent
    does not exist — a missing parent means the sample never showed us that
    shape, which the caller must report rather than invent."""
    parts = [p for p in str(path).split("/") if p]
    if not parts:
        return False
    cur = obj
    for p in parts[:-1]:
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        else:
            return False
    if isinstance(cur, dict):
        cur[parts[-1]] = value
        return True
    return False


def display_path(path: str, record_index: int, root: str = "records") -> str:
    """A Notepad++-friendly path: records[2].clientInfo.OWNER.organizationName"""
    return f"{root}[{record_index}]." + ".".join(p for p in str(path).split("/") if p)


# ── case model ───────────────────────────────────────────────────

def _richness(rec) -> int:
    """Counts populated leaves — a proxy for how many branches this record can
    demonstrate the shape of."""
    n = 0
    if isinstance(rec, dict):
        for v in rec.values():
            n += _richness(v)
    elif isinstance(rec, (list, tuple)):
        for v in rec:
            n += _richness(v)
    elif rec is not None and str(rec).strip() != "":
        n = 1
    return n


@dataclass
class Case:
    case_id: str
    brd_ref: str
    describes: str                       # what this case proves, in plain words
    mutations: list = _f(default_factory=list)   # [(path, value)]
    blocked: str = ""                    # why it could not be generated

    @property
    def paths(self):
        return {p for p, _ in self.mutations}

    @property
    def blocks(self):
        """The parent block of every path this case writes. Two cases that touch
        the same block must not share a record even when their exact fields
        differ — e.g. making CUSTODIAN an organisation changes what the letter
        prints, so it must not sit on top of a CUSTODIAN suppression case. Sharing
        a record would still be evaluated correctly, but the row would take a
        reader three rules to explain instead of one."""
        return {"/".join(p.split("/")[:-1]) for p, _ in self.mutations}


# ── value factories ──────────────────────────────────────────────

CURRENCY_CASES = [
    ("0.00", "zero amount"),
    ("0.01", "smallest non-zero"),
    ("999.99", "just below the thousands separator boundary"),
    ("1000.00", "just above the thousands separator boundary"),
    ("-201.00", "negative amount"),
    ("15", "whole number, no decimals supplied"),
    ("123456789.99", "very large amount"),
]
DATE_CASES = [
    ("2026-01-01", "first day of the year"),
    ("2026-12-31", "last day of the year"),
    ("2026-02-29", "leap-year day"),
]
PHONE_CASES = [
    ("4029604993", "plain 10 digits"),
    ("14029604993", "11 digits with leading 1"),
]


def _fmt_of(slot: dict) -> str:
    return ((slot.get("expected") or {}).get("format") or "").lower()


def _max_len(slot: dict):
    exp = slot.get("expected") or {}
    for src in (slot, exp):
        for key in ("max_length", "field_length", "length"):
            v = src.get(key)
            if isinstance(v, int) and v > 0:
                return v
            if isinstance(v, str) and v.strip().isdigit():
                return int(v.strip())
    return None


def _fields_of(slot: dict, spec: dict) -> list:
    exp = slot.get("expected") or {}
    kind = exp.get("kind")
    if kind == "block_name":
        sw = exp.get("org_switch") or (spec.get("defaults") or {}).get("org_switch") or {}
        return sw.get("person_fields") or NAME_FIELDS
    if kind == "fields":
        return exp.get("fields") or []
    return []


# ── case derivation ──────────────────────────────────────────────

def derive_cases(spec: dict, template: dict) -> list:
    """Walks the spec and produces one Case per thing worth testing."""
    cases, n = [], 0

    def nid(prefix):
        nonlocal n
        n += 1
        return f"{prefix}-{n:03d}"

    # 1. Letter-generation / suppression rules.
    for ldef in spec.get("letters") or []:
        pres = ldef.get("presence") or {}
        if pres.get("kind") != "absent_if_equal":
            continue
        fields = pres.get("fields") or NAME_FIELDS
        letter = {"id": ldef.get("id"), "label": ldef.get("label", ""),
                  "addressee": ldef.get("addressee") or {}, "counterparty": ldef.get("counterparty") or {}}
        a_blk, a_path = resolve_block(letter["addressee"], template, letter)
        b_blk, b_path = resolve_block(letter["counterparty"], template, letter)
        ref = f"letter rule · {ldef.get('id')}"
        if not a_path or not b_path:
            cases.append(Case(nid("LTR"), ref, f"{ldef.get('label','letter')} generation rule",
                              blocked="sample does not contain both parties for this rule"))
            continue

        # equal -> the letter must NOT be produced
        muts = [(f"{b_path}/{f}", str((a_blk or {}).get(f, "") or "")) for f in fields]
        cases.append(Case(nid("LTR"), ref,
                          f"{b_path} equals {a_path} on all name parts — "
                          f"'{ldef.get('label','letter')}' must be SUPPRESSED", muts))

        # differ on exactly one field -> the letter MUST be produced
        for fl in fields:
            base = str((a_blk or {}).get(fl, "") or "")
            cases.append(Case(nid("LTR"), ref,
                              f"{b_path} differs from {a_path} on {fl} ONLY — "
                              f"'{ldef.get('label','letter')}' must be GENERATED",
                              [(f"{b_path}/{f}", str((a_blk or {}).get(f, "") or ""))
                               for f in fields if f != fl]
                              + [(f"{b_path}/{fl}", (base + "X") if base else "DIFFERS")]))

    # 2. first_present blocks — exercise each candidate and the none-present path.
    seen_blocks = set()
    for ldef in spec.get("letters") or []:
        for key in ("addressee", "counterparty"):
            bs = ldef.get(key) or {}
            if bs.get("kind") != "first_present":
                continue
            root, cands = bs.get("root", ""), bs.get("candidates") or []
            sig = (root, tuple(cands))
            if sig in seen_blocks:
                continue
            seen_blocks.add(sig)
            for cand in cands:
                p = f"{root}/{cand}" if root else cand
                if not isinstance(get_path(template, p), dict):
                    cases.append(Case(nid("BLK"), f"block selection · {'/'.join(cands)}",
                                      f"{cand} present → it should be used",
                                      blocked=f"sample has no {p} example to copy"))
                    continue
                cases.append(Case(nid("BLK"), f"block selection · {'/'.join(cands)}",
                                  f"{cand} present → {cand} must be used, not the fallback",
                                  [(f"{p}/__present__", True)]))

    # 3. ORG vs person switch.
    for slot in spec.get("slots") or []:
        exp = slot.get("expected") or {}
        if exp.get("kind") != "block_name":
            continue
        sw = exp.get("org_switch") or (spec.get("defaults") or {}).get("org_switch") or {}
        disc = sw.get("discriminator", "clientType/code")
        org_val = sw.get("org_value", "ORG")
        org_fields = sw.get("org_fields") or ["organizationName"]
        ref = slot.get("brd_ref", slot.get("slot_id", ""))
        for ldef in spec.get("letters") or []:
            letter = {"id": ldef.get("id"), "addressee": ldef.get("addressee") or {},
                      "counterparty": ldef.get("counterparty") or {}}
            _, bpath = resolve_block(exp.get("block") or {"kind": "root"}, template, letter)
            if not bpath:
                continue
            cases.append(Case(nid("ORG"), ref,
                              f"{bpath} is an organisation → {', '.join(org_fields)} must print",
                              [(f"{bpath}/{disc}", org_val)]
                              + [(f"{bpath}/{f}", "Acme Holdings Inc") for f in org_fields]))
            break

    # 4. Format boundaries.
    for slot in spec.get("slots") or []:
        fmt = _fmt_of(slot)
        flds = _fields_of(slot, spec)
        if not fmt or fmt == "none" or len(flds) != 1:
            continue
        exp = slot.get("expected") or {}
        letter = {"id": "x", "addressee": {}, "counterparty": {}}
        _, bpath = resolve_block(exp.get("block") or {"kind": "root"}, template, letter)
        path = f"{bpath}/{flds[0]}" if bpath else flds[0]
        table = {"currency": CURRENCY_CASES, "date": DATE_CASES, "phone": PHONE_CASES}.get(fmt, [])
        for val, why in table:
            cases.append(Case(nid("FMT"), slot.get("brd_ref", slot.get("slot_id", "")),
                              f"{slot.get('slot_name','field')} — {why}", [(path, val)]))

    # 5. Declared field lengths.
    for slot in spec.get("slots") or []:
        ml = _max_len(slot)
        flds = _fields_of(slot, spec)
        if not ml or not flds:
            continue
        exp = slot.get("expected") or {}
        letter = {"id": "x", "addressee": {}, "counterparty": {}}
        _, bpath = resolve_block(exp.get("block") or {"kind": "root"}, template, letter)
        path = f"{bpath}/{flds[0]}" if bpath else flds[0]
        ref = slot.get("brd_ref", slot.get("slot_id", ""))
        cases.append(Case(nid("LEN"), ref,
                          f"{slot.get('slot_name','field')} at the declared limit ({ml} chars)",
                          [(path, "L" * ml)]))
        cases.append(Case(nid("LEN"), ref,
                          f"{slot.get('slot_name','field')} OVER the declared limit "
                          f"({ml + 20} chars) — reveals truncation",
                          [(path, "L" * (ml + 20))]))
    return cases


# ── baseline ─────────────────────────────────────────────────────

def _maximise_letters(spec: dict, template: dict):
    """Returns (base, adjustments).

    A cloned record inherits whatever the sample happened to do — and real feeds
    routinely suppress a document. In this project's sample PAYOR carries the same
    name as CUSTODIAN, so the Payor letter is suppressed; every format and length
    case built on that clone would then exercise the control letter only, and any
    field that prints solely on the Payor letter would never appear in the output
    at all. So where a suppression rule fires on the sample, nudge the
    counterparty just enough that it does not. Cases that deliberately test
    suppression overwrite these fields with equal values, so nothing is lost.
    """
    base = copy.deepcopy(template)
    adjustments = []
    for ldef in spec.get("letters") or []:
        pres = ldef.get("presence") or {}
        if pres.get("kind") != "absent_if_equal":
            continue
        lid = ldef.get("id")
        planned = {l.get("id"): l for l in plan_letters(spec, base)}
        if not (planned.get(lid) or {}).get("skipped"):
            continue
        letter = {"id": lid, "label": ldef.get("label", ""),
                  "addressee": ldef.get("addressee") or {},
                  "counterparty": ldef.get("counterparty") or {}}
        # Change the suppressed letter's OWN addressee where possible, so the
        # marker value lands on the document being unlocked rather than leaking
        # into a letter that was already correct.
        targets = [resolve_block(letter["addressee"], base, letter),
                   resolve_block(letter["counterparty"], base, letter)]
        done = False
        for b_blk, b_path in targets:
            if done or not b_path:
                continue
            for f in pres.get("fields") or NAME_FIELDS:
                cur = str((b_blk or {}).get(f, "") or "")
                if not cur:
                    continue
                path, new = f"{b_path}/{f}", cur + "-ALT"
                if not set_path(base, path, new):
                    continue
                if (({l.get("id"): l for l in plan_letters(spec, base)}.get(lid) or {})
                        .get("skipped")):
                    set_path(base, path, cur)      # did not help — put it back
                    continue
                adjustments.append({
                    "path": path, "value": new,
                    "brd_ref": f"letter rule · {lid}",
                    "describes": f"Baseline — the sample suppressed '{ldef.get('label', lid)}' "
                                 f"because the two parties matched. {f} was changed to "
                                 f"'{new}' so the letter is produced and its fields can be "
                                 f"checked. Records that test suppression override this.",
                })
                done = True
                break
    return base, adjustments


# ── packing + build ──────────────────────────────────────────────

def build_records(spec: dict, sample_records: list, max_records: int = 60):
    """Returns (records, rows, blocked). `rows` links every written value back to
    its BRD reference and case, ready for the location report."""
    if not sample_records:
        raise ValueError("A sample data file is required — it supplies the record shape.")
    # Use the RICHEST sample record as the template, not simply the first. A
    # branch can only be generated if the sample shows its shape, so the record
    # containing the most populated fields unlocks the most cases — picking
    # record[0] blindly blocks any rule whose block happens to be absent there.
    template = max(sample_records, key=_richness)
    base, adjustments = _maximise_letters(spec, template)

    # Derive from BASE, not the raw template: an equality case copies one party's
    # values onto the other, and those values must be the ones the record will
    # actually hold — otherwise a baseline nudge silently defeats the very
    # suppression the case exists to test.
    cases = derive_cases(spec, base)
    blocked = [c for c in cases if c.blocked]
    usable = [c for c in cases if not c.blocked and c.mutations]

    # Pack cases into shared records, but only where they touch unrelated blocks,
    # so each record stays explainable by the cases listed against it.
    def _clash(a_blocks, b_blocks):
        for x in a_blocks:
            for y in b_blocks:
                if x == y or x.startswith(y + "/") or y.startswith(x + "/"):
                    return True
        return False

    buckets = []
    for c in usable:
        placed = False
        for b in buckets:
            if not (b["paths"] & c.paths) and not _clash(b["blocks"], c.blocks):
                b["cases"].append(c)
                b["paths"] |= c.paths
                b["blocks"] |= c.blocks
                placed = True
                break
        if placed:
            continue
        if len(buckets) >= max_records:
            blocked.append(Case(c.case_id, c.brd_ref, c.describes,
                                blocked=f"record cap of {max_records} reached"))
            continue
        buckets.append({"cases": [c], "paths": set(c.paths), "blocks": set(c.blocks)})

    records, rows = [], []
    for i, b in enumerate(buckets):
        rec = copy.deepcopy(base)
        # Document each baseline adjustment on the records where no case explains
        # that block — otherwise the reader finds a value in the file with nothing
        # in the map to account for it.
        owned_refs = {c.brd_ref for c in b["cases"]}
        for adj in adjustments:
            parent = "/".join(adj["path"].split("/")[:-1])
            if adj["brd_ref"] not in owned_refs and not _clash({parent}, b["blocks"]):
                rows.append({"record_index": i, "path": adj["path"], "value": adj["value"],
                             "case_id": "BASE", "brd_ref": adj["brd_ref"],
                             "describes": adj["describes"]})
        for c in b["cases"]:
            for path, val in c.mutations:
                if path.endswith("/__present__"):
                    continue                       # marker only; block already exists
                if set_path(rec, path, val):
                    rows.append({"record_index": i, "path": path, "value": val,
                                 "case_id": c.case_id, "brd_ref": c.brd_ref,
                                 "describes": c.describes})
                else:
                    blocked.append(Case(c.case_id, c.brd_ref, c.describes,
                                        blocked=f"path '{path}' not present in the sample"))
        records.append(rec)

    return records, rows, blocked


def expected_letters(spec: dict, records: list) -> list:
    """What each generated record should produce, so the fixture is self-checking."""
    out = []
    for i, rec in enumerate(records):
        planned = plan_letters(spec, rec)
        out.append({"record_index": i,
                    "letters": [l for l in planned if not l.get("skipped")],
                    "suppressed": [l for l in planned if l.get("skipped")],
                    "slot_count": len(slots_for_letter(spec, (planned[0]["id"] if planned else "")))})
    return out
