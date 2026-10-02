from __future__ import annotations

from itertools import permutations
from types import SimpleNamespace

import numpy as np

from synlab.fracture.implicit.assembler import (
    FACE_KEY_DECIMALS,
    _canonical,
    _face_key,
    _face_keys,
    _pair_points,
)


def _key_for_vertices(vertices: np.ndarray) -> tuple:
    mesh = SimpleNamespace(
        vertices=np.asarray(vertices, dtype=np.float64),
        faces=np.asarray([[0, 1, 2]], dtype=np.int64),
    )
    return next(iter(_face_keys(mesh)))


def test_face_keys_do_not_collide_when_coordinate_columns_sort_alike() -> None:
    triangle_a = np.asarray([(0, 0, 0), (1, 0, 1), (0, 1, 1)], dtype=np.float64)
    triangle_b = np.asarray([(0, 0, 1), (1, 0, 0), (0, 1, 1)], dtype=np.float64)
    vertices = np.concatenate((triangle_a, triangle_b), axis=0)
    mesh = SimpleNamespace(
        vertices=vertices,
        faces=np.asarray([[0, 1, 2], [3, 4, 5]], dtype=np.int64),
    )

    keys = _face_keys(mesh)

    assert len(keys) == 2
    assert _face_key(vertices, np.asarray([0, 1, 2])) != _face_key(
        vertices, np.asarray([3, 4, 5])
    )


def test_face_key_is_invariant_to_every_vertex_permutation_and_winding() -> None:
    triangle = np.asarray([(0.125, -2.5, 1.75), (4.0, 0.25, -3.0), (-1.0, 5.5, 0.5)])
    expected = _key_for_vertices(triangle)

    for order in permutations(range(3)):
        permuted = triangle[list(order)]
        assert _key_for_vertices(permuted) == expected
        assert _face_key(permuted, np.asarray([0, 1, 2])) == expected


def test_face_key_retains_the_frozen_rounding_precision() -> None:
    triangle = np.asarray([(0.1234561, 0, 0), (1, 0, 0), (0, 1, 0)], dtype=np.float64)
    sub_precision_shift = triangle.copy()
    sub_precision_shift[0, 0] += 0.0000002

    assert FACE_KEY_DECIMALS == 6
    assert _key_for_vertices(triangle) == _key_for_vertices(sub_precision_shift)


def test_canonical_sampling_is_identical_for_every_vertex_permutation() -> None:
    triangle = np.asarray([(0.125, -2.5, 1.75), (4.0, 0.25, -3.0), (-1.0, 5.5, 0.5)])
    baseline = _canonical(triangle[None, :, :])
    baseline_samples = _pair_points(baseline, order=3)

    for order in permutations(range(3)):
        permuted = _canonical(triangle[list(order)][None, :, :])
        samples = _pair_points(permuted, order=3)
        np.testing.assert_array_equal(permuted, baseline)
        np.testing.assert_array_equal(samples, baseline_samples)


def test_full_tuple_order_resolves_weighted_scalar_ties() -> None:
    # These distinct vertices both mapped to 1000 under the former x*1e6+y*1e3+z key.
    triangle = np.asarray([(0, 1, 0), (0.001, 0, 0), (0, 0, 1)], dtype=np.float64)
    weighted = triangle[:, 0] * 1.0e6 + triangle[:, 1] * 1.0e3 + triangle[:, 2]
    assert weighted[0] == weighted[1]
    assert not np.array_equal(triangle[0], triangle[1])

    baseline = _canonical(triangle[None, :, :])
    baseline_samples = _pair_points(baseline, order=3)
    for order in permutations(range(3)):
        permuted = _canonical(triangle[list(order)][None, :, :])
        np.testing.assert_array_equal(permuted, baseline)
        np.testing.assert_array_equal(_pair_points(permuted, order=3), baseline_samples)
