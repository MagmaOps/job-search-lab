"""Freehire source — the freehire.me public REST API (JSON, no API key).

Adapted from the ai-job-search repo's `freehire-search` CLI: same endpoint and query
surface, reshaped into our RawJob contract. Tech-focused (software, data, DevOps, remote)
and multi-market via facets, so it is a clean fit for a remote-EU DevOps search. Unlike the
HTML-scraping boards, results arrive structured — including salary and an explicit
work_mode — so we populate those fields directly.

Config (source_config):
    {
      "query": "devops",            # free-text search (q)
      "regions": ["eu", "global"],  # closed vocab: global|north_america|latam|eu|uk|
                                     #   mena|africa|apac|cis|none
      "countries": ["DE"],          # ISO country codes (optional)
      "work_mode": "remote",        # remote | hybrid | onsite (optional)
      "skills": ["kubernetes"],     # optional skill facets
      "category": ["devops"],       # optional category facets
      "posted_within_days": 14,     # recency scope (optional)
      "limit": 50                   # cap (optional, default 50)
    }
    FREEHIRE_API_URL env var overrides the base URL (self-hosted instance).
"""

from __future__ import annotations

import os

from ._http import get_client
from .base import RawJob, format_salary, normalize_work_type
from .registry import register_source

_DEFAULT_BASE_URL = "https://freehire.me"
_SEARCH_PATH = "/api/v1/jobs/search"

# freehire's closed region vocabulary (from its OpenAPI enum). A value outside this set
# matches almost nothing, so we drop unknowns rather than send a filter that returns empty.
_REGION_VALUES = {
    "global", "north_america", "latam", "eu", "uk", "mena", "africa", "apac", "cis", "none",
}


def _base_url() -> str:
    return (os.environ.get("FREEHIRE_API_URL") or _DEFAULT_BASE_URL).rstrip("/")


def _as_list(value: object) -> list[str]:
    """Coerce a config value that may be a scalar or a list into a list of strings."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value if str(v).strip()]
    return [str(value)] if str(value).strip() else []


def _salary(enrichment: dict) -> str | None:
    """Build a salary string from freehire's enrichment block, if present."""
    if not isinstance(enrichment, dict):
        return None
    return format_salary(
        enrichment.get("salary_min"),
        enrichment.get("salary_max"),
        currency=enrichment.get("salary_currency"),
        period=enrichment.get("salary_period"),
    )


class FreehireSource:
    name = "freehire"

    def fetch(self, config: dict) -> list[RawJob]:
        params: list[tuple[str, str]] = []

        query = (config.get("query") or config.get("keyword") or "").strip()
        if query:
            params.append(("q", query))

        limit = int(config.get("limit", 50) or 50)
        params.append(("limit", str(limit)))
        params.append(("offset", "0"))

        posted_within = config.get("posted_within_days")
        if posted_within:
            params.append(("posted_within_days", str(int(posted_within))))

        work_mode = normalize_work_type(config.get("work_mode"))
        if work_mode:
            params.append(("work_mode", work_mode))

        # Repeated facet params; drop region values outside the closed vocabulary.
        for region in _as_list(config.get("regions")):
            if region.lower() in _REGION_VALUES:
                params.append(("regions", region.lower()))
        for key in ("countries", "skills", "category"):
            for value in _as_list(config.get(key)):
                params.append((key, value))
        company_slug = config.get("company_slug")
        if company_slug:
            params.append(("company_slug", str(company_slug)))

        url = f"{_base_url()}{_SEARCH_PATH}"
        with get_client() as client:
            resp = client.get(url, params=params)
            resp.raise_for_status()
            payload = resp.json()

        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            return []

        jobs: list[RawJob] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            enrichment = item.get("enrichment") or {}
            jobs.append(
                RawJob(
                    title=item.get("title") or "",
                    source=self.name,
                    url=item.get("url"),
                    source_job_id=item.get("public_slug") or item.get("external_id"),
                    company=item.get("company"),
                    location=item.get("location") or "Remote",
                    description=item.get("description") or None,
                    salary=_salary(enrichment),
                    work_type=normalize_work_type(
                        item.get("work_mode"),
                        remote_flag="remote" in (item.get("regions") or []),
                    ),
                    extra={
                        "regions": item.get("regions") or [],
                        "skills": item.get("skills") or [],
                        "seniority": enrichment.get("seniority"),
                        "category": enrichment.get("category"),
                    },
                )
            )
        return jobs


register_source(FreehireSource())
