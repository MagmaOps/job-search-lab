"""Truncated-description handling + fully manual jobs."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, update
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from jobsearch.models import CV, Analysis, Base, Job, MatchingProfile, ProcessingStatus
from jobsearch.services import analysis_service
from jobsearch.services.ingest_service import ingest_job, looks_truncated
from jobsearch.sources.base import RawJob

FULL = "We run kubernetes and terraform on aws. " * 45  # ~1800 chars, a real posting


def _raw(**kw) -> RawJob:
    base = {"title": "DevOps Engineer", "source": "remoteok", "url": "https://x.io/j/1",
            "company": "Acme", "location": "Remote", "description": FULL}
    base.update(kw)
    return RawJob(**base)


def _seed_cv(db):
    db.execute(update(CV).values(is_active=False))
    cv = CV(extracted_text="Experienced with kubernetes terraform aws",
            derived_profile={"skills": ["kubernetes"], "seniority": "senior"},
            is_active=True)
    db.add(cv)
    db.flush()
    db.add(MatchingProfile(cv_id=cv.id, must_have_skills=["kubernetes"]))
    db.commit()
    return cv


# ── Heuristic ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize("text", [
    None,
    "",
    "Short teaser about a DevOps role.",
    FULL + " Read more",
    FULL + "…",
    FULL + " [...]",
])
def test_looks_truncated_flags_teasers(text):
    assert looks_truncated(text)


def test_full_posting_is_not_truncated():
    assert not looks_truncated(FULL)


# ── Ingest + analysis queue ─────────────────────────────────────────────────
def test_truncated_job_is_flagged_and_not_analyzed(db):
    _seed_cv(db)
    ingest_job(db, _raw(url="https://x.io/j/1", description="Teaser only..."))
    ingest_job(db, _raw(url="https://x.io/j/2", title="SRE", description=FULL))
    db.commit()

    flagged = db.query(Job).filter(Job.url == "https://x.io/j/1").one()
    assert flagged.description_incomplete is True

    assert analysis_service.analyze_pending(db) == 1  # only the complete one
    assert db.query(Analysis).one().job_id != flagged.id
    # The backlog button doesn't queue it either.
    assert analysis_service.enqueue_all_pending(db) == 0


def test_user_description_survives_recollection(db):
    ingest_job(db, _raw(description="Teaser only..."))
    db.commit()
    job = db.query(Job).one()
    # User pastes the full posting (what PATCH /jobs/{id} does).
    job.description = FULL
    job.description_manual = True
    job.description_incomplete = False
    db.commit()

    # Next collection returns the same teaser again — must not clobber the user's text.
    assert ingest_job(db, _raw(description="Teaser only...")) == "skipped"
    db.commit()
    job = db.query(Job).one()
    assert job.description == FULL
    assert job.description_incomplete is False


def test_changed_feed_content_recomputes_flag(db):
    ingest_job(db, _raw(description="Teaser only..."))
    db.commit()
    assert ingest_job(db, _raw(description=FULL)) == "updated"
    db.commit()
    assert db.query(Job).one().description_incomplete is False


# ── API ─────────────────────────────────────────────────────────────────────
@pytest.fixture()
def api_ctx():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False, future=True)()

    from jobsearch.api import app
    from jobsearch.db import get_db

    app.dependency_overrides[get_db] = lambda: session
    try:
        yield TestClient(app), session
    finally:
        app.dependency_overrides.clear()
        session.close()


def test_api_pasting_description_clears_flag_and_lets_worker_score(api_ctx):
    client, session = api_ctx
    _seed_cv(session)
    ingest_job(session, _raw(description="Teaser only..."))
    session.commit()
    job = session.query(Job).one()

    listed = client.get("/jobs").json()[0]
    assert listed["description_incomplete"] is True
    assert listed["analysis_state"] == "incomplete"
    assert client.get("/jobs", params={"description_incomplete": "true"}).json()
    assert client.get("/jobs", params={"description_incomplete": "false"}).json() == []

    # Re-analyze is refused while incomplete (the worker would never pick it up).
    assert client.post(f"/jobs/{job.id}/reanalyze").status_code == 409

    r = client.patch(f"/jobs/{job.id}", json={"description": FULL})
    assert r.status_code == 200
    assert r.json()["description_incomplete"] is False
    assert analysis_service.analyze_pending(session) == 1


def test_api_mark_complete_override(api_ctx):
    client, session = api_ctx
    ingest_job(session, _raw(description="Short but genuinely complete posting."))
    session.commit()
    job = session.query(Job).one()

    r = client.patch(f"/jobs/{job.id}", json={"description_incomplete": False})
    assert r.json()["description_incomplete"] is False
    r = client.patch(f"/jobs/{job.id}", json={"description_incomplete": True})
    assert r.json()["description_incomplete"] is True


def test_api_add_fully_manual_job_queues_analysis(api_ctx):
    client, session = api_ctx
    _seed_cv(session)
    r = client.post("/jobs/manual", json={
        "title": "Platform Engineer", "company": "Globex", "location": "Berlin",
        "work_type": "Remote", "salary": "EUR 80k", "description": "Short but mine.",
    })
    assert r.status_code == 201
    body = r.json()
    assert body["source"] == "manual"
    assert body["url"] is None
    assert body["work_type"] == "remote"
    # A user-written description is trusted even when short.
    assert body["description_incomplete"] is False
    assert body["analysis_state"] == "pending"
    analysis = session.query(Analysis).one()
    assert analysis.processing_status == ProcessingStatus.pending

    # Same title/company/location again → clean 409, not a 500 from the unique constraint.
    dup = client.post("/jobs/manual", json={
        "title": "Platform Engineer", "company": "Globex", "location": "Berlin",
    })
    assert dup.status_code == 409


def test_api_manual_job_without_description_is_incomplete(api_ctx):
    client, session = api_ctx
    _seed_cv(session)
    r = client.post("/jobs/manual", json={"url": "https://boards.example/jobs/42"})
    assert r.status_code == 201
    assert r.json()["title"] == "https://boards.example/jobs/42"
    assert r.json()["description_incomplete"] is True
    assert session.query(Analysis).count() == 0


def test_api_manual_job_needs_title_or_url(api_ctx):
    client, _ = api_ctx
    assert client.post("/jobs/manual", json={"company": "Acme"}).status_code == 422
