"""Job ingestion: turn RawJobs into persisted, deduplicated Job rows.

Dedup strategy (design requirement 5):
  1. normalized_url   2. (source, source_job_id)   3. fingerprint
We look up an existing job by any of the three identities. If found and the content hash
is unchanged, we skip. If the content changed, we update it and clear stale analyses so it
is re-analyzed. If not found, we insert.

A description the user supplied (manual job / pasted full text) is never overwritten by a
re-collected feed copy, and a description that looks truncated is flagged so the job is
held back from analysis until the user fixes it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..dedup import content_hash, fingerprint, normalize_url
from ..models import Analysis, Job
from ..sources.base import RawJob

# A real DevOps posting (responsibilities + requirements) runs well past this; anything
# shorter from a feed is almost always a teaser. Scoring a teaser produces a misleading
# score, so such jobs wait for the user to paste the full text.
MIN_DESCRIPTION_CHARS = 1500

# Tails feeds append when they cut a description short.
_TRUNCATION_TAIL = re.compile(
    r"(\.\.\.|…|\[…\]|\[\.\.\.\]|read more|see more|show more|continue reading"
    r"|view (?:the )?full (?:job|description|posting))\W*$",
    re.IGNORECASE,
)


def looks_truncated(description: str | None) -> bool:
    """Whether a feed description looks cut off: empty, too short, or ends in a teaser."""
    text = (description or "").strip()
    if len(text) < MIN_DESCRIPTION_CHARS:
        return True
    return bool(_TRUNCATION_TAIL.search(text[-80:]))


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
                salary=raw.salary,
                work_type=raw.work_type,
                content_hash=chash,
                description_incomplete=looks_truncated(raw.description),
            )
        )
        return "inserted"

    if existing.content_hash == chash or existing.description_manual:
        # A user-supplied description always wins over the feed's copy (which is often the
        # very teaser the user replaced), so a manually fixed job is treated as unchanged.
        # Known job, unchanged content → do not re-analyze (design requirement 5). Still
        # backfill salary/work_type if the source now provides what we were missing; these
        # are metadata, not content identity, so they don't trigger re-analysis.
        if raw.salary and not existing.salary:
            existing.salary = raw.salary
        if raw.work_type and not existing.work_type:
            existing.work_type = raw.work_type
        return "skipped"

    # Content changed: update fields and drop stale analyses so it gets re-analyzed.
    existing.title = raw.title
    existing.company = raw.company
    existing.location = raw.location
    existing.description = raw.description
    existing.language = raw.language
    existing.salary = raw.salary
    existing.work_type = raw.work_type
    existing.content_hash = chash
    existing.description_incomplete = looks_truncated(raw.description)
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
