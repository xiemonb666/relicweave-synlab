"""FastAPI dependencies and request DTOs (``extra='forbid'``: unknown fields are rejected)."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from .context import AppContext, Session


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- session
def get_session(request: Request) -> Session:
    context: AppContext = request.app.state.ctx
    session = context.bind_request(request)
    request.state.session = session
    return session


SessionDep = Annotated[Session, Depends(get_session)]


# --------------------------------------------------------------------------- DTOs
#: Known spec kinds.  The DTO deliberately keeps ``kind`` a plain string: an unknown kind
#: must be refused by the *domain* layer with a structured ``BAD_REQUEST`` (422), not
#: swallowed by request-body validation, which cannot report which kinds exist.
SPEC_KINDS: tuple[str, ...] = ("generation", "recipe", "train", "diagnose")
SpecKind = str


class SpecEnvelope(StrictModel):
    spec: dict[str, Any]
    kind: SpecKind = "generation"
    registry_check: bool = True


class BudgetEnvelope(StrictModel):
    spec: dict[str, Any] = Field(default_factory=dict)
    kind: SpecKind = "generation"
    stage: str = "generate"
    planned_jobs: int = Field(1, ge=1, le=1_000_000)
    requires_gpu: bool | None = None


class PreviewEnvelope(StrictModel):
    stage: str
    spec: dict[str, Any] = Field(default_factory=dict)
    input_refs: list[str] = Field(default_factory=list)
    idempotency_key: str | None = Field(default=None, max_length=128)
    budget_ref: str | None = Field(default=None, max_length=128)
    notes: str | None = Field(default=None, max_length=2000)


class JobCreateEnvelope(StrictModel):
    """``POST /jobs`` body (plan 21.2)."""

    schema_version: Literal["synlab.v3", "synlab.train.v1", "synlab.diagnose.v1"] = "synlab.v3"
    data_scope: Literal["SYNTHETIC", "REAL"] | None = None
    release_profile: str | None = None
    spec_ref: str | None = Field(default=None, max_length=160)
    input_refs: list[str] = Field(default_factory=list, max_length=256)
    idempotency_key: str = Field(min_length=1, max_length=128)
    budget_ref: str | None = Field(default=None, max_length=160)
    stage: str = "generate"
    spec: dict[str, Any] = Field(default_factory=dict)
    planned_jobs: int = Field(1, ge=1, le=4096)


class ControlEnvelope(StrictModel):
    revision: int | None = Field(default=None, ge=0)
    reason: str | None = Field(default=None, max_length=500)


class RetryEnvelope(StrictModel):
    reason: str = Field(min_length=1, max_length=500)
    revision: int | None = Field(default=None, ge=0)
    force: bool = False


class AssetIdEnvelope(StrictModel):
    asset_id: str


class AuditEnvelope(StrictModel):
    run_id: str | None = None
    release_id: str | None = None
    asset_ids: list[str] = Field(default_factory=list, max_length=5000)
    release_profile: str = "SANDBOX_CORE"
    include_truth: bool = False


class ReleaseEnvelope(StrictModel):
    release_id: str = Field(min_length=3, max_length=96)
    profile: str
    scope: Literal["SYNTHETIC", "REAL"] = "SYNTHETIC"
    asset_ids: list[str] = Field(min_length=1, max_length=200000)
    audit_id: str
    scope_pending: list[str] = Field(default_factory=list)
    coverage: dict[str, Any] = Field(default_factory=dict)


class ExportEnvelope(StrictModel):
    """``POST /exports`` body.

    ``adapter`` is a plain string on purpose.  The role gate must be able to answer ``403
    ORACLE_EXPORT_FORBIDDEN`` for an oracle adapter *before* the adapter whitelist answers
    ``422``; a ``Literal`` here would collapse both into an opaque request-validation error
    and hide the authorisation refusal (plan 30.16 / A33).
    """

    release_id: str = Field(min_length=3, max_length=96)
    adapter: str = Field(default="manifest", min_length=1, max_length=64)
    idempotency_key: str | None = Field(default=None, max_length=128)


class CameraProfileEnvelope(StrictModel):
    profile_id: str = Field(min_length=2, max_length=64)
    version: str = Field(min_length=1, max_length=32)
    tier: Literal["GLOBAL", "MID", "LOCAL"] = "GLOBAL"
    payload: dict[str, Any]
    calibration_source: Literal["UNGALIBRATED", "MANUFACTURER", "MEASURED", "SYNTHETIC_GT"] = "UNGALIBRATED"


class PoolEnvelope(StrictModel):
    release_id: str = Field(min_length=3, max_length=96)
    spec: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, max_length=128)


class TrainingRunEnvelope(StrictModel):
    spec: dict[str, Any]
    release_id: str | None = None
    idempotency_key: str | None = Field(default=None, max_length=128)


class DiagnosticsRunEnvelope(StrictModel):
    spec: dict[str, Any]
    checkpoint_ref: str | None = None
    pool_ref: str | None = None
    idempotency_key: str | None = Field(default=None, max_length=128)


class EpisodeResetEnvelope(StrictModel):
    spec: dict[str, Any] = Field(default_factory=dict)
    pool_ref: str | None = None
    camera_profile_id: str | None = None


class EpisodeStepEnvelope(StrictModel):
    action: dict[str, Any]
    expected_tick: int | None = Field(default=None, ge=0)
