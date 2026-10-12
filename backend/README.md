# OSCAR Backend

Python backend for the OSCAR desktop automation agent.

## Install and run tests

Use Python 3.13 or another supported interpreter (3.11–3.13; Python 3.14 is currently excluded by the pinned desktop dependencies). From the repository root, create and activate a virtual environment, then install the authoritative project dependencies plus the test extra:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt
python -m pytest backend\tests -q
```

Alternatively, from this `backend` directory, install with `python -m pip install -e ".[dev]"` and run `python -m pytest -q`.

## Run the API directly

```powershell
cd backend
python -m uvicorn oscar.server:app --host 127.0.0.1 --port 4444
```
