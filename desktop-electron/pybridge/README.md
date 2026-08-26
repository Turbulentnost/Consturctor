# Agent sidecar (local Cursor SDK bridge)

`agent_sidecar.py` lets the Electron app run the REAL local Cursor SDK with full
parity to the PySide6 desktop: agent design, askQuestion clarify, trial demo,
published runs and trigger runs - with local tool execution (1C/Outlook/Excel)
and HITL write approvals.

It reuses the existing desktop code without modifying it. It adds the repo
`desktop/` folder to `sys.path` and imports `CursorSdkBridge`, `ApiClient`,
`app.sdk_agent.*` and the tool host. HITL and askQuestion are routed to the
Electron UI instead of Qt (via `ElectronBridge` and a small JSON protocol).

## How it is launched

Electron main (`src/main/agentSidecar.ts`) spawns:

```
<python> -u desktop-electron/pybridge/agent_sidecar.py
```

- Working directory: repo `desktop/` folder.
- Python executable: `CONSTRUCTOR_PYTHON` env var, otherwise `python` on PATH.
- Communication: newline-delimited JSON on stdin/stdout (see the module
  docstring for the full command/event list). Diagnostics go to stderr.

## Prerequisites (same machine as the PySide6 desktop)

- Python with the desktop dependencies installed
  (`pip install -r desktop/requirements.txt`). PySide6 is NOT required by the
  sidecar; HITL classification is replicated locally.
- Node.js >= 22.13 and `desktop/sdk-agent/node_modules`
  (`npm install` in `desktop/sdk-agent`).
- `CURSOR_API_KEY` in `desktop/.env` (loaded automatically by `app.config`).
- Backend reachable at `BACKEND_URL` (default `http://127.0.0.1:7812`).

## Quick check

```
python -c "import importlib.util,pathlib; p=pathlib.Path('desktop-electron/pybridge/agent_sidecar.py'); s=importlib.util.spec_from_file_location('a',p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print('ok')"
```

Send `{"type":"check_ready"}` on stdin to get a `ready_state` reply telling you
whether the local Cursor SDK is available.
