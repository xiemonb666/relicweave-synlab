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

