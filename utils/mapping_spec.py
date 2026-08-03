"""
Mapping Spec — the BRD's field table expressed as machine-evaluable slots.

A "slot" is a named position in the generated document (Addressee Name, Amount,
cc: line, Certificate #...). Each slot knows, from the BRD, how to COMPUTE the
value it should contain for a given source record. That expected value is what
makes real validation possible: comparing expected-vs-actual can express
"rendered but wrong" and "truncated", which a "does this value appear anywhere"
check never can.

Everything in this module is deterministic. The BRD is read once by an LLM into
this structure (see prompts/mapping_spec_prompt.py); evaluating it against a
record is plain Python, so the conditional business rules — CUSTODIAN-else-OWNER,
ORG-vs-person, and the name-equality tests behind the cc: line and the Payor
letter — are verified at zero AI cost and with no chance of drift.

Block references are relative to the letter being validated:
    addressee     — whoever this letter is addressed to
    counterparty  — the other party (used by the cc: line)
This is what lets one slot definition serve both the control letter and the
Payor letter, which is exactly how the BRD's two near-identical tables relate.
"""

import re
from datetime import datetime

ABSENT = "\x00ABSENT"          # sentinel: this slot must render nothing

NAME_FIELDS = ["firstName", "middleName", "lastName", "nameSuffix"]
_DATE_IN = ["%Y-%m-%d", "%m-%d-%Y", "%m/%d/%Y", "%Y/%m/%d", "%d-%m-%Y", "%Y%m%d"]


# ── path access ──────────────────────────────────────────────────

def get_path(obj, path: str):
    """Fetches a '/'-separated path out of nested dicts. Returns None if absent."""
    if not path:
        return obj
    cur = obj
    for part in str(path).split("/"):
        if part == "":
            continue
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _nonblank(v) -> bool:
    return v is not None and str(v).strip() != ""


# ── block resolution ─────────────────────────────────────────────

def resolve_block(spec: dict, record: dict, letter: dict):
    """Returns (block_dict, human_path). A block is a group of related fields —
    a clientInfo role, producerInfo, or the record root."""
    if not isinstance(spec, dict):
        return None, ""
    kind = spec.get("kind")

    if kind == "addressee":
        return resolve_block(letter.get("addressee") or {}, record, letter)
    if kind == "counterparty":
        return resolve_block(letter.get("counterparty") or {}, record, letter)
    if kind == "root":
        return record, ""
    if kind == "fixed":
        p = spec.get("path", "")
        blk = get_path(record, p)
        return (blk if isinstance(blk, dict) else None), p
    if kind == "first_present":
        root = spec.get("root", "")
        for cand in spec.get("candidates", []) or []:
            p = f"{root}/{cand}" if root else cand
            blk = get_path(record, p)
            if isinstance(blk, dict) and any(_nonblank(v) for v in blk.values()):
                return blk, p
        return None, (f"{root}/" + "|".join(spec.get("candidates", []) or [])) if root else ""
    return None, ""


# ── formatting ───────────────────────────────────────────────────

def fmt_phone(v) -> str:
    d = re.sub(r"\D", "", str(v or ""))
    if len(d) == 11 and d.startswith("1"):
        d = d[1:]
    return f"{d[:3]}-{d[3:6]}-{d[6:]}" if len(d) == 10 else str(v or "").strip()


def fmt_date(v) -> str:
    s = str(v or "").strip()
    for f in _DATE_IN:
        try:
            return datetime.strptime(s, f).strftime("%m-%d-%Y")
        except ValueError:
            continue
    return s


def fmt_currency(v) -> str:
    s = re.sub(r"[^\d.\-]", "", str(v or ""))
    try:
        n = float(s)
    except ValueError:
        return str(v or "").strip()
    return f"${n:,.2f}"


def apply_format(value: str, fmt: str) -> str:
    return {"phone": fmt_phone, "date": fmt_date, "currency": fmt_currency}.get(
        (fmt or "none").lower(), lambda x: str(x or "").strip())(value)


# ── value builders ───────────────────────────────────────────────

def join_fields(block: dict, fields: list, sep: str = " ") -> str:
    """Joins field values with exactly one separator, skipping blanks — the
    BRD's 'only 1 space between each part of the name' rule."""
    if not isinstance(block, dict):
        return ""
    vals = [str(block.get(f, "") or "").strip() for f in (fields or [])]
    return sep.join(v for v in vals if v)


