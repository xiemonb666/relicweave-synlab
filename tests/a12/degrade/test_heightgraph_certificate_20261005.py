"""Small exact-geometry contract tests for the isolated A12 certificate candidate.

These tests are authored for root review and have not been executed in this task.
"""

from __future__ import annotations

from fractions import Fraction
from types import SimpleNamespace

import numpy as np

from synlab.degrade.heightgraph_certificate import (
    FacePartition,
    HeightGraphAxis,
    HeightGraphPartition,
    MeshQualityLimits,
    RectangleDomain,
    certify_heightgraph_subset,
)


_DOMAIN = RectangleDomain(0, 1, 0, 1)
_AXIS = HeightGraphAxis()
_QUALITY = MeshQualityLimits(min_q=0.001, min_altitude_mm=1e-6,
                             max_aspect_ratio=1_000_000)
_FRAME_ID = "a12-heightgraph-contract-fixture"
_MESH_METADATA = {"coordinate_unit": "mm", "frame_id": _FRAME_ID}


def _prism(top_points, top_faces, *, bottom_split="02"):
    """Build a closed unit-square prism with an arbitrary upper triangulation."""
    top = [(float(u), float(v), float(height)) for u, v, height in top_points]
    top_count = len(top)
    bottom = [(float(u), float(v), -2.0) for u, v in
              ((0, 0), (1, 0), (1, 1), (0, 1))]

    if bottom_split == "02":
        lower_faces = [(top_count + 0, top_count + 2, top_count + 1),
                       (top_count + 0, top_count + 3, top_count + 2)]
    elif bottom_split == "13":
        lower_faces = [(top_count + 0, top_count + 3, top_count + 1),
                       (top_count + 1, top_count + 3, top_count + 2)]
    else:
        raise ValueError(bottom_split)

    side_faces = []
    for p, q in ((0, 1), (1, 2), (2, 3), (3, 0)):
        side_faces.extend(((p, top_count + q, q),
                           (p, top_count + p, top_count + q)))

    faces = [tuple(face) for face in top_faces]
    upper_ids = tuple(range(len(faces)))
    lower_start = len(faces)
    faces.extend(lower_faces)
    side_start = len(faces)
    faces.extend(side_faces)
    mesh = SimpleNamespace(
        vertices=np.asarray(top + bottom, dtype=np.float64),
        faces=np.asarray(faces, dtype=np.int64),
        metadata=dict(_MESH_METADATA),
    )
    partition = FacePartition(
        upper_faces=upper_ids,
        lower_faces=tuple(range(lower_start, side_start)),
        side_faces=tuple(range(side_start, len(faces))),
    )
    return mesh, partition


def _partition(source_roles, candidate_roles, *, domain=_DOMAIN,
               quality_limits=_QUALITY, max_pair_checks=250_000):
    return HeightGraphPartition(
        domain=domain,
        source=source_roles,
        candidate=candidate_roles,
        quality_limits=quality_limits,
        coordinate_unit="mm",
        frame_id=_FRAME_ID,
        max_pair_checks=max_pair_checks,
    )


def _flat_square(split, *, corner_heights=(0, 0, 0, 0), bottom_split="02"):
    points = [(0, 0, corner_heights[0]), (1, 0, corner_heights[1]),
              (1, 1, corner_heights[2]), (0, 1, corner_heights[3])]
    if split == "02":
        top_faces = [(0, 1, 2), (0, 2, 3)]
    elif split == "13":
        top_faces = [(0, 1, 3), (1, 2, 3)]
    else:
        raise ValueError(split)
    return _prism(points, top_faces, bottom_split=bottom_split)


def test_zero_motion_coplanar_meshes_allow_different_triangulations():
    source, source_roles = _flat_square("02", bottom_split="02")
    candidate, candidate_roles = _flat_square("13", bottom_split="13")

    result = certify_heightgraph_subset(
        source, candidate, _partition(source_roles, candidate_roles), _AXIS)

    assert result["status"] == "PASS"
    assert result["source_hash"]
    assert result["result_hash"]
    assert result["certificate"]["relation"] == "candidate_subset_of_source"
    assert "excluding metadata, input-file bytes, NPZ container bytes, and provenance" \
        in result["certificate"]["mesh_hash_encoding"]


