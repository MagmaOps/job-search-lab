"""Soft-delete (remove/restore) of jobs, the removed counter, and the source filter."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from jobsearch.models import Base
from jobsearch.services.ingest_service import ingest_job
from jobsearch.sources.base import RawJob

FULL = "We run kubernetes and terraform on aws. " * 45


def _raw(n: int, source: str = "remoteok") -> RawJob:
    return RawJob(title=f"DevOps {n}", source=source, url=f"https://x.io/j/{n}",
                  company="Acme", location="Remote", description=FULL)


@pytest.fixture()
def ctx():
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


def test_remove_hides_counts_and_restores(ctx):
    client, db = ctx
    ingest_job(db, _raw(1))
    ingest_job(db, _raw(2))
    db.commit()

    assert client.patch("/jobs/1", json={"removed": True}).json()["removed"] is True

    assert [j["id"] for j in client.get("/jobs").json()] == [2]
    assert [j["id"] for j in client.get("/jobs?removed=true").json()] == [1]
    status = client.get("/status").json()
    assert (status["jobs_total"], status["jobs_removed"]) == (1, 1)

    client.patch("/jobs/1", json={"removed": False})
    assert len(client.get("/jobs").json()) == 2
    assert client.get("/status").json()["jobs_removed"] == 0


def test_removed_job_stays_removed_after_recollection(ctx):
    client, db = ctx
    ingest_job(db, _raw(1))
    db.commit()
    client.patch("/jobs/1", json={"removed": True})
    assert ingest_job(db, _raw(1)) == "skipped"  # dedup finds the hidden row
    db.commit()
    assert client.get("/jobs").json() == []


def test_source_filter_and_list(ctx):
    client, db = ctx
    ingest_job(db, _raw(1, "remoteok"))
    ingest_job(db, _raw(2, "manual"))
    db.commit()

    assert client.get("/jobs/sources").json() == ["manual", "remoteok"]
    assert [j["source"] for j in client.get("/jobs?source=manual").json()] == ["manual"]


def test_found_date_range_is_inclusive(ctx):
    from datetime import datetime

    from jobsearch.models import Job

    client, db = ctx
    for n in (1, 2, 3):
        ingest_job(db, _raw(n))
    db.commit()
    for jid, ts in {1: datetime(2026, 11, 1, 0, 0), 2: datetime(2026, 11, 2, 23, 59),
                    3: datetime(2026, 11, 4, 12, 0)}.items():
        db.get(Job, jid).discovered_at = ts
    db.commit()

    def ids(qs):
        return sorted(j["id"] for j in client.get(f"/jobs?{qs}").json())

    assert ids("found_from=2026-11-02&found_to=2026-11-02") == [2]  # single day
    assert ids("found_from=2026-11-02") == [2, 3]
    assert ids("found_to=2026-11-02") == [1, 2]
    assert ids("found_from=2026-11-01&found_to=2026-11-04") == [1, 2, 3]
