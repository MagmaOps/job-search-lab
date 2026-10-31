import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, update
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from jobsearch.models import CV, Analysis, Base, Job, ProcessingStatus
from jobsearch.services import insights_service


def _seed_cv(db):
    db.execute(update(CV).values(is_active=False))
    cv = CV(extracted_text="DevOps engineer", derived_profile={"skills": []}, is_active=True)
    db.add(cv)
    db.commit()
    return cv


def _seed_analysis(db, cv_id, missing, learning_gaps=None, job_title="J"):
    job = Job(source="remoteok", fingerprint="fp" + job_title + str(id(missing)),
              title=job_title, content_hash="ch" + job_title + str(id(missing)))
    db.add(job)
    db.flush()
    db.add(Analysis(
        job_id=job.id, cv_id=cv_id, processing_status=ProcessingStatus.done,
        match_score=50, missing_requirements=missing, learning_gaps=learning_gaps or [],
    ))
    db.commit()


# ── Aggregation / normalization ─────────────────────────────────────────────
def test_refresh_ranks_by_frequency_across_jobs(db):
    cv = _seed_cv(db)
    _seed_analysis(db, cv.id, ["Terraform", "Kubernetes"])
    _seed_analysis(db, cv.id, ["Terraform", "Ansible"])
    _seed_analysis(db, cv.id, ["Terraform"])
    snap = insights_service.refresh_insights(db)
    assert snap.jobs_analyzed == 3
    items = {i["skill"].lower(): i["count"] for i in snap.items}
    assert items["terraform"] == 3  # most asked → ranked first
    assert snap.items[0]["skill"].lower() == "terraform"
    assert items["kubernetes"] == 1 and items["ansible"] == 1


def test_refresh_merges_spelling_variants(db):
    cv = _seed_cv(db)
    _seed_analysis(db, cv.id, ["Kubernetes"])
    _seed_analysis(db, cv.id, ["k8s"])
    _seed_analysis(db, cv.id, ["KUBERNETES"])
    snap = insights_service.refresh_insights(db)
    # All three collapse into one ranked row with count 3.
    k = [i for i in snap.items if i["skill"].lower() in ("kubernetes", "k8s")]
    assert len(k) == 1
    assert k[0]["count"] == 3


def test_duplicate_skill_in_one_job_counts_once(db):
    cv = _seed_cv(db)
    _seed_analysis(db, cv.id, ["Terraform", "terraform", "TERRAFORM"])  # one job
    snap = insights_service.refresh_insights(db)
    tf = next(i for i in snap.items if i["skill"].lower() == "terraform")
    assert tf["count"] == 1


def test_severity_and_why_from_learning_gaps(db):
    cv = _seed_cv(db)
    _seed_analysis(
        db, cv.id, ["Terraform"],
        learning_gaps=[{"skill": "Terraform", "level": "basic", "why": "IaC is standard"}],
    )
    snap = insights_service.refresh_insights(db)
    tf = next(i for i in snap.items if i["skill"].lower() == "terraform")
    assert tf["severity"] == "basic"
    assert tf["why"] == "IaC is standard"


def test_basic_severity_outranks_average(db):
    cv = _seed_cv(db)
    _seed_analysis(db, cv.id, ["CI/CD"],
                   learning_gaps=[{"skill": "CI/CD", "level": "average", "why": "a"}])
    _seed_analysis(db, cv.id, ["CI/CD"],
                   learning_gaps=[{"skill": "CI/CD", "level": "basic", "why": "b"}])
    snap = insights_service.refresh_insights(db)
    cicd = next(i for i in snap.items if i["skill"].lower() == "ci/cd")
    assert cicd["severity"] == "basic"


def test_refresh_overwrites_previous_snapshot(db):
    cv = _seed_cv(db)
    _seed_analysis(db, cv.id, ["Terraform"])
    insights_service.refresh_insights(db)
    _seed_analysis(db, cv.id, ["Ansible"])
    snap = insights_service.refresh_insights(db)
    from jobsearch.models import Insights
    assert db.query(Insights).count() == 1  # single snapshot, overwritten not appended
    assert snap.jobs_analyzed == 2


def test_clear_requires_nothing_auto_deletes(db):
    cv = _seed_cv(db)
    _seed_analysis(db, cv.id, ["Terraform"])
    insights_service.refresh_insights(db)
    assert insights_service.get_insights(db) is not None
    assert insights_service.clear_insights(db) is True
    assert insights_service.get_insights(db) is None


def test_refresh_without_active_cv_returns_none(db):
    assert insights_service.refresh_insights(db) is None


# ── API ─────────────────────────────────────────────────────────────────────
@pytest.fixture()
def api_ctx():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    session = Session()
    from jobsearch.api import app
    from jobsearch.db import get_db
    app.dependency_overrides[get_db] = lambda: session
    try:
        yield TestClient(app), session
    finally:
        app.dependency_overrides.clear()
        session.close()


def test_api_insights_lifecycle(api_ctx):
    client, session = api_ctx
    cv = _seed_cv(session)
    _seed_analysis(session, cv.id, ["Terraform", "Kubernetes"])

    # Nothing computed yet.
    assert client.get("/insights").json() is None

    # Refresh computes + stores.
    r = client.post("/insights/refresh")
    assert r.status_code == 200
    body = r.json()
    assert body["jobs_analyzed"] == 1
    assert body["stale_cv"] is False
    assert any(i["skill"].lower() == "terraform" for i in body["items"])

    # GET returns the stored snapshot.
    assert client.get("/insights").json()["jobs_analyzed"] == 1

    # Clear deletes it.
    assert client.delete("/insights").status_code == 204
    assert client.get("/insights").json() is None


def test_api_insights_flags_stale_cv(api_ctx):
    client, session = api_ctx
    old_cv = _seed_cv(session)
    _seed_analysis(session, old_cv.id, ["Terraform"])
    client.post("/insights/refresh")

    # Upload a new CV → old snapshot kept, but flagged stale against the now-active CV.
    _seed_cv(session)  # deactivates old, new one active
    body = client.get("/insights").json()
    assert body is not None  # NOT auto-deleted
    assert body["stale_cv"] is True


def test_api_refresh_without_cv_is_400(api_ctx):
    client, _ = api_ctx
    assert client.post("/insights/refresh").status_code == 400
