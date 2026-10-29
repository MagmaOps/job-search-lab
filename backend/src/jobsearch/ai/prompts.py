"""Editable prompt templates: defaults, required placeholders, and safe formatting.

The two prompts Claude receives live here as defaults. They can be overridden and persisted
via the API/UI (see services/prompt_service.py). Each template declares which placeholders
it REQUIRES so a saved template that would break analysis is rejected before it is stored.
"""

from __future__ import annotations

import re
import string
from dataclasses import dataclass

# Prompt keys used across the codebase.
PROFILE = "profile"
ANALYZE = "analyze"


@dataclass(frozen=True)
class PromptSpec:
    key: str
    label: str
    description: str
    required_placeholders: frozenset[str]
    default: str


DEFAULT_PROFILE_PROMPT = """You extract a concise, factual skills profile from a CV.
Return ONLY JSON with keys: skills (array of strings), seniority (string or null),
years_experience (integer or null), summary (short string).
Do not invent anything not supported by the CV text.

CV:
{cv}
"""

DEFAULT_ANALYZE_PROMPT = """You evaluate how well a job matches a candidate.
Rules:
- Score 0-100 based ONLY on evidence in the CV and the matching profile.
- NEVER invent qualifications or experience the candidate does not have.
- matching_skills: only skills present in BOTH the profile/CV and the job.
- missing_requirements: must-have/required items the candidate lacks.
- Detect the job language. If it is not English, provide a short English
  translated_summary; otherwise translated_summary may be null.

Return ONLY JSON with keys: match_score (int), explanation (string),
matching_skills (array), missing_requirements (array), detected_language (string),
translated_summary (string or null).

Matching profile (JSON):
{profile}

Candidate CV:
{cv}

Job title: {title}
Job description:
{description}
"""


SPECS: dict[str, PromptSpec] = {
    PROFILE: PromptSpec(
        key=PROFILE,
        label="CV profile extraction",
        description=(
            "Turns raw CV text into a structured skills profile. Must return JSON with "
            "skills, seniority, years_experience, summary."
        ),
        required_placeholders=frozenset({"cv"}),
        default=DEFAULT_PROFILE_PROMPT,
    ),
    ANALYZE: PromptSpec(
        key=ANALYZE,
        label="Job analysis / scoring",
        description=(
            "Scores a job against the CV + matching profile. Must return JSON with "
            "match_score, explanation, matching_skills, missing_requirements, "
            "detected_language, translated_summary."
        ),
        required_placeholders=frozenset({"profile", "cv", "title", "description"}),
        default=DEFAULT_ANALYZE_PROMPT,
    ),
}


class PromptValidationError(ValueError):
    """Raised when a template is missing required or contains unknown placeholders."""


def _placeholders(template: str) -> set[str]:
    """Field names referenced by str.format in the template (ignores '{{' escapes)."""
    names: set[str] = set()
    for _, field_name, _, _ in string.Formatter().parse(template):
        if field_name:
            # take the base name before any attribute/index access
            base = re.split(r"[.\[]", field_name, maxsplit=1)[0]
            if base:
                names.add(base)
    return names


def validate(key: str, template: str) -> None:
    """Validate a template for a given prompt key. Raises PromptValidationError."""
    spec = SPECS.get(key)
    if spec is None:
        raise PromptValidationError(f"Unknown prompt '{key}'.")
    if not template.strip():
        raise PromptValidationError("Template must not be empty.")

    try:
        found = _placeholders(template)
    except ValueError as exc:  # malformed braces
        raise PromptValidationError(f"Malformed placeholder syntax: {exc}") from None

    missing = spec.required_placeholders - found
    if missing:
        raise PromptValidationError(
            "Missing required placeholder(s): "
            + ", ".join("{" + m + "}" for m in sorted(missing))
        )
    unknown = found - spec.required_placeholders
    if unknown:
        raise PromptValidationError(
            "Unknown placeholder(s) not allowed: "
            + ", ".join("{" + u + "}" for u in sorted(unknown))
            + ". Allowed: "
            + ", ".join("{" + p + "}" for p in sorted(spec.required_placeholders))
        )


def render(key: str, template: str, **values: str) -> str:
    """Format a validated template with the provided values.

    Validates first so a corrupted stored template fails loudly (and is caught per-job by
    the analysis service) rather than producing a malformed prompt.
    """
    validate(key, template)
    return template.format(**values)
