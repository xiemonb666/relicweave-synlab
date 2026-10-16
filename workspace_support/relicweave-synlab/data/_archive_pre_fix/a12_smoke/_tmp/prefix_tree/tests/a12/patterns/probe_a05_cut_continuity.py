"""A05 root-cause probe: is ``cut_continuity`` failing because of the field or the criterion?

The probe rebuilds exactly the recipe/mother the A05 audit uses
(``synlab.patterns.audit_all`` request dictionaries), then:

1. reproduces ``_cut_continuity`` verbatim and records its numbers;
2. sweeps the resolution of ``_lipschitz_bound`` (the "measured Lipschitz bound" the
   criterion divides by) to show whether that number is an *upper* bound of the field's
   sup gradient or a resolution-limited lower-bound estimate;
3. measures the field's *achieved* colour step at the same 1.0 mm separation over many
   random in-region pairs, i.e. the same statistic as the cut step but off the synthetic
   curve.

Nothing here mutates the recipe or the store; every number is written to
``data/a12/reports/a05_cut_continuity_probe.json``.

Run:  .venv\\Scripts\\python.exe tests\\a12\\patterns\\probe_a05_cut_continuity.py --stage repro
      .venv\\Scripts\\python.exe tests\\a12\\patterns\\probe_a05_cut_continuity.py --stage sweep
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT = ROOT / "data" / "a12" / "reports" / "a05_cut_continuity_probe.json"
FAMILIES = ("PAT06", "PAT07", "PAT08", "PAT09")


def _load() -> dict[str, Any]:
    if OUT.exists():
        return json.loads(OUT.read_text(encoding="utf-8"))
    return {"check": "A05 cut_continuity root cause", "families": {}}


def _save(data: dict[str, Any]) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
                   encoding="utf-8")


def build_family(family: str):
    """Rebuild the mother + frozen recipe exactly as ``audit_all_patterns`` does."""
    from synlab.patterns.api import _composite, _context, build_pattern
    from synlab.patterns.audit import _lipschitz_bound
    from synlab.patterns.audit_all import DEFAULT_PALETTE, DEFAULT_TIER, FAMILY_PARAMS
    from synlab.patterns.charts import resolve_frame
    from synlab.patterns.fixtures import mother_for_audit
    from synlab.patterns.layers import build_field
    from synlab.patterns.serialize import recipe_hash
    from synlab.seeds import make_rng

    seed = 20260101
    mother, mother_source, _notes = mother_for_audit(prefer_real=True, seed=seed % 10_000)
    tier = int(DEFAULT_TIER.get(family, 2))
    request = {
        "family": family, "complexity": tier, "palette_id": DEFAULT_PALETTE.get(family),
        "allow_aux_layers": True, "max_aux_layers": 2,
        "params": dict(FAMILY_PARAMS.get(family) or {}),
        "seed_ref": f"pattern-audit:{family}:tier{tier}:seed{seed}",
    }
    recipe = build_pattern(mother, request, make_rng(seed, "pattern-audit", family, tier))
    meta = recipe.meta or {}
    region = list(meta.get("regions") or [])[0]
    frame = resolve_frame(mother, str(region.get("surface_tag")))
    anchor = str(meta.get("recipe_hash") or recipe_hash(recipe))
    rng = np.random.default_rng(int(anchor.split(":")[-1][:16], 16))
    ctx = _context(recipe)
    field = build_field(recipe.family_id, recipe.params)
    aux = list(meta.get("aux_layers") or [])
    body = np.asarray((meta.get("palette") or {}).get("body", recipe.palette[0]), dtype=np.float64)

    def albedo_at(x_mm, s_mm, weight=None):
        out, _ = _composite(field, aux, np.asarray(x_mm, dtype=np.float64),
                            np.asarray(s_mm, dtype=np.float64), ctx)
        coverage = np.clip(out.coverage if weight is None else out.coverage * weight, 0.0, 1.0)
        return np.clip(body[None, :] * (1.0 - coverage[:, None])
                       + out.paint * coverage[:, None], 0.0, 1.0)

    return {"mother": mother, "mother_source": mother_source, "recipe": recipe, "meta": meta,
            "region": region, "frame": frame, "rng": rng, "albedo_at": albedo_at,
            "lipschitz_bound": _lipschitz_bound, "footprint_mm": meta.get("footprint_mm")}


def stage_repro(data: dict[str, Any], family: str) -> None:
    from synlab.patterns.audit import _cut_continuity

    built = build_family(family)
    frame, region = built["frame"], built["region"]
    rng = np.random.default_rng(int(str(built["meta"]["recipe_hash"]).split(":")[-1][:16], 16))
    ok, stats = _cut_continuity(built["albedo_at"], frame, region, rng)
    entry = data["families"].setdefault(family, {})
    entry["repro"] = {
        "pass": bool(ok), "stats": stats, "footprint_mm": built["footprint_mm"],
        "x_period_mm": float(frame.x_period_mm),
        "s_span_mm": float(region["s_max_mm"]) - float(region["s_min_mm"]),
        "lipshitz_grid_spacing_mm": {
            "dx_mm": float(frame.x_period_mm) / 192.0,
            "ds_mm": (float(region["s_max_mm"]) - float(region["s_min_mm"])) / 64.0},
        "cut_separation_mm": stats.get("separation_mm"),
    }
    _save(data)
    print(f"[repro] {family}: pass={ok} ratio={stats.get('max_ratio_to_bound'):.6f} "
          f"step={stats.get('max_abs_color_step'):.6f} "
          f"bound={stats.get('lipschitz_max_per_mm'):.6f}")


def stage_sweep(data: dict[str, Any], family: str, levels: int = 4) -> None:
    """Does the 'measured Lipschitz bound' converge upward with resolution?"""
    built = build_family(family)
    frame, region, albedo_at = built["frame"], built["region"], built["albedo_at"]
    entry = data["families"].setdefault(family, {})
    rows: list[dict[str, Any]] = []
    x_period = float(frame.x_period_mm)
    span = float(region["s_max_mm"]) - float(region["s_min_mm"])
    s0 = float(region["s_min_mm"])
    for mult in [2 ** k for k in range(levels)]:
        n_x, n_s = 192 * mult, 64 * mult
        started = time.perf_counter()
        x = (np.arange(n_x) + 0.5) * x_period / n_x
        s = s0 + (np.arange(n_s) + 0.5) * span / n_s
        gx, gs = np.meshgrid(x, s, indexing="xy")
        values = albedo_at(gx.reshape(-1), gs.reshape(-1)).reshape(n_s, n_x, 3)
        dx_mm, ds_mm = x_period / n_x, span / n_s
        grad_x = float(np.abs(np.diff(values, axis=1)).max() / dx_mm)
        grad_s = float(np.abs(np.diff(values, axis=0)).max() / ds_mm)
        rows.append({"n_x": n_x, "n_s": n_s, "dx_mm": dx_mm, "ds_mm": ds_mm,
                     "grad_x_per_mm": grad_x, "grad_s_per_mm": grad_s,
                     "estimate_per_mm": max(grad_x, grad_s),
                     "seconds": round(time.perf_counter() - started, 3)})
        _save(data)
        print(f"[sweep] {family} {n_x}x{n_s}: est={rows[-1]['estimate_per_mm']:.6f} "
              f"(dx={dx_mm:.4f} ds={ds_mm:.4f}) {rows[-1]['seconds']}s")
    entry["lipschitz_resolution_sweep"] = {
        "definition": "max over an axis-aligned chart grid of |delta albedo| / grid spacing",
        "rows": rows,
        "monotone_increasing": all(rows[i]["estimate_per_mm"] <= rows[i + 1]["estimate_per_mm"] + 1e-12
                                   for i in range(len(rows) - 1)),
        "coarsest_per_mm": rows[0]["estimate_per_mm"],
        "finest_per_mm": rows[-1]["estimate_per_mm"],
    }
    _save(data)


def stage_control(data: dict[str, Any], family: str, n: int = 20000) -> None:
    """Same statistic as the cut step, but measured away from the synthetic curve."""
    built = build_family(family)
    frame, region, albedo_at = built["frame"], built["region"], built["albedo_at"]
    rng = np.random.default_rng(4242)
    x_period = float(frame.x_period_mm)
    lo, hi = float(region["s_min_mm"]), float(region["s_max_mm"])
    offset = 0.5
    # axis-aligned separations (the same operator the grid estimate uses)
    x = rng.uniform(0.0, x_period, size=n)
    s = rng.uniform(lo + 2 * offset, hi - 2 * offset, size=n)
    along_s = np.abs(albedo_at(x, s + offset) - albedo_at(x, s - offset)).max(axis=1)
    per_mm_s = float(along_s.max()) / (2 * offset)
    along_x = np.abs(albedo_at(x + offset, s) - albedo_at(x - offset, s)).max(axis=1)
    per_mm_x = float(along_x.max()) / (2 * offset)
    entry = data["families"].setdefault(family, {})
    entry["off_curve_control"] = {
        "n_pairs": int(n), "separation_mm": 2 * offset,
        "max_step_along_s": float(along_s.max()), "slope_per_mm_along_s": per_mm_s,
        "max_step_along_x": float(along_x.max()), "slope_per_mm_along_x": per_mm_x,
        "p99_step_along_s": float(np.quantile(along_s, 0.99)),
        "detail": "the frozen field's own achieved colour step at the same 1.0 mm separation, "
                  "sampled off the synthetic cut curve",
    }
    _save(data)
    print(f"[control] {family}: slope_s={per_mm_s:.6f} slope_x={per_mm_x:.6f}")


def stage_refine(data: dict[str, Any], family: str, offsets=(0.5, 0.25, 0.125, 0.0625, 0.03125)):
    """Define-level continuity test: does the across-curve step vanish as h -> 0?"""
    built = build_family(family)
    frame, region, albedo_at = built["frame"], built["region"], built["albedo_at"]
    rng = np.random.default_rng(int(str(built["meta"]["recipe_hash"]).split(":")[-1][:16], 16))
    x_period = float(frame.x_period_mm)
    n = 96
    x = rng.uniform(0.0, x_period, size=n)
    n_int = max(1, int(x_period / 40.0))
    phase = float(rng.uniform(0.0, 2 * math.pi))
    s_centre = 0.5 * (float(region["s_min_mm"]) + float(region["s_max_mm"]))
    amplitude = 0.3 * (float(region["s_max_mm"]) - float(region["s_min_mm"]))
    curve = s_centre + amplitude * np.sin(2 * math.pi * n_int * x / x_period + phase)
    slope = amplitude * 2 * math.pi * n_int / x_period * np.cos(
        2 * math.pi * n_int * x / x_period + phase)
    normal = 1.0 / np.sqrt(1.0 + slope ** 2)
    rows = []
    for offset in offsets:
        s_plus, s_minus = curve + offset * normal, curve - offset * normal
        keep = ((s_plus >= region["s_min_mm"]) & (s_plus <= region["s_max_mm"])
                & (s_minus >= region["s_min_mm"]) & (s_minus <= region["s_max_mm"]))
        step = np.abs(albedo_at(x[keep], s_plus[keep]) - albedo_at(x[keep], s_minus[keep])).max(axis=1)
        rows.append({"offset_mm": offset, "separation_mm": 2 * offset, "n_pairs": int(keep.sum()),
                     "max_step": float(step.max()), "empirical_slope_per_mm": float(step.max()) / (2 * offset)})
        _save(data)
        print(f"[refine] {family} h={2*offset:.4f}: step={rows[-1]['max_step']:.6f} "
              f"slope={rows[-1]['empirical_slope_per_mm']:.4f}")
    entry = data["families"].setdefault(family, {})
    entry["cut_refinement"] = {
        "rows": rows,
        "detail": "a colour break at the synthetic curve would keep max_step finite as the "
                  "separation shrinks; a continuous frozen field sends it to zero",
    }
    _save(data)


def _curve_pairs(built, n: int = 96):
    """Reproduce the audit's synthetic fracture curve and its normal field."""
    frame, region = built["frame"], built["region"]
    rng = np.random.default_rng(int(str(built["meta"]["recipe_hash"]).split(":")[-1][:16], 16))
    x_period = float(frame.x_period_mm)
    x = rng.uniform(0.0, x_period, size=n)
    n_int = max(1, int(x_period / 40.0))
    phase = float(rng.uniform(0.0, 2 * math.pi))
    s_centre = 0.5 * (float(region["s_min_mm"]) + float(region["s_max_mm"]))
    amplitude = 0.3 * (float(region["s_max_mm"]) - float(region["s_min_mm"]))
    wave = 2 * math.pi * n_int * x / x_period + phase
    curve = s_centre + amplitude * np.sin(wave)
    slope = amplitude * 2 * math.pi * n_int / x_period * np.cos(wave)
    normal = 1.0 / np.sqrt(1.0 + slope ** 2)
    return x, curve, normal


