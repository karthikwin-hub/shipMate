"""In-memory session state for ShipMate API clients."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from threading import Lock


@dataclass
class RepoSessionState:
    stage_statuses: dict[str, str] = field(
        default_factory=lambda: {"dev": "pending", "qa": "pending", "prod": "pending"}
    )
    stage_logs: dict[str, list[str]] = field(
        default_factory=lambda: {"dev": [], "qa": [], "prod": []}
    )
    checklist_manual: dict[str, bool] = field(default_factory=dict)
    checklist_builtin: dict[str, bool] = field(default_factory=dict)
    checklist_automated: dict[str, bool] = field(default_factory=dict)
    host_overrides: dict[str, bool] = field(
        default_factory=lambda: {"dev": False, "qa": False, "prod": False}
    )


class SessionManager:
    def __init__(self) -> None:
        self._lock = Lock()
        self._sessions: dict[str, dict[str, RepoSessionState]] = {}

    def get(self, session_id: str, repo: str) -> RepoSessionState:
        with self._lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = {}
            if repo not in self._sessions[session_id]:
                self._sessions[session_id][repo] = RepoSessionState()
            return self._sessions[session_id][repo]

    def snapshot(self, session_id: str, repo: str) -> dict:
        state = self.get(session_id, repo)
        return {
            "stage_statuses": copy.copy(state.stage_statuses),
            "checklist_manual": copy.copy(state.checklist_manual),
            "checklist_builtin": copy.copy(state.checklist_builtin),
            "checklist_automated": copy.copy(state.checklist_automated),
            "host_overrides": copy.copy(state.host_overrides),
            "stage_logs": {k: list(v) for k, v in state.stage_logs.items()},
        }


session_manager = SessionManager()
