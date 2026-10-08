"""Prototype: angle-threshold smooth vertex normals on the real authority meshes.

Measures feasibility (timing), the split-vertex count it implies, and how far the
result is from trimesh's plain area/angle-weighted average.
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

REPO = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402


def smooth_vertex_normals(mesh, *, angle_threshold_deg: float = 30.0):
    """Per-vertex normals: area+corner-angle weighted average inside a smoothing group.

    Returns ``(normals, groups, seed_face)`` where ``groups[v]`` is the id of the
    dominant incident face (seed) of the group chosen for vertex ``v``.
    """
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    # face normals + triangle areas
    v0, v1, v2 = vertices[faces[:, 0]], vertices[faces[:, 1]], vertices[faces[:, 2]]
    raw = np.cross(v1 - v0, v2 - v0)
    twice_area = np.linalg.norm(raw, axis=1)
    face_normals = raw / np.where(twice_area > 0, twice_area, 1.0)[:, None]
    area = 0.5 * twice_area
    # corner angle at each of the 3 corners
    def unit(x):
        n = np.linalg.norm(x, axis=1, keepdims=True)
        return x / np.where(n > 0, n, 1.0)
    e = [unit(vertices[faces[:, (i + 1) % 3]] - vertices[faces[:, i]]) for i in range(3)]
    corner = np.empty((len(faces), 3), dtype=np.float64)
    for i in range(3):
        corner[:, i] = np.arccos(np.clip(np.einsum("ij,ij->i", -e[i], e[(i + 2) % 3]), -1.0, 1.0))
    weight = area[:, None] * corner

    cos_limit = float(np.cos(np.radians(angle_threshold_deg)))
    n_vertices = len(vertices)
    normals = np.zeros((n_vertices, 3), dtype=np.float64)
    groups = np.full(n_vertices, -1, dtype=np.int64)
    # incident faces per vertex
    order = np.argsort(faces.reshape(-1), kind="stable")
    flat_vertex = faces.reshape(-1)[order]
    flat_face = np.repeat(np.arange(len(faces)), 3)[order]
    flat_corner = np.tile(np.arange(3), len(faces))[order]
    starts = np.searchsorted(flat_vertex, np.arange(n_vertices + 1))
    for vertex in range(n_vertices):
        incident = flat_face[starts[vertex]:starts[vertex + 1]]
        if incident.size == 0:
            continue
        local_weight = weight[incident, flat_corner[starts[vertex]:starts[vertex + 1]]]
        seed = int(incident[int(np.argmax(local_weight))])
        dots = face_normals[incident] @ face_normals[seed]
        chosen = incident[dots >= cos_limit]
        picked = weight[chosen, flat_corner[starts[vertex]:starts[vertex + 1]][dots >= cos_limit]]
        normal = (face_normals[chosen] * picked[:, None]).sum(axis=0)
        length = float(np.linalg.norm(normal))
        normals[vertex] = normal / length if length > 0 else face_normals[seed]
        groups[vertex] = seed
    return normals, groups


def report(mesh, label: str, thresholds=(15.0, 30.0, 45.0, 60.0)) -> dict:
    import trimesh  # noqa: F401

    out = {"label": label, "vertices": int(len(mesh.vertices)), "faces": int(len(mesh.faces)),
           "thresholds": {}}
    faces = np.asarray(mesh.faces, dtype=np.int64)
    for threshold in thresholds:
        t0 = time.perf_counter()
        normals, groups = smooth_vertex_normals(mesh, angle_threshold_deg=threshold)
        dt = time.perf_counter() - t0
        unique_groups = np.unique(groups)
        # vertices whose 3+ incident faces disagree: detectable from the group map only
        out["thresholds"][str(threshold)] = {
            "seconds": round(dt, 3),
            "distinct_seed_groups": int(len(unique_groups)),
            "smoothing_group_boundary_vertices": int(
                np.sum(groups[faces].max(axis=1) != groups[faces].min(axis=1))),
            "max_normal_length_error": float(np.abs(np.linalg.norm(normals, axis=1) - 1).max()),
            "min_normal_length": float(np.linalg.norm(normals, axis=1).min()),
        }
    # compare with trimesh's own vertex_normals
    base = np.asarray(mesh.vertex_normals, dtype=np.float64)
    normals30, _ = smooth_vertex_normals(mesh, angle_threshold_deg=30.0)
    dots = np.einsum("ij,ij->i", base, normals30)
    out["vs_trimesh_vertex_normals"] = {
        "max_angle_deg": float(np.degrees(np.arccos(np.clip(dots.min(), -1, 1)))),
        "mean_angle_deg": float(np.degrees(np.arccos(np.clip(dots, -1, 1))).mean()),
        "share_over_1deg": float(np.mean(dots < np.cos(np.radians(1.0)))),
    }
    return out


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

    reports = [report(mother.mesh, "mother:V01")]
    for fragment in result.fragments:
        reports.append(report(fragment.mesh, f"fragment:{fragment.fragment_id}"))

    # degrade source (P family = physical_component carrying origin_kind)
    src = store.get_asset("asset_ab3085f11f1be039b14f")
    from synlab.degrade.api import load_source
    bundle = load_source(store, "asset_ab3085f11f1be039b14f")
    reports.append(report(bundle.get("mesh"), f"degrade-source:{src.role}"))
    print(json.dumps(reports, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
