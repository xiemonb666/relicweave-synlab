"""Degrade-side narrow-band physical damage for P02 / P03 / P04.

This module is the *operator implementation* layer for the three P axes whose declared effect
is smaller than the frozen global SDF grid spacing (see :mod:`synlab.degrade.narrowband` for
the measurements that justify the approach).  It is written entirely inside ``synlab/degrade``
and only **consumes** public ``synlab.physical`` helpers (``sdf``, ``fields``,
``operators._cutter_ellipsoid``, ``api.register_components``); nothing under
``synlab/physical`` is modified.

The returned object is a real :class:`synlab.schemas.runtime.PhysicalResult` built through the
same ``register_components`` identity policy as ``synlab.physical.api.apply_damage``
(plan 30.8: every connected body is kept, one representative is chosen, debris is retained and
counted in the material ledger), so ``synlab.degrade.axes._PhysicalAxis._apply`` can treat it
exactly like an ``apply_damage`` result.
"""

from __future__ import annotations

import gc
from typing import Any

import numpy as np
import trimesh

from ..errors import ErrorCode, SynLabError
from ..physical import fields as F
from ..physical import sdf as S
from ..physical.operators import _cutter_ellipsoid
from ..schemas.runtime import PhysicalResult
from . import narrowband as NB

__all__ = ["run_narrowband_damage", "NARROWBAND_AXES"]

#: Axes served by this module (everything else keeps the shipped ``run_damage`` path).
NARROWBAND_AXES = ("P02", "P03", "P04")


def _geometry_hash(mesh: trimesh.Trimesh) -> str:
    from ..physical.api import _geometry_hash as physical_geometry_hash

    return physical_geometry_hash(mesh)


def _assemble(mesh: trimesh.Trimesh, source: trimesh.Trimesh, recipe: Any, *,
              measurements: dict[str, float], units: dict[str, str], details: dict[str, Any],
              realized: bool, fragment: Any) -> PhysicalResult:
    """Wrap a damaged body into a ``PhysicalResult`` with the plan-30.8 component ledger."""
    from ..physical.api import (DAMAGE_SEMANTICS, GEOMETRY_HASH_ALGORITHM,
                                _postassembly_physical_qa,
                                register_components)

    source_volume = float(abs(source.volume))
    min_ratio = float(recipe.meta.get("min_representative_ratio", 0.005))
    parts = S.component_split(mesh)
    if not parts:
        raise SynLabError(ErrorCode.TARGET_INFEASIBLE,
                          f"{recipe.axis_id}: the narrow-band result carries no connected body",
                          stage="degrade.physical_narrowband")
    components, representative_map, ledger = register_components(
        parts, clean_fragment_id=str(getattr(fragment, "fragment_id", "fragment") or "fragment"),
        source_volume_mm3=source_volume, min_support_rel=min_ratio)
    lost_volume = float(ledger["lost_volume_mm3"])
    qa = {
        "status": "PASS" if realized else "FAIL",
        "identity": False, "level": int(recipe.level), "realized": bool(realized),
        "operator_effect_realized": bool(realized),
        "physical_acceptance": bool(realized),
        "geometry_changed": True,
        "geometry_hash_algorithm": GEOMETRY_HASH_ALGORITHM,
        "source_geometry_hash": _geometry_hash(source),
        "result_geometry_hash": _geometry_hash(mesh),
        "geometry_hash_unchanged": bool(_geometry_hash(mesh) == _geometry_hash(source)),
        "component_count": len(components), "ledger": ledger,
        "damage_semantics": DAMAGE_SEMANTICS,
        "sdf_pipeline": details.get("sdf_pipeline", {}),
        "narrowband": details.get("narrowband", {}),
        "failure_code": None if realized else ErrorCode.OPERATOR_NOT_REALIZED.value,
    }
    meta = {
        "declared": recipe.declared(), "identity": False, "ledger": ledger,
        "axis_id": recipe.axis_id, "variant": recipe.variant, "level": int(recipe.level),
        "geometry_changed": True, "frozen": recipe.frozen(),
        "geometry_hash_algorithm": GEOMETRY_HASH_ALGORITHM,
        "source_geometry_hash": _geometry_hash(source),
        "damage_semantics": DAMAGE_SEMANTICS,
        "measured": dict(measurements), "measurement_units": dict(units),
        "details": details, "appearance": None, "appearance_updated": False,
        "damage_backend": "synlab.degrade.physical_narrowband",
    }
    result = PhysicalResult(
        mother_id=str(getattr(recipe, "meta", {}).get("mother_id", "") or ""),
        clean_ref=str(getattr(recipe, "meta", {}).get("fragment_id", "") or ""),
        event_id=str(getattr(recipe, "meta", {}).get("event_id", "") or ""),
        recipe_id=recipe.recipe_id or f"{recipe.axis_id}:{recipe.variant}:L{recipe.level}",
        version=1, components=components, lost_volume_mm3=lost_volume,
        lost_volume_ratio=float(lost_volume / max(source_volume, 1e-12)),
        representative_map=representative_map, physical_truth=None, qa=qa, meta=meta)
    postassembly_qa = _postassembly_physical_qa(
        source, components, ledger, result_lost_volume_mm3=lost_volume)
    result.qa["postassembly"] = postassembly_qa
    failure_codes = list(result.qa.get("failure_codes") or [])
    failure_codes.extend(postassembly_qa["failure_codes"])
    if result.qa.get("failure_code"):
        failure_codes.append(str(result.qa["failure_code"]))
    result.qa["failure_codes"] = sorted(set(failure_codes))
    wall_guard_status = str((details.get("wall_guard") or {}).get("status", "")) or None
    if wall_guard_status is not None:
        result.qa["wall_guard_status"] = wall_guard_status
    accepted = bool(realized and postassembly_qa["status"] == "PASS"
                    and wall_guard_status in (None, "PASS"))
    result.qa["realized"] = accepted
    result.qa["physical_acceptance"] = accepted
    if not accepted:
        result.physical_truth = None
        result.meta["physical_truth_status"] = "SKIPPED_PHYSICAL_QA_FAILURE"
    if postassembly_qa["status"] != "PASS":
        result.qa["status"] = "FAIL"
        result.qa["reason"] = "postassembly entity QA failed; see postassembly.checks"
        result.qa["failure_code"] = (result.qa.get("failure_code")
                                      or next(iter(postassembly_qa["failure_codes"]),
                                              "POSTASSEMBLY_QA_FAILED"))
    elif wall_guard_status not in (None, "PASS"):
        result.qa["status"] = "FAIL"
        result.qa["reason"] = "physical wall guard was not verified"
        result.qa["failure_code"] = "WALL_GUARD_UNKNOWN"
        result.qa["failure_codes"] = sorted(set(
            [*result.qa["failure_codes"], "WALL_GUARD_UNKNOWN"]))
    elif not realized:
        result.qa["status"] = "FAIL"
    return result


def _failure(code: ErrorCode, message: str, *, stage: str, measurements: dict[str, Any],
             seed_ref: str = "") -> SynLabError:
    return SynLabError(code, message, stage=stage, measurements=measurements, seed_ref=seed_ref)


# ======================================================================================
# dispatch
# ======================================================================================
def run_narrowband_damage(mesh: trimesh.Trimesh, recipe: Any, *, fragment: Any = None,
                          rng: Any = None) -> PhysicalResult:
    """Dispatch one level of P02 / P03 / P04 to its narrow-band implementation."""
    axis_id = str(recipe.axis_id)
    if axis_id == "P02":
        return _round_edge(mesh, recipe, fragment=fragment)
    if axis_id == "P03":
        return _erode_interface(mesh, recipe, fragment=fragment)
    if axis_id == "P04":
        return _chip_material(mesh, recipe, fragment=fragment)
    raise SynLabError(ErrorCode.SCHEMA_INVALID,
                      f"{axis_id} has no narrow-band implementation", stage="degrade.narrowband")


# ======================================================================================
# P02 -- edge-local inward fillet
# ======================================================================================
def _round_edge(mesh: trimesh.Trimesh, recipe: Any, *, fragment: Any = None) -> PhysicalResult:
    """P02: subtract the analytic inward fillet of every convex edge of the ROI boundary."""
    strength = float(recipe.parameter("recession_strength", 0.0))
    radius = float(recipe.parameter("edge_width_mm", recipe.meta.get("edge_width_mm", 0.4)))
    variant = str(recipe.variant or "sdf_fillet")
    if strength <= 0:
        raise _failure(ErrorCode.DAMAGE_EFFECT_MISSING, "P02 recession_strength must be > 0",
                       stage="degrade.P02", measurements={"recession_strength": strength})
    # strength is a dimensionless 0..1 knob on the same frozen section: scale the depth, not the
    # radius, so all five levels share one fillet family (plan 30.7: only t moves).
    effective_radius = radius * strength
    if effective_radius <= 1e-6:
        raise _failure(ErrorCode.DAMAGE_EFFECT_MISSING,
                       "P02 effective fillet radius underflowed", stage="degrade.P02",
                       measurements={"recession_strength": strength, "edge_width_mm": radius})

    roi_ids, roi_info = F.roi_faces(mesh, fragment, dict(recipe.roi or {"kind": "interface"}))
    edges, edge_info = NB.roi_boundary_edges(
        mesh, roi_ids, min_angle_deg=float(recipe.meta.get("min_edge_angle_deg", 45.0)))
    if not edges:
        raise _failure(ErrorCode.NA_NOT_APPLICABLE,
                       "P02 needs convex edges on the ROI boundary; the ROI boundary carries "
                       "none above the frozen minimum dihedral angle",
                       stage="degrade.P02", measurements={"roi": roi_info, "edges": edge_info})
    body, field_info = NB.edge_recession_body(mesh, edges, effective_radius)
    report = NB.assert_watertight(body, label="P02 body", stage="degrade.P02")
    accepted, clip_info = S.intersect_with_source(body, mesh)
    del body
    gc.collect()

    source_volume = float(abs(mesh.volume))
    lost_volume = source_volume - float(abs(accepted.volume))
    # independent spatial measurement: original interface samples whose material is gone
    removed = _removed_surface_points(accepted, mesh, n=2500,
                                      seed=int(recipe.basis.get("seed", 0)) + 5)
    inside = _inside_mask(mesh, accepted, n=3000, seed=int(recipe.basis.get("seed", 0)) + 11)
    depth_stats = dict(field_info["vertex_depth_stats"])
    measurements = {
        "recession_strength": float(strength),
        "edge_width_mm": float(radius),
        "effective_fillet_radius_mm": float(effective_radius),
        "boundary_edges": float(len(edges)),
        "edge_length_total_mm": float(field_info["edge_length_total_mm"]),
        "edge_dihedral_median_deg": float(field_info["theta_median_deg"]),
        "planned_max_recession_mm": float(field_info["max_depth_analytic_mm"]),
        "planned_contact_width_mm": float(field_info["contact_analytic_mm"]),
        "measured_max_recession_mm": float(depth_stats["max_depth_mm"]),
        "measured_mean_recession_mm": removed["mean_mm"],
        "measured_recession_p95_mm": removed["p95_mm"],
        "moved_vertices": float(field_info["affected_vertices"]),
        "moved_vertices_fraction": float(field_info["moved_vertices_fraction"]),
        "removed_samples": float(removed["n"]),
        "lost_volume_mm3": float(max(lost_volume, 0.0)),
        "lost_volume_ratio": float(max(lost_volume, 0.0) / max(source_volume, 1e-12)),
        "clipped_volume_mm3": float(clip_info["clipped_volume_mm3"]),
        "watertight": 1.0 if report["watertight"] else 0.0,
        "min_thickness_mm": float(S.ray_thickness(accepted, n_samples=200, seed=4)["min_mm"]),
        **_drift_measurements(accepted, mesh, roi_ids, seed=int(recipe.basis.get("seed", 0)) + 3),
        "max_outside_clean_mm": float(inside["max_outside_mm"]),
    }
    measurements["components"] = float(len(S.component_split(accepted)))
    hard = bool(measurements["lost_volume_mm3"] > 1e-9
                and measurements["measured_max_recession_mm"] > 0.0
                and report["watertight"])
    units = {"lost_volume_mm3": "mm3", "measured_max_recession_mm": "mm",
             "measured_mean_recession_mm": "mm", "planned_max_recession_mm": "mm",
             "edge_width_mm": "mm", "effective_fillet_radius_mm": "mm",
             "edge_length_total_mm": "mm", **_drift_units(),
             "min_thickness_mm": "mm", "max_outside_clean_mm": "mm",
             "planned_contact_width_mm": "mm"}
    details = {
        "narrowband": {"backend": "degrade.physical_narrowband.round_edge",
                       "method": "edge-local inward rolling-ball recession applied along the "
                                 "vertex normals of the ROI-boundary band (plan 12.2 edge "
                                 "rounding; compact support, rim pinned, no global level set)",
                       "roi": roi_info, "edge_info": edge_info, "field": field_info,
                       "clip": clip_info, "variant": variant,
                       "radius_rule": "effective_radius = edge_width_mm * recession_strength",
                       "new_edges": ("planar chamfer variant" if variant == "chamfer"
                                     else "smooth arc: no new sharp edge by construction")},
        "sdf_pipeline": {"spacing": {"spacing_mm": None, "basis": "SURFACE_OPERATOR"},
                         "note": "no voxel grid is used; the recession is analytic"},
    }
    return _assemble(accepted, mesh, recipe, measurements=measurements, units=units,
                     details=details, realized=hard, fragment=fragment)


# ======================================================================================
# P03 -- narrow-band smooth recession
# ======================================================================================
def _p03_preflight(mesh: trimesh.Trimesh, recipe: Any) -> tuple[float, float, float | None, int]:
    """Reject malformed P03 parameters/source before the surface operator runs."""
    try:
        depth = float(recipe.parameter("depth_mm", 0.0))
        scale_mm = float(recipe.parameter("corr_length_mm", recipe.meta.get("corr_length_mm", 6.0)))
    except (TypeError, ValueError, OverflowError) as exc:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          "P03 depth_mm and corr_length_mm must be finite positive numbers",
                          stage="degrade.P03.preflight") from exc
    if not np.isfinite(depth) or depth <= 0.0:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "P03 depth_mm must be finite and > 0",
                          stage="degrade.P03.preflight", measurements={"depth_mm": depth})
    if not np.isfinite(scale_mm) or scale_mm <= 0.0:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          "P03 corr_length_mm must be finite and > 0",
                          stage="degrade.P03.preflight", measurements={"corr_length_mm": scale_mm})
    try:
        guard_value = recipe.qa.get("min_wall_thickness_mm")
        guard_mm = None if guard_value is None else float(guard_value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          "P03 min_wall_thickness_mm must be finite and > 0 when declared",
                          stage="degrade.P03.preflight") from exc
    if guard_mm is not None and (not np.isfinite(guard_mm) or guard_mm <= 0.0):
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          "P03 min_wall_thickness_mm must be finite and > 0 when declared",
                          stage="degrade.P03.preflight",
                          measurements={"min_wall_thickness_mm": guard_mm})
    try:
        vertices = np.asarray(mesh.vertices)
        faces = np.asarray(mesh.faces)
        if (vertices.ndim != 2 or vertices.shape[1:] != (3,) or len(vertices) < 4
                or not np.issubdtype(vertices.dtype, np.number)
                or not np.isfinite(vertices).all()):
            raise ValueError("vertices must be a finite non-empty (N, 3) array")
        if (faces.ndim != 2 or faces.shape[1:] != (3,) or len(faces) < 4
                or not np.issubdtype(faces.dtype, np.integer)
                or int(faces.min()) < 0 or int(faces.max()) >= len(vertices)):
            raise ValueError("faces must be a non-empty integer (M, 3) array with valid indices")
        face_areas = np.asarray(mesh.area_faces, dtype=np.float64)
        volume = float(mesh.volume)
        area = float(mesh.area)
        if (not np.isfinite(face_areas).all() or np.any(face_areas <= 0.0)
                or not np.isfinite(area) or area <= 0.0
                or not np.isfinite(volume) or volume <= 0.0):
            raise ValueError("source area and signed volume must be finite and positive")
        if not bool(mesh.is_watertight) or not bool(mesh.is_winding_consistent):
            raise ValueError("source must be watertight with consistent winding")
    except Exception as exc:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"P03 source failed preflight: {type(exc).__name__}: {exc}",
                          stage="degrade.P03.preflight") from exc
    samples = int(recipe.meta.get("thickness_samples", 400))
    if samples <= 0:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          "P03 thickness_samples must be > 0",
                          stage="degrade.P03.preflight", measurements={"thickness_samples": samples})
    return depth, scale_mm, guard_mm, samples


def _erode_interface(mesh: trimesh.Trimesh, recipe: Any, *, fragment: Any = None) -> PhysicalResult:
    """P03: non-negative smooth recession; wall acceptance awaits a qualified thickness check."""
    depth, scale_mm, guard_mm, thickness_samples = _p03_preflight(mesh, recipe)
    roi_ids, roi_info = F.roi_faces(mesh, fragment, dict(recipe.roi or {"kind": "interface"}))
    if len(roi_ids) == 0:
        raise _failure(ErrorCode.NA_NOT_APPLICABLE, "P03 ROI selects no face",
                       stage="degrade.P03", measurements={"roi": roi_info})
    field = F.FourierField.from_payload(recipe.basis["field"])
    transfer = np.asarray(mesh.triangles_center, dtype=np.float64)
    raw = np.zeros(len(mesh.faces), dtype=np.float64)
    field_values = np.asarray(field(transfer[roi_ids]), dtype=np.float64)
    if field_values.shape != (len(roi_ids),) or not np.isfinite(field_values).all():
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          "P03 frozen recession field must return one finite value per ROI face",
                          stage="degrade.P03.preflight")
    raw[roi_ids] = np.clip(field_values, 0.0, 1.0)
    normalizer = float(max(np.percentile(raw[roi_ids], 99.0), 1e-6))
    amplitude = np.clip(raw / normalizer, 0.0, 1.0)

    mask = np.zeros(len(mesh.faces), dtype=bool)
    mask[roi_ids] = True
    thickness_seed = int(recipe.basis.get("seed", 0)) + 9
    scale = 1.0
    depth_field = amplitude * depth * scale
    body, detail = NB.recessed_body(mesh, roi_ids, depth_field, recipe.basis)
    report = NB.assert_watertight(body, label="P03 body", stage="degrade.P03")
    # Kept as a diagnostic only. This legacy first-hit probe is explicitly not a wall guard.
    legacy_probe = NB.paired_thickness(body, mesh, n_samples=thickness_samples,
                                      seed=thickness_seed, face_mask=mask)
    vertex_depth = np.asarray(detail["vertex_depth_field"], dtype=np.float64)
    accepted, clip_info = S.intersect_with_source(body, mesh)
    del body
    gc.collect()
    source_volume = float(mesh.volume)
    lost_volume = source_volume - float(abs(accepted.volume))
    predicted = float(np.sum(np.asarray(mesh.area_faces, dtype=np.float64)[roi_ids]
                             * amplitude[roi_ids] * depth * scale))
    surface_distance = _sampled_vertex_surface_distance(mesh, accepted, vertex_depth)
    inside = _inside_mask(mesh, accepted, n=3000, seed=int(recipe.basis.get("seed", 0)) + 13)
    measurements = {
        "depth_mm": float(depth),
        "applied_depth_mm": float(depth * scale),
        "corr_length_mm": float(scale_mm),
        "field_normalizer": float(normalizer),
        "field_id": str(field.field_id),
        "roi_faces": float(len(roi_ids)),
        "planned_max_recession_mm": float(depth * scale),
        "planned_mean_recession_mm": float(depth * scale * float(np.mean(amplitude[roi_ids]))),
        "lost_volume_mm3": float(max(lost_volume, 0.0)),
        "linearised_predicted_loss_mm3": predicted,
        "lost_volume_vs_linear_ratio": float(lost_volume / max(predicted, 1e-12)),
        "lost_volume_ratio": float(max(lost_volume, 0.0) / max(source_volume, 1e-12)),
        "clipped_volume_mm3": float(clip_info["clipped_volume_mm3"]),
        **_drift_measurements(accepted, mesh, roi_ids, seed=int(recipe.basis.get("seed", 0)) + 3),
        "rim_vertices_pinned": float(detail["rim_vertices_pinned"]),
        "narrowband_vertices": float(detail["roi_vertices"]),
        "max_outside_clean_mm": float(inside["max_outside_mm"]),
    }
    if surface_distance["status"] == "COMPLETE_DIAGNOSTIC_ONLY":
        measurements["sampled_source_vertex_to_result_surface_distance_max_mm"] = float(
            surface_distance["max_mm"])
        measurements["sampled_source_vertex_to_result_surface_distance_mean_mm"] = float(
            surface_distance["mean_mm"])
    measurements["watertight"] = 1.0 if report["watertight"] else 0.0
    measurements["components"] = float(len(S.component_split(accepted)))
    hard = bool(measurements["lost_volume_mm3"] > 1e-9 and report["watertight"])
    units = {"depth_mm": "mm", "applied_depth_mm": "mm", "lost_volume_mm3": "mm3",
             "sampled_source_vertex_to_result_surface_distance_max_mm": "mm",
             "sampled_source_vertex_to_result_surface_distance_mean_mm": "mm",
             **_drift_units(), "linearised_predicted_loss_mm3": "mm3",
             "planned_max_recession_mm": "mm"}
    wall_guard = {
        "status": "UNKNOWN",
        "required_min_wall_thickness_mm": guard_mm,
        "reason": "the legacy paired first-hit ray probe is not a qualified wall-thickness instrument",
    }
    details = {
        "narrowband": {"backend": "degrade.physical_narrowband.erode_interface",
                       "method": "per-vertex inward normal offset by the frozen smooth depth "
                                 "field, pinned to zero on the ROI rim; untouched surface keeps "
                                 "the original triangles (plan 12.1/12.2 narrow band)",
                       "roi": roi_info, "field": {k: v for k, v in detail.items()
                                                  if k != "vertex_depth_field"},
                       "legacy_paired_thickness_probe": {
                           "valid_for_wall_guard": False,
                           "status": "LEGACY_INVALID_FOR_WALL",
                           "result": legacy_probe,
                       },
                       "sampled_source_vertex_to_result_surface_distance": surface_distance,
                       "clip": clip_info, "grid": "none (surface operator, not a voxel field)",
                       "spacing": {"spacing_mm": 0.0, "basis": "SURFACE_OPERATOR",
                                   "note": "the declared depth is applied directly, so no grid "
                                           "spacing has to resolve it"}},
        "wall_guard": wall_guard,
        "sdf_pipeline": {"spacing": {"spacing_mm": 0.0, "basis": "SURFACE_OPERATOR"}},
    }
    return _assemble(accepted, mesh, recipe, measurements=measurements, units=units,
                     details=details, realized=hard, fragment=fragment)


# ======================================================================================
# P04 -- frozen cutter, 1-D geometric search on the declared contact loss
# ======================================================================================
def _chip_material(mesh: trimesh.Trimesh, recipe: Any, *, fragment: Any = None) -> PhysicalResult:
    """P04: fixed cutter position/direction, size found by a 1-D search on the target."""
    target = float(recipe.parameter("contact_loss_target", 0.0))
    if target <= 0:
        raise _failure(ErrorCode.DAMAGE_EFFECT_MISSING, "P04 target must be > 0",
                       stage="degrade.P04", measurements={"contact_loss_target": target})
    variant = str(recipe.variant or "contact_loss")
    basis = dict(recipe.basis or {})
    center = np.asarray(basis["center_mm"], dtype=np.float64)
    direction = np.asarray(basis["direction"], dtype=np.float64)
    direction = direction / max(float(np.linalg.norm(direction)), 1e-12)
    base_radii = np.asarray(basis.get("radii_mm", [1.0, 1.0, 1.0]), dtype=np.float64)
    e1 = np.cross(direction, np.array([0.0, 0.0, 1.0]))
    if float(np.linalg.norm(e1)) < 1e-6:
        e1 = np.cross(direction, np.array([0.0, 1.0, 0.0]))
    e1 = e1 / max(float(np.linalg.norm(e1)), 1e-12)
    e2 = np.cross(direction, e1)
    axes = np.stack([e1, e2, direction], axis=1)
    roi = {"kind": "all"} if variant == "volume_loss" else dict(recipe.roi or {"kind": "interface"})
    source_volume = float(abs(mesh.volume))
    min_ratio = float(recipe.meta.get("min_representative_ratio", 0.005))
    tolerance = float(recipe.meta.get("target_tol", 0.01))
    max_scale = float(recipe.meta.get("cutter_max_scale", 128.0))
    density = float(recipe.meta.get("contact_density_mm", 0.5))

    def scale_radii(scale: float) -> np.ndarray:
        return np.maximum(base_radii * float(scale), 1e-4)

    def evaluate(scale: float) -> dict[str, Any]:
        cutter = _cutter_ellipsoid(center, axes, scale_radii(scale),
                                   subdivisions=int(recipe.meta.get("cutter_subdivisions", 2)))
        try:
            body = S.boolean_op("difference", [mesh, cutter])
        except SynLabError as exc:
            return {"scale": float(scale), "empty": True, "error": exc.code.value,
                    "loss": 0.0, "volume_ratio": 0.0, "body": None}
        contact = F.interface_contact(mesh, fragment, roi, body, eps_mm=2e-3,
                                      density_mm=density)
        parts = S.component_split(body)
        volumes = sorted((float(abs(p.volume)) for p in parts), reverse=True)
        if variant == "volume_loss":
            loss = 1.0 - float(abs(body.volume)) / max(source_volume, 1e-12)
        else:
            loss = float(contact["lost_fraction"])
        return {"scale": float(scale), "empty": False, "body": body, "contact": contact,
                "components": parts, "volumes": volumes,
                "volume_ratio": (volumes[0] / source_volume) if volumes else 0.0,
                "loss": float(loss),
                "radius_mm": float(np.max(scale_radii(scale)))}

    trace: list[dict[str, Any]] = []

    def record(state: dict[str, Any]) -> None:
        trace.append({"scale": state["scale"], "loss": float(state["loss"]),
                      "volume_ratio": float(state["volume_ratio"]),
                      "empty": bool(state.get("empty", False)),
                      "radius_mm": float(state.get("radius_mm", 0.0))})

    # ------------------------------------------------------------------ phase 1: bracket
    # The cutter family is nested in ``scale`` and the declared loss is monotone in it (measured
    # on the probe with an audit basis: 0.033 @1 -> 0.093 @8 -> 0.227 @16 -> 0.571 @32 -> 0.84
    # @~48 -> 0.99 @56; the body is gone by 64).  Growth keeps doubling while the state stays
    # feasible and below the target, and stops at the first state that is infeasible *or* at or
    # above the target -- whichever comes first, so a feasible state above the target is never
    # stepped over.  Two earlier versions are kept here as negative evidence: stopping at the
    # first infeasible scale reported TARGET_INFEASIBLE for a target of 0.5 that scale 32 misses
    # by 0.0137 and scale 48 reaches, and a "refine by halving" pass reached 0.844 @47 while the
    # bisection below reaches the target itself.
    below: dict[str, Any] | None = None      # feasible state strictly below the target
    best_scale = 0.0                         # largest scale proven feasible
    ceiling: dict[str, Any] | None = None    # first infeasible/empty state (upper bracket)
    high: dict[str, Any] | None = None       # feasible state at/above the target
    scale = 1.0
    growth_steps = 0
    max_growth = int(recipe.meta.get("search_growth_steps", 12))
    while growth_steps <= max_growth and scale <= max_scale:
        state = evaluate(scale)
        record(state)
        infeasible = bool(state.get("empty")) or float(state["volume_ratio"]) < min_ratio
        if infeasible:
            ceiling = state
            break
        best_scale = float(state["scale"])
        best_feasible = state
        if float(state["loss"]) >= target:
            # The doubling step overshoots (measured on an audit basis: target 0.1 is first
            # crossed at scale 16 with loss 0.2266).  Keep it as the *upper* bracket and let the
            # bisection below tighten it; an earlier version used it directly and reported
            # achieved 0.2266 for a declared 0.1.
            high = state
            break
        below = state
        scale *= 2.0
        growth_steps += 1
    # ------------------------------------------------------------------ phase 2: bisect
    # Bisect on ``[lo, hi]``, where ``lo`` is the largest scale proven feasible-and-below and
    # ``hi`` is either feasible-and-at/above or infeasible/empty.  The interval always exists --
    # scale 1 is feasible on every measured body -- which is what makes an unreachable target
    # detectable: after the bisection ``hi`` sits at the *ceiling* of the feasible family, and if
    # even that ceiling is below the target then no cutter in the frozen family reaches it.
    # Negative evidence for the loop structure: growing straight from 32 to 64 and giving up
    # reported TARGET_INFEASIBLE for a target of 0.8 that scale 48 does reach on the probe.
    bisect_started = False
    lo_scale = float(below["scale"]) if below is not None else 1.0
    if high is not None and float(high["scale"]) > lo_scale:
        hi_scale: float | None = float(high["scale"])
    elif ceiling is not None and float(ceiling["scale"]) > lo_scale:
        hi_scale = float(ceiling["scale"])
    else:
        hi_scale = None
    if hi_scale is not None:
        bisect_started = True
        for _ in range(int(recipe.meta.get("bisection_iterations", 24))):
            if (hi_scale - lo_scale) <= max(1e-6, 1e-6 * hi_scale):
                break
            mid = 0.5 * (lo_scale + hi_scale)
            state = evaluate(mid)
            record(state)
            infeasible = bool(state.get("empty")) or float(state["volume_ratio"]) < min_ratio
            if infeasible:
                hi_scale = mid
                continue
            best_scale = float(state["scale"])
            best_feasible = state
            if float(state["loss"]) >= target:
                hi_scale = mid
                high = state
                continue
            lo_scale = mid
            below = state
    if high is None or float(high["loss"]) < target:
        # the target was never reached inside the feasible cutter family: the ceiling found for
        # the representative-volume guard sits below it (or the effect saturates)
        achieved = float(best_feasible["loss"]) if best_feasible else 0.0
        ratio = float(best_feasible["volume_ratio"]) if best_feasible else 0.0
        reason = ("the cutter family would eliminate the representative body"
                  if ceiling is not None else
                  "the declared effect saturates below the target")
        raise _failure(
            ErrorCode.TARGET_INFEASIBLE,
            f"P04 target {target:.3f} is not reachable with the frozen cutter position/direction: "
            f"{reason}; the largest feasible cutter (scale "
            f"{best_feasible['scale'] if best_feasible else 0.0:.4g}, radius "
            f"{best_feasible['radius_mm'] if best_feasible else 0.0:.4g} mm) only removes "
            f"{achieved:.4f} of the contact against the {min_ratio:.3f} representative-volume guard",
            stage="degrade.P04",
            measurements={"contact_loss_target": target, "achieved_contact_loss": achieved,
                          "target_abs_error": float(abs(achieved - target)),
                          "min_representative_ratio": min_ratio,
                          "best_feasible_volume_ratio": ratio,
                          "ratio_blocked_scale": (float(ceiling["scale"]) if ceiling else None),
                          "search_feasible_scale_max": float(best_scale),
                          "search_phase": "BISECT_CEILING", "search_trace": trace[-24:]})

    body = high["body"]
    if body is None:  # pragma: no cover - a feasible bracket always has a body
        raise _failure(ErrorCode.TARGET_INFEASIBLE, "P04 search produced no feasible body",
                       stage="degrade.P04", measurements={"search_trace": trace[-24:]})
    best = high
    contact = best["contact"]
    volumes = best["volumes"]
    parts = best["components"]
    achieved = float(contact["lost_fraction"]) if variant != "volume_loss" else float(best["loss"])
    target_error = float(abs(achieved - target))
    inside = _inside_mask(mesh, body, n=3000, seed=int(recipe.basis.get("seed", 0)) + 13)
    measurements = {
        "contact_loss_target": float(target),
        "achieved_contact_loss": achieved,
        "target_abs_error": target_error,
        "target_tolerance": tolerance,
        "contact_lost_area_mm2": float(contact["lost_area_mm2"]),
        "contact_residual_area_mm2": float(contact["residual_area_mm2"]),
        "contact_area_total_mm2": float(contact.get("interface_area_mm2", 0.0)),
        "cutter_scale": float(best["scale"]),
        "cutter_radius_mm": float(best["radius_mm"]),
        "cutter_center_mm_x": float(center[0]), "cutter_center_mm_y": float(center[1]),
        "cutter_center_mm_z": float(center[2]),
        "search_evaluations": float(len(trace)),
        "search_feasible_scale_max": float(best_scale),
        "search_bisect_started": 1.0 if bisect_started else 0.0,        "search_bracket_low_scale": float(below["scale"]) if below is not None else 0.0,
        "search_bracket_high_scale": float(ceiling["scale"]) if ceiling is not None else 0.0,
        "lost_volume_mm3": float(source_volume - sum(volumes)),
        "components": float(len(parts)),
        "largest_component_ratio": float(best["volume_ratio"]),
        "min_thickness_mm": float(S.ray_thickness(body, n_samples=200, seed=11)["min_mm"]),
        "measured_max_displacement_mm": float(inside["max_outside_mm"]),
        **_drift_from_inside(inside, samples=float(inside["samples"])),
    }
    units = {"achieved_contact_loss": "1", "contact_loss_target": "1",
             "contact_lost_area_mm2": "mm2", "cutter_radius_mm": "mm",
             "cutter_scale": "1", "lost_volume_mm3": "mm3", "min_thickness_mm": "mm",
             "measured_max_displacement_mm": "mm", **_drift_units()}
    details = {
        "narrowband": {"backend": "degrade.physical_narrowband.chip_material",
                       "method": "frozen cutter position/direction, 1-D geometric search on the "
                                 "cutter size (plan 30.7)",
                       "roi": roi, "variant": variant,
                       "cutter": {"center_mm": [float(v) for v in center],
                                  "direction": [float(v) for v in direction],
                                  "base_radii_mm": [float(v) for v in base_radii]},
                       "search": trace},
        "sdf_pipeline": {"spacing": {"spacing_mm": 0.0, "basis": "ANALYTIC_CUTTER"}},
    }
    realized = bool(measurements["lost_volume_mm3"] > 1e-9)
    return _assemble(body, mesh, recipe, measurements=measurements, units=units,
                     details=details, realized=realized, fragment=fragment)


# ======================================================================================
# measurement helpers
# ======================================================================================
def _removed_surface_points(body: trimesh.Trimesh, source: trimesh.Trimesh, *, n: int = 2500,
                            seed: int = 0) -> dict[str, float]:
    """Recession measured on the *source* surface: samples whose material is gone, plus how far
    the surviving surface moved away from them (independent of the operator's own fields)."""
    points, _ = trimesh.sample.sample_surface(source, int(n), seed=int(seed) % (2 ** 31))
    points = np.asarray(points, dtype=np.float64)
    inside = _occupancy(body, points)
    removed = points[~inside]
    if len(removed) == 0:
        return {"n": 0.0, "max_mm": 0.0, "mean_mm": 0.0, "p95_mm": 0.0}
    dist = S.scene_for(body).unsigned_distance(removed)
    finite = np.isfinite(dist)
    if not bool(np.any(finite)):
        return {"n": float(len(removed)), "max_mm": 0.0, "mean_mm": 0.0, "p95_mm": 0.0}
    dist = dist[finite]
    return {"n": float(len(removed)), "max_mm": float(dist.max()),
            "mean_mm": float(dist.mean()), "p95_mm": float(np.percentile(dist, 95))}


def _drift_from_inside(inside: dict[str, float], *, samples: int) -> dict[str, float]:
    """``roi_external_drift*`` block computed from the already-taken ``_inside_mask`` sample.

    P04 is an **analytic** cutter (a boolean with an ellipsoid), not a surface operator and not a
    level set, so there is no "non-ROI source sample" population to re-sample: the population that
    matters is the delivered surface itself, and its outward displacement is already measured by
    :func:`_inside_mask` (``max_outside_mm`` = max signed distance of the damaged surface outside
    the clean body).  Its quantiles are therefore reported under the same keys, from the same
    instrument, with ``population`` naming the difference.  ``max_mm`` is the shipped
    ``measured_max_displacement_mm`` value, bit for bit.
    """
    return {"roi_external_drift_mm": float(inside["max_outside_mm"]),
            "roi_external_drift_p50_mm": float(inside.get("p50_outside_mm", 0.0)),
            "roi_external_drift_p95_mm": float(inside.get("p95_outside_mm", 0.0)),
            "roi_external_drift_p99_mm": float(inside.get("p99_outside_mm", 0.0)),
            "roi_external_drift_samples": float(samples),
            "roi_external_drift_moved_samples": float(inside.get("outside_samples", 0.0))}


def _inside_mask(reference: trimesh.Trimesh, body: trimesh.Trimesh, *, n: int = 3000,
                 seed: int = 0) -> dict[str, float]:
    """``damaged ⊆ clean`` and the displacement of the damaged surface (plan 12.4).

    S12: the outward population (``signed > 1e-6``) also reports p50/p95/p99 so the drift family
    has one key set on every backend; ``max_outside_mm`` is unchanged.
    """
    points, _ = trimesh.sample.sample_surface(body, int(n), seed=int(seed) % (2 ** 31))
    points = np.asarray(points, dtype=np.float64)
    signed = S.scene_for(reference).signed_distance(points)
    outside = signed > 1e-6
    out = {"samples": float(len(points)), "outside_fraction": float(outside.mean()),
           "max_outside_fraction": float(outside.mean()),
           "max_outside_mm": float(signed.max()) if len(points) else 0.0,
           "outside_samples": float(int(outside.sum())),
           "p50_outside_mm": 0.0, "p95_outside_mm": 0.0, "p99_outside_mm": 0.0}
    values = signed[outside]
    values = values[np.isfinite(values)]
    if values.size:
        out["p50_outside_mm"] = float(np.percentile(values, 50))
        out["p95_outside_mm"] = float(np.percentile(values, 95))
        out["p99_outside_mm"] = float(np.percentile(values, 99))
    return out


def _outside_drift(body: trimesh.Trimesh, source: trimesh.Trimesh, roi_faces: np.ndarray,
                   *, n: int = 1500, seed: int = 7) -> float:
    """Maximum displacement of the source surface *away* from the ROI (must stay ~0)."""
    return float(_outside_drift_stats(body, source, roi_faces, n=n, seed=seed)["max_mm"])


#: S12: the quantiles reported beside the max, matching ``physical.operators.DRIFT_QUANTILES``.
DRIFT_QUANTILES: tuple[float, ...] = (50.0, 95.0, 99.0)


def _outside_drift_stats(body: trimesh.Trimesh, source: trimesh.Trimesh,
                         roi_faces: np.ndarray, *, n: int = 1500,
                         seed: int = 7) -> dict[str, float]:
    """The narrow-band drift population: max (shipped statistic) plus p50/p95/p99.

    The *instrument* is deliberately the narrow-band one: the ROI is the set of ROI **face
    centres** and "outside" is ``distance > p5(distance) + 1 mm`` (a compact support test on the
    surface operator's own ROI), whereas the global path uses the voxel halo.  The two paths
    therefore produce different populations and different maxima -- that difference is part of
    what the routing audit measures -- but the reported key set is identical, so a consumer reads
    the same keys from either backend.

    ``max_mm`` is bit-for-bit the value the shipped :func:`_outside_drift` returned (same seed,
    same ``n``, same test) and ``_drift_measurements`` re-checks that equality.
    """
    from scipy.spatial import cKDTree

    out: dict[str, float] = {"max_mm": 0.0, "samples": 0.0, "outside_samples": 0.0,
                             "moved_samples": 0.0}
    for q in DRIFT_QUANTILES:
        out[f"p{q:g}_mm"] = 0.0
    faces = np.asarray(source.faces, dtype=np.int64)
    roi = np.asarray(roi_faces, dtype=np.int64)
    mask = np.zeros(len(faces), dtype=bool)
    mask[roi] = True
    anchors = np.asarray(source.triangles_center, dtype=np.float64)[mask]
    if len(anchors) == 0:
        return out
    tree = cKDTree(anchors)
    points, _ = trimesh.sample.sample_surface(source, int(n), seed=int(seed) % (2 ** 31))
    points = np.asarray(points, dtype=np.float64)
    dist, _ = tree.query(points, workers=1)
    halo = float(np.percentile(dist, 5.0)) + 1.0
    outside = points[dist > halo]
    out["samples"] = float(len(points))
    out["outside_samples"] = float(len(outside))
    if len(outside) == 0:
        return out
    moved = outside[~_occupancy(body, outside)]
    out["moved_samples"] = float(len(moved))
    if len(moved) == 0:
        return out
    values = np.asarray(S.scene_for(body).unsigned_distance(moved), dtype=np.float64)
    values = values[np.isfinite(values)]
    if values.size == 0:
        return out
    out["max_mm"] = float(values.max())
    for q in DRIFT_QUANTILES:
        out[f"p{q:g}_mm"] = float(np.percentile(values, q))
    return out


def _drift_measurements(body: trimesh.Trimesh, source: trimesh.Trimesh,
                        roi_faces: np.ndarray, *, n: int = 1500,
                        seed: int = 7) -> dict[str, float]:
    """The ``roi_external_drift*`` block of the narrow-band backend (max + p50/p95/p99, S12)."""
    stats = _outside_drift_stats(body, source, roi_faces, n=n, seed=seed)
    out = {"roi_external_drift_mm": float(stats["max_mm"]),
           "roi_external_drift_p50_mm": float(stats["p50_mm"]),
           "roi_external_drift_p95_mm": float(stats["p95_mm"]),
           "roi_external_drift_p99_mm": float(stats["p99_mm"]),
           "roi_external_drift_samples": float(stats["samples"]),
           "roi_external_drift_moved_samples": float(stats["moved_samples"])}
    shipped = float(_outside_drift(body, source, roi_faces, n=n, seed=seed))
    if shipped != out["roi_external_drift_mm"]:  # pragma: no cover - guards the refactor
        raise SynLabError(
            ErrorCode.SCHEMA_INVALID,
            f"roi_external_drift max moved: {shipped!r} != {out['roi_external_drift_mm']!r}",
            stage="degrade.physical_narrowband.drift")
    return out


def _drift_units(key_prefix: str = "roi_external_drift") -> dict[str, str]:
    return {f"{key_prefix}_mm": "mm", f"{key_prefix}_p50_mm": "mm",
            f"{key_prefix}_p95_mm": "mm", f"{key_prefix}_p99_mm": "mm"}


def _occupancy(body: trimesh.Trimesh, points: np.ndarray) -> np.ndarray:
    """Occupancy of ``body`` at ``points``; external Open3D scenes are evicted defensively."""
    return S.scene_for(body).occupancy(np.asarray(points, dtype=np.float64))


def _sampled_vertex_surface_distance(source: trimesh.Trimesh, body: trimesh.Trimesh,
                                     depth: np.ndarray) -> dict[str, Any]:
    """Report sampled source-vertex to result-surface distances, not vertex displacement.

    ``unsigned_distance`` is nearest-surface distance and does not establish vertex
    correspondence or recession. Incomplete samples therefore remain UNKNOWN rather than
    exposing a partial maximum or a fabricated zero.
    """
    values = np.asarray(depth, dtype=np.float64).reshape(-1)
    vertices = np.asarray(source.vertices, dtype=np.float64)
    if values.shape[0] != len(vertices):
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"depth field has {values.shape[0]} entries for {len(vertices)} "
                          f"vertices", stage="degrade.physical_narrowband")
    moved = vertices[values > 0.0]
    requested = int(len(moved))
    row: dict[str, Any] = {
        "status": "NOT_APPLICABLE" if requested == 0 else "UNKNOWN",
        "interpretation": "unsigned nearest-result-surface distance; not vertex displacement or recession",
        "requested_samples": requested,
        "finite_samples": 0,
        "missing_samples": requested,
        "max_mm": None,
        "mean_mm": None,
    }
    if requested == 0:
        row["missing_samples"] = 0
        return row
    try:
        distance = np.asarray(S.scene_for(body).unsigned_distance(moved), dtype=np.float64)
    except Exception as exc:
        row["error"] = f"{type(exc).__name__}: {exc}"
        return row
    if distance.shape != (requested,):
        row["error"] = f"distance result shape {distance.shape} does not match {requested} samples"
        return row
    finite = np.isfinite(distance)
    finite_count = int(np.count_nonzero(finite))
    row["finite_samples"] = finite_count
    row["missing_samples"] = requested - finite_count
    if finite_count != requested:
        return row
    row["status"] = "COMPLETE_DIAGNOSTIC_ONLY"
    row["max_mm"] = float(distance.max())
    row["mean_mm"] = float(distance.mean())
    return row
