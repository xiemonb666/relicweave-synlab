"""Tiny analytic fixtures for the isolated sampled wall-interval helper.

These tests are source-only until the parent agent approves one focused pytest run. The
through-hole case uses one explicit Manifold boolean at runtime; every other fixture is made by
composing analytic box meshes without Boolean operations.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pytest
import trimesh

from synlab.degrade.wall_intervals import (
    ResultSubsetEvidence,
    WallDirectionEvidence,
    _all_material_intervals,
    measure_material_intervals,
)


STATION = np.asarray([[5.0, 0.0, 0.0]], dtype=np.float64)
OUTWARD = np.asarray([[1.0, 0.0, 0.0]], dtype=np.float64)
DIRECTION_EVIDENCE = WallDirectionEvidence(
    source="material_wall_direction",
    trusted=True,
    convention="outward_from_source",
    units="mm",
    provenance="analytic hollow-box fixture: positive-X outer wall",
)
SUBSET_EVIDENCE = ResultSubsetEvidence(
    relation="material_subset_of_source",
    trusted=True,
    provenance="fixture construction removes or preserves source material only",
)


def _hollow_box(inner_extents: tuple[float, float, float] = (8.0, 8.0, 8.0)) -> trimesh.Trimesh:
    outer = trimesh.creation.box(extents=(10.0, 10.0, 10.0))
    inner = trimesh.creation.box(extents=inner_extents)
    inner.invert()  # cavity boundary points toward the air gap
    return trimesh.util.concatenate((outer, inner))


def _measure(
    source: trimesh.Trimesh,
    result: trimesh.Trimesh,
    *,
    station: np.ndarray = STATION,
    direction: np.ndarray = OUTWARD,
    direction_evidence: WallDirectionEvidence | dict[str, object] | None = DIRECTION_EVIDENCE,
) -> dict[str, object]:
    return measure_material_intervals(
        source,
        result,
        station,
        direction,
        direction_evidence=direction_evidence,
        result_evidence=SUBSET_EVIDENCE,
        station_ids=["positive-x-center"],
    )


def _capture_uniform_erosion_report(report: dict[str, object]) -> None:
    """Optionally persist a native report for the post-pytest PNG renderer."""
    capture_dir = os.environ.get("WALL_INTERVAL_CAPTURE_DIR")
    if not capture_dir:
        return
    destination = Path(capture_dir)
    destination.mkdir(parents=True, exist_ok=True)
    payload = {
        "fixture_id": "uniform_cavity_side_erosion_0_2_mm",
        "analytic_oracle": {"source_wall_mm": 1.0, "remaining_wall_mm": 0.8},
        "stations_mm": STATION.tolist(),
        "outward_wall_directions": OUTWARD.tolist(),
        "source_mesh": {"outer_extents_mm": [10.0, 10.0, 10.0],
                        "inner_cavity_extents_mm": [8.0, 8.0, 8.0]},
        "result_mesh": {"outer_extents_mm": [10.0, 10.0, 10.0],
                        "inner_cavity_extents_mm": [8.4, 8.4, 8.4]},
        "native_report": report,
    }
    (destination / "uniform_cavity_side_erosion.report.json").write_text(
        json.dumps(payload, allow_nan=False, indent=2), encoding="utf-8")


def test_known_one_mm_hollow_box_pairs_only_the_station_material_interval() -> None:
    source = _hollow_box()
    report = _measure(source, source)

    row = report["station_results"][0]
    assert report["sampled_interval_status"] == "SAMPLED_PASS"
    assert report["global_wall_status"] == "UNVERIFIED"
    assert report["physical_qualification_status"] == "UNKNOWN"
    assert row["source_length_mm"] == pytest.approx(1.0, abs=5.0e-4)
    assert row["remaining_length_mm"] == pytest.approx(1.0, abs=5.0e-4)
    assert row["source_interval_mm"][0] == pytest.approx(1.0e-3, abs=5.0e-4)
    assert report["sampled_violation_count"] == 0
    assert report["sampled_violation_fraction"] == 0.0
    assert report["coverage_fraction"] == 1.0


def test_uniform_cavity_side_erosion_of_point_two_mm_keeps_point_eight_mm() -> None:
    source = _hollow_box()
    result = _hollow_box(inner_extents=(8.4, 8.4, 8.4))
    report = _measure(source, result)
    _capture_uniform_erosion_report(report)

    row = report["station_results"][0]
    assert report["sampled_interval_status"] == "SAMPLED_PASS"
    assert row["source_length_mm"] == pytest.approx(1.0, abs=5.0e-4)
    assert row["remaining_length_mm"] == pytest.approx(0.8, abs=5.0e-4)
    assert row["relative_loss"] == pytest.approx(0.2, abs=1.0e-3)


def test_point_five_mm_remaining_fails_absolute_guard_even_at_half_loss_boundary() -> None:
    source = _hollow_box()
    result = _hollow_box(inner_extents=(9.0, 9.0, 9.0))
    report = _measure(source, result)

    row = report["station_results"][0]
    assert report["sampled_interval_status"] == "SAMPLED_FAIL"
    assert row["status"] == "SAMPLED_FAIL"
    assert row["reason"] == "ABSOLUTE_MIN_WALL_VIOLATION"
    assert row["remaining_length_mm"] == pytest.approx(0.5, abs=5.0e-4)


def test_local_through_hole_is_a_definite_perforation_at_its_centerline() -> None:
    source = _hollow_box()
    cutter = trimesh.creation.cylinder(radius=0.2, height=2.0, sections=24)
    cutter.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2.0, [0.0, 1.0, 0.0]))
    cutter.apply_translation([4.5, 0.0, 0.0])
    result = trimesh.boolean.difference([source, cutter], engine="manifold")
    assert isinstance(result, trimesh.Trimesh)

    report = _measure(source, result)
    row = report["station_results"][0]
    assert report["sampled_interval_status"] == "SAMPLED_FAIL"
    assert row["status"] == "SAMPLED_FAIL"
    assert row["reason"] == "PERFORATED"
    assert row["result_intervals_mm"] == []
    assert row["remaining_length_mm"] == 0.0


def test_station_without_a_source_surface_interval_is_unknown() -> None:
    source = _hollow_box()
    report = _measure(
        source,
        source,
        station=np.asarray([[0.0, 0.0, 0.0]]),  # cavity center, not a source wall station
    )

    assert report["sampled_interval_status"] == "UNKNOWN"
    assert report["station_results"][0]["reason"] == "SOURCE_INTERVAL_MISSING"
    assert report["coverage_fraction"] == 0.0
    assert report["unknown_samples"] == 1


def test_edge_grazing_station_is_not_accepted_as_a_wall_thickness_measurement() -> None:
    source = _hollow_box()
    report = _measure(
        source,
        source,
        station=np.asarray([[5.0, 5.0, 0.0]]),  # shared +X/+Y edge, ray lies along +Y face
    )

    assert report["sampled_interval_status"] == "UNKNOWN"
    assert report["station_results"][0]["status"] == "UNKNOWN"
    assert report["coverage_fraction"] == 0.0


def test_two_retained_material_segments_are_split_fail_without_invented_total_thickness() -> None:
    source = _hollow_box()
    outer_segment = trimesh.creation.box(extents=(0.4, 4.0, 4.0))
    outer_segment.apply_translation([4.8, 0.0, 0.0])  # x=[4.6, 5.0]
    inner_segment = trimesh.creation.box(extents=(0.4, 4.0, 4.0))
    inner_segment.apply_translation([4.2, 0.0, 0.0])  # x=[4.0, 4.4]
    result = trimesh.util.concatenate((outer_segment, inner_segment))

    report = _measure(source, result)
    row = report["station_results"][0]
    assert report["sampled_interval_status"] == "SAMPLED_FAIL"
    assert row["reason"] == "SPLIT_INTERVAL"
    assert row["status"] == "SAMPLED_FAIL"
    assert len(row["result_intervals_mm"]) == 2
    assert row["remaining_length_mm"] is None
    assert row["loss_mm"] is None
    assert row["relative_loss"] is None
    assert report["stations_measured"] == 0
    assert report["stations_classified"] == 1
    assert report["measurement_coverage_fraction"] == 0.0
    assert report["sampled_violation_count"] is None
    assert report["sampled_violation_fraction"] is None
    assert report["relative_metric_unknown_samples"] == 1


def test_open_source_mesh_is_unknown_and_not_repaired() -> None:
    source = _hollow_box()
    open_source = trimesh.Trimesh(
        vertices=source.vertices.copy(),
        faces=np.delete(source.faces, 0, axis=0),
        process=False,
    )
    report = _measure(open_source, _hollow_box())

    assert report["sampled_interval_status"] == "UNKNOWN"
    assert report["station_results"][0]["reason"] == "SOURCE_OPEN_MESH"
    assert report["mesh_health"]["source"]["valid"] is False


def test_inverted_source_mesh_is_unknown_and_not_reoriented() -> None:
    source = _hollow_box()
    source.invert()
    report = _measure(source, source)

    assert report["sampled_interval_status"] == "UNKNOWN"
    assert report["station_results"][0]["reason"] == "SOURCE_INVERTED_OR_NONPOSITIVE_VOLUME"
    assert report["mesh_health"]["source"]["signed_volume_mm3"] < 0.0


def test_self_intersecting_closed_mesh_is_unknown_before_ray_sampling() -> None:
    left = trimesh.creation.box(extents=(2.0, 2.0, 2.0))
    right = trimesh.creation.box(extents=(2.0, 2.0, 2.0))
    right.apply_translation([1.0, 0.0, 0.0])
    crossing = trimesh.util.concatenate((left, right))
    report = _measure(crossing, crossing)

    assert report["sampled_interval_status"] == "UNKNOWN"
    assert report["station_results"][0]["reason"] == "SOURCE_SELF_INTERSECTING"
    assert report["mesh_health"]["source"]["self_intersecting"] is True


def test_threshold_band_is_unknown_and_not_counted_as_classified_coverage() -> None:
    source = _hollow_box()
    result = _hollow_box(inner_extents=(8.8, 8.8, 8.8))  # nominal remaining wall = 0.6 mm
    report = _measure(source, result)

    assert report["sampled_interval_status"] == "UNKNOWN"
    assert report["station_results"][0]["reason"] == "ABSOLUTE_GUARD_WITHIN_FLOAT32_UNCERTAINTY"
    assert report["stations_classified"] == 0
    assert report["stations_measured"] == 1
    assert report["coverage_fraction"] == 0.0
    assert report["measurement_coverage_fraction"] == 1.0
    assert report["sampled_violation_fraction"] is None


def test_missing_trusted_wall_direction_is_unknown_without_claiming_coverage() -> None:
    source = _hollow_box()
    report = _measure(source, source, direction_evidence=None)

    assert report["sampled_interval_status"] == "UNKNOWN"
    assert report["station_results"][0]["reason"] == "WALL_DIRECTION_UNTRUSTED"
    assert report["coverage_fraction"] == 0.0
    assert report["unknown_samples"] == report["stations_requested"] == 1


def test_nonfinite_guard_returns_json_safe_structured_unknown() -> None:
    source = _hollow_box()
    report = measure_material_intervals(
        source,
        source,
        STATION,
        OUTWARD,
        direction_evidence=DIRECTION_EVIDENCE,
        result_evidence=SUBSET_EVIDENCE,
        min_remaining_wall_mm=float("nan"),
    )

    assert report["sampled_interval_status"] == "UNKNOWN"
    assert report["reason_counts"] == {"NONFINITE_GUARD_PARAMETER": 1}
    assert report["guard"]["min_remaining_wall_mm"] is None
    json.dumps(report, allow_nan=False)


def test_none_provenance_does_not_satisfy_trusted_direction_evidence() -> None:
    source = _hollow_box()
    evidence = {
        "source": "material_wall_direction",
        "trusted": True,
        "convention": "outward_from_source",
        "units": "mm",
        "provenance": None,
    }
    report = _measure(source, source, direction_evidence=evidence)

    assert report["sampled_interval_status"] == "UNKNOWN"
    assert report["station_results"][0]["reason"] == "WALL_DIRECTION_UNTRUSTED"


class _FakeTensor:
    def __init__(self, values: np.ndarray) -> None:
        self._values = np.asarray(values)

    def numpy(self) -> np.ndarray:
        return self._values


class _FakeCore:
    Tensor = _FakeTensor


class _FakeOpen3D:
    core = _FakeCore


class _FakeAllHitScene:
    def __init__(self, entry_face: int, exit_face: int, *, distances: list[float],
                 occupancy: list[float]) -> None:
        self.entry_face = entry_face
        self.exit_face = exit_face
        self.distances = distances
        self.occupancy = occupancy
        self.occupancy_calls = 0

    def list_intersections(self, rays: _FakeTensor, nthreads: int = 0) -> dict[str, _FakeTensor]:
        assert np.asarray(rays.numpy()).shape == (1, 6)
        return {
            "ray_splits": _FakeTensor([0, 2]),
            "t_hit": _FakeTensor([1.0, 3.0]),
            "primitive_ids": _FakeTensor([self.entry_face, self.exit_face]),
        }

    def compute_distance(self, query_points: _FakeTensor, nthreads: int = 0) -> _FakeTensor:
        assert len(query_points.numpy()) == 3
        return _FakeTensor(self.distances)

    def compute_occupancy(self, query_points: _FakeTensor, nthreads: int = 0,
                          nsamples: int = 3) -> _FakeTensor:
        self.occupancy_calls += 1
        return _FakeTensor(self.occupancy)


def _synthetic_interval_query(scene: _FakeAllHitScene) -> tuple[dict, dict[int, str]]:
    mesh = trimesh.creation.box(extents=(2.0, 2.0, 2.0))
    entry_face = int(np.flatnonzero(mesh.face_normals[:, 0] > 0.9)[0])
    exit_face = int(np.flatnonzero(mesh.face_normals[:, 0] < -0.9)[0])
    scene.entry_face = entry_face
    scene.exit_face = exit_face
    rays = np.asarray([[2.0, 0.0, 0.0, -1.0, 0.0, 0.0]], dtype=np.float32)
    return _all_material_intervals(
        mesh,
        scene,
        rays,
        _FakeOpen3D,
        occupancy_nsamples=3,
        nthreads=0,
        merge_tolerance_mm=1.0e-5,
        max_events_per_ray=256,
    )


def test_gap_midpoint_on_surface_returns_unknown_without_occupancy_classification() -> None:
    scene = _FakeAllHitScene(0, 0, distances=[0.5, 0.0, 0.00025], occupancy=[0.0, 1.0, 0.0])
    intervals, reasons = _synthetic_interval_query(scene)

    assert intervals == {}
    assert reasons[0] == "GAP_PROBE_ON_OR_NEAR_SURFACE"
    assert scene.occupancy_calls == 0


def test_nonfinite_occupancy_is_unknown_and_never_collapses_to_no_material() -> None:
    scene = _FakeAllHitScene(
        0, 0, distances=[0.5, 1.0, 0.00025], occupancy=[float("nan"), 1.0, 0.0]
    )
    intervals, reasons = _synthetic_interval_query(scene)

    assert intervals == {}
    assert reasons[0] == "NONFINITE_OCCUPANCY_RESPONSE"
    assert scene.occupancy_calls == 1
