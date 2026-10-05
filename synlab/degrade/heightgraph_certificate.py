"""Exact, deliberately restricted material-subset certificates for height-graph meshes.

This module is a diagnostic candidate. It is not wired into a degradation operator and does not
repair, move, simplify, or re-mesh geometry. A PASS applies only to a closed, consistently oriented
mesh pair whose complete face partitions describe the same rectangular projection domain, fixed
bottom surface, fixed vertical boundary curtain, and piecewise-linear upper surfaces. Unsupported
or unverified inputs return UNKNOWN.

All geometric predicates use :class:`fractions.Fraction` values created from the exact binary
float64 inputs. No tolerance, rounded projection, Shapely predicate, or sampled distance is used
as proof. A caller must provide explicit candidate triangle-quality limits as part of the typed
partition. SHA-256 binds the normalized exact geometry-array semantics; it does not authenticate a
source file, NPZ container, metadata, or physical provenance.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import math
import struct
from typing import Any, Iterable, Sequence

import numpy as np

__all__ = [
    "FacePartition",
    "HeightGraphAxis",
    "HeightGraphPartition",
    "MeshQualityLimits",
    "RectangleDomain",
    "certify_heightgraph_subset",
]

_Point2 = tuple[Fraction, Fraction]
_Point3 = tuple[Fraction, Fraction, Fraction]
_DEFAULT_MAX_VERTICES = 5_000
_DEFAULT_MAX_FACES = 10_000
_MAX_PAIR_CHECKS = 250_000
_MAX_INPUT_RATIONAL_BITS = 2_048
_MESH_HASH_ENCODING = (
    "SHA-256 over prefix 'synlab.heightgraph.mesh.exact-f64.v1\\0' || uint64_le(vertex_count) || "
    "each ordered XYZ coordinate as ASCII numerator/denominator; || uint64_le(face_count) || "
    "ordered face indices as uint64_le; normalized exact geometry-array semantics only, excluding "
    "metadata, input-file bytes, NPZ container bytes, and provenance"
)


@dataclass(frozen=True)
class HeightGraphAxis:
    """A coordinate-axis permutation/sign map into ``(u, v, h)`` coordinates.

    The map may permute the three input coordinates and reverse any axis. It cannot rotate,
    translate, or project the mesh. ``name`` records the degradation axis (for example ``P03``).
    """

    projection_axes: tuple[int, int] = (0, 1)
    projection_signs: tuple[int, int] = (1, 1)
    height_axis: int = 2
    height_sign: int = 1
    name: str = "P03"


@dataclass(frozen=True)
class RectangleDomain:
    """Closed rectangle in the exact projected ``(u, v)`` coordinates."""

    u_min: int | float | Fraction
    u_max: int | float | Fraction
    v_min: int | float | Fraction
    v_max: int | float | Fraction


@dataclass(frozen=True)
class FacePartition:
    """Complete, disjoint face IDs for one mesh's upper, lower, and side surfaces."""

    upper_faces: tuple[int, ...]
    lower_faces: tuple[int, ...]
    side_faces: tuple[int, ...]


@dataclass(frozen=True)
class MeshQualityLimits:
    """Required quality floor/ceiling for every delivered candidate triangle."""

    min_q: int | float | Fraction
    min_altitude_mm: int | float | Fraction
    max_aspect_ratio: int | float | Fraction


@dataclass(frozen=True)
class HeightGraphPartition:
    """Typed proof inputs for both meshes and a bounded exact overlay.

    ``max_pair_checks`` bounds all same-patch and cross-patch overlay pair work and cannot exceed
    250,000. All domain/quality integer or Fraction inputs are limited to 2,048 numerator and
    denominator bits. These are input and pair-count limits, not a formal bound on intermediate
    Fraction growth or whole-call runtime. Exhausting a budget produces UNKNOWN. Both mesh metadata
    objects must declare matching ``coordinate_unit=mm`` and
    non-empty ``frame_id`` values identical to this shared declaration. This checks a coordinate
    contract only; it does not authenticate the physical source. The initial implementation
    deliberately supports only a rectangular domain.
    """

    domain: RectangleDomain
    source: FacePartition
    candidate: FacePartition
    quality_limits: MeshQualityLimits
    coordinate_unit: str
    frame_id: str
    max_pair_checks: int = 250_000


@dataclass(frozen=True)
class _Mesh:
    name: str
    vertices: tuple[_Point3, ...]
    faces: tuple[tuple[int, int, int], ...]
    digest: str
    coordinate_unit: str
    frame_id: str


@dataclass(frozen=True)
class _Triangle:
    face_id: int
    vertex_ids: tuple[int, int, int]
    points: tuple[_Point2, _Point2, _Point2]
    values: tuple[Fraction, Fraction, Fraction]
    bounds: tuple[Fraction, Fraction, Fraction, Fraction]


@dataclass(frozen=True)
class _SideTriangle:
    face_id: int
    vertex_ids: tuple[int, int, int]
    points: tuple[_Point2, _Point2, _Point2]
    bounds: tuple[Fraction, Fraction, Fraction, Fraction]


@dataclass(frozen=True)
class _Patch:
    triangles: tuple[_Triangle, ...]
    boundary_edges: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class _SideCell:
    points: tuple[_Point2, ...]
    area: Fraction
    bounds: tuple[Fraction, Fraction, Fraction, Fraction]


