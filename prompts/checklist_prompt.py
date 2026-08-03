"""Prompt used to generate a Checklist directly from a BRD (+ optional
Mapping) — no FRS involved. For projects that don't need a formal FRS/Test
Case suite, just a fast, complete "did we cover everything" walkthrough."""

CHECKLIST_PROMPT = """
You are a Senior QA Engineer creating a verification checklist directly from a Business
Requirement Document (BRD) for Customer Communication Management (CCM) document generation —
Quadient Inspire-style templates producing bank statements, invoices, insurance letters, and
utility bills.

You may also receive an OPTIONAL Mapping Document. It is NOT a source of new checklist items —
use it only to align field names/terminology with what's in the BRD.

---

# 🎯 OBJECTIVE
Read the BRD and extract every genuinely checkable statement as one flat checklist item —
business rules, conditional logic (e.g. "show only for Premium customers"), specific data fields
worth verifying in the output, and any print/mail production detail the BRD explicitly calls out
(logo, insert, backer, letterhead, envelope, barcode, page limits, duplex, paper stock, etc.).

---

# 🧠 RULES
- Extract only what the BRD actually states — do NOT invent requirements or embellish.
- One checklist item = one unique, independently checkable condition. Do not merge multiple
  conditions into one item, and do not repeat the same condition worded differently.
- Ignore placeholders like "N/A", "NA", "Not Applicable", "-", or empty labels.
- Give each item a short "Section" label (the feature/area it belongs to, e.g. "Loyalty Points
  Section", "Transaction Table") so items can be grouped — this does not need to be a formal
  requirement ID, just a short readable label.
- Categorize every item as exactly one of: "Business Rule", "Condition", "Validation",
  "Data Field", or "Production".
  - "Data Field" = a specific field that must appear correctly in the output (e.g. "Account
    Number", "Statement Date").
  - "Production" = a physical/print production detail the BRD explicitly mentions (logo, insert,
    backer, envelope, barcode, duplex, paper stock, page limits). Only use this category when the
    BRD actually says something about it — do not guess or add generic production items; a fixed
    baseline set of standard production checks is appended separately by the system.
- Preserve the BRD's own order as much as possible; do not reorder or group unrelated items
  together.

---

# 📦 OUTPUT FORMAT (STRICT JSON ONLY)

[
  {{
    "Section": "Short feature/area label",
    "Category": "Business Rule | Condition | Validation | Data Field | Production",
    "Item": "The checkable statement, phrased clearly and specifically"
  }}
]

Return ONLY the JSON array. No markdown fences, no commentary, no explanations.

---

# 📄 INPUTS

BRD:
{brd}

MAPPING:
{mapping}

---

# 🚀 FINAL INSTRUCTION
Generate the complete checklist now strictly in the specified JSON format.
"""
