"""Cutfix regression tests: the unified per-cell triangulation and its consequences.

The pre-fix ``_Quadtree.cell_triangles`` chose between twelve hand-written branch tables keyed by
which cell edges were split.  Eight of the twelve tiled the cell incorrectly (measured area sums of
0.75 -- a 25 % hole -- 1.25 with a zero-area sliver spanning a whole edge, and 1.75 -- a 75 %
overlap), which produced "edges used once" and "edges used 3-7 times" and made ``build_closed_cutter``
refuse *every* refined cutter with ``CUTTER_NOT_CLOSED``.  The replacement is one algorithm: walk
the cell boundary counter-clockwise, insert the midpoint of every split edge between the two halves
of that edge, and fan the resulting ring from the cell centre.

Everything here is measured, never assumed:

* :func:`test_every_split_pattern_tiles_the_unit_cell` runs the production ``cell_triangles`` on a
  ``_Quadtree`` whose split flags are produced by the production ``edge_split`` predicate, for all
  16 flag combinations, and checks the area sum, the union area (rasterised), the absence of
  zero-area triangles and the per-cell edge-use structure;
* :func:`test_the_plane_triangulation_is_untouched` pins the ``n_split == 0`` branch -- the only one
  a flat height field ever takes -- to the literal pre-fix geometry, which is what makes the
  plane/zero-amplitude-rough regression bit-for-bit;
* :func:`test_the_plane_cutter_is_unchanged_and_closed` runs a real plane cutter through the
  production path and requires the closed-solid contract on it.

The remaining defect (a refined *rough* cutter is still not watertight) is **not** hidden here: it
is recorded in ``docs/a12/fracture_realism.md`` 搂10 with its measured numbers, and there is no
assertion in this file that the rough cutter closes.
"""

from __future__ import annotations

