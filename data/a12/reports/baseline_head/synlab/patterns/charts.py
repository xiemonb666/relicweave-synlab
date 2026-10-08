"""Mother chart semantics used by the pattern module (plan 7.1 / 9.2).

Frozen coordinate contract (``docs/a12/interfaces.md`` + ``docs/a12/patterns.md``):

* ``Chart.to_uv(points_mm) -> (N,2)`` maps authoritative mother millimetres to chart
  coordinates.
* **Revolve / sweep charts**: column 0 is the *periodic* azimuth ``u`` in ``[0,1)``,
  column 1 is the *true profile arc length* ``s_mm``.  ``Chart.x_period_mm`` is the
  reference circumference ``C_ref`` and chart millimetres are ``x_mm = u * C_ref``.
* **Planar charts**: columns 0/1 are already millimetres; ``x_period_mm`` may still
  declare a tiling period (``None`` = open chart).
* ``chart.meta["s_range_mm"]`` is the legal drawing range in profile arc length.  When
  absent it is *measured* from the mother mesh (recorded as
  ``s_range_source="measured_from_mesh"``) instead of being invented.
* ``chart.meta["uv_to_xyz"]`` is an optional inverse map ``(N,2)->(N,3)`` used by the
  seam audit to place exact ``u=0``/``u=1`` pairs in world space.
* ``chart.meta["s_periodic"]`` marks a closed profile (default ``False``).

The measured circumferential spacing is ``2*pi*r(s)/|k|``: it varies with the radius, so
``x_mm`` is an arc length on the *reference* circumference, never a claim that the whole
vessel has one millimetre pitch.  ``circumferential_metric`` reports the real local
range so downstream code can see the difference.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

from ..errors import ErrorCode, SynLabError
from ..schemas.runtime import Chart, MotherGeometry

TWO_PI = 2.0 * np.pi


@dataclass
class ChartFrame:
    """A resolved chart plus the measured geometry facts the pattern layer needs."""

    chart: Chart
    tag: int
    tag_name: str
    name: str
    kind: str
    x_period_mm: float | None
    u_periodic: bool
    s_periodic: bool
    s_min_mm: float
    s_max_mm: float
    s_range_source: str
    area_mm2: float
    to_xyz: Callable[[np.ndarray], np.ndarray] | None
    region_mask: Callable[[np.ndarray], np.ndarray] | None
    circumferential_metric: dict[str, float]
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def s_span_mm(self) -> float:
        return float(self.s_max_mm - self.s_min_mm)

    def xy(self, points_mm: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """World mm -> chart millimetres ``(x_mm, s_mm)``."""
        return to_chart_mm(self, points_mm)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "surface_tag": self.tag_name,
            "surface_tag_index": int(self.tag),
            "u_periodic": bool(self.u_periodic),
            "x_period_mm": (None if self.x_period_mm is None else float(self.x_period_mm)),
            "s_range_mm": [float(self.s_min_mm), float(self.s_max_mm)],
            "s_range_source": self.s_range_source,
            "s_periodic": bool(self.s_periodic),
            "area_mm2": float(self.area_mm2),
            "circumferential_metric": dict(self.circumferential_metric),
            "uv_to_xyz": self.to_xyz is not None,
            "region_mask": self.region_mask is not None,
        }


def tag_index(mother: MotherGeometry, surface_tag: int | str) -> int:
    """Resolve a surface tag given as an index or as a name; never guess silently."""
    if isinstance(surface_tag, str):
        for index, name in (mother.surface_tag_names or {}).items():
            if str(name) == surface_tag:
                return int(index)
        raise SynLabError(
            ErrorCode.SCHEMA_INVALID,
            f"mother {mother.mother_id!r} has no surface tag named {surface_tag!r} "
            f"(known: {sorted((mother.surface_tag_names or {}).values())})",
            stage="patterns.charts.tag_index",
        )
    index = int(surface_tag)
    if mother.surface_tag_names and index not in mother.surface_tag_names:
        raise SynLabError(
            ErrorCode.SCHEMA_INVALID,
            f"mother {mother.mother_id!r} has no surface tag index {index} "
            f"(known: {sorted(mother.surface_tag_names)})",
            stage="patterns.charts.tag_index",
        )
    return index


def chart_for_tag(mother: MotherGeometry, tag: int) -> Chart:
    chart = mother.chart_for_tag(int(tag))
    if chart is None:
        raise SynLabError(
            ErrorCode.SCHEMA_INVALID,
            f"mother {mother.mother_id!r} declares no chart for surface tag "
            f"{mother.tag_name(int(tag))!r}; pattern evaluation needs a chart",
            stage="patterns.charts.chart_for_tag",
        )
    return chart


def _measure_s_range(mother: MotherGeometry, tag: int, chart: Chart,
                     uv: np.ndarray) -> tuple[float, float]:
    """Measure the legal ``s`` range from the mesh when the chart does not declare it."""
    faces = np.asarray(mother.mesh.faces)
    tags = np.asarray(mother.face_surface_tag)
    mask = tags == int(tag)
    if not np.any(mask):
        raise SynLabError(ErrorCode.MOTHER_INVALID,
                          f"no faces carry surface tag {mother.tag_name(int(tag))!r}",
                          stage="patterns.charts.s_range")
    vidx = np.unique(faces[mask].reshape(-1))
    verts = np.asarray(mother.mesh.vertices, dtype=np.float64)[vidx]
    s = chart.uv(verts)[:, 1]
    return float(np.min(s)), float(np.max(s))


def _circumferential_metric(mother: MotherGeometry, tag: int, chart: Chart,
                            x_period: float | None) -> tuple[dict[str, float], float]:
    """Measure the real radius range of the tagged faces and the induced metric scale."""
    faces = np.asarray(mother.mesh.faces)
    tags = np.asarray(mother.face_surface_tag)
    mask = tags == int(tag)
    if not np.any(mask):
        return {}, 0.0
    vidx = np.unique(faces[mask].reshape(-1))
    verts = np.asarray(mother.mesh.vertices, dtype=np.float64)[vidx]
    r = np.hypot(verts[:, 0], verts[:, 1])
    area = float(np.asarray(mother.mesh.area_faces)[mask].sum())
    out = {
        "radius_min_mm": float(r.min()),
        "radius_max_mm": float(r.max()),
        "circumference_min_mm": float(TWO_PI * r.min()),
        "circumference_max_mm": float(TWO_PI * r.max()),
    }
    if x_period:
        out["metric_scale_at_r_min"] = float(TWO_PI * r.min() / x_period)
        out["metric_scale_at_r_max"] = float(TWO_PI * r.max() / x_period)
    return out, area


def resolve_frame(mother: MotherGeometry, surface_tag: int | str) -> ChartFrame:
    """Build a :class:`ChartFrame` with measured (not invented) ranges and metrics."""
    tag = tag_index(mother, surface_tag)
    chart = chart_for_tag(mother, tag)
    meta = dict(chart.meta or {})
    u_periodic = bool(chart.u_periodic)
    x_period = None if chart.x_period_mm is None else float(chart.x_period_mm)

    if u_periodic and x_period is None:
        raise SynLabError(
            ErrorCode.SCHEMA_INVALID,
            f"chart {chart.name!r} is periodic in u but declares no x_period_mm; "
            "the pattern layer refuses to invent a reference circumference",
            stage="patterns.charts.resolve_frame",
        )
    if not u_periodic and x_period is None:
        # open planar chart: the drawing window is the measured extent
        pass

    declared = meta.get("s_range_mm")
    if declared is not None:
        s_min, s_max = float(declared[0]), float(declared[1])
        source = "declared:chart.meta.s_range_mm"
    else:
        s_min, s_max = _measure_s_range(mother, tag, chart, None)
        source = "measured_from_mesh"
    if not (s_max > s_min):
        raise SynLabError(ErrorCode.MOTHER_INVALID,
                          f"chart {chart.name!r} has empty profile range [{s_min}, {s_max}]",
                          stage="patterns.charts.resolve_frame")

    metric, area = _circumferential_metric(mother, tag, chart, x_period)
    if area <= 0.0:
        area = float(chart.area_mm2)
    return ChartFrame(
        chart=chart, tag=tag, tag_name=mother.tag_name(tag), name=chart.name,
        kind=str(chart.kind), x_period_mm=x_period, u_periodic=u_periodic,
        s_periodic=bool(meta.get("s_periodic", False)),
        s_min_mm=s_min, s_max_mm=s_max, s_range_source=source,
        area_mm2=float(area), to_xyz=meta.get("uv_to_xyz"),
        region_mask=chart.region_mask, circumferential_metric=metric, meta=meta,
    )


def to_chart_mm(frame: ChartFrame, points_mm: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """World millimetres -> chart millimetres ``(x_mm, s_mm)`` using the frozen contract."""
    pts = np.asarray(points_mm, dtype=np.float64)
    if pts.size == 0:
        empty = np.zeros(0, dtype=np.float64)
        return empty, empty
    if pts.ndim != 2 or pts.shape[1] != 3:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"points_mm must be (N,3), got {pts.shape}",
                          stage="patterns.charts.to_chart_mm")
    uv = frame.chart.uv(pts)
    if frame.u_periodic and frame.x_period_mm:
        x_mm = np.mod(uv[:, 0], 1.0) * frame.x_period_mm
    else:
        x_mm = uv[:, 0]
    return np.ascontiguousarray(x_mm, dtype=np.float64), np.ascontiguousarray(uv[:, 1], dtype=np.float64)


def wrap_delta(values: np.ndarray, centre: float, period: float) -> np.ndarray:
    """Shortest signed distance to ``centre`` on a circle of length ``period``."""
    return np.mod(values - centre + 0.5 * period, period) - 0.5 * period


def region_weight(frame: ChartFrame, points_mm: np.ndarray, x_mm: np.ndarray, s_mm: np.ndarray,
                  bounds: dict[str, Any]) -> np.ndarray:
    """Continuous legal-drawing weight in ``[0,1]`` (1 inside, ramped at the boundary).

    ``bounds`` carries the frozen legal region: ``s_min_mm``, ``s_max_mm``, ``feather_mm``.
    The chart's own ``region_mask`` (world points) is combined multiplicatively.
    """
    from .fields import smoothstep

    n = x_mm.shape[0]
    w = np.ones(n, dtype=np.float64)
    feather = float(bounds.get("feather_mm", 0.0) or 0.0)
    lo = float(bounds["s_min_mm"])
    hi = float(bounds["s_max_mm"])
    if frame.s_periodic:
        span = frame.s_span_mm
        d = np.abs(wrap_delta(s_mm, 0.5 * (lo + hi), span))
        half = 0.5 * (hi - lo)
        if feather > 0:
            w *= 1.0 - smoothstep(half - feather, half, d)
        else:
            w *= (d <= half).astype(np.float64)
    else:
        if feather > 0:
            w *= smoothstep(lo - feather, lo, s_mm) * (1.0 - smoothstep(hi, hi + feather, s_mm))
        else:
            w *= ((s_mm >= lo) & (s_mm <= hi)).astype(np.float64)
    if frame.region_mask is not None:
        pts = np.asarray(points_mm, dtype=np.float64)
        mask = np.asarray(frame.region_mask(pts))
        if mask.shape[0] != n:
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              f"chart {frame.name!r} region_mask returned {mask.shape} for {n} points",
                              stage="patterns.charts.region_weight")
        w *= mask.astype(np.float64)
    return np.clip(w, 0.0, 1.0)


# ---------------------------------------------------------------------------------------
# surface sampling helpers
# ---------------------------------------------------------------------------------------
def surface_samples(mother: MotherGeometry, count: int, rng: np.random.Generator, *,
                    tag: int | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Area-weighted mother surface samples via ``trimesh.Trimesh.sample`` (library rule).

    Returns ``(points_mm, face_index)``.  The sampler consumes the supplied generator, so
    callers keep a reproducible sub-stream.
    """
    mesh = mother.mesh
    if count <= 0:
        return np.zeros((0, 3), dtype=np.float64), np.zeros(0, dtype=np.int64)
    points, face_index = mesh.sample(count, return_index=True, seed=rng)
    points = np.asarray(points, dtype=np.float64)
    face_index = np.asarray(face_index, dtype=np.int64)
    if tag is not None:
        keep = np.asarray(mother.face_surface_tag)[face_index] == int(tag)
        points, face_index = points[keep], face_index[keep]
    return points, face_index


