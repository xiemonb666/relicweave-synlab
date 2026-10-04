"""Sampled wall-material intervals from trusted source stations.

This module is intentionally independent of the P03 operator. It reports a sampled interval
guard only; it cannot certify a global minimum wall thickness or qualify a physical data asset.
The caller must supply fixed source stations and trusted outward wall directions.

All coordinates, distances, and thresholds are in millimetres. Open3D receives recentered
float32 geometry/rays, and its native ``RaycastingScene.list_intersections`` API supplies every
triangle hit. Events are clustered by distance and oriented by triangle normals. Every gap
midpoint must be farther than ``2 * merge_tolerance_mm`` from the surface before occupancy can
disambiguate the event sequence. No nearest-hit stepping or surface resampling is used.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np
import trimesh

__all__ = ["WallDirectionEvidence", "ResultSubsetEvidence", "measure_material_intervals"]

_DIRECTION_SOURCES = {
    "inner_outer_wall_map",
    "material_wall_direction",
    "classified_outer_wall_face_normal",
}
_RESULT_RELATION = "material_subset_of_source"
_ALGORITHM = "open3d_list_intersections_oriented_intervals_v1"
_FLOAT32_EPS = float(np.finfo(np.float32).eps)


@dataclass(frozen=True)
class WallDirectionEvidence:
    """Caller evidence for wall directions, in the source mesh's world frame."""

    source: str
    trusted: bool
    convention: str
    units: str
    provenance: str


@dataclass(frozen=True)
class ResultSubsetEvidence:
    """Caller evidence that the result retains material only from the source."""

    relation: str
    trusted: bool
    provenance: str


