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
    status: str
    discovered_at: datetime
    # analysis freshness vs the active CV: current | outdated | none | error
    analysis_state: str = "none"
    # analysis fields flattened in the router
    match_score: int | None = None
    translated_summary: str | None = None
    explanation: str | None = None
    matching_skills: list | None = None
    missing_requirements: list | None = None


class JobStatusUpdate(BaseModel):
    status: str  # new|saved|dismissed|applied|interview


class ManualJobIn(BaseModel):
    url: str
    title: str | None = None
    company: str | None = None
    location: str | None = None
    description: str | None = None


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


# ── Status ────────────────────────────────────────────────────────────────
class StatusOut(BaseModel):
    last_run_at: datetime | None
    last_run_trigger: str | None
    jobs_total: int
    jobs_new: int
    jobs_analyzed: int
    errors: list
    ai_enabled: bool
