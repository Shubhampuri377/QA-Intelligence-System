"""Robust JSON extraction from raw LLM text output, with truncation recovery."""

import json


def safe_json_object(text, debug):
    """Parses a single JSON OBJECT out of raw LLM text.

    `safe_json` below is array-oriented — handed a top-level object it returns
    the first non-empty list it finds inside, which is wrong when the object
    itself is the payload (e.g. a summary with narrative + recommendations).
    Returns {} when nothing usable is found."""
    if not text:
        debug.add("err", "JSON-PARSE", "Input text is empty — nothing to parse")
        return {}

    t = text.strip()
    if t.startswith("```"):
        lines = t.split("\n")
        end = len(lines)
        for i in range(len(lines) - 1, 0, -1):
            if lines[i].strip().startswith("```"):
                end = i
                break
        t = "\n".join(lines[1:end]).strip()

    for candidate in (t, t[t.find("{"): t.rfind("}") + 1] if "{" in t and "}" in t else ""):
        if not candidate:
            continue
        try:
            result = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(result, dict):
            debug.add("ok", "JSON-PARSE", f"Parsed object with {len(result)} key(s)")
            return result
        if isinstance(result, list) and result and isinstance(result[0], dict):
            debug.add("ok", "JSON-PARSE", "Parsed object from single-element array")
            return result[0]

    # Truncation recovery — the model hit its output ceiling mid-object. Closing
    # the open braces salvages the elements that DID complete. The caller is told
    # via `_truncated` so it can warn: a partial spec silently accepted would
    # mean silently validating fewer fields than the BRD requires.
    repaired = _close_open_brackets(t)
    if repaired:
        try:
            result = json.loads(repaired)
        except json.JSONDecodeError:
            result = None
        if isinstance(result, dict) and result:
            result["_truncated"] = True
            debug.add("warn", "JSON-TRUNCATION",
                      f"Response was cut off — recovered {len(result) - 1} key(s) by closing the "
                      f"open structure. Content after the cut is MISSING.",
                      "Raise the model's output limit or split the request.")
            return result

    debug.add("err", "JSON-PARSE", "Could not parse a JSON object", f"Raw (first 400): {text[:400]}")
    return {}


def _close_open_brackets(t: str):
    """Repairs a truncated JSON document.

    Cutting at the single last complete value is not enough: a cut landing
    mid-key leaves `{"slot_id": "S-12", "slot_name"` — a key with no value, which
    cannot be closed into anything valid. So every `}`/`]` position is treated as
    a candidate cut point and tried from the end backwards, keeping the first one
    that actually parses. That drops the incomplete trailing element and retains
    everything before it.

    Returns the repaired JSON string, or None when nothing usable remains.
    """
    cuts, in_str, esc = [], False, False
    for i, ch in enumerate(t):
        if esc:
            esc = False
            continue
        if in_str:
            if ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "}]":
            cuts.append(i)
    if not cuts:
        return None

    for idx in reversed(cuts[-500:]):
        head = t[:idx + 1]
        stack, s_in, s_esc = [], False, False
        for ch in head:
            if s_esc:
                s_esc = False
                continue
            if s_in:
                if ch == "\\":
                    s_esc = True
                elif ch == '"':
                    s_in = False
                continue
            if ch == '"':
                s_in = True
            elif ch in "{[":
                stack.append("}" if ch == "{" else "]")
            elif ch in "}]" and stack:
                stack.pop()
        candidate = head + "".join(reversed(stack))
        try:
            if isinstance(json.loads(candidate), dict):
                return candidate
        except json.JSONDecodeError:
            continue
    return None


def safe_json(text, debug):
    """Parses a JSON array out of raw LLM text. Handles markdown fences, wrapped
    dicts, and truncated output (recovers all complete top-level objects)."""
    if not text:
        debug.add("err", "JSON-PARSE", "Input text is empty — nothing to parse")
        return []

    original = text
    text = text.strip()

    # Strip markdown fences
    if text.startswith("```"):
        lines = text.split("\n")
        end = len(lines)
        for i in range(len(lines) - 1, 0, -1):
            if lines[i].strip().startswith("```"):
                end = i
                break
        text = "\n".join(lines[1:end]).strip()
        debug.add("info", "JSON-STRIP", f"Stripped markdown fences — {len(text):,} chars remaining")

    # Attempt 1: direct parse
    try:
        result = json.loads(text)
        if isinstance(result, list):
            debug.add("ok", "JSON-PARSE", f"Direct parse succeeded — {len(result)} items")
            return result
        if isinstance(result, dict):
            for key in result:
                if isinstance(result[key], list) and result[key]:
                    debug.add("ok", "JSON-PARSE", f"Unwrapped dict key '{key}' — {len(result[key])} items")
                    return result[key]
    except json.JSONDecodeError as e:
        debug.add("warn", "JSON-PARSE", f"Direct parse failed at char {e.pos}: {e.msg}",
                  f"Context: …{text[max(0, e.pos - 60):e.pos + 60]}…")

    # Attempt 2: bracket slice
    s_idx, e_idx = text.find("["), text.rfind("]")
    if s_idx != -1 and e_idx != -1 and e_idx > s_idx:
        try:
            result = json.loads(text[s_idx:e_idx + 1])
            if isinstance(result, list):
                debug.add("ok", "JSON-EXTRACT", f"Bracket-slice succeeded — {len(result)} items")
                return result
        except json.JSONDecodeError as ex:
            debug.add("warn", "JSON-EXTRACT", f"Bracket-slice failed at char {ex.pos}: {ex.msg}")

    # Attempt 3: truncation recovery — walk chars to find last COMPLETE top-level object
    debug.add("warn", "JSON-TRUNCATION", "Attempting truncation recovery — model likely hit output token limit")
    start = text.find("[")
    if start != -1:
        content = text[start:]
        depth = 0
        in_string = False
        escape_next = False
        last_complete_pos = -1
        for i, ch in enumerate(content):
            if escape_next:
                escape_next = False
                continue
            if ch == "\\" and in_string:
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    last_complete_pos = i
        if last_complete_pos != -1:
            repaired = content[:last_complete_pos + 1].rstrip().rstrip(",") + "\n]"
            try:
                result = json.loads(repaired)
                if isinstance(result, list) and result:
                    debug.add("ok", "JSON-TRUNCATION",
                              f"Recovered {len(result)} complete items from truncated output "
                              f"(output was cut off — last item may be missing)",
                              "Tip: switch to a model with higher output limits")
                    return result
            except json.JSONDecodeError as ex:
                debug.add("err", "JSON-TRUNCATION", f"Truncation repair parse failed: {ex}")

    debug.add("err", "JSON-FINAL", "All parse attempts failed", f"Raw text (first 500 chars):\n{original[:500]}")
    return []
