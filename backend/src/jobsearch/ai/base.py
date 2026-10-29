"""AI provider contract and result types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class ProfileExtraction:
    """Baseline matching profile auto-derived from a CV."""

    skills: list[str] = field(default_factory=list)
    seniority: str | None = None
    years_experience: int | None = None
    summary: str | None = None
    # Languages the candidate works in, with self-declared level, e.g.
    # [{"language": "English", "level": "fluent"}]. Feeds the analyze prompt's Language Gate.
    languages: list[dict] = field(default_factory=list)


@dataclass
class DimensionScore:
    """One scored dimension behind the overall match_score, with its reasoning."""

    dimension: str
    score: int  # 0-100
    weight: float  # share of the weighted average, e.g. 0.30
    reason: str = ""

    def as_dict(self) -> dict:
        return {
            "dimension": self.dimension,
            "score": self.score,
            "weight": self.weight,
            "reason": self.reason,
        }


@dataclass
class MatchResult:
    """Outcome of validating one job against the effective matching profile."""

    match_score: int  # 0-100
    explanation: str
    matching_skills: list[str] = field(default_factory=list)
    missing_requirements: list[str] = field(default_factory=list)
    detected_language: str | None = None
    translated_summary: str | None = None
    # Per-dimension breakdown explaining the overall score. Empty when the provider
    # does not return one.
    dimension_scores: list[DimensionScore] = field(default_factory=list)
    # Where the role appears to be posted / hire from, inferred from the description
    # (salary in US cities, "US only", named country, etc.). Best-effort guess.
    posting_country: str | None = None
    # Candidate eligibility verdict for a non-local (e.g. EU) applicant:
    #   "worldwide"  — explicitly open to anywhere, or clearly no location restriction
    #   "restricted" — limited to a country/region the candidate is likely outside of
    #   "unclear"    — not stated; a guess with low confidence
    eligibility: str | None = None
    # One short sentence of evidence for the country/eligibility call.
    eligibility_note: str | None = None
    model: str = "stub"


class AIProvider(Protocol):
    """Pluggable AI backend. Must never invent qualifications (design requirement 6)."""

    model: str

    def extract_profile(
        self, cv_text: str, template: str | None = None
    ) -> ProfileExtraction:
        """Derive a baseline skills/seniority profile from CV text.

        `template` is an optional override of the prompt sent to the model (ignored by
        providers that do not call an LLM, e.g. the stub).
        """
        ...

    def analyze_job(
        self,
        *,
        job_title: str,
        job_description: str,
        job_language: str | None,
        cv_text: str,
        effective_profile: dict,
        template: str | None = None,
    ) -> MatchResult:
        """Detect language, translate if useful, and score the job against the profile."""
        ...
