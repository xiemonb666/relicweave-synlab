"""Step 13 (post-fix): audit ONE vessel with the P1+P2 geometry and write one JSON part.

Usage:  python s13_audit_vessel_fixed.py <VID> [--out DIR]

Same measurement code path as ``mother_geometry_audit/s03_audit_vessel.py`` (same seed, same
prototype parameters) so every number is directly comparable with the pre-fix audit; only the
output directory differs so the pre-fix baseline is never overwritten.

One process per vessel on purpose: a heavy vessel cannot take the whole sweep down.
"""
from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
DEFAULT_OUT = HERE / "parts"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "mother_geometry_audit"))

from mga_lib import (SHELL_TARGET_KEY, component_report, declared_z_extent,  # noqa: E402
                     gaps_between_components, jsonable, silhouette, silhouette_points,
                     wall_taper)

from synlab.mothers.api import (audit_mother, create_mother, default_params,  # noqa: E402
                                vessel_entry)


def main(argv: list[str]) -> int:
    vessel_id = argv[1]
    out_dir = DEFAULT_OUT
    if "--out" in argv:
        out_dir = Path(argv[argv.index("--out") + 1])
    real_params: dict | None = None
    for arg in argv[2:]:
        if arg.startswith("{"):
            real_params = json.loads(arg)
    params = real_params or default_params(vessel_id)
    entry = vessel_entry(vessel_id)

    row: dict = {
        "vessel_id": vessel_id,
        "vessel_name": entry.name,
        "registry_version": entry.version,
        "family": str((entry.applicable or {}).get("family", "")),
        "builder": entry.meta.get("builder_name", ""),
        "params_source": "batch store (real lineage params)" if real_params else "registry defaults",
        "params": jsonable(params),
    }
    started = time.time()
    try:
        # local import: the seed helper lives with the pre-fix audit scripts
        from synlab.seeds import make_rng, seed64
        rng = make_rng(int(seed64(0xA12, vessel_id, "mother_geometry_audit")), vessel_id, "audit")
        mother = create_mother(vessel_id, "M01", dict(params), rng,
                               mother_id=f"{vessel_id}-audit-fixed")
        meta = dict(mother.meta or {})
        pm = dict(meta.get("profile_metrics") or {})
        mesh = mother.mesh

        declared, declared_source = declared_z_extent(vessel_id, params)
        target = pm.get(SHELL_TARGET_KEY)
        if target is not None:
            declared = float(target)
            declared_source = "profile_metrics.z_rim_target_mm (common.shell_profile)"

        comps = component_report(mesh)
        bounds = np.asarray(mesh.bounds, dtype=np.float64)
        report = audit_mother(mother, max_thickness_probes=320, run_self_intersection=True)

        axis_parts = [c for c in comps if c["contains_axis"]]
        body = min(axis_parts or comps, key=lambda c: c["z_min"]) if comps else None
        gaps = gaps_between_components(comps)
        body_top = float(body["z_max"]) if body else float("nan")
        body_extent = float(body["z_extent_mm"]) if body else float("nan")
        profile_z_rim = pm.get("z_rim")
        r_max = pm.get("r_max")
        top_ratio = None
        if body is not None:
            verts = np.asarray(mesh.vertices, dtype=np.float64)
            r = np.hypot(verts[:, 0], verts[:, 1])
            in_body = (verts[:, 2] >= body["z_min"] - 1e-6) & (verts[:, 2] <= body["z_max"] + 1e-6)
            if np.any(in_body):
                z_in = verts[in_body, 2]
                r_in = r[in_body]
                lo, hi = float(z_in.min()), float(z_in.max())
                cut = hi - 0.10 * max(hi - lo, 1e-9)
                top_r = float(r_in[z_in >= cut].max()) if np.any(z_in >= cut) else float("nan")
                top_ratio = top_r / max(float(r_in.max()), 1e-9)
            body_sil = silhouette_points(verts[in_body]) if np.any(in_body) else {}
            body_taper = wall_taper(body_sil)
        else:
            body_sil, body_taper = {}, {}

        row.update({
            "status": "OK",
            "seconds": round(time.time() - started, 2),
            "declared_z_extent_mm": declared,
            "declared_source": declared_source,
            "profile_metrics": jsonable({k: v for k, v in pm.items()
                                         if isinstance(v, (int, float, bool))}),
            "mesh": {
                "faces": int(len(mesh.faces)),
                "vertices": int(len(mesh.vertices)),
                "watertight": bool(mesh.is_watertight),
                "volume_mm3": float(mesh.volume),
                "area_mm2": float(mesh.area),
                "bounds_min": [float(v) for v in bounds[0]],
                "bounds_max": [float(v) for v in bounds[1]],
                "bbox_mm": [float(bounds[1][i] - bounds[0][i]) for i in range(3)],
                "z_min": float(bounds[0][2]),
                "z_max": float(bounds[1][2]),
                "n_bodies": int(len(comps)),
            },
            "body": {
                "z_min": body["z_min"] if body else None,
                "z_max": body_top,
                "z_extent_mm": body_extent,
                "volume_mm3": body["volume_mm3"] if body else None,
                "faces": body["faces"] if body else None,
                "r_max_mm": body["r_max_mm"] if body else None,
                "top_over_max_radius_ratio": top_ratio,
                "profile_z_rim": profile_z_rim,
                "profile_r_max": r_max,
                "body_shortfall_mm": (float(declared) - body_top) if declared is not None else None,
                "extent_shortfall_mm": (float(declared) - body_extent)
                if declared is not None and np.isfinite(body_extent) else None,
                "profile_shortfall_mm": (float(declared) - float(profile_z_rim))
                if (declared is not None and profile_z_rim is not None) else None,
            },
            "max_positive_gap_mm": max([g["gap_mm"] for g in gaps], default=0.0),
            "body_silhouette": body_sil,
            "body_wall_taper": body_taper,
            "components": comps,
            "component_gaps": gaps,
            "silhouette": silhouette(mesh, bins=12),
            "audit": {
                "ok": bool(report.get("ok")),
                "state": report.get("state"),
                "failures": jsonable(report.get("failures") or []),
                "metrics": jsonable(report.get("metrics") or {}),
                "check_ok": {k: v.get("ok") for k, v in (report.get("checks") or {}).items()},
                "thickness_min_mm": (report.get("checks", {}).get("min_thickness", {}) or {}).get("min_mm"),
                "void_ratio": (report.get("metrics") or {}).get("void_ratio"),
                "bodies": (report.get("checks", {}).get("watertight", {}) or {}).get("bodies"),
                "genus": (report.get("metrics") or {}).get("genus"),
            },
            "geometry_hash": report.get("geometry_hash"),
        })
        if declared is not None:
            row["shortfall_mm"] = float(declared) - float(bounds[1][2])
    except Exception as exc:  # reported as data, never swallowed
        code = getattr(getattr(exc, "code", None), "value", None) or getattr(exc, "code", None)
        row.update({
            "status": "RAISED",
            "seconds": round(time.time() - started, 2),
            "error_type": type(exc).__name__,
            "error_code": str(code) if code is not None else None,
            "stage": getattr(exc, "stage", None),
            "measurements": jsonable(dict(getattr(exc, "measurements", None) or {})),
            "error": str(exc)[:2000],
            "traceback": traceback.format_exc()[-3000:],
        })
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{vessel_id}.json").write_text(
        json.dumps(jsonable(row), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(f"{vessel_id}: status={row['status']} seconds={row['seconds']}")
    if row["status"] == "OK":
        print(f"   declared={row.get('declared_z_extent_mm')} z_max={row['mesh']['z_max']:.2f} "
              f"shortfall={row.get('shortfall_mm')} bodies={row['mesh']['n_bodies']} "
              f"vol={row['mesh']['volume_mm3']:.1f} audit_ok={row['audit']['ok']} "
              f"failures={[f.get('check') for f in row['audit']['failures']]}")
    else:
        print(f"   {row.get('error_code')} {row.get('error')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
