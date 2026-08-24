"""LLM client abstraction.

Agents only depend on the narrow `LLMClient` protocol below, never on the
Anthropic SDK directly. This keeps the whole pipeline runnable and unit
testable offline (see `DummyLLMClient`), and keeps the choice of model
provider swappable in one place.
"""
from __future__ import annotations

from typing import Protocol


class LLMClient(Protocol):
    def narrate(self, system: str, user: str) -> str:
        """Return a short natural-language response given a system/user prompt."""
        ...


class DummyLLMClient:
    """Deterministic offline stand-in used for tests and dry runs.

    Does not call any network API. Echoes back a short templated summary
    so the rest of the pipeline has real text to work with.
    """

    def narrate(self, system: str, user: str) -> str:
        return f"[offline-stub] {user.strip().splitlines()[0][:160]}"


class AnthropicLLMClient:
    """Thin wrapper around the Anthropic Messages API."""

    def __init__(self, api_key: str, model: str, max_tokens: int = 512) -> None:
        import anthropic  # imported lazily so the dependency is optional offline

        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens

    def narrate(self, system: str, user: str) -> str:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(
            block.text for block in response.content if block.type == "text"
        ).strip()


def build_llm_client(config) -> LLMClient:
    """Build a real client if an API key is configured, else the offline stub."""
    if config.anthropic_api_key:
        return AnthropicLLMClient(config.anthropic_api_key, config.model_name)
    return DummyLLMClient()
