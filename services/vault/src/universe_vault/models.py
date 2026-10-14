"""Which models the pipeline uses, and a small synchronous Ollama client for workers (egress-gated).

- Text embeddings: the `embed_text` assignment, or else the first installed embedding model (they're small
  and only used for this), preferring the loadout candidates.
- Captions: only with an explicit `vision` assignment. A VLM on every photo is heavy, so it's opt-in.
"""

import base64
import io
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import httpx
from PIL import Image

from universe_common.egress import EgressGate

PREFERRED_EMBEDDERS = ("qwen3-embedding", "nomic-embed-text", "mxbai-embed-large", "bge-m3", "all-minilm")
CAPTION_PROMPT = (
    "Describe this image in one or two plain sentences for a search index: the main subjects, the setting, "
    "any readable text, and notable colors. No preamble."
)


@dataclass(frozen=True)
class ModelInfo:
    name: str
    digest: str
    capabilities: tuple[str, ...]


def assignment(conn: sqlite3.Connection, tier: str) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (f"model.{tier}",)).fetchone()
    return row["value"] if row else None


def _matches(model: str, wanted: str) -> bool:
    return model == wanted or model == f"{wanted}:latest" or model.split(":")[0] == wanted


def pick_embedder(models: list[ModelInfo], assigned: str | None) -> ModelInfo | None:
    embedders = [m for m in models if "embedding" in m.capabilities]
    if assigned:
        return next((m for m in models if _matches(m.name, assigned)), None)
    for family in PREFERRED_EMBEDDERS:
        for model in embedders:
            if model.name.split(":")[0] == family:
                return model
    return embedders[0] if embedders else None


def pick_vision(models: list[ModelInfo], assigned: str | None) -> ModelInfo | None:
    if not assigned:
        return None
    return next((m for m in models if _matches(m.name, assigned) and "vision" in m.capabilities), None)


def doc_prefix(model: str) -> str:
    """Some embedders want task prefixes (nomic-embed-text documents them); others take raw text."""
    return "search_document: " if model.startswith("nomic-embed-text") else ""


def query_prefix(model: str) -> str:
    if model.startswith("nomic-embed-text"):
        return "search_query: "
    if model.startswith("qwen3-embedding"):
        return "Instruct: Given a search query, retrieve relevant passages from my notes and files\nQuery: "
    return ""


class OllamaUnavailable(RuntimeError):
    pass


class SyncOllama:
    def __init__(self, base_url: str, gate: EgressGate | None = None, *, timeout: float = 120.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._http = (gate or EgressGate()).client(
            purpose="ollama", local_only=True, base_url=self.base_url, timeout=timeout
        )
        self._caps: dict[tuple[str, str], tuple[str, ...]] = {}

    def close(self) -> None:
        self._http.close()

    def models(self) -> list[ModelInfo]:
        try:
            response = self._http.get("/api/tags", timeout=10)
            response.raise_for_status()
            raw_models = response.json().get("models", [])
        except (httpx.HTTPError, ValueError) as exc:
            raise OllamaUnavailable(f"Ollama is not reachable at {self.base_url}: {exc}") from exc
        out = []
        for raw in raw_models:
            name = raw.get("name") or raw.get("model") or ""
            digest = str(raw.get("digest") or "")
            caps = raw.get("capabilities")
            if not isinstance(caps, list):
                caps = list(self._show_capabilities(name, digest))
            out.append(ModelInfo(name, digest, tuple(str(c) for c in caps)))
        return out

    def _show_capabilities(self, name: str, digest: str) -> tuple[str, ...]:
        key = (name, digest)
        if key not in self._caps:
            try:
                response = self._http.post("/api/show", json={"model": name}, timeout=10)
                response.raise_for_status()
                caps = response.json().get("capabilities")
                self._caps[key] = tuple(str(c) for c in caps) if isinstance(caps, list) else ("completion",)
            except (httpx.HTTPError, ValueError):
                return ("completion",)
        return self._caps[key]

    def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        try:
            response = self._http.post(
                "/api/embed", json={"model": model, "input": texts, "truncate": True, "keep_alive": "5m"}
            )
        except httpx.HTTPError as exc:
            raise OllamaUnavailable(f"embedding request failed: {exc}") from exc
        if response.status_code >= 400:
            raise RuntimeError(f"Ollama embed returned {response.status_code}: {response.text[:300]}")
        vectors = response.json().get("embeddings")
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise RuntimeError("Ollama returned an unexpected embedding payload")
        return vectors

    def caption(self, model: str, image_path: Path) -> str:
        with Image.open(image_path) as img:
            img = img.convert("RGB")
            img.thumbnail((1024, 1024))
            buffer = io.BytesIO()
            img.save(buffer, "JPEG", quality=85)
        body = {
            "model": model,
            "messages": [
                {"role": "user", "content": CAPTION_PROMPT, "images": [base64.b64encode(buffer.getvalue()).decode()]}
            ],
            "stream": False,
            "keep_alive": "2m",
            "options": {"temperature": 0.2, "num_predict": 120},
        }
        try:
            response = self._http.post("/api/chat", json=body)
        except httpx.HTTPError as exc:
            raise OllamaUnavailable(f"caption request failed: {exc}") from exc
        if response.status_code >= 400:
            raise RuntimeError(f"Ollama chat returned {response.status_code}: {response.text[:300]}")
        return str((response.json().get("message") or {}).get("content") or "").strip()
