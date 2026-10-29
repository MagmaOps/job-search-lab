"""Analysis pipeline: run the AI provider over jobs that need analysis.

Caching (design requirements 5 & 6):
- An analysis is keyed by (job_id, cv_id). If a done analysis exists for the active CV,
  reuse it — no AI call.
- A CV change means a new active cv_id, so existing jobs become eligible for a fresh run.
- Failures are stored with status=error + message + retry_count for later retry.
"""

from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..ai import get_provider, posting_guard, prompts
from ..models import Analysis, Job, ProcessingStatus
from . import prompt_service
from .cv_service import effective_profile, get_active_cv

MAX_RETRIES = 3

# Serializes analysis passes cluster-wide so two overlapping runs (the startup collection
# cycle and the interval queue-drain, or two worker replicas) can't both insert an Analysis
# for the same (job, cv) and trip the unique constraint.
_ANALYSIS_LOCK_KEY = 0x10B5_A1A1


def _try_analysis_lock(db: Session) -> bool:
    """Grab a session-scoped advisory lock for an analysis pass. True if acquired.

    No-ops to True on SQLite (tests), which has no advisory locks and no concurrency.
    """
    if db.bind is None or db.bind.dialect.name != "postgresql":
        return True
    return bool(db.execute(text("SELECT pg_try_advisory_lock(:k)"),
                           {"k": _ANALYSIS_LOCK_KEY}).scalar())


def _release_analysis_lock(db: Session) -> None:
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _ANALYSIS_LOCK_KEY})


def _guarded_description(job: Job) -> tuple[str, list[str]]:
    """Sanitize a job's description before it reaches the model (trust boundary)."""
    result = posting_guard.sanitize(job.description or "")
    return result.text, result.findings


def _with_guard_note(explanation: str | None, findings: list[str]) -> str | None:
    """Prepend a short integrity note to the explanation when the guard flagged anything."""
    if not findings:
        return explanation
    note = "⚠ Posting integrity: " + "; ".join(findings) + "."
    return f"{note}\n\n{explanation}" if explanation else note


def _pending_or_missing_job_ids(db: Session, cv_id: int, limit: int) -> list[int]:
    """Jobs with no done analysis for this CV (and under the retry cap)."""
    done_subq = select(Analysis.job_id).where(
        Analysis.cv_id == cv_id,
        Analysis.processing_status == ProcessingStatus.done,
    )
    exhausted_subq = select(Analysis.job_id).where(
        Analysis.cv_id == cv_id,
        Analysis.processing_status == ProcessingStatus.error,
        Analysis.retry_count >= MAX_RETRIES,
    )
    rows = db.execute(
        select(Job.id)
        .where(Job.id.not_in(done_subq))
        .where(Job.id.not_in(exhausted_subq))
        .order_by(Job.discovered_at.desc())
        .limit(limit)
    ).all()
    return [r[0] for r in rows]


def analyze_pending(db: Session, limit: int = 25) -> int:
    """Analyze up to `limit` jobs against the active CV. Returns count processed.

    Guarded by a cluster-wide advisory lock so concurrent passes don't double-insert an
    analysis row; if another pass holds the lock, this one is a no-op (the other does it).
    """
    cv = get_active_cv(db)
    if cv is None:
        return 0  # nothing to match against yet

    if not _try_analysis_lock(db):
        return 0  # another pass is already analyzing; let it do the work

    try:
        return _analyze_locked(db, cv, limit)
    finally:
        _release_analysis_lock(db)


def _analyze_locked(db: Session, cv, limit: int) -> int:
    provider = get_provider()
    profile = effective_profile(cv)
    analyze_template = prompt_service.get_template(db, prompts.ANALYZE)
    processed = 0

    for job_id in _pending_or_missing_job_ids(db, cv.id, limit):
        job = db.get(Job, job_id)
        if job is None:
            continue

        analysis = (
            db.query(Analysis)
            .filter(Analysis.job_id == job_id, Analysis.cv_id == cv.id)
            .one_or_none()
        )
        if analysis is None:
            analysis = Analysis(job_id=job_id, cv_id=cv.id)
            db.add(analysis)

        try:
            safe_description, findings = _guarded_description(job)
            result = provider.analyze_job(
                job_title=job.title,
                job_description=safe_description,
                job_language=job.language,
                cv_text=cv.extracted_text,
                effective_profile=profile,
                template=analyze_template,
            )
            analysis.processing_status = ProcessingStatus.done
            analysis.error_message = None
            analysis.detected_language = result.detected_language
            analysis.translated_summary = result.translated_summary
            analysis.match_score = result.match_score
            analysis.explanation = _with_guard_note(result.explanation, findings)
            analysis.matching_skills = result.matching_skills
            analysis.missing_requirements = result.missing_requirements
            analysis.dimension_scores = [d.as_dict() for d in result.dimension_scores]
            analysis.posting_country = result.posting_country
            analysis.eligibility = result.eligibility
            analysis.eligibility_note = result.eligibility_note
            analysis.model = result.model
            if result.detected_language and not job.language:
                job.language = result.detected_language
            processed += 1
        except Exception as exc:  # store the error for retry
            analysis.processing_status = ProcessingStatus.error
            analysis.error_message = str(exc)[:1000]
            analysis.retry_count = (analysis.retry_count or 0) + 1

        db.commit()

    return processed


