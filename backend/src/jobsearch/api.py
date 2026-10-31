"""FastAPI application: all REST endpoints from docs/design.md section 7."""

from __future__ import annotations

from datetime import datetime

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .dedup import content_hash, fingerprint, normalize_url
from .models import (
    CV,
    Analysis,
    Application,
    Job,
    JobStatus,
    MatchingProfile,
    ProcessingStatus,
    SearchQuery,
)
from .schemas import (
    ApplicationOut,
    ApplicationUpdate,
    CVOut,
    JobDetailOut,
    JobOut,
    JobPatch,
    ManualJobIn,
    ProfileOut,
    ProfileUpdate,
    PromptOut,
    PromptUpdate,
    QueryIn,
    QueryOut,
    QueryUpdate,
    StatusOut,
)
from .ai import prompts
from .services import (
    analysis_service,
    application_service,
    collect_service,
    cv_service,
    prompt_service,
)
from .sources import source_names
from .sources.base import normalize_work_type

settings = get_settings()
app = FastAPI(title="Job Search Lab", version="1.2.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Health ────────────────────────────────────────────────────────────────
@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.get("/readyz")
def readyz(db: Session = Depends(get_db)) -> dict:
    db.execute(text("SELECT 1"))
    return {"status": "ready"}


# ── Jobs ──────────────────────────────────────────────────────────────────
def _active_cv_id(db: Session) -> int | None:
    cv = cv_service.get_active_cv(db)
    return cv.id if cv else None


@app.get("/jobs", response_model=list[JobOut])
def list_jobs(
    db: Session = Depends(get_db),
    min_score: int | None = Query(None, ge=0, le=100),
    location: str | None = None,
    company: str | None = None,
    language: str | None = None,
    work_type: str | None = None,
    eligibility: str | None = None,
    status: str | None = None,
    has_salary: bool | None = None,
    has_application: bool | None = None,
    sort: str = "score",
) -> list[JobOut]:
    cv_id = _active_cv_id(db)
    q = (
        db.query(Job, Analysis, Application)
        .outerjoin(
            Analysis,
            (Analysis.job_id == Job.id) & (Analysis.cv_id == cv_id),
        )
        .outerjoin(
            Application,
            (Application.job_id == Job.id) & (Application.cv_id == cv_id),
        )
    )

    # Job ids that have a completed analysis against some OTHER (older) CV — used to tell
    # "outdated" (analyzed before, but not for the current CV) from "never analyzed".
    outdated_ids: set[int] = set()
    if cv_id is not None:
        rows_other = db.execute(
            select(Analysis.job_id)
            .where(Analysis.cv_id != cv_id)
            .where(Analysis.processing_status == ProcessingStatus.done)
            .distinct()
        ).all()
        outdated_ids = {r[0] for r in rows_other}
    if location:
        q = q.filter(Job.location.ilike(f"%{location}%"))
    if company:
        q = q.filter(Job.company.ilike(f"%{company}%"))
    if language:
        q = q.filter(Job.language == language)
    if work_type:
        q = q.filter(Job.work_type == work_type)
    if eligibility:
        q = q.filter(Analysis.eligibility == eligibility)
    if status:
        q = q.filter(Job.status == JobStatus(status))
    if min_score is not None:
        q = q.filter(Analysis.match_score >= min_score)
    if has_salary is not None:
        # "Present" = a non-null, non-blank salary string. has_salary=false → the inverse.
        salary_present = (Job.salary.isnot(None)) & (func.trim(Job.salary) != "")
        q = q.filter(salary_present if has_salary else ~salary_present)
    if has_application is not None:
        # "Has application" = an application row exists for the active CV (any status).
        app_present = Application.id.isnot(None)
        q = q.filter(app_present if has_application else ~app_present)

    rows = q.all()

    out: list[JobOut] = []
    for job, analysis, application in rows:
        if analysis and analysis.processing_status == ProcessingStatus.pending:
            # Queued (manual re-analyze or backlog) and not yet processed by the worker.
            state = "pending"
        elif analysis and analysis.processing_status == ProcessingStatus.done and analysis.stale:
            # Scored, but the description changed since — needs a manual re-analyze.
            state = "stale"
        elif analysis and analysis.processing_status == ProcessingStatus.done:
            state = "current"
        elif analysis and analysis.processing_status == ProcessingStatus.error:
            state = "error"
        elif job.id in outdated_ids:
            state = "outdated"
        else:
            state = "none"
        # Application indicator vs the active CV: none | pending | done | error.
        app_state = application.processing_status.value if application else "none"
        out.append(
            JobOut(
                id=job.id,
                source=job.source,
                url=job.url,
                title=job.title,
                company=job.company,
                location=job.location,
                language=job.language,
                salary=job.salary,
                work_type=job.work_type,
                status=job.status.value,
                discovered_at=job.discovered_at,
                analysis_state=state,
                application_state=app_state,
                match_score=analysis.match_score if analysis else None,
                translated_summary=analysis.translated_summary if analysis else None,
                explanation=analysis.explanation if analysis else None,
                matching_skills=analysis.matching_skills if analysis else None,
                missing_requirements=analysis.missing_requirements if analysis else None,
                dimension_scores=analysis.dimension_scores if analysis else None,
                learning_gaps=analysis.learning_gaps if analysis else None,
                posting_country=analysis.posting_country if analysis else None,
                eligibility=analysis.eligibility if analysis else None,
                eligibility_note=analysis.eligibility_note if analysis else None,
            )
        )

    reverse = True
    if sort == "date":
        out.sort(key=lambda j: j.discovered_at, reverse=True)
    else:  # score, None last
        out.sort(key=lambda j: (j.match_score is None, -(j.match_score or 0)))
    return out


@app.get("/jobs/{job_id}", response_model=JobDetailOut)
def get_job(job_id: int, db: Session = Depends(get_db)) -> Job:
    """Full single job including the heavy description. Fetched on demand (e.g. when the
    dashboard opens the description editor) so the list payload stays lean."""
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@app.patch("/jobs/{job_id}", response_model=JobOut)
def update_job(
    job_id: int, body: JobPatch, db: Session = Depends(get_db)
) -> JobOut:
    """Update a job's user-editable fields (status, salary, and/or description). Only the
    fields present in the request are changed; sending salary="" clears a stored salary.

    Pasting a fuller `description` REPLACES the stored (often truncated) one. It does not
    auto-re-analyze — it drops the current-CV analysis so the dashboard indicator flips to
    "not current", prompting a manual Re-analyze against the fuller text when you choose."""
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    fields = body.model_dump(exclude_unset=True)
    if "status" in fields and fields["status"] is not None:
        try:
            job.status = JobStatus(fields["status"])
        except ValueError:
            raise HTTPException(422, f"Invalid status '{fields['status']}'")
    if "salary" in fields:
        salary = (fields["salary"] or "").strip()
        job.salary = salary or None  # empty string clears it
    if "description" in fields and fields["description"] is not None:
        job.description = fields["description"]
        # Refresh the content hash so dedup/change-detection sees the new text.
        job.content_hash = content_hash(job.title, job.description)
        # Mark the current-CV analysis stale rather than deleting it: the score stays
        # visible but flagged, and because the row is still `done` the background worker
        # will NOT silently re-score it. The user re-analyzes manually when ready.
        cv_id = _active_cv_id(db)
        if cv_id is not None:
            db.query(Analysis).filter(
                Analysis.job_id == job.id, Analysis.cv_id == cv_id
            ).update({Analysis.stale: True})

    db.commit()
    db.refresh(job)
    return JobOut(
        id=job.id, source=job.source, url=job.url, title=job.title,
        company=job.company, location=job.location, language=job.language,
        salary=job.salary, work_type=job.work_type,
        status=job.status.value, discovered_at=job.discovered_at,
    )


@app.post("/jobs/manual", response_model=JobOut, status_code=201)
def add_manual_job(body: ManualJobIn, db: Session = Depends(get_db)) -> JobOut:
    """Paste a job URL (e.g. from LinkedIn) to store + analyze it."""
    norm = normalize_url(body.url)
    if norm and db.query(Job).filter(Job.normalized_url == norm).first():
        raise HTTPException(409, "A job with this URL already exists.")
    title = body.title or body.url
    job = Job(
        source="manual",
        url=body.url,
        normalized_url=norm,
        fingerprint=fingerprint("manual", body.company, title, body.location),
        title=title,
        company=body.company,
        location=body.location,
        description=body.description,
        salary=body.salary,
        work_type=normalize_work_type(body.work_type),
        content_hash=content_hash(title, body.description),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    analysis = analysis_service.analyze_single(db, job.id)
    return JobOut(
        id=job.id, source=job.source, url=job.url, title=job.title,
        company=job.company, location=job.location, language=job.language,
        salary=job.salary, work_type=job.work_type,
        status=job.status.value, discovered_at=job.discovered_at,
        match_score=analysis.match_score if analysis else None,
        translated_summary=analysis.translated_summary if analysis else None,
        explanation=analysis.explanation if analysis else None,
        matching_skills=analysis.matching_skills if analysis else None,
        missing_requirements=analysis.missing_requirements if analysis else None,
        dimension_scores=analysis.dimension_scores if analysis else None,
        learning_gaps=analysis.learning_gaps if analysis else None,
        posting_country=analysis.posting_country if analysis else None,
        eligibility=analysis.eligibility if analysis else None,
        eligibility_note=analysis.eligibility_note if analysis else None,
    )


@app.post("/jobs/{job_id}/reanalyze")
def reanalyze(job_id: int, db: Session = Depends(get_db)) -> dict:
    """Queue a single job for re-analysis. Returns immediately; the worker does the work,
    so it completes even if the browser tab is closed. Poll /jobs to see it go
    pending → current."""
    ok = analysis_service.enqueue_job(db, job_id)
    if not ok:
        raise HTTPException(400, "No active CV or job not found.")
    return {"status": "queued", "job_id": job_id}


# ── Applications (tailored cover letter + CV summary) ───────────────────────
def _application_out(app_row: Application) -> ApplicationOut:
    return ApplicationOut(
        job_id=app_row.job_id,
        cv_id=app_row.cv_id,
        processing_status=app_row.processing_status.value,
        error_message=app_row.error_message,
        cover_letter_md=app_row.cover_letter_md,
        cv_summary_md=app_row.cv_summary_md,
        reviewer_notes=app_row.reviewer_notes,
        model=app_row.model,
        updated_at=app_row.updated_at,
    )


@app.get("/jobs/{job_id}/application", response_model=ApplicationOut | None)
def get_application(job_id: int, db: Session = Depends(get_db)) -> ApplicationOut | None:
    """Current application for this job against the active CV (null if none generated)."""
    app_row = application_service.get_application(db, job_id)
    return _application_out(app_row) if app_row else None


@app.post("/jobs/{job_id}/application", response_model=ApplicationOut)
def generate_application(job_id: int, db: Session = Depends(get_db)) -> ApplicationOut:
    """Queue (or regenerate) a tailored application for this job against the active CV.

    Returns immediately with the row in `pending`; the worker drains it. Poll this endpoint
    to see it flip pending → done, so the work survives the browser tab closing.
    """
    ok = application_service.enqueue_application(db, job_id)
    if not ok:
        raise HTTPException(400, "No active CV or job not found.")
    app_row = application_service.get_application(db, job_id)
    return _application_out(app_row)


@app.patch("/jobs/{job_id}/application", response_model=ApplicationOut)
def update_application(
    job_id: int, body: ApplicationUpdate, db: Session = Depends(get_db)
) -> ApplicationOut:
    """Save the user's edits to a generated application (cover letter / CV summary)."""
    app_row = application_service.get_application(db, job_id)
    if app_row is None:
        raise HTTPException(404, "No application for this job and the active CV.")
    fields = body.model_dump(exclude_unset=True)
    if "cover_letter_md" in fields:
        app_row.cover_letter_md = fields["cover_letter_md"]
    if "cv_summary_md" in fields:
        app_row.cv_summary_md = fields["cv_summary_md"]
    db.commit()
    db.refresh(app_row)
    return _application_out(app_row)


@app.post("/analyze")
def analyze(db: Session = Depends(get_db)) -> dict:
    """Queue all un-analyzed stored jobs for scoring against the active CV.

    This is the action to run after uploading a new CV. It returns immediately; the worker
    scores the backlog in the background (so closing the page does not stop it). Jobs with
    a cached up-to-date analysis are not re-queued.
    """
    if cv_service.get_active_cv(db) is None:
        raise HTTPException(400, "No active CV. Upload a CV first.")
    queued = analysis_service.enqueue_all_pending(db)
    return {"queued": queued}


@app.post("/jobs/purge-irrelevant")
def purge_irrelevant(db: Session = Depends(get_db)) -> dict:
    """One-time cleanup: delete stored jobs whose title is not DevOps-relevant.

    Useful to clear a backlog collected before the relevance filter existed. Manual jobs
    are preserved. Destructive — returns the list of removed titles.
    """
    return collect_service.purge_irrelevant_jobs(db)


# ── Queries ───────────────────────────────────────────────────────────────
@app.get("/queries", response_model=list[QueryOut])
def list_queries(db: Session = Depends(get_db)) -> list[SearchQuery]:
    return db.query(SearchQuery).order_by(SearchQuery.id).all()


@app.post("/queries", response_model=QueryOut, status_code=201)
def create_query(body: QueryIn, db: Session = Depends(get_db)) -> SearchQuery:
    q = SearchQuery(**body.model_dump())
    db.add(q)
    db.commit()
    db.refresh(q)
    return q


@app.patch("/queries/{query_id}", response_model=QueryOut)
def update_query(
    query_id: int, body: QueryUpdate, db: Session = Depends(get_db)
) -> SearchQuery:
    q = db.get(SearchQuery, query_id)
    if not q:
        raise HTTPException(404, "Query not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(q, k, v)
    db.commit()
    db.refresh(q)
    return q


@app.delete("/queries/{query_id}", status_code=204)
def delete_query(query_id: int, db: Session = Depends(get_db)) -> None:
    q = db.get(SearchQuery, query_id)
    if not q:
        raise HTTPException(404, "Query not found")
    db.delete(q)
    db.commit()


@app.post("/queries/{query_id}/run")
def run_query_now(query_id: int, db: Session = Depends(get_db)) -> dict:
    """Manual trigger. Runs full collection, then analysis."""
    run = collect_service.run_collection(db, trigger="manual")
    analyzed = analysis_service.analyze_pending(db)
    return {
        "jobs_found": run.jobs_found,
        "jobs_new": run.jobs_new,
        "analyzed": analyzed,
        "errors": run.errors,
    }


@app.get("/sources")
def list_sources() -> dict:
    return {"sources": source_names()}


# ── CV / profile ──────────────────────────────────────────────────────────
@app.get("/cv", response_model=CVOut | None)
def get_cv(db: Session = Depends(get_db)) -> CV | None:
    return cv_service.get_active_cv(db)


@app.post("/cv", response_model=CVOut, status_code=201)
async def upload_cv(
    file: UploadFile = File(...), db: Session = Depends(get_db)
) -> CV:
    data = await file.read()
    try:
        return cv_service.ingest_cv(db, file.filename or "cv", data)
    except cv_service.UnsupportedFileError as exc:
        raise HTTPException(415, str(exc))
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@app.get("/profile", response_model=ProfileOut | None)
def get_profile(db: Session = Depends(get_db)) -> MatchingProfile | None:
    cv = cv_service.get_active_cv(db)
    return cv.matching_profile if cv else None


@app.patch("/profile", response_model=ProfileOut)
def update_profile(body: ProfileUpdate, db: Session = Depends(get_db)) -> MatchingProfile:
    cv = cv_service.get_active_cv(db)
    if not cv or not cv.matching_profile:
        raise HTTPException(404, "No active CV / matching profile.")
    mp = cv.matching_profile
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(mp, k, v)
    db.commit()
    db.refresh(mp)
    return mp


# ── Prompts (editable AI templates) ─────────────────────────────────────────
@app.get("/prompts", response_model=list[PromptOut])
def list_prompts(db: Session = Depends(get_db)) -> list[dict]:
    return prompt_service.list_prompts(db)


@app.put("/prompts/{key}", response_model=PromptOut)
def update_prompt(key: str, body: PromptUpdate, db: Session = Depends(get_db)) -> dict:
    if key not in prompts.SPECS:
        raise HTTPException(404, f"Unknown prompt '{key}'.")
    try:
        prompt_service.set_template(db, key, body.template)
    except prompts.PromptValidationError as exc:
        raise HTTPException(422, str(exc))
    return next(p for p in prompt_service.list_prompts(db) if p["key"] == key)


@app.post("/prompts/{key}/reset", response_model=PromptOut)
def reset_prompt(key: str, db: Session = Depends(get_db)) -> dict:
    if key not in prompts.SPECS:
        raise HTTPException(404, f"Unknown prompt '{key}'.")
    prompt_service.reset_template(db, key)
    return next(p for p in prompt_service.list_prompts(db) if p["key"] == key)


# ── Status ────────────────────────────────────────────────────────────────
@app.get("/status", response_model=StatusOut)
def status(db: Session = Depends(get_db)) -> StatusOut:
    run = collect_service.last_run(db)
    jobs_total = db.query(func.count(Job.id)).scalar() or 0
    jobs_new = (
        db.query(func.count(Job.id)).filter(Job.status == JobStatus.new).scalar() or 0
    )
    analyzed = (
        db.query(func.count(Analysis.id))
        .filter(Analysis.processing_status == ProcessingStatus.done)
        .scalar()
        or 0
    )
    return StatusOut(
        last_run_at=run.started_at if run else None,
        last_run_trigger=run.trigger if run else None,
        jobs_total=jobs_total,
        jobs_new=jobs_new,
        jobs_analyzed=analyzed,
        errors=(run.errors if run and run.errors else []),
        ai_enabled=settings.ai_enabled,
    )
