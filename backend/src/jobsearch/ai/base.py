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


@dataclass
class MatchResult:
    """Outcome of validating one job against the effective matching profile."""

    match_score: int  # 0-100
    explanation: str
    matching_skills: list[str] = field(default_factory=list)
    missing_requirements: list[str] = field(default_factory=list)
    detected_language: str | None = None
    translated_summary: str | None = None
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
