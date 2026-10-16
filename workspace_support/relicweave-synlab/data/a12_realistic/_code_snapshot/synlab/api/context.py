"""Application context shared by every route: store, scheduler, role policy, workspace."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import Request

from ..canonical import hash_json
from ..jobs.resources import ResourceBudget, ResourceGuard
from ..jobs.scheduler import Scheduler
from ..storage.release import ReleaseManager
from ..storage.store import AssetStore
from .problems import API_CODE_BAD_REQUEST, ApiProblem
from .security import (
    ROLE_HEADER,
    SESSION_HEADER,
    WORKSPACE_HEADER,
    RolePolicy,
    check_role_header,
    check_session,
    policy_for,
    validate_role,
)
from .tables import ensure_api_schema

DEFAULT_WORKSPACE = "default"


@dataclass
class AppContext:
    store_root: Path
    role: str
    workspace: str = DEFAULT_WORKSPACE
    session_id: str = "local"
    worker_command: str | None = None
    store: AssetStore = field(init=False)
    scheduler: Scheduler = field(init=False)
    guard: ResourceGuard = field(init=False)
    releases: ReleaseManager = field(init=False)
    budget: ResourceBudget = field(init=False)

    def __post_init__(self) -> None:
        self.role = validate_role(self.role)
        if not self.workspace or not isinstance(self.workspace, str):
            raise ApiProblem(400, API_CODE_BAD_REQUEST, "workspace must be a non-empty string",
                             stage="context.workspace")
        self.store_root = Path(self.store_root).expanduser().resolve()
        self.store = AssetStore(self.store_root)
        ensure_api_schema(self.store)
        self.scheduler = Scheduler(self.store, owner=f"api:{os.getpid()}")
        self.budget = ResourceBudget()
        self.guard = ResourceGuard(self.store, self.budget, root=str(self.store.root))
        self.releases = ReleaseManager(self.store)

    # ------------------------------------------------------------------ identity
    @property
    def policy(self) -> RolePolicy:
        return policy_for(self.role)

    @property
    def store_id(self) -> str:
        """Stable, non-sensitive store identifier (never the filesystem path)."""
        return "store_" + hash_json({"root": str(self.store_root)}).split(":", 1)[-1][:16]

    def bind_request(self, request: Request) -> "Session":
        """Resolve the effective session; a role header may only restate the server role."""
        check_role_header(self.role, request.headers.get(ROLE_HEADER))
        session = check_session(request.headers.get(SESSION_HEADER), fallback=self.session_id)
        header_workspace = request.headers.get(WORKSPACE_HEADER)
        if header_workspace is not None and header_workspace != "" and header_workspace != self.workspace:
            raise ApiProblem(
                403, "WORKSPACE_FORBIDDEN",
                f"request workspace {header_workspace!r} does not match this session workspace "
                f"{self.workspace!r}",
                stage="context.workspace",
            )
        return Session(context=self, session_id=session, workspace=self.workspace,
                       request_id=request.headers.get("x-request-id"))


@dataclass(frozen=True)
class Session:
    context: AppContext
    session_id: str
    workspace: str
    request_id: str | None = None

    @property
    def store(self) -> AssetStore:
        return self.context.store

    @property
    def policy(self) -> RolePolicy:
        return self.context.policy

    @property
    def role(self) -> str:
        return self.context.role

    @property
    def scheduler(self) -> Scheduler:
        return self.context.scheduler

    @property
    def guard(self) -> ResourceGuard:
        return self.context.guard

    @property
    def releases(self) -> ReleaseManager:
        return self.context.releases

    def as_dict(self) -> dict[str, Any]:
        return {"role": self.role, "session_id": self.session_id, "workspace": self.workspace,
                "store_id": self.context.store_id, "policy": self.policy.as_dict()}