def vertex_surface_tags(mother: MotherGeometry) -> np.ndarray:
    """Majority surface tag per vertex (used when displacing the full mother body)."""
    faces = np.asarray(mother.mesh.faces, dtype=np.int64)
    tags = np.asarray(mother.face_surface_tag, dtype=np.int64)
    names = sorted(int(k) for k in (mother.surface_tag_names or {}))
    index = {name: i for i, name in enumerate(names)}
    counts = np.zeros((len(mother.mesh.vertices), len(names)), dtype=np.int32)
    for corner in range(faces.shape[1]):
        np.add.at(counts, (faces[:, corner], np.array([index[int(t)] for t in tags])), 1)
    return np.asarray([names[i] for i in np.argmax(counts, axis=1)], dtype=np.int64)


def face_centre_chart(frame: ChartFrame, mother: MotherGeometry) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Chart millimetres, world millimetres and area of every face carrying the chart tag."""
    faces = np.asarray(mother.mesh.faces, dtype=np.int64)
    tags = np.asarray(mother.face_surface_tag)
    mask = tags == int(frame.tag)
    if not np.any(mask):
        return (np.zeros(0), np.zeros(0), np.zeros(0))
    tri = np.asarray(mother.mesh.triangles[mask], dtype=np.float64)
    centres = tri.mean(axis=1)
    x_mm, s_mm = to_chart_mm(frame, centres)
    areas = np.asarray(mother.mesh.area_faces, dtype=np.float64)[mask]
    return x_mm, s_mm, areas


def region_area_mm2(frame: ChartFrame, mother: MotherGeometry, bounds: dict[str, Any]) -> float:
    """Measured area of the frozen legal drawing region on the mother surface."""
    x_mm, s_mm, areas = face_centre_chart(frame, mother)
    if areas.size == 0:
        return 0.0
    lo, hi = float(bounds["s_min_mm"]), float(bounds["s_max_mm"])
    keep = (s_mm >= lo) & (s_mm <= hi)
    return float(areas[keep].sum())


def local_mm_per_u(frame: ChartFrame) -> tuple[float, float]:
    """True surface arc length per unit ``u`` at the smallest / largest radius."""
    metric = frame.circumferential_metric
    if "circumference_min_mm" in metric:
        return float(metric["circumference_min_mm"]), float(metric["circumference_max_mm"])
    if frame.x_period_mm:
        return float(frame.x_period_mm), float(frame.x_period_mm)
    return 0.0, 0.0
