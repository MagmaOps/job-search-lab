"""Deterministic stub provider used until an Anthropic key is configured.

It does no external calls. It produces a plausible, explainable score by simple keyword
overlap between the job text and the matching profile, so the whole pipeline (collection →
analysis → ranking → dashboard) works end-to-end offline. It never invents qualifications:
matching skills are only those literally present in both the profile and the job text.
"""

from __future__ import annotations

import re

from .base import MatchResult, ProfileExtraction

try:  # langdetect is optional at runtime; degrade gracefully
    from langdetect import detect as _detect_lang
except Exception:  # pragma: no cover
    _detect_lang = None


_DEFAULT_SKILLS = [
    "kubernetes", "docker", "terraform", "aws", "gcp", "azure", "ci/cd",
    "python", "linux", "ansible", "helm", "prometheus", "argocd", "gitops",
]


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9+/#.]+", (text or "").lower()))


class StubProvider:
    model = "stub"

    def extract_profile(
        self, cv_text: str, template: str | None = None
    ) -> ProfileExtraction:
        toks = _tokens(cv_text)
        skills = [s for s in _DEFAULT_SKILLS if s in toks or s.replace("/", "") in toks]
        return ProfileExtraction(
            skills=skills or _DEFAULT_SKILLS[:5],
            seniority="mid",
            years_experience=None,
            summary="Baseline profile derived without an AI key (stub).",
        )

    def analyze_job(
        self,
        *,
        job_title: str,
        job_description: str,
        job_language: str | None,
        cv_text: str,
        effective_profile: dict,
        template: str | None = None,
    ) -> MatchResult:
        text = f"{job_title}\n{job_description}"
        job_toks = _tokens(text)

        must = [s.lower() for s in effective_profile.get("must_have_skills", [])]
        nice = [s.lower() for s in effective_profile.get("nice_to_have_skills", [])]
        derived = [s.lower() for s in effective_profile.get("skills", [])]
        dealbreakers = [s.lower() for s in effective_profile.get("dealbreakers", [])]

        wanted = must + nice + derived
        matched = sorted({s for s in wanted if s and s in job_toks})
        missing = sorted({s for s in must if s and s not in job_toks})

        # Score: weight must-haves heavily, nice-to-haves/derived lightly.
        must_hit = sum(1 for s in must if s in job_toks)
        nice_hit = sum(1 for s in (nice + derived) if s in job_toks)
        must_total = max(len(must), 1)
        score = int(70 * (must_hit / must_total) + min(30, nice_hit * 5))

        # Dealbreakers cap the score hard.
        if any(d in job_toks for d in dealbreakers):
            score = min(score, 10)

        score = max(0, min(100, score))

        lang = job_language
        if not lang and _detect_lang:
            try:
                lang = _detect_lang(text) if text.strip() else None
            except Exception:
                lang = None

        explanation = (
            f"Stub analysis: matched {len(matched)} profile skill(s)"
            + (f", missing must-haves: {', '.join(missing)}" if missing else "")
            + ". Configure an Anthropic key for real analysis."
        )

        return MatchResult(
            match_score=score,
            explanation=explanation,
            matching_skills=matched,
            missing_requirements=missing,
            detected_language=lang,
            translated_summary=None,
            model=self.model,
        )