def test_nonzero_inward_vertex_wear_with_fixed_rim_can_pass():
    source, source_roles = _flat_square("02")
    worn_points = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
                   (0.5, 0.5, -0.25)]
    candidate, candidate_roles = _prism(
        worn_points, [(0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4)])

    result = certify_heightgraph_subset(
        source, candidate, _partition(source_roles, candidate_roles), _AXIS)

    assert result["status"] == "PASS"
    assert result["certificate"]["proved_inequalities"] == [
        "b_source < s_source", "b_candidate < c_candidate",
        "b_candidate == b_source", "c_candidate <= s_source",
        "source_and_candidate_rim_traces_equal",
    ]


def test_axis_permutation_and_projection_signs_use_declared_transformed_domain():
    source, source_roles = _flat_square("02")
    candidate, candidate_roles = _flat_square("13")
    axis = HeightGraphAxis(projection_axes=(1, 0), projection_signs=(1, -1),
                           height_axis=2, height_sign=1, name="permuted")
    domain = RectangleDomain(0, 1, -1, 0)

    result = certify_heightgraph_subset(
        source, candidate,
        _partition(source_roles, candidate_roles, domain=domain), axis)

    assert result["status"] == "PASS"
    assert result["certificate"]["axis"]["projection_axes"] == [1, 0]


def test_shared_vertex_positive_area_overlap_is_a_counterexample():
    source, source_roles = _flat_square("02")
    points = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
              (1, 0.2, 0), (0.2, 1, 0)]
    candidate, candidate_roles = _prism(
        points, [(0, 1, 2), (0, 2, 3), (0, 4, 5)])

    result = certify_heightgraph_subset(
        source, candidate, _partition(source_roles, candidate_roles), _AXIS)

    assert result["status"] == "FAIL"
    assert result["reasons"][0]["code"] == "PROJECTED_TRIANGLES_OVERLAP"
    assert result["witness"]["face_ids"]
    assert result["source_hash"] and result["result_hash"]


def test_coarse_candidate_cannot_fill_source_interior_depression():
    source_points = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
                     (0.5, 0.5, -1)]
    source, source_roles = _prism(
        source_points, [(0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4)])
    candidate, candidate_roles = _flat_square("02")

    result = certify_heightgraph_subset(
        source, candidate, _partition(source_roles, candidate_roles), _AXIS)

    assert result["status"] == "FAIL"
    assert result["reasons"][0]["code"] == "HEIGHT_RELATION_VIOLATED"
    assert result["witness"]["point_uv"] == ["1/2", "1/2"]
    assert result["witness"]["first_surface"] == "source.upper"
    assert result["witness"]["second_surface"] == "candidate.upper"
    assert result["source_hash"] and result["result_hash"]


def test_invalid_source_thickness_stays_unknown_before_candidate_relation():
    source_points = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
                     (0.5, 0.5, -3)]
    source, source_roles = _prism(
        source_points, [(0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4)])
    candidate, candidate_roles = _flat_square("02")

    result = certify_heightgraph_subset(
        source, candidate, _partition(source_roles, candidate_roles), _AXIS)

    assert result["status"] == "UNKNOWN"
    assert result["reasons"][0]["code"] == "SOURCE_HEIGHT_GRAPH_INVALID"
    assert result["result_hash"] is None


def test_crossing_overlay_edges_can_fail_between_all_original_vertices():
    # Both meshes agree at the four rim corners. Their different diagonals cross at
    # (1/2,1/2), where candidate height 1 exceeds source height 0.
    source, source_roles = _flat_square("02", corner_heights=(0, 1, 0, 1))
    candidate, candidate_roles = _flat_square("13", corner_heights=(0, 1, 0, 1))

    result = certify_heightgraph_subset(
        source, candidate, _partition(source_roles, candidate_roles), _AXIS)

    assert result["status"] == "FAIL"
    assert result["reasons"][0]["code"] == "HEIGHT_RELATION_VIOLATED"
    assert result["witness"]["point_uv"] == ["1/2", "1/2"]
    assert result["witness"]["first_minus_second"] == "-1"


