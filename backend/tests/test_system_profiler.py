from __future__ import annotations

from types import SimpleNamespace

import oscar.system_profiler as profiler


def test_get_system_specs_collects_expected_fields(monkeypatch) -> None:
    profiler.get_system_specs.cache_clear()

    monkeypatch.setattr(profiler.platform, "system", lambda: "Windows")
    monkeypatch.setattr(profiler.platform, "release", lambda: "10")
    monkeypatch.setattr(profiler.platform, "version", lambda: "10.0.22631")
    monkeypatch.setattr(profiler.platform, "processor", lambda: "Intel(R) Core(TM) i7")
    monkeypatch.setattr(
        profiler.psutil,
        "virtual_memory",
        lambda: SimpleNamespace(total=16 * 1024**3),
    )

    def fake_run(command, capture_output, text, timeout, check):
        joined = " ".join(command).lower()
        if "vendor" in joined or "manufacturer" in joined:
            return SimpleNamespace(returncode=0, stdout="Vendor\nHP\n")
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr(profiler.subprocess, "run", fake_run)

    specs = profiler.get_system_specs()

    assert specs == {
        "os_version": "Windows 11",
        "manufacturer": "HP",
        "cpu_model": "Intel(R) Core(TM) i7",
        "total_ram": "16.0 GB",
    }
