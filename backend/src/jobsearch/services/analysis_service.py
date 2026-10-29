"""Analysis pipeline: run the AI provider over jobs that need analysis.

Caching (design requirements 5 & 6):
- An analysis is keyed by (job_id, cv_id). If a done analysis exists for the active CV,
  reuse it — no AI call.
- A CV change means a new active cv_id, so existing jobs become eligible for a fresh run.
- Failures are stored with status=error + message + retry_count for later retry.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ai import get_provider, prompts
from ..models import Analysis, Job, ProcessingStatus
from . import prompt_service
from .cv_service import effective_profile, get_active_cv

MAX_RETRIES = 3


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
    """Analyze up to `limit` jobs against the active CV. Returns count processed."""
    cv = get_active_cv(db)
    if cv is None:
        return 0  # nothing to match against yet

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
            result = provider.analyze_job(
                job_title=job.title,
                job_description=job.description or "",
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
            analysis.explanation = result.explanation
            analysis.matching_skills = result.matching_skills
            analysis.missing_requirements = result.missing_requirements
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
    """Force a fresh analysis of one job against the active CV (manual re-analysis)."""
    cv = get_active_cv(db)
    if cv is None:
        return False
    db.query(Analysis).filter(
        Analysis.job_id == job_id, Analysis.cv_id == cv.id
    ).delete()
    db.commit()
    return analyze_single(db, job_id) is not None


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
        result = provider.analyze_job(
            job_title=job.title,
            job_description=job.description or "",
            job_language=job.language,
            cv_text=cv.extracted_text,
            effective_profile=profile,
            template=analyze_template,
        )
        analysis.processing_status = ProcessingStatus.done
        analysis.detected_language = result.detected_language
        analysis.translated_summary = result.translated_summary
        analysis.match_score = result.match_score
        analysis.explanation = result.explanation
        analysis.matching_skills = result.matching_skills
        analysis.missing_requirements = result.missing_requirements
        analysis.model = result.model
    except Exception as exc:
        analysis.processing_status = ProcessingStatus.error
        analysis.error_message = str(exc)[:1000]
        analysis.retry_count = 1
    db.commit()
    return analysis
