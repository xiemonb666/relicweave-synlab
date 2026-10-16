"""Does a synthetic two-shell interpenetrating mother reproduce the whole-body defect?"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import trimesh

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from synlab.fracture import booleans as B
from synlab.fracture.api import make_closed_cutter
from synlab.fracture.spec import FractureSpec


def edges(mesh):
    e = np.asarray(mesh.edges_unique, dtype=np.int64)
    c = np.bincount(np.asarray(mesh.edges_unique_inverse, dtype=np.int64), minlength=e.shape[0])
    return int(np.sum(c == 1)), int(np.sum(c > 2))


class FakeMother:
    def __init__(self, mesh, mother_id="synthetic"):
        self.mesh = mesh
        self.mother_id = mother_id


def compound(n_shift=5.0):
    parts = []
    for i, dx in enumerate((0.0, n_shift)):
        box = trimesh.creation.box(extents=[20.0, 20.0, 20.0])
        box.apply_translation([dx, 0.0, 0.0])
        parts.append(box)
    return trimesh.util.concatenate(parts)


def main() -> int:
    mesh = compound()
    print("compound faces", len(mesh.faces), "watertight", mesh.is_watertight,
          "components", len(mesh.split(only_watertight=False)))
    mother = FakeMother(mesh)
    spec = FractureSpec(backend="plane_shared_cut", error_budget_mm=0.01)
    cutter = make_closed_cutter(mother, spec, np.random.default_rng(7))
    cutter_source = B.tag_source(trimesh.Trimesh(vertices=np.asarray(cutter.mesh.vertices),
                                                 faces=np.asarray(cutter.mesh.faces),
                                                 process=False), 2.0, "cutter")
    whole = B.tag_source(trimesh.Trimesh(vertices=np.asarray(mesh.vertices),
                                         faces=np.asarray(mesh.faces), process=False),
                         1.0, "mother")
    for label, fn in (("M_minus", B.boolean_intersection), ("M_plus", B.boolean_difference)):
        out = fn([whole, cutter_source], label=label)
        boundary, over = edges(out.mesh)
        print(f"whole-body {label}: faces={out.n_faces} watertight={out.mesh.is_watertight} "
              f"boundary={boundary} nonmanifold={over} "
              f"components={len(out.mesh.split(only_watertight=False))}")
    shells = B.mesh_shells(mesh)
    for label, fn in (("M_minus", B.boolean_intersection), ("M_plus", B.boolean_difference)):
        pieces = [fn([B.tag_source(part, 1.0, "mother", triangle_ids=ids), cutter_source],
                     label=label) for part, ids in shells]
        joined = B.concat_tagged(pieces, label=label)
        boundary, over = edges(joined.mesh)
        print(f"per-shell {label}: faces={joined.n_faces} watertight={joined.mesh.is_watertight} "
              f"boundary={boundary} nonmanifold={over} "
              f"components={len(joined.mesh.split(only_watertight=False))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
