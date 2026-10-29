"""Database engine, session factory, and FastAPI dependency."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings

_settings = get_settings()


def _normalize_db_url(url: str) -> str:
    """Ensure the psycopg v3 driver is selected.

    CloudNativePG hands out a plain `postgresql://...` URI; SQLAlchemy would pick the
    default (psycopg2) driver for that. Rewrite the scheme to use psycopg v3 unless a
    driver is already specified.
    """
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    return url


engine = create_engine(
    _normalize_db_url(_settings.database_url),
    pool_pre_ping=True,  # survive CNPG failover: drop stale connections gracefully
    pool_recycle=300,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def get_db() -> Iterator[Session]:
    """FastAPI dependency that yields a session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
