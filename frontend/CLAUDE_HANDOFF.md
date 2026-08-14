# XH Agent Frontend Handoff

This package contains the React/Vite frontend designed for XH Agent.

## Contents

- `src/`: React and TypeScript source code.
- `index.html`: option A entry point.
- `option-b.html`: option B entry point used for the current XH Agent interface.
- `package.json` and `package-lock.json`: reproducible frontend dependencies.

## Upload Target

Upload this package into `frontend/vaultshield` in `ye070901/XH-agent`. Do not upload `node_modules`.

## Local Development

```powershell
cd frontend/vaultshield
npm.cmd ci
npm.cmd run build
npm.cmd run dev
```

Open `http://localhost:5173/option-b.html` for the current option B interface.

## Backend Contract

The UI calls `POST http://localhost:8000/api/generate` and expects the existing XH Agent response fields: `diagnosis`, `resources`, `audit`, and `agent_log`. It does not replace or require changes to backend code.

## Replacing The Existing Streamlit Frontend

The repository currently starts `frontend/streamlit/app_v2.py` through the root `frontend/Dockerfile`. This package is intentionally isolated so its upload does not change the running deployment unexpectedly.

To make React/Vite the default production frontend, first run `npm.cmd run build`, then update the root `frontend/Dockerfile` and the frontend service in `docker-compose.yml` to build and serve `frontend/vaultshield/dist`. Keep the backend service and all backend source unchanged.
