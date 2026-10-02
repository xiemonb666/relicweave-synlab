"""Bounded L-system / turtle grammar and svgpathtools path work (plan 9.5).

Reuse policy (plan 2.4 / A23):

* ``svgpathtools`` owns Bezier/Arc objects, **arc length** and segmentation
  (``Path.length``, ``Seg.point``); this module only adds the bounded grammar and the
  adaptive flattening loop that drives those library calls.
* ``shapely`` owns the 2-D closed-outline / fill geometry (validity, area, unions).
* Nothing here re-implements an SVG parser, a font engine or a Bezier solver.

The grammar is deliberately bounded: 3-5 generations, an explicit total segment cap and
a deterministic per-node hash that fixes the branching probability (no RNG at all in the
grammar itself, so a motif is reproducible from the recipe string).
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

import numpy as np
from shapely.geometry import Polygon
from shapely.ops import unary_union
from svgpathtools import CubicBezier, Line, Path

from ..errors import ErrorCode, SynLabError

MAX_GENERATIONS = 5
MIN_GENERATIONS = 3


# ---------------------------------------------------------------------------------------
# bounded L-system / turtle
# ---------------------------------------------------------------------------------------
@dataclass
class TurtleResult:
    polylines: list[np.ndarray]              # each (M,2) in local motif millimetres
    stats: dict[str, Any] = field(default_factory=dict)


def expand_lsystem(rule: str, generations: int, *, segment_cap: int,
                   axiom: str = "F") -> tuple[str, dict[str, Any]]:
    """Expand an L-system string with a hard segment cap (plan 9.5)."""
    gens = int(generations)
    if not (MIN_GENERATIONS <= gens <= MAX_GENERATIONS):
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"L-system generations must be in [{MIN_GENERATIONS}, {MAX_GENERATIONS}], "
                          f"got {gens}", stage="patterns.grammar.expand_lsystem")
    if rule.count("F") < 2:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"L-system rule {rule!r} must produce at least two F segments",
                          stage="patterns.grammar.expand_lsystem")
    text = axiom
    truncated = False
    for _ in range(gens):
        if text.count("F") * rule.count("F") > int(segment_cap) * 4:
            # stop expanding early and record it; the interpreter caps the rest
            truncated = True
            break
        text = "".join(rule if ch == "F" else ch for ch in text)
    if text.count("F") > int(segment_cap):
        truncated = True
        kept: list[str] = []
        used = 0
        for ch in text:
            if ch == "F":
                if used >= int(segment_cap):
                    break
                used += 1
            kept.append(ch)
        text = "".join(kept)
    return text, {
        "generations": gens, "rule": rule, "axiom": axiom,
        "n_segments_planned": int(text.count("F")), "segment_cap": int(segment_cap),
        "truncated_at_cap": bool(truncated), "string_length": len(text),
    }


def _node_hash(path_string: str) -> float:
    """Deterministic per-node value in [0,1) taken from the node path hash."""
    digest = hashlib.sha256(path_string.encode("utf-8")).digest()
    return int.from_bytes(digest[:6], "big") / float(1 << 48)


def turtle_from_string(text: str, *, step_mm: float, angle_deg: float,
                       branch_probability: float, heading_deg: float = 90.0,
                       origin: tuple[float, float] = (0.0, 0.0)) -> TurtleResult:
    """Interpret ``F + - [ ]`` with a bounded stack; branching is hash-determined."""
    x, y = float(origin[0]), float(origin[1])
    heading = math.radians(float(heading_deg))
    stack: list[tuple[float, float, float, str]] = []
    current: list[tuple[float, float]] = [(x, y)]
    polylines: list[np.ndarray] = []
    segments = 0
    skipped = 0
    path_string = ""
    for ch in text:
        if ch == "F":
            path_string += "F"
            local = _node_hash(path_string)
            if local > branch_probability and stack:
                # deterministic thinning of side branches only (never the main axis)
                skipped += 1
                continue
            length = float(step_mm) * (0.75 + 0.5 * _node_hash(path_string + "#len"))
            x += length * math.cos(heading)
            y += length * math.sin(heading)
            current.append((x, y))
            segments += 1
        elif ch == "+":
            turn = float(angle_deg) * (0.7 + 0.6 * _node_hash(path_string + "#plus"))
            heading += math.radians(turn)
        elif ch == "-":
            turn = float(angle_deg) * (0.7 + 0.6 * _node_hash(path_string + "#minus"))
            heading -= math.radians(turn)
        elif ch == "[":
            stack.append((x, y, heading, path_string))
            path_string += "["
        elif ch == "]":
            if len(current) > 1:
                polylines.append(np.asarray(current, dtype=np.float64))
            if stack:
                x, y, heading, path_string = stack.pop()
                current = [(x, y)]
            else:
                current = [(x, y)]
    if len(current) > 1:
        polylines.append(np.asarray(current, dtype=np.float64))
    stats = {
        "n_segments": int(segments), "n_branches": len(polylines),
        "n_skipped_branches": int(skipped),
        "branch_probability": float(branch_probability),
        "branch_rule": "branch accepted when sha256(node path)[0:6]/2**48 <= branch_probability",
        "step_mm": float(step_mm), "angle_deg": float(angle_deg),
        "stack_depth_max": len(stack),
    }
    return TurtleResult(polylines=polylines, stats=stats)


# ---------------------------------------------------------------------------------------
# svgpathtools: arc length, adaptive flattening
# ---------------------------------------------------------------------------------------
@dataclass
class FlattenResult:
    xy: np.ndarray                 # (M,2)
    stats: dict[str, Any] = field(default_factory=dict)


def flatten_path(path: Path, *, max_chord_error_mm: float, max_points: int = 20000,
                 initial_per_segment: int = 16) -> FlattenResult:
    """Adaptive flattening driven by ``svgpathtools`` segment evaluation.

    Each segment parameter interval is bisected while the midpoint deviates more than
    ``max_chord_error_mm`` from the chord (bounded recursion).  The achieved chord error
    is measured afterwards on the produced polyline.
    """
    if len(path) == 0:
        return FlattenResult(xy=np.zeros((0, 2)), stats={"n_segments": 0, "n_points": 0})
    points: list[complex] = []
    per_segment: list[int] = []
    budget = int(max_points)
    for seg in path:
        seg_points: list[complex] = []

        def refine(a: float, b: float, depth: int) -> None:
            if len(seg_points) + len(points) > budget:
                return
            mid = 0.5 * (a + b)
            p_mid = seg.point(mid)
            chord_mid = 0.5 * (seg.point(a) + seg.point(b))
            if depth <= 0 or abs(p_mid - chord_mid) <= max_chord_error_mm:
                return
            refine(a, mid, depth - 1)
            seg_points.append(p_mid)
            refine(mid, b, depth - 1)

        seg_points.append(seg.point(0.0))
        steps = max(2, int(initial_per_segment))
        for index in range(steps):
            a = index / steps
            b = (index + 1) / steps
            refine(a, b, 6)
            seg_points.append(seg.point(b))
        per_segment.append(len(seg_points))
        points.extend(seg_points)
    xy = np.stack([np.real(points), np.imag(points)], axis=1)
    chord_error = _measure_chord_error(path, xy, max_chord_error_mm)
    return FlattenResult(xy=xy, stats={
        "n_segments": len(path),
        "n_points": int(xy.shape[0]),
        "points_per_segment_max": int(max(per_segment)) if per_segment else 0,
        "requested_chord_error_mm": float(max_chord_error_mm),
        "achieved_chord_error_mm": chord_error,
        "length_mm": float(path.length()),
        "closed": bool(path.isclosed()),
        "method": "svgpathtools Path/Seg.point with bounded adaptive bisection",
    })


def _measure_chord_error(path: Path, xy: np.ndarray, target: float) -> float:
    """Measured deviation of the true path from the flattened *polyline* (not its vertices).

    Distance is taken to the segments, so the number is the real chord error of the
    flattening instead of half the vertex spacing.
    """
    del target
    if xy.shape[0] < 2 or len(path) == 0:
        return 0.0
    samples = np.linspace(0.0, 1.0, 97)
    p0 = xy[:-1]
    d = xy[1:] - p0
    denom = np.where((d ** 2).sum(axis=1) > 0, (d ** 2).sum(axis=1), 1.0)
    worst = 0.0
    for t in samples:
        point = path.point(float(t))
        axis = np.array([point.real, point.imag])
        rel = axis[None, :] - p0
        u = np.clip((rel * d).sum(axis=1) / denom, 0.0, 1.0)
        closest = p0 + u[:, None] * d
        worst = max(worst, float(np.sqrt(((axis[None, :] - closest) ** 2).sum(axis=1)).min()))
    return worst


def bezier_wave_path(*, x_period_mm: float, s_centre_mm: float, amplitude_mm: float,
                     n_waves: int, harmonics: Sequence[float] = (1.0,)) -> Path:
    """Periodic Bezier centre line: ``n_waves`` cubic segments closing exactly at u=0/1.

    A single cubic with quarter-point controls has an amplitude of ``0.75*A``; the
    control offsets are scaled accordingly and the achieved amplitude is *measured* from
    the flattened path (never assumed).  ``harmonics`` adds counter-phase wave pairs at
    integer multiples of the base count so the seam still closes exactly.
    """
    waves = max(1, int(n_waves))
    pitch = float(x_period_mm) / waves
    segments = []
    for index in range(waves):
        x0 = index * pitch
        x1 = x0 + pitch
        s0 = float(s_centre_mm)
        offset = float(amplitude_mm) / 0.75
        c1 = complex(x0 + 0.25 * pitch, s0 + offset)
        c2 = complex(x0 + 0.75 * pitch, s0 - offset)
        segments.append(CubicBezier(complex(x0, s0), c1, c2, complex(x1, s0)))
    path = Path(*segments)
    extra = [float(h) for h in list(harmonics)[1:]]
    for order, factor in enumerate(extra, start=2):
        amp = float(amplitude_mm) * factor / 0.75
        for index in range(waves * order):
            x0 = index * pitch / order
            x1 = x0 + pitch / order
            c1 = complex(x0 + 0.25 * pitch / order, s_centre_mm + amp)
            c2 = complex(x0 + 0.75 * pitch / order, s_centre_mm - amp)
            path.append(CubicBezier(complex(x0, s_centre_mm), c1, c2, complex(x1, s_centre_mm)))
    return path


def polyline_length(xy: np.ndarray) -> float:
    if xy.shape[0] < 2:
        return 0.0
    d = np.diff(np.asarray(xy, dtype=np.float64), axis=0)
    return float(np.sqrt((d ** 2).sum(axis=1)).sum())


def polyline_tangents(xy: np.ndarray) -> np.ndarray:
    xy = np.asarray(xy, dtype=np.float64)
    if xy.shape[0] < 2:
        return np.zeros((xy.shape[0], 2))
    d = np.gradient(xy, axis=0)
    norm = np.sqrt((d ** 2).sum(axis=1))
    norm = np.where(norm > 0, norm, 1.0)
    return d / norm[:, None]


def polyline_to_bezier_path(xy: np.ndarray, *, curvature: float = 0.3) -> Path:
    """Turn a turtle polyline into cubic Beziers so svgpathtools owns arc length.

    Control points are placed along the local tangent (scaled by ``curvature`` times the
    segment length), which keeps the curve close to the polyline while giving the
    library a real analytic path to measure and flatten.
    """
    pts = np.asarray(xy, dtype=np.float64)
    if pts.shape[0] < 2:
        raise ValueError("polyline_to_bezier_path needs at least two points")
    tangents = polyline_tangents(pts)
    segments = []
    for index in range(pts.shape[0] - 1):
        a, b = pts[index], pts[index + 1]
        length = float(np.hypot(*(b - a)))
        if length <= 0:
            continue
        c1 = a + tangents[index] * (curvature * length)
        c2 = b - tangents[index + 1] * (curvature * length)
        segments.append(CubicBezier(complex(*a), complex(*c1), complex(*c2), complex(*b)))
    if not segments:
        raise ValueError("polyline_to_bezier_path produced no segments")
    return Path(*segments)


def resample_by_arclength(xy: np.ndarray, spacing_mm: float) -> np.ndarray:
    """Points along a polyline separated by ``spacing_mm`` of arc length."""
    xy = np.asarray(xy, dtype=np.float64)
    if xy.shape[0] < 2 or spacing_mm <= 0:
        return xy
    seg = np.diff(xy, axis=0)
    lengths = np.sqrt((seg ** 2).sum(axis=1))
    cumulative = np.concatenate([[0.0], np.cumsum(lengths)])
    total = float(cumulative[-1])
    if total <= 0:
        return xy[:1]
    targets = np.arange(0.0, total, float(spacing_mm))
    out = []
    for target in targets:
        idx = int(np.searchsorted(cumulative, target, side="right") - 1)
        idx = max(0, min(idx, xy.shape[0] - 2))
        span = cumulative[idx + 1] - cumulative[idx]
        frac = 0.0 if span <= 0 else (target - cumulative[idx]) / span
        out.append(xy[idx] + frac * (xy[idx + 1] - xy[idx]))
    return np.asarray(out, dtype=np.float64)


# ---------------------------------------------------------------------------------------
# leaves (Bezier outline + shapely fill)
# ---------------------------------------------------------------------------------------
def leaf_outline(*, length_mm: float, width_mm: float, chord_error_mm: float = 0.05
                 ) -> tuple[np.ndarray, dict[str, Any]]:
    """Closed teardrop outline built from two cubic Beziers and flattened by svgpathtools."""
    half = 0.5 * float(width_mm)
    length = float(length_mm)
    tip = complex(length, 0.0)
    upper = CubicBezier(0j, complex(0.25 * length, half * 1.4),
                        complex(0.7 * length, half * 1.25), tip)
    lower = CubicBezier(tip, complex(0.7 * length, -half * 1.25),
                        complex(0.25 * length, -half * 1.4), 0j)
    path = Path(upper, lower)
    flat = flatten_path(path, max_chord_error_mm=chord_error_mm, max_points=512)
    polygon = Polygon(flat.xy)
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    shape = np.asarray(polygon.exterior.coords, dtype=np.float64) if polygon.geom_type == "Polygon" \
        else flat.xy
    stats = {
        "requested_length_mm": length, "requested_width_mm": float(width_mm),
        "path_length_mm": float(path.length()),
        "shapely_area_mm2": float(polygon.area),
        "shapely_valid": bool(polygon.is_valid),
        "flatten": flat.stats,
    }
    return shape, stats


def leaf_placement(stem_xy: np.ndarray, *, spacing_mm: float, length_mm: float,
                   width_mm: float, angle_deg: float, chord_error_mm: float = 0.05
                   ) -> tuple[list[np.ndarray], list[np.ndarray], dict[str, Any]]:
    """Place leaf outlines along a stem by arc length; returns (leaves, stems, stats)."""
    stem = np.asarray(stem_xy, dtype=np.float64)
    anchors = resample_by_arclength(stem, spacing_mm)
    tangents = polyline_tangents(stem)
    outline, shape_stats = leaf_outline(length_mm=length_mm, width_mm=width_mm,
                                        chord_error_mm=chord_error_mm)
    leaves: list[np.ndarray] = []
    areas: list[float] = []
    for index, anchor in enumerate(anchors):
        # nearest stem sample for the tangent
        distances = ((stem - anchor[None, :]) ** 2).sum(axis=1)
        local = tangents[int(np.argmin(distances))]
        base_angle = math.atan2(local[1], local[0])
        for sign in (1.0, -1.0):
            angle = base_angle + sign * math.radians(angle_deg) * (1.0 if index % 2 == 0 else 0.8)
            rot = np.array([[math.cos(angle), -math.sin(angle)],
                            [math.sin(angle), math.cos(angle)]])
            pts = outline @ rot.T + anchor[None, :]
            leaves.append(pts)
            poly = Polygon(pts)
            areas.append(float(poly.area if poly.is_valid else poly.buffer(0).area))
    stats = dict(shape_stats)
    stats.update({
        "n_leaves": len(leaves),
        "leaf_spacing_mm": float(spacing_mm),
        "leaf_placement": "anchors by arc length along the svgpathtools-flattened stem",
        "leaf_area_mm2_mean": float(np.mean(areas)) if areas else 0.0,
        "leaf_angle_deg": float(angle_deg),
    })
    return leaves, [stem], stats


def polygon_union_area(polygons: Iterable[np.ndarray]) -> float:
    shapes = []
    for pts in polygons:
        poly = Polygon(np.asarray(pts, dtype=np.float64))
        if not poly.is_valid:
            poly = poly.buffer(0)
        if poly.area > 0:
            shapes.append(poly)
    if not shapes:
        return 0.0
    return float(unary_union(shapes).area)
