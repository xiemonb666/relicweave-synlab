"""Deep diagnosis of one mother's fracture boolean (V10-style non-watertight M_minus).

Measures, in order: the mother's own components and their pairwise contact, the cutter plane
relative to those components, the *raw* Manifold output (before the coincident-vertex weld) and
the welded output, plus the geometry of every non-manifold edge.

Usage::

    python data/a12_smoke/_tmp/probe_boolean_deep.py [mother_index]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import trimesh
from manifold3d import Manifold, Mesh

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from synlab.config import load_generation_spec
from synlab.fracture import booleans as B
from synlab.fracture.api import make_closed_cutter
from synlab.mothers.api import create_mother
from synlab.pipeline import derive_named_rngs, plan_generation


def mesh_stats(mesh: trimesh.Trimesh, name: str = "") -> dict:
    edges = np.asarray(mesh.edges_unique, dtype=np.int64)
    counts = np.bincount(np.asarray(mesh.edges_unique_inverse, dtype=np.int64),
                         minlength=edges.shape[0])
    boundary = int(np.sum(counts == 1))
    over = int(np.sum(counts > 2))
    dup = len(mesh.vertices) - len(np.unique(np.round(np.asarray(mesh.vertices), 9), axis=0))
    row = {
        "name": name, "faces": int(mesh.faces.shape[0]), "vertices": int(mesh.vertices.shape[0]),
        "watertight": bool(mesh.is_watertight),
        "winding_consistent": bool(mesh.is_winding_consistent),
        "boundary_edges": boundary, "nonmanifold_edges": over,
        "duplicate_vertex_positions": int(dup),
        "components": len(mesh.split(only_watertight=False)),
        "volume_mm3": float(abs(mesh.volume)),
    }
    print("  " + json.dumps(row))
    return row


def nonmanifold_edges(mesh: trimesh.Trimesh, limit: int = 12) -> list[dict]:
    edges = np.asarray(mesh.edges_unique, dtype=np.int64)
    counts = np.bincount(np.asarray(mesh.edges_unique_inverse, dtype=np.int64),
                         minlength=edges.shape[0])
    bad = np.nonzero(counts > 2)[0]
    out = []
    for index in bad[:limit]:
        a, b = edges[index]
        pa, pb = np.asarray(mesh.vertices[a]), np.asarray(mesh.vertices[b])
        length = float(np.linalg.norm(pa - pb))
        faces = np.nonzero(np.isin(np.asarray(mesh.faces), [a, b]).sum(axis=1) >= 2)[0]
        out.append({"edge": [int(a), int(b)], "uses": int(counts[index]), "len_mm": length,
                    "mid_mm": ((pa + pb) / 2.0).tolist(), "faces": faces[:8].tolist(),
                    "face_areas": [float(mesh.area_faces[f]) for f in faces[:8]]})
    return out


def raw_manifold_mesh(source: B.SourceMesh) -> trimesh.Trimesh:
    data = B._to_manifold(source).to_mesh()
    return trimesh.Trimesh(vertices=np.asarray(data.vert_properties)[:, 0:3].astype(np.float64),
                           faces=np.asarray(data.tri_verts, dtype=np.int64), process=False)


def manifold_stats(result, name: str) -> dict:
    data = result.to_mesh()
    mesh = trimesh.Trimesh(vertices=np.asarray(data.vert_properties)[:, 0:3].astype(np.float64),
                           faces=np.asarray(data.tri_verts, dtype=np.int64), process=False)
    return mesh_stats(mesh, name)


def pair_overlap(mesh: trimesh.Trimesh) -> list[dict]:
    """Pairwise intersection volume of the shells of one mesh (0 = they only touch/nest)."""
    parts = mesh.split(only_watertight=False)
    out = []
    for i in range(len(parts)):
        for j in range(i + 1, len(parts)):
            try:
                inter = Manifold(Mesh(vert_properties=np.asarray(
                    parts[i].vertices, dtype=np.float32),
                    tri_verts=np.asarray(parts[i].faces, dtype=np.uint32))) & Manifold(Mesh(
                    vert_properties=np.asarray(parts[j].vertices, dtype=np.float32),
                    tri_verts=np.asarray(parts[j].faces, dtype=np.uint32)))
                out.append({"pair": [i, j], "intersection_volume_mm3": float(inter.volume()),
                            "genus": int(inter.genus()), "components": int(inter.decompose())})
            except Exception as exc:  # noqa: BLE001
                out.append({"pair": [i, j], "error": f"{type(exc).__name__}: {exc}"})
    return out


def main() -> int:
    index = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    spec = load_generation_spec("configs/a12/next_experiment.yaml")
    plan = plan_generation(spec)
    lineage = next(l for l in plan.lineages if l.mother_index == index)
    rngs = derive_named_rngs(spec.master_seed, lineage.lineage_id)
    mother = create_mother(lineage.vessel_id, lineage.material_id, lineage.params,
                           rngs["shape"], mother_id=lineage.lineage_id)
    mm = mother.mesh
    print(f"### {lineage.lineage_id} vessel={lineage.vessel_id} "
          f"material={lineage.material_id} pattern={lineage.pattern_id}")
    print("mother components:")
    parts = mm.split(only_watertight=False)
    labels = np.asarray(mm.faces).copy()
    from synlab.fracture.booleans import components
    comp_labels, n_comp = components(mm)
    for i, part in enumerate(parts):
        bounds = np.asarray(part.bounds, dtype=np.float64)
        mesh_stats(part, f"mother_component_{i}")
        print(f"     bounds={np.round(bounds, 4).tolist()}")
    del labels, comp_labels, n_comp

    cutter = make_closed_cutter(mother, spec.fracture, rngs["cut"])
    basis = cutter.basis
    print(f"cutter: faces={cutter.triangles} watertight={cutter.mesh.is_watertight} "
          f"realized_error={cutter.realized_error_mm:.3e}")
    print(f"basis: origin={np.round(np.asarray(basis.origin), 4).tolist()} "
          f"normal={np.round(np.asarray(basis.normal), 6).tolist()} "
          f"id={basis.basis_id}")
    normal = np.asarray(basis.normal, dtype=np.float64)
    origin = np.asarray(basis.origin, dtype=np.float64)
    signed = (np.asarray(mm.vertices, dtype=np.float64) - origin) @ normal
    print(f"mother vertex signed distance to plane: min={signed.min():.6f} "
          f"max={signed.max():.6f} exact_zero={int(np.sum(np.abs(signed) < 1e-9))}")
    for i, part in enumerate(parts):
        s = (np.asarray(part.vertices, dtype=np.float64) - origin) @ normal
        print(f"   component {i}: signed min={s.min():.6f} max={s.max():.6f} "
              f"zeros={int(np.sum(np.abs(s) < 1e-9))} "
              f"faces_on_plane={int(np.sum(np.abs(s[np.asarray(part.faces)] < 1e-9).all(axis=1)))}")

    source_mother = B.tag_source(trimesh.Trimesh(vertices=np.asarray(mm.vertices),
                                                 faces=np.asarray(mm.faces), process=False),
                                 1.0, "mother")
    source_cutter = B.tag_source(trimesh.Trimesh(vertices=np.asarray(cutter.mesh.vertices),
                                                 faces=np.asarray(cutter.mesh.faces),
                                                 process=False),
                                 2.0, "cutter")
    print("raw manifold inputs (pre-boolean):")
    manifold_mother = B._to_manifold(source_mother)
    manifold_cutter = B._to_manifold(source_cutter)
    mesh_stats(raw_manifold_mesh(source_mother), "manifold_mother_in")
    mesh_stats(raw_manifold_mesh(source_cutter), "manifold_cutter_in")
    print("shell pair overlaps (mother):", json.dumps(pair_overlap(mm)))

    for label in ("M_minus", "M_plus"):
        print(f"{label}:")
        raw = (manifold_mother ^ manifold_cutter) if label == "M_minus" \
            else (manifold_mother - manifold_cutter)
        manifold_stats(raw, f"{label}_raw_unwelded")
        source_mother_fresh = B.tag_source(
            trimesh.Trimesh(vertices=np.asarray(mm.vertices), faces=np.asarray(mm.faces),
                            process=False), 1.0, "mother")
        source_cutter_fresh = B.tag_source(
            trimesh.Trimesh(vertices=np.asarray(cutter.mesh.vertices),
                            faces=np.asarray(cutter.mesh.faces), process=False), 2.0, "cutter")
        fn = B.boolean_intersection if label == "M_minus" else B.boolean_difference
        out = fn([source_mother_fresh, source_cutter_fresh], label=label)
        mesh_stats(out.mesh, f"{label}_post_weld")
        print(f"   weld count={out.mesh.metadata.get('welded_coincident_vertices')}")
        for row in nonmanifold_edges(out.mesh):
            print("   nonmanifold:", json.dumps(row))
        for row in nonmanifold_edges(trimesh.Trimesh(
                vertices=np.asarray(raw.to_mesh().vert_properties)[:, 0:3].astype(np.float64),
                faces=np.asarray(raw.to_mesh().tri_verts, dtype=np.int64), process=False)):
            print("   raw nonmanifold:", json.dumps(row))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
