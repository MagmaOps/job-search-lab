"""URL normalization, fingerprinting, and content hashing for deduplication.

Implements the three-tier dedup strategy from docs/design.md section 3:
1. normalized URL   2. source job id   3. fallback fingerprint
Plus a content hash used to detect whether an already-seen job has changed.
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Query params that carry tracking/session noise, not identity.
_TRACKING_PARAMS = re.compile(
    r"^(utm_|ref$|ref_|source$|fbclid$|gclid$|mc_|trk$|trackingId$|refId$)", re.IGNORECASE
)


def normalize_url(url: str | None) -> str | None:
    """Return a canonical form of a URL for dedup, or None if there is no usable URL.

    - lowercases scheme + host
    - drops the fragment
    - removes tracking query params
    - sorts remaining query params
    - strips a trailing slash from the path
    """
    if not url:
        return None
    url = url.strip()
    if not url:
        return None

    parts = urlsplit(url)
    if not parts.netloc:
        return None

    scheme = parts.scheme.lower() or "https"
    netloc = parts.netloc.lower()
    # strip default ports
    netloc = re.sub(r":(80|443)$", "", netloc)

    path = parts.path.rstrip("/")

    kept = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=False)
        if not _TRACKING_PARAMS.match(k)
    ]
    kept.sort()
    query = urlencode(kept)

    return urlunsplit((scheme, netloc, path, query, ""))


def _norm_text(value: str | None) -> str:
    """Lowercase, collapse whitespace, strip — for stable fingerprints."""
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip().lower()


def fingerprint(
    source: str,
    company: str | None,
    title: str | None,
    location: str | None,
) -> str:
    """Fallback identity hash when there is no URL or source id.

    Based on source + company + title + location (design requirement 5).
    """
    basis = "|".join(_norm_text(x) for x in (source, company, title, location))
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def content_hash(title: str | None, description: str | None) -> str:
    """Hash of the meaningful content, used to detect changes in a known job."""
    basis = "|".join(_norm_text(x) for x in (title, description))
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()
