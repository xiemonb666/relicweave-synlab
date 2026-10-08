"""Read-only: recompute ONE fracture event and measure the AUTHORITY fragments.

Used to establish the ground truth for the new display shading:
  * per-fragment face counts and areas split by ``origin_kind`` / ``interface_id``
  * whether vertices are split (duplicated positions) at material boundaries
  * determinism (two runs must agree on face counts and volume)
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

MASTER_SEED = 20261001
LINEAGE_ID = "a12_demo"


def main() -> int:
    import numpy as np

    from synlab.fracture.api import FractureSpec, fracture_event
    from synlab.mothers.api import load_mother
    from synlab.seeds import make_rng
    from synlab.storage.store import AssetStore

    ap = argparse.ArgumentParser()
    ap.add_argument("--vessel", default="V01")
    ap.add_argument("--backend", default="plane_shared_cut")
    ap.add_argument("--mother-asset", default=None)
    ap.add_argument("--demo-root", default=str(REPO / "data" / "a12_demo"))
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()

    demo_root = pathlib.Path(args.demo_root)
    store = AssetStore(demo_root / "store")
    mother_asset = args.mother_asset
    if not mother_asset:
        manifest = json.loads((demo_root / "demo_manifest.json").read_text(encoding="utf-8"))
        row = next(e for e in manifest["entries"] if e["entry_id"] == f"mother:{args.vessel}")
        mother_asset = row["asset_id"]
    mother = load_mother(store, mother_asset)
    rng = make_rng(MASTER_SEED, LINEAGE_ID, "fracture", args.vessel, args.backend)
    result = fracture_event(mother, FractureSpec(backend=args.backend), rng,
                            event_id=f"{LINEAGE_ID}_{args.vessel}_{args.backend}")

    report = {"vessel": args.vessel, "backend": args.backend, "mother_asset": mother_asset,
              "interface_count": len(result.interfaces), "fragments": []}
    for fragment in result.fragments:
        mesh = fragment.mesh
        vertices = np.asarray(mesh.vertices, dtype=np.float64)
        faces = np.asarray(mesh.faces, dtype=np.int64)
        origin = np.asarray(fragment.face_origin_kind)
        interface = np.asarray(fragment.face_interface_id)
        v0, v1, v2 = vertices[faces[:, 0]], vertices[faces[:, 1]], vertices[faces[:, 2]]
        area = 0.5 * np.linalg.norm(np.cross(v1 - v0, v2 - v0), axis=1)
        quant = np.round(vertices, 6)
        _, inverse, counts = np.unique(quant, axis=0, return_inverse=True, return_counts=True)
        per_origin = []
        for value in sorted(set(int(x) for x in origin.tolist())):
            mask = origin == value
            per_origin.append({"origin_kind": value, "faces": int(mask.sum()),
                               "area_mm2": float(area[mask].sum())})
        per_interface = []
        for value in sorted(set(int(x) for x in interface.tolist())):
            mask = interface == value
            per_interface.append({"interface_id": value, "faces": int(mask.sum()),
                                  "area_mm2": float(area[mask].sum())})
        report["fragments"].append({
            "fragment_id": str(fragment.fragment_id),
            "vertices": int(len(vertices)),
            "faces": int(len(faces)),
            "volume_mm3": float(fragment.volume_mm3),
            "area_mm2": float(fragment.area_mm2),
            "area_from_faces_mm2": float(area.sum()),
            "welded_positions": int(len(counts)),
            "split_positions": int((counts > 1).sum()),
            "max_copies": int(counts.max()) if len(counts) else 0,
            "per_origin": per_origin,
            "per_interface": per_interface,
            "component_id": int(getattr(fragment, "component_id", 0)),
            "parent_id": str(getattr(fragment, "parent_id", "")),
        })

    if args.json_out:
        pathlib.Path(args.json_out).write_text(json.dumps(report, indent=2, ensure_ascii=False),
                                               encoding="utf-8")
    print(f"event {args.vessel}/{args.backend}: {len(result.fragments)} fragments, "
          f"{len(result.interfaces)} interfaces")
    for row in report["fragments"]:
        print(f"  {row['fragment_id']}: V={row['vertices']} F={row['faces']} "
              f"vol={row['volume_mm3']:.3f} area={row['area_mm2']:.3f} "
              f"welded={row['welded_positions']} split_positions={row['split_positions']} "
              f"max_copies={row['max_copies']}")
        print(f"     per_origin: {row['per_origin']}")
        print(f"     per_interface: {row['per_interface']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
