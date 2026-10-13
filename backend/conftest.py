from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Tests must not inherit a developer's local .env / PowerShell dry-run setting.
# Tests that exercise dry-run behavior explicitly monkeypatch config.OSCAR_DRY_RUN.
os.environ["OSCAR_DRY_RUN"] = "false"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
