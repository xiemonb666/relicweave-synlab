"""Structured API problems and the single JSON error envelope.

Every failure leaving the API is a :class:`ApiProblem` carrying a stable code, an HTTP
status and machine-readable details.  Error payloads never contain server filesystem
paths or environment values (plan 30.16), which :func:`redact` enforces.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from ..errors import ErrorCode, SynLabError

# --------------------------------------------------------------------------- codes
#: API-level codes that are not part of ``synlab.errors.ErrorCode``.  They describe
#: transport/authorisation facts, not algorithmic failures.
API_CODE_ROLE_FORBIDDEN = "ROLE_FORBIDDEN"
API_CODE_ROLE_MISMATCH = "ROLE_MISMATCH"
API_CODE_WORKSPACE_FORBIDDEN = "WORKSPACE_FORBIDDEN"
API_CODE_TRUTH_ROUTE_UNMOUNTED = "TRUTH_ROUTE_UNMOUNTED"
API_CODE_PATH_REJECTED = "PATH_REJECTED"
API_CODE_UNREGISTERED_REF = "UNREGISTERED_REF"
API_CODE_NOT_FOUND = "NOT_FOUND"
API_CODE_IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
API_CODE_FILE_ROLE_NOT_SERVABLE = "FILE_ROLE_NOT_SERVABLE"
API_CODE_FILE_ROLE_MISMATCH = "FILE_ROLE_MISMATCH"
API_CODE_UNSUPPORTED_ADAPTER = "UNSUPPORTED_ADAPTER"
API_CODE_ORACLE_EXPORT_FORBIDDEN = "ORACLE_EXPORT_FORBIDDEN"
API_CODE_REVISION_CONFLICT = "REVISION_CONFLICT"
API_CODE_INVALID_CURSOR = "INVALID_CURSOR"
API_CODE_STATE_CONFLICT = "STATE_CONFLICT"
API_CODE_RESEARCH_ROUTE_UNMOUNTED = "RESEARCH_ROUTE_UNMOUNTED"
API_CODE_BAD_REQUEST = "BAD_REQUEST"

#: ``SynLabError`` code -> HTTP status.  Codes are never silently downgraded to 200.
STATUS_BY_CODE: dict[str, int] = {
    ErrorCode.ENV_CAPABILITY_MISSING.value: 503,
    ErrorCode.DEPENDENCY_CAPABILITY_MISSING.value: 503,
    ErrorCode.INTEGRATION_PENDING.value: 503,
    ErrorCode.MVS_NOT_AVAILABLE.value: 503,
    ErrorCode.GPU_DRAIN_PENDING.value: 503,
    ErrorCode.REAL_DATA_PENDING.value: 409,
    ErrorCode.INPUT_UNAVAILABLE.value: 404,
    ErrorCode.ASSET_HASH_MISMATCH.value: 409,
    ErrorCode.BUDGET_EXCEEDED.value: 409,
    ErrorCode.STOP_QA.value: 409,
    ErrorCode.LEASE_STALE.value: 409,
    ErrorCode.FRACTURE_CONSERVATION_FAIL.value: 409,
    ErrorCode.MVS_FAILED.value: 409,
    ErrorCode.TRAIN_NONFINITE.value: 409,
    ErrorCode.REPLAY_MISMATCH.value: 409,
    ErrorCode.SCHEMA_INVALID.value: 422,
    ErrorCode.MOTHER_INVALID.value: 422,
    ErrorCode.CUTTER_NOT_CLOSED.value: 422,
    ErrorCode.PRECISION_NOT_REALIZED.value: 422,
    ErrorCode.PRECISION_BUDGET_EXCEEDED.value: 422,
    ErrorCode.DAMAGE_EFFECT_MISSING.value: 422,
    ErrorCode.OPERATOR_NOT_REALIZED.value: 422,
    ErrorCode.LABEL_MAPPING_UNKNOWN.value: 422,
    ErrorCode.LEAKAGE_DETECTED.value: 422,
    ErrorCode.EXPERIMENT_PROTOCOL_VIOLATION.value: 422,
    ErrorCode.TARGET_INFEASIBLE.value: 422,
    ErrorCode.NA_NOT_APPLICABLE.value: 422,
    ErrorCode.STOP_SFM.value: 409,
    ErrorCode.GALLERY_SIZE_PENDING.value: 409,
    API_CODE_ROLE_FORBIDDEN: 403,
    API_CODE_ROLE_MISMATCH: 403,
    API_CODE_WORKSPACE_FORBIDDEN: 403,
    API_CODE_TRUTH_ROUTE_UNMOUNTED: 403,
    API_CODE_RESEARCH_ROUTE_UNMOUNTED: 403,
    API_CODE_ORACLE_EXPORT_FORBIDDEN: 403,
    API_CODE_FILE_ROLE_NOT_SERVABLE: 403,
    API_CODE_PATH_REJECTED: 400,
    API_CODE_BAD_REQUEST: 400,
    API_CODE_NOT_FOUND: 404,
    API_CODE_UNREGISTERED_REF: 422,
    API_CODE_FILE_ROLE_MISMATCH: 409,
    API_CODE_IDEMPOTENCY_CONFLICT: 409,
    API_CODE_STATE_CONFLICT: 409,
    API_CODE_REVISION_CONFLICT: 409,
    API_CODE_INVALID_CURSOR: 400,
    API_CODE_UNSUPPORTED_ADAPTER: 422,
}

_ABS_PATH_RE = re.compile(r"[A-Za-z]:[\\/][^\s\"'<>|]*|(?<![\w.])/(?:Users|home|var|etc|tmp|opt|mnt)/[^\s\"'<>|]*")


def redact(text: str, store_root: str | None = None) -> str:
    """Remove server filesystem paths from a message before it leaves the process."""
    if not text:
        return text
    out = text
    if store_root:
        for variant in {str(store_root), str(store_root).replace("\\", "/")}:
            if variant:
                out = out.replace(variant, "<store>")
    return _ABS_PATH_RE.sub("<redacted-path>", out)


class ApiProblem(Exception):
    """A structured, transport-safe API failure."""

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        *,
        stage: str = "",
        retryable: bool = False,
        details: dict[str, Any] | None = None,
        evidence_refs: list[str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status = int(status)
        self.code = str(code)
        self.message = message
        self.stage = stage
        self.retryable = bool(retryable)
        self.details = dict(details or {})
        self.evidence_refs = list(evidence_refs or [])
        self.headers = dict(headers or {})
        super().__init__(f"[{self.code}] {message}")

    def payload(self, *, store_root: str | None = None, request_id: str | None = None) -> dict[str, Any]:
        return {
            "ok": False,
            "error": {
                "code": self.code,
                "status": self.status,
                "stage": self.stage,
                "message": redact(self.message, store_root),
                "retryable": self.retryable,
                "details": _redact_tree(self.details, store_root),
                "evidence_refs": self.evidence_refs,
                "request_id": request_id or uuid.uuid4().hex[:16],
            },
        }


def _redact_tree(value: Any, store_root: str | None) -> Any:
    if isinstance(value, str):
        return redact(value, store_root)
    if isinstance(value, dict):
        return {k: _redact_tree(v, store_root) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact_tree(v, store_root) for v in value]
    return value


def problem(
    code: str,
    message: str,
    *,
    status: int | None = None,
    **kwargs: Any,
) -> ApiProblem:
    """Build an :class:`ApiProblem`, deriving the HTTP status from the code table."""
    resolved = status if status is not None else STATUS_BY_CODE.get(code, 500)
    return ApiProblem(resolved, code, message, **kwargs)


def from_synlab(exc: SynLabError, *, status: int | None = None, code: str | None = None) -> ApiProblem:
    """Convert a module-level :class:`SynLabError` into an HTTP-safe problem."""
    raw_code = exc.code.value if isinstance(exc.code, ErrorCode) else str(exc.code)
    resolved_status = status if status is not None else STATUS_BY_CODE.get(raw_code, 500)
    if raw_code == ErrorCode.ASSET_HASH_MISMATCH.value and "unknown asset" in exc.message:
        resolved_status = 404
        raw_code = API_CODE_NOT_FOUND
    if raw_code == ErrorCode.ASSET_HASH_MISMATCH.value and "unknown release" in exc.message:
        resolved_status = 404
        raw_code = API_CODE_NOT_FOUND
    if raw_code == ErrorCode.SCHEMA_INVALID.value and "unknown job" in exc.message:
        resolved_status = 404
        raw_code = API_CODE_NOT_FOUND
    if raw_code == ErrorCode.SCHEMA_INVALID.value and "unknown run" in exc.message:
        resolved_status = 404
        raw_code = API_CODE_NOT_FOUND
    if raw_code == ErrorCode.SCHEMA_INVALID.value and "idempotency key" in exc.message:
        resolved_status = 409
        raw_code = API_CODE_IDEMPOTENCY_CONFLICT
    return ApiProblem(
        resolved_status,
        code or raw_code,
        exc.message,
        stage=exc.stage,
        retryable=exc.retryable,
        details={"measurements": exc.measurements} if exc.measurements else {},
        evidence_refs=exc.evidence_refs,
    )
