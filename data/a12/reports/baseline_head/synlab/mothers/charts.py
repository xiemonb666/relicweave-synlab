"""Surface charts for mothers (plan 7.1 step 7 / 9.2).

A chart maps authoritative mother millimetres to drawing coordinates ``(u, s)``:

* ``revolve``  - ``u = atan2(y, x) / 2 pi mod 1`` (periodic) and ``s`` = arclength along the
  labelled profile poly-line, measured in millimetres from the base centre.  The reference
  circumference ``x_period_mm = 2 pi r(s)`` is recorded so a periodic pattern can be scaled
  to real millimetres;
* ``planar``   - an orthonormal projection for flat or swept faces (bricks, tiles, panels).

Charts are frozen with the mother.  Their ``to_uv`` closures cannot be pickled, so each
chart also carries a JSON *spec* plus a numeric array payload; ``chart_payload`` /
``charts_from_payload`` round-trip them through the asset store.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

import numpy as np

from ..errors import ErrorCode, SynLabError
from ..schemas.runtime import Chart
from .geometry import LabelledPolyline
from .tagging import TAG_NAMES, tag_index

CHART_SPEC_KEY = "spec"
CHART_ARRAY_KEY = "arrays"


def _as_polyline(profile_rzs: np.ndarray) -> LabelledPolyline:
    arr = np.asarray(profile_rzs, dtype=np.float64)
    if arr.ndim != 2 or arr.shape[1] != 3:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "revolve chart needs (P,3) [r,z,s]",
                          stage="mothers.charts")
    seg_len = np.linalg.norm(np.diff(arr[:, :2], axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg_len)])
    labels = np.array(["path"] * (len(arr) - 1), dtype=object)
    return LabelledPolyline(arr[:, :2], labels, s)


def revolve_chart(name: str, surface_tags: Sequence[int], *, profile_rzs: np.ndarray,
                  r_ref_mm: float, area_mm2: float, tol_mm: float = 0.6,
                  legal_tags: Sequence[str] | None = None,
                  stage: str = "mothers.charts.revolve") -> Chart:
    """Periodic surface-of-revolution chart with a metric arclength coordinate."""
    profile = np.asarray(profile_rzs, dtype=np.float64)
    poly = _as_polyline(profile)
    s_total = float(poly.length_mm)
    if s_total <= 0:
        raise SynLabError(ErrorCode.MOTHER_INVALID, "revolve chart profile has zero length",
                          stage=stage)
    r_ref = float(r_ref_mm)
    if not np.isfinite(r_ref) or r_ref <= 0:
        raise SynLabError(ErrorCode.MOTHER_INVALID, "revolve chart needs a positive r_ref_mm",
                          stage=stage, measurements={"r_ref_mm": r_ref})

    def to_uv(points: np.ndarray) -> np.ndarray:
        pts = np.atleast_2d(np.asarray(points, dtype=np.float64))
        u = np.mod(np.arctan2(pts[:, 1], pts[:, 0]) / (2.0 * np.pi), 1.0)
        rz = np.column_stack([np.hypot(pts[:, 0], pts[:, 1]), pts[:, 2]])
        s, _, _ = poly.project(rz)
        return np.column_stack([u, s])

    def region_mask(points: np.ndarray) -> np.ndarray:
        pts = np.atleast_2d(np.asarray(points, dtype=np.float64))
        rz = np.column_stack([np.hypot(pts[:, 0], pts[:, 1]), pts[:, 2]])
        _, dist, _ = poly.project(rz)
        return np.asarray(dist <= float(tol_mm), dtype=bool)

    spec = {
        "name": name,
        "kind": "revolve",
        "surface_tags": [int(t) for t in surface_tags],
        "u_periodic": True,
        "x_period_mm": float(2.0 * np.pi * r_ref),
        "area_mm2": float(area_mm2),
        "s_total_mm": s_total,
        "tol_mm": float(tol_mm),
        "r_ref_mm": r_ref,
        "legal_tags": list(legal_tags or [TAG_NAMES[int(t)] for t in surface_tags]),
        "array_key": f"chart_{name}",
        "meta": {"u_definition": "atan2(y, x) / 2 pi mod 1",
                 "s_definition": "arclength mm along the labelled profile from the base centre"},
    }
    return Chart(
        name=name,
        surface_tags=tuple(int(t) for t in surface_tags),
        kind="revolve",
        u_periodic=True,
        x_period_mm=float(2.0 * np.pi * r_ref),
        area_mm2=float(area_mm2),
        to_uv=to_uv,
        region_mask=region_mask,
        meta={CHART_SPEC_KEY: spec, CHART_ARRAY_KEY: {"profile_rzs": profile}},
    )


def planar_chart(name: str, surface_tags: Sequence[int], *, origin: Sequence[float],
                 e_u: Sequence[float], e_v: Sequence[float], area_mm2: float,
                 extent_u_mm: tuple[float, float] | None = None,
                 extent_v_mm: tuple[float, float] | None = None,
                 meta: dict[str, Any] | None = None,
                 stage: str = "mothers.charts.planar") -> Chart:
    """Orthonormal planar chart; ``to_uv`` returns real millimetres."""
    o = np.asarray(origin, dtype=np.float64).reshape(3)
    eu = np.asarray(e_u, dtype=np.float64).reshape(3)
    ev = np.asarray(e_v, dtype=np.float64).reshape(3)
    if abs(float(np.dot(eu, ev))) > 1e-6:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "planar chart axes must be orthogonal",
                          stage=stage, measurements={"dot": float(np.dot(eu, ev))})
    for vec, label in ((eu, "e_u"), (ev, "e_v")):
        norm = float(np.linalg.norm(vec))
        if abs(norm - 1.0) > 1e-6:
            raise SynLabError(ErrorCode.SCHEMA_INVALID, f"planar chart {label} must be unit",
                              stage=stage, measurements={"norm": norm})

    def to_uv(points: np.ndarray) -> np.ndarray:
        pts = np.atleast_2d(np.asarray(points, dtype=np.float64)) - o[None, :]
        return np.column_stack([pts @ eu, pts @ ev])

    def region_mask(points: np.ndarray) -> np.ndarray:
        uv = to_uv(points)
        ok = np.ones(uv.shape[0], dtype=bool)
        if extent_u_mm is not None:
            ok &= (uv[:, 0] >= extent_u_mm[0]) & (uv[:, 0] <= extent_u_mm[1])
        if extent_v_mm is not None:
            ok &= (uv[:, 1] >= extent_v_mm[0]) & (uv[:, 1] <= extent_v_mm[1])
        return ok

    spec = {
        "name": name,
        "kind": "planar",
        "surface_tags": [int(t) for t in surface_tags],
        "u_periodic": False,
        "x_period_mm": None,
        "area_mm2": float(area_mm2),
        "origin": [float(v) for v in o],
        "e_u": [float(v) for v in eu],
        "e_v": [float(v) for v in ev],
        "extent_u_mm": list(extent_u_mm) if extent_u_mm else None,
        "extent_v_mm": list(extent_v_mm) if extent_v_mm else None,
        "array_key": None,
        "legal_tags": [TAG_NAMES[int(t)] for t in surface_tags],
        "meta": dict(meta or {}),
    }
    return Chart(
        name=name,
        surface_tags=tuple(int(t) for t in surface_tags),
        kind="planar",
        u_periodic=False,
        x_period_mm=None,
        area_mm2=float(area_mm2),
        to_uv=to_uv,
        region_mask=region_mask,
        meta={CHART_SPEC_KEY: spec, CHART_ARRAY_KEY: {}},
    )


def prism_chart(name: str, surface_tags: Sequence[int], *, ring_xy: np.ndarray,
                z_min_mm: float, z_max_mm: float, area_mm2: float, tol_mm: float = 0.6,
                meta: dict[str, Any] | None = None,
                stage: str = "mothers.charts.prism") -> Chart:
    """Developed chart of an extruded wall: ``u`` = perimeter fraction, ``s`` = height.

    This is the extrusion analogue of the revolve chart: ``u`` is periodic in ``[0, 1)``
    with the real perimeter as ``x_period_mm``, ``s`` is the height in millimetres.
    """
    ring = np.asarray(ring_xy, dtype=np.float64)
    if ring.ndim != 2 or ring.shape[1] != 2 or len(ring) < 3:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "prism chart needs a (K>=3, 2) ring",
                          stage=stage)
    closed_ring = np.vstack([ring, ring[:1]])
    seg = np.linalg.norm(np.diff(closed_ring, axis=0), axis=1)
    perimeter = float(seg.sum())
    if perimeter <= 0:
        raise SynLabError(ErrorCode.MOTHER_INVALID, "prism chart ring has zero perimeter",
                          stage=stage)
    poly = LabelledPolyline(closed_ring, np.array(["wall"] * (len(closed_ring) - 1), dtype=object),
                            np.concatenate([[0.0], np.cumsum(seg)]))

    def to_uv(points: np.ndarray) -> np.ndarray:
        pts = np.atleast_2d(np.asarray(points, dtype=np.float64))
        s_ring, _, _ = poly.project(pts[:, :2])
        u = np.mod(s_ring / perimeter, 1.0)
        s = np.clip(pts[:, 2], float(z_min_mm), float(z_max_mm)) - float(z_min_mm)
        return np.column_stack([u, s])

    def region_mask(points: np.ndarray) -> np.ndarray:
        pts = np.atleast_2d(np.asarray(points, dtype=np.float64))
        _, dist, _ = poly.project(pts[:, :2])
        inside_z = (pts[:, 2] >= float(z_min_mm) - 0.5) & (pts[:, 2] <= float(z_max_mm) + 0.5)
        return np.asarray((dist <= float(tol_mm)) & inside_z, dtype=bool)

    spec = {
        "name": name,
        "kind": "prism",
        "surface_tags": [int(t) for t in surface_tags],
        "u_periodic": True,
        "x_period_mm": perimeter,
        "area_mm2": float(area_mm2),
        "s_total_mm": float(z_max_mm - z_min_mm),
        "tol_mm": float(tol_mm),
        "z_min_mm": float(z_min_mm),
        "z_max_mm": float(z_max_mm),
        "legal_tags": [TAG_NAMES[int(t)] for t in surface_tags],
        "array_key": f"chart_{name}",
        "meta": {"u_definition": "perimeter fraction of the extrusion ring",
                 "s_definition": "height above the extrusion base in mm", **dict(meta or {})},
    }
    return Chart(
        name=name,
        surface_tags=tuple(int(t) for t in surface_tags),
        kind="sweep",
        u_periodic=True,
        x_period_mm=perimeter,
        area_mm2=float(area_mm2),
        to_uv=to_uv,
        region_mask=region_mask,
        meta={CHART_SPEC_KEY: spec, CHART_ARRAY_KEY: {"ring_xy": ring}},
    )


def sweep_chart(name: str, surface_tags: Sequence[int], *, path_xyz: np.ndarray,
                area_mm2: float, tol_mm: float = 1.0, meta: dict[str, Any] | None = None,
                stage: str = "mothers.charts.sweep") -> Chart:
    """Developed chart for a swept attachment: ``u`` = arclength along the path."""
    path = np.asarray(path_xyz, dtype=np.float64)
    if path.ndim != 2 or path.shape[1] != 3 or len(path) < 2:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "sweep chart needs a (K>=2, 3) path",
                          stage=stage)
    seg = np.linalg.norm(np.diff(path, axis=0), axis=1)
    length = float(seg.sum())
    if length <= 0:
        raise SynLabError(ErrorCode.MOTHER_INVALID, "sweep chart path has zero length",
                          stage=stage)
    poly2 = LabelledPolyline(path[:, :2], np.array(["sweep"] * (len(path) - 1), dtype=object),
                             np.concatenate([[0.0], np.cumsum(seg)]))

    def to_uv(points: np.ndarray) -> np.ndarray:
        pts = np.atleast_2d(np.asarray(points, dtype=np.float64))
        s_path, _, _ = poly2.project(pts[:, :2])
        return np.column_stack([s_path, pts[:, 2]])

    def region_mask(points: np.ndarray) -> np.ndarray:
        pts = np.atleast_2d(np.asarray(points, dtype=np.float64))
        s_path, _, _ = poly2.project(pts[:, :2])
        dist = np.linalg.norm(pts - path[np.clip((s_path / length * (len(path) - 1)).astype(int),
                                                 0, len(path) - 1)], axis=1)
        return np.asarray(dist <= float(tol_mm), dtype=bool)

    spec = {
        "name": name,
        "kind": "sweep",
        "surface_tags": [int(t) for t in surface_tags],
        "u_periodic": False,
        "x_period_mm": None,
        "area_mm2": float(area_mm2),
        "s_total_mm": length,
        "tol_mm": float(tol_mm),
        "legal_tags": [TAG_NAMES[int(t)] for t in surface_tags],
        "array_key": f"chart_{name}",
        "meta": {"u_definition": "arclength mm along the sweep path (projected)",
                 "s_definition": "z in mm", **dict(meta or {})},
    }
    return Chart(
        name=name,
        surface_tags=tuple(int(t) for t in surface_tags),
        kind="sweep",
        u_periodic=False,
        x_period_mm=None,
        area_mm2=float(area_mm2),
        to_uv=to_uv,
        region_mask=region_mask,
        meta={CHART_SPEC_KEY: spec, CHART_ARRAY_KEY: {"path_xyz": path}},
    )


def chart_payload(charts: Iterable[Chart]) -> tuple[list[dict[str, Any]], dict[str, np.ndarray]]:
    """Split charts into a JSON spec list plus numeric arrays for the asset store."""
    specs: list[dict[str, Any]] = []
    arrays: dict[str, np.ndarray] = {}
    for chart in charts:
        meta = dict(chart.meta or {})
        spec = dict(meta.get(CHART_SPEC_KEY) or {})
        if not spec:
            raise SynLabError(ErrorCode.MOTHER_INVALID,
                              f"chart {chart.name!r} has no serialisable spec",
                              stage="mothers.charts.payload")
        payload = dict(meta.get(CHART_ARRAY_KEY) or {})
        key = spec.get("array_key")
        if key and payload:
            if len(payload) != 1:
                raise SynLabError(ErrorCode.MOTHER_INVALID,
                                  f"chart {chart.name!r} has {len(payload)} arrays, expected 1",
                                  stage="mothers.charts.payload")
            arrays[str(key)] = np.ascontiguousarray(next(iter(payload.values())))
        specs.append(spec)
    return specs, arrays


def charts_from_payload(specs: Sequence[dict[str, Any]],
                        arrays: dict[str, np.ndarray] | None = None) -> list[Chart]:
    """Rebuild live charts (with their ``to_uv`` closures) from stored specs."""
    arrays = dict(arrays or {})
    out: list[Chart] = []
    for spec in specs:
        kind = str(spec.get("kind"))
        if kind == "revolve":
            key = spec.get("array_key")
            if key not in arrays:
                raise SynLabError(ErrorCode.MOTHER_INVALID,
                                  f"stored chart {spec.get('name')!r} misses array {key!r}",
                                  stage="mothers.charts.payload")
            profile = np.asarray(arrays[key], dtype=np.float64)
            chart = revolve_chart(str(spec["name"]), spec["surface_tags"],
                                  profile_rzs=profile,
                                  r_ref_mm=float(spec["r_ref_mm"]),
                                  area_mm2=float(spec["area_mm2"]),
                                  tol_mm=float(spec["tol_mm"]),
                                  legal_tags=spec.get("legal_tags"))
        elif kind == "planar":
            chart = planar_chart(str(spec["name"]), spec["surface_tags"],
                                 origin=spec["origin"], e_u=spec["e_u"], e_v=spec["e_v"],
                                 area_mm2=float(spec["area_mm2"]),
                                 extent_u_mm=tuple(spec["extent_u_mm"]) if spec.get("extent_u_mm") else None,
                                 extent_v_mm=tuple(spec["extent_v_mm"]) if spec.get("extent_v_mm") else None,
                                 meta=spec.get("meta"))
        elif kind == "prism":
            key = spec.get("array_key")
            if key not in arrays:
                raise SynLabError(ErrorCode.MOTHER_INVALID,
                                  f"stored chart {spec.get('name')!r} misses array {key!r}",
                                  stage="mothers.charts.payload")
            chart = prism_chart(str(spec["name"]), spec["surface_tags"],
                                ring_xy=np.asarray(arrays[key], dtype=np.float64),
                                z_min_mm=float(spec["z_min_mm"]), z_max_mm=float(spec["z_max_mm"]),
                                area_mm2=float(spec["area_mm2"]), tol_mm=float(spec["tol_mm"]),
                                meta=spec.get("meta"))
        elif kind == "sweep":
            key = spec.get("array_key")
            if key not in arrays:
                raise SynLabError(ErrorCode.MOTHER_INVALID,
                                  f"stored chart {spec.get('name')!r} misses array {key!r}",
                                  stage="mothers.charts.payload")
            chart = sweep_chart(str(spec["name"]), spec["surface_tags"],
                                path_xyz=np.asarray(arrays[key], dtype=np.float64),
                                area_mm2=float(spec["area_mm2"]), tol_mm=float(spec["tol_mm"]),
                                meta=spec.get("meta"))
        else:
            raise SynLabError(ErrorCode.MOTHER_INVALID, f"unknown stored chart kind {kind!r}",
                              stage="mothers.charts.payload")
        out.append(chart)
    return out


def charts_for_tag(charts: Sequence[Chart], tag: int) -> Chart | None:
    for chart in charts:
        if int(tag) in chart.surface_tags:
            return chart
    return None


def chart_coverage(charts: Sequence[Chart], tags_present: Sequence[int]) -> dict[str, Any]:
    """Every tag that appears on the mesh must belong to at least one chart."""
    present = sorted({int(t) for t in tags_present})
    covered: list[int] = []
    for tag in present:
        if charts_for_tag(charts, tag) is not None:
            covered.append(tag)
    missing = [t for t in present if t not in covered]
    return {
        "tags_present": [TAG_NAMES.get(t, str(t)) for t in present],
        "tags_covered": [TAG_NAMES.get(t, str(t)) for t in covered],
        "missing_tags": [TAG_NAMES.get(t, str(t)) for t in missing],
        "ok": not missing,
    }


def chart_uv_probe(chart: Chart, points: np.ndarray) -> dict[str, Any]:
    """Validate a chart on real sample points (used by ``audit_mother``)."""
    uv = chart.uv(points)
    ok = np.all(np.isfinite(uv))
    u_in_range = True
    if chart.u_periodic:
        u_in_range = bool(np.all((uv[:, 0] >= 0.0) & (uv[:, 0] < 1.0)))
    mask = chart.region_mask(points) if chart.region_mask is not None else np.ones(len(uv), dtype=bool)
    return {
        "name": chart.name,
        "n_points": int(len(uv)),
        "finite": bool(ok),
        "u_in_range": bool(u_in_range),
        "u_min": float(uv[:, 0].min()) if len(uv) else None,
        "u_max": float(uv[:, 0].max()) if len(uv) else None,
        "s_min": float(uv[:, 1].min()) if len(uv) else None,
        "s_max": float(uv[:, 1].max()) if len(uv) else None,
        "region_true": int(np.count_nonzero(mask)),
        "area_mm2": float(chart.area_mm2),
    }


__all__ = [
    "revolve_chart", "planar_chart", "chart_payload", "charts_from_payload",
    "charts_for_tag", "chart_coverage", "chart_uv_probe", "tag_index",
]
