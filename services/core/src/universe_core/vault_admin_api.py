"""REST API for watched folders and backups (Phase 2). Session token only."""

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from universe_common.ids import uuid7
from universe_common.schema import ApiModel
from universe_common.timeutil import utcnow
from universe_core.backups import (
    BackupConfigRequest,
    BackupRecord,
    BackupService,
    BackupStatus,
    RestoreRequest,
    Snapshot,
)
from universe_core.context import CoreContext
from universe_vault.backup import BackupError

router = APIRouter(prefix="/api/v1")


def get_ctx(request: Request) -> CoreContext:
    return request.app.state.ctx


Ctx = Annotated[CoreContext, Depends(get_ctx)]
Glob = Annotated[str, Field(min_length=1, max_length=200)]


# ---------- watched folders ----------


class WatchedFolder(ApiModel):
    id: str
    path: str
    recursive: bool
    include_globs: list[str]
    exclude_globs: list[str]
    default_project_id: str | None = None
    enabled: bool
    exists: bool
    last_scan_at: str | None = None
    last_error: str | None = None
    created_at: str


class WatchedFolderCreate(BaseModel):
    path: str = Field(min_length=1, max_length=4096)
    recursive: bool = True
    include_globs: list[Glob] = Field(default_factory=list, max_length=50)
    exclude_globs: list[Glob] = Field(default_factory=list, max_length=50)
    default_project_id: str | None = None


class WatchedFolderPatch(BaseModel):
    enabled: bool | None = None
    recursive: bool | None = None
    include_globs: list[Glob] | None = Field(default=None, max_length=50)
    exclude_globs: list[Glob] | None = Field(default=None, max_length=50)
    default_project_id: str | None = None


def _folder(row: sqlite3.Row) -> WatchedFolder:
    return WatchedFolder(
        id=row["id"],
        path=row["path"],
        recursive=bool(row["recursive"]),
        include_globs=json.loads(row["include_globs"]),
        exclude_globs=json.loads(row["exclude_globs"]),
        default_project_id=row["default_project_id"],
        enabled=bool(row["enabled"]),
        exists=Path(row["path"]).is_dir(),
        last_scan_at=row["last_scan_at"],
        last_error=row["last_error"],
        created_at=row["created_at"],
    )


def _get_folder(ctx: CoreContext, folder_id: str) -> sqlite3.Row:
    row = ctx.dbs.universe.execute("SELECT * FROM watched_folders WHERE id = ?", (folder_id,)).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such watched folder")
    return row


@router.get("/watched-folders", response_model=list[WatchedFolder])
async def list_watched(ctx: Ctx) -> list[WatchedFolder]:
    rows = ctx.dbs.universe.execute("SELECT * FROM watched_folders ORDER BY created_at").fetchall()
    return [_folder(r) for r in rows]


@router.post("/watched-folders", response_model=WatchedFolder, status_code=status.HTTP_201_CREATED)
async def add_watched(ctx: Ctx, body: WatchedFolderCreate) -> WatchedFolder:
    def check(raw: str) -> Path | None:
        candidate = Path(raw).expanduser()
        return candidate.resolve() if candidate.is_absolute() and candidate.is_dir() else None

    path = await asyncio.to_thread(check, body.path)
    if path is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Choose an existing folder (absolute path)")
    if ctx.vault.contains(path):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "That folder is inside the vault; the vault is watched already"
        )
    if ctx.dbs.universe.execute("SELECT 1 FROM watched_folders WHERE path = ?", (str(path),)).fetchone():
        raise HTTPException(status.HTTP_409_CONFLICT, "That folder is already watched")
    folder_id = uuid7()
    now = utcnow()
    ctx.dbs.universe.execute(
        "INSERT INTO watched_folders (id, path, recursive, include_globs, exclude_globs, default_project_id,"
        " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            folder_id,
            str(path),
            int(body.recursive),
            json.dumps(body.include_globs),
            json.dumps(body.exclude_globs),
            body.default_project_id,
            now,
            now,
        ),
    )
    ctx.audit.append(
        actor="user", action="setting.changed", target_type="watched_folder", target_id=folder_id, details={}
    )
    ctx.refresh_watched(scan=True, only=folder_id)
    return _folder(_get_folder(ctx, folder_id))


