"""AnthropicProvider request shape, checked with a fake client (no network)."""
from __future__ import annotations

import json
from types import SimpleNamespace

from jobsearch.ai.anthropic_provider import AnthropicProvider
from jobsearch.config import Settings

_DIMS = ["technical", "experience", "seniority", "role_alignment", "logistics"]


def test_analyze_disables_thinking_and_recomputes_score():
    sent = {}

    def create(**kwargs):
        sent.update(kwargs)
        body = {
            "match_score": 1,
            "explanation": "ok",
            "dimension_scores": [{"dimension": d, "score": 80, "reason": "x"} for d in _DIMS],
            "caps_applied": [],
        }
        block = SimpleNamespace(type="text", text=json.dumps(body))
        return SimpleNamespace(content=[block], stop_reason="end_turn")

    prov = AnthropicProvider(Settings(anthropic_api_key="x", ai_provider="anthropic"))
    prov._client = SimpleNamespace(messages=SimpleNamespace(create=create))
    res = prov.analyze_job(
        job_title="t", job_description="d", job_language="en", cv_text="cv", effective_profile={}
    )
    # Thinking tokens eat max_tokens on Haiku 5.5 and truncate the JSON.
    assert sent["thinking"] == {"type": "disabled"}
    assert res.match_score == 80  # recomputed from dimensions, not the model's "1"