def stage_paired(data: dict[str, Any], family: str, n: int = 96, controls: int = 8):
    """Cut step vs. the identical operator measured off the curve, at the same separation."""
    built = build_family(family)
    region, albedo_at = built["region"], built["albedo_at"]
    x, curve, normal = _curve_pairs(built, n)
    lo, hi = float(region["s_min_mm"]), float(region["s_max_mm"])
    span = hi - lo
    ctl_rng = np.random.default_rng(20260101)
    rows = []
    for offset in (0.5, 0.25, 0.125, 0.0625):
        s_plus, s_minus = curve + offset * normal, curve - offset * normal
        keep = ((s_plus >= lo) & (s_plus <= hi) & (s_minus >= lo) & (s_minus <= hi))
        step_cut = float(np.abs(albedo_at(x[keep], s_plus[keep])
                                - albedo_at(x[keep], s_minus[keep])).max(axis=1).max())
        ctl_max = 0.0
        for _ in range(controls):
            # same x grid, same normals, same separation: only the location along s moves
            room = np.maximum(0.0, (hi - lo) - 2.0 * offset - span * 0.05)
            base = lo + 0.05 * span + offset + ctl_rng.uniform(0.0, 1.0, size=n) * room
            cp, cm = base + offset * normal, base - offset * normal
            good = (cp >= lo) & (cp <= hi) & (cm >= lo) & (cm <= hi)
            if not np.any(good):
                continue
            step = float(np.abs(albedo_at(x[good], cp[good])
                                - albedo_at(x[good], cm[good])).max(axis=1).max())
            ctl_max = max(ctl_max, step)
        rows.append({
            "separation_mm": 2 * offset, "n_cut_pairs": int(keep.sum()),
            "step_cut": step_cut, "slope_cut_per_mm": step_cut / (2 * offset),
            "step_control_max": ctl_max, "slope_control_per_mm": ctl_max / (2 * offset),
            "ratio_cut_to_control": (step_cut / ctl_max) if ctl_max > 0 else None,
        })
        _save(data)
        print(f"[paired] {family} h={2*offset:.4f}: cut={step_cut:.6f} ctl={ctl_max:.6f} "
              f"ratio={rows[-1]['ratio_cut_to_control']}")
    entry = data["families"].setdefault(family, {})
    entry["paired_control"] = {
        "n_controls_per_separation": controls,
        "rows": rows,
        "max_ratio_cut_to_control": max((r["ratio_cut_to_control"] or 0.0) for r in rows),
        "detail": "identical operator (same x positions, same curve normals, same separation) "
                  "evaluated away from the synthetic curve; the cut must not be steeper than "
                  "the field itself is at that scale",
    }
    _save(data)


