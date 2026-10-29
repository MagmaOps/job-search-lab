"""RemoteOK source — free public JSON API.

Notes (from docs/design.md):
- Requires a User-Agent header.
- The first element of the response array is a legal/attribution notice, not a job.
- Attribution to RemoteOK is required by their terms; we keep the apply URL intact.
"""

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


class RemoteOkSource:
    name = "remoteok"

    def fetch(self, config: dict) -> list[RawJob]:
        tag = config.get("tag", "devops")
        url = f"https://remoteok.com/api?tag={tag}"
        with get_client() as client:
            resp = client.get(url)
            resp.raise_for_status()
            data = resp.json()

        if not isinstance(data, list):
            return []

        jobs: list[RawJob] = []
        for item in data:
            # Skip the leading legal-notice object and anything without an id.
            if not isinstance(item, dict) or "id" not in item or "position" not in item:
                continue
            tags = item.get("tags") or []
            jobs.append(
                RawJob(
                    title=item.get("position") or item.get("title") or "",
                    source=self.name,
                    url=item.get("url") or item.get("apply_url"),
                    source_job_id=str(item.get("id")),
                    company=item.get("company"),
                    location=item.get("location") or "Remote",
                    description=_strip_html(item.get("description")),
                    salary=format_salary(
                        item.get("salary_min"),
                        item.get("salary_max"),
                        currency="USD",
                        period="year",
                    ),
                    # RemoteOK is a remote-only board; the location string confirms it.
                    work_type=normalize_work_type(item.get("location"), remote_flag=True),
                    extra={"tags": tags, "salary_min": item.get("salary_min")},
                )
            )
        return jobs


register_source(RemoteOkSource())
