"""API shapes for vault items, jobs, search and backups (Pydantic → OpenAPI → shared TS types)."""

from typing import Any, Literal

from pydantic import Field

from universe_common.schema import ApiModel
from universe_vault.filetypes import ItemType

ItemStatus = Literal["inbox", "triaged", "active", "archived"]
PipelineStatus = Literal["pending", "processing", "done", "failed"]
StageStatus = Literal["pending", "running", "done", "failed", "skipped"]


class ItemStage(ApiModel):
    stage: str
    status: StageStatus
    model: str | None = None
    model_version: str | None = None
    attempts: int = 0
    error: str | None = None
    detail: str | None = None
    updated_at: str


class ItemSummary(ApiModel):
    id: str
    type: ItemType
    title: str
    status: ItemStatus
    path: str
    mime: str | None = None
    size_bytes: int
    captured_at: str
    created_at: str
    updated_at: str
    pinned: bool
    open_count: int
    last_opened_at: str | None = None
    pipeline_status: PipelineStatus
    has_thumbnail: bool
    project_ids: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    trashed_at: str | None = None


class ItemVersion(ApiModel):
    n: int
    content_hash: str
    size_bytes: int
    created_by: str
    note: str
    created_at: str


class ItemSource(ApiModel):
    kind: str
    origin: str | None = None
    created_at: str


class Item(ItemSummary):
    metadata: dict[str, Any] = Field(default_factory=dict)
    summary: str
    current_version: int
    content_hash: str
    source: ItemSource | None = None
    stages: list[ItemStage] = Field(default_factory=list)
    versions: list[ItemVersion] = Field(default_factory=list)


class ItemPage(ApiModel):
    items: list[ItemSummary]
    next_cursor: str | None = None
    total: int | None = None  # how many match the filters; on the first page only (later pages skip the count)


class ItemText(ApiModel):
    item_id: str
    text: str
    truncated: bool
    chunks: int


class FilterChip(ApiModel):
    kind: Literal["type", "date", "project"]
    label: str
    value: str


class ParsedQuery(ApiModel):
    text: str
    types: list[ItemType] = Field(default_factory=list)
    date_from: str | None = None
    date_to: str | None = None
    project_ids: list[str] = Field(default_factory=list)
    chips: list[FilterChip] = Field(default_factory=list)


class SearchHit(ApiModel):
    item: ItemSummary
    score: float
    snippet: str | None = None
    matched: list[Literal["title", "text", "trigram", "vector"]] = Field(default_factory=list)


class SearchResponse(ApiModel):
    query: str
    mode: Literal["keyword", "hybrid"]
    semantic: bool
    semantic_note: str | None = None
    parsed: ParsedQuery
    hits: list[SearchHit]
    took_ms: float
    timings_ms: dict[str, float] = Field(default_factory=dict)


class JobInfo(ApiModel):
    id: str
    kind: str
    item_id: str | None = None
    priority_class: Literal["realtime", "interactive", "background"]
    priority: int
    status: Literal["queued", "leased", "succeeded", "dead", "cancelled"]
    attempts: int
    max_attempts: int
    run_after: str
    progress: float
    error: str | None = None
    created_at: str
    updated_at: str
    finished_at: str | None = None


class QueueStats(ApiModel):
    queued: int
    leased: int
    dead: int
    succeeded_last_hour: int
    by_kind: dict[str, int] = Field(default_factory=dict)
    paused: bool
    pause_reason: str | None = None
    model_hold: bool
    workers: int
