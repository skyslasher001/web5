"""Consent mirror (ARCHITECTURE §5: `GET /consent`). PROTECTED CORE.

Electron main owns consent: it alone decides whether Chromium may open the microphone. It reports every change
here so the audit log and the timeline record it (`consent.changed`) and the HUD can show it. Core never grants
capture from this record; a wrong report can't open a mic, only mislabel the log.
"""

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from universe_common.schema import ApiModel

router = APIRouter(prefix="/api/v1")


class ConsentRecord(ApiModel):
    mic: bool
    via: str | None
    changed_at: str | None


class ConsentReport(BaseModel):
    kind: Literal["mic"] = "mic"
    on: bool
    via: Literal["hud", "voice", "tray", "killswitch", "window"] = Field(description="Where the change came from")


@router.get("/consent", response_model=ConsentRecord)
async def consent(request: Request) -> ConsentRecord:
    return getattr(request.app.state, "consent", None) or ConsentRecord(mic=False, via=None, changed_at=None)


@router.post("/consent", response_model=ConsentRecord)
async def report_consent(request: Request, body: ConsentReport) -> ConsentRecord:
    ctx = request.app.state.ctx
    record = ConsentRecord(mic=body.on, via=body.via, changed_at=datetime.now(UTC).isoformat())
    request.app.state.consent = record
    ctx.audit.append(
        actor="user",
        action="consent.changed",
        target_type="consent",
        target_id=body.kind,
        details={"on": body.on, "via": body.via},
    )
    ctx.bus.publish("consent.changed", {"kind": body.kind, "on": body.on, "via": body.via}, actor="user")
    return record