def block_name(block: dict, org_switch: dict | None) -> str:
    """A party's printable name, honouring the ORG-vs-person decision."""
    if not isinstance(block, dict):
        return ""
    sw = org_switch or {}
    disc = sw.get("discriminator", "clientType/code")
    org_value = str(sw.get("org_value", "ORG")).upper()
    org_fields = sw.get("org_fields") or ["organizationName"]
    person_fields = sw.get("person_fields") or NAME_FIELDS
    code = str(get_path(block, disc) or "").upper()
    if code == org_value:
        return join_fields(block, org_fields)
    return join_fields(block, person_fields)


def block_address(block: dict, spec: dict | None) -> str:
    """Address lines plus the 'CITY, ST ZIP' line, blanks dropped."""
    if not isinstance(block, dict):
        return ""
    s = spec or {}
    lines = [str(block.get(f, "") or "").strip()
             for f in (s.get("lines") or ["addressLine1", "addressLine2", "addressLine3", "addressLine4"])]
    city = str(get_path(block, s.get("city", "addressCity")) or "").strip()
    state = str(get_path(block, s.get("state", "addressState/code")) or "").strip()
    zipc = str(get_path(block, s.get("zip", "addressZip")) or "").strip()
    tail = ", ".join(p for p in [city, " ".join(x for x in [state, zipc] if x)] if p)
    parts = [l for l in lines if l] + ([tail] if tail else [])
    return ", ".join(parts)


# ── presence + expected value ────────────────────────────────────

def _blocks_equal(a: dict, b: dict, fields: list) -> bool:
    if not isinstance(a, dict) or not isinstance(b, dict):
        return False
    norm = lambda blk: [str(blk.get(f, "") or "").strip().casefold() for f in fields]
    return norm(a) == norm(b)


def slot_is_present(slot: dict, record: dict, letter: dict) -> tuple:
    """Returns (present: bool, why: str) for a slot on this letter."""
    pres = slot.get("presence") or {"kind": "always"}
    kind = pres.get("kind", "always")
    if kind == "always":
        return True, ""
    if kind == "absent_if_equal":
        fields = pres.get("fields") or NAME_FIELDS
        a, pa = resolve_block(pres.get("left") or {"kind": "addressee"}, record, letter)
        b, pb = resolve_block(pres.get("right") or {"kind": "counterparty"}, record, letter)
        if _blocks_equal(a, b, fields):
            return False, f"{pa or 'addressee'} equals {pb or 'counterparty'} on {', '.join(fields)}"
        return True, f"{pa or 'addressee'} differs from {pb or 'counterparty'}"
    return True, ""


def eval_expected(slot: dict, record: dict, letter: dict) -> tuple:
    """Returns (expected_value_or_ABSENT, explanation)."""
    present, why = slot_is_present(slot, record, letter)
    if not present:
        return ABSENT, f"Suppressed — {why}"

    exp = slot.get("expected") or {}
    kind = exp.get("kind", "fields")
    prefix = str(exp.get("prefix", "") or "")

    if kind == "constant":
        return prefix + str(exp.get("value", "") or ""), "Static template text"

    block, bpath = resolve_block(exp.get("block") or {"kind": "root"}, record, letter)

    if kind == "block_name":
        val = block_name(block, exp.get("org_switch"))
        return (prefix + val if val else ""), f"Name from {bpath or 'record'}"
    if kind == "block_address":
        val = block_address(block, exp.get("address"))
        return (prefix + val if val else ""), f"Address from {bpath or 'record'}"

    # kind == "fields"
    fields = exp.get("fields") or []
    if len(fields) == 1:
        raw = get_path(block, fields[0])
        raw = "" if raw is None else str(raw)
    else:
        raw = join_fields(block, fields, exp.get("join", " "))
    val = apply_format(raw, exp.get("format"))
    src = "/".join(x for x in [bpath, ", ".join(fields)] if x)
    return (prefix + val if val else ""), f"From {src}"


# ── letter planning ──────────────────────────────────────────────

