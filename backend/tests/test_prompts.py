import pytest

from jobsearch.ai import prompts
from jobsearch.services import prompt_service


def test_validate_accepts_default_templates():
    prompts.validate(prompts.PROFILE, prompts.DEFAULT_PROFILE_PROMPT)
    prompts.validate(prompts.ANALYZE, prompts.DEFAULT_ANALYZE_PROMPT)


def test_validate_rejects_missing_required_placeholder():
    with pytest.raises(prompts.PromptValidationError):
        prompts.validate(prompts.ANALYZE, "Score this. CV: {cv} profile {profile} title {title}")
        # missing {description}


def test_validate_rejects_unknown_placeholder():
    with pytest.raises(prompts.PromptValidationError):
        prompts.validate(prompts.PROFILE, "Use {cv} and {salary}")  # {salary} unknown


def test_validate_rejects_empty():
    with pytest.raises(prompts.PromptValidationError):
        prompts.validate(prompts.PROFILE, "   ")


def test_render_formats_values():
    out = prompts.render(prompts.PROFILE, "CV is: {cv}", cv="hello")
    assert out == "CV is: hello"


def test_service_get_returns_default_when_unset(db):
    assert prompt_service.get_template(db, prompts.PROFILE) == prompts.DEFAULT_PROFILE_PROMPT


def test_service_set_then_get_roundtrip(db):
    custom = "Extract from this CV only: {cv}"
    prompt_service.set_template(db, prompts.PROFILE, custom)
    assert prompt_service.get_template(db, prompts.PROFILE) == custom
    listed = {p["key"]: p for p in prompt_service.list_prompts(db)}
    assert listed[prompts.PROFILE]["is_customized"] is True


def test_service_set_invalid_raises_and_does_not_store(db):
    with pytest.raises(prompts.PromptValidationError):
        prompt_service.set_template(db, prompts.ANALYZE, "no placeholders here")
    # still default
    assert prompt_service.get_template(db, prompts.ANALYZE) == prompts.DEFAULT_ANALYZE_PROMPT


def test_service_reset_restores_default(db):
    prompt_service.set_template(db, prompts.PROFILE, "Custom {cv}")
    prompt_service.reset_template(db, prompts.PROFILE)
    assert prompt_service.get_template(db, prompts.PROFILE) == prompts.DEFAULT_PROFILE_PROMPT
