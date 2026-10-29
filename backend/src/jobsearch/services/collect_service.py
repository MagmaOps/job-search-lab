"""Collection: run enabled queries through their sources and ingest the results."""

from __future__ import annotations

import re

from sqlalchemy.orm import Session

from ..models import CollectionRun, SearchQuery, _utcnow
from ..sources import get_source
from ..sources.base import RawJob
from .ingest_service import ingest_many

# DevOps-adjacent role vocabulary. A fetched job is kept when its title matches the query's
# own keywords OR any of these — so a "devops"-tagged board result that is really a
# copywriter/manufacturing role is dropped, while genuine DevOps-family roles (SRE,
# Platform, Infrastructure, Cloud, Kubernetes…) are kept even if the title omits "devops".
_DEVOPS_TERMS = (
    "devops", "dev ops", "sre", "site reliability", "platform engineer",
    "platform engineering", "infrastructure engineer", "infrastructure architect",
    "cloud engineer", "cloud infrastructure", "systems engineer", "sysadmin",
    "system administrator", "kubernetes", "k8s", "terraform", "ci/cd", "gitops",
    "release engineer", "automation engineer", "cloud operations", "cloudops",
)


# Generic role words that, standing alone, match almost any posting ("engineer",
# "developer"…). They are dropped from a query's keyword terms so relevance is driven by
# the distinctive words ("devops") and the role vocabulary below, not by "engineer" alone.
_GENERIC_WORDS = {
    "engineer", "engineering", "developer", "dev", "manager", "specialist",
    "senior", "junior", "lead", "staff", "principal", "remote", "and", "the",
}

# Domains to exclude even when the role is genuinely DevOps. A job is dropped when any of
# these terms appears in its title OR description — a DevOps role at a crypto shop usually
# names the domain in the body, not the title. Matched on word boundaries so "blockchain"
# does not also catch an unrelated substring. Extend this set to filter more domains.
_EXCLUDE_TERMS = (
    "blockchain",
    "crypto",
    "cryptocurrency",
    "web3",
    "defi",
    "nft",
)
_EXCLUDE_RE = re.compile(
    r"\b(" + "|".join(re.escape(t) for t in _EXCLUDE_TERMS) + r")\b", re.IGNORECASE
)


def _is_excluded(job: object) -> bool:
    """Whether a job falls in an excluded domain (e.g. Blockchain/crypto), by title or body.

    Accepts anything with `.title` and `.description` — both RawJob (pre-ingest) and the
    stored Job ORM row (purge) qualify.
    """
    title = getattr(job, "title", "") or ""
    description = getattr(job, "description", "") or ""
    return bool(_EXCLUDE_RE.search(f"{title}\n{description}"))


def _keyword_terms(keywords: str | None) -> list[str]:
    """Split a query's keywords into distinctive lowercase terms (generic words dropped)."""
    if not keywords:
        return []
    terms = [t for t in re.split(r"[\s,]+", keywords.lower()) if len(t) > 1]
    return [t for t in terms if t not in _GENERIC_WORDS]


def filter_relevant(raws: list[RawJob], keywords: str | None) -> list[RawJob]:
    """Keep jobs whose title matches the query keywords or the DevOps role vocabulary.

    Sources like RemoteOK's `?tag=devops` return loosely-tagged results (a job carrying a
    'devops' tag among many others), so a title-level relevance filter is applied here for
    every source. A job with no title is dropped. When a query has no keywords and the
    DevOps vocabulary is somehow empty, nothing is filtered (fail open)."""
    query_terms = _keyword_terms(keywords)
    wanted = set(query_terms) | set(_DEVOPS_TERMS)
    kept: list[RawJob] = []
    for raw in raws:
        # Excluded domains (e.g. Blockchain) are dropped even for an otherwise-relevant
        # DevOps title, and regardless of whether a keyword filter is active.
        if _is_excluded(raw):
            continue
        if not wanted:
            kept.append(raw)
            continue
        title = (raw.title or "").lower()
        if title and any(term in title for term in wanted):
            kept.append(raw)
    return kept


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
            raws = filter_relevant(raws, q.keywords)
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


def _title_is_relevant(title: str | None) -> bool:
    """Whether a single stored title passes the DevOps relevance vocabulary."""
    t = (title or "").lower()
    return bool(t) and any(term in t for term in _DEVOPS_TERMS)


def purge_irrelevant_jobs(db: Session, keywords: str | None = "DevOps Engineer") -> dict:
    """Delete stored jobs whose title is not DevOps-relevant (one-time cleanup of a backlog
    collected before the relevance filter existed).

    Destructive: removes Job rows (their analyses cascade). Returns the deleted titles so
    the caller can show exactly what was removed. Manual jobs (source='manual') are kept —
    they were added deliberately by the user, never by a broad source feed."""
    from ..models import Job  # local import to avoid a cycle at module load

    terms = set(_keyword_terms(keywords)) | set(_DEVOPS_TERMS)
    deleted: list[str] = []
    kept = 0
    for job in db.query(Job).all():
        # Excluded domains (Blockchain/crypto) are purged even for a DevOps title — but
        # never a manually-added job, which the user chose deliberately.
        if job.source != "manual" and _is_excluded(job):
            deleted.append(job.title)
            db.delete(job)
            continue
        if job.source == "manual":
            kept += 1
            continue
        title = (job.title or "").lower()
        if title and any(term in title for term in terms):
            kept += 1
            continue
        deleted.append(job.title)
        db.delete(job)
    db.commit()
    return {"deleted_count": len(deleted), "kept_count": kept, "deleted_titles": deleted}