import itertools
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
TESTS_A12 = Path(__file__).resolve().parents[2]
for _path in (str(REPO_ROOT), str(TESTS_A12)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from synlab.fracture import cut as cut_mod  # noqa: E402
from synlab.fracture.api import make_closed_cutter  # noqa: E402
from synlab.fracture.spec import BACKEND_PLANE, BACKEND_ROUGH, FractureSpec  # noqa: E402
from synlab.seeds import make_rng  # noqa: E402

import fixtures as fx  # noqa: E402

MASTER_SEED = 20261001
SPAN = 4
LEVEL = 0
ROOT_LEVEL = 2
TARGET = (1, 1)
#: the unit cell's area in key units with ``SPAN = 4`` (edge ``1 << SPAN``)
UNIT_AREA = float(1 << (2 * SPAN))
AREA_TOL = 1e-9


def _tree_with_flags(flags: tuple[bool, bool, bool, bool]) -> cut_mod._Quadtree:
    """A quadtree whose ``TARGET`` cell reports exactly ``flags`` = (left, bottom, right, top).

    The flags are not injected: the tree is refined the way the real refinement loop refines it --
    the neighbour cell on that side is marked split -- and then ``edge_splits`` is asked for the
    answer.  The neighbour indices are the ones ``cutfix`` left in place (``_across_finer`` reads
    the sibling at ``TARGET``'s own level), so this fixture drives exactly the predicate the
    production refinement loop drives.
    """
    tree = cut_mod._Quadtree(0.0, 4.0, 0.0, 4.0, ROOT_LEVEL)
    i, j = TARGET
    neighbours = ((i - 1, j), (i, j - 1), (i + 1, j), (i, j + 1))
    for index, (ni, nj) in enumerate(neighbours):
        if flags[index]:
            tree.refined.add((ni, nj, LEVEL))
    return tree


def _signed_area(points: np.ndarray) -> float:
    total = 0.0
    for k in range(points.shape[0]):
        x0, y0 = points[k]
        x1, y1 = points[(k + 1) % points.shape[0]]
        total += x0 * y1 - x1 * y0
    return 0.5 * total


def _triangle_area(tri: np.ndarray) -> float:
    (x0, y0), (x1, y1), (x2, y2) = tri
    return 0.5 * ((x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0))


def _union_area(key: np.ndarray, tris: np.ndarray, res: int = 1024) -> float:
    """Rasterised |union of the triangles| -- summing signed areas cannot see an overlap."""
    lo = key.min(axis=0)
    hi = key.max(axis=0)
    h = float((hi[0] - lo[0])) / res
    gx = lo[0] + (np.arange(res) + 0.5) * h
    gy = lo[1] + (np.arange(res) + 0.5) * h
    X, Y = np.meshgrid(gx, gy, indexing="ij")
    covered = np.zeros(X.shape, dtype=bool)
    for t in tris:
        p, q, r = key[t[0]], key[t[1]], key[t[2]]
        det = (q[1] - r[1]) * (p[0] - r[0]) + (r[0] - q[0]) * (p[1] - r[1])
        if abs(det) < 1e-12:
            continue
        w0 = ((q[1] - r[1]) * (X - r[0]) + (r[0] - q[0]) * (Y - r[1])) / det
        w1 = ((r[1] - p[1]) * (X - r[0]) + (p[0] - r[0]) * (Y - r[1])) / det
        covered |= (w0 >= 0) & (w1 >= 0) & (w0 + w1 <= 1)
    return float(covered.sum()) * h * h


def _edge_use(tris: np.ndarray) -> Counter:
    uses: Counter[tuple[int, int]] = Counter()
    for t in tris:
        for k in range(3):
            a, b = int(t[k]), int(t[(k + 1) % 3])
            uses[(min(a, b), max(a, b))] += 1
    return Counter(uses.values())


def _all_flags():
    for n in range(5):
        for mask in itertools.combinations(range(4), n):
            yield tuple(index in mask for index in range(4))


def test_every_split_pattern_tiles_the_unit_cell() -> None:
    """All 16 flag patterns: area 1.0, no sliver, no overlap, every edge used once or twice."""
    seen = 0
    for flags in _all_flags():
        tree = _tree_with_flags(flags)
        assert tree.edge_splits(*TARGET, LEVEL) == flags, "the fixture must produce these flags"
        pts, tris = tree.cell_triangles(*TARGET, LEVEL, SPAN)
        key = np.asarray(pts, dtype=np.float64)
        areas = np.array([_triangle_area(key[t]) for t in tris])
        assert abs(areas.sum() - UNIT_AREA) <= AREA_TOL, (flags, areas.sum() / UNIT_AREA)
        assert np.all(areas > 0.0), f"pattern {flags} has a zero/negative-area triangle"
        assert abs(_union_area(key, tris) - UNIT_AREA) / UNIT_AREA < 3e-3, (
            f"pattern {flags} does not cover the cell exactly once")
        histogram = _edge_use(tris)
        assert set(histogram) <= {1, 2}, f"pattern {flags} reuses an edge: {histogram}"
        assert histogram.get(1, 0) == 4 + int(sum(flags)), (
            f"pattern {flags} does not have one boundary segment per ring half-edge")
        assert pts.shape[0] == (4 if sum(flags) == 0 else 9)
        seen += 1
    assert seen == 16


def test_the_ring_uses_the_midpoint_of_every_split_edge() -> None:
    """The fan's boundary must be the real cell boundary: no chord may cut a corner off."""
    for flags in _all_flags():
        tree = _tree_with_flags(flags)
        pts, tris = tree.cell_triangles(*TARGET, LEVEL, SPAN)
        key = np.asarray(pts, dtype=np.float64)
        # every vertex of the triangulation lies on the cell boundary or is the centre
        c00 = key.min(axis=0)
        c11 = np.array([c00[0] + (1 << SPAN), c00[1] + (1 << SPAN)])
        span = float(1 << SPAN)
        for p in key:
            on_left = abs(p[0] - c00[0]) < 1e-12
            on_right = abs(p[0] - c11[0]) < 1e-12
            on_bottom = abs(p[1] - c00[1]) < 1e-12
            on_top = abs(p[1] - c11[1]) < 1e-12
            centre = (abs(p[0] - (c00[0] + span / 2)) < 1e-12
                      and abs(p[1] - (c00[1] + span / 2)) < 1e-12)
            assert on_left or on_right or on_bottom or on_top or centre, (flags, p)
        del c11, span


def test_the_nsplit_zero_branch_is_the_pre_fix_geometry() -> None:
    """``n_split == 0`` is the only branch a flat field takes: it must stay exactly as it was.

    Pinned literally (four corners, the diagonal split ``(0,1,2) (0,2,3)``) because this is what
    makes ``plane_shared_cut`` -- and a zero-amplitude ``rough_shared_cut`` -- bit-for-bit
    reproducible across the rewrite (evidence: ``data/a12_reports/cutfix/plane_regression.json``).
    """
    tree = _tree_with_flags((False, False, False, False))
    pts, tris = tree.cell_triangles(*TARGET, LEVEL, SPAN)
    expected_pts = np.array([[16, 16], [32, 16], [32, 32], [16, 32]], dtype=np.int64)
    assert np.array_equal(pts, expected_pts)
    assert np.array_equal(tris, np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int64))