def plan_letters(spec: dict, record: dict) -> list:
    """Which letters this record should produce, per the BRD's generation rules.

    This is itself a validated business rule: the count and identity of letters
    is derived here and reconciled against the output document."""
    out = []
    for ldef in spec.get("letters") or []:
        letter = {
            "id": ldef.get("id", "letter"),
            "label": ldef.get("label", ldef.get("id", "letter")),
            "addressee": ldef.get("addressee") or {"kind": "root"},
            "counterparty": ldef.get("counterparty") or {"kind": "root"},
        }
        pres = ldef.get("presence") or {"kind": "always"}
        if pres.get("kind") == "absent_if_equal":
            fields = pres.get("fields") or NAME_FIELDS
            a, pa = resolve_block(letter["addressee"], record, letter)
            b, pb = resolve_block(letter["counterparty"], record, letter)
            if _blocks_equal(a, b, fields):
                letter["skipped"] = True
                letter["skip_reason"] = (f"{pa or 'addressee'} equals {pb or 'counterparty'} "
                                         f"on {', '.join(fields)}")
                out.append(letter)
                continue
        letter["skipped"] = False
        blk, bp = resolve_block(letter["addressee"], record, letter)
        letter["addressee_name"] = block_name(blk, (spec.get("defaults") or {}).get("org_switch"))
        letter["addressee_path"] = bp
        out.append(letter)
    return out


def slot_checks(slot: dict, record: dict, letter: dict, spec: dict) -> list:
    """Expands one slot into the checks it should report.

    A composite slot (a name, an address) is reported BOTH per component field
    and as the assembled value:

      Addressee Address · addressLine2   expected "Shubham puri"        <- which field
      Addressee Address (assembled)      expected "3120 N 90th St, ..." <- ordering/truncation

    The per-field rows are what make a defect diagnosable at a glance; the
    assembled row is what catches truncation and wrong ordering. Reporting only
    the assembled value hides which field is at fault, which is a regression on
    a plain field-by-field list.

    Returns [{label, expected, why, kind}], kind in {"component","assembled","single"}.
    """
    expected, why = eval_expected(slot, record, letter)
    name = slot.get("slot_name", slot.get("slot_id", "?"))
    if expected == ABSENT or not slot.get("expand", True):
        return [{"label": name, "expected": expected, "why": why, "kind": "single"}]

    exp = slot.get("expected") or {}
    kind = exp.get("kind", "fields")
    block, bpath = resolve_block(exp.get("block") or {"kind": "root"}, record, letter)
    comps = []

    if kind == "block_name":
        sw = exp.get("org_switch") or (spec.get("defaults") or {}).get("org_switch") or {}
        disc = sw.get("discriminator", "clientType/code")
        is_org = str(get_path(block, disc) or "").upper() == str(sw.get("org_value", "ORG")).upper()
        fields = (sw.get("org_fields") or ["organizationName"]) if is_org \
            else (sw.get("person_fields") or NAME_FIELDS)
    elif kind == "block_address":
        a = exp.get("address") or {}
        fields = list(a.get("lines") or ["addressLine1", "addressLine2", "addressLine3", "addressLine4"]) \
            + [a.get("city", "addressCity"), a.get("state", "addressState/code"), a.get("zip", "addressZip")]
    elif kind == "fields" and len(exp.get("fields") or []) > 1:
        fields = list(exp.get("fields") or [])
    else:
        return [{"label": name, "expected": expected, "why": why, "kind": "single"}]

    for f in fields:
        raw = get_path(block, f)
        raw = "" if raw is None else str(raw).strip()
        if raw == "":
            continue                      # nothing to check for an empty component
        comps.append({"label": f"{name} · {f.replace(chr(47), '.')}", "expected": raw,
                      "why": f"From {bpath}/{f}".replace("//", "/"), "kind": "component"})

    if not comps:
        return [{"label": name, "expected": expected, "why": why, "kind": "single"}]
    comps.append({"label": f"{name} (assembled)", "expected": expected,
                  "why": why + " — full value, checks ordering and truncation",
                  "kind": "assembled"})
    return comps


def slots_for_letter(spec: dict, letter_id: str) -> list:
    """Slots applicable to one letter — a slot with no `letters` key applies to all."""
    out = []
    for s in spec.get("slots") or []:
        ids = s.get("letters")
        if not ids or letter_id in ids:
            out.append(s)
    return out


def spec_summary(spec: dict) -> dict:
    slots = spec.get("slots") or []
    return {
        "letters": len(spec.get("letters") or []),
        "slots": len(slots),
        "verifiable": sum(1 for s in slots if s.get("verifiable", True)),
        "not_verifiable": [s for s in slots if not s.get("verifiable", True)],
    }