def measure_material_intervals(
    source_mesh: trimesh.Trimesh,
    result_mesh: trimesh.Trimesh,
    stations_mm: np.ndarray,
    wall_directions: np.ndarray,
    *,
    direction_evidence: WallDirectionEvidence | Mapping[str, Any] | None,
    result_evidence: ResultSubsetEvidence | Mapping[str, Any] | None,
    station_ids: Sequence[str] | None = None,
    min_remaining_wall_mm: float = 0.6,
    relative_loss_threshold: float = 0.5,
    relative_violation_budget: float = 0.01,
    probe_offset_mm: float = 1.0e-3,
    merge_tolerance_mm: float | None = None,
    occupancy_nsamples: int = 3,
    nthreads: int = 0,
    max_events_per_ray: int = 256,
) -> dict[str, Any]:
    """Measure the source material interval and its retained result interval per station.

    ``stations_mm[i]`` must be a fixed point on a source wall face. ``wall_directions[i]`` must
    point out of the source material at that point. A station is paired only to the unique
    continuous result interval inside its selected source interval. Air gaps and other shell
    intervals are never added together.

    Evidence is explicit because a fragment/interface face normal does not imply the vessel-wall
    direction. ``direction_evidence`` must be trusted and sourced from an inner/outer wall map, a
    material wall-direction field, or a semantically classified outer-wall face. The caller must
    also attest that ``result_mesh`` is a material subset of ``source_mesh`` before an absent
    interval can be classified as a perforation. This function always returns
    ``global_wall_status="UNVERIFIED"`` and ``physical_qualification_status="UNKNOWN"``.
    """
    try:
        stations = np.asarray(stations_mm, dtype=np.float64)
        directions = np.asarray(wall_directions, dtype=np.float64)
    except Exception:
        return _empty_unknown("INVALID_STATION_ARRAY", min_remaining_wall_mm,
                              relative_loss_threshold, relative_violation_budget)

    if stations.ndim != 2 or stations.shape[1:] != (3,):
        return _empty_unknown("INVALID_STATION_SHAPE", min_remaining_wall_mm,
                              relative_loss_threshold, relative_violation_budget)
    n = int(stations.shape[0])
    try:
        ids = _station_ids(station_ids, n)
    except Exception:
        ids = None
    if ids is None:
        return _unknown_for_stations(n, [f"station-{i:04d}" for i in range(n)],
                                     "INVALID_STATION_IDS", min_remaining_wall_mm,
                                     relative_loss_threshold, relative_violation_budget)

    base = _report_base(n, ids, min_remaining_wall_mm, relative_loss_threshold,
                        relative_violation_budget)
    if n == 0:
        base["sampled_interval_status"] = "UNKNOWN"
        base["reason_counts"] = {"NO_STATIONS": 1}
        return base

    direction_meta = _public_evidence(direction_evidence,
                                      ("source", "trusted", "convention", "units", "provenance"))
    if not _trusted_directions(direction_meta):
        return _unknown_for_stations(n, ids, "WALL_DIRECTION_UNTRUSTED", min_remaining_wall_mm,
                                     relative_loss_threshold, relative_violation_budget)
    result_meta = _public_evidence(result_evidence, ("relation", "trusted", "provenance"))
    if not _trusted_subset(result_meta):
        return _unknown_for_stations(n, ids, "RESULT_SUBSET_UNVERIFIED", min_remaining_wall_mm,
                                     relative_loss_threshold, relative_violation_budget)

    if directions.shape != stations.shape:
        return _unknown_for_stations(n, ids, "INVALID_DIRECTION_SHAPE", min_remaining_wall_mm,
                                     relative_loss_threshold, relative_violation_budget)
    parameter_error = _parameter_error(min_remaining_wall_mm, relative_loss_threshold,
                                       relative_violation_budget, probe_offset_mm,
                                       occupancy_nsamples, nthreads, max_events_per_ray)
    if parameter_error is not None:
        return _unknown_for_stations(n, ids, parameter_error, min_remaining_wall_mm,
                                     relative_loss_threshold, relative_violation_budget)
    min_remaining_wall_mm = float(min_remaining_wall_mm)
    relative_loss_threshold = float(relative_loss_threshold)
    relative_violation_budget = float(relative_violation_budget)
    probe_offset_mm = float(probe_offset_mm)
    occupancy_nsamples = int(occupancy_nsamples)
    nthreads = int(nthreads)
    max_events_per_ray = int(max_events_per_ray)

    try:
        import open3d as o3d
    except Exception as exc:
        return _unknown_for_stations(
            n, ids, f"OPEN3D_UNAVAILABLE:{type(exc).__name__}", min_remaining_wall_mm,
            relative_loss_threshold, relative_violation_budget)

    source_health = _mesh_health(source_mesh, o3d)
    result_health = _mesh_health(result_mesh, o3d)
    base["mesh_health"] = {"source": source_health, "result": result_health}
    if not source_health["valid"]:
        return _unknown_for_stations(n, ids, f"SOURCE_{source_health['reason']}",
                                     min_remaining_wall_mm, relative_loss_threshold,
                                     relative_violation_budget, mesh_health=base["mesh_health"])
    if not result_health["valid"]:
        return _unknown_for_stations(n, ids, f"RESULT_{result_health['reason']}",
                                     min_remaining_wall_mm, relative_loss_threshold,
                                     relative_violation_budget, mesh_health=base["mesh_health"])

    diag = max(float(source_health["bounds_diagonal_mm"]),
               float(result_health["bounds_diagonal_mm"]), 1.0)
    precision_bound = 8.0 * _FLOAT32_EPS * diag
    try:
        requested_tol = 0.0 if merge_tolerance_mm is None else float(merge_tolerance_mm)
    except (TypeError, ValueError, OverflowError):
        requested_tol = float("nan")
    if not np.isfinite(requested_tol) or requested_tol < 0:
        return _unknown_for_stations(n, ids, "INVALID_MERGE_TOLERANCE", min_remaining_wall_mm,
                                     relative_loss_threshold, relative_violation_budget,
                                     mesh_health=base["mesh_health"])
    tol = max(1.0e-5, precision_bound, requested_tol)
    uncertainty = 2.0 * tol
    if tol * 16.0 >= min_remaining_wall_mm:
        return _unknown_for_stations(n, ids, "FLOAT32_RESOLUTION_TOO_COARSE_FOR_GUARD",
                                     min_remaining_wall_mm, relative_loss_threshold,
                                     relative_violation_budget, mesh_health=base["mesh_health"],
                                     merge_tolerance_mm=tol,
                                     float32_precision_bound_mm=precision_bound)
    if probe_offset_mm <= 8.0 * tol:
        return _unknown_for_stations(n, ids, "PROBE_OFFSET_UNRESOLVED_AT_FLOAT32_PRECISION",
                                     min_remaining_wall_mm, relative_loss_threshold,
                                     relative_violation_budget, mesh_health=base["mesh_health"],
                                     merge_tolerance_mm=tol,
                                     float32_precision_bound_mm=precision_bound)

    finite_station = np.isfinite(stations).all(axis=1)
    finite_direction = np.isfinite(directions).all(axis=1)
    lengths = np.linalg.norm(np.where(finite_direction[:, None], directions, 0.0), axis=1)
    direction_ok = finite_direction & np.isfinite(lengths) & (lengths > 1.0e-12)
    normalised = np.zeros_like(directions)
    normalised[direction_ok] = directions[direction_ok] / lengths[direction_ok, None]
    row_reasons: list[str | None] = [None] * n
    for i in range(n):
        if not finite_station[i]:
            row_reasons[i] = "NONFINITE_STATION"
        elif not direction_ok[i]:
            row_reasons[i] = "INVALID_WALL_DIRECTION"

    query_indices = np.flatnonzero(np.asarray([reason is None for reason in row_reasons], dtype=bool))
    source_intervals: dict[int, list[tuple[float, float]]] = {}
    result_intervals: dict[int, list[tuple[float, float]]] = {}
    source_ray_reasons: dict[int, str] = {}
    result_ray_reasons: dict[int, str] = {}
    if query_indices.size:
        try:
            center = 0.5 * (np.asarray(source_mesh.bounds[0], dtype=np.float64)
                            + np.asarray(source_mesh.bounds[1], dtype=np.float64))
            source_scene = _build_scene(source_mesh, center, o3d)
            # Use the same local origin for both scenes to make float32 conversion comparable.
            result_scene = _build_scene(result_mesh, center, o3d)
            origins = stations[query_indices] + normalised[query_indices] * float(probe_offset_mm)
            ray_directions = -normalised[query_indices]
            rays_source = np.concatenate([origins - center, ray_directions], axis=1).astype(
                np.float32, copy=False)
            source_intervals, source_ray_reasons = _all_material_intervals(
                source_mesh, source_scene, rays_source, o3d,
                occupancy_nsamples=int(occupancy_nsamples), nthreads=int(nthreads),
                merge_tolerance_mm=tol, max_events_per_ray=int(max_events_per_ray))
            rays_result = np.concatenate([origins - center, ray_directions], axis=1).astype(
                np.float32, copy=False)
            result_intervals, result_ray_reasons = _all_material_intervals(
                result_mesh, result_scene, rays_result, o3d,
                occupancy_nsamples=int(occupancy_nsamples), nthreads=int(nthreads),
                merge_tolerance_mm=tol, max_events_per_ray=int(max_events_per_ray))
        except Exception as exc:
            return _unknown_for_stations(
                n, ids, f"RAYCAST_SETUP_OR_QUERY_ERROR:{type(exc).__name__}",
                min_remaining_wall_mm, relative_loss_threshold, relative_violation_budget,
                mesh_health=base["mesh_health"], merge_tolerance_mm=tol,
                float32_precision_bound_mm=precision_bound)

    rows: list[dict[str, Any]] = []
    definite_relative_violations = 0
    classified = 0
    paired = 0
    unknown_count = 0
    observed_source: list[float] = []
    observed_result: list[float] = []
    reason_counts: Counter[str] = Counter()
    station_tol = max(8.0 * tol, 0.1 * float(probe_offset_mm))

    for i, station_id in enumerate(ids):
        row: dict[str, Any] = {
            "station_id": station_id,
            "status": "UNKNOWN",
            "reason": None,
            "source_interval_index": None,
            "source_interval_mm": None,
            "result_interval_mm": None,
            "source_length_mm": None,
            "remaining_length_mm": None,
            "loss_mm": None,
            "relative_loss": None,
            "relative_violation": None,
            "result_intervals_mm": None,
        }
        if row_reasons[i] is not None:
            reason = str(row_reasons[i])
            row["reason"] = reason
            rows.append(row)
            unknown_count += 1
            reason_counts[reason] += 1
            continue

        local_i = int(np.searchsorted(query_indices, i))
        src_reason = source_ray_reasons.get(local_i)
        if src_reason is not None:
            row["reason"] = f"SOURCE_{src_reason}"
            rows.append(row)
            unknown_count += 1
            reason_counts[row["reason"]] += 1
            continue
        src_intervals = source_intervals.get(local_i, [])
        if not src_intervals:
            row["reason"] = "SOURCE_INTERVAL_MISSING"
            rows.append(row)
            unknown_count += 1
            reason_counts[row["reason"]] += 1
            continue
        source_candidates = [(j, interval) for j, interval in enumerate(src_intervals)
                             if abs(float(interval[0]) - float(probe_offset_mm)) <= station_tol]
        if len(source_candidates) != 1:
            row["reason"] = ("SOURCE_INTERVAL_MISSING" if not source_candidates
                             else "SOURCE_INTERVAL_AMBIGUOUS")
            rows.append(row)
            unknown_count += 1
            reason_counts[row["reason"]] += 1
            continue
        source_index, source_interval = source_candidates[0]
        source_length = float(source_interval[1] - source_interval[0])
        if not np.isfinite(source_length) or source_length <= tol:
            row["reason"] = "SOURCE_INTERVAL_UNRESOLVED"
            rows.append(row)
            unknown_count += 1
            reason_counts[row["reason"]] += 1
            continue
        row["source_interval_index"] = int(source_index)
        row["source_interval_mm"] = [float(source_interval[0]), float(source_interval[1])]
        row["source_length_mm"] = source_length
        observed_source.append(source_length)

        res_reason = result_ray_reasons.get(local_i)
        if res_reason is not None:
            row["reason"] = f"RESULT_{res_reason}"
            rows.append(row)
            unknown_count += 1
            reason_counts[row["reason"]] += 1
            continue
        res_intervals = result_intervals.get(local_i, [])
        overlap = []
        for interval in res_intervals:
            lo, hi = float(interval[0]), float(interval[1])
            overlap_mm = min(hi, source_interval[1]) - max(lo, source_interval[0])
            if overlap_mm > tol:
                if lo < source_interval[0] - tol or hi > source_interval[1] + tol:
                    row["reason"] = "RESULT_INTERVAL_NOT_CONTAINED_IN_SOURCE"
                    break
                overlap.append((lo, hi))
        if row["reason"] is not None:
            rows.append(row)
            unknown_count += 1
            reason_counts[row["reason"]] += 1
            continue
        if len(overlap) > 1:
            row["status"] = "SAMPLED_FAIL"
            row["reason"] = "SPLIT_INTERVAL"
            row["result_intervals_mm"] = [[float(lo), float(hi)] for lo, hi in overlap]
            classified += 1
            reason_counts[row["reason"]] += 1
            rows.append(row)
            continue
        if not overlap:
            row["status"] = "SAMPLED_FAIL"
            row["reason"] = "PERFORATED"
            row["result_intervals_mm"] = []
            row["remaining_length_mm"] = 0.0
            row["loss_mm"] = source_length
            row["relative_loss"] = 1.0
            row["relative_violation"] = True
            classified += 1
            definite_relative_violations += 1
            reason_counts[row["reason"]] += 1
            rows.append(row)
            continue

        result_interval = overlap[0]
        result_length = float(result_interval[1] - result_interval[0])
        loss = source_length - result_length
        relative_loss = loss / max(source_length, 1.0e-12)
        row["result_interval_mm"] = [float(result_interval[0]), float(result_interval[1])]
        row["result_intervals_mm"] = [[float(result_interval[0]), float(result_interval[1])]]
        row["remaining_length_mm"] = result_length
        row["loss_mm"] = loss
        row["relative_loss"] = relative_loss
        paired += 1
        classified += 1
        observed_result.append(result_length)
        if loss < -uncertainty:
            row["reason"] = "RESULT_INTERVAL_GREW"
            unknown_count += 1
            reason_counts[row["reason"]] += 1
            rows.append(row)
            continue
        relative_uncertainty = uncertainty / max(source_length, 1.0e-12)
        if abs(relative_loss - relative_loss_threshold) <= relative_uncertainty:
            row["relative_violation"] = None
        else:
            row["relative_violation"] = bool(
                relative_loss > relative_loss_threshold + relative_uncertainty)
            if row["relative_violation"]:
                definite_relative_violations += 1
        if abs(result_length - min_remaining_wall_mm) <= uncertainty:
            row["reason"] = "ABSOLUTE_GUARD_WITHIN_FLOAT32_UNCERTAINTY"
            unknown_count += 1
            reason_counts[row["reason"]] += 1
            rows.append(row)
            continue
        if result_length < min_remaining_wall_mm - uncertainty:
            row["status"] = "SAMPLED_FAIL"
            row["reason"] = "ABSOLUTE_MIN_WALL_VIOLATION"
            reason_counts[row["reason"]] += 1
            rows.append(row)
            continue
        if abs(relative_loss - relative_loss_threshold) <= relative_uncertainty:
            row["reason"] = "RELATIVE_GUARD_WITHIN_FLOAT32_UNCERTAINTY"
            unknown_count += 1
            reason_counts[row["reason"]] += 1
            rows.append(row)
            continue
        row["status"] = "SAMPLED_PASS"
        row["reason"] = None
        rows.append(row)

    # Recompute qualification counters from terminal row states. Intermediate geometry parsing
    # must never let a threshold-uncertain sample count as complete coverage.
    terminal_unknown = sum(row["status"] == "UNKNOWN" for row in rows)
    terminal_classified = sum(row["status"] in {"SAMPLED_PASS", "SAMPLED_FAIL"} for row in rows)
    terminal_measured = sum(row["result_interval_mm"] is not None for row in rows)
    relative_metric_unknowns = sum(row["relative_violation"] is None for row in rows)
    unknown_count = int(terminal_unknown)
    classified = int(terminal_classified)
    paired = int(terminal_measured)
    if unknown_count == 0 and relative_metric_unknowns == 0:
        fraction = definite_relative_violations / n
        budget_exceeded = fraction > relative_violation_budget
        if budget_exceeded:
            reason_counts["RELATIVE_VIOLATION_BUDGET_EXCEEDED"] += 1
    else:
        fraction = None
        budget_exceeded = False
    terminal_failures = sum(row["status"] == "SAMPLED_FAIL" for row in rows)
    sampled_status = ("SAMPLED_FAIL" if terminal_failures or budget_exceeded else
                      "UNKNOWN" if unknown_count else "SAMPLED_PASS")

    base.update({
        "sampled_interval_status": sampled_status,
        "global_wall_status": "UNVERIFIED",
        "physical_qualification_status": "UNKNOWN",
        "stations_requested": n,
        "stations_classified": int(classified),
        "stations_measured": int(paired),
        "paired_valid": int(paired),
        "unknown_samples": int(unknown_count),
        "relative_metric_unknown_samples": int(relative_metric_unknowns),
        "coverage_fraction": float(classified / n) if n else None,
        "measurement_coverage_fraction": float(paired / n) if n else None,
        "sampled_violation_count": (int(definite_relative_violations)
                                     if fraction is not None else None),
        "sampled_violation_fraction": (float(fraction) if fraction is not None else None),
        "observed_min_source_interval_mm": (float(min(observed_source))
                                            if observed_source else None),
        "observed_min_remaining_interval_mm": (float(min(observed_result))
                                                if observed_result else None),
        "perforated_samples": int(reason_counts.get("PERFORATED", 0)),
        "split_interval_samples": int(reason_counts.get("SPLIT_INTERVAL", 0)),
        "reason_counts": dict(sorted(reason_counts.items())),
        "station_results": rows,
        "direction_evidence": dict(direction_meta),
        "result_evidence": dict(result_meta),
        "merge_tolerance_mm": float(tol),
        "float32_precision_bound_mm": float(precision_bound),
        "measurement_uncertainty_mm": float(uncertainty),
        "probe_offset_mm": float(probe_offset_mm),
        "occupancy_nsamples": int(occupancy_nsamples),
        "native_api_call_plan_per_valid_mesh": {
            "legacy_is_self_intersecting": 1,
            "list_intersections": 1,
            "compute_distance": "0 or 1 batched call when at least one hit gap is present",
            "compute_occupancy": "0 or 1 batched call when at least one hit gap is present",
        },
        "normal_grazing_cosine_tolerance": 1.0e-4,
        "max_events_per_ray": int(max_events_per_ray),
    })
    return base