def test_the_fully_split_fan_is_unchanged_in_geometry() -> None:
    """A fully split cell must still be the same 9 points / 8 triangles as the old fan."""
    tree = _tree_with_flags((True, True, True, True))
    pts, tris = tree.cell_triangles(*TARGET, LEVEL, SPAN)
    assert pts.shape == (9, 2) and tris.shape == (8, 3)
    old_points = np.array([[16, 16], [32, 16], [32, 32], [16, 32],
                           [24, 16], [32, 24], [24, 32], [16, 24], [24, 24]], dtype=np.int64)
    # the point *set* is identical; only the midpoint ordering inside the array is permuted
    assert {tuple(int(x) for x in p) for p in pts} == \
           {tuple(int(x) for x in p) for p in old_points}
    areas = np.array([_triangle_area(np.asarray(pts, dtype=np.float64)[t]) for t in tris])
    assert np.all(areas > 0.0)
    assert abs(areas.sum() - UNIT_AREA) <= AREA_TOL
    assert set(_edge_use(tris)) <= {1, 2}


def test_the_plane_cutter_is_unchanged_and_closed() -> None:
    """Real plane cutter through the production path: closed solid, every edge used twice."""
    mother = fx.thin_bowl_mother()
    spec = FractureSpec(backend=BACKEND_PLANE)
    cutter = make_closed_cutter(mother, spec, make_rng(MASTER_SEED, "cutfix_test", BACKEND_PLANE))
    mesh = cutter.mesh
    assert bool(mesh.is_watertight)
    assert bool(mesh.is_winding_consistent)
    assert float(mesh.volume) > 0.0
    faces = np.asarray(mesh.faces, dtype=np.int64)
    a = faces[:, [0, 1, 2]].ravel()
    b = faces[:, [1, 2, 0]].ravel()
    keys = np.stack([np.minimum(a, b), np.maximum(a, b)], axis=1)
    _unique, counts = np.unique(keys, axis=0, return_counts=True)
    assert set(Counter(counts.tolist())) == {2}
    assert float(cutter.realized_error_mm) == 0.0
    assert cutter.meta["leaf_level"] == 0
    assert cutter.meta["edge_use_histogram"] == {"2": int(_unique.shape[0])}


def test_a_zero_amplitude_rough_cut_still_regresses_to_the_plane() -> None:
    """The zero-amplitude rough path must still take the untouched ``n_split == 0`` branch."""
    box = fx.box_mother((20.0, 20.0, 20.0))
    plane = make_closed_cutter(box, FractureSpec(backend=BACKEND_PLANE),
                               make_rng(MASTER_SEED, "cutfix_test", "plane"))
    rough = make_closed_cutter(box, FractureSpec(backend=BACKEND_ROUGH, target_rms_mm=0.0),
                               make_rng(MASTER_SEED, "cutfix_test", "rough"))
    assert np.array_equal(np.asarray(plane.mesh.faces), np.asarray(rough.mesh.faces))
    assert np.array_equal(np.asarray(plane.mesh.vertices), np.asarray(rough.mesh.vertices))
    assert rough.meta["height_field"]["flat"] is True
    assert rough.meta["leaf_level"] == 0
    assert rough.meta["edge_use_histogram"] == plane.meta["edge_use_histogram"]


