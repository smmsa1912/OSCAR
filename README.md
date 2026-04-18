# OSCAR

OSCAR is a desktop automation agent with a Python backend and a Flutter Windows frontend.

## Repo layout

```text
backend/   Python package, API server, tests, env files
desktop/   Flutter desktop app and Windows runner
scripts/   helper launch scripts
```

## Run the full desktop app

```powershell
python .\scripts\run_desktop.py
```

## Run backend only

```powershell
cd backend
python -m uvicorn oscar.server:app --host 127.0.0.1 --port 4444
```

## Run Flutter only

```powershell
cd desktop
flutter run -d windows --dart-define OSCAR_WS_URL=ws://127.0.0.1:4444/ws/oscar
```