@router.patch("/watched-folders/{folder_id}", response_model=WatchedFolder)
async def patch_watched(ctx: Ctx, folder_id: str, body: WatchedFolderPatch) -> WatchedFolder:
    _get_folder(ctx, folder_id)
    updates: dict[str, object] = {}
    if body.enabled is not None:
        updates["enabled"] = int(body.enabled)
    if body.recursive is not None:
        updates["recursive"] = int(body.recursive)
    if body.include_globs is not None:
        updates["include_globs"] = json.dumps(body.include_globs)
    if body.exclude_globs is not None:
        updates["exclude_globs"] = json.dumps(body.exclude_globs)
    if "default_project_id" in body.model_fields_set:
        updates["default_project_id"] = body.default_project_id
    if updates:
        assignments = ", ".join(f"{k} = ?" for k in updates)
        ctx.dbs.universe.execute(
            f"UPDATE watched_folders SET {assignments}, updated_at = ? WHERE id = ?",  # noqa: S608 - fixed columns
            (*updates.values(), utcnow(), folder_id),
        )
        ctx.refresh_watched(scan=bool(body.enabled), only=folder_id)
    return _folder(_get_folder(ctx, folder_id))


@router.delete("/watched-folders/{folder_id}", response_model=WatchedFolder)
async def remove_watched(ctx: Ctx, folder_id: str) -> WatchedFolder:
    row = _get_folder(ctx, folder_id)
    ctx.dbs.universe.execute("DELETE FROM watched_folders WHERE id = ?", (folder_id,))
    ctx.refresh_watched()
    return _folder(row)  # items already imported stay in the vault


@router.post("/watched-folders/{folder_id}/scan", response_model=WatchedFolder)
async def scan_watched(ctx: Ctx, folder_id: str) -> WatchedFolder:
    row = _get_folder(ctx, folder_id)
    if not row["enabled"]:
        raise HTTPException(status.HTTP_409_CONFLICT, "Turn the folder on first")
    ctx.refresh_watched(scan=True, only=folder_id)
    return _folder(row)


# ---------- backups ----------


class Started(ApiModel):
    started: bool


def _backups(ctx: CoreContext) -> BackupService:
    if ctx.backups is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Backups are unavailable")
    return ctx.backups


@router.get("/backups/status", response_model=BackupStatus)
async def backup_status(ctx: Ctx) -> BackupStatus:
    return await _backups(ctx).status()


@router.put("/backups/config", response_model=BackupStatus)
async def configure_backups(ctx: Ctx, body: BackupConfigRequest) -> BackupStatus:
    try:
        result = await _backups(ctx).configure(body)
    except BackupError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    ctx.audit.append(
        actor="user",
        action="setting.changed",
        target_type="setting",
        target_id="backup.config",
        details={"enabled": body.enabled},
    )
    return result


@router.post("/backups/run", response_model=Started, status_code=status.HTTP_202_ACCEPTED)
async def run_backup(ctx: Ctx) -> Started:
    service = _backups(ctx)
    if not (await service.status()).configured:
        raise HTTPException(status.HTTP_409_CONFLICT, "Set up backups first")
    return Started(started=service.run("manual"))


@router.get("/backups", response_model=list[BackupRecord])
async def backup_history(ctx: Ctx) -> list[BackupRecord]:
    return await _backups(ctx).history()


@router.get("/backups/snapshots", response_model=list[Snapshot])
async def backup_snapshots(ctx: Ctx) -> list[Snapshot]:
    try:
        return await _backups(ctx).snapshots()
    except BackupError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.post("/backups/restore", response_model=Started, status_code=status.HTTP_202_ACCEPTED)
async def restore_backup(ctx: Ctx, body: RestoreRequest) -> Started:
    target = Path(body.target)
    if not target.is_absolute():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Choose an absolute folder to restore into")
    started = _backups(ctx).restore(body.snapshot_id, str(target))
    ctx.audit.append(
        actor="user", action="backup.restore", target_type="snapshot", target_id=body.snapshot_id, details={}
    )
    return Started(started=started)


@router.post("/backups/verify", response_model=Started, status_code=status.HTTP_202_ACCEPTED)
async def verify_backup(ctx: Ctx) -> Started:
    return Started(started=_backups(ctx).verify())
