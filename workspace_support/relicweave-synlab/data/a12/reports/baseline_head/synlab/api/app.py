"""FastAPI application factory (plan 21.1, 30.16).

```python
from synlab.api import create_app

app = create_app(store_root="data/a12", role="researcher", workspace="default")
```

Role isolation is structural, not cosmetic:

* ``deployment_client`` gets a *denied* research mount: ``GET /research/...`` answers ``403``
  with ``TRUTH_ROUTE_UNMOUNTED`` and the real research handler is never registered;
* ``X-SynLab-Role`` may only restate the server role — anything else is ``403``;
* requests are scoped to the workspace the app was created with;
* ``POST /jobs`` and friends enqueue work; computation happens in ``synlab.api.worker``.
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..errors import ErrorCode, SynLabError
from .context import AppContext
from .problems import (
    API_CODE_BAD_REQUEST,
    API_CODE_NOT_FOUND,
    API_CODE_STATE_CONFLICT,
    API_CODE_TRUTH_ROUTE_UNMOUNTED,
    ApiProblem,
    from_synlab,
    problem,
)
from .routers import assets as assets_router
from .routers import cameras as cameras_router
from .routers import governance as governance_router
from .routers import jobs as jobs_router
from .routers import learning as learning_router
from .routers import meta as meta_router
from .routers import showcase as showcase_router
from .security import ROLES, validate_role

API_PREFIX = "/api/synlab"
API_TITLE = "RelicWeave SynLab A12 API"
API_VERSION = "1.0.0"

#: HTTP status -> stable API error code, used for router-level failures
#: (unrouted paths, wrong method) so every refusal shares one envelope.
HTTP_CODE_BY_STATUS: dict[int, str] = {
    400: API_CODE_BAD_REQUEST,
    403: "ROLE_FORBIDDEN",
    404: API_CODE_NOT_FOUND,
    405: "METHOD_NOT_ALLOWED",
    409: API_CODE_STATE_CONFLICT,
    413: "PAYLOAD_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    422: "SCHEMA_INVALID",
}


def create_app(
    store_root: str | Path,
    *,
    role: str = "researcher",
    workspace: str | None = None,
    session_id: str = "local",
    worker_command: str | None = None,
    cors_origins: list[str] | None = None,
    docs: bool = True,
    showcase_root: str | Path | None = None,
) -> FastAPI:
    validate_role(role)
    # Populate the capability registry once, at app construction: /registry/*, the UI forms and
    # the capability report all read it, and the 31 degradation axes are mirrored into it by
    # load_all(). Without this the first /registry/* responses are legitimately empty (count 0),
    # which the UI renders as "未知 / 0 条" even though the capabilities exist.
    from ..registry import load_all

    load_all()
    context = AppContext(store_root=Path(store_root), role=role,
                         workspace=workspace or "default", session_id=session_id,
                         worker_command=worker_command)

    app = FastAPI(
        title=API_TITLE,
        version=API_VERSION,
        description="A12 合成实验室后端：校验/入队/查询；重计算由 synlab.api.worker 独立进程执行。",
        openapi_url=f"{API_PREFIX}/openapi.json" if docs else None,
        docs_url="/docs" if docs else None,
        redoc_url=None,
    )
    app.state.ctx = context

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins or ["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-SynLab-Role", "X-SynLab-Session", "X-SynLab-Workspace",
                       "Last-Event-ID", "X-Request-Id"],
        expose_headers=["X-SynLab-Asset-Id", "X-SynLab-File-Sha256", "X-SynLab-Hash-Verified",
                        "X-SynLab-Asset-Role", "X-SynLab-File-Key"],
    )

    # ------------------------------------------------------------------ middleware
    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next: Any) -> Any:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        request.state.request_id = request_id
        started = time.time()
        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        response.headers["X-SynLab-Role"] = context.role
        response.headers["X-SynLab-Workspace"] = context.workspace
        response.headers["X-SynLab-Elapsed-Ms"] = f"{(time.time() - started) * 1000:.1f}"
        return response

    # ------------------------------------------------------------------ error paths
    @app.exception_handler(ApiProblem)
    async def api_problem_handler(request: Request, exc: ApiProblem) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        return JSONResponse(status_code=exc.status,
                            content=exc.payload(store_root=str(context.store_root),
                                                request_id=request_id),
                            headers=exc.headers or None)

    @app.exception_handler(SynLabError)
    async def synlab_error_handler(request: Request, exc: SynLabError) -> JSONResponse:
        mapped = from_synlab(exc)
        request_id = getattr(request.state, "request_id", None)
        return JSONResponse(status_code=mapped.status,
                            content=mapped.payload(store_root=str(context.store_root),
                                                   request_id=request_id))

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = []
        for error in exc.errors():
            details.append({
                "loc": [str(part) for part in error.get("loc", ())],
                "type": error.get("type"),
                "msg": error.get("msg"),
            })
        unknown = [d for d in details if d["type"] == "extra_forbidden"]
        mapped = problem(
            "SCHEMA_INVALID",
            ("request contains unknown fields: " + ", ".join(".".join(d["loc"]) for d in unknown))
            if unknown else "request body failed schema validation",
            status=422, stage="request.validation", details={"errors": details},
        )
        request_id = getattr(request.state, "request_id", None)
        return JSONResponse(status_code=422,
                            content=mapped.payload(store_root=str(context.store_root),
                                                   request_id=request_id))

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        """Router/HTTP-level failures use the same envelope as every other refusal.

        Without this, an unrouted path (for example a file-role segment that does not match
        the route) would answer a bare ``{"detail": "Not Found"}`` — a different error shape
        that clients cannot branch on and that the plan forbids alongside button-only states.
        """
        status = int(exc.status_code)
        code = HTTP_CODE_BY_STATUS.get(status, API_CODE_BAD_REQUEST)
        mapped = problem(code, str(exc.detail or code), status=status,
                         stage="request.http", details={"path": request.url.path})
        request_id = getattr(request.state, "request_id", None)
        return JSONResponse(status_code=status,
                            content=mapped.payload(store_root=str(context.store_root),
                                                   request_id=request_id),
                            headers=getattr(exc, "headers", None))

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        # never leak a traceback or a filesystem path through the API
        mapped = problem("INTERNAL_ERROR", f"{type(exc).__name__}: {exc}", status=500,
                         stage="request.unhandled")
        request_id = getattr(request.state, "request_id", None)
        return JSONResponse(status_code=500,
                            content=mapped.payload(store_root=str(context.store_root),
                                                   request_id=request_id))

    # ------------------------------------------------------------------ mounts
    for router in (meta_router.router, jobs_router.router, assets_router.router,
                   governance_router.router, cameras_router.router, learning_router.router,
                   showcase_router.router):
        app.include_router(router, prefix=API_PREFIX)

    # 只读展示页的数据源（`tools/build_demo_assets.py` 产出的独立演示资产库）。
    # 它与会话的 store_root 无关，也不携带任何研究真值：任何角色（含 deployment_client）
    # 都只能读到演示清单与演示资产文件的字节，角色隔离策略不变。
    app.state.showcase = showcase_router.ShowcaseLocator(context.store_root, showcase_root)

    if context.policy.truth_routes_mounted:
        app.include_router(assets_router.research_router, prefix=API_PREFIX)
        app.state.research_mounted = True
    else:
        app.include_router(_denied_research_router(context.role), prefix=API_PREFIX)
        app.state.research_mounted = False

    app.state.capability_snapshot = None

    @app.get(f"{API_PREFIX}/health", tags=["meta"], summary="存活探针（不含敏感路径）")
    def health() -> dict[str, Any]:
        return {"ok": True, "api_version": API_VERSION, "role": context.role,
                "workspace": context.workspace, "store_id": context.store_id,
                "research_routes_mounted": app.state.research_mounted}

    @app.get("/", include_in_schema=False)
    def root() -> dict[str, Any]:
        return {"ok": True, "service": API_TITLE, "api_prefix": API_PREFIX,
                "openapi": f"{API_PREFIX}/openapi.json"}

    return app


def _denied_research_router(role: str) -> APIRouter:
    """Placeholder mount for roles that must not reach research data.

    The real handler is *not* registered; every path a research client might try answers
    403 ``TRUTH_ROUTE_UNMOUNTED`` so the refusal is explicit rather than a bare 404.
    """
    router = APIRouter(tags=["research-denied"])

    def _deny() -> None:
        raise ApiProblem(
            403, API_CODE_TRUTH_ROUTE_UNMOUNTED,
            f"role {role!r} runs a deployment/operator session: the research and truth routes "
            "are not mounted on this server, and oracle exports are refused",
            stage="research.mount", details={"role": role, "mounted": False},
        )

    for path in ("/research/assets/{asset_id}/truth", "/research/{rest:path}",
                 "/assets/{asset_id}/truth", "/truth/{rest:path}"):
        router.add_api_route(path, _deny, methods=["GET", "POST"], include_in_schema=True,
                             name=f"denied:{path}")
    return router


__all__ = ["create_app", "API_PREFIX", "ROLES", "API_CODE_BAD_REQUEST", "API_CODE_NOT_FOUND",
           "ErrorCode"]