def _all_material_intervals(
    mesh: trimesh.Trimesh,
    scene: Any,
    rays: np.ndarray,
    o3d: Any,
    *,
    occupancy_nsamples: int,
    nthreads: int,
    merge_tolerance_mm: float,
    max_events_per_ray: int,
) -> tuple[dict[int, list[tuple[float, float]]], dict[int, str]]:
    """Return all verified material intervals per ray, or an explicit reason per ray."""
    tensor = o3d.core.Tensor(np.ascontiguousarray(rays, dtype=np.float32))
    hit_data = scene.list_intersections(tensor, nthreads=int(nthreads))
    splits = np.asarray(hit_data["ray_splits"].numpy(), dtype=np.int64).reshape(-1)
    t_hit = np.asarray(hit_data["t_hit"].numpy(), dtype=np.float64).reshape(-1)
    primitive_ids = np.asarray(hit_data["primitive_ids"].numpy(), dtype=np.int64).reshape(-1)
    if splits.shape != (len(rays) + 1,) or splits[0] != 0 or splits[-1] != len(t_hit):
        return {}, {i: "INVALID_ALL_HIT_RESPONSE" for i in range(len(rays))}
    if primitive_ids.shape != t_hit.shape:
        return {}, {i: "INVALID_ALL_HIT_RESPONSE" for i in range(len(rays))}

    face_normals = np.asarray(mesh.face_normals, dtype=np.float64)
    reasons: dict[int, str] = {}
    occupancy_points: list[np.ndarray] = []
    occupancy_ranges: dict[int, tuple[int, int]] = {}
    groups_by_ray: dict[int, list[tuple[float, int]]] = {}
    directions = np.asarray(rays[:, 3:6], dtype=np.float64)

    for ray_index in range(len(rays)):
        lo = int(splits[ray_index])
        hi = int(splits[ray_index + 1])
        if hi - lo > int(max_events_per_ray):
            reasons[ray_index] = "EVENT_LIMIT_REACHED"
            continue
        distances = t_hit[lo:hi]
        faces = primitive_ids[lo:hi]
        if not np.isfinite(distances).all() or np.any(distances < -merge_tolerance_mm):
            reasons[ray_index] = "NONFINITE_OR_NEGATIVE_HIT"
            continue
        if np.any((faces < 0) | (faces >= len(face_normals))):
            reasons[ray_index] = "INVALID_PRIMITIVE_ID"
            continue
        order = np.argsort(distances, kind="stable")
        distances = distances[order]
        faces = faces[order]
        groups: list[tuple[list[float], list[int]]] = []
        for t_value, face_id in zip(distances, faces, strict=True):
            if not groups or float(t_value) - groups[-1][0][0] > merge_tolerance_mm:
                groups.append(([float(t_value)], [int(face_id)]))
            else:
                groups[-1][0].append(float(t_value))
                groups[-1][1].append(int(face_id))
        events: list[tuple[float, int]] = []
        ray_direction = directions[ray_index]
        for values, face_ids in groups:
            t_event = float(np.median(np.asarray(values, dtype=np.float64)))
            dots = face_normals[np.asarray(face_ids, dtype=np.int64)] @ ray_direction
            if not np.isfinite(dots).all():
                reasons[ray_index] = "NONFINITE_EVENT_NORMAL"
                break
            grazing = np.abs(dots) <= 1.0e-4
            signs = np.where(dots < -1.0e-4, -1, np.where(dots > 1.0e-4, 1, 0))
            nonzero_signs = set(int(v) for v in signs if v != 0)
            if bool(np.any(grazing)):
                reasons[ray_index] = "GRAZING_EVENT"
                break
            if len(nonzero_signs) != 1:
                reasons[ray_index] = "NORMAL_CONFLICT_EVENT"
                break
            events.append((t_event, next(iter(nonzero_signs))))
        if ray_index in reasons:
            continue
        if not events:
            # A no-hit ray is kept distinct from a bad ray; the caller decides whether it means
            # an invalid source station or a measured perforation in a trusted subset result.
            groups_by_ray[ray_index] = []
            continue
        if events[0][0] <= 4.0 * merge_tolerance_mm:
            reasons[ray_index] = "FIRST_EVENT_WITHIN_FLOAT32_SURFACE_BAND"
            continue
        gaps: list[np.ndarray] = []
        first_t = events[0][0]
        gaps.append(rays[ray_index, :3].astype(np.float64)
                    + directions[ray_index] * (0.5 * first_t))
        unresolved_gap = False
        for left, right in zip(events, events[1:], strict=False):
            gap = right[0] - left[0]
            if gap <= 4.0 * merge_tolerance_mm:
                unresolved_gap = True
                break
            gaps.append(rays[ray_index, :3].astype(np.float64)
                        + directions[ray_index] * (0.5 * (left[0] + right[0])))
        if unresolved_gap:
            reasons[ray_index] = "UNRESOLVED_GAP_BETWEEN_EVENTS"
            continue
        tail_step = max(8.0 * merge_tolerance_mm, 0.25e-3)
        gaps.append(rays[ray_index, :3].astype(np.float64)
                    + directions[ray_index] * (events[-1][0] + tail_step))
        start_index = len(occupancy_points)
        occupancy_points.extend(gaps)
        occupancy_ranges[ray_index] = (start_index, len(occupancy_points))
        groups_by_ray[ray_index] = events

    if occupancy_points:
        points = np.ascontiguousarray(np.asarray(occupancy_points, dtype=np.float32))
        try:
            surface_distance = scene.compute_distance(
                o3d.core.Tensor(points), nthreads=int(nthreads))
            distances = np.asarray(surface_distance.numpy(), dtype=np.float64)
            if distances.shape != (len(points),):
                return {}, {**reasons,
                            **{i: "INVALID_SURFACE_DISTANCE_RESPONSE" for i in occupancy_ranges}}
            if not np.isfinite(distances).all():
                return {}, {**reasons,
                            **{i: "NONFINITE_SURFACE_DISTANCE_RESPONSE" for i in occupancy_ranges}}
            near_surface = distances <= 2.0 * merge_tolerance_mm
            for ray_index, (start, end) in occupancy_ranges.items():
                if bool(np.any(near_surface[start:end])):
                    reasons[ray_index] = "GAP_PROBE_ON_OR_NEAR_SURFACE"
        except Exception:
            return {}, {**reasons,
                        **{i: "SURFACE_DISTANCE_QUERY_FAILED" for i in occupancy_ranges}}

        query_point_indices: list[int] = []
        occupancy_query_ranges: dict[int, tuple[int, int]] = {}
        for ray_index, (start, end) in occupancy_ranges.items():
            if ray_index in reasons:
                continue
            query_start = len(query_point_indices)
            query_point_indices.extend(range(start, end))
            occupancy_query_ranges[ray_index] = (query_start, len(query_point_indices))
        if query_point_indices:
            query_points = np.ascontiguousarray(points[query_point_indices])
            try:
                occupancy = scene.compute_occupancy(
                    o3d.core.Tensor(query_points), nthreads=int(nthreads),
                    nsamples=int(occupancy_nsamples))
                occupancy_values = np.asarray(occupancy.numpy(), dtype=np.float64)
                if occupancy_values.shape != (len(query_points),):
                    return {}, {**reasons,
                                **{i: "INVALID_OCCUPANCY_RESPONSE"
                                   for i in occupancy_query_ranges}}
                if not np.isfinite(occupancy_values).all():
                    return {}, {**reasons,
                                **{i: "NONFINITE_OCCUPANCY_RESPONSE"
                                   for i in occupancy_query_ranges}}
                occupied = occupancy_values > 0.5
            except Exception:
                return {}, {**reasons,
                            **{i: "OCCUPANCY_QUERY_FAILED" for i in occupancy_query_ranges}}
        else:
            occupied = np.zeros(0, dtype=bool)
    else:
        occupied = np.zeros(0, dtype=bool)
        occupancy_query_ranges = {}

    intervals: dict[int, list[tuple[float, float]]] = {}
    for ray_index, events in groups_by_ray.items():
        if ray_index in reasons:
            continue
        if not events:
            intervals[ray_index] = []
            continue
        start, end = occupancy_query_ranges[ray_index]
        states = occupied[start:end]
        if len(states) != len(events) + 1:
            reasons[ray_index] = "INVALID_OCCUPANCY_GAP_COUNT"
            continue
        if bool(states[0]) or bool(states[-1]):
            reasons[ray_index] = "RAY_NOT_OUTSIDE_AT_ENDS"
            continue
        line_intervals: list[tuple[float, float]] = []
        entry: float | None = None
        ray_bad = False
        for event_index, (t_event, normal_sign) in enumerate(events):
            before = bool(states[event_index])
            after = bool(states[event_index + 1])
            if before == after:
                reasons[ray_index] = "GRAZING_OR_NONCROSSING_EVENT"
                ray_bad = True
                break
            if not before and after:
                if normal_sign != -1 or entry is not None:
                    reasons[ray_index] = "ORIENTATION_OCCUPANCY_CONFLICT"
                    ray_bad = True
                    break
                entry = float(t_event)
            elif before and not after:
                if normal_sign != 1 or entry is None:
                    reasons[ray_index] = "ORIENTATION_OCCUPANCY_CONFLICT"
                    ray_bad = True
                    break
                if float(t_event) - entry <= 2.0 * merge_tolerance_mm:
                    reasons[ray_index] = "UNRESOLVED_THIN_INTERVAL"
                    ray_bad = True
                    break
                line_intervals.append((entry, float(t_event)))
                entry = None
        if ray_bad:
            continue
        if entry is not None:
            reasons[ray_index] = "UNPAIRED_ENTRY_EVENT"
            continue
        intervals[ray_index] = line_intervals
    return intervals, reasons


