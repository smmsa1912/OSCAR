# OSCAR - AI Desktop Assistant

OSCAR is an end-to-end, agentic AI desktop assistant designed to autonomously execute complex, cross-domain workflows. It combines a seamless Flutter-based desktop UI with a robust, multi-pass Python reasoning engine powered by Google's Gemini LLM. 

Unlike standard conversational bots, OSCAR acts as a system-level orchestrator. It utilizes specialized domain agents to interact with web browsers, desktop UIs, and the terminal, employing computer vision and structured memory to ensure reliable execution.

## 🚀 Features

*   **Multi-Agent Orchestration:** Dedicated `BrowserAgent`, `UIAgent`, and `TerminalAgent` modules to handle domain-specific tasks[span_0](start_span)[span_0](end_span).
*   **Multi-Pass Reasoning:** A system-software-inspired `Planner` and `Orchestrator` that resolve dependencies before executing tool calls[span_1](start_span)[span_1](end_span).
*   **Computer Vision Fallback:** Employs grid overlays and target refinement for UI navigation when standard accessibility trees fall short[span_2](start_span)[span_2](end_span).
*   **Multimodal Input (Voice):** Integrates a custom Windows speech-to-text plugin (`speech_to_text_windows`) for seamless voice commands[span_3](start_span)[span_3](end_span).
*   **Decoupled State Management:** Uses a `PersistentMemory` module to maintain execution state separately from the LLM context window, preventing context bloat during long-running tasks[span_4](start_span)[span_4](end_span).
*   **Robust Tool Execution:** Features a central tool registry and strict payload parsers to catch LLM hallucinations before execution[span_5](start_span)[span_5](end_span).

## 🏗️ Project Architecture

The repository is divided into two primary components[span_6](start_span)[span_6](end_span):

1.  **`/backend`**: The Python-based orchestration engine[span_7](start_span)[span_7](end_span). It handles LLM communication (`gemini_client.py`), system profiling, memory management, and agent execution (e.g., Playwright for browser control, PyAutoGUI/vision tools for UI control)[span_8](start_span)[span_8](end_span).
2.  **`/desktop`**: The Flutter-based frontend UI compiled for Windows[span_9](start_span)[span_9](end_span). It handles user interactions, displays agent trajectories, and captures voice inputs[span_10](start_span)[span_10](end_span).

## 🛠️ Prerequisites

*   **Backend:** Python 3.9+ 
*   **Frontend:** Flutter SDK (configured for Windows Desktop development)
*   **API Keys:** Google Gemini API Key

## ⚙️ Installation & Setup

### 1. Backend Setup
Navigate to the backend directory and install the required dependencies:

```bash
cd backend
pip install -r requirements.txt
```
*(Note: You can also use `poetry` or `pipenv` if you prefer managing dependencies via `pyproject.toml`[span_11](start_span)[span_11](end_span))*

Next, set up your environment variables:
1. Copy the example environment file[span_12](start_span)[span_12](end_span): `cp .env.example .env`
2. Open `.env` and add your `GEMINI_API_KEY` and any other required configurations.

### 2. Desktop (Frontend) Setup
Navigate to the desktop directory and fetch the Flutter packages[span_13](start_span)[span_13](end_span):

```bash
cd desktop
flutter pub get
```

## 🏃‍♂️ Running OSCAR

You can start both the backend and frontend using the provided Python runner script[span_14](start_span)[span_14](end_span):

```bash
python scripts/run_desktop.py
```

Alternatively, you can run them separately for debugging:

**Run the Backend:**
```bash
cd backend
python main.py
```

**Run the Desktop UI:**
```bash
cd desktop
flutter run -d windows
```

## 🧪 Testing

The backend includes a comprehensive, deterministic test suite (`/tests`) for the orchestrator, memory management, routing, and specific agents[span_15](start_span)[span_15](end_span). To run the tests:

```bash
cd backend
pytest
```

The desktop UI also includes standard Flutter widget tests[span_16](start_span)[span_16](end_span):

```bash
cd desktop
flutter test
```

## 📄 License

This project is licensed under the terms included in the `LICENSE` file[span_17](start_span)[span_17](end_span).
