# Pidgin Office (prototype)

An old-school-game-style UI for Pidgin: a top-down office where each robot worker
sits at a desk. Click a robot to talk to it, hire/fire robots, customize them,
drag everyone around, and decorate the rooms.

Now split into a **Python backend** (JSON data store) and a **static frontend**.

```
prototypes/office-ui/
├── README.md
├── MISSING_FEATURES.md        # editable notes, served/saved by the backend
├── index.html                 # frontend shell
├── styles.css
├── src/                       # frontend ES modules
│   ├── api.js                 #   backend client
│   ├── config.js              #   data catalogs (roles, robot parts, desks, decor)
│   ├── store.js               #   reactive state + persistence
│   ├── robot.js               #   customizable robot sprite
│   ├── world.js, drag.js, dialogue.js, overlays.js, editor.js, features.js
│   └── main.js                #   bootstrap
└── backend/
    ├── server.py              # stdlib HTTP API (no pip installs needed)
    └── data/office.json       # the data store (created on first save)
```

## Architecture

- **Backend** — `backend/server.py`, Python standard library only. Persists the
  office to `backend/data/office.json` and the feature notes to
  `MISSING_FEATURES.md`. Exposes a small REST API on **:8770**.
- **Frontend** — static HTML/CSS/ES-modules. One-way data flow:
  `actions → store.emit() → views re-render`, and every change is saved to the
  backend (debounced `PUT /api/office`).

### API

| Method | Path            | Purpose                                   |
|--------|-----------------|-------------------------------------------|
| GET    | `/api/health`   | liveness check                            |
| GET    | `/api/office`   | load the office (`{empty:true}` first run)|
| PUT    | `/api/office`   | overwrite the office store                |
| GET    | `/api/features` | `{ "text": "<MISSING_FEATURES.md>" }`     |
| PUT    | `/api/features` | overwrite `MISSING_FEATURES.md`           |

## Running

You need **two processes**: the backend (API + data) and a static file server
for the frontend. Open two terminals.

### Quick start (scripts)

| | Backend (:8770) | Frontend (:5500) |
|---|---|---|
| Windows | `run-backend.bat`  | `run-frontend.bat`  |
| macOS / Linux | `./run-backend.sh` | `./run-frontend.sh` |

Then open **http://localhost:5500**. Or run the commands manually below.

### 1. Backend (port 8770)

```bash
cd prototypes/office-ui/backend
python server.py
```

Override the port with `PORT=9000 python server.py` (macOS/Linux) or
`set PORT=9000 && python server.py` (Windows cmd).

### 2. Frontend (port 5500)

Pick either static server — run it from `prototypes/office-ui/`:

```bash
# Node (sends correct ES-module MIME types):
npx serve -p 5500

# …or pure Python:
python -m http.server 5500
```

Then open **http://localhost:5500**.

> The frontend talks to the backend at `http://<same-host>:8770` by default.
> To point elsewhere, set `window.PIDGIN_API = "http://host:port"` before the
> app loads.

## Using it

- **Click** a robot → talk to it (bottom dialogue box).
- **Right-click** a robot → Talk / Customize / Fire.
- **+ HIRE** (bottom-right) → build a new robot (role + colors + eyes + antenna).
- **+ DECOR** (bottom-left) → drop plants, chairs, signs (drag to place).
- **Drag** desks and decorations anywhere; positions persist.
- **⟲ RESET** (top-left) → restore the default office.
- **✦ FEATURES** (top-right) → view/edit the missing-features notes, saved back
  to `MISSING_FEATURES.md`.
