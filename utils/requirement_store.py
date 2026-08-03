"""
Requirement Store — the structured, addressable output of the BRD Agent.
Every downstream agent (Validation, Evidence, Reviewer, Report) works off of
this shared representation instead of re-parsing the BRD.
"""

import re
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional

_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "must", "shall", "should",
    "when", "then", "else", "not", "all", "any", "are", "was", "were", "will",
}


def _as_list(v) -> List[str]:
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    if isinstance(v, str):
        return [v.strip()] if v.strip() else []
    return []


@dataclass
class Requirement:
    id: str
    text: str
    business_rule: str = ""
    input_fields: List[str] = field(default_factory=list)
    output_fields: List[str] = field(default_factory=list)
    calculations: List[str] = field(default_factory=list)
    validation_type: str = ""
    brd_section: str = ""
    expected_format: str = ""
    calculation_formula: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Requirement":
        return cls(
            id=str(d.get("Requirement_ID") or d.get("id") or d.get("ID") or "").strip(),
            text=str(d.get("Requirement_Text") or d.get("text") or d.get("Requirement") or "").strip(),
            business_rule=str(d.get("Business_Rule") or d.get("business_rule") or "").strip(),
            input_fields=_as_list(d.get("Input_Fields") or d.get("input_fields")),
            output_fields=_as_list(d.get("Output_Fields") or d.get("output_fields")),
            calculations=_as_list(d.get("Calculations") or d.get("calculations")),
            validation_type=str(d.get("Validation_Type") or d.get("validation_type") or "").strip(),
            brd_section=str(d.get("BRD_Section") or d.get("brd_section") or "").strip(),
            expected_format=str(d.get("Expected_Format") or d.get("expected_format") or "").strip(),
            calculation_formula=str(d.get("Calculation_Formula") or d.get("calculation_formula") or "").strip(),
        )

    @property
    def keywords(self) -> List[str]:
        """Terms the retrieval layer uses to locate relevant Data/Output evidence."""
        terms = set()
        for f in self.input_fields + self.output_fields:
            f = f.strip().lower()
            if f:
                terms.add(f)
        for blob in (self.business_rule, self.text):
            for word in re.findall(r"[A-Za-z][A-Za-z0-9_]{2,}", blob):
                w = word.lower()
                if w not in _STOPWORDS:
                    terms.add(w)
        return list(terms)


class RequirementStore:
    def __init__(self, requirements: Optional[List[Requirement]] = None):
        self.requirements: List[Requirement] = requirements or []

    @classmethod
    def from_raw(cls, raw_list: List[dict]) -> "RequirementStore":
        reqs = []
        for i, item in enumerate(raw_list or [], start=1):
            req = Requirement.from_dict(item)
            if not req.id:
                req.id = f"REQ-{i:03d}"
            reqs.append(req)
        return cls(reqs)

    def __len__(self):
        return len(self.requirements)

    def __iter__(self):
        return iter(self.requirements)

    def get(self, req_id: str) -> Optional[Requirement]:
        for r in self.requirements:
            if r.id == req_id:
                return r
        return None

    def batches(self, size: int = 10):
        """Yields requirement batches — keeps each Validation Agent call small
        regardless of how many requirements the BRD produced."""
        for i in range(0, len(self.requirements), size):
            yield self.requirements[i:i + size]

    def to_list(self) -> List[dict]:
        return [r.to_dict() for r in self.requirements]

    def coverage_stats(self) -> dict:
        total = len(self.requirements)
        return {
            "total": total,
            "with_business_rules": sum(1 for r in self.requirements if r.business_rule),
            "with_calculations": sum(1 for r in self.requirements if r.calculations),
            "with_validation_type": sum(1 for r in self.requirements if r.validation_type),
        }

    def find_duplicates(self) -> List[List[str]]:
        """Groups requirement IDs whose text is near-identical (normalized match)."""
        groups: Dict[str, List[str]] = {}
        for r in self.requirements:
            norm = re.sub(r"\s+", " ", r.text.strip().lower())
            if norm:
                groups.setdefault(norm, []).append(r.id)
        return [ids for ids in groups.values() if len(ids) > 1]
