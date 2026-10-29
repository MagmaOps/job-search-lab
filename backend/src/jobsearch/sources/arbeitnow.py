"""Arbeitnow source — free public JSON API, EU-friendly board."""

from __future__ import annotations

import html
import re

from ._http import get_client
from .base import RawJob, normalize_work_type
from .registry import register_source

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str | None) -> str | None:
    if not text:
        return None
    return html.unescape(_TAG_RE.sub("", text)).strip() or None


class ArbeitnowSource:
    name = "arbeitnow"

    def fetch(self, config: dict) -> list[RawJob]:
        keyword = (config.get("keyword") or "").lower()
        remote_only = config.get("remote_only", True)
        url = "https://www.arbeitnow.com/api/job-board-api"
        with get_client() as client:
            resp = client.get(url)
            resp.raise_for_status()
            data = resp.json()

        jobs: list[RawJob] = []
        for item in data.get("data", []):
            if remote_only and not item.get("remote", False):
                continue
            title = item.get("title") or ""
            if keyword and keyword not in title.lower():
                continue
            jobs.append(
                RawJob(
                    title=title,
                    source=self.name,
                    url=item.get("url"),
                    source_job_id=item.get("slug"),
                    company=item.get("company_name"),
                    location=item.get("location") or ("Remote" if item.get("remote") else None),
                    description=_strip_html(item.get("description")),
                    # Arbeitnow exposes an explicit remote boolean; fall back to the title
                    # and job-type tags for hybrid/onsite hints.
                    work_type=normalize_work_type(
                        f"{title} {' '.join(item.get('job_types') or [])}",
                        remote_flag=bool(item.get("remote")),
                    ),
                    extra={"tags": item.get("tags") or [], "remote": item.get("remote")},
                )
            )
        return jobs


register_source(ArbeitnowSource())
