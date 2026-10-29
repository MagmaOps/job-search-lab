"""Registry mapping source names to implementations."""

from __future__ import annotations

from .base import JobSource

_REGISTRY: dict[str, JobSource] = {}


def register_source(source: JobSource) -> JobSource:
    """Register a source instance under its `name`. Returns it for decorator-style use."""
    _REGISTRY[source.name] = source
    return source


def get_source(name: str) -> JobSource:
    try:
        return _REGISTRY[name]
    except KeyError as exc:
        raise KeyError(
            f"Unknown job source '{name}'. Registered: {sorted(_REGISTRY)}"
        ) from exc


def source_names() -> list[str]:
    return sorted(_REGISTRY)