def stage_perpair(data: dict[str, Any], family: str, n: int = 96, controls: int = 8,
                  margin: float = 0.05):
    """Per-pair paired test: can any cut pair be steeper than the field at the same x?"""
    built = build_family(family)
    region, albedo_at = built["region"], built["albedo_at"]
    x, curve, normal = _curve_pairs(built, n)
    lo, hi = float(region["s_min_mm"]), float(region["s_max_mm"])
    span = hi - lo
    ctl_rng = np.random.default_rng(20260101)
    rows = []
    for offset in (0.5, 0.25, 0.125):
        h = 2 * offset
        s_plus, s_minus = curve + offset * normal, curve - offset * normal
        keep = ((s_plus >= lo) & (s_plus <= hi) & (s_minus >= lo) & (s_minus <= hi))
        xk, nk = x[keep], normal[keep]
        step_cut = np.abs(albedo_at(xk, s_plus[keep]) - albedo_at(xk, s_minus[keep])).max(axis=1)
        ctl = np.zeros((xk.size, controls))
        for j in range(controls):
            room = max(0.0, span - h - 0.05 * span)
            base = lo + 0.05 * span + offset + ctl_rng.uniform(0.0, 1.0, size=xk.size) * room
            cp, cm = base + offset * nk, base - offset * nk
            good = (cp >= lo) & (cp <= hi) & (cm >= lo) & (cm <= hi)
            vals = np.zeros(xk.size)
            if np.any(good):
                vals[good] = np.abs(albedo_at(xk[good], cp[good])
                                    - albedo_at(xk[good], cm[good])).max(axis=1)
            ctl[:, j] = vals
        ctl_max = ctl.max(axis=1)
        allowed = ctl_max * (1.0 + margin)
        viol = step_cut > allowed
        rows.append({
            "separation_mm": h, "n_pairs": int(xk.size),
            "n_violations": int(viol.sum()),
            "worst_ratio": float((step_cut / np.maximum(ctl_max, 1e-12)).max()),
            "step_cut_max": float(step_cut.max()), "control_max": float(ctl_max.max()),
        })
        _save(data)
        print(f"[perpair] {family} h={h:.4f}: viol={int(viol.sum())}/{int(xk.size)} "
              f"worst_ratio={rows[-1]['worst_ratio']:.4f}")
    entry = data["families"].setdefault(family, {})
    entry["per_pair_control"] = {
        "margin": margin, "n_controls_per_pair": controls, "rows": rows,
        "total_violations": int(sum(r["n_violations"] for r in rows)),
        "detail": "each cut pair is compared with the field's own step at the same x, normal "
                  "and separation, sampled at control offsets along s",
    }
    _save(data)


