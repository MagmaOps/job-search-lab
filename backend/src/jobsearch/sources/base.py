"""Source abstraction: the contract every job source implements."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


def normalize_work_type(value: str | None, *, remote_flag: bool | None = None) -> str | None:
    """Map a free-text hint (and an optional explicit remote flag) to a canonical value.

    Returns one of "remote" | "hybrid" | "onsite", or None when there is no signal.
    `remote_flag` (e.g. Arbeitnow's boolean `remote`) wins when True.
    """
    text = (value or "").lower()
    if "hybrid" in text:
        return "hybrid"
    if remote_flag or "remote" in text or "anywhere" in text or "work from home" in text:
        return "remote"
    if any(k in text for k in ("on-site", "onsite", "on site", "in office", "in-office")):
        return "onsite"
    return None


def format_salary(
    min_value: object = None,
    max_value: object = None,
    *,
    currency: str | None = None,
    period: str | None = None,
    raw: str | None = None,
) -> str | None:
    """Build a human-readable salary string, or pass through a source's own `raw` string.

    Returns None when there is nothing usable. Non-numeric min/max are ignored so a bad
    field never produces a misleading figure.
    """
    if raw and raw.strip():
        return raw.strip()

    def _num(v: object) -> int | None:
        if isinstance(v, bool) or v is None:
            return None
        try:
            n = int(float(v))
        except (TypeError, ValueError):
            return None
        return n if n > 0 else None

    lo, hi = _num(min_value), _num(max_value)
    if lo is None and hi is None:
        return None

    cur = f"{currency} " if currency else ""
    per = f"/{period}" if period else ""
    if lo is not None and hi is not None and lo != hi:
        return f"{cur}{lo:,} – {hi:,}{per}"
    return f"{cur}{(lo or hi):,}{per}"


# Backwards-friendly alias; some callers may want to detect remote from a location string.
_REMOTE_RE = re.compile(r"\bremote\b", re.IGNORECASE)


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
    # Human-readable salary range as the source states it, e.g. "$90k – $120k". None when
    # the source gives no salary.
    salary: str | None = None
    # Normalized work arrangement: "remote" | "hybrid" | "onsite" | None (unknown).
    work_type: str | None = None
    extra: dict = field(default_factory=dict)


@runtime_checkable
class JobSource(Protocol):
    """A fetchable job source. Implementations are registered by `name`."""

    name: str

    def fetch(self, config: dict) -> list[RawJob]:
        """Fetch jobs for the given per-query source configuration."""
        ...
