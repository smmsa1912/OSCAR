# OSCAR — AI Desktop Assistant

<p align="center">
  <strong>A Windows-first agentic assistant that turns natural-language requests into desktop workflows.</strong><br />
  Python orchestration · Flutter desktop UI · Gemini-powered planning
</p>

<p align="center">
  <a href="https://github.com/smmsa1912/OSCAR"><img src="https://img.shields.io/badge/Platform-Windows-0078D4?logo=windows&logoColor=white" alt="Platform: Windows" /></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Backend-Python-3776AB?logo=python&logoColor=white" alt="Backend: Python" /></a>
  <a href="https://flutter.dev/"><img src="https://img.shields.io/badge/Desktop-Flutter-02569B?logo=flutter&logoColor=white" alt="Desktop: Flutter" /></a>
  <a href="https://ai.google.dev/"><img src="https://img.shields.io/badge/LLM-Google%20Gemini-8E75B2?logo=googlegemini&logoColor=white" alt="LLM: Google Gemini" /></a>
</p>

---

## What is OSCAR?

OSCAR is an agentic AI desktop assistant built to plan and execute workflows across browser automation, desktop interactions, and terminal tasks. Instead of stopping at conversational answers, it coordinates specialized agents to carry out steps on the user's machine.

The project combines a **Python orchestration backend** with a **Flutter Windows desktop app**. Its planning and execution flow is supported by persistent workflow state, validated tool payloads, and computer-vision utilities for cases where conventional UI targeting is not sufficient.

## Highlights

- **Multi-agent execution** — Dedicated `BrowserAgent`, `UIAgent`, and `TerminalAgent` components route tasks to the appropriate environment.
- **Plan before execution** — Planner and orchestrator components help decompose requests and handle dependencies between actions.
- **Vision-assisted desktop control** — Grid overlays and target refinement offer a fallback when UI elements are difficult to target directly.
- **Voice commands** — A custom Windows `speech_to_text_windows` plugin supports speech input.
- **Persistent workflow state** — `PersistentMemory` stores execution state separately from the LLM conversation context to support longer tasks.
- **Tool-call validation** — A central tool registry and payload parsing help reject malformed model-generated actions before execution.
- **Execution visibility** — The desktop UI displays user interactions and agent execution progress.

## Architecture

```text
OSCAR/
├── backend/                 # Python orchestration engine and tests
│   ├── oscar/
│   │   ├── agents/          # Browser, UI, and terminal agents
│   │   ├── brain/           # Planning components
│   │   ├── core/            # Persistent workflow memory
│   │   ├── tools/           # Tool registry
│   │   └── ...              # Runtime, routing, vision, and API
│   ├── tests/               # Backend test suite
│   ├── .env.example         # Example configuration
│   └── requirements.txt
├── desktop/                 # Flutter Windows application
├── scripts/
│   └── run_desktop.py       # Desktop application launcher
└── README.md
```

| Component | Role |
| --- | --- |
| **Planner and orchestrator** | Break down requests, organize execution, and route actions |
| **Browser agent** | Automate browser workflows with Playwright |
| **UI agent** | Interact with desktop controls using UI and vision utilities |
| **Terminal agent** | Execute supported terminal-oriented tasks |
| **Persistent memory** | Keep workflow state outside the LLM context window |
| **Flutter desktop app** | Provide the Windows interface, voice input, and execution progress |

## Tech Stack

- **Backend:** Python
- **Desktop UI:** Flutter / Dart
- **LLM:** Google Gemini API
- **Browser automation:** Playwright
- **Desktop interaction:** PyAutoGUI and computer-vision utilities
- **Backend testing:** pytest
- **Desktop testing:** Flutter test

## Prerequisites

- Python 3.9+
- Flutter SDK with Windows desktop support enabled
- Git
- A Google Gemini API key

OSCAR is primarily designed for Windows. Individual automation capabilities may depend on operating-system permissions, screen layout, installed applications, and local configuration.

## Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/smmsa1912/OSCAR.git
cd OSCAR
```

### 2. Install backend dependencies

Create and activate a virtual environment from the repository root.

**Windows PowerShell**

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt
Copy-Item backend\.env.example backend\.env
```

Open `backend/.env` and add your `GEMINI_API_KEY` and any other required configuration values. Keep API keys private, and never commit your populated `.env` file.

### 3. Install Flutter dependencies

```powershell
cd desktop
flutter pub get
cd ..
```

If Windows desktop support is not configured yet, follow the official [Flutter desktop setup guide](https://docs.flutter.dev/platform-integration/desktop).

## Run OSCAR

### Start the full application

From the **repository root**, run:

```powershell
python scripts/run_desktop.py
```

The launcher coordinates the backend and desktop application and checks for required dependencies.

### Run components separately

For backend debugging, open a terminal and run:

```powershell
cd backend
python -m uvicorn oscar.server:app --host 127.0.0.1 --port 4444
```

In a second terminal, run the Flutter desktop app:

```powershell
cd desktop
flutter run -d windows --dart-define OSCAR_WS_URL=ws://127.0.0.1:4444/ws/oscar
```

## Tests

### Backend

```powershell
cd backend
pytest -q
```

### Flutter desktop app

```powershell
cd desktop
flutter test
```

## Security Notes

- Keep API keys and secrets in local environment files; do not commit them.
- Review actions that can submit forms, modify files, or run commands with meaningful side effects.
- Automation reliability can vary with UI layout, permissions, and the applications currently open.

## Contributing

Bug reports, feature ideas, and pull requests are welcome. For problems or suggestions, please [open an issue](https://github.com/smmsa1912/OSCAR/issues).

## License

See [LICENSE](LICENSE) for the project's license terms.
