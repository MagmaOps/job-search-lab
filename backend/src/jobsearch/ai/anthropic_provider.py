"""Anthropic-backed AI provider. Enabled only when ANTHROPIC_API_KEY is set.

Guardrail baked into the prompts: score strictly from the CV and the explicit matching
profile; never invent qualifications or experience the candidate does not have.
"""

from __future__ import annotations

import json

from ..config import Settings
from . import prompts
from .base import ApplicationDraft, DimensionScore, MatchResult, ProfileExtraction


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
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            # A truncated response (hit max_tokens mid-string) or non-JSON output. Surface a
            # clear, actionable message instead of the raw "Unterminated string" parse error.
            stop = getattr(msg, "stop_reason", None)
            hint = (
                " (model output was truncated — raise max_tokens)"
                if stop == "max_tokens"
                else ""
            )
            raise ValueError(f"AI did not return valid JSON{hint}: {exc}") from None

    def extract_profile(
        self, cv_text: str, template: str | None = None
    ) -> ProfileExtraction:
        tmpl = template or prompts.DEFAULT_PROFILE_PROMPT
        # Profile extraction now returns skills + languages + summary, which can exceed the
        # default 1024-token budget and truncate the JSON; give it room.
        data = self._complete_json(
            prompts.render(prompts.PROFILE, tmpl, cv=cv_text[:12000]),
            max_tokens=2048,
        )
        return ProfileExtraction(
            skills=list(data.get("skills") or []),
            seniority=data.get("seniority"),
            years_experience=data.get("years_experience"),
            languages=[lang for lang in (data.get("languages") or []) if isinstance(lang, dict)],
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
        # The analyze response carries explanation + a 4-row dimension_scores breakdown +
        # eligibility fields + translated_summary; 1800 tokens truncated the JSON, so give
        # it headroom.
        data = self._complete_json(prompt, max_tokens=3000)
        score = int(data.get("match_score", 0))
        score = max(0, min(100, score))
        return MatchResult(
            match_score=score,
            explanation=str(data.get("explanation", "")),
            matching_skills=list(data.get("matching_skills") or []),
            missing_requirements=list(data.get("missing_requirements") or []),
            detected_language=data.get("detected_language") or job_language,
            translated_summary=data.get("translated_summary"),
            dimension_scores=_parse_dimensions(data.get("dimension_scores")),
            posting_country=data.get("posting_country") or None,
            eligibility=_norm_eligibility(data.get("eligibility")),
            eligibility_note=data.get("eligibility_note") or None,
            model=self.model,
        )

    def generate_application(
        self,
        *,
        job_title: str,
        job_description: str,
        cv_text: str,
        effective_profile: dict,
        draft_template: str | None = None,
        review_template: str | None = None,
        revise_template: str | None = None,
    ) -> ApplicationDraft:
        profile_json = json.dumps(effective_profile, ensure_ascii=False)
        cv = cv_text[:12000]
        description = (job_description or "")[:12000]

        # Pass 1 — draft. Long Markdown output: budget generously to avoid JSON truncation.
        draft_tmpl = draft_template or prompts.DEFAULT_APPLICATION_PROMPT
        draft = self._complete_json(
            prompts.render(
                prompts.APPLICATION,
                draft_tmpl,
                profile=profile_json,
                cv=cv,
                title=job_title,
                description=description,
            ),
            max_tokens=4000,
        )
        cover_letter = str(draft.get("cover_letter_md", "")).strip()
        cv_summary = str(draft.get("cv_summary_md", "")).strip()

        # Pass 2 — reviewer critique (grounding audit + quality suggestions).
        review_tmpl = review_template or prompts.DEFAULT_APPLICATION_REVIEW_PROMPT
        review = self._complete_json(
            prompts.render(
                prompts.APPLICATION_REVIEW,
                review_tmpl,
                profile=profile_json,
                cv=cv,
                title=job_title,
                cover_letter=cover_letter,
                cv_summary=cv_summary,
            ),
            max_tokens=2000,
        )
        grounding = [str(x) for x in (review.get("grounding_issues") or [])]
        suggestions = [str(x) for x in (review.get("suggestions") or [])]
        reviewer_notes = _format_review_notes(grounding, suggestions)

        # Pass 3 — revise once, applying the critique while keeping the never-invent rule.
        if grounding or suggestions:
            revise_tmpl = revise_template or prompts.DEFAULT_APPLICATION_REVISE_PROMPT
            revised = self._complete_json(
                prompts.render(
                    prompts.APPLICATION_REVISE,
                    revise_tmpl,
                    profile=profile_json,
                    cv=cv,
                    title=job_title,
                    description=description,
                    cover_letter=cover_letter,
                    cv_summary=cv_summary,
                    critique=reviewer_notes,
                ),
                max_tokens=4000,
            )
            cover_letter = str(revised.get("cover_letter_md", "")).strip() or cover_letter
            cv_summary = str(revised.get("cv_summary_md", "")).strip() or cv_summary

        return ApplicationDraft(
            cover_letter_md=cover_letter,
            cv_summary_md=cv_summary,
            reviewer_notes=reviewer_notes,
            model=self.model,
        )


def _format_review_notes(grounding: list[str], suggestions: list[str]) -> str:
    """Render the reviewer's JSON critique into readable Markdown for storage/UI."""
    parts: list[str] = []
    if grounding:
        parts.append(
            "**Grounding issues**\n"
            + "\n".join(f"- {g}" for g in grounding)
        )
    if suggestions:
        parts.append(
            "**Suggestions**\n" + "\n".join(f"- {s}" for s in suggestions)
        )
    if not parts:
        return "Reviewer found no grounding issues and no further suggestions."
    return "\n\n".join(parts)


def _norm_eligibility(value: object) -> str | None:
    """Coerce the model's eligibility verdict to one of the allowed values, else None."""
    v = str(value or "").strip().lower()
    return v if v in ("worldwide", "restricted", "unclear") else None


def _parse_dimensions(raw: object) -> list[DimensionScore]:
    """Coerce the model's dimension_scores array into DimensionScore objects, tolerantly."""
    out: list[DimensionScore] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict) or not item.get("dimension"):
            continue
        try:
            dim_score = max(0, min(100, int(item.get("score", 0))))
            weight = float(item.get("weight", 0) or 0)
        except (TypeError, ValueError):
            continue
        out.append(
            DimensionScore(
                dimension=str(item["dimension"]),
                score=dim_score,
                weight=weight,
                reason=str(item.get("reason", "")),
            )
        )
    return out
