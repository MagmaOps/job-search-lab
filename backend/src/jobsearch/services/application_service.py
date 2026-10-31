"""Application-generation pipeline: tailored cover letter + CV summary per job.

Mirrors analysis_service exactly (design requirements 5 & 6):
- An application is keyed by (job_id, cv_id). A done application for the active CV is
  reused — no AI call.
- A CV change means a new active cv_id, so a job becomes eligible for a fresh draft.
- Generation is queued (`pending`); the background worker drains it, so the work survives
  the browser tab closing.
- Failures are stored with status=error + message + retry_count for later retry.
- The posting is sanitized via posting_guard before it reaches the model (trust boundary).
- Grounding is the provider's job; the stub stays faithful offline so tests need no tokens.
"""

from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..ai import get_provider, posting_guard, prompts
from ..models import Application, Job, ProcessingStatus
from . import prompt_service
from .cv_service import effective_profile, get_active_cv

MAX_RETRIES = 3

# Cluster-wide lock so two overlapping generation passes can't both insert an Application
# for the same (job, cv) and trip the unique constraint. Distinct from the analysis lock.
_APPLICATION_LOCK_KEY = 0x10B5_A2A2


def _try_application_lock(db: Session) -> bool:
    """Grab a session-scoped advisory lock for a generation pass. True if acquired.

    No-ops to True on SQLite (tests), which has no advisory locks and no concurrency.
    """
    if db.bind is None or db.bind.dialect.name != "postgresql":
        return True
    return bool(db.execute(text("SELECT pg_try_advisory_lock(:k)"),
                           {"k": _APPLICATION_LOCK_KEY}).scalar())


def _release_application_lock(db: Session) -> None:
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _APPLICATION_LOCK_KEY})


def _guarded_description(job: Job) -> str:
    """Sanitize a job's description before it reaches the model (trust boundary)."""
    return posting_guard.sanitize(job.description or "").text


def _pending_application_job_ids(db: Session, cv_id: int, limit: int) -> list[int]:
    """Jobs with an application row queued (`pending`) for this CV and under the retry cap.

    Unlike analysis, generation is opt-in per job (the user clicks 'Generate application'),
    so we only process rows the user explicitly queued — never the whole backlog.
    """
    exhausted_subq = select(Application.job_id).where(
        Application.cv_id == cv_id,
        Application.processing_status == ProcessingStatus.error,
        Application.retry_count >= MAX_RETRIES,
    )
    rows = db.execute(
        select(Application.job_id)
        .where(Application.cv_id == cv_id)
        .where(Application.processing_status == ProcessingStatus.pending)
        .where(Application.job_id.not_in(exhausted_subq))
        .order_by(Application.updated_at.desc())
        .limit(limit)
    ).all()
    return [r[0] for r in rows]


def enqueue_application(db: Session, job_id: int) -> bool:
    """Queue a job for (re)generation against the active CV without running the AI now.

    Resets the (job, active-CV) application row to `pending` so the worker's
    `generate_pending` picks it up. Returns immediately; the work survives the tab closing.
    Returns False when there is no active CV or the job does not exist.
    """
    cv = get_active_cv(db)
    job = db.get(Job, job_id)
    if cv is None or job is None:
        return False
    application = (
        db.query(Application)
        .filter(Application.job_id == job_id, Application.cv_id == cv.id)
        .one_or_none()
    )
    if application is None:
        application = Application(job_id=job_id, cv_id=cv.id)
        db.add(application)
    # Reset to a clean pending state so a prior done/error result shows as "in progress".
    application.processing_status = ProcessingStatus.pending
    application.error_message = None
    application.retry_count = 0
    db.commit()
    return True


def get_application(db: Session, job_id: int) -> Application | None:
    """Return the current application for a job against the active CV, if any."""
    cv = get_active_cv(db)
    if cv is None:
        return None
    return (
        db.query(Application)
        .filter(Application.job_id == job_id, Application.cv_id == cv.id)
        .one_or_none()
    )


def generate_pending(db: Session, limit: int = 10) -> int:
    """Generate applications for up to `limit` queued jobs. Returns count processed.

    Guarded by a cluster-wide advisory lock so concurrent passes don't double-insert an
    application row; if another pass holds the lock, this one is a no-op.
    """
    cv = get_active_cv(db)
    if cv is None:
        return 0

    if not _try_application_lock(db):
        return 0

    try:
        return _generate_locked(db, cv, limit)
    finally:
        _release_application_lock(db)


def _generate_locked(db: Session, cv, limit: int) -> int:
    provider = get_provider()
    profile = effective_profile(cv)
    draft_template = prompt_service.get_template(db, prompts.APPLICATION)
    review_template = prompt_service.get_template(db, prompts.APPLICATION_REVIEW)
    revise_template = prompt_service.get_template(db, prompts.APPLICATION_REVISE)
    processed = 0

    for job_id in _pending_application_job_ids(db, cv.id, limit):
        job = db.get(Job, job_id)
        if job is None:
            continue

        application = (
            db.query(Application)
            .filter(Application.job_id == job_id, Application.cv_id == cv.id)
            .one_or_none()
        )
        if application is None:
            application = Application(job_id=job_id, cv_id=cv.id)
            db.add(application)

        try:
            safe_description = _guarded_description(job)
            draft = provider.generate_application(
                job_title=job.title,
                job_description=safe_description,
                cv_text=cv.extracted_text,
                effective_profile=profile,
                draft_template=draft_template,
                review_template=review_template,
                revise_template=revise_template,
            )
            application.processing_status = ProcessingStatus.done
            application.error_message = None
            application.cover_letter_md = draft.cover_letter_md
            application.cv_summary_md = draft.cv_summary_md
            application.cv_full_md = draft.cv_full_md
            application.reviewer_notes = draft.reviewer_notes
            application.model = draft.model
            processed += 1
        except Exception as exc:  # store the error for retry
            application.processing_status = ProcessingStatus.error
            application.error_message = str(exc)[:1000]
            application.retry_count = (application.retry_count or 0) + 1

        db.commit()

    return processed
