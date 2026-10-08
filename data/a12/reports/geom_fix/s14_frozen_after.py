"""Step 14 (post-fix): replay the FROZEN batch lineages with the P1+P2 geometry.

Identical to ``mother_geometry_audit/s04_frozen_repro.py`` (same params, same seed
``make_rng(0xA12, <lineage>, "audit")``, same measurement helpers) so the numbers line up with

* ``s04_frozen_repro.json``  - the measured **pre-fix** state, and
* ``s11_fix_simulation.json`` - the **simulated** post-fix state (in-process monkeypatch).

Writes ``geom_fix/s14_frozen_after.json``; it never touches the pre-fix evidence files.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "mother_geometry_audit"))

from mga_lib import component_report, gaps_between_components, jsonable, silhouette  # noqa: E402

from synlab.mothers.api import audit_mother, create_mother  # noqa: E402
from synlab.seeds import make_rng  # noqa: E402

REAL = {
    "LIN0004_V10_M06_PAT03": ("V10", {
        "base_mm": 10.649771173028173, "belly_ratio": 0.68991973127168,
        "diameter_mm": 222.77854733012697, "height_mm": 352.12756141776987,
        "knob_diameter_mm": 64.43440084462063, "lid_height_ratio": 0.568826035425881,
        "lid_seat_mm": 3.3710449924909853, "mouth_ratio": 0.30098125744230925,
        "wall_mm": 2.8443414248422236, "warp_amplitude": 0.016873063698682116,
        "warp_eccentricity_mm": 1.848518300460957, "warp_lobes": 2}),
    "LIN0000_V10_M11_PAT15": ("V10", {
        "base_mm": 16.25640284535809, "belly_ratio": 1.342951572929974,
        "diameter_mm": 243.40045346124103, "height_mm": 205.7264438423038,
        "knob_diameter_mm": 17.718809719300232, "lid_height_ratio": 0.34308726483786,
        "lid_seat_mm": 13.062273097916366, "mouth_ratio": 0.947908125947771,
        "wall_mm": 9.7008674906311, "warp_amplitude": 0.022576087632897448,
        "warp_eccentricity_mm": 1.4913959072464065, "warp_lobes": 2}),
    "LIN0006_V09_M09_PAT03": ("V09", {
        "base_mm": 15.158553801891568, "belly_ratio": 1.1161788491776976,
        "diameter_mm": 262.5068873811831, "handle_span_ratio": 0.9508241451705133,
        "height_mm": 294.88495327061656, "neck_ratio": 0.40728578426690004,
        "spout_angle_deg": 16.752630179838093, "spout_bore_mm": 28.26905787271389,
        "spout_length_mm": 87.82286120683884, "wall_mm": 8.29251376441934,
        "warp_amplitude": 0.012910494651944234, "warp_eccentricity_mm": 0.22546127956209078,
        "warp_lobes": 2}),
    "LIN0014_V16_M07_PAT10": ("V16", {
        "base_mm": 8.16478352807982, "belly_ratio": 0.7058423758393259,
        "diameter_mm": 235.75435316131734, "foot_count": 5,
        "foot_height_mm": 96.41921641393304, "height_mm": 265.4053512410892,
        "shoulder_ratio": 0.36401622797259525, "vent_count": 11,
        "vent_diameter_mm": 29.760870991711116, "wall_mm": 5.432194146934794,
        "warp_amplitude": 0.029918694893006234, "warp_eccentricity_mm": 0.07738022154521806,
        "warp_lobes": 2}),
}


def main() -> int:
    out: dict = {}
    for lineage, (vessel_id, params) in REAL.items():
        rng = make_rng(0xA12, lineage, "audit")
        try:
            mother = create_mother(vessel_id, "M01", dict(params), rng, mother_id=lineage)
        except Exception as exc:
            print(f"{lineage}: RAISED {type(exc).__name__}: {exc}")
            out[lineage] = {"status": "RAISED", "error": f"{type(exc).__name__}: {exc}"}
            continue
        pm = dict((mother.meta or {}).get("profile_metrics") or {})
        comps = component_report(mother.mesh)
        gaps = gaps_between_components(comps)
        report = audit_mother(mother, max_thickness_probes=64, run_self_intersection=False)
        declared = float(pm.get("z_rim_target_mm", float("nan")))
        body = min(comps, key=lambda c: c["z_min"]) if comps else None
        row = {
            "status": "OK", "vessel_id": vessel_id,
            "registry_version": (mother.meta or {}).get("registry_version"),
            "declared_z_rim_target_mm": declared,
            "profile_z_rim_mm": pm.get("z_rim"),
            "profile_z_bottom_mm": pm.get("z_bottom"),
            "profile_r_max_mm": pm.get("r_max"),
            "z_rim_shortfall_mm": pm.get("z_rim_shortfall_mm"),
            "profile_shortfall_mm": declared - float(pm.get("z_rim", float("nan"))),
            "body_z_max_mm": body["z_max"] if body else None,
            "body_shortfall_mm": declared - float(body["z_max"]) if body else None,
            "components": comps,
            "component_gaps": gaps,
            "max_positive_gap_mm": max([g["gap_mm"] for g in gaps], default=0.0),
            "mesh_volume_mm3": float(mother.mesh.volume),
            "audit_ok": bool(report.get("ok")),
            "audit_failures": [f.get("check") for f in (report.get("failures") or [])],
            "geometry_hash": report.get("geometry_hash"),
            "silhouette": silhouette(mother.mesh, bins=12)["normalised"],
        }
        out[lineage] = jsonable(row)
        print(f"=== {lineage} ({vessel_id}) registry_version="
              f"{(mother.meta or {}).get('registry_version')}")
        print(f"    declared z_rim_target = {declared:.4f}  measured profile z_rim = "
              f"{pm.get('z_rim')}  shortfall = {row['profile_shortfall_mm']:.4f} mm")
        for comp in sorted(comps, key=lambda c: c["z_min"]):
            print(f"    component #{comp['index']}: {comp['faces']:6d} faces  "
                  f"{comp['volume_mm3']:14.3f} mm^3  z=[{comp['z_min']:.2f}, {comp['z_max']:.2f}]")
        print(f"    audit_ok={row['audit_ok']} failures={row['audit_failures']} "
              f"hash={row['geometry_hash']}")
        print(f"    max_positive_gap_mm={row['max_positive_gap_mm']:.4f}")
    (HERE / "s14_frozen_after.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