def stage_inherit(data: dict[str, Any], family: str, band_mm: float = 5.0, azimuth_deg: float = 0.0):
    """Plan 9.6 clause 3: do points on both sides of a real cut query the *original* field?

    A plane through the vessel axis is a real cut of the kind the plane fracture backend
    makes.  Mother vertices inside the +-band around it are split into the two sides; each
    side is queried twice: through the fragment-facing path (``api.evaluate``: world mm ->
    chart -> field, with the surface tag / legal-region weight) and through the audit's own
    field path.  Plan 9.6 asks for "source inheritance and colour": the two paths must agree.
    """
    from synlab.patterns.api import evaluate
    from synlab.patterns.charts import (region_weight, resolve_frame, tag_index, to_chart_mm,
                                        vertex_surface_tags)

    built = build_family(family)
    mother, region, frame = built["mother"], built["region"], built["frame"]
    verts = np.asarray(mother.mesh.vertices, dtype=np.float64)
    tags = np.asarray(vertex_surface_tags(mother), dtype=np.int64)
    tag = int(tag_index(mother, str(region["surface_tag"])))
    on_tag = tags == tag
    angle = math.radians(azimuth_deg)
    n = np.array([-math.sin(angle), math.cos(angle), 0.0])
    signed = verts @ n
    band = np.abs(signed) <= band_mm
    pts = verts[on_tag & band]
    side = signed[on_tag & band] >= 0.0
    x_mm, s_mm = to_chart_mm(frame, pts)
    weight = region_weight(frame, pts, x_mm, s_mm, region)
    interior = weight >= 1.0 - 1e-12
    result: dict[str, Any] = {
        "cut": {"kind": "plane_through_axis", "azimuth_deg": azimuth_deg, "band_mm": band_mm},
        "n_candidate": int(pts.shape[0]), "n_interior": int(interior.sum()),
        "n_side_plus": int((side & interior).sum()), "n_side_minus": int((~side & interior).sum()),
    }
    if int(interior.sum()) < 16:
        result["status"] = "NOT_RUN"
        result["reason"] = "too few interior outer-wall vertices inside the cut band"
        data["families"].setdefault(family, {})["fragment_path_inheritance"] = result
        _save(data)
        print(f"[inherit] {family}: NOT_RUN n_interior={int(interior.sum())}")
        return
    sel = interior
    channels = evaluate(built["recipe"], mother, pts[sel], tag)
    fragment_albedo = np.asarray(channels.albedo, dtype=np.float64)
    mother_albedo = built["albedo_at"](x_mm[sel], s_mm[sel])
    diff = np.abs(fragment_albedo - mother_albedo)
    side_sel = side[sel]
    result.update({
        "status": "OK",
        "bit_identical": bool(np.array_equal(fragment_albedo, mother_albedo)),
        "max_abs_diff": float(diff.max()),
        "max_abs_diff_side_plus": float(diff[side_sel].max()) if np.any(side_sel) else None,
        "max_abs_diff_side_minus": float(diff[~side_sel].max()) if np.any(~side_sel) else None,
        "pattern_region_side_plus_fraction": float(np.mean(
            np.asarray(channels.pattern_region)[side_sel] > 0)) if np.any(side_sel) else None,
        "pattern_region_side_minus_fraction": float(np.mean(
            np.asarray(channels.pattern_region)[~side_sel] > 0)) if np.any(~side_sel) else None,
        "definition": "fragment-facing api.evaluate(...) vs the frozen recipe field at the same "
                      "chart coordinates, on both sides of a plane cut through the real mother",
    })
    data["families"].setdefault(family, {})["fragment_path_inheritance"] = result
    _save(data)
    print(f"[inherit] {family}: interior={int(interior.sum())} "
          f"(+{int((side & interior).sum())}/-{int((~side & interior).sum())}) "
          f"bit_identical={result['bit_identical']} max_abs_diff={result['max_abs_diff']:.3e}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", required=True,
                        choices=["repro", "sweep", "control", "refine", "paired", "perpair",
                                 "inherit"])
    parser.add_argument("--family", default=None)
    parser.add_argument("--levels", type=int, default=4)
    args = parser.parse_args()
    families = [args.family] if args.family else list(FAMILIES)
    data = _load()
    for family in families:
        if args.stage == "repro":
            stage_repro(data, family)
        elif args.stage == "sweep":
            stage_sweep(data, family, args.levels)
        elif args.stage == "control":
            stage_control(data, family)
        elif args.stage == "refine":
            stage_refine(data, family)
        elif args.stage == "paired":
            stage_paired(data, family)
        elif args.stage == "perpair":
            stage_perpair(data, family)
        elif args.stage == "inherit":
            stage_inherit(data, family)
    _save(data)
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
