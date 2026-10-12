"""Lightweight system profiling for prompt context."""

from __future__ import annotations

from functools import lru_cache
import platform
import subprocess
from typing import Any

try:
    import psutil
except ImportError:  # Keep profiling available when optional system metrics are unavailable.
    psutil = None  # type: ignore[assignment]



def _first_data_line(output: str) -> str | None:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        return None
    if len(lines) == 1:
        return lines[0]
    headers = {"vendor", "manufacturer", "name"}
    for line in lines[1:]:
        if line.strip().lower() not in headers:
            return line.strip()
    return lines[-1].strip()


def _run_profile_command(command: list[str]) -> str | None:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except Exception:
        return None
    if completed.returncode != 0:
        return None
    return _first_data_line(completed.stdout)


def _detect_os_version() -> str:
    system = platform.system() or "Unknown OS"
    release = platform.release()
    version = platform.version()
    if system.lower() == "windows":
        try:
            build = int(str(version).split(".")[-1])
        except Exception:
            build = 0
        if build >= 22000:
            return "Windows 11"
        if release:
            return f"Windows {release}"
        return "Windows"
    return " ".join(part for part in (system, release) if part).strip() or system


def _detect_manufacturer() -> str | None:
    commands = [
        ["wmic", "csproduct", "get", "vendor"],
        ["wmic", "computersystem", "get", "manufacturer"],
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "(Get-CimInstance Win32_ComputerSystem).Manufacturer",
        ],
    ]
    for command in commands:
        value = _run_profile_command(command)
        if value:
            return value
    return None


def _detect_cpu_model() -> str | None:
    processor = (platform.processor() or "").strip()
    if processor:
        return processor
    commands = [
        ["wmic", "cpu", "get", "name"],
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "(Get-CimInstance Win32_Processor | Select-Object -First 1 -ExpandProperty Name)",
        ],
    ]
    for command in commands:
        value = _run_profile_command(command)
        if value:
            return value
    return None


def _format_ram(total_bytes: int) -> str:
    gib = total_bytes / float(1024**3)
    return f"{gib:.1f} GB"


@lru_cache(maxsize=1)
def get_system_specs() -> dict[str, Any]:
    """Return a cached hardware/software snapshot for prompt guidance."""

    try:
        if psutil is None:
            raise RuntimeError("psutil is not installed")
        total_ram = _format_ram(int(psutil.virtual_memory().total))
    except Exception:
        total_ram = "Unknown"

    specs = {
        "os_version": _detect_os_version(),
        "manufacturer": _detect_manufacturer() or "Unknown",
        "cpu_model": _detect_cpu_model() or "Unknown",
        "total_ram": total_ram,
    }
    return specs
