"""Workspace-safe terminal execution agent."""

from __future__ import annotations

import asyncio
import os
import re
import shlex
import shutil
import sys
from contextlib import suppress
from pathlib import Path, PureWindowsPath
from typing import Any, Awaitable, Callable

from oscar import config
from oscar.runtime import ActionResult
from oscar.user_paths import get_known_user_paths, rewrite_known_user_paths


_DANGEROUS_PATTERNS = (
    r"\bgit\s+reset\s+--hard\b",
    r"\bgit\s+clean\s+-fdx\b",
    r"\bshutdown\b",
    r"\brestart-computer\b",
    r"\bstop-computer\b",
    r"\bdiskpart\b",
    r"\breg\s+delete\b",
)

# Root commands that are dangerous when they are the *verb* of the command.
# Does NOT include PowerShell Format-* cmdlets (Format-Table, Format-List, etc)
# which are safe formatting operations, not disk formatters.
_DANGEROUS_ROOT_COMMANDS = {
    "format",       # disk format — not PowerShell Format-*
    "format.com",
}

# PowerShell formatting cmdlets that are safe despite containing "format".
_SAFE_POWERSHELL_FORMAT_CMDLETS = {
    "format-table", "format-list", "format-wide",
    "format-hex", "format-custom",
}


class TerminalAgent:
    """Execute safe shell commands asynchronously with cwd tracking."""

    def __init__(
        self,
        *,
        root_dir: Path | None = None,
        confirmation_callback: Callable[[str, Path], bool | Awaitable[bool]] | None = None,
    ) -> None:
        self.root_dir = (root_dir or Path.cwd()).resolve()
        # This callback must be wired to a trusted UI/API approval flow. Never
        # infer approval from a model-generated action field.
        self.confirmation_callback = confirmation_callback

    async def run(self, action: dict[str, Any], current_cwd: str) -> ActionResult:
        command = self._normalize_user_path_text(str(action.get("command") or "")).strip()
        command = self._normalize_aliases(command)
        cwd = self._resolve_directory(
            str(action.get("working_directory") or current_cwd or self.root_dir),
            base=self.root_dir,
        )
        if not command:
            return ActionResult(
                success=False,
                route="terminal",
                action="terminal_command",
                failure_reason="Terminal command cannot be empty.",
                retryable=False,
            )
        # Hard-block known destructive root commands and commands targeting
        # paths outside allowed roots regardless of any approval callback.
        if not self._is_safe_command(command, cwd):
            return ActionResult(
                success=False,
                route="terminal",
                action="terminal_command",
                failure_reason=f"Blocked unsafe terminal command: {command}",
                retryable=False,
            )

        if not self._is_allowlisted_command(command, cwd):
            approved = False
            if self.confirmation_callback is not None:
                try:
                    approval = self.confirmation_callback(command, cwd)
                    if asyncio.iscoroutine(approval) or isinstance(approval, Awaitable):
                        approval = await approval
                    approved = approval is True
                except Exception:
                    approved = False
            if not approved:
                return ActionResult(
                    success=False,
                    route="terminal",
                    action="terminal_command",
                    confidence=1.0,
                    failure_reason=(
                        "This terminal command requires explicit user confirmation. "
                        "No command was executed."
                    ),
                    retryable=False,
                    data={
                        "requires_confirmation": True,
                        "pending_command": command,
                        "cwd": str(cwd),
                    },
                )
        if not cwd.exists() or not cwd.is_dir():
            return ActionResult(
                success=False,
                route="terminal",
                action="terminal_command",
                failure_reason=f"Working directory '{cwd}' does not exist or is not a directory.",
                retryable=True,
                data={"command": command, "cwd": str(cwd)},
            )

        invocation = self._build_terminal_invocation(command)
        started = asyncio.get_running_loop().time()
        process = None
        try:
            process = await asyncio.create_subprocess_exec(
                *invocation,
                cwd=str(cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(),
                timeout=config.TERMINAL_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            if process is not None and process.returncode is None:
                await self._terminate_process(process)
            return ActionResult(
                success=False,
                route="terminal",
                action="terminal_command",
                confidence=0.1,
                failure_reason=(
                    f"Command timed out after {config.TERMINAL_TIMEOUT_SECONDS} seconds."
                ),
                retryable=True,
                data={"command": command, "cwd": str(cwd)},
            )
        except OSError as exc:
            return ActionResult(
                success=False,
                route="terminal",
                action="terminal_command",
                confidence=0.1,
                failure_reason=str(exc),
                retryable=False,
                data={"command": command, "cwd": str(cwd)},
            )
        finally:
            # Windows can otherwise leave the transport in a bad state, which later
            # shows up as noisy closed-pipe errors under asyncio subprocess usage.
            if process is not None and process.returncode is None:
                await self._terminate_process(process)

        duration_ms = int((asyncio.get_running_loop().time() - started) * 1000)
        stdout = self._truncate_output(stdout_bytes.decode(errors="replace"))
        stderr = self._truncate_output(stderr_bytes.decode(errors="replace"))
        exit_code = int(process.returncode or 0)
        created_paths = self._extract_created_paths(command, cwd)
        deleted_paths = self._extract_deleted_paths(command, cwd)
        missing_created_paths = [
            str(path) for path in created_paths if not path.exists()
        ]
        remaining_deleted_paths = [
            str(path) for path in deleted_paths if path.exists()
        ]
        success = exit_code == 0 and not missing_created_paths and not remaining_deleted_paths
        data = {
            "command": command,
            "cwd": str(cwd),
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": exit_code,
            "duration_ms": duration_ms,
        }
        if created_paths:
            data["created_paths"] = [str(path) for path in created_paths]
        if missing_created_paths:
            data["missing_created_paths"] = missing_created_paths
        if deleted_paths:
            data["deleted_paths"] = [str(path) for path in deleted_paths]
        if remaining_deleted_paths:
            data["remaining_deleted_paths"] = remaining_deleted_paths
        return ActionResult(
            success=success,
            route="terminal",
            action="terminal_command",
            confidence=0.95 if success else 0.2,
            data=data,
            failure_reason=(
                None
                if success
                else (
                    stderr
                    or (
                        f"Expected file was not created: {missing_created_paths[0]}"
                        if missing_created_paths
                        else (
                            f"Expected file was not deleted: {remaining_deleted_paths[0]}"
                            if remaining_deleted_paths
                            else f"Command exited with {exit_code}."
                        )
                    )
                )
            ),
            retryable=not success,
            duration_ms=duration_ms,
            context_updates={
                "current_working_directory": self._maybe_update_cwd(command, cwd),
                "last_command_result": {
                    "command": command,
                    "cwd": str(cwd),
                    "stdout": stdout,
                    "stderr": stderr,
                    "exit_code": exit_code,
                    "success": success,
                },
            },
        )

    def _build_terminal_invocation(self, command: str) -> list[str]:
        if sys.platform == "win32":
            shell_path = (
                shutil.which("pwsh")
                or shutil.which("powershell")
                or shutil.which("powershell.exe")
                or "powershell.exe"
            )
            return [shell_path, "-NoProfile", "-NonInteractive", "-Command", command]

        shell_path = shutil.which("bash") or shutil.which("sh") or "/bin/sh"
        shell_flag = "-lc" if shell_path.endswith("bash") else "-c"
        return [shell_path, shell_flag, command]

    def _truncate_output(self, value: str) -> str:
        text = value.strip()
        limit = max(int(config.TERMINAL_OUTPUT_LIMIT), 0)
        if limit and len(text) > limit:
            return f"{text[:limit]}\n...[truncated]"
        return text

    def _normalize_aliases(self, command: str) -> str:
        normalized = command.strip()
        replacements = [
            (r"^touch\s+(.+)$", r"New-Item -ItemType File -Path \1 -Force | Out-Null"),
            (r"^rm\s+-rf\s+(.+)$", r"Remove-Item -LiteralPath \1 -Recurse -Force"),
            (r"^rm\s+(.+)$", r"Remove-Item -LiteralPath \1 -Force"),
            (r"^mkdir\s+-p\s+(.+)$", r"New-Item -ItemType Directory -Path \1 -Force | Out-Null"),
            (r"^ls$", "Get-ChildItem"),
            (r"^pwd$", "Get-Location"),
        ]
        for pattern, replacement in replacements:
            if re.match(pattern, normalized, re.IGNORECASE):
                return re.sub(pattern, replacement, normalized, flags=re.IGNORECASE)
        return normalized

    def _normalize_user_path_text(self, value: str) -> str:
        normalized = rewrite_known_user_paths(value.strip())
        return self._expand_powershell_env_vars(normalized)

    def _resolve_directory(self, value: str, *, base: Path) -> Path:
        normalized = self._normalize_user_path_text(value).strip().strip("\"'")
        if os.name != "nt" and not PureWindowsPath(normalized).drive:
            normalized = normalized.replace("\\", os.sep)
        candidate = Path(normalized).expanduser()
        if not candidate.is_absolute():
            candidate = (base / candidate).resolve()
        return candidate

    def _is_safe_command(self, command: str, cwd: Path) -> bool:
        lowered = command.lower()
        # Check compound dangerous patterns (multi-word sequences)
        if any(re.search(pattern, lowered, re.IGNORECASE) for pattern in _DANGEROUS_PATTERNS):
            return False
        # PowerShell has constructs such as here-strings that are not shlex
        # compatible, so only parse the leading command verb for root checks.
        root = self._root_command(command)
        if root is None:
            return False
        if root not in _SAFE_POWERSHELL_FORMAT_CMDLETS and root in _DANGEROUS_ROOT_COMMANDS:
            return False
        if not self._is_allowed_directory(cwd):
            return False
        created_paths = self._extract_created_paths(command, cwd)
        if any(not self._is_allowed_path(path) for path in created_paths):
            return False
        if re.search(r"\bremove-item\b|\bdel\b", command, re.IGNORECASE):
            deleted_paths = self._extract_deleted_paths(command, cwd)
            if not deleted_paths:
                return False
            if any(self._is_drive_root(path) or not self._is_allowed_path(path) for path in deleted_paths):
                return False
        if self._targets_drive_root(command, cwd):
            return False
        return True

    def _is_allowlisted_command(self, command: str, cwd: Path | None = None) -> bool:
        """Return whether a command belongs to the conservative no-prompt set.

        This is intentionally not a general PowerShell parser. Commands outside
        this narrow set require a trusted confirmation callback; model-provided
        booleans or strings are never treated as proof of user approval.
        """
        normalized = command.strip()
        root = self._root_command(normalized)
        if root in {"get-location", "pwd"}:
            # Current-directory inspection is read-only and has no target path.
            return len(normalized.split()) == 1

        if root in {"get-childitem", "ls"}:
            # Explicit target paths require confirmation until parsed structurally.
            return len(normalized.split()) == 1

        if root in {"test-path", "get-content"}:
            # File inspection must name a quoted path inside an approved root.
            pattern = r'(?is)(?:Test-Path|Get-Content)\s+(?:-LiteralPath|-Path)\s+"(.*?)"'
            match = re.fullmatch(pattern, normalized)
            if match is None:
                return False
            target = self._resolve_shell_path(match.group(1), cwd or self.root_dir)
            return self._is_allowed_path(target)
        # Safe, scoped file operations are allowed when existing path checks
        # prove every extracted target stays within approved roots.
        if root in {"set-content", "new-item", "remove-item", "del", "touch", "mkdir", "rm"}:
            if re.search(r"[;`]|&&|\|\||\$\(|\b(?:invoke-expression|iex|start-process)\b", normalized, re.I):
                # PowerShell's Out-Null pipe is only accepted for known New-Item
                # file/directory aliases; arbitrary pipelines need confirmation.
                if not re.fullmatch(
                    r"(?is)(?:New-Item\s+-ItemType\s+(?:File|Directory)\s+-Path\s+.+?\s+-Force\s*\|\s*Out-Null)",
                    normalized,
                ):
                    return False
            return True

        # Existing guarded delete idiom is allowed only in its exact shape.
        if re.fullmatch(
            r"(?is)if\s*\(\s*Test-Path\s+-LiteralPath\s+(['\"]).+?\1\s*\)\s*\{\s*Remove-Item\s+-LiteralPath\s+(['\"]).+?\2\s+-Force\s*\}",
            normalized,
        ):
            return True
        return False

    def _root_command(self, command: str) -> str | None:
        try:
            tokens = shlex.split(command, posix=False)
        except ValueError:
            tokens = []
        if tokens:
            return tokens[0].lower().strip()

        match = re.match(r"^\s*(?P<root>[A-Za-z][A-Za-z0-9_.-]*)\b", command)
        if match is None:
            return None
        return match.group("root").lower()

    def _targets_drive_root(self, command: str, cwd: Path) -> bool:
        deleted_paths = self._extract_deleted_paths(command, cwd)
        return any(self._is_drive_root(path) for path in deleted_paths)

    def _is_drive_root(self, path: Path) -> bool:
        resolved = path.resolve()
        return resolved == Path(resolved.anchor)

    def _is_allowed_directory(self, cwd: Path) -> bool:
        return self._is_allowed_path(cwd)

    def _is_allowed_path(self, path: Path) -> bool:
        if os.name != "nt" and PureWindowsPath(str(path)).drive:
            return False
        known_paths = get_known_user_paths()
        allowed_roots = [
            self.root_dir,
            Path.cwd().resolve(),
            Path(os.getenv("TEMP", Path.cwd())).resolve(),
            *[path.resolve() for path in known_paths.values()],
        ]
        path_resolved = path.resolve()
        return any(
            path_resolved == root or root in path_resolved.parents
            for root in allowed_roots
        )

    def _maybe_update_cwd(self, command: str, cwd: Path) -> str:
        match = re.match(
            r"^(?:set-location(?:\s+-literalpath|\s+-path)?|cd|chdir|sl|push-location)\s+(?P<path>.+)$",
            command,
            re.IGNORECASE,
        )
        if match is None:
            return str(cwd)
        return str(self._resolve_directory(match.group("path").strip().strip("\"'"), base=cwd))

    def _extract_created_paths(self, command: str, cwd: Path) -> list[Path]:
        patterns = (
            r"Set-Content\s+-LiteralPath\s+['\"](?P<path>[^'\"]+)['\"]",
            r"Set-Content\s+-Path\s+['\"](?P<path>[^'\"]+)['\"]",
            r"New-Item\s+-ItemType\s+File\s+-Path\s+['\"](?P<path>[^'\"]+)['\"]",
            r"New-Item\s+-ItemType\s+Directory\s+-Path\s+['\"](?P<path>[^'\"]+)['\"]",
            r">\s+['\"](?P<path>[^'\"]+)['\"]",
            r">>\s+['\"](?P<path>[^'\"]+)['\"]",
        )
        created_paths: list[Path] = []
        for pattern in patterns:
            for match in re.finditer(pattern, command, re.IGNORECASE):
                raw_path = self._expand_powershell_env_vars(match.group("path"))
                candidate = self._resolve_shell_path(raw_path, cwd)
                if candidate not in created_paths:
                    created_paths.append(candidate)
        django_startproject = re.search(
            r"\b(?:django-admin|python(?:\.exe)?\s+-m\s+django)\s+startproject\s+(?P<name>[A-Za-z0-9_.-]+)",
            command,
            re.IGNORECASE,
        )
        if django_startproject is not None:
            candidate = (cwd / django_startproject.group("name")).resolve()
            if candidate not in created_paths:
                created_paths.append(candidate)
        return created_paths

    def _extract_deleted_paths(self, command: str, cwd: Path) -> list[Path]:
        patterns = (
            r"Remove-Item\s+-LiteralPath\s+['\"](?P<path>[^'\"]+)['\"]",
            r"Remove-Item\s+-Path\s+['\"](?P<path>[^'\"]+)['\"]",
            r"Remove-Item\s+['\"](?P<path>[^'\"]+)['\"]",
            r"\bdel\s+['\"](?P<path>[^'\"]+)['\"]",
        )
        deleted_paths: list[Path] = []
        for pattern in patterns:
            for match in re.finditer(pattern, command, re.IGNORECASE):
                raw_path = self._expand_powershell_env_vars(match.group("path"))
                candidate = self._resolve_shell_path(raw_path, cwd)
                if candidate not in deleted_paths:
                    deleted_paths.append(candidate)
        return deleted_paths

    def _resolve_shell_path(self, raw_path: str, cwd: Path) -> Path:
        """Resolve a shell path consistently, including Windows paths in POSIX tests."""
        expanded = os.path.expanduser(raw_path.strip())
        windows_path = PureWindowsPath(expanded)
        if os.name != "nt" and windows_path.drive:
            # A Windows absolute path must never be reinterpreted as a harmless
            # relative POSIX path; that can bypass allowed-root checks.
            return Path(expanded)
        if os.name != "nt":
            expanded = expanded.replace("\\", os.sep)
        candidate = Path(expanded).expanduser()
        if not candidate.is_absolute():
            candidate = (cwd / candidate).resolve()
        return candidate

    def _expand_powershell_env_vars(self, value: str) -> str:
        def _replace(match: re.Match[str]) -> str:
            env_name = match.group("name")
            return os.getenv(env_name, match.group(0))

        return re.sub(r"\$env:(?P<name>[A-Za-z_][A-Za-z0-9_]*)", _replace, value)

    async def _terminate_process(self, process: asyncio.subprocess.Process) -> None:
        with suppress(ProcessLookupError):
            process.kill()
        with suppress(Exception):
            await process.wait()
