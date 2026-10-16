"""Structured error codes and the universal Result envelope (plan section 3.3, 26).

Every public façade function in this project returns either a real result or a
structured error.  Nothing may silently degrade into a fake success.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ErrorCode(str, Enum):
    """Error codes registered in plan section 26 (failure handling table)."""

    ENV_CAPABILITY_MISSING = "ENV_CAPABILITY_MISSING"
    SCHEMA_INVALID = "SCHEMA_INVALID"
    MOTHER_INVALID = "MOTHER_INVALID"
    CUTTER_NOT_CLOSED = "CUTTER_NOT_CLOSED"
    PRECISION_NOT_REALIZED = "PRECISION_NOT_REALIZED"
    PRECISION_BUDGET_EXCEEDED = "PRECISION_BUDGET_EXCEEDED"
    FRACTURE_CONSERVATION_FAIL = "FRACTURE_CONSERVATION_FAIL"
    DAMAGE_EFFECT_MISSING = "DAMAGE_EFFECT_MISSING"
    OPERATOR_NOT_REALIZED = "OPERATOR_NOT_REALIZED"
    LABEL_MAPPING_UNKNOWN = "LABEL_MAPPING_UNKNOWN"
    LEAKAGE_DETECTED = "LEAKAGE_DETECTED"
    MVS_FAILED = "MVS_FAILED"
    MVS_NOT_AVAILABLE = "MVS_NOT_AVAILABLE"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    ASSET_HASH_MISMATCH = "ASSET_HASH_MISMATCH"
    LEASE_STALE = "LEASE_STALE"
    GPU_DRAIN_PENDING = "GPU_DRAIN_PENDING"
    TRAIN_NONFINITE = "TRAIN_NONFINITE"
    EXPERIMENT_PROTOCOL_VIOLATION = "EXPERIMENT_PROTOCOL_VIOLATION"
    TARGET_INFEASIBLE = "TARGET_INFEASIBLE"
    DEPENDENCY_CAPABILITY_MISSING = "DEPENDENCY_CAPABILITY_MISSING"
    STOP_QA = "STOP_QA"
    STOP_SFM = "STOP_SFM"
    REAL_DATA_PENDING = "REAL_DATA_PENDING"
    INTEGRATION_PENDING = "INTEGRATION_PENDING"
    GALLERY_SIZE_PENDING = "GALLERY_SIZE_PENDING"
    REPLAY_MISMATCH = "REPLAY_MISMATCH"
    INPUT_UNAVAILABLE = "INPUT_UNAVAILABLE"
    NA_NOT_APPLICABLE = "NA_NOT_APPLICABLE"


class SynLabError(Exception):
    """Structured failure with a stable code, stage and evidence references."""

    def __init__(
        self,
        code: ErrorCode | str,
        message: str,
        *,
        stage: str = "",
        attempt: int = 0,
        retryable: bool = False,
        seed_ref: str | None = None,
        config_hash: str | None = None,
        evidence_refs: list[str] | None = None,
        measurements: dict[str, Any] | None = None,
        reproduce_command: str | None = None,
    ) -> None:
        self.code = ErrorCode(code) if isinstance(code, str) and code in ErrorCode.__members__ else code
        self.message = message
        self.stage = stage
        self.attempt = attempt
        self.retryable = retryable
        self.seed_ref = seed_ref
        self.config_hash = config_hash
        self.evidence_refs = list(evidence_refs or [])
        self.measurements = dict(measurements or {})
        self.reproduce_command = reproduce_command
        super().__init__(f"[{self.code}] ({stage}) {message}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": str(self.code.value if isinstance(self.code, ErrorCode) else self.code),
            "stage": self.stage,
            "message": self.message,
            "attempt": self.attempt,
            "retryable": self.retryable,
            "seed_ref": self.seed_ref,
            "config_hash": self.config_hash,
            "evidence_refs": self.evidence_refs,
            "measurements": self.measurements,
            "reproduce_command": self.reproduce_command,
        }


ResultStatus = Literal[
    "OK",
    "QA_PASSED",
    "QA_FAILED",
    "FAILED",
    "BLOCKED",
    "PENDING",
    "NOT_RUN",
    "NA",
]


class AssetRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str
    hash: str
    role: str | None = None


class ErrorInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    stage: str = ""
    message: str = ""
    attempt: int = 0
    retryable: bool = False
    seed_ref: str | None = None
    config_hash: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    measurements: dict[str, Any] = Field(default_factory=dict)
    reproduce_command: str | None = None


class Result(BaseModel):
    """Universal result envelope (plan section 3.3)."""

    model_config = ConfigDict(extra="forbid")

    status: ResultStatus
    output_refs: list[AssetRef] = Field(default_factory=list)
    input_hashes: list[str] = Field(default_factory=list)
    qa_report_ref: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    error: ErrorInfo | None = None

    @classmethod
    def ok(cls, refs: list[AssetRef] | None = None, *, metrics: dict[str, Any] | None = None,
           input_hashes: list[str] | None = None, qa_report_ref: str | None = None,
           status: ResultStatus = "OK") -> "Result":
        return cls(status=status, output_refs=refs or [], metrics=metrics or {},
                   input_hashes=input_hashes or [], qa_report_ref=qa_report_ref)

    @classmethod
    def failure(cls, exc: SynLabError) -> "Result":
        return cls(status="FAILED", error=ErrorInfo(**exc.to_dict()))

    @classmethod
    def blocked(cls, exc: SynLabError) -> "Result":
        return cls(status="BLOCKED", error=ErrorInfo(**exc.to_dict()))


def require(condition: bool, code: ErrorCode, message: str, **kwargs: Any) -> None:
    """``require_pass`` helper: raise a structured failure when a QA gate fails."""
    if not condition:
        raise SynLabError(code, message, **kwargs)
