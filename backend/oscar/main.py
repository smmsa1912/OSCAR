"""CLI entrypoint for the routed OSCAR runtime."""

from __future__ import annotations

import argparse
from pathlib import Path

from oscar import config
from oscar.orchestrator import run_task
from oscar.utils.logging import configure_logging


def run_oscar(task: str) -> Path:
    """Run the routed OSCAR loop for a single task and return the saved log path."""

    outcome = run_task(task)
    final_message = getattr(outcome, "final_message", None)
    if final_message:
        print(final_message)
    print(f"Run log saved to {outcome.log_path}")
    print(f"Execution trace saved to {outcome.trace_path}")
    return outcome.log_path


def main(argv: list[str] | None = None) -> int:
    """Parse CLI arguments and run OSCAR."""

    configure_logging(config.LOG_LEVEL)
    config.enable_windows_dpi_awareness()

    parser = argparse.ArgumentParser(description="Run OSCAR desktop automation tasks.")
    parser.add_argument("--task", help="Task for OSCAR to perform.")
    args = parser.parse_args(argv)

    task = args.task.strip() if args.task else input("Enter a task for OSCAR: ").strip()
    if not task:
        print("A task is required.")
        return 1

    try:
        run_oscar(task)
    except KeyboardInterrupt:
        print("\n[OSCAR] Interrupted by user.")
        return 130
    except Exception:
        import traceback
        traceback.print_exc()
        return 1
    return 0
