"""Remotive source — free public JSON API."""

from __future__ import annotations

import html
import re

from ._http import get_client
from .base import RawJob, format_salary, normalize_work_type
from .registry import register_source

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str | None) -> str | None:
    if not text:
        return None
    return html.unescape(_TAG_RE.sub("", text)).strip() or None


class RemotiveSource:
    name = "remotive"

    def fetch(self, config: dict) -> list[RawJob]:
        category = config.get("category", "devops")
        limit = config.get("limit", 50)
        url = f"https://remotive.com/api/remote-jobs?category={category}&limit={limit}"
        with get_client() as client:
            resp = client.get(url)
            resp.raise_for_status()
            data = resp.json()

        jobs: list[RawJob] = []
        for item in data.get("jobs", []):
            jobs.append(
                RawJob(
                    title=item.get("title") or "",
                    source=self.name,
                    url=item.get("url"),
                    source_job_id=str(item["id"]) if item.get("id") is not None else None,
                    company=item.get("company_name"),
                    location=item.get("candidate_required_location") or "Remote",
                    description=_strip_html(item.get("description")),
                    # Remotive's `salary` is a free-text string (often empty).
                    salary=format_salary(raw=item.get("salary")),
                    # Remotive is a remote board; its `job_type` ("full_time") is employment
                    # type, not arrangement, so default to remote.
                    work_type=normalize_work_type(
                        item.get("candidate_required_location"), remote_flag=True
                    ),
                    extra={
                        "category": item.get("category"),
                        "job_type": item.get("job_type"),
                    },
                )
            )
        return jobs


register_source(RemotiveSource())
