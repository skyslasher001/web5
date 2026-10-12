import pytest

from universe_models.hardware import GIB, GpuInfo, HardwareInfo
from universe_models.recommend import classify, load_loadouts, recommend


def _hw(vram_gib: float | None, ram_gib: float = 32, battery: bool = False) -> HardwareInfo:
    gpus = [] if vram_gib is None else [GpuInfo(name="GPU", vram_bytes=int(vram_gib * GIB), source="nvml")]
    return HardwareInfo(
        os="Windows",
        os_version="10.0.26100",
        machine="AMD64",
        cpu_model="CPU",
        cpu_cores=8,
        cpu_threads=16,
        ram_bytes=int(ram_gib * GIB),
        gpus=gpus,
        has_battery=battery,
        on_ac_power=False if battery else None,
    )


@pytest.mark.parametrize(
    ("vram", "tier"),
    [
        (23.99, "24gb-plus"),
        (47.9, "24gb-plus"),
        (15.99, "12-16gb"),
        (11.99, "12-16gb"),
        (9.99, "le-8gb"),
        (7.99, "le-8gb"),
        (3.9, "le-8gb"),
        (2.0, "cpu"),
        (None, "cpu"),
    ],
)
def test_tier_thresholds(vram: float | None, tier: str) -> None:
    assert classify(_hw(vram))[0] == tier


def test_every_tier_has_chat_candidates_with_permissive_licenses() -> None:
    data = load_loadouts()
    assert set(data["tiers"]) == {"cpu", "le-8gb", "12-16gb", "24gb-plus"}
    for spec in data["tiers"].values():
        for role in ("local-fast", "local-large"):
            assert spec[role], role
            for candidate in spec[role]:
                assert candidate["license"] in {"Apache-2.0", "MIT"}
    assert data["verified"] is False  # flips only after model cards are checked


def test_installed_candidates_are_marked() -> None:
    rec = recommend(_hw(24), installed={"gemma4:e4b"})
    assert rec.tier == "24gb-plus"
    assert rec.local_fast[0].tag == "gemma4:e4b" and rec.local_fast[0].installed
    assert not any(c.installed for c in rec.local_large)


def test_warnings_for_low_ram_and_battery() -> None:
    rec = recommend(_hw(None, ram_gib=8, battery=True))
    assert any("RAM" in w for w in rec.warnings)
    assert any("battery" in w for w in rec.warnings)
