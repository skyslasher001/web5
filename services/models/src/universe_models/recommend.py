"""Map detected hardware to a tier and a candidate model loadout."""

from functools import cache
from importlib import resources
from typing import Any, Literal

import yaml

from universe_common.schema import ApiModel
from universe_models.hardware import GIB, HardwareInfo

Tier = Literal["cpu", "le-8gb", "12-16gb", "24gb-plus"]

# A 24 GB card reports ~23.99 GiB, 16 GB ~15.99, 12 GB ~11.99, 8 GB ~7.99.
_TIER_THRESHOLDS: list[tuple[float, Tier]] = [(21.0, "24gb-plus"), (11.5, "12-16gb"), (3.5, "le-8gb")]


class Candidate(ApiModel):
    tag: str
    family: str
    license: str
    approx_download_gb: float | None = None
    installed: bool = False


class Recommendation(ApiModel):
    tier: Tier
    tier_label: str
    reason: str
    local_fast: list[Candidate]
    local_large: list[Candidate]
    later_roles: dict[str, Any]
    verified: bool
    source: str
    warnings: list[str]


@cache
def load_loadouts() -> dict[str, Any]:
    text = resources.files("universe_models").joinpath("loadouts.yaml").read_text(encoding="utf-8")
    return yaml.safe_load(text)


def classify(hw: HardwareInfo) -> tuple[Tier, str]:
    vram = max((g.vram_bytes or 0 for g in hw.gpus), default=0)
    vram_gib = vram / GIB
    for threshold, tier in _TIER_THRESHOLDS:
        if vram_gib >= threshold:
            best = max(hw.gpus, key=lambda g: g.vram_bytes or 0)
            return tier, f"{best.name} with {vram_gib:.1f} GiB VRAM"
    if vram:
        return "cpu", f"largest GPU has {vram_gib:.1f} GiB VRAM (under 3.5 GiB), so models run on the CPU"
    return "cpu", "no dedicated GPU detected, so models run on the CPU"


def recommend(hw: HardwareInfo, installed: set[str] | None = None) -> Recommendation:
    data = load_loadouts()
    tier, reason = classify(hw)
    spec = data["tiers"][tier]
    installed = installed or set()

    def candidates(role: str) -> list[Candidate]:
        out = []
        for entry in spec[role]:
            c = Candidate(**entry)
            c.installed = c.tag in installed or f"{c.tag}:latest" in installed
            out.append(c)
        return out

    warnings = []
    ram_gib = hw.ram_bytes / GIB
    if tier == "cpu" and ram_gib < 15.5:
        warnings.append(f"{ram_gib:.0f} GiB RAM is below the 16 GiB the CPU tier assumes; expect slow replies.")
    if hw.has_battery and hw.on_ac_power is False:
        warnings.append("Running on battery: background work will be paused (Phase 2 governor).")
    return Recommendation(
        tier=tier,
        tier_label=spec["label"],
        reason=reason,
        local_fast=candidates("local-fast"),
        local_large=candidates("local-large"),
        later_roles=data["later_roles"],
        verified=bool(data["verified"]),
        source=str(data["source"]),
        warnings=warnings,
    )
