"""Shared HTTP helper for sources. A descriptive User-Agent is polite and required by
some APIs (e.g. RemoteOK rejects requests without one)."""

from __future__ import annotations

import httpx

USER_AGENT = "job-search-lab/0.1 (+personal homelab job aggregator)"

_TIMEOUT = httpx.Timeout(20.0, connect=10.0)


def get_client() -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept": "application/json, */*"},
        timeout=_TIMEOUT,
        follow_redirects=True,
    )
