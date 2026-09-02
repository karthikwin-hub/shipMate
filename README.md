# ShipMate

Standalone DevOps and QA dashboard for orchestrating a 3-tier delivery workflow (Windows Dev → Linux QA → Production) across any local Git repository.

## Prerequisites

- Python 3.10+
- Git
- GitHub CLI (`gh`) — authenticated for PR create/merge
- Platform CLIs as needed: `vercel`, `firebase`, SSH keys for Oracle VM

## Install

**Quick setup (recommended):**

```powershell
# Windows
.\setup.ps1
```

```bash
# Linux / macOS
chmod +x setup.sh && ./setup.sh
```

**Manual install:**

```bash
pip install -r requirements.txt
```

## Configure

1. Copy global config:
   ```bash
   cp shipmate_config.example.yaml shipmate_config.yaml
   ```
2. Set notification env vars in `.env` (optional):
   ```
   WEBHOOK_URL=...
   SMTP_SERVER=smtp.example.com
   SMTP_FROM=shipmate@example.com
   SMTP_TO=team@example.com
   ```
3. For Infisical backend (optional):
   ```
   secrets.backend: infisical
   INFISICAL_TOKEN=your-token
   ```

## Per-project deploy config

Add `.shipmate/deploy.yaml` to each target repo (see [examples/deploy.example.yaml](examples/deploy.example.yaml)):

```yaml
deploy:
  provider: vercel    # oracle_vm | vercel | firebase
  health_url: https://myapp.vercel.app
  vercel:
    project: my-app
secrets:
  required:
    - VERCEL_TOKEN
```

## Run

```bash
python start.py
```

Opens **http://127.0.0.1:5000** in your browser automatically.

Alternative (no auto-open):

```bash
python -m uvicorn server:app --host 127.0.0.1 --port 5000
```

## Repository resolution

ShipMate supports **local workspace** paths and **remote Git URLs**. Remote URLs clone into a managed cache at `~/.shipmate/repos/<owner>/<repo>` (namespaced to avoid collisions).

## Fleet Overview

The **Fleet Overview** tab (⚡ in the header) gives a single-pane view of all registered projects across four environments:

| Tier | What it shows |
|------|----------------|
| Dev (Windows) | Local branch, commit, dirty/clean status |
| Remote (GitHub) | Default/PR branch, PR status via `gh` |
| QA (Linux) | QA/cache path commit and sync delta vs remote |
| Prod | Oracle VM SSH commit + health URL (Vercel/Firebase: health only) |

Projects are stored in `~/.shipmate/projects.json`. Register projects manually, **auto-populate from current repo**, or **Import Registered** from `~/.shipmate/config.json`.

API endpoints: `GET/POST/PUT/DELETE /api/projects`, `POST /api/projects/inspect`, `GET /api/projects/suggest`.

### Local vs cache

When you sync a GitHub/GitLab URL, ShipMate checks **registered paths** in `~/.shipmate/config.json` (not a filesystem scan). If a matching local clone is registered, the UI prompts:

- **Use Local Workspace** — bind your existing clone (no pull; your files stay untouched)
- **Use Isolated Cache** — clone/update under `~/.shipmate/repos/`

Register a path automatically when you choose **Use Local Workspace**, or add entries manually:

```json
{
  "registered_paths": [
    {"path": "C:\\Cursor\\appforge", "remote": "github.com/karthikwin-hub/appforge"}
  ]
}
```

### Branch syntax

Append a branch to the URL:

- `https://github.com/user/repo#feature/x`
- `https://github.com/user/repo@dev`

Use the branch dropdown after entering a URL.

### Data safety

- Dashboard refresh (`GET /api/context`) **never runs `git pull`**
- Cache sync stashes dirty changes before pull, then reapplies them
- **Discard Cache Changes** is manual-only and affects the cache copy, not your local workspace

## Architecture

- **Backend:** FastAPI (`server.py`) on port 5000 with REST API + WebSocket job streaming
- **Frontend:** Tailwind CSS + Alpine.js dashboard (`static/index.html`)
- **Pipeline logic:** `pipeline_service.py` (reuses git_manager, runner, deploy_providers, etc.)

Send `X-Session-Id` header (UUID stored in browser localStorage) for per-client checklist and stage state.

## QA app lifecycle

When you launch a QA app from Stage 2, ShipMate writes a `.qa_server.pid` file in the target repo root. **Stop QA App** reads this file so it works across page refreshes. Stale PID files are cleaned up automatically.

## Tests

```bash
pip install -r requirements.txt
python -m pytest tests/
```

## Workflow

1. **Activity Dashboard** — per-project pipeline history and metrics
2. **Stage 1 Dev** — pre-flight, commit, push, open PR
3. **Stage 2 QA** — pull, test, launch app, merge
4. **Stage 3 Prod** — provider-specific deploy (Oracle VM / Vercel / Firebase)
5. **Project Settings** — view deploy config from Git
6. **Secrets Manager** — maintain project and team secrets

## Project Structure

```
server.py                 # FastAPI REST + WebSocket
pipeline_service.py       # Pipeline orchestration
session_manager.py        # Per-client session state
start.py                  # One-click launcher
static/                   # Tailwind/Alpine.js dashboard
repo_resolver.py          # Local/cache resolution, safe sync
projects_store.py         # ~/.shipmate/projects.json fleet registry
environment_inspector.py  # Cross-env inspection + workflow suggestions
shipmate_user_config.py   # ~/.shipmate/config.json registered paths
secrets_vault.py          # Local + Infisical secret backends
deploy_providers/         # oracle_vm, vercel, firebase
audit_analytics.py        # Activity dashboard queries
.workflow-checklist.yaml  # Default QA/prod checklist template
```

## Reference

Specs in `docs/`. Original prototype in `s-code/`.