def test_nonrectangular_hole_domain_is_unknown_even_when_face_vertices_are_in_material():
    # U = bottom bar plus left/right arms. The candidate triangle's three vertices
    # lie in U, but its centroid lies in the missing center. This first version only
    # certifies a complete rectangular projection domain, so it must fail closed.
    u_points = [(0, 0, 0), (3, 0, 0), (3, 1, 0), (0, 1, 0),
                (1, 1, 0), (2, 1, 0), (1, 3, 0), (0, 3, 0),
                (3, 3, 0), (2, 3, 0)]
    u_faces = [(0, 1, 2), (0, 2, 5), (0, 5, 4), (0, 4, 3),
               (3, 4, 6), (3, 6, 7), (5, 2, 8), (5, 8, 9)]
    source = SimpleNamespace(vertices=np.asarray(u_points, dtype=np.float64),
                             faces=np.asarray(u_faces, dtype=np.int64),
                             metadata=dict(_MESH_METADATA))
    source_roles = FacePartition(tuple(range(len(u_faces))), (), ())

    candidate = SimpleNamespace(
        vertices=np.asarray([(0.5, 2, 0), (1.5, 0.5, 0), (2.5, 2, 0)],
                            dtype=np.float64),
        faces=np.asarray([(0, 1, 2)], dtype=np.int64),
        metadata=dict(_MESH_METADATA),
    )
    candidate_roles = FacePartition((0,), (), ())
    partition = HeightGraphPartition(
        domain=RectangleDomain(0, 3, 0, 3), source=source_roles,
        candidate=candidate_roles, quality_limits=_QUALITY,
        coordinate_unit="mm", frame_id=_FRAME_ID,
    )

    result = certify_heightgraph_subset(source, candidate, partition, _AXIS)

    assert result["status"] == "UNKNOWN"
    assert result["reasons"][0]["code"] == "HEIGHT_PATCH_DOES_NOT_COVER_RECTANGLE"


def test_unsupported_mesh_type_and_exhausted_pair_budget_are_unknown():
    source, source_roles = _flat_square("02")
    candidate, candidate_roles = _flat_square("13")
    regular_partition = _partition(source_roles, candidate_roles)

    type_result = certify_heightgraph_subset(
        object(), candidate, regular_partition, _AXIS)
    budget_result = certify_heightgraph_subset(
        source, candidate,
        _partition(source_roles, candidate_roles, max_pair_checks=0), _AXIS)

    assert type_result["status"] == "UNKNOWN"
    assert type_result["reasons"][0]["code"] == "MESH_TYPE_UNSUPPORTED"
    assert budget_result["status"] == "UNKNOWN"
    assert budget_result["reasons"][0]["code"] == "PAIR_BUDGET_EXHAUSTED"


def test_source_candidate_coordinate_metadata_must_match_contract():
    source, source_roles = _flat_square("02")
    candidate, candidate_roles = _flat_square("13")
    partition = _partition(source_roles, candidate_roles)

    candidate.metadata["frame_id"] = "different-frame"
    frame_result = certify_heightgraph_subset(source, candidate, partition, _AXIS)
    candidate.metadata["frame_id"] = _FRAME_ID
    candidate.metadata["coordinate_unit"] = "cm"
    unit_result = certify_heightgraph_subset(source, candidate, partition, _AXIS)

    assert frame_result["status"] == "UNKNOWN"
    assert frame_result["reasons"][0]["code"] == "MESH_COORDINATE_METADATA_MISMATCH"
    assert unit_result["status"] == "UNKNOWN"
    assert unit_result["reasons"][0]["code"] == "MESH_COORDINATE_METADATA_MISMATCH"


class _DuckArray:
    """A deceptive array-like which must be rejected without calling tolist()."""

    def __init__(self, shape, dtype):
        self.shape = shape
        self.dtype = np.dtype(dtype)

    def tolist(self):
        raise AssertionError("non-ndarray inputs must be rejected before tolist()")


class _MisleadingShapeArray(np.ndarray):
    """An ndarray subclass with deceptive metadata; normalization must see base metadata."""

    @property
    def shape(self):
        return (1, 3)

    @property
    def dtype(self):
        return np.dtype(np.float64)

    @property
    def nbytes(self):
        return 24


