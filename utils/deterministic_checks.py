"""
Deterministic (non-AI) validation checks.

A meaningful slice of what the Validation Agent checks — field presence,
known formatting patterns, and simple arithmetic — is exact and mechanical.
Routing it through an LLM is slower, burns tokens, and is actually LESS
reliable for arithmetic than plain code. Every function here resolves what
it can resolve with real confidence and returns None for anything it can't
be sure about, so the caller falls back to the AI Validation Agent instead
of a check silently guessing.
"""

import ast
import operator
import re

_FORMAT_PATTERNS = {
    "date": re.compile(r"^\d{4}-\d{2}-\d{2}$|^\d{2}/\d{2}/\d{4}$|^\d{2}-\d{2}-\d{4}$"),
    "email": re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$"),
    "phone": re.compile(r"^\+?[\d\s().-]{7,15}$"),
    "numeric": re.compile(r"^-?\d+(\.\d+)?$"),
    "currency": re.compile(r"^-?[$₹€£]?\s?\d{1,3}(,\d{3})*(\.\d{1,2})?$"),
    "alphanumeric": re.compile(r"^[A-Za-z0-9]+$"),
}


def _find_field_value(field_name, chunks_a, chunks_b):
    """Looks for `field_name` as a JSON-style key (Data records are rendered
    as JSON text) or as a "Field: value" line (Output text). Returns the
    matched value as a string, or None if not confidently found."""
    field_name = (field_name or "").strip()
    if not field_name:
        return None
    key_pattern = re.compile(r'"' + re.escape(field_name) + r'"\s*:\s*"?([^",\n}]+)"?', re.IGNORECASE)
    line_pattern = re.compile(re.escape(field_name) + r"\s*[:\-]\s*([^\n]+)", re.IGNORECASE)
    for chunks in (chunks_a, chunks_b):
        for chunk in chunks:
            m = key_pattern.search(chunk.text) or line_pattern.search(chunk.text)
            if m:
                return m.group(1).strip().strip('"')[:160]
    return None


def _mentioned(field_name, *chunk_lists):
    field_lc = (field_name or "").strip().lower()
    if not field_lc:
        return False
    return any(field_lc in c.text.lower() for chunks in chunk_lists for c in chunks)


def _to_number(s):
    if s is None:
        return None
    cleaned = re.sub(r"[^\d.\-]", "", str(s))
    try:
        return float(cleaned)
    except ValueError:
        return None


# ── Field Presence ───────────────────────────────────────────────

def check_field_presence(req, data_chunks, output_chunks):
    fields = req.input_fields + req.output_fields
    if not fields:
        return None
    found, missing = {}, []
    for f in fields:
        val = _find_field_value(f, data_chunks, output_chunks)
        if val:
            found[f] = val
        elif _mentioned(f, data_chunks, output_chunks):
            found[f] = "(present — value not cleanly parsed)"
        else:
            missing.append(f)
    if len(missing) == len(fields):
        return None  # nothing matched at all — likely a retrieval miss, not a real absence; let the AI look
    status = "Pass" if not missing else "Fail"
    reason = "All required fields are present." if not missing else f"Missing field(s): {', '.join(missing)}."
    return {
        "Status": status, "Confidence": 100 if not missing else 90,
        "Reason": f"Deterministic field-presence check. {reason}",
        "Evidence": {"Input Record": ", ".join(f"{k}={v}" for k, v in found.items()) or "none found"},
    }


# ── Format ───────────────────────────────────────────────────────

def check_format(req, data_chunks, output_chunks):
    fmt = (req.expected_format or "").strip()
    fields = req.input_fields + req.output_fields
    if not fmt or not fields:
        return None

    if fmt.lower().startswith("regex:"):
        try:
            pattern = re.compile(fmt.split(":", 1)[1])
        except re.error:
            return None
    else:
        pattern = _FORMAT_PATTERNS.get(fmt.lower())
        if pattern is None:
            return None  # unknown format vocabulary — let the AI interpret it

    for f in fields:
        val = _find_field_value(f, data_chunks, output_chunks)
        if val is None:
            continue
        ok = bool(pattern.match(val.strip()))
        return {
            "Status": "Pass" if ok else "Fail", "Confidence": 100,
            "Reason": f'Deterministic format check on "{f}" against pattern "{fmt}". Value found: "{val}".',
            "Evidence": {"Input Record": f"{f} = {val}"},
        }
    return None  # no field value confidently found — defer to AI


# ── Calculation (safe arithmetic evaluator) ─────────────────────

_ALLOWED_BINOPS = {ast.Add: operator.add, ast.Sub: operator.sub,
                   ast.Mult: operator.mul, ast.Div: operator.truediv}
_ALLOWED_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _safe_eval(node, variables):
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body, variables)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.Name):
        if node.id not in variables:
            raise ValueError(f"unresolved variable '{node.id}'")
        return variables[node.id]
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
        return _ALLOWED_BINOPS[type(node.op)](_safe_eval(node.left, variables), _safe_eval(node.right, variables))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARY:
        return _ALLOWED_UNARY[type(node.op)](_safe_eval(node.operand, variables))
    raise ValueError("disallowed expression")


def check_calculation(req, data_chunks, output_chunks):
    """Evaluates a simple `left_field = arithmetic expression` formula the
    BRD Agent extracted, e.g. "Total = UnitPrice * Quantity". Every named
    field must resolve to a real number from the retrieved evidence, or
    this defers to the AI rather than guessing at a match."""
    formula = (req.calculation_formula or "").strip()
    if not formula or "=" not in formula:
        return None
    left_name, expr = formula.split("=", 1)
    left_name, expr = left_name.strip(), expr.strip()
    if not left_name or not expr:
        return None

    field_names = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", expr))
    variables = {}
    for name in field_names:
        num = _to_number(_find_field_value(name, data_chunks, output_chunks))
        if num is None:
            return None  # can't resolve every variable confidently — defer to AI
        variables[name] = num

    try:
        computed = _safe_eval(ast.parse(expr, mode="eval"), variables)
    except Exception:
        return None

    actual_raw = _find_field_value(left_name, data_chunks, output_chunks)
    actual = _to_number(actual_raw)
    if actual is None:
        return None

    ok = abs(actual - computed) < 0.01
    return {
        "Status": "Pass" if ok else "Fail", "Confidence": 100,
        "Reason": (f"Deterministic calculation check: {formula}. Computed {computed:.2f}, "
                   f"found {left_name} = {actual:.2f} in evidence."),
        "Evidence": {"Input Record": ", ".join(f"{k}={v:g}" for k, v in variables.items()),
                     "Output Value": f"{left_name} = {actual_raw}",
                     "Calculation": f"{expr} = {computed:.2f}"},
    }


_CHECKERS = {
    "Field Presence": check_field_presence,
    "Format": check_format,
    "Calculation": check_calculation,
}


def try_deterministic(req, data_chunks, output_chunks):
    """Attempts a deterministic resolution for one requirement. Returns a
    result dict (Status/Confidence/Reason/Evidence) or None if this
    requirement genuinely needs AI reasoning (Business Rule, Conditional
    Logic, Mapping, or a mechanical check whose fields couldn't be
    confidently resolved from the retrieved evidence)."""
    checker = _CHECKERS.get(req.validation_type)
    if not checker:
        return None
    try:
        return checker(req, data_chunks, output_chunks)
    except Exception:
        return None
