"""Backend entry points: build the implicit cutter, run the event, publish the record.

``build_implicit_cutter`` is a drop-in for
:func:`synlab.fracture.morphology.build_morphology_cutter`: it returns the same
``(CutterResult, field, params, report)`` tuple, so the frozen event path
(:func:`synlab.fracture.event.run_shared_cut`) consumes it unchanged -- which is what makes the
conjugacy constructive: both halves are cut by **one** mesh instance.

Two measured fixed points drive the build (both are reported with the numbers that decided them):

* **spacing**: the interpolation budget needs ``C * delta^2 / 8 <= budget`` (``C`` measured on the
  realized surface), the sampling contract needs ``delta <= lambda_min / 4..5``, and the triangle
  budget needs ``delta >= sqrt(2 * block_area / max_triangles)``.  The sheet is refined until the
  *measured* error is inside the budget, and if the triangle budget blocks that, the footprint mask
  is widened (its curvature falls as ``1 / width^2``) -- never the other way round, and never by
  relaxing a threshold;
* **slope**: the relief amplitudes are scaled until the measured P95 slope of the realized surface
  enters the declared band (see :func:`synlab.fracture.implicit.field.calibrate_slope`).

Stage timings and the build's peak memory are recorded per stage.
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
    "max_sheet_triangles": "ENGINEERING: memory/time guard for the boolean; when it binds, the "
                           "footprint mask is widened (the relief near the rim is damped, which is "
                           "measured and published) instead of sampling the field below the "
                           "contract",
    "envelope_width_mm": "ENGINEERING: width of the footprint mask transition; widened "
                         "automatically while the measured curvature does not fit the spacing the "
                         "triangle budget allows",
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
    ``slope_p95_target_deg``, ``max_sheet_triangles``, ``envelope_width_mm``, ``strategy``
    (``"tensor"``) and ``coarse_max_mm``.  Every default used is published under
    ``report['defaults']``.
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
    #: every (re)build of the field uses its own deterministic stream derived from ONE draw of the
    #: caller's rng: a refinement loop that redraws the random phases compares different surfaces
    #: and can never converge (measured: 0.0103 / 0.0198 / 0.0640 mm error on the same geometry).
    base_seed = int(rng.integers(0, 2 ** 31 - 1))
    if float(max_triangles) < 2 * triangle_budget:
        raise SynLabError(
            ErrorCode.SCHEMA_INVALID,
            f"the sheet triangle budget ({triangle_budget}) does not fit the cutter budget "
            f"({max_triangles}); the cutter budget is never exceeded silently",
            stage="fracture.implicit.build")
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
    fine_u = (float(pts[:, 0].min()) - margin, float(pts[:, 0].max()) + margin)
    fine_v = (float(pts[:, 1].min()) - margin, float(pts[:, 1].max()) + margin)
    block_area = max((fine_u[1] - fine_u[0]) * (fine_v[1] - fine_v[0]), 1.0e-9)
    delta_sampling = float(requested_lambda) / samples_per_wavelength
    delta_budget = float(np.sqrt(2.0 * block_area / max(triangle_budget, 1)))
    if delta_budget > delta_sampling:
        # the triangle budget cannot even sample the requested spectrum: band-limit explicitly
        delta_sampling = delta_budget
    envelope_width = float(opts.get("envelope_width_mm", 0.0) or 0.0)
    if envelope_width <= 0.0:
        envelope_width = max(8.0 * delta_sampling, 1.0)

    # ------------------------------------------------------------------ field
    stage = time.time()
    field, field_info = build_implicit_field(
        basis, mesh, base_params, rng=np.random.default_rng(base_seed + 1),
        cross_section=(tris_uv, core_area, prepared["cross_info"]),
        delta_mm=delta_sampling, samples_per_wavelength=samples_per_wavelength,
        slope_target_p95_deg=slope_target, envelope_width_mm=envelope_width,
        raster_step_mm=opts.get("raster_step_mm"), slope_step_mm=opts.get("slope_step_mm"))
    timings["field_seconds"] = time.time() - stage
    envelope = field.envelope
    lambda_realized = float(field.meta["spectrum"]["shortest_mm"])
    if not np.isfinite(lambda_realized):
        lambda_realized = float(requested_lambda)
    h_fn = lambda u, v: np.asarray(field(u, v), dtype=np.float64)  # noqa: E731
    inside_fn = lambda u, v: envelope.smoothness(u, v) > 0.5  # noqa: E731
    coarse_max = float(opts.get("coarse_max_mm", 0.0) or 0.0)
    if coarse_max <= 0.0:
        coarse_max = max(4.0 * delta_sampling,
                         float(np.hypot(basis.u_range[1] - basis.u_range[0],
                                        basis.v_range[1] - basis.v_range[0])) / 24.0)
    w_min = float(basis.meta.get("w_min_mm", -1.0))
    depth_margin = float(basis.meta.get("depth_margin_mm", 2.0))
    bottom_w = float(w_min - depth_margin)

    # ------------------------------------------------------------------ sheet + closure loop
    #
    # The predictor ``error <= C * delta^2 / 8`` is only a bound; the loop below refines the sheet
    # on the *measured* error until it is inside the budget, and widens the footprint mask (then
    # rebuilds the field) when the triangle budget blocks the refinement.
    attempts: list[dict[str, Any]] = []
    #: the sheet may be refined below the sampling spacing to meet the interpolation budget, but
    #: never below half of it: past that point the mask is widened instead, because a runaway
    #: refinement is a memory/time hazard (the host kills heavy runs) and the mask is the cheaper
    #: lever -- the trade-off is published either way.
    delta_floor = float(max(delta_budget, 0.5 * delta_sampling))
    delta = float(min(delta_sampling, max(delta_floor, delta_sampling)))
    sheet = None
    error: dict[str, Any] = {}
    closure: dict[str, Any] = {}
    vertices = faces = None
    outer_attempts = int(opts.get("outer_attempts", 3))
    for outer in range(1, outer_attempts + 1):
        for inner in range(1, 5):
            stage = time.time()
            sheet = build_tensor_sheet(
                basis, h_fn, delta_mm=delta,
                fine_u=(fine_u[0] - (envelope_width + 4.0 * delta),
                        fine_u[1] + (envelope_width + 4.0 * delta)),
                fine_v=(fine_v[0] - (envelope_width + 4.0 * delta),
                        fine_v[1] + (envelope_width + 4.0 * delta)),
                coarse_max_mm=coarse_max)
            timings["sheet_seconds"] = timings.get("sheet_seconds", 0.0) + (time.time() - stage)
            stage = time.time()
            error = measure_realized_error(h_fn, sheet, budget_mm=budget,
                                           lambda_min_mm=lambda_realized, inside_fn=inside_fn)
            timings["verify_seconds"] = timings.get("verify_seconds", 0.0) + (time.time() - stage)
            attempts.append({"outer": outer, "inner": inner, "delta_mm": float(delta),
                             "realized_error_mm": float(error["realized_error_mm"]),
                             "triangles": int(sheet.faces.shape[0])})
            if error["within_budget"] or delta <= delta_floor * (1.0 + 1e-12):
                break
            shrink = float(np.sqrt(0.85 * budget / max(error["realized_error_mm"], 1e-12)))
            delta = float(max(delta_floor, delta * min(0.9, max(0.5, shrink))))
        if error["within_budget"]:
            break
        if outer >= outer_attempts:
            break
        # the triangle budget blocks the refinement: widen the mask and rebuild the field
        envelope_width = float(min(4.0 * envelope_width, envelope_width * 1.5))
        stage = time.time()
        field, field_info = build_implicit_field(
            basis, mesh, base_params, rng=np.random.default_rng(base_seed + 1 + outer),
            cross_section=(tris_uv, core_area, prepared["cross_info"]),
            delta_mm=delta_sampling, samples_per_wavelength=samples_per_wavelength,
            slope_target_p95_deg=slope_target, envelope_width_mm=envelope_width,
            raster_step_mm=opts.get("raster_step_mm"), slope_step_mm=opts.get("slope_step_mm"))
        timings["field_seconds"] = timings.get("field_seconds", 0.0) + (time.time() - stage)
        envelope = field.envelope
        h_fn = lambda u, v: np.asarray(field(u, v), dtype=np.float64)  # noqa: E731
        inside_fn = lambda u, v: envelope.smoothness(u, v) > 0.5  # noqa: E731
        delta = float(delta_floor)

    if sheet is None or not error.get("within_budget", False):
        raise SynLabError(
            ErrorCode.PRECISION_NOT_REALIZED,
            f"the implicit sheet realizes {error.get('realized_error_mm', float('nan')):.6f} mm "
            f"interpolation error, above the {budget:.6f} mm budget, after refining to the "
            f"triangle-budget spacing {delta:.6f} mm and widening the footprint mask to "
            f"{envelope_width:.4f} mm; the budget is not relaxed and the spacing is not raised "
            f"above the sampling contract",
            stage="fracture.implicit.verify",
            measurements={"realized_error_mm": error.get("realized_error_mm"),
                          "budget_mm": budget, "delta_mm": float(delta),
                          "delta_budget_mm": delta_budget, "attempts": attempts},
        )
    # The closure happens in the *cut basis* frame: the flat bottom is ``w = bottom_w`` there, not
    # a horizontal plane in world coordinates.  Extruding along world z instead (the first revision)
    # cut a near-vertical plane's mother with a horizontal slab, which produced a third fragment and
    # a 0.14 mm conjugate gap -- measured, then fixed here.
    local_top = np.column_stack([sheet.uv, sheet.heights])
    stage = time.time()
    local_vertices, faces, closure = close_sheet(local_top, sheet.faces, bottom_w=bottom_w)
    vertices = _local_to_world(basis, local_vertices)
    timings["closure_seconds"] = timings.get("closure_seconds", 0.0) + (time.time() - stage)

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
    sampling = measure_sampling_density(sheet, lambda_min_mm=lambda_realized, core_fn=inside_fn)
    timings["verify_seconds"] = timings.get("verify_seconds", 0.0) + (time.time() - stage)
    if not sampling["meets_4_per_lambda"]:
        raise SynLabError(
            ErrorCode.PRECISION_NOT_REALIZED,
            f"the sheet samples the shortest retained wavelength only "
            f"{sampling['samples_per_lambda_p95_worst']:.2f} times (>= 4 required, >= 5 with the "
            f"shipped default); the mesh is not coarsened to hide it",
            stage="fracture.implicit.verify", measurements=sampling)
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    timings["total_seconds"] = time.time() - started

    report: dict[str, Any] = {
        "backend": BACKEND_IMPLICIT, "strategy": strategy,
        "defaults": dict(DEFAULTS_PROVENANCE),
        "options": {"samples_per_wavelength": samples_per_wavelength,
                    "slope_p95_target_deg": slope_target,
                    "max_sheet_triangles": triangle_budget,
                    "coarse_max_mm": coarse_max,
                    "envelope_width_mm": float(envelope_width)},
        "sampling_plan": {
            "requested_lambda_min_mm": float(requested_lambda),
            "lambda_min_realized_mm": float(lambda_realized),
            "delta_sampling_mm": float(delta_sampling),
            "delta_triangle_budget_mm": float(delta_budget),
            "delta_final_mm": float(delta),
            "triangle_budget": int(triangle_budget),
            "fine_block_u_mm": [float(x) for x in fine_u],
            "fine_block_v_mm": [float(x) for x in fine_v],
            "fine_block_area_mm2": float(block_area), "core_area_mm2": core_area,
            "refinement_attempts": attempts,
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


def _local_to_world(basis: Any, local: np.ndarray) -> np.ndarray:
    """``(u, v, w)`` in the cut basis -> world mm (the frame the plane cutter also works in)."""
    matrix = np.stack([basis.e_u, basis.e_v, basis.normal], axis=0)
    return (np.asarray(local, dtype=np.float64) @ matrix
            + np.asarray(basis.origin, dtype=np.float64)[None, :])


def run_implicit_event(mother: Any, spec: Any, rng: np.random.Generator, *,
                       event_id: str) -> Any:
    """One implicit-sheet event through the frozen shared-cutter path (gated, off by default)."""
    from .. import morphology as morphology_mod
    from .assembler import assemble_implicit_event

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
    result = assemble_implicit_event(
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