def test_mesh_shape_and_size_limits_reject_before_array_list_conversion():
    candidate, candidate_roles = _flat_square("02")
    oversized_vertices = SimpleNamespace(
        vertices=np.zeros((5_001, 3), dtype=np.float64).view(_MisleadingShapeArray),
        faces=candidate.faces,
        metadata=dict(_MESH_METADATA),
    )
    oversized_faces = SimpleNamespace(
        vertices=candidate.vertices,
        faces=np.zeros((10_001, 3), dtype=np.int64),
        metadata=dict(_MESH_METADATA),
    )
    wrong_shape = SimpleNamespace(
        vertices=np.zeros((4, 4), dtype=np.float64),
        faces=candidate.faces,
        metadata=dict(_MESH_METADATA),
    )
    duck_array = SimpleNamespace(
        vertices=_DuckArray((1, 3), np.float64),
        faces=candidate.faces,
        metadata=dict(_MESH_METADATA),
    )
    partition = _partition(candidate_roles, candidate_roles)

    vertex_result = certify_heightgraph_subset(
        oversized_vertices, candidate, partition, _AXIS)
    face_result = certify_heightgraph_subset(
        oversized_faces, candidate, partition, _AXIS)
    shape_result = certify_heightgraph_subset(
        wrong_shape, candidate, partition, _AXIS)
    duck_result = certify_heightgraph_subset(
        duck_array, candidate, partition, _AXIS)

    assert vertex_result["status"] == "UNKNOWN"
    assert vertex_result["reasons"][0]["code"] == "MESH_ARRAY_LIMIT_EXCEEDED"
    assert face_result["status"] == "UNKNOWN"
    assert face_result["reasons"][0]["code"] == "MESH_ARRAY_LIMIT_EXCEEDED"
    assert shape_result["status"] == "UNKNOWN"
    assert shape_result["reasons"][0]["code"] == "MESH_ARRAY_SHAPE_INVALID"
    assert duck_result["status"] == "UNKNOWN"
    assert duck_result["reasons"][0]["code"] == "MESH_ARRAY_TYPE_UNSUPPORTED"


def test_pair_ceiling_and_external_rational_bit_caps_fail_closed():
    source, source_roles = _flat_square("02")
    candidate, candidate_roles = _flat_square("13")

    pair_result = certify_heightgraph_subset(
        source, candidate,
        _partition(source_roles, candidate_roles, max_pair_checks=250_001), _AXIS)
    domain_result = certify_heightgraph_subset(
        source, candidate,
        _partition(source_roles, candidate_roles,
                   domain=RectangleDomain(Fraction(1, 1 << 2_048), 1, 0, 1)), _AXIS)
    integer_domain_result = certify_heightgraph_subset(
        source, candidate,
        _partition(source_roles, candidate_roles,
                   domain=RectangleDomain(0, 1 << 2_048, 0, 1)), _AXIS)
    quality_result = certify_heightgraph_subset(
        source, candidate,
        _partition(source_roles, candidate_roles,
                   quality_limits=MeshQualityLimits(
                       min_q=Fraction(1, 1 << 2_048),
                       min_altitude_mm=1e-6, max_aspect_ratio=1_000_000)), _AXIS)
    too_many_role_ids = FacePartition(
        upper_faces=tuple(range(len(source.faces) + 1)),
        lower_faces=(), side_faces=(),
    )
    role_result = certify_heightgraph_subset(
        source, candidate, _partition(too_many_role_ids, candidate_roles), _AXIS)

    assert pair_result["status"] == "UNKNOWN"
    assert pair_result["reasons"][0]["code"] == "PAIR_BUDGET_INVALID"
    assert domain_result["status"] == "UNKNOWN"
    assert domain_result["reasons"][0]["code"] == "INPUT_RATIONAL_BIT_LIMIT_EXCEEDED"
    assert integer_domain_result["status"] == "UNKNOWN"
    assert integer_domain_result["reasons"][0]["code"] == "INPUT_RATIONAL_BIT_LIMIT_EXCEEDED"
    assert quality_result["status"] == "UNKNOWN"
    assert quality_result["reasons"][0]["code"] == "INPUT_RATIONAL_BIT_LIMIT_EXCEEDED"
    assert role_result["status"] == "UNKNOWN"
    assert role_result["reasons"][0]["code"] == "FACE_PARTITION_TOO_LARGE"
