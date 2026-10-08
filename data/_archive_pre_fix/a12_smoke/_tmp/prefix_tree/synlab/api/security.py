"""Server-side role isolation, workspace scoping and path/reference guards (plan 30.16).

The rules enforced here are authoritative: hiding a field in the UI is never treated as
authorisation.  Specifically:

* ``deployment_client`` never reaches truth or research routes, and may not request an
  oracle export;
* the client may not switch role by sending a header — a mismatching role header is a
  403, not a silent upgrade;
* every file reference is resolved to a registered asset/resource id first, and any
  reference containing ``..``, a separator or an absolute path is rejected before it
  reaches the filesystem;
* a resolved path is verified to stay inside the configured data root, with symlinks
  resolved.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from ..roles import (
    ROLE_CLEAN_TRUTH,
    ROLE_LABEL_BUNDLE,
    ROLE_PHYSICAL_TRUTH,
    ROLE_VISIBLE_LABELS,
)
from .problems import (
    API_CODE_ORACLE_EXPORT_FORBIDDEN,
    API_CODE_PATH_REJECTED,
    API_CODE_ROLE_FORBIDDEN,
    API_CODE_ROLE_MISMATCH,
    API_CODE_UNREGISTERED_REF,
    API_CODE_WORKSPACE_FORBIDDEN,
    ApiProblem,
)

ROLE_OPERATOR = "operator"
ROLE_RESEARCHER = "researcher"
ROLE_DEPLOYMENT = "deployment_client"
ROLES = (ROLE_OPERATOR, ROLE_RESEARCHER, ROLE_DEPLOYMENT)

#: Assets whose payload is a research answer.  Deployment and operator sessions must
#: never read these through a generic asset route; researchers use the research entry.
RESEARCH_ONLY_ROLES: frozenset[str] = frozenset({
    ROLE_CLEAN_TRUTH,
    ROLE_PHYSICAL_TRUTH,
    ROLE_VISIBLE_LABELS,
    ROLE_LABEL_BUNDLE,
    "spurious_mask",
    "hard_case_tag",
    "ancestry_graph",
})

#: asset roles that are legal deployment inputs (feature-visible, no answers inside)
DEPLOYMENT_SAFE_ROLES: frozenset[str] = frozenset({
    "obs_view", "obs_result", "obs_fused_geometry", "feature_bundle",
    "display_lod_glb", "fragment_mesh", "mother_mesh",
})

ORACLE_ADAPTERS: frozenset[str] = frozenset({"oracle_truth", "truth_pack", "gt_oracle"})

ROLE_HEADER = "x-synlab-role"
SESSION_HEADER = "x-synlab-session"
WORKSPACE_HEADER = "x-synlab-workspace"

_SESSION_RE = re.compile(r"^[A-Za-z0-9_.:\-]{1,64}$")
_ASSET_ID_RE = re.compile(r"^asset_[0-9a-f]{8,64}$")
_RESOURCE_ID_RE = re.compile(r"^[A-Za-z0-9_.:\-]{1,96}$")


@dataclass(frozen=True)
class RolePolicy:
    role: str
    can_read_truth: bool
    can_read_research: bool
    can_read_ancestry: bool
    can_request_oracle_export: bool
    can_create_release: bool
    can_audit: bool
    can_control_jobs: bool
    can_start_training: bool
    truth_routes_mounted: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "role": self.role,
            "can_read_truth": self.can_read_truth,
            "can_read_research": self.can_read_research,
            "can_read_ancestry": self.can_read_ancestry,
            "can_request_oracle_export": self.can_request_oracle_export,
            "can_create_release": self.can_create_release,
            "can_audit": self.can_audit,
            "can_control_jobs": self.can_control_jobs,
            "can_start_training": self.can_start_training,
            "truth_routes_mounted": self.truth_routes_mounted,
        }


_POLICIES: dict[str, RolePolicy] = {
    # operator drives the platform (jobs, audits, releases, exports of legal adapters)
    # but does not gain research data just by being able to start jobs.
    ROLE_OPERATOR: RolePolicy(
        role=ROLE_OPERATOR, can_read_truth=False, can_read_research=False,
        can_read_ancestry=False, can_request_oracle_export=False, can_create_release=True,
        can_audit=True, can_control_jobs=True, can_start_training=True, truth_routes_mounted=False,
    ),
    ROLE_RESEARCHER: RolePolicy(
        role=ROLE_RESEARCHER, can_read_truth=True, can_read_research=True,
        can_read_ancestry=True, can_request_oracle_export=True, can_create_release=True,
        can_audit=True, can_control_jobs=True, can_start_training=True, truth_routes_mounted=True,
    ),
    ROLE_DEPLOYMENT: RolePolicy(
        role=ROLE_DEPLOYMENT, can_read_truth=False, can_read_research=False,
        can_read_ancestry=False, can_request_oracle_export=False, can_create_release=False,
        can_audit=False, can_control_jobs=False, can_start_training=False, truth_routes_mounted=False,
    ),
}


def validate_role(role: str) -> str:
    if role not in _POLICIES:
        raise ApiProblem(400, "BAD_REQUEST", f"unknown role {role!r}; expected one of {list(ROLES)}")
    return role


def policy_for(role: str) -> RolePolicy:
    return _POLICIES[validate_role(role)]


def check_role_header(server_role: str, header_role: str | None) -> None:
    """A client may restate the server role but never escalate it."""
    if header_role is None or header_role == "":
        return
    if header_role != server_role:
        raise ApiProblem(
            403, API_CODE_ROLE_MISMATCH,
            f"requested role {header_role!r} does not match this server session role "
            f"{server_role!r}; UI tabs cannot change authorisation",
            stage="security.role",
        )


def check_session(value: str | None, *, fallback: str) -> str:
    if value is None or value == "":
        return fallback
    if not _SESSION_RE.match(value):
        raise ApiProblem(400, "BAD_REQUEST",
                         "session id must match ^[A-Za-z0-9_.:-]{1,64}$", stage="security.session")
    return value


def require(policy: RolePolicy, flag: str, *, stage: str, code: str | None = None,
            message: str | None = None) -> None:
    if getattr(policy, flag):
        return
    raise ApiProblem(
        403, code or API_CODE_ROLE_FORBIDDEN,
        message or f"role {policy.role!r} is not permitted to {flag}",
        stage=stage,
    )


def require_job_control(policy: RolePolicy, *, stage: str, action: str) -> None:
    """Gate every route that enqueues work or drives a live run.

    ``can_control_jobs`` is false for ``deployment_client``; hiding the button in the UI is
    not authorisation (plan 30.16), so each enqueuing route repeats the check even when the
    route is not one the deployment package would call.
    """
    require(policy, "can_control_jobs", stage=stage,
            message=f"role {policy.role!r} may not {action}: this session is read-only")


def require_training_start(policy: RolePolicy, *, stage: str, action: str) -> None:
    """Gate routes that start training or change the capture/calibration configuration."""
    require(policy, "can_start_training", stage=stage,
            message=f"role {policy.role!r} may not {action}")


def require_truth_access(policy: RolePolicy, asset_role: str | None, *, stage: str) -> None:
    if asset_role in RESEARCH_ONLY_ROLES and not policy.can_read_truth:
        raise ApiProblem(
            403, API_CODE_ROLE_FORBIDDEN,
            f"asset role {asset_role!r} carries research answers and is not readable by "
            f"role {policy.role!r}; use the research entry point with a researcher session",
            stage=stage,
            details={"asset_role": asset_role, "role": policy.role},
        )


def require_oracle_adapter(policy: RolePolicy, adapter: str, *, stage: str) -> None:
    if adapter in ORACLE_ADAPTERS and not policy.can_request_oracle_export:
        raise ApiProblem(
            403, API_CODE_ORACLE_EXPORT_FORBIDDEN,
            f"adapter {adapter!r} exports oracle/truth data and is not permitted for role "
            f"{policy.role!r}",
            stage=stage,
            details={"adapter": adapter, "role": policy.role},
        )


def require_workspace_match(policy: RolePolicy, session_workspace: str, obj_workspace: str | None,
                            *, object_kind: str, object_id: str) -> None:
    if obj_workspace is None:
        obj_workspace = "default"
    if obj_workspace != session_workspace:
        raise ApiProblem(
            403, API_CODE_WORKSPACE_FORBIDDEN,
            f"{object_kind} {object_id} belongs to workspace {obj_workspace!r}, "
            f"this session is scoped to {session_workspace!r}",
            stage="security.workspace",
            details={"object_kind": object_kind, "object_id": object_id},
        )


# --------------------------------------------------------------------------- refs / paths
def resolve_asset_ref(ref: str) -> str:
    """Validate an opaque asset reference.  Rejects separators, ``..`` and absolute paths."""
    if not isinstance(ref, str) or not ref:
        raise ApiProblem(400, API_CODE_PATH_REJECTED, "asset reference must be a non-empty string",
                         stage="security.asset_ref")
    candidate = ref.strip()
    if candidate != ref:
        raise ApiProblem(400, API_CODE_PATH_REJECTED,
                         "asset reference must not contain leading/trailing whitespace",
                         stage="security.asset_ref")
    lowered = candidate.lower()
    if any(token in candidate for token in ("..", "/", "\\", "\x00")) or lowered.startswith(("file:", "http:", "https:")):
        raise ApiProblem(
            400, API_CODE_PATH_REJECTED,
            "asset reference must be a registered asset id; paths, URLs and '..' are rejected",
            stage="security.asset_ref",
            details={"reference": candidate[:96]},
        )
    if not _ASSET_ID_RE.match(candidate):
        raise ApiProblem(422, API_CODE_UNREGISTERED_REF,
                         f"{candidate!r} is not a registered asset id (expected asset_<hex>)",
                         stage="security.asset_ref")
    return candidate


def resolve_resource_ref(ref: str, *, kind: str) -> str:
    """Validate a non-path resource reference (job/run/release/pool/... id)."""
    if not isinstance(ref, str) or not ref or not _RESOURCE_ID_RE.match(ref):
        raise ApiProblem(422, API_CODE_UNREGISTERED_REF,
                         f"{ref!r} is not a valid {kind} id", stage="security.resource_ref")
    return ref


def safe_join(root: Path, relative: str) -> Path:
    """Join ``relative`` under ``root`` and prove the result stays inside ``root``."""
    if not relative or relative.startswith(("/", "\\")) or ".." in Path(relative).parts:
        raise ApiProblem(400, API_CODE_PATH_REJECTED, "unsafe relative path rejected",
                         stage="security.safe_join")
    root_resolved = Path(root).resolve()
    candidate = (root_resolved / Path(*relative.replace("\\", "/").split("/"))).resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise ApiProblem(400, API_CODE_PATH_REJECTED,
                         "resolved path escapes the configured data root", stage="security.safe_join")
    return candidate


def assert_within(root: Path, candidate: Path, *, stage: str = "security.assert_within") -> Path:
    root_resolved = Path(root).resolve()
    resolved = Path(candidate).resolve()
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise ApiProblem(400, API_CODE_PATH_REJECTED,
                         "path escapes the configured data root", stage=stage)
    return resolved


def filter_research_fields(payload: dict, *, policy: RolePolicy, keys: Iterable[str]) -> dict:
    """Drop research-only keys for non-research roles (belt and braces next to routing)."""
    if policy.can_read_truth:
        return payload
    return {k: v for k, v in payload.items() if k not in set(keys)}
