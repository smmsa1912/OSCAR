"""Create a source archive without local secrets, runtime state, or caches.

Usage: python scripts/create_source_archive.py [output.zip]
The output path defaults to ../OSCAR-source.zip.
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT.parent / "OSCAR-source.zip"
EXCLUDED_DIRS = {
    ".git", ".venv", "venv", "env", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", ".dart_tool", "build", "dist",
    ".playwright", ".oscar", "logs",
}
EXCLUDED_NAMES = {".env", ".env.local", ".env.production", ".DS_Store", "Thumbs.db"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".log", ".secrets", ".pem", ".key", ".p12", ".pfx"}

def should_exclude(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    if any(part in EXCLUDED_DIRS for part in relative.parts):
        return True
    if path.name in EXCLUDED_NAMES or path.suffix.lower() in EXCLUDED_SUFFIXES:
        return True
    if path.name.startswith(".env.") and path.name != ".env.example":
        return True
    return False

def main() -> int:
    output = Path(sys.argv[1]).expanduser().resolve() if len(sys.argv) > 1 else DEFAULT_OUTPUT.resolve()
    if output == ROOT or ROOT in output.parents:
        raise SystemExit("Choose an archive output path outside the project directory.")
    output.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(ROOT.rglob("*")):
            if not path.is_file() or should_exclude(path):
                continue
            if path.resolve() == output:
                continue
            archive.write(path, path.relative_to(ROOT.parent))
            written += 1
    print(f"Created {output} with {written} files; local secrets and runtime artifacts were excluded.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