class _CertificateIssue(Exception):
    def __init__(self, status: str, code: str, message: str,
                 witness: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.witness = witness


class _Budget:
    def __init__(self, maximum: int) -> None:
        self.maximum = maximum
        self.checked = 0

    def consume(self, *, context: str) -> None:
        if self.checked >= self.maximum:
            raise _CertificateIssue(
                "UNKNOWN", "PAIR_BUDGET_EXHAUSTED",
                f"exact overlay budget {self.maximum} exhausted during {context}",
                {"pair_checks": self.checked, "max_pair_checks": self.maximum,
                 "context": context},
            )
        self.checked += 1


def certify_heightgraph_subset(source: Any, candidate: Any,
                               partition: HeightGraphPartition,
                               axis: HeightGraphAxis) -> dict[str, Any]:
    """Certify ``candidate ⊆ source`` for the restricted rectangular height-graph case.

    Returns ``{"status", "reasons", "source_hash", "result_hash", "certificate"}`` and adds a
    rational ``witness`` on a proved contradiction. Invalid types, unsupported domains, incomplete
    partitions, and budget exhaustion return UNKNOWN. No input mesh is modified.
    """
    source_hash: str | None = None
    result_hash: str | None = None
    budget: _Budget | None = None
    try:
        if type(partition) is not HeightGraphPartition:
            raise _unsupported("PARTITION_TYPE_UNSUPPORTED",
                               "partition must be HeightGraphPartition")
        if type(axis) is not HeightGraphAxis:
            raise _unsupported("AXIS_TYPE_UNSUPPORTED", "axis must be HeightGraphAxis")
        _validate_axis(axis)
        _validate_coordinate_contract(partition)
        domain = _validate_domain(partition.domain)
        _validate_quality_limits(partition.quality_limits)
        if (type(partition.max_pair_checks) is not int
                or partition.max_pair_checks < 0
                or partition.max_pair_checks > _MAX_PAIR_CHECKS):
            raise _unsupported("PAIR_BUDGET_INVALID",
                               f"max_pair_checks must be an integer in [0, {_MAX_PAIR_CHECKS}]")

        source_mesh = _load_mesh(source, "source")
        source_hash = source_mesh.digest
        _validate_source_coordinate_metadata(source_mesh, partition)
        _validate_face_partition(source_mesh, partition.source)
        budget = _Budget(partition.max_pair_checks)

        source_uvh = tuple(_transform(point, axis) for point in source_mesh.vertices)
        expected_orientation = _axis_determinant_sign(axis)

        source_upper = _make_patch(source_mesh, partition.source.upper_faces, source_uvh,
                                   domain, "upper", "source", expected_orientation, budget)
        source_lower = _make_patch(source_mesh, partition.source.lower_faces, source_uvh,
                                   domain, "lower", "source", -expected_orientation, budget)

        _check_height_overlay(source_upper.triangles, source_lower.triangles,
                              "source upper minus source lower", "positive",
                              domain, budget, contradiction_owner="source",
                              first_surface="source.upper", second_surface="source.lower")
        _check_sides(source_mesh, partition.source, source_uvh, source_upper, source_lower,
                     domain, "source", budget)
        _validate_closed_mesh(source_mesh, partition.source, "source", axis, domain)

        # Candidate-derived FAIL results are meaningful only after the source has passed every
        # structural and positive-thickness premise of this restricted proof.
        candidate_mesh = _load_mesh(candidate, "candidate")
        result_hash = candidate_mesh.digest
        _validate_mesh_coordinate_metadata(source_mesh, candidate_mesh, partition)
        _validate_face_partition(candidate_mesh, partition.candidate)
        candidate_uvh = tuple(_transform(point, axis) for point in candidate_mesh.vertices)
        candidate_upper = _make_patch(candidate_mesh, partition.candidate.upper_faces,
                                      candidate_uvh, domain, "upper", "candidate",
                                      expected_orientation, budget)
        candidate_lower = _make_patch(candidate_mesh, partition.candidate.lower_faces,
                                      candidate_uvh, domain, "lower", "candidate",
                                      -expected_orientation, budget)

        _check_height_overlay(source_upper.triangles, candidate_upper.triangles,
                              "source upper minus candidate upper", "nonnegative",
                              domain, budget, contradiction_owner="candidate",
                              first_surface="source.upper", second_surface="candidate.upper")
        _check_height_overlay(source_lower.triangles, candidate_lower.triangles,
                              "source lower minus candidate lower", "zero",
                              domain, budget, contradiction_owner="candidate",
                              first_surface="source.lower", second_surface="candidate.lower")
        _check_height_overlay(candidate_upper.triangles, candidate_lower.triangles,
                              "candidate upper minus candidate lower", "positive",
                              domain, budget, contradiction_owner="candidate",
                              first_surface="candidate.upper", second_surface="candidate.lower")

        _check_fixed_rim(source_upper, source_lower, source_uvh,
                         candidate_upper, candidate_lower, candidate_uvh, domain)
        _check_sides(candidate_mesh, partition.candidate, candidate_uvh,
                     candidate_upper, candidate_lower, domain, "candidate", budget)

        _validate_closed_mesh(candidate_mesh, partition.candidate, "candidate", axis, domain)
        quality = _validate_candidate_quality(candidate_mesh, partition.quality_limits)

        return {
            "status": "PASS",
            "reasons": [],
            "source_hash": source_hash,
            "result_hash": result_hash,
            "certificate": {
                "algorithm": "exact_fraction_rectangular_heightgraph_subset_v1",
                "axis": _axis_dict(axis),
                "coordinate_unit": partition.coordinate_unit,
                "frame_id": partition.frame_id,
                "coordinate_metadata_scope": "declared_and_matched_only_not_source_authentication",
                "mesh_hash_encoding": _MESH_HASH_ENCODING,
                "mesh_limits": {"max_vertices": _DEFAULT_MAX_VERTICES,
                                "max_faces": _DEFAULT_MAX_FACES},
                "input_rational_bit_limit": _MAX_INPUT_RATIONAL_BITS,
                "pair_count_ceiling": _MAX_PAIR_CHECKS,
                "resource_bound_scope": (
                    "array element caps, bounded input rationals, and bbox candidate-pair count; "
                    "no formal bound on intermediate Fraction bit growth or whole-call runtime"
                ),
                "domain_exact": [_fraction_text(value) for value in domain],
                "relation": "candidate_subset_of_source",
                "proved_inequalities": ["b_source < s_source", "b_candidate < c_candidate",
                                        "b_candidate == b_source", "c_candidate <= s_source",
                                        "source_and_candidate_rim_traces_equal"],
                "source_faces": len(source_mesh.faces),
                "candidate_faces": len(candidate_mesh.faces),
                "source_patch_faces": {
                    "upper": len(source_upper.triangles),
                    "lower": len(source_lower.triangles),
                    "side": len(partition.source.side_faces),
                },
                "candidate_patch_faces": {
                    "upper": len(candidate_upper.triangles),
                    "lower": len(candidate_lower.triangles),
                    "side": len(partition.candidate.side_faces),
                },
                "exact_pair_checks": budget.checked,
                "max_pair_checks": budget.maximum,
                "candidate_quality": quality,
                "scope_limit": "coordinate-axis permutation/sign changes; one rectangular domain",
            },
        }
    except _CertificateIssue as issue:
        result: dict[str, Any] = {
            "status": issue.status,
            "reasons": [{"code": issue.code, "message": issue.message}],
            "source_hash": source_hash,
            "result_hash": result_hash,
            "certificate": None,
        }
        if issue.witness is not None:
            result["witness"] = issue.witness
        if budget is not None:
            result["pair_checks"] = budget.checked
        return result
    except Exception as exc:  # structured fail-closed boundary for malformed third-party objects
        return {
            "status": "UNKNOWN",
            "reasons": [{"code": "VALIDATION_INPUT_ERROR",
                         "message": f"{type(exc).__name__}: {exc}"}],
            "source_hash": source_hash,
            "result_hash": result_hash,
            "certificate": None,
            **({"pair_checks": budget.checked} if budget is not None else {}),
        }


def _unsupported(code: str, message: str,
                 witness: dict[str, Any] | None = None) -> _CertificateIssue:
    return _CertificateIssue("UNKNOWN", code, message, witness)


def _contradiction(code: str, message: str,
                   witness: dict[str, Any] | None = None) -> _CertificateIssue:
    return _CertificateIssue("FAIL", code, message, witness)


def _validate_axis(axis: HeightGraphAxis) -> None:
    if (not isinstance(axis.projection_axes, tuple) or len(axis.projection_axes) != 2
            or not isinstance(axis.projection_signs, tuple) or len(axis.projection_signs) != 2):
        raise _unsupported("AXIS_SPEC_INVALID", "axis coordinate fields must be fixed tuples")
    axes = (*axis.projection_axes, axis.height_axis)
    if any(isinstance(value, bool) or not isinstance(value, int) for value in axes):
        raise _unsupported("AXIS_SPEC_INVALID", "coordinate axis indices must be integers")
    if tuple(sorted(axes)) != (0, 1, 2):
        raise _unsupported("AXIS_SPEC_INVALID", "axis must be a permutation of coordinates 0,1,2")
    signs = (*axis.projection_signs, axis.height_sign)
    if any(isinstance(value, bool) or not isinstance(value, int)
           or value not in (-1, 1) for value in signs):
        raise _unsupported("AXIS_SPEC_INVALID", "axis signs must be +1 or -1")
    if not isinstance(axis.name, str) or not axis.name.strip():
        raise _unsupported("AXIS_SPEC_INVALID", "axis name must be a non-empty string")


def _validate_coordinate_contract(partition: HeightGraphPartition) -> None:
    if partition.coordinate_unit != "mm":
        raise _unsupported("COORDINATE_UNIT_UNSUPPORTED",
                           "height-graph coordinates must be declared in millimetres")
    if not isinstance(partition.frame_id, str) or not partition.frame_id.strip():
        raise _unsupported("COORDINATE_FRAME_INVALID",
                           "a non-empty shared coordinate frame_id is required")


def _axis_determinant_sign(axis: HeightGraphAxis) -> int:
    permutation = (*axis.projection_axes, axis.height_axis)
    inversions = sum(permutation[i] > permutation[j]
                     for i in range(3) for j in range(i + 1, 3))
    parity = -1 if inversions % 2 else 1
    return parity * axis.projection_signs[0] * axis.projection_signs[1] * axis.height_sign


def _axis_dict(axis: HeightGraphAxis) -> dict[str, Any]:
    return {"name": axis.name, "projection_axes": list(axis.projection_axes),
            "projection_signs": list(axis.projection_signs),
            "height_axis": axis.height_axis, "height_sign": axis.height_sign}


def _check_rational_bit_limit(numerator: int, denominator: int, *, context: str) -> None:
    if (abs(numerator).bit_length() > _MAX_INPUT_RATIONAL_BITS
            or denominator.bit_length() > _MAX_INPUT_RATIONAL_BITS):
        raise _unsupported(
            "INPUT_RATIONAL_BIT_LIMIT_EXCEEDED",
            f"{context} numerator/denominator exceeds {_MAX_INPUT_RATIONAL_BITS} bits",
            {"context": context, "maximum_bits": _MAX_INPUT_RATIONAL_BITS},
        )


def _to_fraction(value: Any, *, context: str) -> Fraction:
    if isinstance(value, np.generic):
        value = value.item()
    if type(value) is bool:
        raise _unsupported("NON_NUMERIC_COORDINATE", f"boolean value in {context}")
    if type(value) is Fraction:
        _check_rational_bit_limit(value.numerator, value.denominator, context=context)
        return value
    if type(value) is int:
        _check_rational_bit_limit(value, 1, context=context)
        return Fraction(value)
    if type(value) is not float:
        raise _unsupported("NON_FLOAT64_COORDINATE",
                           f"{context} must be represented by integer, Fraction, or float64 values")
    if not math.isfinite(value):
        raise _unsupported("NONFINITE_COORDINATE", f"non-finite coordinate in {context}")
    numerator, denominator = value.as_integer_ratio()
    _check_rational_bit_limit(numerator, denominator, context=context)
    return Fraction(numerator, denominator)


def _validate_domain(value: Any) -> tuple[Fraction, Fraction, Fraction, Fraction]:
    if type(value) is not RectangleDomain:
        raise _unsupported("DOMAIN_TYPE_UNSUPPORTED",
                           "only typed RectangleDomain projection domains are supported")
    bounds = (
        _to_fraction(value.u_min, context="domain.u_min"),
        _to_fraction(value.u_max, context="domain.u_max"),
        _to_fraction(value.v_min, context="domain.v_min"),
        _to_fraction(value.v_max, context="domain.v_max"),
    )
    if bounds[0] >= bounds[1] or bounds[2] >= bounds[3]:
        raise _unsupported("DOMAIN_BOUNDS_INVALID", "rectangle bounds must have positive extent")
    return bounds


def _validate_quality_limits(value: Any) -> None:
    if type(value) is not MeshQualityLimits:
        raise _unsupported("QUALITY_LIMITS_REQUIRED",
                           "typed candidate q/altitude/aspect limits are required")
    numbers = (value.min_q, value.min_altitude_mm, value.max_aspect_ratio)
    fractions = tuple(_to_fraction(number, context=f"quality_limits[{index}]")
                      for index, number in enumerate(numbers))
    if (fractions[0] <= 0 or fractions[1] <= 0 or fractions[2] < 1):
        raise _unsupported("QUALITY_LIMITS_INVALID",
                           "min_q/min_altitude_mm must be positive and max_aspect_ratio >= 1")


def _load_mesh(value: Any, name: str) -> _Mesh:
    if value is None or not hasattr(value, "vertices") or not hasattr(value, "faces"):
        raise _unsupported("MESH_TYPE_UNSUPPORTED", f"{name} must expose vertices and faces")
    raw_vertices = _base_numpy_array(value.vertices, "vertices", name)
    raw_faces = _base_numpy_array(value.faces, "faces", name)
    _validate_mesh_array_shape(raw_vertices, "vertices", name, _DEFAULT_MAX_VERTICES)
    _validate_mesh_array_shape(raw_faces, "faces", name, _DEFAULT_MAX_FACES)
    if raw_vertices.dtype.kind != "f" or raw_vertices.dtype.itemsize != 8:
        raise _unsupported("VERTEX_DTYPE_UNSUPPORTED", f"{name} vertices must be float64")
    if raw_faces.dtype.kind not in ("i", "u") or raw_faces.dtype.itemsize > 8:
        raise _unsupported("FACE_DTYPE_UNSUPPORTED", f"{name} faces must have integer dtype")
    raw_metadata = getattr(value, "metadata", None)
    if not isinstance(raw_metadata, Mapping):
        raise _unsupported("MESH_COORDINATE_METADATA_MISSING",
                           f"{name} mesh metadata must declare coordinate_unit and frame_id")
    coordinate_unit = raw_metadata.get("coordinate_unit")
    frame_id = raw_metadata.get("frame_id")
    if not isinstance(coordinate_unit, str) or not coordinate_unit.strip():
        raise _unsupported("MESH_COORDINATE_METADATA_INVALID",
                           f"{name} coordinate_unit metadata must be a non-empty string")
    if not isinstance(frame_id, str) or not frame_id.strip():
        raise _unsupported("MESH_COORDINATE_METADATA_INVALID",
                           f"{name} frame_id metadata must be a non-empty string")
    try:
        vertex_rows = raw_vertices.tolist()
        face_rows = raw_faces.tolist()
    except Exception as exc:
        raise _unsupported("MESH_ARRAYS_UNREADABLE",
                           f"{name} arrays could not be read: {type(exc).__name__}") from exc
    if not isinstance(vertex_rows, list) or not vertex_rows:
        raise _unsupported("MESH_VERTICES_INVALID", f"{name} must have vertices")
    if len(vertex_rows) != raw_vertices.shape[0]:
        raise _unsupported("MESH_ARRAY_SHAPE_INVALID",
                           f"{name} vertex conversion changed the verified row count")
    vertices_list: list[_Point3] = []
    for index, row in enumerate(vertex_rows):
        if not isinstance(row, (list, tuple)) or len(row) != 3:
            raise _unsupported("MESH_VERTEX_SHAPE_INVALID",
                               f"{name} vertex {index} is not a 3-vector")
        vertices_list.append(tuple(_to_fraction(x, context=f"{name}.vertices[{index}]")
                                   for x in row))  # type: ignore[arg-type]
    if not isinstance(face_rows, list) or not face_rows:
        raise _unsupported("MESH_FACES_INVALID", f"{name} must have faces")
    if len(face_rows) != raw_faces.shape[0]:
        raise _unsupported("MESH_ARRAY_SHAPE_INVALID",
                           f"{name} face conversion changed the verified row count")
    faces: list[tuple[int, int, int]] = []
    for face_id, row in enumerate(face_rows):
        if not isinstance(row, (list, tuple)) or len(row) != 3:
            raise _unsupported("MESH_FACE_SHAPE_INVALID",
                               f"{name} face {face_id} is not a triangle")
        if any(isinstance(index, bool) or not isinstance(index, int) for index in row):
            raise _unsupported("MESH_FACE_INDEX_INVALID",
                               f"{name} face {face_id} has a non-integer index")
        face = tuple(int(index) for index in row)
        if len(set(face)) != 3 or min(face) < 0 or max(face) >= len(vertices_list):
            raise _unsupported("MESH_FACE_INDEX_INVALID",
                               f"{name} face {face_id} has duplicate/out-of-range indices")
        faces.append(face)  # type: ignore[arg-type]
    digest = _mesh_digest(vertices_list, faces)
    if len(set(vertices_list)) != len(vertices_list):
        raise _unsupported("DUPLICATE_MESH_VERTICES",
                           f"{name} has duplicate exact 3D vertex coordinates")
    return _Mesh(name, tuple(vertices_list), tuple(faces), digest,
                 coordinate_unit, frame_id)


def _base_numpy_array(value: Any, role: str, name: str) -> np.ndarray:
    if not isinstance(value, np.ndarray):
        raise _unsupported("MESH_ARRAY_TYPE_UNSUPPORTED",
                           f"{name} {role} must be a NumPy ndarray")
    try:
        # Call the ndarray descriptor directly to ignore subclass overrides of view/shape/dtype.
        base_array = np.ndarray.view(value, type=np.ndarray)
    except Exception as exc:
        raise _unsupported("MESH_ARRAY_TYPE_UNSUPPORTED",
                           f"{name} {role} cannot be normalized to a base ndarray: "
                           f"{type(exc).__name__}") from exc
    return base_array


def _validate_mesh_array_shape(array: np.ndarray, role: str, name: str, maximum: int) -> None:
    shape = array.shape
    if len(shape) != 2:
        raise _unsupported("MESH_ARRAY_SHAPE_INVALID",
                           f"{name} {role} must be a rank-2 Nx3 array")
    rows, columns = shape
    if columns != 3:
        raise _unsupported("MESH_ARRAY_SHAPE_INVALID",
                           f"{name} {role} array must have shape Nx3")
    if rows <= 0:
        raise _unsupported("MESH_ARRAY_EMPTY", f"{name} {role} array must be non-empty")
    if rows > maximum:
        raise _unsupported(
            "MESH_ARRAY_LIMIT_EXCEEDED",
            f"{name} {role} count {rows} exceeds the certificate limit {maximum}",
            {"mesh": name, "array": role, "count": rows, "maximum": maximum},
        )
    maximum_bytes = maximum * 3 * 8
    expected_bytes = rows * columns * array.dtype.itemsize
    if array.nbytes != expected_bytes or array.nbytes > maximum_bytes:
        raise _unsupported(
            "MESH_ARRAY_NBYTES_INVALID",
            f"{name} {role} logical bytes do not match its verified shape/dtype limit",
            {"mesh": name, "array": role, "nbytes": array.nbytes,
             "expected_nbytes": expected_bytes, "maximum_nbytes": maximum_bytes},
        )


def _validate_mesh_coordinate_metadata(source: _Mesh, candidate: _Mesh,
                                       partition: HeightGraphPartition) -> None:
    _validate_source_coordinate_metadata(source, partition)
    source_metadata = (source.coordinate_unit, source.frame_id)
    candidate_metadata = (candidate.coordinate_unit, candidate.frame_id)
    if source_metadata != candidate_metadata:
        raise _unsupported(
            "MESH_COORDINATE_METADATA_MISMATCH",
            "source and candidate coordinate_unit/frame_id metadata must match",
            {"source": {"coordinate_unit": source.coordinate_unit,
                        "frame_id": source.frame_id},
             "candidate": {"coordinate_unit": candidate.coordinate_unit,
                          "frame_id": candidate.frame_id}},
        )
    if candidate_metadata != (partition.coordinate_unit, partition.frame_id):
        raise _unsupported(
            "MESH_COORDINATE_METADATA_MISMATCH",
            "candidate mesh metadata must match the typed partition contract",
            {"declared": {"coordinate_unit": partition.coordinate_unit,
                           "frame_id": partition.frame_id},
             "candidate": {"coordinate_unit": candidate.coordinate_unit,
                           "frame_id": candidate.frame_id}},
        )


def _validate_source_coordinate_metadata(mesh: _Mesh,
                                         partition: HeightGraphPartition) -> None:
    source_metadata = (mesh.coordinate_unit, mesh.frame_id)
    declared_metadata = (partition.coordinate_unit, partition.frame_id)
    if source_metadata != declared_metadata:
        raise _unsupported(
            "MESH_COORDINATE_METADATA_MISMATCH",
            "source mesh metadata must match the typed partition contract",
            {"declared": {"coordinate_unit": partition.coordinate_unit,
                           "frame_id": partition.frame_id},
             "source": {"coordinate_unit": mesh.coordinate_unit,
                        "frame_id": mesh.frame_id}},
        )


def _mesh_digest(vertices: Sequence[_Point3], faces: Sequence[tuple[int, int, int]]) -> str:
    """Hash normalized exact mesh-array geometry; this is not a source/artifact identity hash."""
    digest = hashlib.sha256()
    digest.update(b"synlab.heightgraph.mesh.exact-f64.v1\0")
    digest.update(struct.pack("<Q", len(vertices)))
    for point in vertices:
        for coordinate in point:
            digest.update(f"{coordinate.numerator}/{coordinate.denominator};".encode("ascii"))
    digest.update(struct.pack("<Q", len(faces)))
    for face in faces:
        for index in face:
            digest.update(struct.pack("<Q", index))
    return digest.hexdigest()


def _transform(point: _Point3, axis: HeightGraphAxis) -> _Point3:
    u = point[axis.projection_axes[0]] * axis.projection_signs[0]
    v = point[axis.projection_axes[1]] * axis.projection_signs[1]
    h = point[axis.height_axis] * axis.height_sign
    return u, v, h


def _validate_face_partition(mesh: _Mesh, faceset: FacePartition) -> None:
    if type(faceset) is not FacePartition:
        raise _unsupported("FACE_PARTITION_TYPE_UNSUPPORTED",
                           f"{mesh.name} faces require typed FacePartition")
    groups = (faceset.upper_faces, faceset.lower_faces, faceset.side_faces)
    if any(type(group) is not tuple for group in groups):
        raise _unsupported("FACE_PARTITION_NOT_IMMUTABLE",
                           f"{mesh.name} face role lists must be tuples")
    if any(len(group) > len(mesh.faces) for group in groups):
        raise _unsupported("FACE_PARTITION_TOO_LARGE",
                           f"{mesh.name} face role list cannot exceed mesh face count",
                           {"mesh": mesh.name, "max_face_ids": len(mesh.faces)})
    flattened: list[int] = []
    for role, group in zip(("upper", "lower", "side"), groups):
        if any(isinstance(face_id, bool) or not isinstance(face_id, int)
               for face_id in group):
            raise _unsupported("FACE_PARTITION_INDEX_INVALID",
                               f"{mesh.name} {role} face IDs must be integers")
        if len(set(group)) != len(group):
            raise _unsupported("FACE_PARTITION_DUPLICATE_ID",
                               f"{mesh.name} {role} face IDs contain duplicates")
        if any(face_id < 0 or face_id >= len(mesh.faces) for face_id in group):
            raise _unsupported("FACE_PARTITION_INDEX_INVALID",
                               f"{mesh.name} {role} face ID is out of range")
        flattened.extend(group)
    if len(flattened) != len(mesh.faces) or set(flattened) != set(range(len(mesh.faces))):
        raise _unsupported("FACE_PARTITION_INCOMPLETE",
                           f"{mesh.name} upper/lower/side partition must cover every face once")


def _make_patch(mesh: _Mesh, face_ids: tuple[int, ...], uvh: Sequence[_Point3],
                domain: tuple[Fraction, Fraction, Fraction, Fraction], role: str,
                owner: str, orientation_sign: int, budget: _Budget) -> _Patch:
    if not face_ids:
        raise _unsupported("HEIGHT_PATCH_EMPTY", f"{owner} {role} patch has no faces")
    triangles: list[_Triangle] = []
    for face_id in face_ids:
        ids = mesh.faces[face_id]
        points = tuple((uvh[index][0], uvh[index][1]) for index in ids)
        values = tuple(uvh[index][2] for index in ids)
        signed = _orient(points[0], points[1], points[2])
        if signed == 0:
            raise _unsupported(
                "FACE_NOT_A_HEIGHT_GRAPH",
                f"{owner} {role} face {face_id} has zero projected area",
                {"mesh": owner, "role": role, "face_id": face_id},
            )
        if (1 if signed > 0 else -1) != orientation_sign:
            _raise_owner_issue(owner, "FACE_ORIENTATION_INVALID",
                              f"{owner} {role} face {face_id} has inconsistent orientation",
                              {"mesh": owner, "role": role, "face_id": face_id})
        if any(not _inside_domain(point, domain) for point in points):
            raise _unsupported(
                "HEIGHT_PATCH_OUTSIDE_DOMAIN",
                f"{owner} {role} face {face_id} leaves the declared rectangle",
                {"mesh": owner, "role": role, "face_id": face_id},
            )
        bounds = _bounds(points)
        triangles.append(_Triangle(face_id, ids, points, values, bounds))

    _check_triangle_patch_overlaps(triangles, owner, role, budget)
    patch = _validate_patch_boundary(mesh, triangles, uvh, domain, owner, role)
    return patch


def _raise_owner_issue(owner: str, code: str, message: str,
                       witness: dict[str, Any] | None = None) -> None:
    if owner == "candidate":
        raise _contradiction(code, message, witness)
    raise _unsupported(code, message, witness)


def _validate_patch_boundary(mesh: _Mesh, triangles: Sequence[_Triangle], uvh: Sequence[_Point3],
                             domain: tuple[Fraction, Fraction, Fraction, Fraction], owner: str,
                             role: str) -> _Patch:
    incidence: dict[tuple[int, int], list[tuple[int, int, int]]] = {}
    area2_sum = Fraction(0)
    for triangle in triangles:
        ids = triangle.vertex_ids
        area2_sum += abs(_orient(*triangle.points))
        for start, end in ((ids[0], ids[1]), (ids[1], ids[2]), (ids[2], ids[0])):
            key = (min(start, end), max(start, end))
            incidence.setdefault(key, []).append((triangle.face_id, start, end))
    expected_area2 = 2 * (domain[1] - domain[0]) * (domain[3] - domain[2])
    if area2_sum != expected_area2:
        raise _unsupported(
            "HEIGHT_PATCH_DOES_NOT_COVER_RECTANGLE",
            f"{owner} {role} patch projected area does not equal the declared rectangle",
            {"mesh": owner, "role": role,
             "patch_area2": _fraction_text(area2_sum),
             "domain_area2": _fraction_text(expected_area2)},
        )

    boundary: list[tuple[int, int]] = []
    for edge, rows in incidence.items():
        if len(rows) == 1:
            boundary.append(edge)
        elif len(rows) != 2:
            _raise_owner_issue(owner, "PATCH_EDGE_NONMANIFOLD",
                              f"{owner} {role} patch edge {edge} has {len(rows)} incident faces",
                              {"mesh": owner, "role": role, "edge_vertex_ids": list(edge),
                               "face_ids": [row[0] for row in rows]})
        elif rows[0][1:] == rows[1][1:]:
            _raise_owner_issue(owner, "PATCH_EDGE_ORIENTATION_CONFLICT",
                              f"{owner} {role} adjacent faces orient edge {edge} the same way",
                              {"mesh": owner, "role": role, "edge_vertex_ids": list(edge),
                               "face_ids": [rows[0][0], rows[1][0]]})
    if not boundary:
        raise _unsupported("PATCH_BOUNDARY_MISSING",
                           f"{owner} {role} patch has no rectangle boundary")

    boundary_neighbors: dict[int, set[int]] = {}
    side_intervals: dict[int, list[tuple[Fraction, Fraction]]] = {i: [] for i in range(4)}
    for a, b in boundary:
        boundary_neighbors.setdefault(a, set()).add(b)
        boundary_neighbors.setdefault(b, set()).add(a)
        ua, va, _ha = uvh[a]
        ub, vb, _hb = uvh[b]
        side = _edge_rectangle_side((ua, va), (ub, vb), domain)
        if side is None:
            raise _unsupported(
                "PATCH_BOUNDARY_NOT_RECTANGULAR",
                f"{owner} {role} patch boundary edge {(a, b)} is not on one rectangle side",
                {"mesh": owner, "role": role, "edge_vertex_ids": [a, b]},
            )
        t0, t1 = _edge_parameter(side, (ua, va), (ub, vb))
        lo, hi = sorted((t0, t1))
        if lo == hi:
            raise _unsupported("PATCH_BOUNDARY_ZERO_LENGTH",
                               f"{owner} {role} patch has a projected zero-length boundary edge")
        side_intervals[side].append((lo, hi))

    if any(len(neighbors) != 2 for neighbors in boundary_neighbors.values()):
        raise _unsupported("PATCH_BOUNDARY_NOT_A_CYCLE",
                           f"{owner} {role} patch boundary has a branch or open endpoint")
    pending = [next(iter(boundary_neighbors))]
    visited: set[int] = set()
    while pending:
        vertex = pending.pop()
        if vertex in visited:
            continue
        visited.add(vertex)
        pending.extend(boundary_neighbors[vertex] - visited)
    if visited != set(boundary_neighbors):
        raise _unsupported("PATCH_BOUNDARY_MULTIPLE_CYCLES",
                           f"{owner} {role} patch has multiple boundary cycles")

    for side in range(4):
        lo, hi = _side_parameter_bounds(side, domain)
        intervals = sorted(side_intervals[side])
        if not intervals:
            raise _unsupported("PATCH_RECTANGLE_SIDE_MISSING",
                               f"{owner} {role} patch omits rectangle side {side}")
        cursor = lo
        for start, end in intervals:
            if start != cursor or end <= start:
                raise _unsupported(
                    "PATCH_RECTANGLE_SIDE_GAP_OR_OVERLAP",
                    f"{owner} {role} boundary does not tile rectangle side {side} exactly",
                    {"mesh": owner, "role": role, "side": side,
                     "expected_cursor": _fraction_text(cursor),
                     "next_interval": [_fraction_text(start), _fraction_text(end)]},
                )
            cursor = end
        if cursor != hi:
            raise _unsupported("PATCH_RECTANGLE_SIDE_INCOMPLETE",
                               f"{owner} {role} boundary does not reach rectangle side endpoint")
    return _Patch(tuple(triangles), tuple(boundary))


def _check_triangle_patch_overlaps(triangles: Sequence[_Triangle], owner: str, role: str,
                                   budget: _Budget) -> None:
    for left, right in _same_bbox_pairs(triangles, budget, f"{owner}.{role}.self_overlay"):
        polygon = _triangle_intersection(left.points, right.points)
        if not polygon:
            continue
        if _polygon_area(polygon) > 0:
            _raise_owner_issue(
                owner, "PROJECTED_TRIANGLES_OVERLAP",
                f"{owner} {role} faces {left.face_id} and {right.face_id} overlap in positive area",
                {"mesh": owner, "role": role,
                 "face_ids": [left.face_id, right.face_id],
                 "overlap_polygon_uv": _points_text(polygon)},
            )
        shared_ids = set(left.vertex_ids) & set(right.vertex_ids)
        expected = {left.points[left.vertex_ids.index(index)] for index in shared_ids}
        actual = set(polygon)
        if actual != expected:
            _raise_owner_issue(
                owner, "PROJECTED_TRIANGLE_NONCONFORMITY",
                f"{owner} {role} faces {left.face_id} and {right.face_id} touch without exact shared topology",
                {"mesh": owner, "role": role,
                 "face_ids": [left.face_id, right.face_id],
                 "shared_vertex_ids": sorted(shared_ids),
                 "expected_contact_uv": _points_text(tuple(sorted(expected))),
                 "actual_contact_uv": _points_text(tuple(sorted(actual)))}
            )


def _check_height_overlay(first: Sequence[_Triangle], second: Sequence[_Triangle], label: str,
                          condition: str, domain: tuple[Fraction, Fraction, Fraction, Fraction],
                          budget: _Budget, *, contradiction_owner: str,
                          first_surface: str, second_surface: str) -> None:
    positive_area = Fraction(0)
    for left, right in _cross_bbox_pairs(first, second, budget, label):
        polygon = _triangle_intersection(left.points, right.points)
        if not polygon:
            continue
        positive_area += _polygon_area(polygon)
        for point in polygon:
            first_value = _linear_value(left, point)
            second_value = _linear_value(right, point)
            difference = first_value - second_value
            bad = ((condition == "nonnegative" and difference < 0)
                   or (condition == "positive" and difference <= 0)
                   or (condition == "zero" and difference != 0))
            if bad:
                witness = {
                    "comparison": label,
                    "first_surface": first_surface,
                    "first_face_id": left.face_id,
                    "second_surface": second_surface,
                    "second_face_id": right.face_id,
                    "point_uv": _point_text(point),
                    "first_height": _fraction_text(first_value),
                    "second_height": _fraction_text(second_value),
                    "first_minus_second": _fraction_text(difference),
                }
                message = f"height comparison {label!r} violates {condition} at an exact overlay vertex"
                if contradiction_owner == "candidate":
                    raise _contradiction("HEIGHT_RELATION_VIOLATED", message, witness)
                raise _unsupported("SOURCE_HEIGHT_GRAPH_INVALID", message, witness)
    expected_area = (domain[1] - domain[0]) * (domain[3] - domain[2])
    if positive_area != expected_area:
        raise _unsupported("OVERLAY_DOES_NOT_COVER_DOMAIN",
                           f"overlay for {label!r} did not cover the full rectangle",
                           {"comparison": label,
                            "overlay_area": _fraction_text(positive_area),
                            "domain_area": _fraction_text(expected_area)})


def _check_fixed_rim(source_upper: _Patch, source_lower: _Patch, source_uvh: Sequence[_Point3],
                     candidate_upper: _Patch, candidate_lower: _Patch,
                     candidate_uvh: Sequence[_Point3],
                     domain: tuple[Fraction, Fraction, Fraction, Fraction]) -> None:
    for role, source_patch, candidate_patch in (
        ("upper", source_upper, candidate_upper), ("lower", source_lower, candidate_lower)):
        for side in range(4):
            source_trace = _trace_segments(source_patch, source_uvh, side, domain)
            candidate_trace = _trace_segments(candidate_patch, candidate_uvh, side, domain)
            knots = sorted({point for segment in (*source_trace, *candidate_trace)
                            for point in segment[:2]})
            for parameter in knots:
                source_value = _trace_value(source_trace, parameter)
                candidate_value = _trace_value(candidate_trace, parameter)
                if source_value != candidate_value:
                    raise _contradiction(
                        "RIM_TRACE_CHANGED",
                        f"candidate {role} trace differs from source on rectangle side {side}",
                        {"role": role, "side": side,
                         "parameter": _fraction_text(parameter),
                         "source_height": _fraction_text(source_value),
                         "candidate_height": _fraction_text(candidate_value)},
                    )


def _trace_segments(patch: _Patch, uvh: Sequence[_Point3], side: int,
                    domain: tuple[Fraction, Fraction, Fraction, Fraction]
                    ) -> tuple[tuple[Fraction, Fraction, Fraction, Fraction], ...]:
    segments: list[tuple[Fraction, Fraction, Fraction, Fraction]] = []
    for a, b in patch.boundary_edges:
        pa, pb = uvh[a], uvh[b]
        edge_side = _edge_rectangle_side((pa[0], pa[1]), (pb[0], pb[1]), domain)
        if edge_side != side:
            continue
        ta, tb = _edge_parameter(side, (pa[0], pa[1]), (pb[0], pb[1]))
        if ta < tb:
            segments.append((ta, tb, pa[2], pb[2]))
        else:
            segments.append((tb, ta, pb[2], pa[2]))
    segments.sort(key=lambda segment: (segment[0], segment[1]))
    lo, hi = _side_parameter_bounds(side, domain)
    cursor = lo
    for start, end, _h0, _h1 in segments:
        if start != cursor:
            raise _unsupported("BOUNDARY_TRACE_NOT_TILED",
                               f"height trace does not tile rectangle side {side}")
        cursor = end
    if cursor != hi:
        raise _unsupported("BOUNDARY_TRACE_NOT_TILED",
                           f"height trace does not reach rectangle side {side} endpoint")
    return tuple(segments)


def _trace_value(segments: Sequence[tuple[Fraction, Fraction, Fraction, Fraction]],
                 parameter: Fraction) -> Fraction:
    found: set[Fraction] = set()
    index = bisect_right(segments, parameter, key=lambda segment: segment[0])
    for candidate_index in (index - 1, index):
        if candidate_index < 0 or candidate_index >= len(segments):
            continue
        start, end, h0, h1 = segments[candidate_index]
        if start <= parameter <= end:
            found.add(h0 + (h1 - h0) * (parameter - start) / (end - start))
    if len(found) != 1:
        raise _unsupported("BOUNDARY_TRACE_AMBIGUOUS",
                           "piecewise-linear boundary trace is missing or ambiguous")
    return next(iter(found))


def _check_sides(mesh: _Mesh, roles: FacePartition, uvh: Sequence[_Point3],
                 upper: _Patch, lower: _Patch,
                 domain: tuple[Fraction, Fraction, Fraction, Fraction], owner: str,
                 budget: _Budget) -> None:
    for side in range(4):
        top_trace = _trace_segments(upper, uvh, side, domain)
        bottom_trace = _trace_segments(lower, uvh, side, domain)
        cells = _side_cells(top_trace, bottom_trace, side, domain, owner)
        triangles = _make_side_triangles(mesh, roles.side_faces, uvh, side, domain, owner)
        _check_side_triangle_overlaps(triangles, owner, side, budget)
        covered_area = Fraction(0)
        for triangle in triangles:
            triangle_area = _polygon_area(_ccw(triangle.points))
            clipped_area = Fraction(0)
            for cell in cells:
                budget.consume(context=f"{owner}.side{side}.cell_overlay")
                if not _bounds_overlap(triangle.bounds, cell.bounds):
                    continue
                clipped_area += _polygon_area(_clip_polygon(_ccw(triangle.points), cell.points))
            if clipped_area != triangle_area:
                _raise_owner_issue(
                    owner, "SIDE_FACE_LEAVES_CURTAIN",
                    f"{owner} side face {triangle.face_id} is not contained in its vertical curtain",
                    {"mesh": owner, "side": side, "face_id": triangle.face_id,
                     "face_area2": _fraction_text(2 * triangle_area),
                     "inside_area2": _fraction_text(2 * clipped_area)},
                )
            covered_area += triangle_area
        expected_area = sum((cell.area for cell in cells), Fraction(0))
        if covered_area != expected_area:
            _raise_owner_issue(
                owner, "SIDE_CURTAIN_NOT_COVERED",
                f"{owner} side faces do not exactly cover rectangle curtain {side}",
                {"mesh": owner, "side": side,
                 "side_area2": _fraction_text(2 * covered_area),
                 "curtain_area2": _fraction_text(2 * expected_area)},
            )


def _make_side_triangles(mesh: _Mesh, face_ids: tuple[int, ...], uvh: Sequence[_Point3],
                         side: int, domain: tuple[Fraction, Fraction, Fraction, Fraction],
                         owner: str) -> tuple[_SideTriangle, ...]:
    result: list[_SideTriangle] = []
    for face_id in face_ids:
        ids = mesh.faces[face_id]
        coords = tuple(uvh[index] for index in ids)
        assigned_side = _side_face_rectangle_side(coords, domain)
        if assigned_side is None:
            _raise_owner_issue(
                owner, "SIDE_FACE_NOT_ON_ONE_RECTANGLE_SIDE",
                f"{owner} side face {face_id} is not wholly on exactly one rectangle side",
                {"mesh": owner, "face_id": face_id,
                 "projected_uv": [_point_text((point[0], point[1])) for point in coords]},
            )
        if assigned_side != side:
            continue
        points = tuple((_edge_t(side, point), point[2]) for point in coords)
        if _orient(points[0], points[1], points[2]) == 0:
            _raise_owner_issue(owner, "SIDE_FACE_DEGENERATE_IN_PROJECTION",
                              f"{owner} side face {face_id} has zero curtain area",
                              {"mesh": owner, "side": side, "face_id": face_id})
        result.append(_SideTriangle(face_id, ids, points, _bounds(points)))
    return tuple(result)


def _side_face_rectangle_side(coords: Sequence[_Point3],
                              domain: tuple[Fraction, Fraction, Fraction, Fraction]
                              ) -> int | None:
    u0, u1, v0, v1 = domain
    us = {point[0] for point in coords}
    vs = {point[1] for point in coords}
    matches = []
    if len(us) == 1 and next(iter(us)) == u0:
        matches.append(0)
    if len(us) == 1 and next(iter(us)) == u1:
        matches.append(1)
    if len(vs) == 1 and next(iter(vs)) == v0:
        matches.append(2)
    if len(vs) == 1 and next(iter(vs)) == v1:
        matches.append(3)
    return matches[0] if len(matches) == 1 else None


def _check_side_triangle_overlaps(triangles: Sequence[_SideTriangle], owner: str, side: int,
                                  budget: _Budget) -> None:
    for left, right in _same_bbox_pairs(triangles, budget, f"{owner}.side{side}.self_overlay"):
        polygon = _triangle_intersection(left.points, right.points)
        if not polygon:
            continue
        if _polygon_area(polygon) > 0:
            _raise_owner_issue(
                owner, "SIDE_FACES_OVERLAP",
                f"{owner} side faces {left.face_id} and {right.face_id} overlap in positive area",
                {"mesh": owner, "side": side,
                 "face_ids": [left.face_id, right.face_id],
                 "overlap_polygon": _points_text(polygon)},
            )
        shared = set(left.vertex_ids) & set(right.vertex_ids)
        expected = {left.points[left.vertex_ids.index(vertex_id)] for vertex_id in shared}
        if set(polygon) != expected:
            _raise_owner_issue(
                owner, "SIDE_FACE_NONCONFORMITY",
                f"{owner} side faces touch without matching shared vertex/edge topology",
                {"mesh": owner, "side": side,
                 "face_ids": [left.face_id, right.face_id],
                 "actual_contact": _points_text(polygon)},
            )


def _side_cells(top: Sequence[tuple[Fraction, Fraction, Fraction, Fraction]],
                bottom: Sequence[tuple[Fraction, Fraction, Fraction, Fraction]], side: int,
                domain: tuple[Fraction, Fraction, Fraction, Fraction],
                owner: str) -> tuple[_SideCell, ...]:
    knots = sorted({point for segment in (*top, *bottom) for point in segment[:2]})
    lo, hi = _side_parameter_bounds(side, domain)
    if not knots or knots[0] != lo or knots[-1] != hi:
        raise _unsupported("SIDE_CURTAIN_KNOTS_INCOMPLETE",
                           f"{owner} side {side} has incomplete upper/lower boundary knots")
    cells: list[_SideCell] = []
    for t0, t1 in zip(knots, knots[1:]):
        if t1 <= t0:
            continue
        b0, b1 = _trace_value(bottom, t0), _trace_value(bottom, t1)
        s0, s1 = _trace_value(top, t0), _trace_value(top, t1)
        if b0 >= s0 or b1 >= s1:
            raise _CertificateIssue(
                "FAIL" if owner == "candidate" else "UNKNOWN",
                "NONPOSITIVE_BOUNDARY_THICKNESS",
                f"{owner} side {side} has no positive curtain thickness",
                {"mesh": owner, "side": side, "parameter_interval":
                 [_fraction_text(t0), _fraction_text(t1)],
                 "bottom": [_fraction_text(b0), _fraction_text(b1)],
                 "top": [_fraction_text(s0), _fraction_text(s1)]},
            )
        points = ((t0, b0), (t1, b1), (t1, s1), (t0, s0))
        area = _polygon_area(points)
        if area <= 0:
            raise _unsupported("SIDE_CURTAIN_CELL_INVALID",
                               f"{owner} side {side} curtain cell is degenerate")
        cells.append(_SideCell(points, area, _bounds(points)))
    return tuple(cells)


def _validate_closed_mesh(mesh: _Mesh, roles: FacePartition, owner: str,
                          axis: HeightGraphAxis,
                          domain: tuple[Fraction, Fraction, Fraction, Fraction]) -> None:
    role_by_face: dict[int, str] = {}
    for role, face_ids in (("upper", roles.upper_faces), ("lower", roles.lower_faces),
                           ("side", roles.side_faces)):
        role_by_face.update({face_id: role for face_id in face_ids})
    edge_faces: dict[tuple[int, int], list[tuple[int, int, int]]] = {}
    vertex_links: dict[int, list[tuple[int, int]]] = {}
    seen_faces: set[tuple[int, int, int]] = set()
    signed_volume6 = Fraction(0)
    for face_id, face in enumerate(mesh.faces):
        canonical = tuple(sorted(face))
        if canonical in seen_faces:
            _raise_owner_issue(owner, "DUPLICATE_FACE",
                              f"{owner} has duplicate triangle face {face_id}",
                              {"mesh": owner, "face_id": face_id})
        seen_faces.add(canonical)
        p0, p1, p2 = (mesh.vertices[index] for index in face)
        cross = _cross3(_sub3(p1, p0), _sub3(p2, p0))
        if cross == (0, 0, 0):
            _raise_owner_issue(owner, "DEGENERATE_3D_FACE",
                              f"{owner} face {face_id} has zero exact 3D area",
                              {"mesh": owner, "face_id": face_id})
        signed_volume6 += _dot3(p0, _cross3(p1, p2))
        for start, end in ((face[0], face[1]), (face[1], face[2]), (face[2], face[0])):
            key = (min(start, end), max(start, end))
            edge_faces.setdefault(key, []).append((face_id, start, end))
        for vertex, a, b in ((face[0], face[1], face[2]),
                             (face[1], face[2], face[0]),
                             (face[2], face[0], face[1])):
            vertex_links.setdefault(vertex, []).append((a, b))
    for edge, rows in edge_faces.items():
        if len(rows) != 2:
            _raise_owner_issue(owner, "MESH_EDGE_NOT_TWO_MANIFOLD",
                              f"{owner} edge {edge} has {len(rows)} incident faces",
                              {"mesh": owner, "edge_vertex_ids": list(edge),
                               "face_ids": [row[0] for row in rows]})
        if rows[0][1:] == rows[1][1:]:
            _raise_owner_issue(owner, "MESH_WINDING_INCONSISTENT",
                              f"{owner} adjacent faces orient edge {edge} the same way",
                              {"mesh": owner, "edge_vertex_ids": list(edge),
                               "face_ids": [rows[0][0], rows[1][0]]})
        first_role, second_role = role_by_face[rows[0][0]], role_by_face[rows[1][0]]
        if {first_role, second_role} == {"upper", "lower"}:
            _raise_owner_issue(owner, "UPPER_LOWER_DIRECT_ADJACENCY",
                              f"{owner} upper and lower patches share an edge",
                              {"mesh": owner, "edge_vertex_ids": list(edge),
                               "face_ids": [rows[0][0], rows[1][0]]})
        if first_role != second_role and "side" not in (first_role, second_role):
            _raise_owner_issue(owner, "PATCH_ROLE_ADJACENCY_INVALID",
                              f"{owner} has incompatible face roles at edge {edge}",
                              {"mesh": owner, "edge_vertex_ids": list(edge),
                               "roles": [first_role, second_role]})
    for vertex, links in vertex_links.items():
        degree: dict[int, int] = {}
        graph: dict[int, set[int]] = {}
        for a, b in links:
            degree[a] = degree.get(a, 0) + 1
            degree[b] = degree.get(b, 0) + 1
            graph.setdefault(a, set()).add(b)
            graph.setdefault(b, set()).add(a)
        if any(value != 2 for value in degree.values()):
            _raise_owner_issue(owner, "MESH_VERTEX_LINK_INVALID",
                              f"{owner} vertex {vertex} has a non-cyclic face link",
                              {"mesh": owner, "vertex_id": vertex})
        pending = [next(iter(graph))]
        visited: set[int] = set()
        while pending:
            item = pending.pop()
            if item in visited:
                continue
            visited.add(item)
            pending.extend(graph[item] - visited)
        if visited != set(graph):
            _raise_owner_issue(owner, "MESH_VERTEX_LINK_DISCONNECTED",
                              f"{owner} vertex {vertex} has multiple face fans",
                              {"mesh": owner, "vertex_id": vertex})
    if signed_volume6 <= 0:
        _raise_owner_issue(owner, "SIGNED_VOLUME_NOT_POSITIVE",
                          f"{owner} exact signed volume is not positive",
                          {"mesh": owner, "signed_volume6": _fraction_text(signed_volume6)})
    _validate_role_edge_adjacency(
        mesh, roles, role_by_face, edge_faces,
        tuple(_transform(point, axis) for point in mesh.vertices),
        domain, owner,
    )


def _validate_role_edge_adjacency(mesh: _Mesh, roles: FacePartition,
                                  role_by_face: dict[int, str],
                                  edge_faces: dict[tuple[int, int], list[tuple[int, int, int]]],
                                  uvh: Sequence[_Point3],
                                  domain: tuple[Fraction, Fraction, Fraction, Fraction],
                                  owner: str) -> None:
    for face_ids, role in ((roles.upper_faces, "upper"), (roles.lower_faces, "lower")):
        incidence: dict[tuple[int, int], int] = {}
        for face_id in face_ids:
            face = mesh.faces[face_id]
            for a, b in ((face[0], face[1]), (face[1], face[2]), (face[2], face[0])):
                key = (min(a, b), max(a, b))
                incidence[key] = incidence.get(key, 0) + 1
        for edge, local_count in incidence.items():
            roles_at_edge = [role_by_face[row[0]] for row in edge_faces[edge]]
            if local_count == 1:
                if roles_at_edge.count(role) != 1 or roles_at_edge.count("side") != 1:
                    _raise_owner_issue(owner, "SURFACE_RIM_NOT_CLOSED_BY_SIDE",
                                      f"{owner} {role} boundary edge {edge} is not paired to one side face",
                                      {"mesh": mesh.name, "role": role,
                                       "edge_vertex_ids": list(edge), "roles": roles_at_edge})
                a, b = edge
                if _edge_rectangle_side((uvh[a][0], uvh[a][1]),
                                        (uvh[b][0], uvh[b][1]), domain) is None:
                    _raise_owner_issue(owner, "SURFACE_RIM_NOT_ON_RECTANGLE",
                                      f"{owner} {role} rim edge {edge} leaves rectangle boundary",
                                      {"mesh": owner, "role": role,
                                       "edge_vertex_ids": list(edge)})
            elif local_count != 2 or roles_at_edge.count(role) != 2:
                _raise_owner_issue(owner, "SURFACE_PATCH_EDGE_INVALID",
                                  f"{owner} {role} internal edge {edge} has invalid role adjacency",
                                  {"mesh": mesh.name, "role": role,
                                   "edge_vertex_ids": list(edge), "roles": roles_at_edge})


def _validate_candidate_quality(mesh: _Mesh, limits: MeshQualityLimits) -> dict[str, Any]:
    min_q_squared: Fraction | None = None
    min_altitude_squared: Fraction | None = None
    max_aspect_squared: Fraction | None = None
    worst_q_face: int | None = None
    worst_altitude_face: int | None = None
    worst_aspect_face: int | None = None
    for face_id, face in enumerate(mesh.faces):
        p0, p1, p2 = (mesh.vertices[index] for index in face)
        edge_squared = tuple(_dot3(vector, vector) for vector in
                             (_sub3(p1, p0), _sub3(p2, p1), _sub3(p0, p2)))
        longest_squared = max(edge_squared)
        normal = _cross3(_sub3(p1, p0), _sub3(p2, p0))
        area2_squared = _dot3(normal, normal)
        if longest_squared <= 0 or area2_squared <= 0:
            raise _contradiction("CANDIDATE_QUALITY_DEGENERATE",
                                 f"candidate face {face_id} has nonpositive exact area or edge length",
                                 {"face_id": face_id})
        q_squared = Fraction(12) * area2_squared / sum(edge_squared) ** 2
        altitude_squared = area2_squared / longest_squared
        aspect_squared = longest_squared ** 2 / area2_squared
        if min_q_squared is None or q_squared < min_q_squared:
            min_q_squared, worst_q_face = q_squared, face_id
        if min_altitude_squared is None or altitude_squared < min_altitude_squared:
            min_altitude_squared, worst_altitude_face = altitude_squared, face_id
        if max_aspect_squared is None or aspect_squared > max_aspect_squared:
            max_aspect_squared, worst_aspect_face = aspect_squared, face_id

    if (min_q_squared is None or min_altitude_squared is None
            or max_aspect_squared is None):
        raise _unsupported("CANDIDATE_QUALITY_EMPTY", "candidate mesh has no quality faces")
    min_q_limit = _to_fraction(limits.min_q, context="quality_limits.min_q")
    min_altitude_limit = _to_fraction(limits.min_altitude_mm,
                                      context="quality_limits.min_altitude_mm")
    max_aspect_limit = _to_fraction(limits.max_aspect_ratio,
                                    context="quality_limits.max_aspect_ratio")
    if (min_q_squared < min_q_limit ** 2
            or min_altitude_squared < min_altitude_limit ** 2
            or max_aspect_squared > max_aspect_limit ** 2):
        raise _contradiction(
            "CANDIDATE_TRIANGLE_QUALITY_FAILED",
            "candidate mesh violates one or more declared q/altitude/aspect limits",
            {"min_q_squared": _fraction_text(min_q_squared),
             "min_q_face_id": worst_q_face,
             "min_altitude_squared_mm2": _fraction_text(min_altitude_squared),
             "min_altitude_face_id": worst_altitude_face,
             "max_aspect_squared": _fraction_text(max_aspect_squared),
             "max_aspect_face_id": worst_aspect_face,
             "limits": {"min_q_squared": _fraction_text(min_q_limit ** 2),
                        "min_altitude_squared_mm2": _fraction_text(min_altitude_limit ** 2),
                        "max_aspect_squared": _fraction_text(max_aspect_limit ** 2)}},
        )
    return {"min_q_squared": _fraction_text(min_q_squared),
            "min_q_face_id": worst_q_face,
            "min_altitude_squared_mm2": _fraction_text(min_altitude_squared),
            "min_altitude_face_id": worst_altitude_face,
            "max_aspect_squared": _fraction_text(max_aspect_squared),
            "max_aspect_face_id": worst_aspect_face,
            "limits": {"min_q_squared": _fraction_text(min_q_limit ** 2),
                       "min_altitude_squared_mm2": _fraction_text(min_altitude_limit ** 2),
                       "max_aspect_squared": _fraction_text(max_aspect_limit ** 2)}}


def _same_bbox_pairs(triangles: Sequence[Any], budget: _Budget,
                     context: str) -> Iterable[tuple[Any, Any]]:
    ordered = sorted(triangles, key=lambda tri: (tri.bounds[0], tri.face_id))
    active: list[Any] = []
    for current in ordered:
        active = [previous for previous in active if previous.bounds[1] >= current.bounds[0]]
        for previous in active:
            budget.consume(context=context)
            if _interval_overlap(previous.bounds[2], previous.bounds[3],
                                 current.bounds[2], current.bounds[3]):
                yield previous, current
        active.append(current)


def _cross_bbox_pairs(first: Sequence[Any], second: Sequence[Any], budget: _Budget,
                      context: str) -> Iterable[tuple[Any, Any]]:
    events = [(tri.bounds[0], 0, tri.face_id, tri) for tri in first]
    events.extend((tri.bounds[0], 1, tri.face_id, tri) for tri in second)
    events.sort(key=lambda event: (event[0], event[1], event[2]))
    active_first: list[Any] = []
    active_second: list[Any] = []
    for minimum_u, group, _face_id, current in events:
        active_first = [tri for tri in active_first if tri.bounds[1] >= minimum_u]
        active_second = [tri for tri in active_second if tri.bounds[1] >= minimum_u]
        opposite = active_second if group == 0 else active_first
        for other in opposite:
            budget.consume(context=context)
            if _interval_overlap(other.bounds[2], other.bounds[3],
                                 current.bounds[2], current.bounds[3]):
                yield (current, other) if group == 0 else (other, current)
        (active_first if group == 0 else active_second).append(current)


def _triangle_intersection(first: Sequence[_Point2],
                           second: Sequence[_Point2]) -> tuple[_Point2, ...]:
    polygon = _clip_polygon(_ccw(first), _ccw(second))
    return _canonical_convex_polygon(polygon)


def _clip_polygon(subject: Sequence[_Point2], clipper: Sequence[_Point2]
                  ) -> tuple[_Point2, ...]:
    output = list(subject)
    clip = _ccw(clipper)
    if len(output) < 3 or len(clip) < 3:
        return ()
    for index, clip_start in enumerate(clip):
        clip_end = clip[(index + 1) % len(clip)]
        input_points = output
        output = []
        if not input_points:
            break
        previous = input_points[-1]
        previous_side = _orient(clip_start, clip_end, previous)
        for current in input_points:
            current_side = _orient(clip_start, clip_end, current)
            previous_inside = previous_side >= 0
            current_inside = current_side >= 0
            if previous_inside != current_inside:
                denominator = previous_side - current_side
                if denominator != 0:
                    ratio = previous_side / denominator
                    output.append((previous[0] + ratio * (current[0] - previous[0]),
                                   previous[1] + ratio * (current[1] - previous[1])))
            if current_inside:
                output.append(current)
            previous, previous_side = current, current_side
        output = list(_dedupe_consecutive(output))
    return _canonical_convex_polygon(tuple(output))


def _canonical_convex_polygon(points: Sequence[_Point2]) -> tuple[_Point2, ...]:
    unique = sorted(set(points))
    if len(unique) <= 2:
        return tuple(unique)
    hull = _convex_hull(unique)
    if len(hull) < 3 or _polygon_area(hull) == 0:
        if not hull:
            return ()
        if len(hull) == 1:
            return tuple(hull)
        return (min(hull), max(hull))
    return _ccw(hull)


def _convex_hull(points: Sequence[_Point2]) -> tuple[_Point2, ...]:
    ordered = sorted(set(points))
    if len(ordered) <= 1:
        return tuple(ordered)

    def half(sequence: Iterable[_Point2]) -> list[_Point2]:
        result: list[_Point2] = []
        for point in sequence:
            while len(result) >= 2 and _orient(result[-2], result[-1], point) <= 0:
                result.pop()
            result.append(point)
        return result

    lower = half(ordered)
    upper = half(reversed(ordered))
    return tuple(lower[:-1] + upper[:-1])


def _dedupe_consecutive(points: Sequence[_Point2]) -> tuple[_Point2, ...]:
    result: list[_Point2] = []
    for point in points:
        if not result or result[-1] != point:
            result.append(point)
    if len(result) > 1 and result[0] == result[-1]:
        result.pop()
    return tuple(result)


def _linear_value(triangle: _Triangle, point: _Point2) -> Fraction:
    p0, p1, p2 = triangle.points
    denominator = _orient(p0, p1, p2)
    w0 = _orient(p1, p2, point) / denominator
    w1 = _orient(p2, p0, point) / denominator
    w2 = _orient(p0, p1, point) / denominator
    return w0 * triangle.values[0] + w1 * triangle.values[1] + w2 * triangle.values[2]


def _inside_domain(point: _Point2,
                   domain: tuple[Fraction, Fraction, Fraction, Fraction]) -> bool:
    return domain[0] <= point[0] <= domain[1] and domain[2] <= point[1] <= domain[3]


def _bounds(points: Sequence[_Point2]) -> tuple[Fraction, Fraction, Fraction, Fraction]:
    return (min(point[0] for point in points), max(point[0] for point in points),
            min(point[1] for point in points), max(point[1] for point in points))


def _bounds_overlap(first: tuple[Fraction, Fraction, Fraction, Fraction],
                    second: tuple[Fraction, Fraction, Fraction, Fraction]) -> bool:
    return (_interval_overlap(first[0], first[1], second[0], second[1])
            and _interval_overlap(first[2], first[3], second[2], second[3]))


def _interval_overlap(a0: Fraction, a1: Fraction, b0: Fraction, b1: Fraction) -> bool:
    return a0 <= b1 and b0 <= a1


def _orient(a: _Point2, b: _Point2, c: _Point2) -> Fraction:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _signed_polygon_area2(points: Sequence[_Point2]) -> Fraction:
    if len(points) < 3:
        return Fraction(0)
    return sum(
        (points[index][0] * points[(index + 1) % len(points)][1]
         - points[(index + 1) % len(points)][0] * points[index][1]
         for index in range(len(points))),
        Fraction(0),
    )


def _polygon_area(points: Sequence[_Point2]) -> Fraction:
    return abs(_signed_polygon_area2(points)) / 2


def _ccw(points: Sequence[_Point2]) -> tuple[_Point2, ...]:
    cleaned = _dedupe_consecutive(points)
    return cleaned if _signed_polygon_area2(cleaned) >= 0 else tuple(reversed(cleaned))


def _edge_rectangle_side(a: _Point2, b: _Point2,
                         domain: tuple[Fraction, Fraction, Fraction, Fraction]
                         ) -> int | None:
    u0, u1, v0, v1 = domain
    matches = []
    if a[0] == b[0] == u0:
        matches.append(0)
    if a[0] == b[0] == u1:
        matches.append(1)
    if a[1] == b[1] == v0:
        matches.append(2)
    if a[1] == b[1] == v1:
        matches.append(3)
    return matches[0] if len(matches) == 1 else None


def _edge_parameter(side: int, a: _Point2, b: _Point2) -> tuple[Fraction, Fraction]:
    index = 1 if side in (0, 1) else 0
    return a[index], b[index]


def _edge_t(side: int, point: _Point3) -> Fraction:
    return point[1] if side in (0, 1) else point[0]


def _side_parameter_bounds(side: int,
                           domain: tuple[Fraction, Fraction, Fraction, Fraction]
                           ) -> tuple[Fraction, Fraction]:
    return (domain[2], domain[3]) if side in (0, 1) else (domain[0], domain[1])


def _sub3(a: _Point3, b: _Point3) -> _Point3:
    return a[0] - b[0], a[1] - b[1], a[2] - b[2]


def _cross3(a: _Point3, b: _Point3) -> _Point3:
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _dot3(a: _Point3, b: _Point3) -> Fraction:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _fraction_text(value: Fraction) -> str:
    return str(value.numerator) if value.denominator == 1 else f"{value.numerator}/{value.denominator}"


def _point_text(point: _Point2) -> list[str]:
    return [_fraction_text(point[0]), _fraction_text(point[1])]


def _points_text(points: Sequence[_Point2]) -> list[list[str]]:
    return [_point_text(point) for point in points]
