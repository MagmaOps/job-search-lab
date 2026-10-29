"""SQLAlchemy ORM models — the data model from docs/design.md section 3."""

from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class JobStatus(str, enum.Enum):
    new = "new"
    saved = "saved"
    dismissed = "dismissed"
    applied = "applied"
    interview = "interview"


class ProcessingStatus(str, enum.Enum):
    pending = "pending"
    done = "done"
    error = "error"


def _utcnow() -> datetime:
    # Naive UTC to match the timezone-naive DateTime columns consistently.
    return datetime.now(timezone.utc).replace(tzinfo=None)


class CV(Base):
    """A CV version. Only extracted text + derived profile are kept; the file is discarded."""

    __tablename__ = "cv"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_filename: Mapped[str | None] = mapped_column(String(512))
    extracted_text: Mapped[str] = mapped_column(Text)
    derived_profile: Mapped[dict | None] = mapped_column(JSONB)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    matching_profile: Mapped[MatchingProfile | None] = relationship(
        back_populates="cv", uselist=False, cascade="all, delete-orphan"
    )


class MatchingProfile(Base):
    """Editable matching profile (option c): user overrides on top of the derived baseline."""

    __tablename__ = "matching_profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cv_id: Mapped[int] = mapped_column(ForeignKey("cv.id", ondelete="CASCADE"), index=True)
    must_have_skills: Mapped[list | None] = mapped_column(JSONB, default=list)
    nice_to_have_skills: Mapped[list | None] = mapped_column(JSONB, default=list)
    dealbreakers: Mapped[list | None] = mapped_column(JSONB, default=list)
    min_seniority: Mapped[str | None] = mapped_column(String(64))
    notes: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow
    )

    cv: Mapped[CV] = relationship(back_populates="matching_profile")


class SearchQuery(Base):
    """A stored, editable search query bound to a modular source."""

    __tablename__ = "search_query"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(256))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    keywords: Mapped[str | None] = mapped_column(String(512))
    work_type: Mapped[str | None] = mapped_column(String(32))  # remote / hybrid / onsite
    location: Mapped[str | None] = mapped_column(String(256))
    source: Mapped[str] = mapped_column(String(64), index=True)  # registry key
    source_config: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    reference_url: Mapped[str | None] = mapped_column(Text)  # manual LinkedIn bookmark
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow
    )


class Job(Base):
    """A discovered job listing. Uniqueness enforced at the DB level for dedup."""

    __tablename__ = "job"
    __table_args__ = (
        UniqueConstraint("normalized_url", name="uq_job_normalized_url"),
        UniqueConstraint("source", "source_job_id", name="uq_job_source_sourceid"),
        UniqueConstraint("fingerprint", name="uq_job_fingerprint"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(64), index=True)
    source_job_id: Mapped[str | None] = mapped_column(String(256))
    url: Mapped[str | None] = mapped_column(Text)
    normalized_url: Mapped[str | None] = mapped_column(Text)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)

    title: Mapped[str] = mapped_column(String(512))
    company: Mapped[str | None] = mapped_column(String(256))
    location: Mapped[str | None] = mapped_column(String(256))
    description: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(16))
    # Human-readable salary range as the source stated it, e.g. "USD 90,000 – 120,000/year".
    salary: Mapped[str | None] = mapped_column(String(128))
    # Work arrangement: "remote" | "hybrid" | "onsite" | None (unknown).
    work_type: Mapped[str | None] = mapped_column(String(16), index=True)

    discovered_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status"), default=JobStatus.new, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow
    )

    analyses: Mapped[list[Analysis]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class Analysis(Base):
    """AI analysis of a job against a specific CV version. Cached by (job_id, cv_id)."""

    __tablename__ = "analysis"
    __table_args__ = (UniqueConstraint("job_id", "cv_id", name="uq_analysis_job_cv"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("job.id", ondelete="CASCADE"), index=True)
    cv_id: Mapped[int] = mapped_column(ForeignKey("cv.id", ondelete="CASCADE"), index=True)

    processing_status: Mapped[ProcessingStatus] = mapped_column(
        Enum(ProcessingStatus, name="processing_status"),
        default=ProcessingStatus.pending,
        index=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)

    detected_language: Mapped[str | None] = mapped_column(String(16))
    translated_summary: Mapped[str | None] = mapped_column(Text)
    match_score: Mapped[int | None] = mapped_column(Integer, index=True)
    explanation: Mapped[str | None] = mapped_column(Text)
    matching_skills: Mapped[list | None] = mapped_column(JSONB)
    missing_requirements: Mapped[list | None] = mapped_column(JSONB)
    # Per-dimension reasoning behind match_score: a list of
    # {"dimension": str, "score": int, "weight": float, "reason": str}. Lets the
    # dashboard explain WHY a job scored what it did. Null for pre-breakdown analyses.
    dimension_scores: Mapped[list | None] = mapped_column(JSONB)
    # Inferred posting location + applicant-eligibility verdict (advisory; does not affect
    # match_score). eligibility ∈ {worldwide, restricted, unclear}.
    posting_country: Mapped[str | None] = mapped_column(String(64))
    eligibility: Mapped[str | None] = mapped_column(String(16), index=True)
    eligibility_note: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    job: Mapped[Job] = relationship(back_populates="analyses")


class PromptTemplate(Base):
    """An editable prompt sent to the AI provider, stored and overridable via the UI."""

    __tablename__ = "prompt_template"

    key: Mapped[str] = mapped_column(String(32), primary_key=True)  # 'profile' | 'analyze'
    template: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow
    )


class CollectionRun(Base):
    """Record of each collection run for the dashboard's 'last search time + errors'."""

    __tablename__ = "collection_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    trigger: Mapped[str] = mapped_column(String(32), default="scheduled")  # scheduled|manual
    jobs_found: Mapped[int] = mapped_column(Integer, default=0)
    jobs_new: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[list | None] = mapped_column(JSONB, default=list)
