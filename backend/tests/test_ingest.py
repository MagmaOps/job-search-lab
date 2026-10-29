from jobsearch.models import Analysis, Job, ProcessingStatus
from jobsearch.services.ingest_service import ingest_job, ingest_many
from jobsearch.sources.base import RawJob


def _raw(**kw) -> RawJob:
    base = dict(title="DevOps Engineer", source="remoteok", url="https://x.io/j/1",
                company="Acme", location="Remote", description="k8s and terraform")
    base.update(kw)
    return RawJob(**base)


def test_insert_then_skip_unchanged(db):
    assert ingest_job(db, _raw()) == "inserted"
    db.commit()
    assert ingest_job(db, _raw()) == "skipped"


def test_dedup_by_normalized_url_ignores_tracking(db):
    ingest_job(db, _raw(url="https://x.io/j/1"))
    db.commit()
    # Same job, noisy URL + no source id → matched via normalized_url.
    outcome = ingest_job(db, _raw(url="https://x.io/j/1?utm_source=foo", source_job_id=None))
    assert outcome == "skipped"
    assert db.query(Job).count() == 1


def test_changed_content_updates_and_clears_analyses(db):
    ingest_job(db, _raw())
    db.commit()
    job = db.query(Job).one()
    db.add(Analysis(job_id=job.id, cv_id=1, processing_status=ProcessingStatus.done,
                    match_score=80))
    db.commit()

    outcome = ingest_job(db, _raw(description="completely different text"))
    db.commit()
    assert outcome == "updated"
    # stale analysis dropped so it will be re-analyzed
    assert db.query(Analysis).count() == 0


def test_ingest_many_counts(db):
    raws = [_raw(url="https://x.io/j/1", source_job_id="1"),
            _raw(url="https://x.io/j/2", source_job_id="2", title="SRE"),
            _raw(title="")]  # skipped: no title
    result = ingest_many(db, raws)
    assert result.inserted == 2
    assert result.skipped == 1
