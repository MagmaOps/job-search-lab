"""Anthropic-backed AI provider. Enabled only when ANTHROPIC_API_KEY is set.

Guardrail baked into the prompts: score strictly from the CV and the explicit matching
profile; never invent qualifications or experience the candidate does not have.
"""

from __future__ import annotations

import json

from ..config import Settings
from . import prompts
from .base import MatchResult, ProfileExtraction


class AnthropicProvider:
    def __init__(self, settings: Settings) -> None:
        from anthropic import Anthropic

        self._client = Anthropic(api_key=settings.anthropic_api_key)
        self.model = settings.ai_model

    def _complete_json(self, prompt: str, max_tokens: int = 1024) -> dict:
        msg = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(
            block.text for block in msg.content if getattr(block, "type", "") == "text"
        ).strip()
        # Be tolerant of code fences around the JSON.
        if text.startswith("```"):
            text = text.strip("`")
            text = text[text.find("{") : text.rfind("}") + 1]
        return json.loads(text)

    def extract_profile(
        self, cv_text: str, template: str | None = None
    ) -> ProfileExtraction:
        tmpl = template or prompts.DEFAULT_PROFILE_PROMPT
        data = self._complete_json(
            prompts.render(prompts.PROFILE, tmpl, cv=cv_text[:12000])
        )
        return ProfileExtraction(
            skills=list(data.get("skills") or []),
            seniority=data.get("seniority"),
            years_experience=data.get("years_experience"),
            summary=data.get("summary"),
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
        tmpl = template or prompts.DEFAULT_ANALYZE_PROMPT
        prompt = prompts.render(
            prompts.ANALYZE,
            tmpl,
            profile=json.dumps(effective_profile, ensure_ascii=False),
            cv=cv_text[:12000],
            title=job_title,
            description=(job_description or "")[:12000],
        )
        data = self._complete_json(prompt, max_tokens=1500)
        score = int(data.get("match_score", 0))
        score = max(0, min(100, score))
        return MatchResult(
            match_score=score,
            explanation=str(data.get("explanation", "")),
            matching_skills=list(data.get("matching_skills") or []),
            missing_requirements=list(data.get("missing_requirements") or []),
            detected_language=data.get("detected_language") or job_language,
            translated_summary=data.get("translated_summary"),
            model=self.model,
        )
