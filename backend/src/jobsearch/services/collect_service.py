"""Collection: run enabled queries through their sources and ingest the results."""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import CollectionRun, SearchQuery, _utcnow
from ..sources import get_source
from .ingest_service import ingest_many


def run_collection(db: Session, trigger: str = "scheduled") -> CollectionRun:
    """Run every enabled query, ingest results, and record the run.

    Manual-reference sources (e.g. linkedin bookmarks) are skipped automatically because
    they are not registered as fetchable sources.
    """
    run = CollectionRun(started_at=_utcnow(), trigger=trigger, errors=[])
    db.add(run)
    db.commit()

    errors: list[dict] = []
    total_found = total_new = 0

    queries = db.query(SearchQuery).filter(SearchQuery.enabled.is_(True)).all()
    for q in queries:
        try:
            source = get_source(q.source)
        except KeyError:
            # Not a fetchable source (e.g. 'linkedin' manual reference) — skip quietly.
            continue
        try:
            raws = source.fetch(q.source_config or {})
            result = ingest_many(db, raws)
            total_found += result.found
            total_new += result.inserted
        except Exception as exc:
            errors.append({"query": q.name, "source": q.source, "error": str(exc)[:500]})

    run.finished_at = _utcnow()
    run.jobs_found = total_found
    run.jobs_new = total_new
    run.errors = errors
    db.commit()
    db.refresh(run)
    return run


def last_run(db: Session) -> CollectionRun | None:
    return (
        db.query(CollectionRun)
        .order_by(CollectionRun.started_at.desc())
        .first()
    )
