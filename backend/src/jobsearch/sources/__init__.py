"""Modular job sources. New sources register here without touching the scheduler."""

from __future__ import annotations

from .base import JobSource, RawJob
from .registry import get_source, register_source, source_names

# Import implementations so they self-register.
from . import arbeitnow, remoteok, remotive, rss  # noqa: E402,F401

__all__ = [
    "JobSource",
    "RawJob",
    "get_source",
    "register_source",
    "source_names",
]