def _build_scene(mesh: trimesh.Trimesh, origin: np.ndarray, o3d: Any) -> Any:
    vertices = (np.asarray(mesh.vertices, dtype=np.float64) - np.asarray(origin, dtype=np.float64))
    faces = np.asarray(mesh.faces, dtype=np.int32)
    legacy = o3d.geometry.TriangleMesh(
        o3d.utility.Vector3dVector(np.ascontiguousarray(vertices)),
        o3d.utility.Vector3iVector(np.ascontiguousarray(faces)))
    tensor_mesh = o3d.t.geometry.TriangleMesh.from_legacy(legacy)
    scene = o3d.t.geometry.RaycastingScene()
    scene.add_triangles(tensor_mesh)
    return scene


def _mesh_health(mesh: Any, o3d: Any) -> dict[str, Any]:
    if not isinstance(mesh, trimesh.Trimesh):
        return {"valid": False, "reason": "NOT_TRIMESH"}
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    if vertices.ndim != 2 or vertices.shape[1:] != (3,) or not np.isfinite(vertices).all():
        return {"valid": False, "reason": "NONFINITE_OR_INVALID_VERTICES"}
    if faces.ndim != 2 or faces.shape[1:] != (3,) or len(faces) < 4:
        return {"valid": False, "reason": "DEGENERATE_OR_EMPTY_FACES"}
    if np.any((faces < 0) | (faces >= len(vertices))):
        return {"valid": False, "reason": "INVALID_FACE_INDEX"}
    bounds = np.asarray(mesh.bounds, dtype=np.float64)
    diagonal = float(np.linalg.norm(bounds[1] - bounds[0])) if bounds.shape == (2, 3) else float("nan")
    areas = np.asarray(mesh.area_faces, dtype=np.float64)
    area_floor = max(1.0e-14, 1.0e-14 * diagonal * diagonal) if np.isfinite(diagonal) else 1.0e-14
    if not np.isfinite(diagonal) or diagonal <= 0 or not np.isfinite(areas).all() \
            or np.any(areas <= area_floor):
        return {"valid": False, "reason": "DEGENERATE_OR_NONFINITE_TRIANGLES",
                "bounds_diagonal_mm": diagonal, "area_floor_mm2": float(area_floor)}
    try:
        watertight = bool(mesh.is_watertight)
        winding_consistent = bool(mesh.is_winding_consistent)
        volume = float(mesh.volume)
    except Exception:
        return {"valid": False, "reason": "MESH_HEALTH_QUERY_FAILED",
                "bounds_diagonal_mm": diagonal}
    if not watertight:
        reason = "OPEN_MESH"
    elif not winding_consistent:
        reason = "INCONSISTENT_WINDING"
    elif not np.isfinite(volume) or volume <= 0.0:
        reason = "INVERTED_OR_NONPOSITIVE_VOLUME"
    else:
        reason = None
    self_intersecting: bool | None = None
    if reason is None:
        try:
            if not callable(getattr(o3d.geometry.TriangleMesh, "is_self_intersecting", None)):
                raise AttributeError("TriangleMesh.is_self_intersecting unavailable")
            legacy = o3d.geometry.TriangleMesh(
                o3d.utility.Vector3dVector(np.ascontiguousarray(vertices)),
                o3d.utility.Vector3iVector(np.ascontiguousarray(faces, dtype=np.int32)))
            self_intersecting = bool(legacy.is_self_intersecting())
        except Exception:
            return {"valid": False, "reason": "SELF_INTERSECTION_CHECK_UNAVAILABLE_OR_FAILED",
                    "watertight": watertight, "winding_consistent": winding_consistent,
                    "signed_volume_mm3": volume, "bounds_diagonal_mm": diagonal,
                    "face_count": int(len(faces)), "vertex_count": int(len(vertices)),
                    "self_intersecting": None}
        if self_intersecting:
            reason = "SELF_INTERSECTING"
    return {"valid": reason is None, "reason": reason, "watertight": watertight,
            "winding_consistent": winding_consistent, "signed_volume_mm3": volume,
            "bounds_diagonal_mm": diagonal, "area_floor_mm2": float(area_floor),
            "face_count": int(len(faces)), "vertex_count": int(len(vertices)),
            "self_intersecting": self_intersecting}


