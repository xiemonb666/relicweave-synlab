"""Scratch: debug the cutter mesh topology."""
import sys
from collections import Counter

import numpy as np

sys.path.insert(0, r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab")
sys.path.insert(0, r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\tests\a12\fracture")

from fixtures import box_mother
import synlab.fracture.cut as cut

mother = box_mother((20.0, 20.0, 20.0))
basis = cut.build_basis(np.asarray(mother.mesh.vertices), np.array([1.0, 0.0, 0.0]),
                        anchor=np.zeros(3))
field = cut.make_height_field(basis, np.random.default_rng(0), target_rms_mm=0.0)

real_build = cut.build_closed_cutter
captured = {}


def fake_build(b, h, **kw):
    import types
    src = None
    # capture internals by re-running the function body with a hook on trimesh construction
    import trimesh as _tm
    holder = {}
    real_Trimesh = _tm.Trimesh

    class Spy(_tm.Trimesh):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            holder.setdefault("meshes", []).append(self)

    _tm.Trimesh = Spy
    try:
        return real_build(b, h, **kw)
    finally:
        _tm.Trimesh = real_Trimesh
        captured["meshes"] = holder.get("meshes", [])


try:
    mesh, report = fake_build(basis, field, error_budget_mm=0.01, max_cells=200000)
    print("built", len(mesh.faces))
except Exception as exc:
    print("build failed:", exc)
    meshes = captured.get("meshes", [])
    print("captured", len(meshes))
    if meshes:
        local = meshes[0]
        verts = np.asarray(local.vertices)
        faces = np.asarray(local.faces)
        print("verts", verts.shape, "faces", faces.shape)
        counter = Counter()
        for tri in faces:
            for k in range(3):
                a, b = int(tri[k]), int(tri[(k + 1) % 3])
                counter[(min(a, b), max(a, b))] += 1
        from collections import Counter as C
        print("hist", C(counter.values()))
        bad = [e for e, n in counter.items() if n != 2]
        print("bad edges", len(bad))
        for e in bad[:12]:
            print("  ", e, counter[e], verts[e[0]], verts[e[1]])
        # how many faces are top?
        print("top faces from report?", len(faces))
        # locate the bad vertices
        badv = sorted({v for e in bad for v in e})
        print("bad vertices", len(badv))
        coords = verts[badv]
        print("uv range of bad verts", coords[:, 0].min(), coords[:, 0].max(),
              coords[:, 1].min(), coords[:, 1].max())
