"""Stage-1 probe: does warp_voronoi_cut produce >2 pieces on a real mother, and how long?"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "data" / "a12_reports" / "_fcal_probe1.json"


def main() -> int:
    from synlab.mothers.api import create_mother, default_params, ensure_registered
    from synlab.mothers.measure import thickness_samples
    from synlab.fracture.impact import BodyStats, MaterialStats, target_piece_count
    from synlab.fracture.physics import load_physics_config
    from synlab.fracture.voronoi_event import run_voronoi_event
    from synlab.fracture.voronoi_frag import build_partition
    from synlab.errors import SynLabError

    ensure_registered()
    cfg = load_physics_config()
    report: dict = {"config_hash": cfg.hash, "u_ref_j": cfg.impact.u_ref_j, "rows": []}
    OUT.write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")

    vessel, mid = "V01", "M01"
    mother = create_mother(vessel, mid, default_params(vessel), np.random.default_rng(20261002))
    mesh = mother.mesh
    th = thickness_samples(mesh, np.arange(len(mesh.faces)), max_probes=320)
    body = BodyStats(
        vessel_id=vessel, volume_mm3=float(abs(mesh.volume)), area_mm2=float(mesh.area),
        extents_mm=tuple(float(x) for x in mesh.extents),
        thickness_min_mm=float(th.get("min_mm", 0.0) or 0.0),
        thickness_p05_mm=float(th.get("p05_mm", 0.0) or 0.0),
        thickness_median_mm=float(th.get("median_mm", 0.0) or 0.0),
        thickness_max_mm=float(th.get("max_mm", 0.0) or 0.0),
    )
    material = MaterialStats(material_id=mid, density_g_cm3=2.2, porosity=0.2, grain_size_mm=0.05)
    rec = target_piece_count(body, material, cfg.impact, rng=np.random.default_rng(20261002),
                             drop_height_mm=500.0)
    report["body"] = body.as_dict()
    report["count_model"] = rec

    for target in (None, 8, 32):
        row: dict = {"target_pieces": target}
        try:
            t0 = time.perf_counter()
            result = run_voronoi_event(
                mother, event_id=f"P1-{vessel}-{target}", config=cfg,
                rng=np.random.default_rng(20261002), body=body, material=material,
                target_pieces=target)
            row["seconds_total"] = round(time.perf_counter() - t0, 3)
            row["pieces"] = len(result.fragments)
            row["interfaces"] = len(result.interfaces)
            row["faces_total"] = int(result.meta["faces_total"])
            row["qa_passed"] = bool(result.qa.get("passed"))
            row["qa"] = {k: v for k, v in result.qa.items() if k != "failures"}
            row["failures"] = list(result.qa.get("failures", []))
            row["unmatched_ratio"] = result.meta.get("unmatched_interface_area_ratio")
            conj = result.meta.get("facet_conjugacy", {})
            row["conjugacy"] = conj
        except SynLabError as exc:
            row["error"] = f"{exc.code}: {exc.message}"
            row["measurements"] = {k: v for k, v in (exc.measurements or {}).items()}
        except BaseException as exc:  # noqa: BLE001
            row["error"] = f"{type(exc).__name__}: {exc}"
        report["rows"].append(row)
        OUT.write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
        print("row:", json.dumps(row, default=str)[:400], flush=True)

    # stage timing probes: partition alone, then one cell mesh
    n = report["count_model"]["n_physical"]
    t0 = time.perf_counter()
    partition, seed_report = build_partition(mesh, int(n), rng=np.random.default_rng(20261002),
                                            seed_cfg=cfg.seeds, padding_mm=2.0)
    report["partition_seconds"] = round(time.perf_counter() - t0, 3)
    report["partition_cells"] = len(partition.cells)
    t0 = time.perf_counter()
    from synlab.fracture.voronoi_event import _displaced_cell_mesh

    face_counts = []
    for cell in partition.cells:
        cm = _displaced_cell_mesh(cell, {}, refinement=cfg.roughness.facet_refinement,
                                  refine_mm=cfg.roughness.facet_refine_mm)
        face_counts.append(int(len(np.asarray(cm.faces))))
    report["cell_mesh_seconds"] = round(time.perf_counter() - t0, 3)
    report["cell_faces_total"] = int(sum(face_counts))
    report["seed_report_keys"] = sorted(seed_report.keys())
    OUT.write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    print("partition", report["partition_seconds"], "s cells", report["partition_cells"],
          "cellmesh", report["cell_mesh_seconds"], "s faces", report["cell_faces_total"],
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
