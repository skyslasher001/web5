"""Client for Ollama's native API (model listing, capabilities). Chat uses the OpenAI-compatible API."""

import time

import httpx
from pydantic import Field

from universe_common.egress import EgressGate
from universe_common.schema import ApiModel


class InstalledModel(ApiModel):
    name: str
    digest: str = ""
    size_bytes: int | None = None
    family: str | None = None
    parameter_size: str | None = None
    quantization: str | None = None
    capabilities: list[str] = Field(default_factory=list)


class OllamaStatus(ApiModel):
    reachable: bool
    version: str | None = None
    url: str
    error: str | None = None


class OllamaClient:
    def __init__(self, base_url: str, gate: EgressGate, *, cache_s: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._http = gate.async_client(purpose="ollama", local_only=True, base_url=self.base_url, timeout=10.0)
        self._cache_s = cache_s
        self._models: tuple[float, list[InstalledModel]] | None = None
        self._capability_cache: dict[tuple[str, str], list[str]] = {}  # (name, digest) -> capabilities

    async def aclose(self) -> None:
        await self._http.aclose()

    async def status(self) -> OllamaStatus:
        try:
            response = await self._http.get("/api/version")
            response.raise_for_status()
            return OllamaStatus(reachable=True, version=response.json().get("version"), url=self.base_url)
        except (httpx.HTTPError, ValueError) as exc:
            return OllamaStatus(reachable=False, url=self.base_url, error=str(exc) or type(exc).__name__)

    async def _capabilities(self, raw: dict, name: str, family: str | None) -> list[str]:
        listed = raw.get("capabilities")
        if isinstance(listed, list):  # Ollama ≥ 0.12 includes capabilities in /api/tags
            return [str(c) for c in listed]
        key = (name, str(raw.get("digest") or ""))
        if key in self._capability_cache:
            return self._capability_cache[key]
        try:
            response = await self._http.post("/api/show", json={"model": name})
            response.raise_for_status()
            caps = response.json().get("capabilities")
            if isinstance(caps, list):
                self._capability_cache[key] = [str(c) for c in caps]
                return self._capability_cache[key]
        except (httpx.HTTPError, ValueError):
            pass
        # Older Ollama builds don't report capabilities; BERT-family models are embedders. Not cached.
        return ["embedding"] if family and "bert" in family.lower() else ["completion"]

    async def list_models(self, *, refresh: bool = False) -> list[InstalledModel]:
        now = time.monotonic()
        if not refresh and self._models and now - self._models[0] < self._cache_s:
            return self._models[1]
        response = await self._http.get("/api/tags")
        response.raise_for_status()
        models = []
        for raw in response.json().get("models", []):
            details = raw.get("details") or {}
            family = details.get("family")
            name = raw.get("name") or raw.get("model")
            models.append(
                InstalledModel(
                    name=name,
                    digest=str(raw.get("digest") or ""),
                    size_bytes=raw.get("size"),
                    family=family,
                    parameter_size=details.get("parameter_size"),
                    quantization=details.get("quantization_level"),
                    capabilities=await self._capabilities(raw, name, family),
                )
            )
        self._models = (now, models)
        return models

    async def embed(self, model: str, texts: list[str], *, request_timeout_s: float = 10.0) -> list[list[float]]:
        """Text embeddings via /api/embed (used for search queries; workers embed documents)."""
        response = await self._http.post(
            "/api/embed",
            json={"model": model, "input": texts, "truncate": True, "keep_alive": "5m"},
            timeout=request_timeout_s,
        )
        response.raise_for_status()
        vectors = response.json().get("embeddings")
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise httpx.DecodingError("unexpected embedding payload from Ollama")
        return vectors
