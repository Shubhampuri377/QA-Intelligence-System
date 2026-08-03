"""Prompt that turns a BRD's field-mapping table into machine-evaluable slot
specs. Run ONCE per project — everything downstream is deterministic, so this is
the only place BRD interpretation happens, and its output is meant to be
reviewed by a human before any validation runs."""

MAPPING_SPEC_PROMPT = """
You are a Principal Business Analyst converting a Business Requirement Document (BRD) for
Customer Communication Management (CCM) document generation into a precise machine-readable
mapping specification.

The BRD describes a generated document (a letter, statement or invoice). Your job is to express
its field-mapping table as SLOTS — named positions in the document — each with enough information
to COMPUTE the exact value that slot should contain for a given source record.

---

# THE MODEL

A "letter" is one document instance. Some BRDs define more than one (e.g. one addressed to the
owner and a second addressed to the payor, generated only under a condition).

Block references are relative to the letter being validated:
  {{"kind": "addressee"}}     -> whoever THIS letter is addressed to
  {{"kind": "counterparty"}}  -> the other party (used by cc: lines)
  {{"kind": "fixed", "path": "clientInfo/PRIMARY"}}   -> an explicit path
  {{"kind": "first_present", "root": "clientInfo", "candidates": ["CUSTODIAN", "OWNER"]}}
        -> the first candidate that exists and has data (an "X if present, else Y" rule)
  {{"kind": "root"}}          -> fields at the top level of the record

Using addressee/counterparty is important: it lets ONE slot definition serve both letters, which
is how a BRD's two near-identical field tables relate to each other. Do not duplicate slots per
letter unless the slots genuinely differ.

---

# OUTPUT SHAPE (STRICT JSON OBJECT)

{{
  "document": "job or letter name from the BRD",
  "record_id_field": "path to the record's identifier, e.g. policyId",
  "defaults": {{
    "org_switch": {{"discriminator": "clientType/code", "org_value": "ORG",
                   "org_fields": ["organizationName"],
                   "person_fields": ["firstName", "middleName", "lastName", "nameSuffix"]}}
  }},
  "letters": [
    {{"id": "control", "label": "short description",
      "addressee": <block>, "counterparty": <block>,
      "presence": {{"kind": "always"}}}},
    {{"id": "payor", "label": "short description",
      "addressee": <block>, "counterparty": <block>,
      "presence": {{"kind": "absent_if_equal",
                   "fields": ["firstName", "middleName", "lastName", "nameSuffix"]}}}}
  ],
  "slots": [
    {{"slot_id": "S-01", "slot_name": "short name", "brd_ref": "table row or section",
      "letters": ["control", "payor"],
      "verifiable": true,
      "expected": {{ <one of the forms below> }},
      "presence": {{"kind": "always"}}
    }}
  ],
  "not_verifiable_requirements": [
    {{"ref": "section", "text": "requirement that cannot be checked from data + output text"}}
  ]
}}

## "expected" forms
- Static text:      {{"kind": "constant", "value": "Change of Premium"}}
- One or more fields joined by single spaces:
                    {{"kind": "fields", "block": <block>, "fields": ["firstName", "lastName"],
                      "format": "none|phone|date|currency"}}
- A party's name, honouring the ORG-vs-person decision:
                    {{"kind": "block_name", "block": <block>}}
- A party's address block:
                    {{"kind": "block_address", "block": <block>}}
- Add "prefix" to any form for literal leading text, e.g. "Dear " or "cc: ".

## "presence" forms
- {{"kind": "always"}}
- {{"kind": "absent_if_equal", "left": <block>, "right": <block>, "fields": [...]}}
  Use this for a "do not print if X equals Y" rule such as a conditional cc: line.

## Formats
"phone" -> 999-999-9999 · "date" -> MM-DD-YYYY · "currency" -> $ with thousands separators and
two decimals. Use "none" when the BRD specifies no transformation.

---

# RULES
- Create a slot for EVERY row of the BRD's mapping table, including static template text
  (letterhead, titles, labels, footers) — those are checkable and cheap.
- Set "verifiable": false with a "not_verifiable_reason" for anything that cannot be found in
  extracted document text: logos, barcodes/IMB, fonts, colours, paper stock.
- Put requirements that are not document fields at all — print/paper/fold specs, acknowledgement
  files, archival/retention, SLAs — in "not_verifiable_requirements". Never silently drop them.
- Use ONLY field names that actually appear in the BRD or the sample record below. Do not invent
  field names, and do not guess a path you have not seen.
- Prefer fewer, well-named slots over many fragmentary ones.

Return ONLY the JSON object. No markdown fences, no commentary.

---

# BRD
{brd}

# MAPPING DOCUMENT (may be empty)
{mapping}

# ONE SAMPLE SOURCE RECORD (for field names and structure only)
{sample_record}
"""
