"""Capability probing: what is *actually* importable and callable right now.

The API never guesses.  Every route that needs a module resolves it through this
module; a missing module produces ``DEPENDENCY_CAPABILITY_MISSING`` and a missing
external backend produces ``ENV_CAPABILITY_MISSING``.  Nothing is ever substituted
with synthetic data to keep a page looking busy.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
import time
from dataclasses import dataclass, field
from typing import Any

STATUS_OK = "OK"
STATUS_DEPENDENCY_MISSING = "DEPENDENCY_CAPABILITY_MISSING"
STATUS_ENV_MISSING = "ENV_CAPABILITY_MISSING"

#: capability key -> importable module path
CAPABILITY_MODULES: dict[str, str] = {
    "mothers": "synlab.mothers",
    "materials": "synlab.materials",
    "patterns": "synlab.patterns",
    "fracture": "synlab.fracture",
    "physical": "synlab.physical",
    "truth": "synlab.truth",
    "cameras": "synlab.cameras",
    "observe": "synlab.observe",
    "degrade": "synlab.degrade",
    "relations": "synlab.relations",
    "training": "synlab.training",
    "diagnostics": "synlab.diagnostics",
    "episodes": "synlab.episodes",
}

#: capability key -> façade functions that must exist (docs/a12/interfaces.md section 2).
#: A function may live on the package itself or on its ``api`` submodule; additional
#: canonical locations are probed in order.
CAPABILITY_ENTRYPOINTS: dict[str, tuple[str, ...]] = {
    "mothers": ("create_mother", "audit_mother", "sample_parameters"),
    "materials": ("build_material_profile", "material_at", "layer_combo"),
    "patterns": ("build_pattern", "evaluate", "apply_pattern_geometry", "audit_pattern"),
    "fracture": ("fracture_event", "make_closed_cutter", "audit_fracture"),
    "physical": ("apply_damage", "audit_physical"),
    "truth": ("finalize_clean_truth", "update_residual_truth", "update_visibility_truth"),
    "cameras": ("camera_profiles", "make_view_frames", "project"),
    "observe": ("observe", "adapt_observed_features", "estimate_quality"),
    "degrade": ("compile_recipe", "apply_axis", "audit_axis"),
    "relations": ("build_pool", "sample_training_batch"),
    "training": ("train", "evaluate", "resume"),
    "diagnostics": ("run_diagnosis",),
    "episodes": ("EpisodeEnv", "available_actions", "step"),
}

#: capability key -> extra submodules that must import too
CAPABILITY_SUBMODULES: dict[str, tuple[str, ...]] = {
    "degrade": ("synlab.degrade.registry",),
}

_ENTRY_SEARCH_ROOTS = ("", ".api")

#: external backends whose absence must be reported as ENV_CAPABILITY_MISSING
ENV_PROBES: tuple[str, ...] = ("blender_bpy", "cuda", "colmap", "gmsh", "open3d", "faiss", "trimesh")

_CACHE: dict[str, Any] = {"at": 0.0, "report": None}
_CACHE_TTL_SECONDS = 5.0


@dataclass
class CapabilityStatus:
    key: str
    module: str
    status: str
    error: str | None = None
    entry_points: dict[str, bool] = field(default_factory=dict)
    missing_entry_points: list[str] = field(default_factory=list)
    search_roots: dict[str, str] = field(default_factory=dict)

    @property
    def available(self) -> bool:
        return self.status == STATUS_OK

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "module": self.module,
            "status": self.status,
            "available": self.available,
            "error": self.error,
            "entry_points": self.entry_points,
            "missing_entry_points": self.missing_entry_points,
            "resolved_from": self.search_roots,
        }


def _probe_entry_points(module: Any, key: str) -> tuple[dict[str, bool], list[str], dict[str, str]]:
    wanted = CAPABILITY_ENTRYPOINTS.get(key, ())
    found: dict[str, bool] = {}
    origin: dict[str, str] = {}
    for root_name in _ENTRY_SEARCH_ROOTS:
        if not wanted:
            break
        try:
            candidate = importlib.import_module(module.__name__ + root_name)
        except Exception:  # noqa: BLE001 - a missing submodule is a normal probe outcome
            continue
        for name in wanted:
            if name in found:
                continue
            if hasattr(candidate, name):
                found[name] = True
                origin[name] = candidate.__name__
    missing = [name for name in wanted if not found.get(name)]
    for name in missing:
        found[name] = False
    return found, missing, origin


def probe_capability(key: str, *, refresh: bool = False) -> CapabilityStatus:
    """Import one capability module and report honestly whether it is usable."""
    module_name = CAPABILITY_MODULES[key]
    if not refresh and key in _CACHE and _CACHE.get("keys", {}).get(key) is not None:
        cached = _CACHE["keys"][key]
        if time.time() - cached[0] < _CACHE_TTL_SECONDS:
            return cached[1]
    _CACHE.setdefault("keys", {})

    status: CapabilityStatus
    try:
        spec = importlib.util.find_spec(module_name)
    except (ImportError, ValueError) as exc:
        status = CapabilityStatus(key, module_name, STATUS_DEPENDENCY_MISSING,
                                  error=f"{type(exc).__name__}: {exc}")
        _CACHE["keys"][key] = (time.time(), status)
        return status
    if spec is None:
        status = CapabilityStatus(key, module_name, STATUS_DEPENDENCY_MISSING,
                                  error=f"module {module_name} not found on sys.path")
        _CACHE["keys"][key] = (time.time(), status)
        return status

    try:
        module = importlib.import_module(module_name)
    except Exception as exc:  # noqa: BLE001 - reported verbatim, never hidden
        status = CapabilityStatus(key, module_name, STATUS_DEPENDENCY_MISSING,
                                  error=f"{type(exc).__name__}: {exc}")
        _CACHE["keys"][key] = (time.time(), status)
        return status

    for sub in CAPABILITY_SUBMODULES.get(key, ()):
        try:
            importlib.import_module(sub)
        except Exception as exc:  # noqa: BLE001
            status = CapabilityStatus(key, module_name, STATUS_DEPENDENCY_MISSING,
                                      error=f"{sub}: {type(exc).__name__}: {exc}")
            _CACHE["keys"][key] = (time.time(), status)
            return status

    entry_points, missing, origin = _probe_entry_points(module, key)
    status = CapabilityStatus(
        key, module_name,
        STATUS_OK if not missing else STATUS_DEPENDENCY_MISSING,
        error=None if not missing else f"missing façade functions: {missing}",
        entry_points=entry_points, missing_entry_points=missing, search_roots=origin,
    )
    _CACHE["keys"][key] = (time.time(), status)
    return status


def require_capabilities(keys: list[str] | tuple[str, ...], *, stage: str = "") -> None:
    """Raise ``SynLabError(DEPENDENCY_CAPABILITY_MISSING)`` when a capability is unusable."""
    from ..errors import ErrorCode, SynLabError

    missing = []
    for key in keys:
        if key not in CAPABILITY_MODULES:
            missing.append({"key": key, "reason": "unregistered capability key"})
            continue
        probe = probe_capability(key)
        if not probe.available:
            missing.append({"key": key, "module": probe.module, "reason": probe.error or "unavailable"})
    if missing:
        raise SynLabError(
            ErrorCode.DEPENDENCY_CAPABILITY_MISSING,
            "required capabilities are not available: "
            + ", ".join(f"{m['key']}({m.get('module', '?')})" for m in missing),
            stage=stage or "capabilities.require",
            evidence_refs=[m.get("module", "") for m in missing if m.get("module")],
            measurements={"missing": missing},
        )


# --------------------------------------------------------------------------- env
def _probe_env(name: str) -> dict[str, Any]:
    if name == "blender_bpy":
        ok = importlib.util.find_spec("bpy") is not None
        return {"id": name, "status": STATUS_OK if ok else STATUS_ENV_MISSING,
                "detail": "bpy module importable" if ok else "Blender/bpy unavailable; "
                          "renderer=blender routes are blocked, software_rasterizer stays available"}
    if name == "cuda":
        try:
            import torch  # noqa: PLC0415

            ok = bool(torch.cuda.is_available())
            return {"id": name, "status": STATUS_OK if ok else STATUS_ENV_MISSING,
                    "detail": f"torch {torch.__version__}, cuda_available={ok}"}
        except Exception as exc:  # noqa: BLE001
            return {"id": name, "status": STATUS_ENV_MISSING, "detail": f"torch import failed: {exc}"}
    if name == "colmap":
        ok = importlib.util.find_spec("pycolmap") is not None
        return {"id": name, "status": STATUS_OK if ok else STATUS_ENV_MISSING,
                "detail": "pycolmap importable (library only; no standalone COLMAP binary)"
                if ok else "pycolmap unavailable"}
    for module_name, detail in (("gmsh", "gmsh meshing backend"), ("open3d", "Open3D geometry backend"),
                                ("faiss", "FAISS exact index"), ("trimesh", "trimesh IO/GLB export")):
        if name == module_name:
            ok = importlib.util.find_spec(module_name) is not None
            return {"id": name, "status": STATUS_OK if ok else STATUS_ENV_MISSING,
                    "detail": detail if ok else f"{module_name} unavailable"}
    return {"id": name, "status": "NA", "detail": "unregistered env probe"}


def env_report() -> dict[str, Any]:
    return {name: _probe_env(name) for name in ENV_PROBES}


# --------------------------------------------------------------------------- aggregate
def capability_report(*, refresh: bool = False) -> dict[str, Any]:
    if not refresh and _CACHE.get("report") is not None and time.time() - _CACHE["at"] < _CACHE_TTL_SECONDS:
        return _CACHE["report"]
    modules = {key: probe_capability(key, refresh=refresh).as_dict() for key in CAPABILITY_MODULES}
    report = {
        "modules": modules,
        "env": env_report(),
        "available": sorted(k for k, v in modules.items() if v["available"]),
        "missing": sorted(k for k, v in modules.items() if not v["available"]),
        "python": sys.version.split()[0],
        "probed_at": time.time(),
    }
    _CACHE["report"] = report
    _CACHE["at"] = time.time()
    return report
