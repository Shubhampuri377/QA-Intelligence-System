"""
Serialisers that record the line number of every value as they write it.

Why not just search the finished file for the value: a name like "Michael Brown"
appears many times in a real feed, so a text search finds the wrong occurrence.
The line is therefore captured while writing, keyed by the value's full path —
exact by construction, never guessed.

Every writer returns (text, locations) where locations maps
    "0/clientInfo/OWNER/organizationName" -> line number (1-based)
so the report can print a Notepad++ Ctrl+G target alongside the JSON/XML path.
Paths are kept as well as lines: reformatting the file in an editor shifts line
numbers, but the path stays valid.
"""

import re
from xml.sax.saxutils import escape as _xml_escape

INDENT = "  "


def _j(v) -> str:
    """JSON scalar. Values are emitted as strings when the source was a string,
    so identifiers keep their leading zeros — "0004073361" must not become a
    number."""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    s = str(v).replace("\\", "\\\\").replace('"', '\\"')
    s = s.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    return f'"{s}"'


def write_json(records: list, root_key: str = "records") -> tuple:
    """Pretty JSON with 2-space indent, recording a line per leaf."""
    lines, locs = [], {}

    def emit(s):
        lines.append(s)
        return len(lines)

    def walk(node, path, depth, trailing):
        pad = INDENT * depth
        if isinstance(node, dict):
            emit(pad + "{")
            keys = list(node.keys())
            for i, k in enumerate(keys):
                last = i == len(keys) - 1
                child = node[k]
                cpath = f"{path}/{k}" if path else k
                if isinstance(child, (dict, list)):
                    emit(f"{pad}{INDENT}{_j(k)}: " + ("{" if isinstance(child, dict) else "["))
                    inner(child, cpath, depth + 1)
                    emit(f"{pad}{INDENT}" + ("}" if isinstance(child, dict) else "]")
                         + ("" if last else ","))
                else:
                    ln = emit(f"{pad}{INDENT}{_j(k)}: {_j(child)}" + ("" if last else ","))
                    locs[cpath] = ln
            emit(pad + "}" + trailing)
        elif isinstance(node, list):
            emit(pad + "[")
            inner(node, path, depth)
            emit(pad + "]" + trailing)
        else:
            ln = emit(pad + _j(node) + trailing)
            locs[path] = ln

    def inner(node, path, depth):
        """Emits a dict/list body without re-emitting its own braces."""
        pad = INDENT * (depth + 1)
        if isinstance(node, dict):
            keys = list(node.keys())
            for i, k in enumerate(keys):
                last = i == len(keys) - 1
                child, cpath = node[k], (f"{path}/{k}" if path else k)
                if isinstance(child, dict):
                    emit(f"{pad}{_j(k)}: {{")
                    inner(child, cpath, depth + 1)
                    emit(pad + "}" + ("" if last else ","))
                elif isinstance(child, list):
                    emit(f"{pad}{_j(k)}: [")
                    inner(child, cpath, depth + 1)
                    emit(pad + "]" + ("" if last else ","))
                else:
                    locs[cpath] = emit(f"{pad}{_j(k)}: {_j(child)}" + ("" if last else ","))
        else:
            for i, item in enumerate(node):
                last = i == len(node) - 1
                ipath = f"{path}[{i}]"
                if isinstance(item, dict):
                    emit(pad + "{")
                    inner(item, ipath, depth + 1)
                    emit(pad + "}" + ("" if last else ","))
                elif isinstance(item, list):
                    emit(pad + "[")
                    inner(item, ipath, depth + 1)
                    emit(pad + "]" + ("" if last else ","))
                else:
                    locs[ipath] = emit(pad + _j(item) + ("" if last else ","))

    emit("{")
    emit(f'{INDENT}{_j(root_key)}: [')
    for i, rec in enumerate(records):
        last = i == len(records) - 1
        emit(INDENT * 2 + "{")
        inner(rec, str(i), 2)
        emit(INDENT * 2 + "}" + ("" if last else ","))
    emit(f"{INDENT}]")
    emit("}")
    return "\n".join(lines) + "\n", locs


def write_xml(records: list, root_tag: str = "Records", rec_tag: str = "Record") -> tuple:
    lines, locs = [], {}

    def emit(s):
        lines.append(s)
        return len(lines)

    def safe(tag):
        t = re.sub(r"[^A-Za-z0-9_.-]", "_", str(tag)) or "field"
        return f"f_{t}" if t[0].isdigit() else t

    def walk(node, path, depth):
        pad = INDENT * depth
        if isinstance(node, dict):
            for k, v in node.items():
                tag, cpath = safe(k), (f"{path}/{k}" if path else k)
                if isinstance(v, dict):
                    emit(f"{pad}<{tag}>")
                    walk(v, cpath, depth + 1)
                    emit(f"{pad}</{tag}>")
                elif isinstance(v, list):
                    emit(f"{pad}<{tag}>")
                    for i, item in enumerate(v):
                        ipath = f"{cpath}[{i}]"
                        if isinstance(item, (dict, list)):
                            emit(f"{pad}{INDENT}<Item>")
                            walk(item, ipath, depth + 2)
                            emit(f"{pad}{INDENT}</Item>")
                        else:
                            locs[ipath] = emit(f"{pad}{INDENT}<Item>"
                                               f"{_xml_escape('' if item is None else str(item))}</Item>")
                    emit(f"{pad}</{tag}>")
                else:
                    locs[cpath] = emit(f"{pad}<{tag}>"
                                       f"{_xml_escape('' if v is None else str(v))}</{tag}>")
        elif isinstance(node, list):
            for i, item in enumerate(node):
                walk(item, f"{path}[{i}]", depth)

    emit('<?xml version="1.0" encoding="UTF-8"?>')
    emit(f"<{root_tag}>")
    for i, rec in enumerate(records):
        emit(f'{INDENT}<{rec_tag} index="{i}">')
        walk(rec, str(i), 2)
        emit(f"{INDENT}</{rec_tag}>")
    emit(f"</{root_tag}>")
    return "\n".join(lines) + "\n", locs


def _flatten(rec, prefix="", out=None):
    out = {} if out is None else out
    if isinstance(rec, dict):
        for k, v in rec.items():
            _flatten(v, f"{prefix}/{k}" if prefix else k, out)
    elif isinstance(rec, list):
        for i, v in enumerate(rec):
            _flatten(v, f"{prefix}[{i}]", out)
    else:
        out[prefix] = rec
    return out


def write_csv(records: list) -> tuple:
    """One row per record. Column order is the union of flattened paths, so the
    header row is line 1 and record i is line i+2."""
    flat = [_flatten(r) for r in records]
    cols = []
    for f in flat:
        for k in f:
            if k not in cols:
                cols.append(k)

    def cell(v):
        s = "" if v is None else str(v)
        return '"' + s.replace('"', '""') + '"' if any(c in s for c in ',"\n') else s

    lines, locs = [",".join(cell(c) for c in cols)], {}
    for i, f in enumerate(flat):
        ln = len(lines) + 1
        lines.append(",".join(cell(f.get(c, "")) for c in cols))
        for c in cols:
            if c in f:
                locs[f"{i}/{c}"] = ln
    return "\n".join(lines) + "\n", locs


WRITERS = {"JSON": write_json, "XML": write_xml, "CSV": write_csv}


def write(records: list, fmt: str) -> tuple:
    fn = WRITERS.get((fmt or "JSON").upper())
    if not fn:
        raise ValueError(f"No located writer for format '{fmt}'")
    return fn(records)
