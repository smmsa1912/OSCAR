# OSCAR Backend

Python backend for the OSCAR desktop automation agent.

## Run tests

```powershell
cd backend
pytest -q
```

## Run the API directly

```powershell
cd backend
python -m uvicorn oscar.server:app --host 127.0.0.1 --port 4444
```
