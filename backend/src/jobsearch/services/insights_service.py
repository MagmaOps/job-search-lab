"""Insights: aggregate skill gaps across all analyzed jobs for the active CV.

A snapshot, not a live view. `refresh_insights` recomputes from every `done` analysis for
the active CV and overwrites the single stored snapshot; `get_insights` returns it;
`clear_insights` deletes it. Nothing auto-deletes or auto-recomputes it — the user drives
Refresh/Clear from the UI. The computation is pure SQL aggregation + deterministic
normalization (no AI call), so Refresh is fast and free.

Signal source: `analysis.missing_requirements` (what postings wanted that the CV lacks),
ranked by how often each normalized skill appears. Severity comes from
`analysis.learning_gaps` (basic | average) where the same skill was flagged there.
"""

from __future__ import annotations

import re
from collections import Counter

from sqlalchemy.orm import Session

from ..models import Analysis, Insights, ProcessingStatus
from .cv_service import get_active_cv

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

    items = []
    for key, count in counts.most_common():
        label = label_votes[key].most_common(1)[0][0] if label_votes.get(key) else key
        items.append(
            {
                "skill": label,
                "count": count,
                "severity": severity.get(key),
                "why": why.get(key, ""),
            }
        )

    # Overwrite the single stored snapshot.
    db.query(Insights).delete()
    snapshot = Insights(cv_id=cv.id, jobs_analyzed=len(rows), items=items)
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot
