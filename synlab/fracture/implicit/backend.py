"""Backend entry points: build the implicit cutter, run the event, publish the record.

``build_implicit_cutter`` is a drop-in for
:func:`synlab.fracture.morphology.build_morphology_cutter`: it returns the same
``(CutterResult, field, params, report)`` tuple, so the frozen event path
(:func:`synlab.fracture.event.run_shared_cut`) consumes it unchanged -- which is what makes the
conjugacy constructive: both halves are cut by **one** mesh instance.

The stage timings and the peak memory of the build are recorded per stage (sampling,
triangulation, closure, verification) because the plan asks for a per-stage cost report.
"""

from __future__ import annotations

import time
import tracemalloc
from typing import Any, Mapping

import numpy as np

from ...errors import ErrorCode, SynLabError
from . import BACKEND_IMPLICIT, IMPLICIT_META_KEY, _gate, implicit_backend_enabled, implicit_options
from .field import (
    MAX_SHEET_TRIANGLES,
    SAMPLES_PER_WAVELENGTH,
    SLOPE_P95_TARGET_DEG,
    build_implicit_field,
)
from .sheet import (
    build_tensor_sheet,
    close_sheet,
    measure_realized_error,
    measure_sampling_density,
    topology_report,
)

__all__ = ["build_implicit_cutter", "run_implicit_event", "IMPLICIT_META_KEY"]

#: provenance of every default this backend applies (published in the report).
DEFAULTS_PROVENANCE = {
    "samples_per_wavelength": "ENGINEERING: >= 4-5 samples of the shortest retained wavelength "
                              "(task contract); 5.0 is the shipped default",
    "slope_p95_target_deg": "LITERATURE/ENGINEERING: a real ceramic fracture surface slopes a few "
                            "degrees up to ~20 deg away from the mean plane (A12 realism doc 9.4); "
                            "18 deg is the shipped target",
    "max_sheet_triangles": "ENGINEERING: memory/time guard for the boolean; the morphology "
                           "spectrum is band-limited (and the dropped bands are named) instead of "
                           "silently coarsening the mesh",
}


def _ladder(values: Mapping[str, Any], key: str, default: float) -> float:
    try:
        return float(values.get(key, default))
    except (TypeError, ValueError):
        return float(default)


def build_implicit_cutter(
    mother: Any,
    *,
    material_profile: Mapping[str, Any] | None = None,
    rng: np.random.Generator,
    basis: Any | None = None,
    prepared: Mapping[str, Any] | None = None,
    event_id: str = "",
    error_budget_mm: float = 0.01,
    max_triangles: int = 3_000_000,
    wall_probes: int = 320,
    origin_uv: Any = None,
    options: Mapping[str, Any] | None = None,
) -> tuple[Any, Any, Any, dict[str, Any]]:
    """Build the shared implicit-sheet cutter and its parameter/realization record.

    ``options`` (from ``spec.meta['implicit']``) may carry ``samples_per_wavelength``,
    ``slope_p95_target_deg``, ``max_sheet_triangles``, ``strategy`` (``"tensor"``) and
    ``coarse_max_mm``.  Every default used is published under ``report['defaults']``.
    """
    from ...schemas.runtime import CutterResult
    from .. import morphology as morphology_mod
    from ..booleans import mesh_hash

    opts = dict(options or {})
    samples_per_wavelength = max(4.0, _ladder(opts, "samples_per_wavelength",
                                              SAMPLES_PER_WAVELENGTH))
    slope_target = _ladder(opts, "slope_p95_target_deg", SLOPE_P95_TARGET_DEG)
    triangle_budget = int(_ladder(opts, "max_sheet_triangles", MAX_SHEET_TRIANGLES))
    strategy = str(opts.get("strategy", "tensor") or "tensor")
    if strategy != "tensor":
        raise SynLabError(
            ErrorCode.OPERATOR_NOT_REALIZED,
            f"implicit sheet strategy {strategy!r} is not implemented in this build; the "
            f"implemented one is 'tensor' (conforming tensor-product sheet).  The narrow-band "
            f"3-D SDF fallback is a separate entry point "
            f"(synlab.fracture.implicit.narrowband.build_narrowband_cutter)",
            stage="fracture.implicit.build",
        )
    budget = float(error_budget_mm)
    timings: dict[str, float] = {}
    tracemalloc.start()
    started = time.time()

    # ------------------------------------------------------------------ measure the body once
    if prepared is None:
        if material_profile is None:
            raise SynLabError(
                ErrorCode.SCHEMA_INVALID,
                "the implicit backend needs the real material profile in "
                "spec.meta['material_profile'] (it is what drives the amplitudes)",
                stage="fracture.implicit.build")
        prepared = morphology_mod.prepare_morphology(
            mother, material_profile=material_profile, rng=rng, basis=basis, event_id=event_id,
            error_budget_mm=budget, wall_probes=int(opts.get("wall_probes", wall_probes)),
            origin_uv=origin_uv)
    basis = prepared["basis"]
    mesh = mother.mesh
    tris_uv = prepared["tris_uv"]
    core_area = float(prepared["core_area_mm2"])
    base_params = prepared["base_params"]
    if event_id and not base_params.event_id:
        from dataclasses import replace

        base_params = replace(base_params, event_id=str(event_id))
    timings["prepare_seconds"] = time.time() - started

    # ------------------------------------------------------------------ sampling plan
    pts = np.asarray(tris_uv, dtype=np.float64).reshape(-1, 2)
    margin = float(opts.get("fine_margin_mm", 0.0) or 0.0)
    requested_lambda = min([float(b[1]) for b in base_params.bands if float(b[0]) > 0.0]
                           or [float("inf")])
    #: bbox of the material cross-section: the fine block of the tensor grid
    fine_u = (float(pts[:, 0].min()) - margin, float(pts[:, 0].max()) + margin)
    fine_v = (float(pts[:, 1].min()) - margin, float(pts[:, 1].max()) + margin)
    block_area = max((fine_u[1] - fine_u[0]) * (fine_v[1] - fine_v[0]), 1.0e-9)
    delta_from_budget = float(np.sqrt(2.0 * block_area / max(triangle_budget, 1)))
    delta = max(delta_from_budget, requested_lambda / samples_per_wavelength)
    delta = float(min(delta, max(requested_lambda, 1.0e-3)))
    timings["planning_seconds"] = time.time() - started

    # ------------------------------------------------------------------ field (sampling stage)
    stage = time.time()
    field, field_info = build_implicit_field(
        basis, mesh, base_params, rng=rng,
        cross_section=(tris_uv, core_area, prepared["cross_info"]),
        delta_mm=delta, samples_per_wavelength=samples_per_wavelength,
        slope_target_p95_deg=slope_target,
        envelope_width_mm=opts.get("envelope_width_mm"),
        raster_step_mm=opts.get("raster_step_mm"),
        slope_step_mm=opts.get("slope_step_mm"))
    timings["field_seconds"] = time.time() - stage
    envelope = field.envelope
    lambda_realized = float(field.meta["spectrum"]["shortest_mm"])
    if not np.isfinite(lambda_realized):
        lambda_realized = float(requested_lambda)

    # ------------------------------------------------------------------ sheet + closure
    stage = time.time()
    coarse_max = float(opts.get("coarse_max_mm", 0.0) or 0.0)
    if coarse_max <= 0.0:
        coarse_max = max(4.0 * delta,
                         float(np.hypot(basis.u_range[1] - basis.u_range[0],
                                        basis.v_range[1] - basis.v_range[0])) / 24.0)
    h_fn = lambda u, v: np.asarray(field(u, v), dtype=np.float64)  # noqa: E731
    sheet = build_tensor_sheet(
        basis, h_fn, delta_mm=delta,
        fine_u=(fine_u[0] - 4.0 * delta, fine_u[1] + 4.0 * delta),
        fine_v=(fine_v[0] - 4.0 * delta, fine_v[1] + 4.0 * delta),
        coarse_max_mm=coarse_max)
    timings["sheet_seconds"] = time.time() - stage

    world = _sheet_to_world(basis, sheet)
    w_min = float(basis.meta.get("w_min_mm", -1.0))
    depth_margin = float(basis.meta.get("depth_margin_mm", 2.0))
    bottom_w = float(w_min - depth_margin)
    stage = time.time()
    vertices, faces, closure = close_sheet(world, sheet.faces, bottom_w=bottom_w)
    timings["closure_seconds"] = time.time() - stage

    import trimesh

    cutter_mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    stage = time.time()
    topology = topology_report(cutter_mesh)
    if topology["bad_edges"] != 0 or not topology["is_watertight"]:
        raise SynLabError(
            ErrorCode.CUTTER_NOT_CLOSED,
            f"the implicit sheet cutter is not watertight: {topology['bad_edges']} edges with a "
            f"face count != 2 (edge_use_histogram {topology['edge_use_histogram']}); a T-junction "
            f"cannot exist on a tensor grid, so this is an assembler defect and is reported as one",
            stage="fracture.implicit.verify",
            measurements={"bad_edges": topology["bad_edges"],
                          "edge_use_histogram": topology["edge_use_histogram"]},
        )
    inside_fn = lambda u, v: envelope.smoothness(u, v) > 0.5  # noqa: E731
    error = measure_realized_error(h_fn, sheet, budget_mm=budget, lambda_min_mm=lambda_realized,
                                  inside_fn=inside_fn)
    sampling = measure_sampling_density(sheet, lambda_min_mm=lambda_realized, core_fn=inside_fn)
    timings["verify_seconds"] = time.time() - stage
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    timings["total_seconds"] = time.time() - started

    if not error["within_budget"]:
        raise SynLabError(
            ErrorCode.PRECISION_NOT_REALIZED,
            f"the implicit sheet realizes {error['realized_error_mm']:.6f} mm interpolation error, "
            f"above the {budget:.6f} mm budget (measured on the emitted triangles with "
            f"{error['probes_per_triangle']} probes each); the budget is not relaxed",
            stage="fracture.implicit.verify",
            measurements={"realized_error_mm": error["realized_error_mm"], "budget_mm": budget,
                          "worst_uv_mm": error["worst_uv_mm"], "delta_mm": float(delta)},
        )
    if not sampling["meets_4_per_lambda"]:
        raise SynLabError(
            ErrorCode.PRECISION_NOT_REALIZED,
            f"the sheet samples the shortest retained wavelength only "
            f"{sampling['samples_per_lambda_p95_worst']:.2f} times (>= 4 required, >= 5 with the "
            f"shipped default); the mesh is not coarsened to hide it",
            stage="fracture.implicit.verify",
            measurements=sampling,
        )

    report: dict[str, Any] = {
        "backend": BACKEND_IMPLICIT, "strategy": strategy,
        "defaults": dict(DEFAULTS_PROVENANCE),
        "options": {"samples_per_wavelength": samples_per_wavelength,
                    "slope_p95_target_deg": slope_target,
                    "max_sheet_triangles": triangle_budget,
                    "coarse_max_mm": coarse_max},
        "sampling_plan": {
            "requested_lambda_min_mm": float(requested_lambda),
            "delta_from_triangle_budget_mm": delta_from_budget,
            "delta_mm": float(delta), "triangle_budget": triangle_budget,
            "fine_block_u_mm": [float(x) for x in fine_u],
            "fine_block_v_mm": [float(x) for x in fine_v],
            "fine_block_area_mm2": float(block_area),
            "core_area_mm2": core_area,
        },
        "field": field_info,
        "sheet": {
            "axis_u": sheet.axis_u, "axis_v": sheet.axis_v,
            "cells": int((sheet.n_u - 1) * (sheet.n_v - 1)),
            "top_triangles": int(sheet.faces.shape[0]),
            "seconds_evaluate": float(sheet.seconds_evaluate),
            "seconds_triangulate": float(sheet.seconds_triangulate),
        },
        "closure": closure, "topology": topology,
        "realized_error": error, "sampling_density": sampling,
        "timings_seconds": timings, "peak_memory_mb": float(peak / 1024.0 / 1024.0),
        "cutter_hash": mesh_hash(cutter_mesh),
        "watertight": bool(topology["is_watertight"]),
        "bad_edges": int(topology["bad_edges"]),
        "winding_consistent": bool(topology["is_winding_consistent"]),
        "requested_error_mm": budget,
        "realized_error_mm": float(error["realized_error_mm"]),
    }
    cutter = CutterResult(
        mesh=cutter_mesh, basis=basis, h_fn=h_fn,
        requested_error_mm=budget, realized_error_mm=float(error["realized_error_mm"]),
        triangles=int(faces.shape[0]),
        meta={k: v for k, v in report.items() if k != "field"},
    )
    cutter.meta["height_field"] = field.as_dict()
    cutter.meta[IMPLICIT_META_KEY] = _jsonable(report)
    return cutter, field, field.morphology, report


def _sheet_to_world(basis: Any, sheet: Any) -> np.ndarray:
    """``(u, v, h)`` lattice -> world mm using the cut basis (same frame as the plane cutter)."""
    matrix = np.stack([basis.e_u, basis.e_v, basis.normal], axis=0)
    local = np.column_stack([sheet.uv, sheet.heights])
    return local @ matrix + np.asarray(basis.origin, dtype=np.float64)[None, :]


def run_implicit_event(mother: Any, spec: Any, rng: np.random.Generator, *,
                       event_id: str) -> Any:
    """One implicit-sheet event through the frozen shared-cutter path (gated, off by default)."""
    from .. import event as event_mod
    from .. import morphology as morphology_mod

    _gate(spec, stage="fracture.implicit.run_implicit_event")
    profile, options = implicit_options(spec)
    if profile is None:
        meta = getattr(spec, "meta", None)
        profile = dict(meta).get("material_profile") if isinstance(meta, Mapping) else None
    if profile is None:
        raise SynLabError(
            ErrorCode.SCHEMA_INVALID,
            "the implicit backend needs the real material profile in "
            "spec.meta['material_profile']",
            stage="fracture.implicit.run_implicit_event")
    budget = float(getattr(spec, "error_budget_mm", 0.01))
    cutter, field, params, report = build_implicit_cutter(
        mother, material_profile=profile, rng=rng,
        basis=None, event_id=str(event_id), error_budget_mm=budget,
        max_triangles=int(getattr(spec, "max_cutter_triangles", 3_000_000)),
        options=options)
    result = event_mod.run_shared_cut(
        mother, cutter, event_id=event_id, backend=BACKEND_IMPLICIT,
        extra_meta={
            IMPLICIT_META_KEY: _jsonable(report),
            morphology_mod.MORPHOLOGY_META_KEY: params.as_dict(),
        })
    record = _jsonable(report)
    for patch in result.interfaces:
        patch.meta[IMPLICIT_META_KEY] = record
    for fragment in result.fragments:
        fragment.meta[IMPLICIT_META_KEY] = record
    return result


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


_ = implicit_backend_enabled  # re-exported for callers that gate on the switch
