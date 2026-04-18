from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_ROOT = REPO_ROOT / "backend"
DESKTOP_ROOT = REPO_ROOT / "desktop"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 4444
FLUTTER_CACHE_PATHS = (
    DESKTOP_ROOT / "build",
    DESKTOP_ROOT / ".dart_tool",
    DESKTOP_ROOT / "windows" / "flutter" / "ephemeral",
)


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _cmake_normalized(path: Path) -> str:
    return path.resolve().as_posix().lower()


def _run_checked(command: list[str], *, cwd: Path) -> None:
    print(f"[setup] {' '.join(command)}")
    subprocess.run(command, cwd=str(cwd), check=True)


def _ensure_python_dependencies(skip_install: bool) -> None:
    if _module_available("fastapi") and _module_available("uvicorn"):
        return
    if skip_install:
        raise RuntimeError(
            "Missing Python dependencies. Re-run without --skip-python-install or install requirements.txt first."
        )
    _run_checked(
        [sys.executable, "-m", "pip", "install", "-r", str(BACKEND_ROOT / "requirements.txt")],
        cwd=BACKEND_ROOT,
    )


def _ensure_flutter_available() -> str:
    flutter = shutil.which("flutter")
    if flutter is None:
        raise RuntimeError("Flutter is not on PATH.")
    return flutter


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _flutter_cache_reason() -> str | None:
    cache_file = DESKTOP_ROOT / "build" / "windows" / "x64" / "CMakeCache.txt"
    if not cache_file.exists():
        return None

    cache_text = _read_text(cache_file).lower()
    current_root = _cmake_normalized(DESKTOP_ROOT)
    current_source = _cmake_normalized(DESKTOP_ROOT / "windows" / "CMakeLists.txt")
    current_build = _cmake_normalized(DESKTOP_ROOT / "build" / "windows" / "x64")

    if current_root not in cache_text or current_source not in cache_text or current_build not in cache_text:
        return f"stale CMake cache references another project path: {cache_file}"
    return None


def _remove_tree(path: Path) -> None:
    if not path.exists():
        return
    print(f"[clean] Removing {path}")
    shutil.rmtree(path, ignore_errors=False)


def _remove_file(path: Path) -> None:
    if not path.exists():
        return
    print(f"[clean] Removing {path}")
    path.unlink()


def _reset_flutter_caches(reason: str) -> None:
    print(f"[clean] {reason}")
    for path in FLUTTER_CACHE_PATHS:
        if path.is_dir():
            _remove_tree(path)
    for file_path in (
        DESKTOP_ROOT / ".flutter-plugins-dependencies",
    ):
        _remove_file(file_path)


def _port_is_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def _choose_port(host: str, preferred_port: int) -> int:
    for offset in range(20):
        candidate = preferred_port + offset
        if _port_is_free(host, candidate):
            return candidate
    raise RuntimeError("Could not find a free backend port.")


def _wait_for_backend(host: str, port: int, process: subprocess.Popen[bytes], timeout: float = 20.0) -> None:
    health_url = f"http://{host}:{port}/health"
    deadline = time.time() + timeout
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Backend exited early with code {process.returncode}.")
        try:
            with urllib.request.urlopen(health_url, timeout=1.0) as response:
                if response.status == 200:
                    print(f"[backend] Ready at {health_url}")
                    return
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.4)
    raise RuntimeError(f"Backend did not become healthy within {timeout:.0f} seconds.")


def _terminate_process(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return

    try:
        if sys.platform == "win32":
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            process.terminate()
        process.wait(timeout=8)
    except Exception:
        process.kill()
        process.wait(timeout=5)


def _build_flutter_command(
    flutter: str,
    *,
    device: str,
    ws_url: str,
    release: bool,
) -> list[str]:
    command = [
        flutter,
        "run",
        "-d",
        device,
        "--dart-define",
        f"OSCAR_WS_URL={ws_url}",
    ]
    if release:
        command.append("--release")
    return command


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="One-command launcher for OSCAR desktop.")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Backend host. Default: 127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Preferred backend port. Default: 4444")
    parser.add_argument("--device", default="windows", help="Flutter device id. Default: windows")
    parser.add_argument("--release", action="store_true", help="Run Flutter in release mode.")
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Delete Flutter build caches before launching.",
    )
    parser.add_argument(
        "--skip-python-install",
        action="store_true",
        help="Do not auto-install Python requirements if fastapi/uvicorn are missing.",
    )
    parser.add_argument(
        "--skip-flutter-pub-get",
        action="store_true",
        help="Do not run flutter pub get before launching the app.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    backend_process: subprocess.Popen[bytes] | None = None

    try:
        flutter = _ensure_flutter_available()
        _ensure_python_dependencies(skip_install=args.skip_python_install)

        cache_reason = _flutter_cache_reason()
        if args.clean:
            _reset_flutter_caches("manual clean requested")
        elif cache_reason is not None:
            _reset_flutter_caches(cache_reason)

        if not args.skip_flutter_pub_get:
            _run_checked([flutter, "pub", "get"], cwd=DESKTOP_ROOT)

        port = _choose_port(args.host, args.port)
        ws_url = f"ws://{args.host}:{port}/ws/oscar"

        backend_command = [
            sys.executable,
            "-m",
            "uvicorn",
            "oscar.server:app",
            "--host",
            args.host,
            "--port",
            str(port),
        ]
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
        print(f"[backend] {' '.join(backend_command)}")
        backend_process = subprocess.Popen(
            backend_command,
            cwd=str(BACKEND_ROOT),
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
            creationflags=creationflags,
        )
        _wait_for_backend(args.host, port, backend_process)

        flutter_command = _build_flutter_command(
            flutter,
            device=args.device,
            ws_url=ws_url,
            release=args.release,
        )
        print(f"[frontend] {' '.join(flutter_command)}")
        completed = subprocess.run(flutter_command, cwd=str(DESKTOP_ROOT))
        return completed.returncode
    except KeyboardInterrupt:
        print("\n[launcher] Stopping OSCAR...")
        return 130
    except Exception as exc:
        print(f"[launcher] {exc}", file=sys.stderr)
        return 1
    finally:
        _terminate_process(backend_process)


if __name__ == "__main__":
    raise SystemExit(main())
