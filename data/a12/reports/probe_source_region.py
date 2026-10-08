"""Do the chunks' *source cutter triangles* tile the shared sheet? (read-only probe)

If they do, a plan-30.5 implementation inside ``build_interface`` that collects both sides'
output triangles *per source triangle* (rather than trusting the lossy face pairing) recovers
the full hand-computed 144 mm^2.  The probe wraps ``build_interface`` to capture the cutter mesh
and the source-triangle assignment without changing any production file.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import shapely

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tests" / "a12" / "fracture"))
sys.path.insert(0, str(REPO_ROOT / "tests" / "a12"))

from synlab.fracture import event as event_mod  # noqa: E402
from synlab.fracture import fragment as fragment_mod  # noqa: E402
from synlab.fracture.api import fracture_event  # noqa: E402
from synlab.fracture.spec import FractureSpec  # noqa: E402

from fixtures import box_mother  # noqa: E402

CAPTURED: list[dict] = []
_ORIGINAL = fragment_mod.build_interface


def _wrapped(**kwargs):
    cutter = kwargs["cutter_mesh"]
    source = int(kwargs["source_tri"])
    patch, rows = _ORIGINAL(**kwargs)
    CAPTURED.append({
        "interface_id": int(patch.interface_id),
        "source_tri": source,
        "faces_a": [int(x) for x in kwargs["faces_a"]],
        "faces_b": [int(x) for x in kwargs["faces_b"]],
        "cutter_faces": int(len(np.asarray(cutter.faces))),
        "cutter_centres": np.asarray(cutter.triangles_center, dtype=np.float64),
        "cutter_triangles": np.asarray(cutter.triangles, dtype=np.float64),
    })
    return patch, rows


def main() -> int:
    fragment_mod.build_interface = _wrapped
    event_mod.build_interface = _wrapped
    try:
        mother = box_mother((12.0, 12.0, 12.0), mother_id="box12")
        spec = FractureSpec(backend="plane_shared_cut", plane_point=np.zeros(3),
                            plane_normal=np.array([1.0, 0.0, 0.0]))
        result = fracture_event(mother, spec, np.random.default_rng(4), event_id="E_plane")
    finally:
        fragment_mod.build_interface = _ORIGINAL
        event_mod.build_interface = _ORIGINAL

    by_id = {f.fragment_id: f for f in result.fragments}
    cutter_triangles = CAPTURED[0]["cutter_triangles"]
    rows = []
    for entry in CAPTURED:
        # nearest cutter triangle of every face of this chunk, recomputed the way `_interface_faces`
        # does it (nearest surface point of the face centroid)
        frag_a = by_id[result.interfaces[0].fragment_a]
        frag_b = by_id[result.interfaces[0].fragment_b]
        sources: set[int] = set()
        for fragment, faces in ((frag_a, entry["faces_a"]), (frag_b, entry["faces_b"])):
            centres = np.asarray(fragment.mesh.triangles_center, dtype=np.float64)[
                np.asarray(faces, dtype=np.int64)]
            # brute-force nearest triangle (small meshes only)
            centres_c = entry["cutter_centres"]
            d = np.linalg.norm(centres[:, None, :] - centres_c[None, :, :], axis=2)
            sources.update(int(x) for x in np.argmin(d, axis=1))
        sources.discard(entry["source_tri"])
        tri = cutter_triangles[sorted(sources)]
        yz = np.stack([tri[..., 1], tri[..., 2]], axis=-1)
        union = shapely.union_all(shapely.polygons(yz))
        rows.append({
            "interface_id": entry["interface_id"],
            "source_tri": entry["source_tri"],
            "sources": sorted(sources),
            "n_sources": len(sources),
            "source_region_mm2": float(shapely.area(union)),
            "source_region_bounds": [float(x) for x in union.bounds],
        })
    total = 0.0
    for row in rows:
        total += row["source_region_mm2"]
    out = {
        "cutter_faces": CAPTURED[0]["cutter_faces"],
        "cutter_x_extent": [float(np.min(cutter_triangles.reshape(-1, 3)[:, 0])),
                            float(np.max(cutter_triangles.reshape(-1, 3)[:, 0]))],
        "rows": rows,
        "sum_source_region_mm2": total,
        "hand_computed_mm2": 144.0,
    }
    target = Path(__file__).with_suffix(".json")
    target.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}, indent=1))
    for row in rows:
        print(f"  patch {row['interface_id']}: n_sources={row['n_sources']} "
              f"region={row['source_region_mm2']:.4f} mm2 bounds={row['source_region_bounds']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
