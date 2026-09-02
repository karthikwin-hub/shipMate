"""ShipMate FastAPI server — REST API + WebSocket job streaming."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any

import asyncio
from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import pipeline_service as ps
from job_manager import job_manager
from repo_resolver import (
    discover_local_match,
    discard_cache_changes,
    get_repo_status,
    is_remote_url,
    parse_remote_url,
    sync_repo,
)
from git_manager import GitManager
import environment_inspector as ei
import projects_store as pstore

ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(ROOT, "static")
ASSETS_DIR = os.path.join(ROOT, "assets")


@asynccontextmanager
async def lifespan(app: FastAPI):
    job_manager.set_loop(asyncio.get_running_loop())
    yield


app = FastAPI(title="ShipMate", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
if os.path.isdir(ASSETS_DIR):
    app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")


def _session_id(x_session_id: str | None) -> str:
    return x_session_id or "default"


class RepoBody(BaseModel):
    repo: str


class RepoSyncBody(BaseModel):
    repo: str
    mode: str = "auto"  # auto | local | cache
    local_path: str | None = None
    branch: str | None = None


class RepoDiscoverBody(BaseModel):
    repo: str


class RepoDiscardBody(BaseModel):
    repo: str
    confirm: bool = False


class IdentityBody(BaseModel):
    repo: str
    name: str
    email: str


class DevShipBody(BaseModel):
    repo: str
    commit_msg: str
    host_override: bool = False


class StageActionBody(BaseModel):
    repo: str
    host_override: bool = False
    check_id: str | None = None


class ChecklistPatchBody(BaseModel):
    repo: str
    item_id: str
    checked: bool


class HostOverrideBody(BaseModel):
    repo: str
    stage: str
    enabled: bool


class SecretBody(BaseModel):
    scope: str
    repo: str | None = None
    name: str
    value: str | None = None


class SecretDeleteBody(BaseModel):
    scope: str
    repo: str | None = None
    name: str


class SecretImportBody(BaseModel):
    scope: str
    repo: str | None = None
    env_content: str


class ProjectBody(BaseModel):
    project_id: str | None = None
    name: str
    stack: str | None = None
    remote_url: str
    dev_path: str | None = None
    qa_path: str | None = None
    prod_ssh_host: str | None = None
    prod_remote_path: str | None = None
    health_url: str | None = None
    provider: str | None = None


class ProjectUpdateBody(BaseModel):
    name: str | None = None
    stack: str | None = None
    remote_url: str | None = None
    dev_path: str | None = None
    qa_path: str | None = None
    prod_ssh_host: str | None = None
    prod_remote_path: str | None = None
    health_url: str | None = None
    provider: str | None = None


class ProjectInspectBody(BaseModel):
    project_ids: list[str] | None = None
    bypass_cache: bool = False


class AutoPopulateBody(BaseModel):
    path: str


def _start_job(fn) -> dict[str, str]:
    job_id = job_manager.create_job(fn)
    return {"job_id": job_id}


@app.get("/")
async def index():
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    raise HTTPException(404, "Frontend not found")


@app.get("/api/context")
def api_context(repo: str, x_session_id: str | None = Header(None)):
    ctx = ps.get_context(_session_id(x_session_id), repo)
    if not ctx.get("valid"):
        raise HTTPException(400, ctx.get("error", "Invalid repo"))
    return ctx


@app.post("/api/repo/validate")
def api_validate_repo(body: RepoBody):
    ok, msg = ps.validate_repo(body.repo)
    return {"valid": ok, "message": msg, "is_remote_url": is_remote_url(body.repo)}


@app.post("/api/repo/discover")
def api_discover_repo(body: RepoDiscoverBody):
    if not is_remote_url(body.repo):
        return {"status": "local_path", "message": "Not a remote URL"}
    try:
        return discover_local_match(body.repo)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.post("/api/repo/sync")
def api_sync_repo(body: RepoSyncBody):
    try:
        result = sync_repo(
            body.repo,
            mode=body.mode,  # type: ignore[arg-type]
            local_path=body.local_path,
            branch=body.branch,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    payload = result.to_dict()
    payload["is_remote_url"] = is_remote_url(body.repo)
    if result.status == "needs_choice":
        payload["valid"] = False
    if result.ok and result.path:
        ok, branches, _ = GitManager.list_remote_branches_for_url(
            result.remote or body.repo
        ) if result.remote else (False, [], "")
        if not branches and result.path:
            ok, branches, _ = GitManager(result.path).list_remote_branches()
        payload["branches"] = branches if ok else []
    return payload


@app.post("/api/repo/branches")
def api_repo_branches(body: RepoDiscoverBody):
    try:
        clone_url, _, _, _ = parse_remote_url(body.repo)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    ok, branches, err = GitManager.list_remote_branches_for_url(clone_url)
    if not ok:
        raise HTTPException(400, err)
    return {"branches": branches}


@app.get("/api/repo/status")
def api_repo_status(repo: str):
    status = get_repo_status(repo)
    if not status.get("valid"):
        raise HTTPException(400, status.get("error", "Invalid repo"))
    return status


@app.post("/api/repo/discard-cache")
def api_discard_cache(body: RepoDiscardBody):
    if not body.confirm:
        raise HTTPException(400, "confirm=true required")
    result = discard_cache_changes(body.repo)
    if not result.ok:
        raise HTTPException(400, result.message)
    return result.to_dict()


@app.post("/api/identity/override")
def api_identity_override(body: IdentityBody):
    ok, msg = ps.override_identity(body.repo, body.name, body.email)
    if not ok:
        raise HTTPException(400, msg)
    return {"success": True, "message": msg}


@app.get("/api/checklist")
def api_checklist(repo: str, stage: str, x_session_id: str | None = Header(None)):
    return ps.get_checklist_view(_session_id(x_session_id), repo, stage)


@app.patch("/api/checklist/manual")
def api_checklist_manual(body: ChecklistPatchBody, x_session_id: str | None = Header(None)):
    ps.update_checklist_manual(_session_id(x_session_id), body.repo, body.item_id, body.checked)
    return {"success": True}


@app.post("/api/host-override")
def api_host_override(body: HostOverrideBody, x_session_id: str | None = Header(None)):
    ps.set_host_override(_session_id(x_session_id), body.repo, body.stage, body.enabled)
    return {"success": True}


@app.post("/api/stages/dev/ship")
def api_dev_ship(body: DevShipBody, x_session_id: str | None = Header(None)):
    sid = _session_id(x_session_id)
    return _start_job(
        lambda: ps.run_dev_ship(sid, body.repo, body.commit_msg, body.host_override)
    )


@app.post("/api/stages/qa/{action}")
def api_qa_action(action: str, body: StageActionBody, x_session_id: str | None = Header(None)):
    sid = _session_id(x_session_id)
    return _start_job(
        lambda: ps.run_qa_action(sid, body.repo, action, body.host_override)
    )


@app.post("/api/stages/prod/{action}")
def api_prod_action(action: str, body: StageActionBody, x_session_id: str | None = Header(None)):
    sid = _session_id(x_session_id)
    return _start_job(
        lambda: ps.run_prod_action(
            sid, body.repo, action, body.host_override, body.check_id
        )
    )


@app.get("/api/activity/overview")
def api_activity_overview():
    return ps.get_activity_overview()


@app.get("/api/activity/project")
def api_activity_project(repo: str):
    return ps.get_activity_project(repo)


@app.get("/api/audit")
def api_audit(filter: str = ""):
    return ps.get_audit_entries(filter)


@app.get("/api/settings/deploy")
def api_settings(repo: str):
    return ps.get_settings(repo)


@app.get("/api/secrets")
def api_list_secrets(scope: str, repo: str | None = None):
    return ps.list_secrets(scope, repo)


@app.post("/api/secrets")
def api_set_secret(body: SecretBody):
    if not body.value:
        raise HTTPException(400, "value required")
    ps.set_secret(body.scope, body.repo, body.name, body.value)
    return {"success": True}


@app.post("/api/secrets/delete")
def api_delete_secret(body: SecretDeleteBody):
    ps.delete_secret(body.scope, body.repo, body.name)
    return {"success": True}


@app.post("/api/secrets/import")
def api_import_secrets(body: SecretImportBody):
    count = ps.import_secrets(body.scope, body.repo, body.env_content)
    return {"success": True, "count": count}


@app.post("/api/secrets/validate")
def api_validate_secrets(body: RepoBody):
    ok, missing = ps.validate_secrets(body.repo)
    return {"valid": ok, "missing": missing}


@app.get("/api/live-status")
def api_live_status(repo: str):
    return ps.get_live_status(repo)


@app.get("/api/projects")
def api_list_projects():
    return {"projects": pstore.list_projects()}


@app.post("/api/projects")
def api_create_project(body: ProjectBody):
    try:
        project = pstore.create_project(body.model_dump(exclude_none=True))
        return {"success": True, "project": project}
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.put("/api/projects/{project_id}")
def api_update_project(project_id: str, body: ProjectUpdateBody):
    try:
        project = pstore.update_project(
            project_id, body.model_dump(exclude_none=True)
        )
        return {"success": True, "project": project}
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.delete("/api/projects/{project_id}")
def api_delete_project(project_id: str):
    try:
        pstore.delete_project(project_id)
        return {"success": True}
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.post("/api/projects/{project_id}/touch")
def api_touch_project(project_id: str):
    try:
        project = pstore.touch_project(project_id)
        return {"success": True, "project": project}
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


@app.post("/api/projects/auto-populate")
def api_auto_populate(body: AutoPopulateBody):
    try:
        draft = pstore.auto_populate_from_path(body.path)
        return {"draft": draft}
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.post("/api/projects/import-registered")
def api_import_registered():
    count = pstore.import_from_registered_paths()
    return {"success": True, "imported": count}


@app.post("/api/projects/inspect")
async def api_inspect_projects(body: ProjectInspectBody):
    projects = pstore.list_projects()
    if body.project_ids:
        ids = set(body.project_ids)
        projects = [p for p in projects if p.get("project_id") in ids]
    inspections = await ei.inspect_fleet(
        projects, bypass_cache=body.bypass_cache
    )
    suggestions = [i.get("suggestion") for i in inspections if i.get("suggestion")]
    return {"inspections": inspections, "suggestions": suggestions}


@app.get("/api/projects/suggest")
async def api_project_suggest(project_id: str, refresh: bool = False):
    project = pstore.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    if not refresh:
        cached = ei.get_cached_suggestion(project_id)
        if cached:
            return {"suggestion": cached, "project_id": project_id}
    inspection = await ei.inspect_project(project)
    return {
        "suggestion": inspection.suggestion,
        "project_id": project_id,
        "inspection": inspection.to_dict(),
    }


@app.websocket("/ws/jobs/{job_id}")
async def ws_job(job_id: str, websocket: WebSocket):
    await websocket.accept()
    queue = job_manager.get_queue(job_id)
    if not queue:
        await websocket.send_json({"type": "done", "success": False, "message": "Job not found"})
        await websocket.close()
        return
    try:
        while True:
            event = await queue.get()
            if event is None:
                break
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    finally:
        job_manager.cleanup(job_id)
