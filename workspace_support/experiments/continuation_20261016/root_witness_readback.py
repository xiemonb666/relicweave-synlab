"""Independent source-quadrature and recorded-history check of v15 CAD evidence.

This does not repeat the OCC operation or qualify later meshing/physics.
"""
from pathlib import Path
import hashlib
import json
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "vesselforge/src"))
from vesselforge.revolved_profile import MeridianSegment


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def integrate(segments, order):
    xi, wi = np.polynomial.legendre.leggauss(order)
    t, w = (xi + 1) / 2, wi / 2
    areas, cross, volume = [], 0.0, 0.0
    for seg in segments:
        p = np.asarray([seg.point(float(v)) for v in t])
        d = np.asarray([seg.derivative(float(v)) for v in t])
        areas.append(float(2 * np.pi * np.sum(w * p[:, 0] * np.linalg.norm(d, axis=1))))
        cross += float(np.sum(w * p[:, 0] * d[:, 1]))
        volume += float(np.sum(w * p[:, 0] ** 2 * d[:, 1]))
    return np.asarray(areas), 2 * abs(cross), np.pi * abs(volume)


def main():
    evidence = ROOT / "vesselforge/experiments/continuation_20261015/named_step/daily_witness_probe_20261016_v15"
    r = json.loads((evidence / "receipt.json").read_text())
    asset = ROOT / r["source_asset_relative_path"]
    for name, digest in r["source_hashes"].items():
        path = asset / name if name == "geometry_report.json" else asset / "geometry" / name
        assert sha(path) == digest, name
    assert sha(r["executed_probe_source_path"]) == r["executed_probe_source_sha256"]
    assert sha(evidence / "daily_native_named.step") == r["native_body_step_sha256"]
    assert sha(evidence / "witness_manifest.json") == r["native_face_witness_manifest_sha256"]
    assert sha(evidence / "native_face_identity.json") == r["native_face_identity_sha256"]
    manifest = r["native_face_witness_manifest"]
    for row in manifest["witnesses"]:
        assert sha(row["witness_path"]) == row["witness_sha256"]

    section = json.loads((asset / "geometry/section.json").read_text())
    segments = [MeridianSegment(role=v["role"], kind=v["curve"],
                   points=tuple(tuple(p) for p in v["points_rz_mm"]))
                for v in section["segments"]]
    a64, cut64, vol64 = integrate(segments, 64)
    a128, cut128, vol128 = integrate(segments, 128)
    assert np.allclose(a64, a128, rtol=1e-11, atol=1e-10)
    assert abs(cut64 - cut128) < 1e-9 and abs(vol64 - vol128) < 1e-7
    lineage = json.loads((asset / "geometry/face_lineage.json").read_text())
    by_id = {row["source_face_id"]: row for row in manifest["witnesses"]}
    area_errors = []
    for fid, rec in lineage["faces"].items():
        row = by_id[f"original-brep-face-{int(fid):03d}"]
        assert row["role"] == rec["role"]
        area = float(a128[np.asarray(rec["source_segment_indices"], dtype=int)].sum())
        err = abs(area - row["native_face_area_mm2"]) / area
        area_errors.append(err)
        assert err < 1e-9, (fid, err)

    imprint = r["witness_imprint"]
    cut = r["plane_cut_and_composed_ancestry"]
    exterior = set(cut["exterior_surface_tags"])
    interface = set(cut["cut_plane"]["interface_surface_tags"])
    mapped = {int(k): v for k, v in cut["composed_source_by_exterior_surface"].items()}
    assert set(mapped) == exterior and not set(mapped) & interface
    assert set(mapped.values()) == set(by_id)
    raw = cut["raw_witness_surface_parent_map_rows"]
    ancestry = {}
    for row in raw:
        desc = row["raw_parent_map_descendants"]
        assert desc and all(d["dim"] == 2 for d in desc)
        tags = [d["tag"] for d in desc]
        assert len(tags) == len(set(tags)) and set(tags) <= exterior
        for tag in tags:
            ancestry.setdefault(tag, []).append(row["source_face_id"])
    assert set(ancestry) == exterior
    assert all(len(v) == 1 and v[0] == mapped[k] for k, v in ancestry.items())
    plane = {d["tag"] for d in cut["raw_plane_parent_map"]}
    assert interface <= plane and not interface & set(ancestry)
    cut_area_error = abs(cut["interface_area_m2"] - cut128 * 1e-6) / (cut128 * 1e-6)
    area_tolerance = r["declared_occ_tolerances"]["surface_area_relative"]
    assert cut_area_error < area_tolerance
    assert abs(imprint["input_body_volume_m3"] - vol128 * 1e-9) / (vol128 * 1e-9) < 1e-9
    assert abs(sum(cut["cut_volume_m3"]) - vol128 * 1e-9) / (vol128 * 1e-9) < 1e-6
    assert all(v["status"] == "PASS_REJECTED" for v in r["negative_witness_controls"]["controls"])
    report = {
        "status": "INDEPENDENT_SOURCE_QUADRATURE_AND_RECORDED_ANCESTRY_PASS",
        "receipt_sha256": sha(evidence / "receipt.json"),
        "source_step_sha256": r["source_hashes"]["solid.step"],
        "named_step_sha256": r["native_body_step_sha256"],
        "quadrature_orders": [64, 128],
        "source_surface_area_mm2": float(a128.sum()),
        "maximum_native_face_area_relative_error_vs_source_quadrature": max(area_errors),
        "source_volume_mm3": vol128,
        "source_complete_central_cut_area_mm2": cut128,
        "occ_cut_area_relative_error_vs_source_quadrature": cut_area_error,
        "cut_area_comparison_relative_tolerance": area_tolerance,
        "exterior_surfaces": len(exterior),
        "source_faces": len(by_id),
        "raw_map_exclusive_coverage_verified": True,
        "scope": "Independent source-curve quadrature, hashes and receipt raw-map arithmetic; OCC operation not rerun; no mesh, material, fracture or specimen fidelity qualification.",
    }
    target = Path(__file__).with_suffix(".json")
    with target.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
