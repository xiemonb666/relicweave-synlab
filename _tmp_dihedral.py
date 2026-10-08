"""Read-only: dihedral-angle distribution of the authority meshes (pick the crease threshold)."""
from __future__ import annotations

import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402


def dihedral_report(mesh, label: str) -> dict:
    import trimesh

    adjacency = np.asarray(mesh.face_adjacency, dtype=np.int64)
    normals = np.asarray(mesh.face_normals, dtype=np.float64)
    dots = np.einsum("ij,ij->i", normals[adjacency[:, 0]], normals[adjacency[:, 1]])
    angle = np.degrees(np.arccos(np.clip(dots, -1.0, 1.0)))
    hist, edges = np.histogram(angle, bins=[0, 1, 2, 5, 10, 20, 30, 45, 60, 90, 120, 180.0001])
    return {
        "label": label,
        "faces": int(len(mesh.faces)),
        "vertices": int(len(mesh.vertices)),
        "euler_estimate_watertight": bool(mesh.is_watertight),
        "edges_shared_by_2_faces": int(len(adjacency)),
        "edges_total": int(len(mesh.edges_unique)),
        "angle_hist": {f"{edges[i]:g}-{edges[i+1]:g}": int(hist[i]) for i in range(len(hist))},
        "max_angle": float(angle.max()) if angle.size else None,
        "share_over_30deg": float((angle > 30).mean()) if angle.size else None,
        "share_over_60deg": float((angle > 60).mean()) if angle.size else None,
    }


def main() -> int:
    from synlab.fracture.api import FractureSpec, fracture_event
    from synlab.mothers.api import load_mother
    from synlab.seeds import make_rng
    from synlab.storage.store import AssetStore

    demo_root = REPO / "data" / "a12_demo"
    store = AssetStore(demo_root / "store")
    manifest = json.loads((demo_root / "demo_manifest.json").read_text(encoding="utf-8"))
    rows = {e["entry_id"]: e for e in manifest["entries"]}

    mother = load_mother(store, rows["mother:V01"]["asset_id"])
    rng = make_rng(20261001, "a12_demo", "fracture", "V01", "plane_shared_cut")
    result = fracture_event(mother, FractureSpec(backend="plane_shared_cut"), rng,
                            event_id="a12_demo_V01_plane_shared_cut")

    reports = [dihedral_report(mother.mesh, "mother:V01")]
    for fragment in result.fragments:
        reports.append(dihedral_report(fragment.mesh, f"fragment:{fragment.fragment_id}"))

    from synlab.degrade.api import load_source
    bundle = load_source(store, "asset_ab3085f11f1be039b14f")
    reports.append(dihedral_report(bundle.get("mesh"), "degrade-source:physical_component"))
    print(json.dumps(reports, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