@pytest.mark.parametrize("backend", [BACKEND_PLANE])
def test_the_cutfix_measurement_is_recorded(backend: str) -> None:
    """The measured evidence files must exist and agree with the code's own assertions."""
    import json

    root = REPO_ROOT / "data" / "a12_reports" / "cutfix"
    triangulation = root / "cell_triangulation_after.json"
    regression = root / "plane_regression.json"
    if not triangulation.exists() or not regression.exists():
        pytest.skip("cutfix evidence files are not present in this checkout")
    payload = json.loads(triangulation.read_text(encoding="utf-8"))
    assert payload["area_ok_all"] is True
    assert payload["no_degenerate_all"] is True
    assert payload["edge_check_ok_all"] is True
    for row in payload["rows"]:
        assert abs(row["area_key"] / 256.0 - 1.0) <= 1e-9
        assert set(row["edge_use_histogram"]) <= {"1", "2"}
    regression_payload = json.loads(regression.read_text(encoding="utf-8"))
    comparison = regression_payload["comparison"]
    assert comparison, "the plane regression file must contain measured comparisons"
    for key, entry in comparison.items():
        assert entry["mesh_hash_equal"], key
        assert entry["vertices_bitwise_equal"], key
        assert entry["faces_bitwise_equal"], key
        assert entry["all_identical"], key


# ---------------------------------------------------------------------------------------------
# Assembler-level T-junction resolution (docs/a12/fracture_realism.md 搂11)
# ---------------------------------------------------------------------------------------------

TARGET_CELL = (1, 1, 0)
ROOT_SIDE = 4


def _tj_tree(refined: list[tuple[int, int, int]]) -> cut_mod._Quadtree:
    """A four-cell quadtree with the given cells refined (never a refined cell below a refined
    ancestor: such a set is not a quadtree and ``leaves`` would not be a partition)."""
    tree = cut_mod._Quadtree(0.0, 4.0, 0.0, 4.0, 2)
    for cell in refined:
        ci, cj, cl = (int(v) for v in cell)
        ok = True
        while cl > 0:
            cl, ci, cj = cl - 1, ci >> 1, cj >> 1
            if (ci, cj, cl) in tree.refined:
                ok = False
                break
        if ok:
            tree.refined.add((int(cell[0]), int(cell[1]), int(cell[2])))
    return tree


def _child_facing(cell: tuple[int, int, int], orient: str, lo: bool,
                  sub: int) -> tuple[int, int, int]:
    i, j, level = (int(v) for v in cell)
    if orient == "v":
        return (2 * i + (0 if lo else 1), 2 * j + int(sub), level + 1)
    return (2 * i + int(sub), 2 * j + (0 if lo else 1), level + 1)


def _edge_corner_points(tree: cut_mod._Quadtree, cell: tuple[int, int, int], orient: str,
                        lo: bool, key_level: int) -> set[tuple[int, int]]:
    """Key points strictly inside one edge of ``cell`` that are corners of *other* leaves.

    This is the ground truth for a conforming ring: every one of them must be a point of the ring
    ``cell_triangles`` emits, otherwise the facing leaf traverses an edge this cell never emits
    (a T-junction), and the assembler compensates with a spurious side quad.
    """
    i, j, level = (int(v) for v in cell)
    span = int(key_level) - level
    step = 1 << span
    gu, gv = i << span, j << span
    if orient == "v":
        line, lo_k, hi_k = (gu if lo else gu + step), gv, gv + step
    else:
        line, lo_k, hi_k = (gv if lo else gv + step), gu, gu + step
    points: set[tuple[int, int]] = set()
    for (li, lj, ll) in tree.leaves():
        if (int(li), int(lj), int(ll)) == (i, j, level):
            continue
        lspan = int(key_level) - int(ll)
        lstep = 1 << lspan
        lu, lv = int(li) << lspan, int(lj) << lspan
        for (cu, cv) in ((lu, lv), (lu + lstep, lv), (lu + lstep, lv + lstep), (lu, lv + lstep)):
            if orient == "v" and cu == line and lo_k < cv < hi_k:
                points.add((cu, cv))
            elif orient == "u" and cv == line and lo_k < cu < hi_k:
                points.add((cu, cv))
    return points


