from __future__ import annotations

from pathlib import Path

import pytest

from oscar.agents.terminal_agent import TerminalAgent


def test_terminal_agent_extracts_created_paths_from_powershell_commands(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    agent = TerminalAgent(root_dir=tmp_path)
    desktop = tmp_path / "Desktop"
    monkeypatch.setenv("USERPROFILE", str(tmp_path))

    paths = agent._extract_created_paths(
        "Set-Content -LiteralPath '$env:USERPROFILE\\Desktop\\palindrome_checker.py' -Value $code -Encoding UTF8",
        tmp_path,
    )

    assert paths == [desktop / "palindrome_checker.py"]


def test_terminal_agent_allows_safe_set_content_here_string(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    agent = TerminalAgent(root_dir=tmp_path)
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    monkeypatch.setenv("USERPROFILE", str(tmp_path))

    command = 'Set-Content -Path "$env:USERPROFILE\\Desktop\\palindrome_check.py" -Value @"\nprint("hello")\n"@ -Encoding UTF8'

    assert agent._is_safe_command(command, desktop) is True
    assert agent._extract_created_paths(command, desktop) == [
        desktop / "palindrome_check.py"
    ]


def test_terminal_agent_blocks_set_content_outside_allowed_roots(tmp_path: Path) -> None:
    agent = TerminalAgent(root_dir=tmp_path)

    command = 'Set-Content -Path "C:\\Windows\\System32\\bad.txt" -Value "nope"'

    assert agent._is_safe_command(command, tmp_path) is False


def test_terminal_agent_extracts_deleted_paths_from_powershell_commands(
    tmp_path: Path,
) -> None:
    agent = TerminalAgent(root_dir=tmp_path)

    paths = agent._extract_deleted_paths(
        "if (Test-Path -LiteralPath 'Desktop\\palindrome_checker.py') { Remove-Item -LiteralPath 'Desktop\\palindrome_checker.py' -Force }",
        tmp_path,
    )

    assert paths == [(tmp_path / "Desktop" / "palindrome_checker.py").resolve()]


def test_terminal_agent_updates_cwd_with_userprofile_env_var(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    agent = TerminalAgent(root_dir=tmp_path)
    monkeypatch.setenv("USERPROFILE", str(tmp_path))

    updated = agent._maybe_update_cwd(r"cd $env:USERPROFILE\Desktop", tmp_path)

    assert updated == str((tmp_path / "Desktop").resolve())


def test_terminal_agent_extracts_created_paths_for_django_startproject(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    agent = TerminalAgent(root_dir=tmp_path)
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    monkeypatch.setenv("USERPROFILE", str(tmp_path))

    paths = agent._extract_created_paths(
        "django-admin startproject myproject",
        desktop,
    )

    assert paths == [(desktop / "myproject").resolve()]


@pytest.mark.anyio
async def test_terminal_agent_marks_file_write_failure_when_expected_file_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    agent = TerminalAgent(root_dir=tmp_path)

    class FakeProcess:
        def __init__(self) -> None:
            self.returncode = 0

        async def communicate(self):
            return (b"", b"")

    async def fake_create_subprocess_exec(*args, **kwargs):
        return FakeProcess()

    monkeypatch.setattr(
        "oscar.agents.terminal_agent.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )
    monkeypatch.setattr("oscar.agents.terminal_agent.asyncio.wait_for", lambda coro, timeout: coro)
    monkeypatch.setattr(
        "oscar.agents.terminal_agent.asyncio.get_running_loop",
        lambda: type("Loop", (), {"time": staticmethod(lambda: 0.0)})(),
    )

    result = await agent.run(
        {
            "action": "terminal_command",
            "command": "Set-Content -LiteralPath 'missing.py' -Value 'print(1)'",
            "reasoning": "Create a file.",
            "task_complete": False,
        },
        str(tmp_path),
    )

    assert result.success is False
    assert result.data["missing_created_paths"] == [str((tmp_path / "missing.py").resolve())]


@pytest.mark.anyio
async def test_terminal_agent_marks_delete_success_when_file_is_gone(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    agent = TerminalAgent(root_dir=tmp_path)
    target = tmp_path / "palindrome_checker.py"
    target.write_text("print('hello')", encoding="utf-8")

    class FakeProcess:
        def __init__(self) -> None:
            self.returncode = 0

        async def communicate(self):
            if target.exists():
                target.unlink()
            return (b"", b"")

    async def fake_create_subprocess_exec(*args, **kwargs):
        return FakeProcess()

    monkeypatch.setattr(
        "oscar.agents.terminal_agent.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )
    monkeypatch.setattr("oscar.agents.terminal_agent.asyncio.wait_for", lambda coro, timeout: coro)
    monkeypatch.setattr(
        "oscar.agents.terminal_agent.asyncio.get_running_loop",
        lambda: type("Loop", (), {"time": staticmethod(lambda: 0.0)})(),
    )

    result = await agent.run(
        {
            "action": "terminal_command",
            "command": f"if (Test-Path -LiteralPath '{target}') {{ Remove-Item -LiteralPath '{target}' -Force }}",
            "reasoning": "Delete a file.",
            "task_complete": False,
        },
        str(tmp_path),
    )

    assert result.success is True
    assert result.data["deleted_paths"] == [str(target)]


@pytest.mark.anyio
async def test_terminal_agent_allows_safe_desktop_delete_with_env_var_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    agent = TerminalAgent(root_dir=tmp_path)
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    target = desktop / "world.txt"
    target.write_text("hello", encoding="utf-8")
    monkeypatch.setenv("USERPROFILE", str(tmp_path))

    class FakeProcess:
        def __init__(self) -> None:
            self.returncode = 0

        async def communicate(self):
            if target.exists():
                target.unlink()
            return (b"", b"")

    async def fake_create_subprocess_exec(*args, **kwargs):
        return FakeProcess()

    monkeypatch.setattr(
        "oscar.agents.terminal_agent.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )
    monkeypatch.setattr("oscar.agents.terminal_agent.asyncio.wait_for", lambda coro, timeout: coro)
    monkeypatch.setattr(
        "oscar.agents.terminal_agent.asyncio.get_running_loop",
        lambda: type("Loop", (), {"time": staticmethod(lambda: 0.0)})(),
    )

    result = await agent.run(
        {
            "action": "terminal_command",
            "command": 'Remove-Item "$env:USERPROFILE\\Desktop\\world.txt"',
            "reasoning": "Delete a desktop file.",
            "task_complete": False,
        },
        str(tmp_path),
    )

    assert result.success is True
    assert result.data["deleted_paths"] == [str(target)]
