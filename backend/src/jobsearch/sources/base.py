"""Source abstraction: the contract every job source implements."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class RawJob:
    """A job as returned by a source, before dedup/normalization/persistence."""

    title: str
    source: str
    url: str | None = None
    source_job_id: str | None = None
    company: str | None = None
    location: str | None = None
    description: str | None = None
    language: str | None = None
    extra: dict = field(default_factory=dict)


@runtime_checkable
class JobSource(Protocol):
    """A fetchable job source. Implementations are registered by `name`."""

    name: str

    def fetch(self, config: dict) -> list[RawJob]:
        """Fetch jobs for the given per-query source configuration."""
        ...