def reanalyze_job(db: Session, job_id: int) -> bool:
    """Force a fresh analysis of one job against the active CV (manual re-analysis).

    Synchronous: runs the AI call in-process. Kept for callers that want the result back
    immediately (e.g. the manual-paste flow). The dashboard uses `enqueue_job` instead so
    the request returns at once and the worker does the work.
    """
    cv = get_active_cv(db)
    if cv is None:
        return False
    db.query(Analysis).filter(
        Analysis.job_id == job_id, Analysis.cv_id == cv.id
    ).delete()
    db.commit()
    return analyze_single(db, job_id) is not None


def enqueue_job(db: Session, job_id: int) -> bool:
    """Queue a job for (re)analysis against the active CV without running the AI now.

    Resets the (job, active-CV) analysis row to `pending` so the background worker's
    `analyze_pending` picks it up. The HTTP request returns immediately, and the work
    survives the browser tab closing because the worker — not the request — performs it.
    Returns False when there is no active CV or the job does not exist.
    """
    cv = get_active_cv(db)
    job = db.get(Job, job_id)
    if cv is None or job is None:
        return False
    analysis = (
        db.query(Analysis)
        .filter(Analysis.job_id == job_id, Analysis.cv_id == cv.id)
        .one_or_none()
    )
    if analysis is None:
        analysis = Analysis(job_id=job_id, cv_id=cv.id)
        db.add(analysis)
    # Reset to a clean pending state so a prior done/error result shows as "in progress".
    analysis.processing_status = ProcessingStatus.pending
    analysis.error_message = None
    analysis.retry_count = 0
    db.commit()
    return True


def enqueue_all_pending(db: Session) -> int:
    """Queue every job that has no completed analysis for the active CV. Returns the count.

    Like `enqueue_job` but for the whole backlog — the 'Analyze jobs vs CV' button. Creates
    a `pending` analysis row for each un-analyzed job so the worker processes them in the
    background; returns at once regardless of how many jobs there are.
    """
    cv = get_active_cv(db)
    if cv is None:
        return 0
    queued = 0
    for job_id in _pending_or_missing_job_ids(db, cv.id, limit=10_000):
        analysis = (
            db.query(Analysis)
            .filter(Analysis.job_id == job_id, Analysis.cv_id == cv.id)
            .one_or_none()
        )
        if analysis is None:
            db.add(Analysis(job_id=job_id, cv_id=cv.id,
                            processing_status=ProcessingStatus.pending))
            queued += 1
        elif analysis.processing_status != ProcessingStatus.done:
            analysis.processing_status = ProcessingStatus.pending
            analysis.error_message = None
            analysis.retry_count = 0
            queued += 1
    db.commit()
    return queued


def analyze_single(db: Session, job_id: int):
    cv = get_active_cv(db)
    job = db.get(Job, job_id)
    if cv is None or job is None:
        return None
    provider = get_provider()
    profile = effective_profile(cv)
    analyze_template = prompt_service.get_template(db, prompts.ANALYZE)
    analysis = Analysis(job_id=job_id, cv_id=cv.id)
    db.add(analysis)
    try:
        safe_description, findings = _guarded_description(job)
        result = provider.analyze_job(
            job_title=job.title,
            job_description=safe_description,
            job_language=job.language,
            cv_text=cv.extracted_text,
            effective_profile=profile,
            template=analyze_template,
        )
        analysis.processing_status = ProcessingStatus.done
        analysis.detected_language = result.detected_language
        analysis.translated_summary = result.translated_summary
        analysis.match_score = result.match_score
        analysis.explanation = _with_guard_note(result.explanation, findings)
        analysis.matching_skills = result.matching_skills
        analysis.missing_requirements = result.missing_requirements
        analysis.dimension_scores = [d.as_dict() for d in result.dimension_scores]
        analysis.posting_country = result.posting_country
        analysis.eligibility = result.eligibility
        analysis.eligibility_note = result.eligibility_note
        analysis.model = result.model
    except Exception as exc:
        analysis.processing_status = ProcessingStatus.error
        analysis.error_message = str(exc)[:1000]
        analysis.retry_count = 1
    db.commit()
    return analysis
