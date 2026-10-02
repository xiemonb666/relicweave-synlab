"""Scratch probe 41: hand-built clean-truth fixture (no boolean), to learn the real rules."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import trimesh  # noqa: E402

from synlab.schemas.runtime import (  # noqa: E402
    ORIGIN_INTERFACE,
    ORIGIN_MOTHER_SURFACE,
    FractureResult,
    Fragment,
    InterfacePatch,
    RELATION_R2,
    RELATION_R1,
    RELATION_TINY,
    RELATION_UNKNOWN,
)


def half_box(sign: float, *, size: float = 12.0) -> trimesh.Trimesh:
    box = trimesh.creation.box(extents=[size / 2.0, size, size])
    box.apply_translation([sign * size / 4.0, 0.0, 0.0])
    return box


def make_fragment(fragment_id: str, mesh: trimesh.Trimesh, *, side: int,
                  interface_faces: np.ndarray) -> Fragment:
    n = len(mesh.faces)
    origin = np.full(n, ORIGIN_MOTHER_SURFACE, dtype=np.uint8)
    origin[interface_faces] = ORIGIN_INTERFACE
    source = np.arange(n, dtype=np.int32)
    source[interface_faces] = -1
    return Fragment(
        fragment_id=fragment_id, mesh=mesh, volume_mm3=float(abs(mesh.volume)),
        area_mm2=float(mesh.area), face_origin_kind=origin, face_source_tri=source,
        face_interface_id=np.full(n, -1, dtype=np.int32),
        face_side=np.full(n, side, dtype=np.int8), component_id=0,
    )


def shared_plane_patch(a: Fragment, b: Fragment, *, area: float, ambiguity: float,
                       interface_id: int = 0, gap: float = 0.0,
                       angle: float = 0.0) -> InterfacePatch:
    size = 12.0
    grid = np.linspace(-size / 2.0, size / 2.0, 7)
    gx, gy = np.meshgrid(grid, grid, indexing="ij")
    pts = np.column_stack([np.zeros(gx.size), gx.reshape(-1), gy.reshape(-1)])
    ones = np.ones((pts.shape[0], 3), dtype=np.float64)
    return InterfacePatch(
        interface_id=interface_id, fragment_a=a.fragment_id, fragment_b=b.fragment_id,
        area_mm2=float(area), sample_points_a=pts, sample_points_b=pts + np.array([gap, 0, 0]),
        normals_a=ones * np.array([-1.0, 0.0, 0.0]),
        normals_b=ones * np.array([1.0, 0.0, 0.0]),
        gap_p95_mm=float(gap), normal_angle_p95_deg=float(angle),
        ambiguity_area_ratio=float(ambiguity), ambiguous_area_mm2=float(area * ambiguity),
        meta={"source_triangles": [0], "samples": int(pts.shape[0]),
              "faces_a": [0], "faces_b": [0]},
    )


def main() -> None:
    from synlab.truth.api import finalize_clean_truth, relation_audit, truth_summary

    print("ORIGIN_INTERFACE =", ORIGIN_INTERFACE, "ORIGIN_MOTHER_SURFACE =", ORIGIN_MOTHER_SURFACE)
    from tests.a12.fracture.fixtures import box_mother
    mother = box_mother((12.0, 12.0, 12.0), mother_id="box12")
    outer = np.asarray(mother.mesh.face_normals, dtype=np.float64)
    inner = np.where(np.abs(outer[:, 0]) > 0.5)[0]

    left = half_box(1.0)
    right = half_box(-1.0)
    lf = np.where(np.abs(np.asarray(left.face_normals)[:, 0] + 1.0) < 1e-9)[0]
    rf = np.where(np.abs(np.asarray(right.face_normals)[:, 0] - 1.0) < 1e-9)[0]
    fa = make_fragment("A", left, side=-1, interface_faces=lf)
    fb = make_fragment("B", right, side=1, interface_faces=rf)
    del inner
    patch = shared_plane_patch(fa, fb, area=144.0, ambiguity=0.0)
    result = FractureResult(fragments=[fa, fb], interfaces=[patch], event_tree={"event_id": "E1"},
                            debris=[], parent_id="box12", backend="plane_shared_cut", qa={},
                            meta={"correspondence": []})
    truth = finalize_clean_truth(mother, result)
    audit = relation_audit(truth)
    print("summary", truth_summary(truth))
    print("audit ok", audit.get("ok"), "failures", audit.get("failures"))
    for pair, edge in sorted(truth.relations.items()):
        if pair[0] < pair[1]:
            print("  ", pair, edge.kind, "area", round(edge.area_mm2, 4), "valid", edge.valid,
                  "reason", edge.reason)
    print("patch evidence",
          {k: v for k, v in (truth.qa.get("patch_evidence") or {}).items()}
          if isinstance(truth.qa.get("patch_evidence"), dict) else truth.qa.get("checks"))
    print("relation constants", RELATION_R2, RELATION_R1, RELATION_TINY, RELATION_UNKNOWN)


if __name__ == "__main__":
    main()
