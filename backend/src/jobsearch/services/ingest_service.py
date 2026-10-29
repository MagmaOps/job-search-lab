"""Job ingestion: turn RawJobs into persisted, deduplicated Job rows.

Dedup strategy (design requirement 5):
  1. normalized_url   2. (source, source_job_id)   3. fingerprint
We look up an existing job by any of the three identities. If found and the content hash
is unchanged, we skip. If the content changed, we update it and clear stale analyses so it
is re-analyzed. If not found, we insert.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..dedup import content_hash, fingerprint, normalize_url
from ..models import Analysis, Job
from ..sources.base import RawJob


@dataclass
class IngestResult:
    found: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0


def _find_existing(db: Session, norm_url: str | None, source: str,
                   source_job_id: str | None, fp: str) -> Job | None:
    conditions = [Job.fingerprint == fp]
    if norm_url:
        conditions.append(Job.normalized_url == norm_url)
    if source_job_id:
        conditions.append((Job.source == source) & (Job.source_job_id == source_job_id))
    return db.query(Job).filter(or_(*conditions)).first()


def ingest_job(db: Session, raw: RawJob) -> str:
    """Insert/update/skip a single raw job. Returns 'inserted' | 'updated' | 'skipped'."""
    norm_url = normalize_url(raw.url)
    fp = fingerprint(raw.source, raw.company, raw.title, raw.location)
    chash = content_hash(raw.title, raw.description)

    existing = _find_existing(db, norm_url, raw.source, raw.source_job_id, fp)

    if existing is None:
        db.add(
            Job(
                source=raw.source,
                source_job_id=raw.source_job_id,
                url=raw.url,
                normalized_url=norm_url,
                fingerprint=fp,
                title=raw.title,
                company=raw.company,
                location=raw.location,
                description=raw.description,
                language=raw.language,
                content_hash=chash,
            )
        )
        return "inserted"

    if existing.content_hash == chash:
        # Known job, unchanged → do not re-analyze (design requirement 5).
        return "skipped"

    # Content changed: update fields and drop stale analyses so it gets re-analyzed.
    existing.title = raw.title
    existing.company = raw.company
    existing.location = raw.location
    existing.description = raw.description
    existing.language = raw.language
    existing.content_hash = chash
    db.query(Analysis).filter(Analysis.job_id == existing.id).delete()
    return "updated"


def ingest_many(db: Session, raws: list[RawJob]) -> IngestResult:
    result = IngestResult(found=len(raws))
    for raw in raws:
        if not raw.title:
            result.skipped += 1
            continue
        try:
            outcome = ingest_job(db, raw)
        except Exception:
            db.rollback()
            result.skipped += 1
            continue
        setattr(result, outcome, getattr(result, outcome) + 1)
        db.commit()
    return result
