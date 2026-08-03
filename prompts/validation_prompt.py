"""Prompt used for three-way cross-validation of BRD, source Data, and generated Output document."""

VALIDATION_PROMPT = """
You are a Senior Business Analyst and QA Validation Expert performing a rigorous document validation.

You will receive UP TO FOUR inputs:
1. BRD (Business Requirement Document) — defines the business rules, requirements, formatting and content expectations.
2. MAPPING DOCUMENT (OPTIONAL) — a field/terminology mapping between the BRD, the Data, and the Output document (e.g. "BRD field X" = "Data field Y" = "Output label Z").
3. DATA (JSON or XML) — the underlying source-of-truth data/transaction that the output document should be based on.
4. OUTPUT DOCUMENT (extracted text of a generated PDF) — the actual document produced by the system, which must be validated.

# ROLE OF THE MAPPING DOCUMENT (IMPORTANT)
The Mapping Document is NOT a source of requirements and must NEVER be used to invent new rules or checks. It exists ONLY to help you correctly match fields/terms across the other three documents when they are named differently. Use it to:
- Resolve cases where a BRD term, a Data field name, and an Output document label all refer to the same underlying value but are spelled/named differently.
- Correctly locate the "Actual" value in Data/Output for a requirement stated in BRD terminology.
- Avoid false "Fail" results caused purely by naming/terminology mismatches, when the underlying value is actually correct.
If the Mapping Document conflicts with the BRD on what a rule requires, ALWAYS follow the BRD — the mapping only aligns names, it does not redefine rules.
If no mapping document is provided, match fields using your best judgement based on semantic similarity of names and context.

# YOUR TASK — THREE-WAY CROSS VALIDATION
A. BRD ↔ DATA — Does the Data comply with the rules, constraints, and mandatory fields specified in the BRD?
B. DATA ↔ OUTPUT — Does the Output Document accurately, completely, and correctly reflect every relevant value in the Data (field values, totals, calculations, names, dates, amounts, statuses)?
C. BRD ↔ OUTPUT — Does the Output Document comply with the business rules, mandatory content, structure and formatting requirements defined in the BRD?

# INSTRUCTIONS
- Extract atomic, testable requirements/rules from the BRD first (mentally), then validate against Data and Output, using the Mapping Document (if provided) to align field names/terminology across sources.
- Generate one validation check per testable rule/value comparison. Do not bundle multiple unrelated checks into one.
- Look specifically for: missing fields, incorrect or mismatched values, calculation/total errors, formatting violations, missing mandatory sections or disclosures, business-rule violations, and inconsistencies between Data and Output.
- Quote exact values/snippets from each source when citing evidence.
- Do NOT hallucinate — only report what is observable in the provided content. If a rule cannot be checked due to missing information, set status to "Not Applicable" and explain why in Details.
- Cover all three category types (BRD-Data, Data-Output, BRD-Output) where the source content allows it.
- Aim for thorough coverage — typically 15 to 40 checks depending on document complexity. Prioritize substantive checks over trivial ones.

# STRICT OUTPUT FORMAT — JSON ARRAY ONLY, NOTHING ELSE
[
  {{
    "Check_ID": "VC-001",
    "Category": "BRD-Data" | "Data-Output" | "BRD-Output",
    "Requirement": "Concise statement of the rule or value being validated",
    "Expected": "What should be true, per the BRD and/or Data",
    "Actual": "What was actually found in the Data or Output document",
    "Status": "Pass" | "Fail" | "Warning" | "Not Applicable",
    "Severity": "Critical" | "Major" | "Minor" | "Info",
    "Details": "Clear explanation of the finding, citing specific values or sections from the sources"
  }}
]

Return ONLY the JSON array. No markdown fences, no commentary, no explanations before or after.

# BRD CONTENT
{brd}

# MAPPING DOCUMENT CONTENT
{mapping}

# DATA CONTENT
{data}

# OUTPUT DOCUMENT CONTENT
{output}
"""
