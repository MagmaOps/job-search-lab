"""AI provider abstraction and factory."""

from __future__ import annotations

from ..config import Settings, get_settings
from .base import AIProvider, MatchResult
from .stub import StubProvider


def get_provider(settings: Settings | None = None) -> AIProvider:
    """Return the configured provider, falling back to the stub when no key is set."""
    settings = settings or get_settings()
    if settings.ai_enabled:
        # Imported lazily so the anthropic SDK isn't required for stub-only runs/tests.
        from .anthropic_provider import AnthropicProvider

        return AnthropicProvider(settings)
    return StubProvider()


__all__ = ["AIProvider", "MatchResult", "StubProvider", "get_provider"]
