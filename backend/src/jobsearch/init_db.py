"""Create tables and seed the predefined DevOps query.

Idempotent: safe to run on every container start. Uses create_all (no destructive ops)
and only inserts the seed query if no queries exist yet.
"""

from __future__ import annotations

import logging

from sqlalchemy import func, text

from .config import get_settings
from .db import SessionLocal, engine
from .models import Base, SearchQuery
from .services.ingest_service import looks_truncated

# Serialize schema creation/seed so concurrent api+worker startup can't collide
# (e.g. both trying to CREATE TYPE job_status at once).
_INIT_LOCK_KEY = 0x10B5_1217

log = logging.getLogger("jobsearch.init_db")

# The predefined DevOps-focused queries (design: RSS/API auto sources + LinkedIn reference).
LINKEDIN_EU_REMOTE_URL = (
    "https://www.linkedin.com/jobs/search/?keywords=DevOps%20Engineer"
    "&location=European%20Union&geoId=91000000&f_WT=2&f_TPR=r604800&sortBy=DD"
)

SEED_QUERIES = [
    dict(
        name="DevOps — We Work Remotely",
        source="rss",
        keywords="DevOps Engineer",
        work_type="remote",
        location="Remote",
        source_config={
            "url": "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss"
        },
    ),
    dict(
        name="DevOps — RemoteOK",
        source="remoteok",
        keywords="DevOps Engineer",
        work_type="remote",
        location="Remote",
        source_config={"tag": "devops"},
    ),
    dict(
        name="DevOps — Remotive",
        source="remotive",
        keywords="DevOps Engineer",
        work_type="remote",
        location="Remote",
        source_config={"category": "devops", "limit": 50},
    ),
    dict(
        name="DevOps — Arbeitnow (EU)",
        source="arbeitnow",
        keywords="DevOps",
        work_type="remote",
        location="EU / Remote",
        source_config={"keyword": "devops", "remote_only": True},
    ),
    dict(
        name="DevOps — Freehire (EU/remote)",
        source="freehire",
        keywords="DevOps Engineer",
        work_type="remote",
        location="EU / Remote",
        source_config={
            "query": "devops",
            "regions": ["eu", "global"],
            "work_mode": "remote",
            "posted_within_days": 30,
            "limit": 50,
        },
    ),
    dict(
        name="DevOps — LinkedIn (manual reference, EU remote)",
        source="linkedin",  # not a fetchable source → skipped by the collector
        keywords="DevOps Engineer",
        work_type="remote",
        location="European Union",
        enabled=False,
        source_config={"mode": "manual"},
        reference_url=LINKEDIN_EU_REMOTE_URL,
    ),
]


# Additive column top-ups for tables that already exist from an earlier version.
# create_all() creates missing tables but never alters an existing one, so a new column
# on an existing table is added here. Each statement is idempotent (IF NOT EXISTS).
_COLUMN_TOPUPS = (
    'ALTER TABLE analysis ADD COLUMN IF NOT EXISTS dimension_scores JSONB',
    'ALTER TABLE analysis ADD COLUMN IF NOT EXISTS learning_gaps JSONB',
    'ALTER TABLE analysis ADD COLUMN IF NOT EXISTS stale BOOLEAN DEFAULT FALSE',
    'ALTER TABLE application ADD COLUMN IF NOT EXISTS cv_full_md TEXT',
    'ALTER TABLE insights ADD COLUMN IF NOT EXISTS grouping VARCHAR(16)',
    'ALTER TABLE insights ADD COLUMN IF NOT EXISTS grouping_error TEXT',
    'ALTER TABLE analysis ADD COLUMN IF NOT EXISTS posting_country VARCHAR(64)',
    'ALTER TABLE analysis ADD COLUMN IF NOT EXISTS eligibility VARCHAR(16)',
    'ALTER TABLE analysis ADD COLUMN IF NOT EXISTS eligibility_note TEXT',
    'ALTER TABLE job ADD COLUMN IF NOT EXISTS salary VARCHAR(128)',
    'ALTER TABLE job ADD COLUMN IF NOT EXISTS work_type VARCHAR(16)',
    # No DEFAULT on purpose: existing rows stay NULL so _backfill_description_flags can
    # tell "never checked" from a user's explicit "complete" (False).
    'ALTER TABLE job ADD COLUMN IF NOT EXISTS description_incomplete BOOLEAN',
    'ALTER TABLE job ADD COLUMN IF NOT EXISTS description_manual BOOLEAN DEFAULT FALSE',
    'ALTER TABLE job ADD COLUMN IF NOT EXISTS removed BOOLEAN DEFAULT FALSE',
)


def _backfill_description_flags(conn) -> None:
    """Flag truncated descriptions on jobs collected before the flag existed (NULL only).

    Manual jobs are trusted unless empty — the user wrote that text deliberately.
    Idempotent: once a row is set it is never revisited, so a user's override sticks.
    """
    rows = conn.execute(
        text("SELECT id, source, description FROM job WHERE description_incomplete IS NULL")
    ).all()
    for job_id, source, description in rows:
        if source == "manual":
            incomplete = not (description or "").strip()
        else:
            incomplete = looks_truncated(description)
        conn.execute(
            text("UPDATE job SET description_incomplete = :v WHERE id = :id"),
            {"v": incomplete, "id": job_id},
        )
    if rows:
        log.info("checked %s existing job descriptions for truncation", len(rows))


def create_tables() -> None:
    Base.metadata.create_all(bind=engine)


def main() -> None:
    logging.basicConfig(level=get_settings().log_level)
    # Hold a transaction-scoped advisory lock so only one process initializes at a time.
    with engine.begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _INIT_LOCK_KEY})
        Base.metadata.create_all(bind=conn)
        for stmt in _COLUMN_TOPUPS:
            conn.execute(text(stmt))
        _backfill_description_flags(conn)
    seed()


def seed() -> None:
    db = SessionLocal()
    try:
        existing = db.query(func.count(SearchQuery.id)).scalar() or 0
        if existing:
            log.info("queries already present (%s); skipping seed", existing)
            return
        for q in SEED_QUERIES:
            db.add(SearchQuery(**q))
        db.commit()
        log.info("seeded %s predefined queries", len(SEED_QUERIES))
    finally:
        db.close()


if __name__ == "__main__":
    main()
