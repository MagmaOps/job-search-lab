"""Generic RSS source — e.g. We Work Remotely category feeds.

Config:
    {"url": "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss"}

WWR item titles are usually "Company: Job Title"; we split on the first colon when present.
"""

from __future__ import annotations

import html
import re

import feedparser

from .base import RawJob
from .registry import register_source

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str | None) -> str | None:
    if not text:
        return None
    return html.unescape(_TAG_RE.sub("", text)).strip() or None


def _split_company_title(raw_title: str) -> tuple[str | None, str]:
    if ":" in raw_title:
        company, _, title = raw_title.partition(":")
        return company.strip() or None, title.strip() or raw_title.strip()
    return None, raw_title.strip()


class RssSource:
    name = "rss"

    def fetch(self, config: dict) -> list[RawJob]:
        url = config.get("url")
        if not url:
            raise ValueError("rss source requires a 'url' in source_config")

        feed = feedparser.parse(url)
        jobs: list[RawJob] = []
        for entry in feed.entries:
            raw_title = entry.get("title", "")
            company, title = _split_company_title(raw_title)
            region = entry.get("region") or entry.get("location")
            jobs.append(
                RawJob(
                    title=title,
                    source=self.name,
                    url=entry.get("link"),
                    source_job_id=entry.get("id") or entry.get("guid"),
                    company=company,
                    location=region or "Remote",
                    description=_strip_html(
                        entry.get("summary") or entry.get("description")
                    ),
                    extra={"feed": url},
                )
            )
        return jobs

    def parse_content(self, content: str, feed_url: str = "") -> list[RawJob]:
        """Parse already-fetched feed content. Useful for tests with fixtures."""
        feed = feedparser.parse(content)
        jobs: list[RawJob] = []
        for entry in feed.entries:
            company, title = _split_company_title(entry.get("title", ""))
            jobs.append(
                RawJob(
                    title=title,
                    source=self.name,
                    url=entry.get("link"),
                    source_job_id=entry.get("id") or entry.get("guid"),
                    company=company,
                    location=entry.get("region") or entry.get("location") or "Remote",
                    description=_strip_html(
                        entry.get("summary") or entry.get("description")
                    ),
                    extra={"feed": feed_url},
                )
            )
        return jobs


register_source(RssSource())
