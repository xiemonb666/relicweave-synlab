"""Decompose rejected run04 volume error using its exact source-face identities."""
from pathlib import Path
import hashlib
import json
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "vesselforge/src"))
from vesselforge.revolved_profile import MeridianSegment


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    source = ROOT / "vesselforge/experiments/continuation_20261015/reference_forms/outputs/daily_aberdeen_108x53_v6_final/geometry"
    diagnostic = ROOT / "vesselforge/experiments/continuation_20261016/reference_v6_tetra/run04/failed_geometry_not_for_simulation/FAILED_GEOMETRY_NOT_FOR_SIMULATION.npz"
    a = np.load(diagnostic, allow_pickle=False)
    assert np.all(a["exterior_ancestry_exact"])
    section = json.loads((source / "section.json").read_text())
    lineage = json.loads((source / "face_lineage.json").read_text())["faces"]
    xi, wi = np.polynomial.legendre.leggauss(128)
    tt, ww = (xi + 1) / 2, wi / 2
    cad_v, cad_a = [], []
    for row in section["segments"]:
        seg = MeridianSegment(role=row["role"], kind=row["curve"],
                              points=tuple(tuple(p) for p in row["points_rz_mm"]))
        p = np.array([seg.point(float(t)) for t in tt])
        d = np.array([seg.derivative(float(t)) for t in tt])
        # Meridian goes axis->inside->rim->outside->foot->axis. Its outward
        # revolution normal is proportional to (-z',0,r') at theta=0.
        cad_v.append(2*np.pi/3 * np.sum(ww*p[:, 0]*(p[:, 1]*d[:, 0]-p[:, 0]*d[:, 1]))*1e-9)
        cad_a.append(2*np.pi*np.sum(ww*p[:, 0]*np.linalg.norm(d, axis=1))*1e-6)
    cad_v, cad_a = np.asarray(cad_v), np.asarray(cad_a)
    tri = a["nodes_m"][a["exterior_triangles"]]
    mesh_v = np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2]))/6
    mesh_a = np.linalg.norm(np.cross(tri[:, 1]-tri[:, 0], tri[:, 2]-tri[:, 0]), axis=1)/2
    assert abs(mesh_v.sum() - a["volume_m3"].sum()) < 1e-15
    rows = []
    for key, rec in lineage.items():
        fid = f"original-brep-face-{int(key):03d}"
        mask = a["exterior_source_face_ids"] == fid
        assert mask.any()
        ids = rec["source_segment_indices"]
        cv, ca = float(cad_v[ids].sum()), float(cad_a[ids].sum())
        mv, ma = float(mesh_v[mask].sum()), float(mesh_a[mask].sum())
        rows.append({"fid": fid, "role": rec["role"], "segment_indices": ids,
                     "cad_surface_volume_contribution_m3": cv,
                     "mesh_surface_volume_contribution_m3": mv,
                     "volume_contribution_error_m3": mv-cv,
                     "cad_area_m2": ca, "mesh_area_m2": ma,
                     "relative_area_error": (ma-ca)/ca})
    rows.sort(key=lambda row: abs(row["volume_contribution_error_m3"]), reverse=True)
    residual = float(mesh_v.sum()-cad_v.sum())
    assert abs(sum(row["volume_contribution_error_m3"] for row in rows)-residual) < 1e-15
    report = {"status": "REJECTED_MESH_SURFACE_ERROR_DIAGNOSTIC",
              "source_section_sha256": sha(source / "section.json"),
              "source_lineage_sha256": sha(source / "face_lineage.json"),
              "failed_mesh_npz_sha256": sha(diagnostic),
              "origin_m": [0, 0, 0],
              "cad_volume_m3": float(cad_v.sum()), "mesh_volume_m3": float(mesh_v.sum()),
              "signed_volume_error_m3": residual,
              "relative_volume_error": abs(residual)/cad_v.sum(),
              "per_fid": rows,
              "scope": "Divergence theorem at a declared origin; per-face signed contributions depend on origin, their sum does not. Failed mesh remains excluded from simulation. No gate changed."}
    with Path(__file__).with_suffix(".json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