def _evidence_mapping(evidence: Any) -> dict[str, Any]:
    if evidence is None:
        return {}
    if isinstance(evidence, Mapping):
        return dict(evidence)
    if hasattr(evidence, "__dataclass_fields__"):
        return {name: getattr(evidence, name) for name in evidence.__dataclass_fields__}
    return {}


def _public_evidence(evidence: Any, fields: Sequence[str]) -> dict[str, Any]:
    raw = _evidence_mapping(evidence)
    safe: dict[str, Any] = {}
    for field in fields:
        value = raw.get(field)
        if isinstance(value, float) and not np.isfinite(value):
            safe[field] = None
        elif value is None or isinstance(value, (str, bool, int, float)):
            safe[field] = value
        else:
            safe[field] = str(value)
    return safe


def _trusted_directions(evidence: Mapping[str, Any]) -> bool:
    return bool(evidence.get("trusted") is True
                and str(evidence.get("source", "")) in _DIRECTION_SOURCES
                and evidence.get("convention") == "outward_from_source"
                and evidence.get("units") == "mm"
                and _has_provenance(evidence.get("provenance")))


def _trusted_subset(evidence: Mapping[str, Any]) -> bool:
    return bool(evidence.get("trusted") is True
                and evidence.get("relation") == _RESULT_RELATION
                and _has_provenance(evidence.get("provenance")))


