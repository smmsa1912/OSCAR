# Dry-Run Dispatch Audit — Checkpoint 06

## Changes in this checkpoint

- `oscar.executor._launch_process()` now returns before `subprocess.Popen()` when `OSCAR_DRY_RUN` is enabled. This is a defense-in-depth guard for any caller that reaches the low-level launcher directly.
- `oscar.window_control.focus_app_window()` now returns `False` before app resolution or desktop inspection when dry-run is enabled.
- Added regression tests that invoke these low-level helpers directly and assert that process launching and window inspection do not occur.

## Verification performed

- Python compilation: passed.
- Targeted dry-run helper and window-control tests: 21 passed.
- Full backend test suite in the audit environment: 277 passed.

## Scope and limitations

These guards protect the two audited low-level helpers. They do not by themselves prove that every possible desktop, browser, terminal, filesystem, or external integration path is side-effect-free in dry-run mode. Continue testing dispatch paths with side-effecting dependencies mocked, and rerun the full suite on the target Windows environment after applying the archive.
