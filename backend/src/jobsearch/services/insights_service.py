"""Insights: aggregate skill gaps across all analyzed jobs for the active CV.

A snapshot, not a live view. `refresh_insights` recomputes from every `done` analysis for
the active CV and overwrites the single stored snapshot; `get_insights` returns it;
`clear_insights` deletes it. Nothing auto-deletes or auto-recomputes it — the user drives
Refresh/Clear from the UI. The computation is pure SQL aggregation + deterministic
normalization (no AI call), so Refresh is fast and free.

Signal source: `analysis.missing_requirements` (what postings wanted that the CV lacks),
ranked by how often each normalized skill appears. Severity comes from
`analysis.learning_gaps` (basic | average) where the same skill was flagged there.

Two grouping layers:
1. Deterministic (always, free): casefold + a small alias map merges obvious spellings.
2. AI canonicalization (on Refresh, best-effort): the provider clusters semantic duplicates
   the string rules can't catch ("Linux" vs "Linux-based infrastructure operation"). If the
   AI call fails, the deterministic result stands — Insights never breaks.
"""

from __future__ import annotations

import logging
import re
from collections import Counter

from sqlalchemy.orm import Session

from ..ai import get_provider, prompts
from ..models import Analysis, Insights, ProcessingStatus
from . import prompt_service
from .cv_service import get_active_cv

log = logging.getLogger("jobsearch.insights")

# Small alias map so obvious variants merge into one ranked row instead of fragmenting the
# count. Keys/values are already normalized (casefolded). Extend as patterns show up.
_ALIASES = {
    "k8s": "kubernetes",
    "kube": "kubernetes",
    "gha": "github actions",
    "github action": "github actions",
    "tf": "terraform",
    "iac": "infrastructure as code",
    "ci cd": "ci/cd",
    "cicd": "ci/cd",
    "gcp": "google cloud",
    "aws cloud": "aws",
}


def _normalize(skill: str) -> str:
    """Casefold, collapse whitespace/punctuation noise, and fold known aliases.

    Returns a canonical key used ONLY for grouping/counting; the human-facing label is the
    most common original spelling (tracked separately).
    """
    s = (skill or "").strip().casefold()
    # Normalize separators to single spaces, but keep '/' (e.g. ci/cd, tcp/ip) and '+'/'#'.
    s = re.sub(r"[_\-]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return _ALIASES.get(s, s)


def get_insights(db: Session) -> Insights | None:
    """Return the current stored snapshot (there is at most one), or None."""
    return db.query(Insights).order_by(Insights.id.desc()).first()


def clear_insights(db: Session) -> bool:
    """Delete the stored snapshot. Returns True if one existed. User-initiated only."""
    deleted = db.query(Insights).delete()
    db.commit()
    return bool(deleted)


def refresh_insights(db: Session) -> Insights | None:
    """Recompute the gap aggregation for the active CV and overwrite the snapshot.

    Returns the new snapshot, or None when there is no active CV. Aggregates over ALL done
    analyses for the active CV (dismissed jobs included).
    """
    cv = get_active_cv(db)
    if cv is None:
        return None

    rows = (
        db.query(Analysis)
        .filter(
            Analysis.cv_id == cv.id,
            Analysis.processing_status == ProcessingStatus.done,
        )
        .all()
    )

    counts: Counter[str] = Counter()          # canonical key -> job count
    label_votes: dict[str, Counter] = {}      # canonical key -> {surface spelling: votes}
    severity: dict[str, str] = {}             # canonical key -> basic|average
    why: dict[str, str] = {}                  # canonical key -> representative reason

    for a in rows:
        # Each skill counts at most once per job (a posting listing it twice is still one job).
        seen_this_job: set[str] = set()
        for raw in (a.missing_requirements or []):
            if not isinstance(raw, str) or not raw.strip():
                continue
            key = _normalize(raw)
            if not key or key in seen_this_job:
                continue
            seen_this_job.add(key)
            counts[key] += 1
            label_votes.setdefault(key, Counter())[raw.strip()] += 1

        # Severity + a representative "why" from learning_gaps (basic outranks average).
        for gap in (a.learning_gaps or []):
            if not isinstance(gap, dict) or not gap.get("skill"):
                continue
            key = _normalize(str(gap["skill"]))
            level = str(gap.get("level", "")).strip().casefold()
            if level in ("basic", "average") and (
                key not in severity or (level == "basic" and severity[key] != "basic")
            ):
                severity[key] = level
            if gap.get("why") and key not in why:
                why[key] = str(gap["why"]).strip()

    # Per-key display label = most common surface spelling.
    labels = {
        key: (label_votes[key].most_common(1)[0][0] if label_votes.get(key) else key)
        for key in counts
    }

    # AI canonicalization pass (best-effort) over the distinct display labels, merging
    # semantic duplicates the deterministic layer can't catch. On any failure, keep the
    # deterministic grouping.
    canonical_of = _ai_canonical_map(db, list(labels.values()))

    items = _build_items(counts, labels, severity, why, canonical_of)

    # Overwrite the single stored snapshot.
    db.query(Insights).delete()
    snapshot = Insights(cv_id=cv.id, jobs_analyzed=len(rows), items=items)
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


def _ai_canonical_map(db: Session, display_labels: list[str]) -> dict[str, str]:
    """Return {display_label -> canonical name} from the provider, or {} on failure.

    Best-effort: a provider error, missing key, or malformed response degrades to no
    semantic grouping (the deterministic aggregation stands). The stub returns identity, so
    offline/test runs simply get no extra merging.
    """
    if not display_labels:
        return {}
    try:
        provider = get_provider()
        template = prompt_service.get_template(db, prompts.INSIGHTS_CANONICALIZE)
        mapping = provider.canonicalize_skills(display_labels, template=template)
        # Keep only clean mappings for labels we sent.
        return {
            lbl: mapping[lbl].strip()
            for lbl in display_labels
            if isinstance(mapping.get(lbl), str) and mapping[lbl].strip()
        }
    except Exception:  # never let canonicalization break a refresh
        log.exception("insights canonicalization failed; using deterministic grouping")
        return {}


def _build_items(
    counts: Counter,
    labels: dict[str, str],
    severity: dict[str, str],
    why: dict[str, str],
    canonical_of: dict[str, str],
) -> list[dict]:
    """Fold the deterministic per-key aggregates into final ranked items, applying the AI
    canonical grouping (by display label) on top. Counts sum across merged keys; severity
    takes basic over average; the first non-empty why wins; the display name is the AI
    canonical name when present, else the most common surface spelling."""
    # Group deterministic keys by their canonical cluster name.
    cluster_count: Counter[str] = Counter()
    cluster_display: dict[str, str] = {}
    cluster_severity: dict[str, str] = {}
    cluster_why: dict[str, str] = {}

    # Most-common order first so cluster display/why pick the dominant key's values.
    for key, count in counts.most_common():
        display = labels.get(key, key)
        canonical = canonical_of.get(display, display)
        cluster_key = canonical.casefold()

        cluster_count[cluster_key] += count
        cluster_display.setdefault(cluster_key, canonical)

        sev = severity.get(key)
        if sev and (
            cluster_key not in cluster_severity
            or (sev == "basic" and cluster_severity[cluster_key] != "basic")
        ):
            cluster_severity[cluster_key] = sev
        if why.get(key) and cluster_key not in cluster_why:
            cluster_why[cluster_key] = why[key]

    return [
        {
            "skill": cluster_display[ck],
            "count": count,
            "severity": cluster_severity.get(ck),
            "why": cluster_why.get(ck, ""),
        }
        for ck, count in cluster_count.most_common()
    ]
