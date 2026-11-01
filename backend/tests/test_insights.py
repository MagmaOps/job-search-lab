import itertools

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


_JOB_SEQ = itertools.count(1)


def _seed_analysis(db, cv_id, missing, learning_gaps=None, job_title="J"):
    n = next(_JOB_SEQ)  # guaranteed-unique per seeded job (fingerprint is UNIQUE)
    job = Job(source="remoteok", fingerprint=f"fp{n}",
              title=f"{job_title}{n}", content_hash=f"ch{n}")
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


# ── AI semantic canonicalization (Part A) ───────────────────────────────────
class _FakeProvider:
    """Stands in for the AI provider: maps labels via a fixed canonical table."""

    model = "fake"

    def __init__(self, table):
        self._table = table

    def canonicalize_skills(self, labels, template=None):
        # Return a mapping only for labels we know; unknown ones fall back to themselves.
        return {lbl: self._table.get(lbl, lbl) for lbl in labels}


def _patch_provider(monkeypatch, provider):
    import jobsearch.services.insights_service as svc
    monkeypatch.setattr(svc, "get_provider", lambda: provider)


def test_ai_grouping_merges_semantic_variants(db, monkeypatch):
    cv = _seed_cv(db)
    # Three different surface forms of the same skill, each in a separate job.
    _seed_analysis(db, cv.id, ["Linux"])
    _seed_analysis(db, cv.id, ["Linux (not explicitly evidenced in CV)"])
    _seed_analysis(db, cv.id, ["Linux-based infrastructure operation"])
    _seed_analysis(db, cv.id, ["Terraform"])

    # The deterministic layer keeps these as 3 distinct keys; the AI maps them to "Linux".
    _patch_provider(monkeypatch, _FakeProvider({
        "Linux": "Linux",
        "Linux (not explicitly evidenced in CV)": "Linux",
        "Linux-based infrastructure operation": "Linux",
        "Terraform": "Terraform",
    }))

    snap = insights_service.refresh_insights(db)
    by_skill = {i["skill"]: i["count"] for i in snap.items}
    assert by_skill["Linux"] == 3           # three variants merged, counts summed
    assert by_skill["Terraform"] == 1
    assert snap.items[0]["skill"] == "Linux"  # most-asked ranks first


def test_ai_grouping_preserves_severity_and_why_across_merge(db, monkeypatch):
    cv = _seed_cv(db)
    _seed_analysis(db, cv.id, ["Linux ops"],
                   learning_gaps=[{"skill": "Linux ops", "level": "average", "why": "a"}])
    _seed_analysis(db, cv.id, ["Linux"],
                   learning_gaps=[{"skill": "Linux", "level": "basic", "why": "fundamental"}])
    _patch_provider(monkeypatch, _FakeProvider({"Linux ops": "Linux", "Linux": "Linux"}))

    snap = insights_service.refresh_insights(db)
    linux = next(i for i in snap.items if i["skill"] == "Linux")
    assert linux["count"] == 2
    assert linux["severity"] == "basic"  # basic wins over average across the merge


def test_ai_grouping_failure_falls_back_to_deterministic(db, monkeypatch):
    cv = _seed_cv(db)
    _seed_analysis(db, cv.id, ["Linux"])
    _seed_analysis(db, cv.id, ["Linux-based infrastructure operation"])

    class _Boom:
        model = "boom"
        def canonicalize_skills(self, labels, template=None):
            raise RuntimeError("AI down")

    _patch_provider(monkeypatch, _Boom())

    # Must not raise; deterministic grouping stands (two distinct unmerged rows).
    snap = insights_service.refresh_insights(db)
    assert snap is not None
    assert len(snap.items) == 2


def test_insights_canonicalize_prompt_registered_and_valid():
    from jobsearch.ai import prompts
    assert prompts.INSIGHTS_CANONICALIZE in prompts.SPECS
    prompts.validate(
        prompts.INSIGHTS_CANONICALIZE, prompts.DEFAULT_INSIGHTS_CANONICALIZE_PROMPT
    )
    # Stub returns an identity map (no offline semantic grouping).
    from jobsearch.ai.stub import StubProvider
    m = StubProvider().canonicalize_skills(["Linux", "K8s"])
    assert m == {"Linux": "Linux", "K8s": "K8s"}
