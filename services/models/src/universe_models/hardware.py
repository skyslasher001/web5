"""Hardware detection for picking a model loadout (SPEC §15). Never raises; gaps go into `notes`."""

import platform
import sys
from pathlib import Path

import psutil
from pydantic import Field

from universe_common.schema import ApiModel

GIB = 1024**3


class GpuInfo(ApiModel):
    name: str
    vram_bytes: int | None = None
    driver: str | None = None
    cuda_driver: str | None = None
    source: str  # "nvml" | "windows-registry"


class DiskInfo(ApiModel):
    mount: str
    fstype: str
    total_bytes: int
    free_bytes: int


class HardwareInfo(ApiModel):
    os: str
    os_version: str
    machine: str
    cpu_model: str
    cpu_cores: int | None
    cpu_threads: int | None
    ram_bytes: int
    gpus: list[GpuInfo] = Field(default_factory=list)
    disks: list[DiskInfo] = Field(default_factory=list)
    has_battery: bool = False
    on_ac_power: bool | None = None
    notes: list[str] = Field(default_factory=list)


def _cpu_model(notes: list[str]) -> str:
    try:
        if sys.platform == "win32":
            import winreg

            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            value, _ = winreg.QueryValueEx(key, "ProcessorNameString")
            return str(value).strip()
        cpuinfo = Path("/proc/cpuinfo")
        if cpuinfo.is_file():
            for line in cpuinfo.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError as exc:
        notes.append(f"cpu model lookup failed: {exc}")
    return platform.processor() or "unknown"


def _nvml_gpus(notes: list[str]) -> list[GpuInfo]:
    try:
        import pynvml
    except ImportError:
        notes.append("nvidia-ml-py not installed")
        return []
    try:
        pynvml.nvmlInit()
    except Exception as exc:  # NVMLError when no NVIDIA driver is present
        notes.append(f"NVML unavailable: {exc}")
        return []
    gpus = []
    try:
        driver = pynvml.nvmlSystemGetDriverVersion()
        cuda = pynvml.nvmlSystemGetCudaDriverVersion()
        cuda_str = f"{cuda // 1000}.{(cuda % 1000) // 10}"
        for index in range(pynvml.nvmlDeviceGetCount()):
            handle = pynvml.nvmlDeviceGetHandleByIndex(index)
            name = pynvml.nvmlDeviceGetName(handle)
            memory = pynvml.nvmlDeviceGetMemoryInfo(handle)
            gpus.append(
                GpuInfo(
                    name=name.decode() if isinstance(name, bytes) else str(name),
                    vram_bytes=int(memory.total),
                    driver=driver.decode() if isinstance(driver, bytes) else str(driver),
                    cuda_driver=cuda_str,
                    source="nvml",
                )
            )
    except Exception as exc:
        notes.append(f"NVML query failed: {exc}")
    finally:
        try:
            pynvml.nvmlShutdown()
        except Exception as exc:
            notes.append(f"NVML shutdown failed: {exc}")
    return gpus


def _windows_registry_gpus(notes: list[str]) -> list[GpuInfo]:
    """Display adapters from the driver class key. Win32_VideoController caps VRAM at 4 GB; this doesn't."""
    if sys.platform != "win32":
        return []
    import winreg

    path = r"SYSTEM\ControlSet001\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
    gpus = []
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path)
    except OSError as exc:
        notes.append(f"display adapter registry key unavailable: {exc}")
        return []
    index = 0
    while True:
        try:
            sub = winreg.EnumKey(root, index)
        except OSError:
            break
        index += 1
        if not sub.isdigit():
            continue
        try:
            key = winreg.OpenKey(root, sub)
            name = str(winreg.QueryValueEx(key, "DriverDesc")[0])
        except OSError:
            continue
        vram = None
        for value_name in ("HardwareInformation.qwMemorySize", "HardwareInformation.MemorySize"):
            try:
                value = winreg.QueryValueEx(key, value_name)[0]
            except OSError:
                continue
            if isinstance(value, int):
                vram = value
                break
            if isinstance(value, bytes) and len(value) in (4, 8):
                vram = int.from_bytes(value, "little")
                break
        try:
            driver = str(winreg.QueryValueEx(key, "DriverVersion")[0])
        except OSError:
            driver = None
        gpus.append(GpuInfo(name=name, vram_bytes=vram, driver=driver, source="windows-registry"))
    return gpus


def _disks(notes: list[str]) -> list[DiskInfo]:
    disks = []
    for part in psutil.disk_partitions(all=False):
        if "cdrom" in part.opts or not part.fstype:
            continue
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except OSError as exc:
            notes.append(f"disk {part.mountpoint} unreadable: {exc}")
            continue
        disks.append(
            DiskInfo(mount=part.mountpoint, fstype=part.fstype, total_bytes=usage.total, free_bytes=usage.free)
        )
    return disks


def detect() -> HardwareInfo:
    notes: list[str] = []
    gpus = _nvml_gpus(notes)
    seen = {g.name.lower() for g in gpus}
    for gpu in _windows_registry_gpus(notes):
        if gpu.name.lower() not in seen:
            gpus.append(gpu)
            seen.add(gpu.name.lower())
    if not gpus and sys.platform not in ("win32",):
        notes.append("GPU detection on this platform covers NVIDIA (NVML) only")
    battery = None
    try:
        battery = psutil.sensors_battery()
    except (AttributeError, NotImplementedError, OSError):
        battery = None
    return HardwareInfo(
        os=platform.system(),
        os_version=platform.version(),
        machine=platform.machine(),
        cpu_model=_cpu_model(notes),
        cpu_cores=psutil.cpu_count(logical=False),
        cpu_threads=psutil.cpu_count(logical=True),
        ram_bytes=psutil.virtual_memory().total,
        gpus=gpus,
        disks=_disks(notes),
        has_battery=battery is not None,
        on_ac_power=None if battery is None else bool(battery.power_plugged),
        notes=notes,
    )
