"""Pydantic schemas for the API surface."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ── Jobs ──────────────────────────────────────────────────────────────────
class JobOut(ORMModel):
    id: int
    source: str
    url: str | None
    title: str
    company: str | None
    location: str | None
    language: str | None
    salary: str | None = None
    work_type: str | None = None  # remote | hybrid | onsite | None
    # Description looks truncated → held back from analysis until the user fixes it.
    description_incomplete: bool = False
    status: str
    discovered_at: datetime
    # analysis freshness vs the active CV: current | outdated | none | error
    analysis_state: str = "none"
    # application generation vs the active CV: none | pending | done | error
    application_state: str = "none"
    # analysis fields flattened in the router
    match_score: int | None = None
    translated_summary: str | None = None
    explanation: str | None = None
    matching_skills: list | None = None
    missing_requirements: list | None = None
    # Per-dimension score breakdown: [{dimension, score, weight, reason}]
    dimension_scores: list | None = None
    # Gaps to close / what to learn first: [{skill, level, why}], level ∈ basic|average
    learning_gaps: list | None = None
    # Inferred posting location + eligibility verdict (worldwide|restricted|unclear)
    posting_country: str | None = None
    eligibility: str | None = None
    eligibility_note: str | None = None


class JobStatusUpdate(BaseModel):
    status: str  # new|saved|dismissed|applied|interview


class JobPatch(BaseModel):
    """Partial update of a job's user-editable fields from the dashboard."""

    status: str | None = None  # new|saved|dismissed|applied|interview
    salary: str | None = None  # free-text salary range; "" clears it
    description: str | None = None  # paste the full posting text (replaces the stored one)
    # Override the truncation heuristic: False = "this description is complete, analyze it";
    # True = "this is cut off, hold it back from analysis".
    description_incomplete: bool | None = None


class JobDetailOut(ORMModel):
    """Full single-job payload (includes the heavy description), fetched on demand."""

    id: int
    title: str
    company: str | None
    description: str | None


class ManualJobIn(BaseModel):
    """A job added by hand from the dashboard. Needs at least a URL or a title."""

    url: str | None = None
    title: str | None = None
    company: str | None = None
    location: str | None = None
    description: str | None = None
    salary: str | None = None
    work_type: str | None = None  # remote | hybrid | onsite


# ── Queries ───────────────────────────────────────────────────────────────
class QueryIn(BaseModel):
    name: str
    source: str
    enabled: bool = True
    keywords: str | None = None
    work_type: str | None = None
    location: str | None = None
    source_config: dict = {}
    reference_url: str | None = None


class QueryUpdate(BaseModel):
    name: str | None = None
    source: str | None = None
    enabled: bool | None = None
    keywords: str | None = None
    work_type: str | None = None
    location: str | None = None
    source_config: dict | None = None
    reference_url: str | None = None


class QueryOut(ORMModel):
    id: int
    name: str
    source: str
    enabled: bool
    keywords: str | None
    work_type: str | None
    location: str | None
    source_config: dict | None
    reference_url: str | None


# ── CV / profile ──────────────────────────────────────────────────────────
class CVOut(ORMModel):
    id: int
    source_filename: str | None
    derived_profile: dict | None
    uploaded_at: datetime
    is_active: bool


class ProfileOut(ORMModel):
    id: int
    cv_id: int
    must_have_skills: list | None
    nice_to_have_skills: list | None
    dealbreakers: list | None
    min_seniority: str | None
    notes: str | None


# ── Applications ────────────────────────────────────────────────────────────
class ApplicationOut(ORMModel):
    job_id: int
    cv_id: int
    # pending | done | error — drives the dashboard spinner, same as analysis.
    processing_status: str
    error_message: str | None = None
    cover_letter_md: str | None = None
    cv_summary_md: str | None = None
    cv_full_md: str | None = None
    reviewer_notes: str | None = None
    model: str | None = None
    updated_at: datetime | None = None


class ApplicationUpdate(BaseModel):
    """User edits to the generated application. Only present fields are changed."""

    cover_letter_md: str | None = None
    cv_summary_md: str | None = None
    cv_full_md: str | None = None


class PromptOut(BaseModel):
    key: str
    label: str
    description: str
    required_placeholders: list[str]
    template: str
    is_customized: bool
    updated_at: str | None


class PromptUpdate(BaseModel):
    template: str


class ProfileUpdate(BaseModel):
    must_have_skills: list[str] | None = None
    nice_to_have_skills: list[str] | None = None
    dealbreakers: list[str] | None = None
    min_seniority: str | None = None
    notes: str | None = None


# ── Insights ────────────────────────────────────────────────────────────────
class InsightsOut(ORMModel):
    cv_id: int | None
    jobs_analyzed: int
    # Ranked gaps: [{skill, count, severity: basic|average|null, why}]
    items: list | None
    # "ai" if the AI canonicalization ran, "deterministic" if it fell back.
    grouping: str = "deterministic"
    # The reason the AI wasn't used, when grouping is "deterministic". None on success.
    grouping_error: str | None = None
    computed_at: datetime
    # True when the snapshot was computed against a CV that is no longer active — the UI
    # shows a "Refresh to update" hint. Set by the router, not stored.
    stale_cv: bool = False


# ── Status ────────────────────────────────────────────────────────────────
class StatusOut(BaseModel):
    last_run_at: datetime | None
    last_run_trigger: str | None
    jobs_total: int
    jobs_new: int
    jobs_analyzed: int
    errors: list
    ai_enabled: bool
