import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from jobsearch.models import Base


@pytest.fixture()
def db():
    """In-memory SQLite session for fast, isolated service tests.

    Note: SQLite lacks JSONB/partial-unique nuances, but it is sufficient for the dedup,
    content-hash, caching and retry logic under test. Production uses Postgres.
    """
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    session = Session()
    try:
        yield session
    finally:
        session.close()
