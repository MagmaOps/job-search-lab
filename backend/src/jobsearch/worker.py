"""Background worker: scheduled collection + analysis queue, with optional leader election.

HA model (design): run 2+ replicas, but only the leader runs the scheduler. In Kubernetes
the leader is elected via a Lease; here we implement a lightweight Postgres advisory-lock
leader election so a single active worker runs at a time and failover is automatic when the
leader process/node dies (the advisory lock is released with its session).
"""

from __future__ import annotations

import logging
import signal
import time

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import text

from .config import get_settings
from .db import SessionLocal, engine
from .services import analysis_service, application_service, collect_service

logging.basicConfig(level=get_settings().log_level)
log = logging.getLogger("jobsearch.worker")

# Arbitrary but stable key for the collection leader advisory lock.
_LEADER_LOCK_KEY = 0x10B5_EA40


def _run_cycle() -> None:
    """One collection + analysis pass."""
    db = SessionLocal()
    try:
        run = collect_service.run_collection(db, trigger="scheduled")
        analyzed = analysis_service.analyze_pending(db, limit=50)
        log.info(
            "collection: found=%s new=%s analyzed=%s errors=%s",
            run.jobs_found, run.jobs_new, analyzed, len(run.errors or []),
        )
    except Exception:
        log.exception("collection cycle failed")
    finally:
        db.close()


def _drain_analysis_queue() -> None:
    """Frequent tick: process any jobs queued for analysis (manual re-analyze / backlog).

    Runs on a short interval so a user's 'Re-analyze' click resolves within seconds and the
    dashboard spinner clears, independent of the 6-hourly collection schedule. The work
    happens here in the worker, so it continues even if the browser tab that triggered it
    is closed.
    """
    db = SessionLocal()
    try:
        processed = analysis_service.analyze_pending(db, limit=25)
        if processed:
            log.info("analysis queue: processed=%s", processed)
        # Same tick drains the application-generation queue so a 'Generate application'
        # click resolves within seconds. Generation is heavier per job, so a smaller batch.
        generated = application_service.generate_pending(db, limit=5)
        if generated:
            log.info("application queue: generated=%s", generated)
    except Exception:
        log.exception("analysis queue tick failed")
    finally:
        db.close()


def _acquire_leader(conn) -> bool:
    """Try to grab the session-scoped advisory lock. Non-blocking."""
    return bool(conn.execute(text("SELECT pg_try_advisory_lock(:k)"),
                             {"k": _LEADER_LOCK_KEY}).scalar())


def main() -> None:
    settings = get_settings()
    log.info("worker starting; schedule=%s leader_election=%s",
             settings.collect_schedule, settings.leader_election)

    stop = {"flag": False}

    def _handle(_sig, _frame):
        stop["flag"] = True

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)

    if settings.leader_election:
        # Hold a dedicated connection for the life of the leader session.
        conn = engine.connect()
        try:
            while not stop["flag"]:
                if _acquire_leader(conn):
                    log.info("became leader; starting scheduler")
                    _schedule_and_block(settings, stop)
                    break
                log.info("not leader; standing by")
                time.sleep(15)
        finally:
            conn.close()
    else:
        _schedule_and_block(settings, stop)

    log.info("worker stopped")


def _schedule_and_block(settings, stop: dict) -> None:
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        _run_cycle,
        CronTrigger.from_crontab(settings.collect_schedule),
        id="collect",
        max_instances=1,
        coalesce=True,
    )
    # Drain the manual analysis queue every few seconds so re-analyze feedback is prompt.
    scheduler.add_job(
        _drain_analysis_queue,
        "interval",
        seconds=settings.analysis_poll_seconds,
        id="analysis_queue",
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    # Run one pass immediately on startup so the dashboard isn't empty.
    _run_cycle()
    try:
        while not stop["flag"]:
            time.sleep(1)
    finally:
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    main()