def _has_provenance(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _station_ids(values: Sequence[str] | None, n: int) -> list[str] | None:
    if values is None:
        return [f"station-{i:04d}" for i in range(n)]
    ids = [str(value) for value in values]
    if len(ids) != n or any(not value for value in ids) or len(set(ids)) != n:
        return None
    return ids


def _parameter_error(min_wall: float, relative_threshold: float, budget: float,
                     probe_offset: float, occupancy_samples: int, nthreads: int,
                     max_events: int) -> str | None:
    try:
        values = tuple(float(value) for value in
                       (min_wall, relative_threshold, budget, probe_offset))
        occupancy_samples = int(occupancy_samples)
        nthreads = int(nthreads)
        max_events = int(max_events)
    except (TypeError, ValueError, OverflowError):
        return "INVALID_GUARD_PARAMETER"
    if not all(np.isfinite(value) for value in values):
        return "NONFINITE_GUARD_PARAMETER"
    min_wall, relative_threshold, budget, probe_offset = values
    if min_wall <= 0 or not 0 < relative_threshold <= 1 or not 0 <= budget <= 1:
        return "INVALID_GUARD_PARAMETER"
    if probe_offset <= 0 or occupancy_samples <= 0 or occupancy_samples % 2 != 1 \
            or nthreads < 0 or max_events <= 0:
        return "INVALID_RAYCAST_PARAMETER"
    return None


def _report_base(n: int, ids: Sequence[str], min_wall: float,
                 relative_threshold: float, budget: float) -> dict[str, Any]:
    return {
        "algorithm": _ALGORITHM,
        "units": "mm",
        "sampled_interval_status": "UNKNOWN",
        "global_wall_status": "UNVERIFIED",
        "physical_qualification_status": "UNKNOWN",
        "stations_requested": int(n),
        "stations_classified": 0,
        "stations_measured": 0,
        "paired_valid": 0,
        "unknown_samples": int(n),
        "relative_metric_unknown_samples": int(n),
        "coverage_fraction": 0.0 if n else None,
        "measurement_coverage_fraction": 0.0 if n else None,
        "sampled_violation_count": None,
        "sampled_violation_fraction": None,
        "observed_min_source_interval_mm": None,
        "observed_min_remaining_interval_mm": None,
        "perforated_samples": 0,
        "split_interval_samples": 0,
        "reason_counts": {},
        "station_results": [{
            "station_id": str(station_id), "status": "UNKNOWN", "reason": "NOT_PROCESSED",
            "source_interval_index": None, "source_interval_mm": None,
            "result_interval_mm": None, "source_length_mm": None,
            "remaining_length_mm": None, "loss_mm": None, "relative_loss": None,
            "relative_violation": None, "result_intervals_mm": None,
        } for station_id in ids],
        "guard": {"min_remaining_wall_mm": _finite_json_number(min_wall),
                  "relative_loss_threshold": _finite_json_number(relative_threshold),
                  "relative_violation_budget": _finite_json_number(budget)},
        "mesh_health": None,
    }


def _finite_json_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if np.isfinite(number) else None


def _empty_unknown(reason: str, min_wall: float, relative_threshold: float,
                   budget: float) -> dict[str, Any]:
    report = _report_base(0, [], min_wall, relative_threshold, budget)
    report["reason_counts"] = {reason: 1}
    return report


def _unknown_for_stations(n: int, ids: Sequence[str], reason: str, min_wall: float,
                          relative_threshold: float, budget: float,
                          **extras: Any) -> dict[str, Any]:
    report = _report_base(n, ids, min_wall, relative_threshold, budget)
    report["reason_counts"] = {reason: int(n) if n else 1}
    for row in report["station_results"]:
        row["reason"] = reason
    report.update(extras)
    return report
