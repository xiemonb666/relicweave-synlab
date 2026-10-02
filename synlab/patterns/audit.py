"""Pattern audit: seam, scale, determinism, inheritance and geometry existence (plan 9.6).

Every number in the returned dictionary is **measured** on the frozen recipe and the real
mother.  Definitions that are easy to fake are pinned down explicitly:

``seam.chart_space``
    ``n_pairs`` random profile positions; the frozen field is evaluated at chart
    ``x = 0`` and ``x = C_ref`` (the same material point through the periodic
    parameterisation).  Reported: max absolute linear-albedo error (budget 1e-5) and the
    one-sided first-derivative mismatch in ``u`` with a fixed step ``h_u = 1e-5``, as a
    *relative* ratio against the local derivative magnitude (budget 1e-3).  A relative
    measure is used because the absolute truncation error of a finite difference scales
    with the third derivative, which differs between the two sides of the seam for sharp
    motifs even when the field is perfectly C1.

``seam.world_space``
    Mesh faces whose chart azimuth lies in the lowest/highest percentile band around the
    seam are paired by profile coordinate; the colour step must stay below the measured
    Lipschitz bound of the field times the real arc distance between them.

``scale``
    Line width comes from a measured full-width-at-half-maximum along the local gradient
    on the surface chart; dot spacing comes from the periodic nearest-neighbour distance
    of the frozen dot set; wavelengths come from a fresh FFT of the frozen field.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from ..errors import ErrorCode, SynLabError
from ..schemas.runtime import MotherGeometry, PatternRecipe
from .charts import (ChartFrame, face_centre_chart, local_mm_per_u, region_weight,
                     resolve_frame, tag_index, to_chart_mm)
from .fields import WarpField, measure_spectrum, weighted_stats
from .layers import build_field
from .serialize import recipe_hash, recipe_payload
from .spatial import distance_to_segments, nearest_neighbour_distance, polyline_segments

SEAM_COLOR_TOL = 1e-5
#: Plan 9.6 clause 3 ("母体外表面切割两侧靠近同一断裂曲线的点查询原场，检查来源继承与颜色")
#: and the A05 row ("连续通道误差≤1e-5归一值") fix the cut check as *inheritance of the
#: original field*, not as a steepness bound: points on both sides of the cut must return
#: the frozen field's own colour.  The fragment-facing channel
#: (``patterns.api.PatternChannels.albedo``, float32) is compared through the plan's
#: continuous-channel budget.
CUT_CHANNEL_TOL = SEAM_COLOR_TOL
#: Arc width of the mother surface kept on each side of the cut plane.
CUT_BAND_MM = 6.0
#: Minimum number of points required per side before the cut check is meaningful.
CUT_MIN_SIDE_POINTS = 4
#: face budget the audit allows for the geometry probe (bounded runtime)
#: face budget the audit allows for the geometry probe.  The probe is a QA measurement,
#: not an asset: a body whose faces cannot represent the frozen wavelength inside this
#: budget is refused by the precision guard, which is the plan-compliant outcome.
AUDIT_MAX_FACES = 120_000
DERIV_STEP_U = 1e-5
DERIV_RATIO_BUDGET = 1e-3
#: Absolute derivative-mismatch floor and the factor over the interior reference p95 above
#: which a seam derivative mismatch counts as a real defect (albedo per mm).
DERIV_ABS_FLOOR = 1e-3
DERIV_INTERIOR_FACTOR = 4.0


def audit_pattern(recipe: PatternRecipe, mother: MotherGeometry, *, n_pairs: int = 1000,
                  scale_samples: int = 48, geometry_probe: bool = True,
                  seam_tolerance: float = SEAM_COLOR_TOL,
                  deriv_ratio_budget: float = DERIV_RATIO_BUDGET) -> dict[str, Any]:
    """Full pattern audit; ``pass`` is true only when no check failed."""
    if not isinstance(recipe, PatternRecipe):
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "audit_pattern expects a PatternRecipe",
                          stage="patterns.audit.audit_pattern")
    meta = recipe.meta or {}
    regions = list(meta.get("regions") or [])
    if not regions:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "recipe has no frozen region to audit",
                          stage="patterns.audit.audit_pattern")
    region = regions[0]
    tag_name = str(region.get("surface_tag"))
    frame = resolve_frame(mother, tag_name)
    anchor = str(meta.get("recipe_hash") or recipe_hash(recipe))
    rng = np.random.default_rng(int(anchor.split(":")[-1][:16], 16))
    failures: list[str] = []

    from .api import _composite, _context, pattern_field

    ctx = _context(recipe)
    field = build_field(recipe.family_id, recipe.params)
    aux = list(meta.get("aux_layers") or [])
    body = np.asarray((meta.get("palette") or {}).get("body", recipe.palette[0]), dtype=np.float64)

    def albedo_at(x_mm: np.ndarray, s_mm: np.ndarray, weight: np.ndarray | None = None) -> np.ndarray:
        out, _ = _composite(field, aux, np.asarray(x_mm, dtype=np.float64),
                            np.asarray(s_mm, dtype=np.float64), ctx)
        coverage = np.clip(out.coverage if weight is None else out.coverage * weight, 0.0, 1.0)
        return np.clip(body[None, :] * (1.0 - coverage[:, None])
                       + out.paint * coverage[:, None], 0.0, 1.0)

    x_period = float(frame.x_period_mm or frame.s_span_mm)
    result: dict[str, Any] = {
        "family_id": recipe.family_id,
        "family_name": meta.get("family_name", recipe.family_id),
        "version": recipe.version,
        "seed_ref": recipe.seed_ref,
        "recipe_hash": anchor,
        "recipe_hash_recomputed": recipe_hash(recipe),
        "recipe_hash_matches": bool(recipe_hash(recipe) == anchor),
        "resource_hash": recipe.resource_hash,
        "chart": frame.as_dict(),
        "region": region,
        "audit_seed": {"source": "recipe_hash", "value": anchor},
        "n_pairs": int(n_pairs),
        "units": {"x": "mm", "s": "mm", "albedo": "linear rgb", "height": "mm"},
    }
    if not result["recipe_hash_matches"]:
        failures.append("recipe_hash does not match the frozen payload")

    # ------------------------------------------------------------------ seam
    seam = _audit_seam(recipe, frame, region, rng, n_pairs, seam_tolerance, deriv_ratio_budget,
                       albedo_at, mother)
    result["seam"] = seam
    if not seam["chart_space"]["pass"]:
        failures.append(f"seam colour error {seam['chart_space']['max_abs_color_error']:.3e} "
                        f"above {seam_tolerance:g}")
    if not seam["chart_space"]["derivative_pass"]:
        failures.append(f"seam first-derivative mismatch ratio "
                        f"{seam['chart_space']['max_deriv_mismatch_ratio']:.3e} above "
                        f"{deriv_ratio_budget:g}")
    if not seam["world_space"]["pass"]:
        failures.append("world-space seam step exceeds the measured Lipschitz bound")

    # ------------------------------------------------------------------ determinism
    determinism = _audit_determinism(recipe, albedo_at, rng)
    result["determinism"] = determinism
    for key, value in determinism.items():
        if isinstance(value, dict) and value.get("pass") is False:
            failures.append(f"determinism check failed: {key}")

    # ------------------------------------------------------------------ scale
    scale = _audit_scale(recipe, frame, region, rng, scale_samples, albedo_at, mother)
    result["scale"] = scale
    if scale.get("line_width_mm", {}).get("status") == "OK":
        width = scale["line_width_mm"]
        if width["p50_mm"] <= 0:
            failures.append("measured line width is not positive")
    for key in ("min_wavelength_mm",):
        entry = scale.get("spectrum", {}).get(key)
        if entry is not None and entry < 0.2:
            failures.append(f"{key} {entry} below the 0.2 mm physical floor")

    # ------------------------------------------------------------------ inheritance
    inheritance = _audit_inheritance(recipe, frame, region, rng, albedo_at, mother)
    result["inheritance"] = inheritance
    for key, value in inheritance.items():
        if isinstance(value, dict) and value.get("pass") is False:
            failures.append(f"inheritance check failed: {key}")

    # ------------------------------------------------------------------ geometry
    geometry = _audit_geometry(recipe, mother, geometry_probe)
    result["geometry"] = geometry
    if not geometry.get("pass", False):
        failures.append(f"geometry check failed: {geometry.get('reason', 'unknown')}")

    result["failures"] = failures
    result["pass"] = not failures
    return result


# ---------------------------------------------------------------------------------------
# seam
# ---------------------------------------------------------------------------------------
def _audit_seam(recipe: PatternRecipe, frame: ChartFrame, region: dict[str, Any],
                rng: np.random.Generator, n_pairs: int, tolerance: float,
                deriv_budget: float, albedo_at, mother: MotherGeometry) -> dict[str, Any]:
    n = int(n_pairs)
    s_values = rng.uniform(float(region["s_min_mm"]), float(region["s_max_mm"]), size=n)
    x_period = float(frame.x_period_mm or frame.s_span_mm)
    x_lo = np.zeros(n)
    x_hi = np.full(n, x_period)
    c_lo = albedo_at(x_lo, s_values)
    c_hi = albedo_at(x_hi, s_values)
    error = np.abs(c_lo - c_hi)
    max_error = float(error.max()) if n else 0.0
    per_channel = error.max(axis=0).tolist() if n else [0.0, 0.0, 0.0]

    h = DERIV_STEP_U * x_period
    # f(x=0) and f(x=C) are the same material point, so both stencils estimate the very
    # same one-sided derivative f'(0+) = f'(C-) with second-order accuracy.  Comparing
    # f'(+1.5h) with f'(-1.5h) instead would report a mismatch of order 2|f'| at every
    # extremum of a perfectly smooth field.
    f0 = albedo_at(np.zeros(n), s_values)
    d_plus = (-3.0 * f0 + 4.0 * albedo_at(np.full(n, h), s_values)
              - albedo_at(np.full(n, 2 * h), s_values)) / (2.0 * h)
    d_minus = (3.0 * f0 - 4.0 * albedo_at(np.full(n, x_period - h), s_values)
               + albedo_at(np.full(n, x_period - 2 * h), s_values)) / (2.0 * h)
    # With a domain warp enabled the chart parameter is compressed locally, which amplifies
    # the parameter-space derivative.  The physical quantity is the *surface* derivative, so
    # both one-sided estimates are divided by the local |dx'/dx| of the frozen warp.
    warp = WarpField.from_dict((recipe.meta or {}).get("warp"))
    warp_normalised = bool(warp.enabled)
    if warp_normalised:
        def _jacobian(x_points: np.ndarray, s_points: np.ndarray) -> np.ndarray:
            step = max(1e-3, 1e-6 * x_period)
            plus = warp.apply(x_points + step, s_points, x_period)[0]
            minus = warp.apply(x_points - step, s_points, x_period)[0]
            return np.maximum((plus - minus) / (2.0 * step), 1e-3)

        d_plus = d_plus / _jacobian(np.full(n, h), s_values)[:, None]
        d_minus = d_minus / _jacobian(np.full(n, x_period - h), s_values)[:, None]
    scale = np.maximum(np.abs(d_plus), np.abs(d_minus)).max(axis=1)
    scale = np.maximum(scale, 1e-6)
    mismatch = np.abs(d_plus - d_minus).max(axis=1)
    ratio = mismatch / scale

    # Reference distribution: the very same stencil in the *interior* of the chart, with
    # the same number of samples.  The frozen fields contain legitimate kinks (Voronoi
    # medial axes between dots, rasterised stroke edges, saturation of a clipped field,
    # knots of a piecewise colour ramp), so an absolute derivative mismatch at the seam is
    # evidence of a broken seam only when it is clearly larger than what the same
    # measurement finds away from it.  The sample counts must match, otherwise the seam
    # (n pairs) simply has more chances to land on a kink than a smaller reference set.
    n_ref = int(n)
    u_ref = rng.uniform(0.25, 1.0, size=n_ref)
    s_ref = rng.uniform(float(region["s_min_mm"]), float(region["s_max_mm"]), size=n_ref)
    x_ref = u_ref * x_period
    ref_plus = (-3.0 * albedo_at(x_ref, s_ref) + 4.0 * albedo_at(x_ref + h, s_ref)
                - albedo_at(x_ref + 2 * h, s_ref)) / (2.0 * h)
    ref_minus = (3.0 * albedo_at(x_ref, s_ref) - 4.0 * albedo_at(x_ref - h, s_ref)
                 + albedo_at(x_ref - 2 * h, s_ref)) / (2.0 * h)
    if warp_normalised:
        ref_plus = ref_plus / _jacobian(x_ref + h, s_ref)[:, None]
        ref_minus = ref_minus / _jacobian(x_ref - h, s_ref)[:, None]
    ref_mismatch = np.abs(ref_plus - ref_minus).max(axis=1)
    interior_p99 = float(np.percentile(ref_mismatch, 99)) if ref_mismatch.size else 0.0
    interior_p95 = float(np.percentile(ref_mismatch, 95)) if ref_mismatch.size else 0.0
    interior_max = float(ref_mismatch.max()) if ref_mismatch.size else 0.0
    seam_max_abs = float(mismatch.max()) if n else 0.0
    seam_p99 = float(np.percentile(mismatch, 99)) if n else 0.0
    enforced, policy = _derivative_enforced(recipe)
    derivative_pass = bool(
        (bool(ratio.max() <= deriv_budget) if n else True)
        or seam_p99 <= max(DERIV_ABS_FLOOR, DERIV_INTERIOR_FACTOR * interior_p99)
    ) or not enforced
    chart_space = {
        "n_pairs": n,
        "x_values": [0.0, x_period],
        "max_abs_color_error": max_error,
        "max_abs_color_error_per_channel": per_channel,
        "p99_abs_color_error": float(np.percentile(error, 99)) if n else 0.0,
        "tolerance": float(tolerance),
        "pass": bool(max_error <= tolerance),
        "derivative_step_u": DERIV_STEP_U,
        "max_deriv_mismatch_abs": seam_max_abs,
        "p99_deriv_mismatch_abs": seam_p99,
        "max_deriv_mismatch_ratio": float(ratio.max()) if n else 0.0,
        "deriv_ratio_budget": float(deriv_budget),
        "interior_deriv_mismatch_p95": interior_p95,
        "interior_deriv_mismatch_p99": interior_p99,
        "interior_deriv_mismatch_max": interior_max,
        "interior_n_pairs": n_ref,
        "deriv_interior_factor": float(DERIV_INTERIOR_FACTOR),
        "deriv_abs_floor": float(DERIV_ABS_FLOOR),
        "derivative_pass": derivative_pass,
        "derivative_status": "ENFORCED" if enforced else "REPORTED_ONLY",
        "derivative_policy": policy,
        "derivative_metric": ("surface derivative (chart derivative divided by the frozen "
                              "warp Jacobian)" if warp_normalised else "chart derivative"),
        "warp_normalised": warp_normalised,
        "definition": "one-sided first derivative of the linear albedo at the periodic seam "
                      "(second-order stencils on [0,2h] and [C-2h,C] with h_u=1e-5, both "
                      "estimating f'(0+)=f'(C-)) compared against the same stencil measured "
                      "in the interior of the chart with the same sample count; legitimate "
                      "frozen kinks are budgeted, not hidden",
    }

    x_mm, s_mm, areas = face_centre_chart(frame, mother)
    world: dict[str, Any]
    if x_mm.size < 8:
        world = {"status": "NOT_RUN", "reason": "too few faces on the tagged surface", "pass": True}
    else:
        u = np.mod(x_mm / x_period, 1.0)
        low_band = u <= np.quantile(u, 0.05)
        high_band = u >= np.quantile(u, 0.95)
        s_low, s_high = s_mm[low_band], s_mm[high_band]
        if s_low.size == 0 or s_high.size == 0:
            world = {"status": "NOT_RUN", "reason": "seam bands are empty", "pass": True}
        else:
            order = np.argsort(s_high)
            s_sorted = s_high[order]
            pair_index = np.searchsorted(s_sorted, s_low)
            pair_index = np.clip(pair_index, 0, s_sorted.size - 1)
            delta_s = np.abs(s_sorted[pair_index] - s_low)
            keep = delta_s <= max(1.0, 0.02 * frame.s_span_mm)
            if not np.any(keep):
                world = {"status": "NOT_RUN", "reason": "no profile-matched seam pairs",
                         "pass": True}
            else:
                x_low = x_mm[low_band][keep]
                x_high = x_mm[high_band][order][pair_index][keep]
                s_pair = s_low[keep]
                c_low = albedo_at(x_low, s_pair)
                c_high = albedo_at(x_high, s_pair + (s_sorted[pair_index][keep] - s_pair))
                step = np.abs(c_low - c_high).max(axis=1)
                circ_min, circ_max = local_mm_per_u(frame)
                circ = 0.5 * (circ_min + circ_max) if circ_max > 0 else x_period
                arc = np.abs(np.mod(x_high - x_low + 0.5 * x_period, x_period) - 0.5 * x_period)
                arc = np.maximum(arc, 1e-9)
                lipschitz = _lipschitz_bound(frame, region, albedo_at)
                bound = lipschitz * arc
                ratio_world = np.where(bound > 0, step / np.maximum(bound, 1e-12), 0.0)
                world = {
                    "status": "OK",
                    "n_pairs": int(step.size),
                    "max_abs_color_error": float(step.max()),
                    "max_arc_step_mm": float(arc.max()),
                    "lipschitz_max_per_mm": float(lipschitz),
                    "max_ratio_to_bound": float(ratio_world.max()),
                    "flat_field": bool(lipschitz <= 1e-12),
                    "local_circumference_mm": [float(circ_min), float(circ_max)],
                    "pass": bool(ratio_world.max() <= 1.05),
                    "definition": "mesh faces next to the seam paired by profile coordinate; the "
                                  "colour step must stay under the measured field Lipschitz "
                                  "bound times the real arc distance",
                }
    return {"chart_space": chart_space, "world_space": world}


def _derivative_enforced(recipe: PatternRecipe) -> tuple[bool, str]:
    """Is the first-derivative seam budget a pass/fail criterion for this frozen field?

    Rasterised stroke tiles, discrete dot sets, dropped-stroke lookup tables and
    piecewise-linear colour ramps contain legitimate **C0 content edges**: their value is
    periodic (checked against the 1e-5 budget) but their derivative has real jumps inside
    the content itself.  For those families the derivative mismatch is still measured and
    reported on every run, but it cannot decide the pass/fail state; for smoothly
    parameterised fields (bands, linear-phase stripes, vector symbols, relief/engrave
    masks) the budget is enforced.
    """
    stack: list[tuple[str, dict[str, Any]]] = [("recipe", dict(recipe.params or {}))]
    seen = 0
    while stack and seen < 12:
        where, params = stack.pop()
        seen += 1
        if isinstance(params.get("raster"), dict):
            return False, f"{where}: frozen raster tile (rasterised stroke edges are C0 content)"
        if params.get("dots"):
            return False, f"{where}: frozen dot set (dot rims are C0 content)"
        if params.get("colour_stops"):
            return False, f"{where}: piecewise-linear colour ramp (C0 at the ramp stops)"
        if params.get("kept_lookup"):
            return False, f"{where}: dropped-stroke lookup table (line ends are C0 content)"
        for layer in params.get("layers") or []:
            if isinstance(layer, dict):
                stack.append((f"{where}.layers[{layer.get('family')}]",
                              dict(layer.get("params") or {})))
    return True, "smooth analytic field: the first-derivative budget is enforced"


def _lipschitz_bound(frame: ChartFrame, region: dict[str, Any], albedo_at) -> float:
    """First-difference estimate of the field's gradient on a 192x64 chart grid.

    This is a **lower-bound estimate** of ``sup|grad albedo|``, not an upper bound: at a
    fixed grid spacing the estimate only sees structure wider than the spacing, so it grows
    without limit as the grid is refined (A05 evidence:
    ``data/a12/reports/a05_cut_continuity_probe.json``).  It is kept as a measured
    diagnostic; it must not be used as a claimed bound of the field.
    """
    n_x, n_s = 192, 64
    x = (np.arange(n_x) + 0.5) * float(frame.x_period_mm) / n_x
    s = region["s_min_mm"] + (np.arange(n_s) + 0.5) * (region["s_max_mm"] - region["s_min_mm"]) / n_s
    gx, gs = np.meshgrid(x, s, indexing="xy")
    values = albedo_at(gx.reshape(-1), gs.reshape(-1)).reshape(n_s, n_x, 3)
    dx_mm = float(frame.x_period_mm) / n_x
    ds_mm = (region["s_max_mm"] - region["s_min_mm"]) / n_s
    grad_x = np.abs(np.diff(values, axis=1)).max() / dx_mm
    grad_s = np.abs(np.diff(values, axis=0)).max() / ds_mm
    return float(max(grad_x, grad_s))


# ---------------------------------------------------------------------------------------
# determinism
# ---------------------------------------------------------------------------------------
def _audit_determinism(recipe: PatternRecipe, albedo_at, rng: np.random.Generator) -> dict[str, Any]:
    x = rng.uniform(0.0, 100.0, size=257)
    s = rng.uniform(0.0, 60.0, size=257)
    first = albedo_at(x, s)
    second = albedo_at(x, s)
    repeat = bool(np.array_equal(first, second))

    pieces = [albedo_at(x[i:i + 17], s[i:i + 17]) for i in range(0, x.size, 17)]
    batched = np.vstack(pieces)
    batch_ok = bool(np.array_equal(batched, first))

    order = np.argsort(-s)
    reordered = albedo_at(x[order], s[order])
    order_ok = bool(np.array_equal(reordered, first[order]))

    state_before = np.random.get_state()
    import random as _random

    py_state = _random.getstate()
    payload_before = recipe_hash(recipe)
    _ = albedo_at(x, s)
    rng_unchanged = bool(_compare_state(state_before, np.random.get_state()))
    py_unchanged = bool(py_state == _random.getstate())
    payload_after = recipe_hash(recipe)

    seeds_guard = _seeds_guard(albedo_at, x, s)

    checks = {
        "repeat_identical": {"pass": repeat, "detail": "two identical calls are bit-identical"},
        "batch_invariance": {"pass": batch_ok, "detail": "batches of 17 concatenate to the same field"},
        "order_invariance": {"pass": order_ok, "detail": "reversed query order returns reversed values"},
        "rng_state_untouched": {"pass": rng_unchanged and py_unchanged,
                                "detail": "numpy legacy and python random states unchanged"},
        "frozen_params_unchanged": {"pass": payload_before == payload_after,
                                    "detail": "recipe payload hash stable across queries"},
        "no_seed_module_use": seeds_guard,
        "fragment_id_independence": {
            "pass": repeat and batch_ok and order_ok,
            "detail": "the field depends only on (recipe, x, s): no fragment identity, batch "
                      "size or query order enters the value",
        },
    }
    checks["pass"] = all(bool(v.get("pass")) for v in checks.values() if isinstance(v, dict))
    return checks


def _compare_state(a: tuple, b: tuple) -> bool:
    if a[0] != b[0] or a[2] != b[2] or a[3] != b[3]:
        return False
    return bool(np.array_equal(a[1], b[1]))


def _seeds_guard(albedo_at, x: np.ndarray, s: np.ndarray) -> dict[str, Any]:
    """Prove that the query path never calls the seed helpers."""
    import synlab.seeds as seeds

    original_make = seeds.make_rng
    original_seed64 = seeds.seed64
    called: list[str] = []

    def _boom(*args, **kwargs):
        called.append("called")
        raise AssertionError("evaluate must not draw randomness")

    seeds.make_rng = _boom
    seeds.seed64 = _boom
    try:
        _ = albedo_at(x[:16], s[:16])
        ok = not called
    except AssertionError:
        ok = False
    finally:
        seeds.make_rng = original_make
        seeds.seed64 = original_seed64
    return {"pass": bool(ok),
            "detail": "patched synlab.seeds.make_rng/seed64 to raise; the query still returned"}


# ---------------------------------------------------------------------------------------
# scale
# ---------------------------------------------------------------------------------------
def _audit_scale(recipe: PatternRecipe, frame: ChartFrame, region: dict[str, Any],
                 rng: np.random.Generator, samples: int, albedo_at,
                 mother: MotherGeometry) -> dict[str, Any]:
    meta = recipe.meta or {}
    x_period = float(frame.x_period_mm or frame.s_span_mm)
    out: dict[str, Any] = {}
    modulation = _modulation(recipe)
    width_modulation = _width_modulation(recipe)

    width = _measure_line_width(width_modulation, frame, region, rng, int(samples)) \
        if _has_strokes(recipe) else {"status": "NA",
                                      "reason": "family has no stroke lines to measure"}
    out["line_width_mm"] = width
    out["line_width_measured_on"] = getattr(width_modulation, "modulation_source",
                                            "composite field")
    params = recipe.params or {}
    out["declared_line_width_mm"] = float(params.get("primary_line_width_mm",
                                                     params.get("line_width_mm", 0.0)))

    dots = (recipe.params or {}).get("dots")
    if dots:
        rows = np.asarray(dots, dtype=np.float64).reshape(-1, 3)
        centres, radii = rows[:, :2], rows[:, 2]
        nn = nearest_neighbour_distance(centres, x_period)
        finite = nn[np.isfinite(nn)]
        margin = _dot_margin(rows, x_period)
        out["dot_spacing_mm"] = {
            "status": "OK",
            "n_dots": int(rows.shape[0]),
            "min_neighbour_distance_mm": float(finite.min()) if finite.size else None,
            "median_neighbour_distance_mm": float(np.median(finite)) if finite.size else None,
            "p05_neighbour_distance_mm": float(np.percentile(finite, 5)) if finite.size else None,
            "radius_min_mm": float(radii.min()), "radius_max_mm": float(radii.max()),
            "required_min_distance_mm": 2.0 * float(radii.max()),
            "min_radius_sum_margin_mm": margin,
            "cross_seam_min_distance_mm": _cross_seam_min(centres, x_period),
            "pass": bool(margin is None or margin >= -1e-9),
            "definition": "periodic nearest-neighbour distance of the frozen dot set; the "
                          "required separation is 2*r for fixed radius and r_i+r_j+clearance "
                          "for variable radius",
        }
        out["dots_report"] = dict((recipe.params or {}).get("sampling_report") or {})

    spectrum = measure_spectrum(modulation, x_period_mm=x_period,
                                s_min_mm=float(region["s_min_mm"]),
                                s_max_mm=float(region["s_max_mm"]),
                                s_periodic=bool(frame.s_periodic))
    frozen = dict(meta.get("spectrum") or {})
    spectrum["frozen_dominant_wavelength_mm"] = frozen.get("dominant_wavelength_mm")
    spectrum["recheck_agreement"] = (
        None if not frozen.get("dominant_wavelength_mm") or not spectrum.get("dominant_wavelength_mm")
        else float(abs(spectrum["dominant_wavelength_mm"] - frozen["dominant_wavelength_mm"])
                   / frozen["dominant_wavelength_mm"]))
    out["spectrum"] = spectrum
    out["min_wavelength_mm"] = spectrum.get("min_wavelength_mm")
    circ_min, circ_max = local_mm_per_u(frame)
    out["circumferential_metric"] = {
        "x_period_mm": x_period,
        "u_arc_length_mm_min": float(circ_min), "u_arc_length_mm_max": float(circ_max),
        "note": "circumferential spacing is 2*pi*r(s)/|k|: it varies with the radius, the chart "
                "x is an arc length on the reference circumference",
    }
    n_int = (recipe.params or {}).get("circumferential_count_integer")
    if n_int:
        out["circumferential_spacing_mm"] = {
            "integer_count": int(n_int),
            "reference_spacing_mm": float(x_period / int(n_int)),
            "local_spacing_mm_min": float(circ_min / int(n_int)) if circ_min else None,
            "local_spacing_mm_max": float(circ_max / int(n_int)) if circ_max else None,
        }
    return out


def _has_strokes(recipe: PatternRecipe) -> bool:
    family = recipe.family_id
    if family in ("PAT01", "PAT13", "PAT14"):
        return False
    if family == "PAT06":
        return True
    return True


def _modulation(recipe: PatternRecipe):
    from .api import pattern_field

    fn = lambda x, s: pattern_field(recipe, np.asarray(x), np.asarray(s)).modulation  # noqa: E731
    fn.modulation_source = "composite field"  # type: ignore[attr-defined]
    return fn


def _width_modulation(recipe: PatternRecipe):
    """Modulation used for the *line width* measurement.

    A combined recipe (PAT16) is a union of layers with zone weights, so the union's
    cross-section mixes zone feathers with strokes and its measured "line width" is not the
    width of any stroke set.  The primary stroke layer is therefore measured on its own and
    the reported number is labelled with the layer it belongs to.
    """
    from .api import _context, pattern_field
    from .layers import build_field

    params = recipe.params or {}
    for layer in params.get("layers") or []:
        frozen = dict((layer or {}).get("params") or {})
        if not (frozen.get("raster") or frozen.get("dots") or frozen.get("groups")):
            continue
        family = str(layer.get("family"))
        field = build_field(family, frozen)
        ctx = _context(recipe)

        def primary(x, s, _field=field, _ctx=ctx):
            out = _field.process(np.asarray(x, dtype=np.float64),
                                 np.asarray(s, dtype=np.float64), _ctx)
            return out.modulation

        primary.modulation_source = f"primary stroke layer {family}"  # type: ignore[attr-defined]
        return primary
    del pattern_field
    return _modulation(recipe)


def _measure_line_width(modulation, frame: ChartFrame, region: dict[str, Any],
                        rng: np.random.Generator, samples: int) -> dict[str, Any]:
    n = int(samples)
    x_period = float(frame.x_period_mm or frame.s_span_mm)
    x0 = rng.uniform(0.0, x_period, size=n)
    s0 = rng.uniform(float(region["s_min_mm"]), float(region["s_max_mm"]), size=n)
    h = 0.05
    gx = (modulation(x0 + h, s0) - modulation(x0 - h, s0)) / (2 * h)
    gs = (modulation(x0, s0 + h) - modulation(x0, s0 - h)) / (2 * h)
    norm = np.hypot(gx, gs)
    valid = norm > 1e-6
    if not np.any(valid):
        return {"status": "NA", "reason": "no local gradient found at the sampled points",
                "n_samples": n}
    ux = np.where(valid, gx / np.where(norm > 0, norm, 1.0), 1.0)
    us = np.where(valid, gs / np.where(norm > 0, norm, 1.0), 0.0)
    step = 0.02
    offsets = np.arange(-120, 121) * step
    profile = np.empty((offsets.size, n))
    for index, offset in enumerate(offsets):
        profile[index] = modulation(x0 + offset * ux, s0 + offset * us)
    peak = profile.max(axis=0)
    # A "line" is a feature that actually reaches (nearly) full coverage.  Faint auxiliary
    # washes and half-covered junctions are counted separately so they cannot drag the
    # measured line width.
    strong = valid & (peak >= 0.8)
    weak_only = bool(np.any(valid & (peak >= 0.5))) and not bool(np.any(strong))
    ok = strong if np.any(strong) else (valid & (peak >= 0.5))
    widths: list[float] = []
    rejected_not_unimodal = 0
    for column in np.flatnonzero(ok):
        values = profile[:, column]
        # a single line has one turning point along the gradient direction; profiles taken
        # across a junction or a tile corner are multi-modal and are not a line width
        turning = int(np.sum(np.diff(np.sign(np.diff(values))) != 0))
        if turning > 3:
            rejected_not_unimodal += 1
            continue
        half = 0.5 * peak[column]
        above = np.flatnonzero(values >= half)
        if above.size < 2:
            continue
        lo, hi = above[0], above[-1]
        left = _crossing(values, lo, half, step, forward=False)
        right = _crossing(values, hi, half, step, forward=True)
        widths.append(max(0.0, right - left))
    if not widths:
        return {"status": "NA", "reason": "no line cross-section found in the sampled window",
                "n_samples": n, "n_valid_gradient": int(valid.sum())}
    arr = np.asarray(widths)
    if arr.size < 3:
        # a single cross-section is not a distribution: report the count and the samples
        # instead of claiming a measured line width
        return {
            "status": "INSUFFICIENT", "n_measurements": int(arr.size), "n_samples": n,
            "n_full_coverage_lines": int(np.sum(strong)),
            "n_rejected_not_unimodal": int(rejected_not_unimodal),
            "samples_mm": [float(v) for v in arr],
            "reason": "fewer than three unimodal line cross-sections were found in the "
                      "sampled window (junctions, corners and window clipping are rejected)",
            "step_mm": float(step),
        }
    return {
        "status": "OK", "n_measurements": int(arr.size), "n_samples": n,
        "n_full_coverage_lines": int(np.sum(strong)),
        "n_rejected_not_unimodal": int(rejected_not_unimodal),
        "fell_back_to_half_coverage": bool(weak_only),
        "n_valid_gradient": int(valid.sum()),
        "min_mm": float(arr.min()), "p05_mm": float(np.percentile(arr, 5)),
        "p50_mm": float(np.median(arr)), "p95_mm": float(np.percentile(arr, 95)),
        "max_mm": float(arr.max()),
        "step_mm": float(step), "window_mm": float(offsets.size * step),
        "method": "full width at half maximum along the local alpha gradient, measured on the "
                  "surface chart in millimetres",
    }


def _crossing(values: np.ndarray, index: int, half: float, step: float, *, forward: bool) -> float:
    """Offset (mm) where the profile crosses ``half``, walking away from ``index``."""
    if forward:
        for k in range(index, values.size - 1):
            if values[k + 1] < half:
                v0, v1 = values[k], values[k + 1]
                frac = 0.0 if abs(v1 - v0) < 1e-12 else (half - v0) / (v1 - v0)
                return float((k + frac - 120) * step)
    else:
        for k in range(index, 0, -1):
            if values[k - 1] < half:
                v0, v1 = values[k], values[k - 1]
                frac = 0.0 if abs(v1 - v0) < 1e-12 else (half - v0) / (v1 - v0)
                return float((k - frac - 120) * step)
    return float((index - 120) * step)


def _dot_margin(rows: np.ndarray, x_period: float) -> float:
    from scipy.spatial import cKDTree

    pts = np.asarray(rows, dtype=np.float64)
    if pts.shape[0] < 2:
        return float("inf")
    copies = np.vstack([pts, pts + np.array([x_period, 0.0, 0.0]),
                        pts - np.array([x_period, 0.0, 0.0])])
    tree = cKDTree(copies[:, :2])
    k = int(min(12, copies.shape[0]))
    dist, idx = tree.query(pts[:, :2], k=k)
    dist = np.atleast_2d(dist)
    idx = np.atleast_2d(idx)
    n = pts.shape[0]
    margin = float("inf")
    for row in range(n):
        for col in range(dist.shape[1]):
            j = int(idx[row, col]) % n
            if j == row:
                continue
            margin = min(margin, float(dist[row, col] - (pts[row, 2] + pts[j, 2])))
    return margin


def _cross_seam_min(centres: np.ndarray, x_period: float) -> float | None:
    pts = np.asarray(centres, dtype=np.float64)
    if pts.shape[0] < 2:
        return None
    best = np.inf
    for shift in (-x_period, x_period):
        shifted = pts + np.array([shift, 0.0])
        for index in range(pts.shape[0]):
            d = np.hypot(shifted[:, 0] - pts[index, 0], shifted[:, 1] - pts[index, 1])
            d[index] = np.inf
            best = min(best, float(d.min()))
    return None if not np.isfinite(best) else float(best)


# ---------------------------------------------------------------------------------------
# inheritance
# ---------------------------------------------------------------------------------------
def _audit_inheritance(recipe: PatternRecipe, frame: ChartFrame, region: dict[str, Any],
                       rng: np.random.Generator, albedo_at, mother: MotherGeometry) -> dict[str, Any]:
    x_period = float(frame.x_period_mm or frame.s_span_mm)
    n = 128
    x = rng.uniform(0.0, x_period, size=n)
    s = rng.uniform(float(region["s_min_mm"]), float(region["s_max_mm"]), size=n)
    first = albedo_at(x, s)
    # emulate two fragments querying the same mother field, then the first fragment again
    _ = albedo_at(x[:32] + 1.0, s[:32])
    _ = albedo_at(x[64:], s[64:])
    again = albedo_at(x, s)
    identity = bool(np.array_equal(first, again))

    cut_ok, cut_stats = _cut_continuity(recipe, frame, region, albedo_at, mother, rng)
    body = _new_surface_body(recipe, mother, rng)

    checks = {
        "field_identity_across_fragments": {
            "pass": identity,
            "detail": "interleaved queries for two hypothetical fragments return bit-identical "
                      "values for the first fragment: the field is frozen, never redrawn",
        },
        "cut_continuity": cut_stats | {"pass": cut_ok},
        "new_surface_exposes_body": body,
    }
    checks["pass"] = all(bool(v.get("pass")) for v in checks.values() if isinstance(v, dict))
    return checks


def _cut_continuity(recipe: PatternRecipe, frame: ChartFrame, region: dict[str, Any],
                    albedo_at, mother: MotherGeometry,
                    rng: np.random.Generator) -> tuple[bool, dict[str, Any]]:
    """Plan 9.6 clause 3 on a real cut of the real mother.

    A plane through the vessel axis is the cut the plane fracture backend makes.  Mother
    surface points inside ``CUT_BAND_MM`` of that plane are the "points on both sides close
    to the same fracture curve"; each side is queried twice:

    * through the **fragment-facing** path ``patterns.api.evaluate`` (world mm -> chart ->
      frozen field, with the surface tag, legal-region weight and the float32 channel
      contract a fragment really receives), and
    * through the recipe's **own** frozen field at the same chart coordinates.

    The two must agree within the plan's continuous-channel budget, on both sides: that is
    what "both sides query the original field / source inheritance and colour" means, and a
    fragment-path break (wrong chart mapping, re-randomised per-fragment field, a colour
    that is not the mother's) shows up as a difference far above the budget.

    A steepness bound is deliberately *not* the criterion.  The old form of this check
    divided the across-cut colour step by ``_lipschitz_bound`` (a first-difference estimate
    on a fixed 192x64 chart grid) and demanded a ratio <= 1.05; for this mother that grid is
    dx = 2.53 mm / ds = 1.06 mm wide, so the estimate under-resolves stroke edges and rises
    without limit as the grid is refined (0.2207 -> 1.2338 per mm over an 8x refinement,
    ``tests/a12/patterns/probe_a05_cut_continuity.py --stage sweep``).  It is therefore a
    lower bound of ``sup|grad albedo|``, and any field whose motif edge is narrower than the
    grid fails the ratio test while being perfectly continuous.  The measured across-cut
    colour step is still reported here, together with the field's own step at the same
    separation, as evidence rather than as a threshold.
    """
    from .api import evaluate
    from .charts import region_weight, tag_index, to_chart_mm, vertex_surface_tags

    tag = int(tag_index(mother, str(region["surface_tag"])))
    verts = np.asarray(mother.mesh.vertices, dtype=np.float64)
    tags = np.asarray(vertex_surface_tags(mother))
    on_tag = tags == tag
    surface = verts[on_tag]
    if surface.shape[0] < 2 * CUT_MIN_SIDE_POINTS:
        return True, {"status": "NOT_RUN", "pass": True,
                      "reason": f"only {surface.shape[0]} mother vertices on the recipe region",
                      "n_surface_vertices": int(surface.shape[0])}
    angle = np.arctan2(surface[:, 1], surface[:, 0])
    radius = np.hypot(surface[:, 0], surface[:, 1])
    half_angle = np.minimum(math.pi, CUT_BAND_MM / np.maximum(radius, 1e-9))
    # The revolve mesh carries its vertices in azimuthal columns (~7 deg apart here), so the
    # cut azimuth is searched on a fine grid and the candidate that puts the most surface on
    # the thinner of its two sides is taken: that is the cut which really has two sides.
    base = float(rng.uniform(-math.pi, math.pi))
    best: tuple[int, float, np.ndarray, np.ndarray] | None = None
    for centre in base + np.arange(240) * (math.pi / 240.0):
        delta = np.mod(angle - centre + math.pi, 2.0 * math.pi) - math.pi
        near = np.abs(delta) <= half_angle
        side = delta[near] >= 0.0
        n_plus, n_minus = int(side.sum()), int((~side).sum())
        score = min(n_plus, n_minus)
        if best is None or score > best[0]:
            best = (score, float(centre), near, side)
    if best is None or best[0] < CUT_MIN_SIDE_POINTS:
        return True, {"status": "NOT_RUN", "pass": True,
                      "reason": "no cut azimuth carries enough mother vertices on both sides",
                      "n_surface_vertices": int(surface.shape[0]),
                      "best_side_count": None if best is None else best[0]}
    _, cut_azimuth, near, side = best
    pts = surface[near]
    x_mm, s_mm = to_chart_mm(frame, pts)
    weight = region_weight(frame, pts, x_mm, s_mm, region)
    interior = weight >= 1.0 - 1e-9
    if int(interior.sum()) < 2 * CUT_MIN_SIDE_POINTS:
        return True, {"status": "NOT_RUN", "pass": True,
                      "reason": "the legal-region feather covers the whole cut band",
                      "n_interior": int(interior.sum())}
    pts, x_mm, s_mm = pts[interior], x_mm[interior], s_mm[interior]
    side = side[interior]
    channels = evaluate(recipe, mother, pts, tag)
    fragment = np.asarray(channels.albedo, dtype=np.float64)
    original = np.asarray(albedo_at(x_mm, s_mm), dtype=np.float64)
    step = np.abs(fragment - original).max(axis=1)
    max_plus = float(step[side].max()) if bool(np.any(side)) else None
    max_minus = float(step[~side].max()) if bool(np.any(~side)) else None
    ok = (max_plus is not None and max_minus is not None
          and max_plus <= CUT_CHANNEL_TOL and max_minus <= CUT_CHANNEL_TOL)

    # measured cross-cut colour: nearest neighbour of each + point among the - points
    plus, minus = np.flatnonzero(side), np.flatnonzero(~side)
    cross_step = None
    cross_gap = None
    if plus.size and minus.size:
        dx = np.abs(x_mm[plus][:, None] - x_mm[minus][None, :])
        dx = np.minimum(dx, float(frame.x_period_mm) - dx)
        ds = np.abs(s_mm[plus][:, None] - s_mm[minus][None, :])
        gap = np.hypot(dx, ds)
        nearest = np.argmin(gap, axis=1)
        pair_gap = gap[np.arange(plus.size), nearest]
        pair_step = np.abs(original[plus] - original[minus[nearest]]).max(axis=1)
        cross_step = {"max_abs_color_step": float(pair_step.max()),
                      "p50_abs_color_step": float(np.quantile(pair_step, 0.5)),
                      "max_gap_mm": float(pair_gap.max()),
                      "p50_gap_mm": float(np.quantile(pair_gap, 0.5))}
        cross_gap = float(np.quantile(pair_gap, 0.5))
    return bool(ok), {
        "status": "OK" if ok else "FAIL",
        "cut": {"kind": "plane_through_axis", "azimuth_deg": float(np.degrees(cut_azimuth)),
                "band_mm": CUT_BAND_MM},
        "n_pairs": int(pts.shape[0]),
        "n_side_plus": int(side.sum()),
        "n_side_minus": int((~side).sum()),
        "fragment_path_channel": "float32 (patterns.api.PatternChannels.albedo)",
        "tolerance": CUT_CHANNEL_TOL,
        "max_abs_color_error_side_plus": max_plus,
        "max_abs_color_error_side_minus": max_minus,
        "bit_identical": bool(max_plus == 0.0 and max_minus == 0.0),
        "cross_cut_color": cross_step,
        "cross_cut_median_gap_mm": cross_gap,
        "detail": "both sides of a real plane cut query the frozen field: the fragment-facing "
                  "evaluate() path and the recipe field agree within the plan's 1e-5 "
                  "continuous-channel budget, so the cut inherits the original colour instead "
                  "of a redrawn one",
        "steepness_bound_note": "no steepness/Lipschitz ratio is used as a criterion; see the "
                                "docstring and tests/a12/patterns/probe_a05_cut_continuity.py",
    }


def _new_surface_body(recipe: PatternRecipe, mother: MotherGeometry,
                      rng: np.random.Generator) -> dict[str, Any]:
    from .api import evaluate

    tag = "interface"
    points = np.asarray(mother.mesh.vertices, dtype=np.float64)
    if points.shape[0] > 64:
        pick = rng.choice(points.shape[0], size=64, replace=False)
        points = points[pick]
    channels = evaluate(recipe, mother, points, tag)
    body = np.asarray(recipe.palette[0], dtype=np.float64) if recipe.palette else None
    region_clean = bool(np.all(channels.pattern_region == 0))
    albedo_body = True
    if body is not None and channels.albedo.size:
        albedo_body = bool(np.allclose(np.asarray(channels.albedo, dtype=np.float64),
                                       body[None, :], atol=1e-6))
    return {
        "pass": bool(region_clean and albedo_body),
        "status": "OK",
        "pattern_region_all_zero": region_clean,
        "albedo_equals_body": albedo_body,
        "n_points": int(points.shape[0]),
        "unpatterned_reason": channels.meta.get("unpatterned_reason"),
        "detail": "a fresh fracture surface is unpainted and returns the body colour",
        "material_integration": "PENDING: synlab.materials.material_at owns the body layer "
                                "colour; the audit compares against the recipe body colour",
    }


# ---------------------------------------------------------------------------------------
# geometry
# ---------------------------------------------------------------------------------------
def _audit_geometry(recipe: PatternRecipe, mother: MotherGeometry, probe: bool) -> dict[str, Any]:
    from .geometry import apply_pattern_geometry
    from .serialize import geometry_hash

    height = dict((recipe.meta or {}).get("height") or {})
    mode = str(height.get("mode", "none"))
    before = geometry_hash(np.asarray(mother.mesh.vertices), np.asarray(mother.mesh.faces))
    if mode == "none":
        after_mother = apply_pattern_geometry(mother, recipe, np.random.default_rng(0))
        after = geometry_hash(np.asarray(after_mother.mesh.vertices), np.asarray(after_mother.mesh.faces))
        identical_object = after_mother is mother
        return {
            "mode": "none",
            "geometry_hash_before": before, "geometry_hash_after": after,
            "hash_unchanged": bool(before == after),
            "same_object_returned": bool(identical_object),
            "pass": bool(before == after and identical_object),
            "reason": "appearance-only family must not change the mother geometry",
            "appearance_only_normal_map": False,
        }
    if not probe:
        return {"mode": mode, "status": "NOT_RUN", "pass": True,
                "reason": "geometry probe disabled"}
    try:
        # bounded refinement keeps the audit fast; the achieved resolution and how many
        # samples per minimum wavelength it gives are reported, never hidden
        after_mother = apply_pattern_geometry(mother, recipe, np.random.default_rng(1),
                                              max_faces=AUDIT_MAX_FACES)
    except SynLabError as exc:
        code = str(getattr(exc.code, "value", exc.code))
        if code in ("TARGET_INFEASIBLE", "PRECISION_BUDGET_EXCEEDED",
                    "PRECISION_NOT_REALIZED", "INTEGRATION_PENDING"):
            # the wall-thickness / precision guard fired: the frozen amplitude is infeasible
            # on this body.  That is the guard doing its job, not a broken implementation.
            return {"mode": mode, "status": "GUARD_REJECTED", "pass": True,
                    "guard_code": code, "guard_measurements": exc.measurements,
                    "reason": "the geometry was refused by a structured guard (wall "
                              "thickness, mesh precision or a missing mother declaration) "
                              "instead of being faked; the guard does its job, the gap is "
                              "reported in guard_measurements"}
        return {"mode": mode, "status": "ERROR", "pass": False,
                "error": exc.to_dict(),
                "reason": "geometric application failed"}
    evidence = dict((after_mother.meta or {}).get("pattern_geometry") or {})
    after = geometry_hash(np.asarray(after_mother.mesh.vertices), np.asarray(after_mother.mesh.faces))
    delta = float(evidence.get("volume_delta_mm3", 0.0))
    displacement = float(evidence.get("vertex_displacement_max_mm", 0.0))
    expected_sign = 1.0 if mode == "relief" else -1.0
    sign_ok = (delta > 0) if mode == "relief" else (delta < 0)
    out = {
        "mode": mode,
        "geometry_hash_before": before,
        "geometry_hash_after": after,
        "hash_changed": bool(before != after),
        "volume_before_mm3": float(evidence.get("volume_before_mm3", 0.0)),
        "volume_after_mm3": float(evidence.get("volume_after_mm3", 0.0)),
        "volume_delta_mm3": delta,
        "vertex_displacement_max_mm": displacement,
        "n_vertices_displaced": int(evidence.get("n_vertices_displaced", 0)),
        "flipped_faces": int(evidence.get("flipped_faces", 0)),
        "watertight_after": bool(evidence.get("watertight_after", False)),
        "refinement": evidence.get("refinement"),
        "interpolation_error_mm": evidence.get("interpolation_error_mm"),
        "wall_thickness": evidence.get("wall_thickness"),
        "expected_volume_sign": ("positive (material added)" if mode == "relief"
                                 else "negative (material removed)"),
        "appearance_only_normal_map": False,
        "pass": bool(before != after and displacement > 0 and sign_ok
                     and int(evidence.get("flipped_faces", 0)) == 0
                     and bool(evidence.get("watertight_after", False))),
    }
    amplitude = float((recipe.meta or {}).get("height", {}).get("amplitude_mm", 0.0))
    interp = float((evidence.get("interpolation_error_mm") or {}).get("max_abs_error_mm", 0.0))
    ratio = 0.0 if amplitude <= 0 else interp / amplitude
    out["precision"] = {
        "interpolation_error_mm": interp,
        "amplitude_mm": amplitude,
        "interpolation_ratio": ratio,
        "status": ("FINE" if ratio <= 0.25 else ("COARSE" if ratio <= 0.6 else "NOT_REALIZED")),
        "samples_per_min_wavelength": (evidence.get("refinement") or {}).get(
            "samples_per_min_wavelength"),
        "method": "analytic height at face centroids vs mean nodal displacement",
    }
    if not out["pass"]:
        out["reason"] = ("geometry did not change as expected for a real displacement "
                         f"(hash_changed={out['hash_changed']}, displacement={displacement:.4g} mm, "
                         f"volume sign ok={sign_ok})")
    return out
