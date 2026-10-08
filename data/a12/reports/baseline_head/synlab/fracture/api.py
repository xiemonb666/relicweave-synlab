"""Fracture façade: shared cutter, four required backends, provenance and QA.

The heavy lifting lives in :mod:`synlab.fracture.cut` (closed shared cutter body),
:mod:`synlab.fracture.event` (one shared discrete C for both sides) and
:mod:`synlab.fracture.fragment` (pieces, interfaces, audit).  This module is the single
entry point the pipeline and the CLI use, and it is where the backend registry lives.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ..canonical import hash_json
from ..errors import ErrorCode, SynLabError
from ..registry import register_fracture_backend
from ..roles import (
    FRAME_WORLD,
    ROLE_CUTTER,
    ROLE_FRAGMENT_MESH,
    SCHEMA_CUTTER,
    SCHEMA_FRAGMENT,
    UNIT_MM,
)
from ..schemas.runtime import CutBasis, CutterResult, FractureResult
from ..storage.mesh_io import with_face_attrs
from . import cut as cut_mod
from . import event as event_mod
from . import fragment as fragment_mod
from .spec import BACKEND_PLANE, BACKEND_ROUGH, FractureSpec

BACKEND_SECONDARY = "secondary_fracture"
BACKEND_WARPED = "warped_partition"
BACKEND_FRACTURE_MODES = "fracture_modes"

__all__ = [
    "make_closed_cutter", "fracture_event", "audit_fracture", "commit_fracture",
    "commit_cutter", "BUILT_BACKENDS", "PENDING_BACKENDS",
]

#: Backends implemented in this build; the pipeline records the honest status per event.
BUILT_BACKENDS = ("plane_shared_cut", "rough_shared_cut", BACKEND_SECONDARY)
PENDING_BACKENDS = (BACKEND_WARPED, BACKEND_FRACTURE_MODES)


# ---------------------------------------------------------------------------- registry
@register_fracture_backend("plane_shared_cut", "共享平面切割", applicable={"shell": True, "solid": True},
                           notes="analytic plane cut with one shared closed cutter body")
def _backend_plane(spec: Any = None, **_: Any) -> str:  # pragma: no cover - registry marker
    return "plane_shared_cut"


@register_fracture_backend("rough_shared_cut", "共享粗糙切割",
                           applicable={"shell": True, "solid": True},
                           notes="finite Fourier height field frozen once, shared by both sides")
def _backend_rough(spec: Any = None, **_: Any) -> str:  # pragma: no cover - registry marker
    return "rough_shared_cut"


@register_fracture_backend(BACKEND_SECONDARY, "二次破碎",
                           applicable={"shell": True, "solid": True},
                           notes="child event on the largest piece; adjacency is rebuilt from "
                                 "interface samples so old patches are clipped by membership")
def _backend_secondary(spec: Any = None, **_: Any) -> str:  # pragma: no cover - registry marker
    return BACKEND_SECONDARY


@register_fracture_backend(BACKEND_WARPED, "共享形变 Voronoi/Power 分区", status="PENDING",
                           applicable={"shell": True, "solid": True},
                           notes="weighted Power cells via scipy Qhull are implemented in the "
                                 "spec; the conformal gmsh PLC + shared warp stage is NOT "
                                 "implemented in this build (capability probe: gmsh 4.15.2 OK), "
                                 "so the backend reports PENDING instead of substituting planes")
def _backend_warped(spec: Any = None, **_: Any) -> str:  # pragma: no cover - registry marker
    return BACKEND_WARPED


@register_fracture_backend(BACKEND_FRACTURE_MODES, "fracture-modes 物理插件", status="MISSING",
                           applicable={},
                           notes="author code not fetched; license and units unverified, so the "
                                 "backend is registered as MISSING and never approximated")
def _backend_modes(spec: Any = None, **_: Any) -> str:  # pragma: no cover - registry marker
    return BACKEND_FRACTURE_MODES


# ---------------------------------------------------------------------------- cutter
def _default_basis(mother: Any, rng: np.random.Generator, spec: FractureSpec) -> CutBasis:
    mesh = mother.mesh
    points = np.asarray(mesh.vertices, dtype=np.float64)
    centroid = points.mean(axis=0)
    if spec.plane_normal is not None:
        normal = np.asarray(spec.plane_normal, dtype=np.float64).reshape(3)
        normal = normal / max(float(np.linalg.norm(normal)), 1e-12)
        anchor = np.asarray(spec.plane_point, dtype=np.float64).reshape(3) \
            if spec.plane_point is not None else centroid
    else:
        azimuth = float(rng.uniform(0.0, 2.0 * np.pi))
        # a mostly horizontal normal splits the body through its axis (a bowl into halves)
        normal = np.array([np.cos(azimuth), np.sin(azimuth), float(rng.uniform(-0.25, 0.25))])
        normal = normal / float(np.linalg.norm(normal))
        anchor = centroid
    return cut_mod.build_basis(points, normal, anchor=anchor, basis_id=spec_hash(spec))


def spec_hash(spec: FractureSpec) -> str:
    return hash_json({
        "backend": spec.backend, "rms": float(spec.target_rms_mm), "n_bands": spec.n_bands,
        "budget": float(spec.error_budget_mm),
        "plane_point": None if spec.plane_point is None else np.asarray(spec.plane_point).tolist(),
        "plane_normal": None if spec.plane_normal is None else np.asarray(spec.plane_normal).tolist(),
        "seeds": int(spec.n_seeds),
    })[:32]


def make_closed_cutter(mother: Any, spec: Any, rng: np.random.Generator,
                       basis: CutBasis | None = None) -> CutterResult:
    """Build the single closed cutter body shared by both sides of the cut."""
    fracture_spec = _coerce_spec(spec)
    basis = basis or _default_basis(mother, rng, fracture_spec)
    backend = str(fracture_spec.backend)
    target_rms = 0.0 if backend == BACKEND_PLANE else float(fracture_spec.target_rms_mm)
    height = cut_mod.make_height_field(basis, rng, target_rms_mm=target_rms,
                                       n_bands=fracture_spec.n_bands)
    mesh, report = cut_mod.build_closed_cutter(
        basis, height, error_budget_mm=float(fracture_spec.error_budget_mm))
    request_mm = float(fracture_spec.error_budget_mm)
    realized = float(report.get("realized_error_mm", float("inf")))
    if realized > request_mm + 1e-12:
        raise SynLabError(
            ErrorCode.PRECISION_NOT_REALIZED,
            f"cutter realized interpolation error {realized:.6f} mm exceeds the "
            f"{request_mm:.6f} mm budget",
            stage="fracture.make_closed_cutter",
            measurements={"realized_error_mm": realized, "budget_mm": request_mm},
        )
    meta = dict(report)
    from .booleans import mesh_hash

    meta["cutter_hash"] = mesh_hash(mesh)
    meta["height_field"] = height
    meta["backend"] = backend
    return CutterResult(
        mesh=mesh, basis=basis,
        h_fn=(lambda u, v: np.asarray(height.raw(u, v), dtype=np.float64)),
        requested_error_mm=request_mm, realized_error_mm=realized,
        triangles=int(len(np.asarray(mesh.faces))), meta=meta,
    )


def _coerce_spec(spec: Any) -> FractureSpec:
    from ..schemas.spec import FractureConfig

    if isinstance(spec, FractureSpec):
        return spec
    if isinstance(spec, FractureConfig):
        return FractureSpec(
            backend=spec.backend,
            target_rms_mm=float(np.mean(spec.rough_amplitude_mm)),
            error_budget_mm=float(spec.shared_surface_max_error_mm),
            n_seeds=int(spec.seed_count_range[1]),
        )
    if isinstance(spec, dict):
        return FractureSpec(**{k: v for k, v in spec.items() if k in FractureSpec.__dataclass_fields__})
    raise SynLabError(ErrorCode.SCHEMA_INVALID, f"unsupported fracture spec type {type(spec)!r}",
                      stage="fracture.api")


# ---------------------------------------------------------------------------- event
def fracture_event(mother: Any, spec: Any, rng: np.random.Generator, *, event_id: str) -> FractureResult:
    """Run one fracture event with the requested backend, or fail honestly."""
    fracture_spec = _coerce_spec(spec)
    backend = str(fracture_spec.backend)
    if backend in (BACKEND_WARPED, BACKEND_FRACTURE_MODES):
        raise SynLabError(
            ErrorCode.OPERATOR_NOT_REALIZED,
            f"backend {backend!r} is registered as "
            f"{'PENDING' if backend == BACKEND_WARPED else 'MISSING'}: the conformal shared-PLC "
            f"warp stage (gmsh) is not implemented in this build, so the pipeline refuses to "
            f"substitute a planar partition and call it a deformed backend",
            stage="fracture.fracture_event",
        )
    if backend == BACKEND_SECONDARY:
        return _secondary_event(mother, fracture_spec, rng, event_id=event_id)
    cutter = make_closed_cutter(mother, fracture_spec, rng)
    return event_mod.run_shared_cut(mother, cutter, event_id=event_id, backend=backend)


def _secondary_event(mother: Any, spec: FractureSpec, rng: np.random.Generator,
                     *, event_id: str) -> FractureResult:
    """Primary cut, then a child event on the largest piece.

    Adjacency is *recomputed from interface samples* rather than inherited: an old patch only
    stays an interface for a child that still contains that material area.  The clipping itself
    is performed by the truth layer, which filters samples by leaf membership (plan 30.5).
    """
    primary_spec = FractureSpec(backend=BACKEND_PLANE, error_budget_mm=spec.error_budget_mm)
    primary = fracture_event(mother, primary_spec, rng, event_id=event_id)
    pieces = [f for f in primary.fragments if not f.is_tiny]
    if not pieces:
        raise SynLabError(ErrorCode.FRACTURE_CONSERVATION_FAIL, "primary cut produced no piece",
                          stage="fracture.secondary")
    target = max(pieces, key=lambda f: float(f.volume_mm3))

    import copy as _copy

    child_mother = _copy.copy(mother)
    child_mother.mesh = target.mesh
    child_mother.meta = dict(getattr(mother, "meta", {}) or {})
    child_mother.meta["secondary_parent_fragment"] = target.fragment_id
    child_spec = FractureSpec(backend=BACKEND_PLANE, error_budget_mm=spec.error_budget_mm)
    child = fracture_event(child_mother, child_spec, rng, event_id=f"{event_id}_S1")

    from ..schemas.runtime import Fragment, InterfacePatch  # noqa: PLC0415

    children: list[Fragment] = []
    for frag in child.fragments:
        children.append(Fragment(
            fragment_id=f"{target.fragment_id}::{frag.fragment_id}",
            mesh=frag.mesh, volume_mm3=frag.volume_mm3, area_mm2=frag.area_mm2,
            face_origin_kind=frag.face_origin_kind, face_source_tri=frag.face_source_tri,
            face_interface_id=frag.face_interface_id, face_side=frag.face_side,
            component_id=frag.component_id, is_tiny=frag.is_tiny, parent_id=target.fragment_id,
            meta={**frag.meta, "ancestor": target.fragment_id, "secondary": True},
        ))
    kept = [f for f in primary.fragments if f.fragment_id != target.fragment_id]
    interfaces = list(primary.interfaces) + [
        InterfacePatch(**{**patch.__dict__,
                          "fragment_a": f"{target.fragment_id}::{patch.fragment_a}"
                          if patch.fragment_a == child.fragments[0].fragment_id else patch.fragment_a,
                          "fragment_b": f"{target.fragment_id}::{patch.fragment_b}"
                          if patch.fragment_b == child.fragments[0].fragment_id else patch.fragment_b})
        for patch in child.interfaces
    ]
    tree = {
        "event_id": event_id,
        "backend": BACKEND_SECONDARY,
        "parent_event": primary.event_tree,
        "child_events": [child.event_tree],
        "ancestor_of": {f.fragment_id: target.fragment_id for f in children},
        "patch_clip_policy": "membership_filtered_by_truth",
    }
    qa = dict(primary.qa)
    qa["secondary"] = {"parent": target.fragment_id, "children": [f.fragment_id for f in children],
                       "old_patch_policy": ("old interfaces stay in the record and are clipped to "
                                            "the child that still holds the shared area; the truth "
                                            "layer performs the membership filter")}
    return FractureResult(
        fragments=kept + children,
        interfaces=interfaces,
        event_tree=tree,
        debris=list(primary.debris) + list(child.debris),
        parent_id=primary.parent_id,
        backend=BACKEND_SECONDARY,
        qa=qa,
        cutter_ref=primary.cutter_ref,
        meta={"secondary_of": target.fragment_id},
    )


# ---------------------------------------------------------------------------- QA / commit
def audit_fracture(result: FractureResult, mother: Any) -> dict[str, Any]:
    """Volume conservation, overlap, shared-surface distance/normal and origin coverage."""
    report = fragment_mod.audit_fracture_result(result, mother)
    report.setdefault("backend", result.backend)
    return report


def commit_cutter(store: Any, cutter: CutterResult, *, lineage_id: str, split: str,
                  ancestry: Any = ()) -> Any:
    report = {k: v for k, v in cutter.meta.items() if k != "height_field"}
    with_face_attrs(cutter.mesh)
    return store.commit_asset(
        role=ROLE_CUTTER, schema=SCHEMA_CUTTER, unit=UNIT_MM, frame=FRAME_WORLD,
        payload={"mesh": cutter.mesh},
        meta={"basis_id": cutter.basis.basis_id, "triangles": int(cutter.triangles),
              "requested_error_mm": float(cutter.requested_error_mm),
              "realized_error_mm": float(cutter.realized_error_mm),
              "report": _jsonable(report)},
        qa={"ok": True, "realized_error_mm": float(cutter.realized_error_mm)},
        qa_status="QA_PASS", ancestry=list(ancestry), lineage_id=lineage_id, split=split,
    )


def commit_fracture(store: Any, result: FractureResult, *, lineage_id: str, split: str,
                    ancestry: Any = ()) -> list[Any]:
    records = []
    for fragment in result.fragments:
        with_face_attrs(
            fragment.mesh,
            origin_kind=np.asarray(fragment.face_origin_kind, dtype=np.uint8),
            source_triangle=np.asarray(fragment.face_source_tri, dtype=np.int32),
            interface_id=np.asarray(fragment.face_interface_id, dtype=np.int32),
            side=np.asarray(fragment.face_side, dtype=np.int8),
        )
        records.append(store.commit_asset(
            role=ROLE_FRAGMENT_MESH, schema=SCHEMA_FRAGMENT, unit=UNIT_MM, frame=FRAME_WORLD,
            payload={"mesh": fragment.mesh},
            meta={"fragment_id": fragment.fragment_id, "event_id": result.event_tree.get("event_id"),
                  "backend": result.backend, "component_id": int(fragment.component_id),
                  "is_tiny": bool(fragment.is_tiny), "volume_mm3": float(fragment.volume_mm3),
                  "area_mm2": float(fragment.area_mm2), "parent_id": fragment.parent_id},
            qa={"ok": True}, qa_status="QA_PASS", ancestry=list(ancestry),
            lineage_id=lineage_id, split=split,
        ))
    return records


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