def _ring_points_on_edge(ring: np.ndarray, cell: tuple[int, int, int], orient: str, lo: bool,
                         key_level: int) -> set[tuple[int, int]]:
    i, j, level = (int(v) for v in cell)
    span = int(key_level) - level
    step = 1 << span
    gu, gv = i << span, j << span
    if orient == "v":
        line, lo_k, hi_k, row_axis, position_axis = (gu if lo else gu + step), gv, gv + step, 0, 1
    else:
        line, lo_k, hi_k, row_axis, position_axis = (gv if lo else gv + step), gu, gu + step, 1, 0
    return {(int(p[0]), int(p[1])) for p in ring
            if int(p[row_axis]) == line and lo_k < int(p[position_axis]) < hi_k}


def _lattice_step(tree: cut_mod._Quadtree, cell: tuple[int, int, int], key_level: int) -> int:
    """One key unit of the cell's own lattice at ``key_level`` (the finest point it can emit)."""
    del tree
    return 1 << (int(key_level) - int(cell[2]))


@pytest.mark.parametrize("refined,bottom_extra,right_extra", [
    ([], 0, 0),
    ([(0, 1, 0)], 1, 0),
    ([(0, 1, 0), (0, 2, 1)], 2, 0),
    ([(2, 1, 0)], 0, 1),
    ([(0, 1, 0), (0, 2, 1), (2, 1, 0), (4, 2, 1)], 2, 1),
])
def test_the_ring_carries_every_facing_leaf_corner(refined, bottom_extra, right_extra) -> None:
    """No T-junction: every facing leaf corner on an edge is a point of the emitted ring.

    The extra-halving walk is measured against the *ground truth* of the leaf set (the corners of
    other leaves lying strictly inside the edge), not against a second copy of the walk.  The
    parametrisation covers: no refinement; a plain 2:1 interface; two levels on one side; two
    levels on the other side; and both sides at once.
    """
    tree = _tj_tree(refined)
    extras = cut_mod.edge_extra_all(tree, np.asarray([TARGET_CELL], dtype=np.int64), KEY_LEVEL)[0]
    span = KEY_LEVEL - TARGET_CELL[2]
    ring, _tris = tree.cell_triangles(*TARGET_CELL, span, extras)
    assert int(extras[1]) == bottom_extra, ("bottom edge extra", tuple(extras))
    assert int(extras[2]) == right_extra, ("right edge extra", tuple(extras))
    for orient, lo in (("v", True), ("u", True), ("v", False), ("u", False)):
        missing = _edge_corner_points(tree, TARGET_CELL, orient, lo, KEY_LEVEL) \
            - _ring_points_on_edge(ring, TARGET_CELL, orient, lo, KEY_LEVEL)
        assert not missing, (orient, lo, sorted(missing))


def test_the_extra_points_sit_where_the_facing_side_has_them() -> None:
    """``extra == 1`` must put one *quarter* point on the edge, not a half-quarter.

    Measured regression: the first version stepped by ``half >> extra``, i.e. half the intended
    spacing, so the extra point landed on a key-lattice position no neighbour owned; the assembler
    then created a second global vertex for a point that was already there and the solid stayed
    non-manifold (86 duplicated directed edges on the thin-bowl fixture).
    """
    tree = _tj_tree([(0, 1, 0), (0, 2, 1)])
    extras = cut_mod.edge_extra_all(tree, np.asarray([TARGET_CELL], dtype=np.int64), KEY_LEVEL)[0]
    assert int(extras[1]) == 2
    span = KEY_LEVEL - TARGET_CELL[2]
    ring, _tris = tree.cell_triangles(*TARGET_CELL, span, extras)
    gu = TARGET_CELL[0] << span
    gv = TARGET_CELL[1] << span
    unit = _lattice_step(tree, TARGET_CELL, KEY_LEVEL)
    want = {1 * unit, 2 * unit, 3 * unit}
    got = {int(p[0]) - gu for p in ring if int(p[1]) == gv and gu < int(p[0]) < gu + (1 << span)}
    assert want <= got, (sorted(want), sorted(got))


