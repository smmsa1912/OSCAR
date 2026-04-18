from __future__ import annotations

from pathlib import Path

import pytest

from oscar import main as oscar_main


def test_run_oscar_delegates_to_orchestrator(
    monkeypatch: pytest.MonkeyPatch, tmp_path, capsys
) -> None:
    class Outcome:
        log_path = tmp_path / "run.json"
        trace_path = tmp_path / "trace.json"
        final_message = "The current local time is 2026-03-27T00:26:38+05:30."

    monkeypatch.setattr(oscar_main, "run_task", lambda task: Outcome())

    log_path = oscar_main.run_oscar("open settings")

    assert log_path == tmp_path / "run.json"
    output = capsys.readouterr().out
    assert "The current local time is 2026-03-27T00:26:38+05:30." in output
    assert "run.json" in output
    assert "trace.json" in output


def test_cli_main_prompts_when_task_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(oscar_main, "run_oscar", lambda task: Path("logs/run.json"))
    monkeypatch.setattr("builtins.input", lambda _prompt: "Prompted task")

    assert oscar_main.main([]) == 0


def test_cli_main_returns_error_when_run_oscar_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(_task: str):
        raise RuntimeError("boom")

    monkeypatch.setattr(oscar_main, "run_oscar", _boom)

    assert oscar_main.main(["--task", "explode"]) == 1
