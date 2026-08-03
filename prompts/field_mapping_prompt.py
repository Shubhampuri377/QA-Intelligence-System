"""Prompts for Field Mapping Validation — the AI pass only sees fields the
deterministic rules could not resolve, so these prompts are deliberately
narrow: judge a rendering, don't re-derive the whole document."""

FIELD_COMPARE_PROMPT = """
You are a QA Engineer validating Customer Communication Management (CCM) output — a document
generated from a source data feed (Quadient Inspire-style template rendering).

You are given the text of ONE generated document, and a list of source fields whose values could
not be matched mechanically. For each field, decide whether the source value is correctly
rendered in that document.

---

# VERDICTS — use exactly one per field
- "MATCH"    — the value IS rendered, even if reformatted (uppercased, currency/date formatting,
               abbreviated, reordered, country code or leading zeros suppressed, split across
               lines, or shown next to a label). Formatting differences are NOT defects.
               ALSO use MATCH when the value is absent but the BUSINESS RULES below explain that
               absence — a conditional section whose condition was not met, a field the spec says
               is internal/not printed, or a value the spec says is deliberately suppressed. Cite
               the rule in the note.
- "MISMATCH" — the field IS rendered, but with a value that contradicts the source (a different
               number, a different date, generic placeholder text where a real value was expected).
- "GAP"      — the value is populated in the source, does not appear anywhere in the document, and
               nothing in the BUSINESS RULES explains why it is missing.
- "REVIEW"   — you genuinely cannot tell from the text given, or the absence looks intentional but
               no rule confirms it (say so in the note).

# ABSENT FIELDS
Some fields below are absent from the document — that has already been established mechanically.
For those, your job is NOT to search again; it is to decide WHY they are absent:
  * a BUSINESS RULE explains it  -> MATCH, and name the rule in the note
  * no rule explains it          -> GAP
  * plausibly intentional but unconfirmed by any rule -> REVIEW
Never guess a suppression rule that is not written in the BUSINESS RULES section.

# RULES
- Judge ONLY from the OUTPUT DOCUMENT TEXT and the BUSINESS RULES below. Never assume a value is
  present because it "should" be. If you cannot see it and no rule explains it, it is GAP.
- PDF text extraction loses layout. A value split across lines or separated from its label still
  counts as rendered.
- Keep every note under 25 words, specific, and free of hedging. State what you observed.
  Good: "Literal date not printed; 'Upon Receipt' shown instead." Bad: "May be a possible issue."
- If MAPPING RULES below explain a transformation or suppression, apply it and say so in the note.
- Return one object per input field, same Field_Path values, no extras, no omissions.

# OUTPUT_VALUE — quote the document, do not paraphrase
For every field, also report what the document actually shows:
  * rendered            -> copy the exact text VERBATIM from the OUTPUT DOCUMENT TEXT (max ~100
                           chars). Include its label if that is how it appears, e.g.
                           "SITE # 1173389" or "Payment Due Upon Receipt".
  * absent              -> "Not present in output"
  * absent but a rule explains it -> "Not present in output (suppressed per rule)"
Never invent, correct, complete or tidy this text. If the document shows a misspelling or an odd
abbreviation, reproduce it as-is — that is the evidence a reviewer needs.

# STRICT OUTPUT FORMAT — JSON ARRAY ONLY
[
  {{"Field_Path": "exactly as given", "Status": "MATCH|MISMATCH|GAP|REVIEW",
    "Output_Value": "verbatim text from the document, or 'Not present in output'",
    "Notes": "under 25 words, or empty string"}}
]

Return ONLY the JSON array. No markdown fences, no commentary.

---

# BUSINESS RULES & MAPPING SPEC (from the BRD and mapping document — may be empty)
{mapping_rules}

# OUTPUT DOCUMENT TEXT
{output_text}

# FIELDS TO JUDGE
Each entry may carry "Mechanical_Finding": "ABSENT" — meaning the value was already confirmed not
to appear in the document, so decide WHY per the ABSENT FIELDS instruction above.
{fields}
"""

MAPPING_SUMMARY_PROMPT = """
You are a QA lead writing the executive summary of a field mapping validation report for a
Customer Communication Management (CCM) document run.

You are given the reconciliation counts and every finding that was flagged. Write a short,
factual summary for a client-facing report.

# RULES
- Do NOT invent findings, counts, or field names. Use only what is given.
- "narrative": 2-4 sentences. State what was validated, how many documents/records were involved,
  and the overall shape of the result. No marketing language, no hedging.
- "assessment": one line starting with PASS, PASS WITH FINDINGS, or FAIL, then a dash and a brief
  justification. Use PASS only if there are zero mismatches and zero gaps.
- "recommendations": 2-5 concrete next actions, each naming the specific field or behaviour to
  check and who should confirm it (business owner, mapping owner, developer). No generic advice
  like "review the report".

# STRICT OUTPUT FORMAT — JSON OBJECT ONLY
{{
  "narrative": "...",
  "assessment": "...",
  "recommendations": ["...", "..."]
}}

Return ONLY the JSON object. No markdown fences, no commentary.

---

# RUN CONTEXT
Source feed: {source_file}
Generated output: {output_file}
Records in feed: {record_count}
Document instances located in output: {instance_count}
Mapped fields validated: {field_count}
Matches: {matches}   Mismatches: {mismatches}   Gaps: {gaps}   Flagged for review: {reviews}

# FINDINGS (mismatches, gaps, and review items)
{findings}
"""
