"""Scratch probe 43: is the planar-cut ambiguity real, and does the sampling density drive it?"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402


def run(sample_target: int) -> None:
    from synlab.fracture.booleans import boolean_difference, boolean_intersection, tag_source
    from synlab.fracture.cut import build_basis, build_closed_cutter, make_height_field
    from synlab.fracture.event import run_shared_cut
    from synlab.fracture.spec import FractureSpec
    from synlab.schemas.runtime import CutterResult
    import trimesh

    from tests.a12.fracture.fixtures import box_mother

    mother = box_mother((12.0, 12.0, 12.0), mother_id="box12")
    basis = build_basis(np.asarray(mother.mesh.vertices), np.array([1.0, 0.0, 0.0]),
                        anchor=np.zeros(3), basis_id="x")
    height = make_height_field(basis, np.random.default_rng(1), target_rms_mm=0.0)
    mesh, report = build_closed_cutter(basis, height, error_budget_mm=0.01)
    cutter = CutterResult(mesh=mesh, basis=basis, h_fn=height.__call__,
                          requested_error_mm=0.01,
                          realized_error_mm=report["realized_error_mm"],
                          triangles=int(len(mesh.faces)), meta=dict(report))
    del boolean_difference, boolean_intersection, tag_source, FractureSpec, trimesh
    result = run_shared_cut(mother, cutter, event_id="E1", backend="plane_shared_cut",
                            sample_target=sample_target)
    print(f"--- sample_target={sample_target}: {len(result.interfaces)} patches", flush=True)
    for patch in result.interfaces:
        meta = patch.meta
        print(f"   id={patch.interface_id} area={patch.area_mm2:.4f} "
              f"samples={meta.get('samples')} faces_a={len(meta.get('faces_a', []))} "
              f"amb_samples={meta.get('ambiguous_samples')} "
              f"amb_ratio={patch.ambiguity_area_ratio:.5f} "
              f"bary_min_a={meta.get('bary_min_a'):.3e} "
              f"gap={patch.gap_p95_mm:.3e} ang={patch.normal_angle_p95_deg:.3e}", flush=True)
    print("   audit", {k: v for k, v in result.qa.items()
                       if k in ("volume_rel_diff", "overlap_ratio", "gap_p95_mm_max",
                                "source_coverage", "ambiguous_area_ratio_max", "passed")},
          flush=True)


if __name__ == "__main__":
    for target in (24, 8, 96):
        run(target)
