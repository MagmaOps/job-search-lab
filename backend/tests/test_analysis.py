from jobsearch.models import CV, Analysis, Job, MatchingProfile, ProcessingStatus
from sqlalchemy import update

from jobsearch.services import analysis_service


def _seed_cv(db, cv_id_skills):
    # Mirror production ingest: only one CV is active at a time.
    db.execute(update(CV).values(is_active=False))
    cv = CV(extracted_text="Experienced with kubernetes docker terraform aws",
            derived_profile={"skills": cv_id_skills, "seniority": "senior"},
            is_active=True)
    db.add(cv)
    db.flush()
    db.add(MatchingProfile(cv_id=cv.id, must_have_skills=["kubernetes"],
                           nice_to_have_skills=["terraform"], dealbreakers=["php"]))
    db.commit()
    return cv


def _seed_job(db, title="DevOps", desc="We use kubernetes and terraform on aws"):
    job = Job(source="remoteok", fingerprint="fp" + title, title=title,
              description=desc, content_hash="ch" + title)
    db.add(job)
    db.commit()
    return job


def test_stub_analysis_runs_and_caches(db):
    _seed_cv(db, ["kubernetes", "terraform"])
    _seed_job(db)

    processed = analysis_service.analyze_pending(db)
    assert processed == 1
    a = db.query(Analysis).one()
    assert a.processing_status == ProcessingStatus.done
    assert a.match_score is not None
    assert "kubernetes" in (a.matching_skills or [])

    # Second run reuses the cached analysis → nothing processed.
    assert analysis_service.analyze_pending(db) == 0


def test_dealbreaker_caps_score(db):
    _seed_cv(db, ["kubernetes"])
    _seed_job(db, title="PhpDev", desc="php php kubernetes")
    analysis_service.analyze_pending(db)
    a = db.query(Analysis).one()
    assert a.match_score <= 10


def test_no_active_cv_processes_nothing(db):
    _seed_job(db)
    assert analysis_service.analyze_pending(db) == 0


def test_error_retry_cap(db):
    _seed_cv(db, ["kubernetes"])
    job = _seed_job(db)
    # Simulate an exhausted error analysis; it should not be retried.
    db.add(Analysis(job_id=job.id, cv_id=db.query(CV).one().id,
                    processing_status=ProcessingStatus.error, retry_count=3))
    db.commit()
    assert analysis_service.analyze_pending(db) == 0