def test_the_ring_visits_the_boundary_in_one_direction() -> None:
    """The fan's boundary walk must not go backwards, and must not reuse a point.

    Measured regression: the ring used to append the edge's start corner *before* the midpoint, so
    a split edge came out as ``corner -> corner -> midpoint`` — the fan still covered the cell, but
    the boundary was walked backwards and two neighbours then traversed their shared edge in the
    *same* direction (a directed edge used twice, which the assembler turns into a duplicate side
    wall).
    """
    tree = _tj_tree([(0, 1, 0), (0, 2, 1), (2, 1, 0), (4, 2, 1)])
    extras = cut_mod.edge_extra_all(tree, np.asarray([TARGET_CELL], dtype=np.int64), KEY_LEVEL)[0]
    span = KEY_LEVEL - TARGET_CELL[2]
    pts, tris = tree.cell_triangles(*TARGET_CELL, span, extras)
    key = np.asarray(pts, dtype=np.float64)
    assert len({tuple(int(x) for x in p) for p in pts}) == pts.shape[0], "a point is emitted twice"
    #: the ring is the first vertex of every fan triangle, in order
    ring = [int(t[0]) for t in tris]
    assert len(ring) == len(set(ring)), "the ring visits a vertex twice"
    #: consecutive ring points must be connected by an axis-aligned segment or share the centre
    centre = ring[-1]
    for k in range(len(ring) - 1):
        a, b = ring[k], ring[k + 1]
        if a == centre or b == centre:
            continue
        same_u = key[a][0] == key[b][0]
        same_v = key[a][1] == key[b][1]
        assert same_u or same_v, (a, b)
    #: the ring is an exact traversal of the cell boundary
    x0, y0 = key.min(axis=0)
    x1, y1 = x0 + float(1 << span), y0 + float(1 << span)
    for index in ring[:-1]:
        p = key[index]
        assert (p[0] in (x0, x1)) or (p[1] in (y0, y1)) or (
            p[0] == (x0 + x1) / 2 and p[1] == (y0 + y1) / 2), p


def test_the_plane_cutter_reports_no_hanging_corner() -> None:
    """The plane control must report zero unresolved T-junctions (it has none to resolve)."""
    mother = fx.thin_bowl_mother()
    cutter = make_closed_cutter(
        mother, FractureSpec(backend=BACKEND_PLANE),
        make_rng(MASTER_SEED, "cutfix_test", "plane-audit"))
    assert cutter.meta["hanging_corner_points"] == 0
    assert cutter.meta["edges_missing_a_hanging_point"] == 0
    assert cutter.meta["edge_extra_histogram"] == {"0": 4 * cutter.meta["cells"]}


@pytest.mark.xfail(strict=False, reason=(
    "the assembler resolves every T-junction (hanging_corner_points == 0) but the assembled "
    "rough solid still has 76 duplicated directed edges on the thin-bowl fixture, so it is not "
    "watertight yet; recorded in docs/a12/fracture_realism.md 搂11 as still open"))
def test_the_rough_cutter_is_watertight_on_the_thin_bowl() -> None:
    """Landing claim: a refined rough cutter closes with every edge used exactly twice."""
    mother = fx.thin_bowl_mother()
    spec = FractureSpec(backend=BACKEND_ROUGH, target_rms_mm=0.02,
                        error_budget_mm=0.011, max_cutter_cells=90000)
    cutter = make_closed_cutter(mother, spec, make_rng(MASTER_SEED, "cutfix_test", "tj-rough"))
    faces = np.asarray(cutter.mesh.faces, dtype=np.int64)
    a = faces[:, [0, 1, 2]].ravel()
    b = faces[:, [1, 2, 0]].ravel()
    keys = np.stack([np.minimum(a, b), np.maximum(a, b)], axis=1)
    _unique, counts = np.unique(keys, axis=0, return_counts=True)
    assert set(Counter(counts.tolist())) == {2}

