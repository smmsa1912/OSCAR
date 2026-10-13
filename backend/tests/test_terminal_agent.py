from __future__ import annotations

import asyncio
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


@pytest.mark.anyio
@pytest.mark.parametrize(
    "command",
    [
        "shutdown /s /t 0",
        "git reset --hard",
        "git clean -fdx",
        "format C:",
        "Stop-Computer",
    ],
)
async def test_terminal_agent_blocks_dangerous_commands_before_subprocess(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    command: str,
) -> None:
    agent = TerminalAgent(root_dir=tmp_path)
    subprocess_called = False

    async def forbidden_subprocess(*args, **kwargs):
        nonlocal subprocess_called
        subprocess_called = True
        raise AssertionError("Blocked commands must not reach subprocess execution.")

    monkeypatch.setattr(
        "oscar.agents.terminal_agent.asyncio.create_subprocess_exec",
        forbidden_subprocess,
    )

    result = await agent.run(
        {"action": "terminal_command", "command": command},
        str(tmp_path),
    )

    assert result.success is False
    assert "Blocked unsafe terminal command" in (result.failure_reason or "")
    assert subprocess_called is False


def test_terminal_agent_rejects_paths_outside_allowed_roots(tmp_path: Path) -> None:
    agent = TerminalAgent(root_dir=tmp_path)
    # pytest's temp directory is itself an explicitly allowed root, so a sibling
    # under tmp_path.parent is not actually outside policy. Use the filesystem root.
    outside = Path(tmp_path.anchor) / "oscar-outside-root.txt"

    command = f"Set-Content -LiteralPath '{outside}' -Value 'not allowed'"

    assert agent._is_safe_command(command, tmp_path) is False


def test_terminal_agent_truncates_output_to_configured_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("oscar.agents.terminal_agent.config.TERMINAL_OUTPUT_LIMIT", 8)

    result = TerminalAgent()._truncate_output("  1234567890  ")

    assert result == "12345678\n...[truncated]"


@pytest.mark.anyio
async def test_terminal_agent_times_out_and_terminates_process(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    agent = TerminalAgent(root_dir=tmp_path)

    class FakeProcess:
        returncode = None
        killed = False
        waited = False

        async def communicate(self):
            raise asyncio.TimeoutError

        def kill(self):
            self.killed = True
            self.returncode = -9

        async def wait(self):
            self.waited = True
            return self.returncode

    process = FakeProcess()

    async def fake_create_subprocess_exec(*args, **kwargs):
        return process

    async def fake_wait_for(awaitable, timeout):
        # Match asyncio.wait_for cancellation behavior and avoid an un-awaited coroutine.
        awaitable.close()
        raise asyncio.TimeoutError

    monkeypatch.setattr(
        "oscar.agents.terminal_agent.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )
    monkeypatch.setattr(
        "oscar.agents.terminal_agent.asyncio.wait_for",
        fake_wait_for,
    )

    result = await agent.run(
        {"action": "terminal_command", "command": "Get-Location"},
        str(tmp_path),
    )

    assert result.success is False
    assert "timed out" in (result.failure_reason or "").lower()
    assert process.killed is True
    assert process.waited is True


@pytest.mark.anyio
async def test_arbitrary_command_requires_confirmation_and_is_not_executed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    agent = TerminalAgent(root_dir=tmp_path)
    subprocess_called = False

    async def forbidden_subprocess(*args, **kwargs):
        nonlocal subprocess_called
        subprocess_called = True
        raise AssertionError("Command must not execute before confirmation")

    monkeypatch.setattr(
        "oscar.agents.terminal_agent.asyncio.create_subprocess_exec",
        forbidden_subprocess,
    )
    result = await agent.run(
        {
            "action": "terminal_command",
            "command": "python -c \"print('hello')\"",
            # A model-generated field must never count as user approval.
            "user_confirmed": True,
        },
        str(tmp_path),
    )

    assert result.success is False
    assert result.data["requires_confirmation"] is True
    assert result.data["pending_command"] == "python -c \"print('hello')\""
    assert subprocess_called is False


@pytest.mark.anyio
async def test_arbitrary_command_runs_only_after_trusted_confirmation_callback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, Path]] = []

    async def approve(command: str, cwd: Path) -> bool:
        calls.append((command, cwd))
        return True

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            return (b"ok", b"")

    async def fake_create_subprocess_exec(*args, **kwargs):
        return FakeProcess()

    monkeypatch.setattr(
        "oscar.agents.terminal_agent.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )
    monkeypatch.setattr(
        "oscar.agents.terminal_agent.asyncio.wait_for",
        lambda coro, timeout: coro,
    )
    times = iter([0.0, 0.01])
    monkeypatch.setattr(
        "oscar.agents.terminal_agent.asyncio.get_running_loop",
        lambda: type("Loop", (), {"time": staticmethod(lambda: next(times))})(),
    )

    command = "python -c \"print('hello')\""
    result = await TerminalAgent(
        root_dir=tmp_path, confirmation_callback=approve
    ).run({"action": "terminal_command", "command": command}, str(tmp_path))

    assert result.success is True
    assert calls == [(command, tmp_path.resolve())]


@pytest.mark.parametrize(
    "command",
    [
        "Get-Location; Remove-Item -LiteralPath 'important.txt' -Force",
        "Get-ChildItem | Invoke-Expression",
        "python -c \"import os; os.remove('important.txt')\"",
    ],
)
def test_compound_or_interpreter_commands_are_not_allowlisted(
    tmp_path: Path,
    command: str,
) -> None:
    assert TerminalAgent(root_dir=tmp_path)._is_allowlisted_command(command) is False


def test_read_command_with_path_outside_allowed_roots_requires_confirmation(
    tmp_path: Path,
) -> None:
    agent = TerminalAgent(root_dir=tmp_path)

    assert agent._is_allowlisted_command(
        'Get-Content -LiteralPath "C:\\Windows\\win.ini"', tmp_path
    ) is False
    assert agent._is_allowlisted_command(
        'Get-ChildItem "C:\\Windows"', tmp_path
    ) is False


@pytest.mark.anyio
async def test_terminal_agent_dry_run_never_spawns_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from oscar import config

    monkeypatch.setattr(config, "OSCAR_DRY_RUN", True)
    monkeypatch.setattr("oscar.agents.terminal_agent.config.OSCAR_DRY_RUN", True)

    async def forbidden_spawn(*args, **kwargs):
        raise AssertionError("subprocess must not be spawned in dry-run mode")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden_spawn)
    agent = TerminalAgent(root_dir=tmp_path)
    result = await agent.run(
        {"action": "terminal_command", "command": "python -c \"print(1)\""},
        str(tmp_path),
    )

    assert result.success is True
    assert result.data["dry_run"] is True
    assert result.data["execution_confirmed"] is False
