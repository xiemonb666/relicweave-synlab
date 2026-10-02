"""Scratch: expose the assembled top surface of a refined cutter.

Executes a *diagnostic copy* of ``synlab/fracture/cut.py`` with two textual changes: the
watertightness refusal is disarmed and the assembled arrays are published to module globals.
Nothing here is used for any reported production number -- it exists only to attribute the
remaining over-used edges to their emitting leaves.
"""

from __future__ import annotations

import sys
import types
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
TESTS_A12 = Path(__file__).resolve().parents[2]
for _path in (str(REPO_ROOT), str(TESTS_A12)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from synlab.fracture.api import _default_basis  # noqa: E402
from synlab.fracture.spec import BACKEND_ROUGH, FractureSpec  # noqa: E402
from synlab.seeds import make_rng  # noqa: E402

import fixtures as fx  # noqa: E402

SOURCE = REPO_ROOT / "synlab" / "fracture" / "cut.py"
ANCHOR = "    bottom_faces: list[tuple[int, int, int]] = []\n"
PROBE = (
    "    _PROBE = {'leaves': [], 'levels': []}\n"
    "    for _i, _j, _level in leaves:\n"
    "        _pts_ij, _tris = tree.cell_triangles(_i, _j, _level, leaf_span_for(_level))\n"
    "        _local = [top_vertex(_level, int(p[0]), int(p[1])) for p in _pts_ij]\n"
    "        _PROBE['leaves'].append((int(_level), tuple(int(x) for x in _local),\n"
    "                                 tuple(tuple(int(x) for x in t) for t in _tris)))\n"
    "    globals()['PROBE_DATA'] = _PROBE\n"
    "    globals()['PROBE_VERTS'] = list(vertices)\n"
    "    globals()['PROBE_TOP_FACES'] = list(top_faces)\n"
    "    globals()['PROBE_TOP_USE'] = dict(top_edge_use)\n"
)

#: installed into the module *after* execution: the assembler publishes its own stage tables here
STAGE_PROBE = (
    "    globals()['PROBE_BOTTOM_FACES'] = list(bottom_faces)\n"
    "    globals()['PROBE_SIDE_FACES'] = list(side_faces)\n"
    "    globals()['PROBE_FACES'] = list(top_faces + bottom_faces + side_faces)\n"
)


def load_private():
    source = SOURCE.read_text(encoding="utf-8")
    assert ANCHOR in source
    patched = source.replace(ANCHOR, PROBE + ANCHOR, 1)
    patched = patched.replace("    if bad_edges:\n", "    if bad_edges and not True:\n", 1)
    stage_anchor = "    verts = np.asarray(vertices, dtype=np.float64)\n"
    assert stage_anchor in patched
    patched = patched.replace(stage_anchor, STAGE_PROBE + stage_anchor, 1)
    name = "synlab.fracture._cut_probe"
    module = types.ModuleType(name)
    module.__file__ = str(SOURCE)
    module.__package__ = "synlab.fracture"
    sys.modules[name] = module
    exec(compile(patched, str(SOURCE), "exec"), module.__dict__)  # noqa: S102
    return module


def main() -> int:
    module = load_private()
    mother = fx.thin_bowl_mother()
    spec = FractureSpec(backend=BACKEND_ROUGH, target_rms_mm=0.05)
    rng = make_rng(20261001, "fracture_test", BACKEND_ROUGH)
    basis = _default_basis(mother, rng, spec)
    height = module.make_height_field(basis, rng, target_rms_mm=0.05, n_bands=spec.n_bands)
    height = module.attach_material_band(height, mother.mesh)
    mesh, report = module.build_closed_cutter(
        basis, height, error_budget_mm=0.01, max_cells=int(spec.max_cutter_cells))
    print(f"cells={report['cells']} leaf_level={report['leaf_level']} "
          f"top={report['top_triangles']} side={report['side_triangles']} "
          f"histogram={report['edge_use_histogram']}")
    data = module.__dict__.get("PROBE_DATA")
    print(f"probe published: {data is not None}")
    if data is None:
        return 1
    leaves = data["leaves"]
    print(f"leaf records: {len(leaves)}  levels: "
          f"{dict(sorted(Counter(lv for lv, _l, _t in leaves).items()))}")

    use: Counter[tuple[int, int]] = Counter()
    owner: dict[tuple[int, int], list[tuple[int, int, int]]] = defaultdict(list)
    for level, local, tris in leaves:
        for tri in tris:
            face = (local[tri[0]], local[tri[1]], local[tri[2]])
            if len(set(face)) < 3:
                continue
            for k in range(3):
                a, b = face[k], face[(k + 1) % 3]
                if a == b:
                    continue
                key = (min(a, b), max(a, b))
                use[key] += 1
                owner[key].append((level, a, b))
    print(f"top edge use histogram: {dict(sorted(Counter(use.values()).items()))}")
    bad = [k for k, v in use.items() if v > 2]
    ones = [k for k, v in use.items() if v == 1]
    print(f"top edges used >2: {len(bad)}   used 1 (holes/T-junctions): {len(ones)}")

    level_combo = Counter()
    for key in bad:
        level_combo[tuple(sorted({lv for lv, _a, _b in owner[key]}))] += 1
    print("level combinations on over-used edges:")
    for combo, count in level_combo.most_common(12):
        print(f"  {combo}: {count}")

    one_combo = Counter()
    for key in ones:
        one_combo[tuple(sorted({lv for lv, _a, _b in owner[key]}))] += 1
    print("level combinations on single-use edges:")
    for combo, count in one_combo.most_common(8):
        print(f"  {combo}: {count}")

    verts = np.asarray(module.__dict__["PROBE_VERTS"], dtype=np.float64)
    top_faces = module.__dict__["PROBE_TOP_FACES"]

    def undirected(faces):
        table: Counter[tuple[int, int]] = Counter()
        for face in faces:
            for k in range(3):
                aa, bb = int(face[k]), int(face[(k + 1) % 3])
                table[(min(aa, bb), max(aa, bb))] += 1
        return table

    top_use = undirected(top_faces)
    bottom_use = undirected(module.__dict__["PROBE_BOTTOM_FACES"])
    side_use = undirected(module.__dict__["PROBE_SIDE_FACES"])
    all_faces = module.__dict__["PROBE_FACES"]
    total = undirected(all_faces)
    print(f"\nstage edge-use histograms:")
    print(f"  top:    {dict(sorted(Counter(top_use.values()).items()))}")
    print(f"  bottom: {dict(sorted(Counter(bottom_use.values()).items()))}")
    print(f"  side:   {dict(sorted(Counter(side_use.values()).items()))}")
    print(f"  total:  {dict(sorted(Counter(total.values()).items()))}")
    print(f"  reported: {report['edge_use_histogram']}")
    bad = [e for e, n in total.items() if n != 2]
    print(f"reconstructed bad edges: {len(bad)}   reported: {report['bad_edges']}")
    origin = Counter()
    for e in bad:
        pieces = []
        if top_use.get(e):
            pieces.append(f"top{top_use[e]}")
        if bottom_use.get(e):
            pieces.append(f"bot{bottom_use[e]}")
        if side_use.get(e):
            pieces.append(f"side{side_use[e]}")
        origin["+".join(pieces)] += 1
    print("composition of the bad edges (uses per stage):")
    for combo, count in origin.most_common(10):
        print(f"   {combo}: {count}")

    # is every bad edge a *vertical* one (top vertex <-> its own bottom vertex)?
    vertical = 0
    for e in bad:
        z0, z1 = verts[e[0], 2], verts[e[1], 2]
        xy0 = verts[e[0], :2]
        xy1 = verts[e[1], :2]
        if abs(z0 - z1) > 1e-9 and float(np.linalg.norm(xy0 - xy1)) < 1e-9:
            vertical += 1
    print(f"bad edges that are exact verticals: {vertical} / {len(bad)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
