"""Resolve a router tier ("local-fast", ...) to an installed model."""

from collections.abc import Callable

import httpx

from universe_models.ollama import OllamaClient


class NoModelAvailable(RuntimeError):
    def __init__(self, message: str, hint: str) -> None:
        super().__init__(message)
        self.hint = hint


class ModelRouter:
    def __init__(
        self,
        ollama: OllamaClient,
        *,
        assignment: Callable[[str], str | None],
        override: str | None = None,
        preferences: Callable[[str], list[str]] | None = None,
    ) -> None:
        self._ollama = ollama
        self._assignment = assignment
        self._override = override
        self._preferences = preferences or (lambda _tier: [])

    async def resolve(self, tier: str, *, needs_tools: bool = False) -> str:
        """The model for a tier. `needs_tools`: only models that can call tools (agents with tools need one)."""
        try:
            models = await self._ollama.list_models()
        except httpx.HTTPError as exc:
            raise NoModelAvailable(
                f"Ollama is not reachable at {self._ollama.base_url}",
                "Install Ollama from https://ollama.com/download and start it, or let UNIVERSE start it.",
            ) from exc
        chat_models = [
            m.name for m in models if "completion" in m.capabilities and (not needs_tools or "tools" in m.capabilities)
        ]
        if needs_tools and not chat_models and any("completion" in m.capabilities for m in models):
            raise NoModelAvailable(
                "None of the installed chat models can call tools, which agents need",
                "Run: ollama pull qwen3:8b (or another model whose Ollama page lists 'tools')",
            )
        installed = set(chat_models)

        def is_installed(tag: str) -> bool:
            return tag in installed or f"{tag}:latest" in installed

        if self._override:
            if is_installed(self._override):
                return self._override
            raise NoModelAvailable(
                f"UNIVERSE_MODEL_FAST is set to '{self._override}', which is not installed",
                f"Run: ollama pull {self._override}",
            )
        assigned = self._assignment(tier)
        if assigned and is_installed(assigned):
            return assigned
        preferences = self._preferences(tier)
        for tag in preferences:
            if is_installed(tag):
                return tag
        if chat_models:
            return chat_models[0]
        suggestion = preferences[0] if preferences else "gemma4:e4b"
        raise NoModelAvailable("No chat model is installed in Ollama", f"Run: ollama pull {suggestion}")
