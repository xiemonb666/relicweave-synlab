"""Scratch: run the production assembly past the watertightness gate to see the offending faces.

Loads ``synlab/fracture/cut.py`` source, *only* relaxes the ``bad_edges`` refusal (a diagnostic
patch, never used for any reported number), executes it in a private namespace and inspects the
assembled mesh.  Prints the leaf-level and split-pattern context of every over-used edge.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
TESTS_A12 = Path(__file__).resolve().parents[2]
for _path in (str(REPO_ROOT), str(TESTS_A12)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from synlab.fracture.api import _default_basis  # noqa: E402
from synlab.fracture.spec import BACKEND_ROUGH, FractureSpec  # noqa: E402
from synlab.fracture.surface_features import top_surface_samples  # noqa: E402,F401
from synlab.seeds import make_rng  # noqa: E402

import fixtures as fx  # noqa: E402

SOURCE = REPO_ROOT / "synlab" / "fracture" / "cut.py"


def load_private():
    import types

    source = SOURCE.read_text(encoding="utf-8")
    needle = "    if bad_edges:\n"
    assert needle in source
    patched = source.replace(needle, "    if bad_edges and False:  # DIAGNOSTIC ONLY\n", 1)
    assert patched != source
    name = "synlab.fracture._cut_diag"
    module = types.ModuleType(name)
    module.__file__ = str(SOURCE)
    module.__package__ = "synlab.fracture"
    module.__dict__["__builtins__"] = __builtins__
    sys.modules[name] = module
    exec(compile(patched, str(SOURCE), "exec"), module.__dict__)  # noqa: S102
    return module.__dict__


def main() -> int:
    private = load_private()
    build = private["build_closed_cutter"]

    mother = fx.thin_bowl_mother()
    spec = FractureSpec(backend=BACKEND_ROUGH, target_rms_mm=0.05)
    rng = make_rng(20261001, "fracture_test", BACKEND_ROUGH)
    basis = _default_basis(mother, rng, spec)
    height = private["make_height_field"](basis, rng, target_rms_mm=0.05, n_bands=spec.n_bands)
    height = private["attach_material_band"](height, mother.mesh)
    mesh, report = build(basis, height, error_budget_mm=0.01,
                         max_cells=int(spec.max_cutter_cells))
    print(f"cells={report['cells']} leaf_level={report['leaf_level']} "
          f"faces={report['triangles']} histogram={report['edge_use_histogram']}")
    print(f"top={report['top_triangles']} bottom={report['bottom_triangles']} "
          f"side={report['side_triangles']} degenerate={report['degenerate_faces']}")

    faces = np.asarray(mesh.faces, dtype=np.int64)
    verts = np.asarray(mesh.vertices, dtype=np.float64)
    a = faces[:, [0, 1, 2]].ravel()
    b = faces[:, [1, 2, 0]].ravel()
    keys = np.stack([np.minimum(a, b), np.maximum(a, b)], axis=1)
    unique, counts = np.unique(keys, axis=0, return_counts=True)
    print(f"\nedge-use histogram: {dict(sorted(Counter(counts.tolist()).items()))}")
    bad = unique[counts != 2]
    print(f"bad edges: {bad.shape[0]}")

    # which faces touch the bad edges?
    bad_set = {tuple(int(x) for x in e) for e in bad[:5000]}
    touching = []
    for idx, tri in enumerate(faces):
        for k in range(3):
            p, q = int(tri[k]), int(tri[(k + 1) % 3])
            if (min(p, q), max(p, q)) in bad_set:
                touching.append(idx)
                break
    touching = np.asarray(touching, dtype=np.int64)
    print(f"faces touching the first {min(len(bad_set), 5000)} bad edges: {touching.shape[0]}")

    # wall-clock length of the bad edges and their z-extent (top vs side vs bottom faces)
    lengths = np.linalg.norm(verts[bad[:, 0]] - verts[bad[:, 1]], axis=1)
    print(f"bad edge length: min={lengths.min():.3e} median={np.median(lengths):.3e} "
          f"max={lengths.max():.3e} zero={int(np.sum(lengths < 1e-12))}")
    dz = np.abs(verts[bad[:, 0], 2] - verts[bad[:, 1], 2])
    print(f"bad edge |dz|: min={dz.min():.3e} median={np.median(dz):.3e} max={dz.max():.3e} "
          f"horizontal={int(np.sum(dz < 1e-9))}")

    # sizes of the *faces* around the bad edges
    areas = np.asarray(mesh.area_faces, dtype=np.float64)
    if touching.size:
        print(f"area of touching faces: min={areas[touching].min():.3e} "
              f"median={np.median(areas[touching]):.3e} max={areas[touching].max():.3e}")
        deg = int(np.sum(areas[touching] <= 1e-15))
        print(f"degenerate touching faces: {deg} / {touching.shape[0]}")

    # histogram of face-vertex z: separate top / side / bottom
    z = verts[:, 2]
    bottom_z = float(report["bottom_w_mm"])
    face_kind = Counter()
    for idx in touching[:2000]:
        zs = z[faces[idx]]
        if np.all(np.abs(zs - bottom_z) < 1e-9):
            face_kind["bottom"] += 1
        elif np.any(np.abs(zs - bottom_z) < 1e-9):
            face_kind["side"] += 1
        else:
            face_kind["top"] += 1
    print(f"kind of touching faces: {dict(face_kind)}")

    # duplicate faces?
    canon = np.sort(faces, axis=1)
    uniq_faces, face_counts = np.unique(canon, axis=0, return_counts=True)
    print(f"duplicate vertex-triples: {int(np.sum(face_counts > 1))} "
          f"(max multiplicity {int(face_counts.max())})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
