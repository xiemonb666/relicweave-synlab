"""Prototype: per-shell booleans vs whole-mother boolean (V10 composite / V01 single shell).

For each requested mother index this probe measures, for both sides of the shared cut:

* the current whole-mother boolean (watertight? non-manifold edges? faces?),
* a per-shell boolean (one Manifold per connected shell, results concatenated),
* the per-shell inputs' own health,

and for a single-shell mother it checks that the per-shell path is *identical* to the current
path (so the fix cannot change any already-working vessel).

Usage::

    python data/a12_smoke/_tmp/probe_per_shell.py 0 51
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import trimesh

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from synlab.config import load_generation_spec
from synlab.fracture import booleans as B
from synlab.fracture.api import make_closed_cutter
from synlab.mothers.api import create_mother
from synlab.pipeline import derive_named_rngs, plan_generation


def stats(mesh: trimesh.Trimesh, name: str = "") -> dict:
    edges = np.asarray(mesh.edges_unique, dtype=np.int64)
    counts = np.bincount(np.asarray(mesh.edges_unique_inverse, dtype=np.int64),
                         minlength=edges.shape[0])
    row = {"name": name, "faces": int(mesh.faces.shape[0]),
           "vertices": int(mesh.vertices.shape[0]),
           "watertight": bool(mesh.is_watertight),
           "boundary_edges": int(np.sum(counts == 1)),
           "nonmanifold_edges": int(np.sum(counts > 2)),
           "components": len(mesh.split(only_watertight=False)),
           "volume_mm3": float(abs(mesh.volume))}
    print("   " + json.dumps(row))
    return row


def shells(mesh: trimesh.Trimesh) -> list[tuple[trimesh.Trimesh, np.ndarray]]:
    labels, count = B.components(mesh)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    out = []
    for index in range(count):
        mask = labels == index
        sub = trimesh.Trimesh(vertices=np.asarray(mesh.vertices), faces=faces[mask],
                              process=False)
        trimmed = sub.remove_unreferenced_vertices()
        if trimmed is not None:
            sub = trimmed
        out.append((sub, np.nonzero(mask)[0]))
    return out


def concat(results: list[B.SourceTaggedResult], label: str) -> B.SourceTaggedResult:
    vertices, faces, offset = [], [], 0
    point, mesh_id, source_tri, bary = [], [], [], []
    for item in results:
        v = np.asarray(item.mesh.vertices, dtype=np.float64)
        f = np.asarray(item.mesh.faces, dtype=np.int64)
        vertices.append(v)
        faces.append(f + offset)
        point.append(np.asarray(item.point, dtype=np.float64))
        mesh_id.append(np.asarray(item.mesh_id, dtype=np.float64))
        source_tri.append(np.asarray(item.source_tri, dtype=np.int64))
        bary.append(np.asarray(item.bary, dtype=np.float64))
        offset += v.shape[0]
    mesh = trimesh.Trimesh(vertices=np.concatenate(vertices), faces=np.concatenate(faces),
                           process=False)
    mesh.metadata = {"label": label, "welded_coincident_vertices": sum(
        int(r.mesh.metadata.get("welded_coincident_vertices", 0)) for r in results)}
    return B.SourceTaggedResult(mesh=mesh, point=np.concatenate(point),
                                mesh_id=np.concatenate(mesh_id),
                                source_tri=np.concatenate(source_tri),
                                bary=np.concatenate(bary))


def main() -> int:
    spec = load_generation_spec("configs/a12/next_experiment.yaml")
    plan = plan_generation(spec)
    indices = [int(x) for x in sys.argv[1:]] or [0, 51]
    for index in indices:
        lineage = next(l for l in plan.lineages if l.mother_index == index)
        rngs = derive_named_rngs(spec.master_seed, lineage.lineage_id)
        mother = create_mother(lineage.vessel_id, lineage.material_id, lineage.params,
                               rngs["shape"], mother_id=lineage.lineage_id)
        mm = mother.mesh
        cutter = make_closed_cutter(mother, spec.fracture, rngs["cut"])
        cutter_source = B.tag_source(trimesh.Trimesh(vertices=np.asarray(cutter.mesh.vertices),
                                                     faces=np.asarray(cutter.mesh.faces),
                                                     process=False), 2.0, "cutter")
        print(f"### {lineage.lineage_id} vessel={lineage.vessel_id} "
              f"mother_faces={mm.faces.shape[0]}")
        shell_list = shells(mm)
        print(f"   shells={len(shell_list)}")
        for i, (sub, tri_ids) in enumerate(shell_list):
            stats(sub, f"shell_{i}")
        for label, whole_fn, part_fn in (("M_minus", B.boolean_intersection,
                                          B.boolean_intersection),
                                         ("M_plus", B.boolean_difference,
                                          B.boolean_difference)):
            mother_source = B.tag_source(trimesh.Trimesh(vertices=np.asarray(mm.vertices),
                                                         faces=np.asarray(mm.faces),
                                                         process=False), 1.0, "mother")
            whole = whole_fn([mother_source, cutter_source], label=label)
            print(f"  {label} whole-mother:")
            whole_stats = stats(whole.mesh, "whole")
            pieces = []
            for sub, tri_ids in shell_list:
                src = B.tag_source(sub, 1.0, "mother", triangle_ids=tri_ids)
                pieces.append(part_fn([src, cutter_source], label=f"{label}_s"))
            joined = concat(pieces, label)
            print(f"  {label} per-shell ({len(pieces)} pieces):")
            per_stats = stats(joined.mesh, "per_shell")
            per_stats["piece_watertight"] = [bool(p.mesh.is_watertight) for p in pieces]
            print(f"     piece_watertight={per_stats['piece_watertight']}")
            if len(shell_list) == 1:
                same_v = np.allclose(np.asarray(whole.mesh.vertices),
                                     np.asarray(joined.mesh.vertices), atol=0.0, rtol=0.0)
                same_f = np.array_equal(np.asarray(whole.mesh.faces),
                                        np.asarray(joined.mesh.faces))
                print(f"     identical_to_whole: vertices={bool(same_v)} faces={bool(same_f)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
