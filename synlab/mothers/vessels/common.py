"""Chart factories shared by the vessel builders.

Each construction family gets the chart its geometry actually supports:

* ``revolve_charts``  - periodic ``(u = theta / 2 pi, s = profile arclength mm)`` chart of
  a body of revolution, plus one developed sweep chart per attachment;
* ``prism_charts``    - developed ``(u = perimeter fraction, s = height mm)`` chart of an
  extruded wall plus planar charts for the caps;
* ``arc_band_charts`` - developed chart of a curved shell (arc tile / doubly curved panel).
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

import numpy as np
import trimesh

from ...errors import ErrorCode, SynLabError
from ..geometry import ShellProfile, build_shell_profile
from ..charts import planar_chart, prism_chart, revolve_chart, sweep_chart
from ..tagging import TAG_INDEX

BODY_TAGS = ("outer_wall", "inner_wall", "rim", "foot", "base")


def shell_profile(*, R_mm: float, z_rim_mm: float, base_pts: Sequence[tuple[float, float]],
                  wall_pts: Sequence[tuple[float, float]], t_base_mm: float, t_wall_mm: float,
                  rim_mode: str = "flat", rim_bulge: float = 1.0, taper_top: float = 0.9,
                  belly_thickness: float = 1.05, min_wall_mm: float = 0.8,
                  chord_tol_mm: float | None = None, stage: str = "mothers.vessels.shell") -> ShellProfile:
    """Assemble a thick revolve profile from base and wall control points.

    ``base_pts`` / ``wall_pts`` are **absolute** ``(r_mm, z_mm)`` pairs; the mid-line is
    ``base_pts + wall_pts[1:]`` and must start on the axis.  ``R_mm`` is the reference
    radius the vessel is scaled to (used for the pole-blend length and the degeneracy
    check).  The thickness field is a PCHIP through ``(s_normalised, t_mm)``: thick base,
    slightly thicker belly, tapered rim.

    Offsetting a mid-line that starts *on the axis* by half the base thickness would push
    the inner curve through the axis, so the *material* thickness field is blended to zero
    over the first few millimetres: the plan's step-3 guard ("轴附近底部采用专门封底拓扑，
    避免重复轴顶点和退化三角形") is exactly that pole.  The requested ``t_base_mm`` stays a
    real floor thickness as soon as the mid-line leaves the axis, which the audit then
    re-measures on the final triangles.
    """
    R_mm = float(R_mm)
    base = [(float(rr), float(z)) for rr, z in base_pts]
    wall = [(float(rr), float(z)) for rr, z in wall_pts]
    ctrl = np.asarray(base + wall[1:], dtype=np.float64)
    if ctrl[0, 0] > 1e-9:
        ctrl = np.vstack([[0.0, ctrl[0, 1]], ctrl])
    ctrl = advancing_control_points(ctrl, stage=stage)
    if np.max(ctrl[:, 0]) < 0.2 * R_mm:
        raise SynLabError(ErrorCode.MOTHER_INVALID, "vessel radius is degenerate",
                          stage=stage, measurements={"r_max": float(np.max(ctrl[:, 0]))})
    # The plan's acceptance is a chord error (step 5), not a fixed sample count: a fixed
    # 0.06 mm on a 150 mm radius keeps a needlessly dense mesh, so the default scales with the
    # profile radius.  The realised chord error is still measured and reported.
    tolerance = float(chord_tol_mm) if chord_tol_mm is not None else max(
        0.06, 0.004 * max(float(np.max(ctrl[:, 0])), 1.0))
    pole_blend_mm = float(np.clip(0.06 * max(R_mm, 1e-6) + 0.35 * float(t_base_mm), 0.6,
                                  0.08 * max(float(max(z for _, z in base)), 1.0) + 1.0))
    blend_fraction = float(np.clip(_blend_fraction(pole_blend_mm, ctrl, R_mm) + 0.02, 0.03, 0.45))
    wall_floor = float(min(min_wall_mm, t_base_mm, t_wall_mm))
    t_ctrl = _thickness_control_points(blend_fraction, t_base_mm, t_wall_mm, belly_thickness,
                                       taper_top)
    _require_monotone_thickness(t_ctrl, min_wall_mm, stage=stage,
                                requested={"t_base_mm": float(t_base_mm),
                                           "t_wall_mm": float(t_wall_mm)})
    profile = build_shell_profile(ctrl, t_ctrl, chord_tol_mm=tolerance, rim_mode=rim_mode,
                                 rim_bulge=rim_bulge, min_wall_mm=wall_floor * 0.9, stage=stage)
    profile.metrics["z_rim_target_mm"] = float(z_rim_mm)
    # Recording only (it changes no geometry): the parameter/geometry consistency column, so a
    # reviewer can query "does this asset's body reach the rim its own parameters declare"
    # without re-deriving it.  A value near zero means the two agree; a large positive value is
    # the A2 truncation signature measured in docs/a12/mother_geometry_audit.md.
    profile.metrics["z_rim_shortfall_mm"] = float(z_rim_mm) - float(profile.z_rim)
    profile.metrics["pole_blend_mm"] = float(pole_blend_mm)
    profile.metrics["pole_blend_fraction"] = float(blend_fraction)
    profile.metrics["design_min_wall_mm"] = float(min_wall_mm)
    return profile


def _thickness_control_points(blend_fraction: float, t_base_mm: float, t_wall_mm: float,
                              belly_thickness: float, taper_top: float) -> np.ndarray:
    """Thickness field ``(s_normalised, t_mm)``: blended pole, thick base, tapered rim.

    The base-to-wall descent is ramped over several control points.  A single step from the
    base thickness to the wall thickness would make PCHIP overshoot towards zero between the
    control points, which is a real defect: the offset profile would pinch the wall shut near
    the base corner.
    """
    base_t = float(t_base_mm)
    wall_t = float(t_wall_mm)
    blend = float(blend_fraction)
    rows: list[list[float]] = [[0.0, 0.0], [blend, base_t]]
    ring_bottom = min(blend + 0.10, 0.45)
    rows.append([ring_bottom, base_t * 0.97])
    belly = max(0.55, ring_bottom + 0.15)
    rows.append([belly, wall_t * float(belly_thickness)])
    rows.append([min(0.80, belly + 0.20), wall_t])
    # the rim taper is a *feature* (口沿收薄), but it may never take the wall below the
    # vessel's own gate: the realised minimum is measured on the resulting triangles either way
    rows.append([1.0, max(wall_t * float(taper_top), 0.92 * wall_t)])
    return _dedupe_sorted(np.asarray(rows, dtype=np.float64))


def _require_monotone_thickness(t_ctrl: np.ndarray, min_wall_mm: float, *, stage: str,
                                requested: dict[str, Any]) -> None:
    """Reject a request whose *wall* thickness (away from the pole) is below the gate."""
    if min_wall_mm <= 0:
        return
    from ..geometry import thickness_field

    probe = np.linspace(float(t_ctrl[1, 0]), 1.0, 128)
    t = thickness_field(probe, t_ctrl)
    realised = float(np.min(t))
    if realised < float(min_wall_mm) - 1e-9:
        raise SynLabError(
            ErrorCode.MOTHER_INVALID,
            f"requested wall thickness {realised:.3f} mm is below the {min_wall_mm:.3f} mm gate",
            stage=stage,
            measurements={**requested, "min_wall_mm": float(min_wall_mm),
                          "realised_min_mm": realised,
                          "note": "thin walls are rejected here with MOTHER_INVALID, they are "
                                  "never silently thickened"},
        )


def _blend_fraction(pole_blend_mm: float, ctrl: np.ndarray, R_mm: float) -> float:
    """Fraction of the mid-line arclength over which the pole blend completes."""
    seg = np.linalg.norm(np.diff(ctrl, axis=0), axis=1)
    total = float(seg.sum())
    if total <= 0:
        return 0.03
    axis_run = float(np.sum(seg[np.maximum(ctrl[:-1, 0], ctrl[1:, 0]) < 0.06 * max(R_mm, 1e-6)]))
    return float(np.clip((axis_run + float(pole_blend_mm)) / total, 0.02, 0.45))


def _dedupe_sorted(t_ctrl: np.ndarray) -> np.ndarray:
    """Drop thickness control points that collide after the pole blend was inserted."""
    out = [t_ctrl[0]]
    for row in t_ctrl[1:]:
        if row[0] - out[-1][0] < 1e-3:
            continue
        out.append(row)
    return np.asarray(out, dtype=np.float64)


def advancing_control_points(ctrl: np.ndarray, *, min_ratio: float = 0.05,
                             stage: str = "mothers.vessels.shell") -> np.ndarray:
    """Keep the mid-line advancing in ``z``: drop points that repeat or fall back.

    A shoulder or a neck is described by radii that shrink towards the mouth, which is a
    perfectly ordinary function graph: :func:`~synlab.mothers.geometry.build_shell_profile`
    builds ``r(t)`` and ``z(t)`` against the **arclength parameter** ``t``, which strictly
    increases, so a radius that rises and then falls can never fold the wall onto itself.
    What genuinely degenerates PCHIP is a *parameter* that does not advance - a duplicated or
    backwards ``z``.  Only those points are dropped here (the kept/dropped counts are reported
    in the raised error's measurements when nothing usable is left).

    This function was previously named ``monotone_radius_control_points`` and enforced a
    non-decreasing **radius**, which silently deleted every shoulder/neck segment of a necked
    vessel (defect A2 in ``docs/a12/mother_geometry_audit.md``).  The real fold guards are the
    *measured* ones inside ``build_shell_profile``: ``offset_clearance`` (inscribed radius at a
    vertex), ``curvature_margin`` (local curvature radius vs half thickness) and
    ``_self_intersects``; they still raise ``MOTHER_INVALID`` with their measurements.
    """
    pts = np.asarray(ctrl, dtype=np.float64)
    kept: list[np.ndarray] = [pts[0]]
    for row in pts[1:]:
        if row[1] <= kept[-1][1] + 1e-9:      # z must strictly advance
            continue
        kept.append(row)
    out = np.asarray(kept, dtype=np.float64)
    if len(out) < 3:
        raise SynLabError(ErrorCode.MOTHER_INVALID,
                          "mid-line control points collapse after enforcing rising z",
                          stage=stage, measurements={"requested": int(len(pts)),
                                                     "kept": int(len(out))})
    if out[0, 0] > 1e-9:
        out = np.vstack([[0.0, out[0, 1]], out])
    if float(np.max(out[:, 0])) < float(min_ratio) * float(np.max(pts[:, 0])):
        raise SynLabError(ErrorCode.MOTHER_INVALID, "vessel radius is degenerate after cleanup",
                          stage=stage)
    return out


def rim_wave_profile(*, z_rim_mm: float, wave_mm: float) -> dict[str, Any]:
    """Rim undulation parameters handed to :class:`~synlab.mothers.warp.WarpSpec`."""
    return {"rim_wave_mm": float(wave_mm), "z_rim_mm": float(z_rim_mm)}


def wall_points(*, r_start_mm: float, R_mm: float, z_start: float, z_rim_mm: float,
                count: int = 6, exponent: float = 1.0, flare_mm: float = 0.0,
                flare_from: float = 0.75, neck_r_mm: float | None = None,
                neck_from: float = 0.75) -> list[tuple[float, float]]:
    """Wall control points as absolute ``(r_mm, z_mm)`` following a shape exponent.

    ``exponent > 1`` gives a straight conical wall, ``exponent < 1`` a rounded belly.
    ``flare_mm`` widens the last part of the profile (口沿) and may push the radius past
    ``R_mm``; ``neck_r_mm`` pulls the top in towards a neck (颈).

    The returned points are the sampled mid-line, unchanged and in rising ``z``: the radius is
    free to widen towards ``R_mm`` (and to overshoot it when ``flare_mm`` is requested), and to
    narrow again towards a neck.  An earlier revision clamped every rising radius to the
    previous one (``if out and rr > out[-1][0]: rr = out[-1][0]``), which flattened **every**
    widening wall to the radius of its first sample - defect A1 in
    ``docs/a12/mother_geometry_audit.md``.  Radii are still floored at zero; the anti-fold
    guards live in :func:`~synlab.mothers.geometry.build_shell_profile` and are measured there.
    """
    n = int(max(count, 3))
    r_start_mm = float(r_start_mm)
    R_mm = float(R_mm)
    neck_r_mm = float(neck_r_mm) if neck_r_mm is not None else None
    top = R_mm if neck_r_mm is None else neck_r_mm
    pts: list[tuple[float, float]] = []
    for i in range(n):
        u = (i + 1) / n
        z = z_start + (z_rim_mm - z_start) * u
        rr = r_start_mm + (top - r_start_mm) * (u ** float(exponent))
        if neck_r_mm is not None and u >= float(neck_from):
            w = (u - float(neck_from)) / max(1.0 - float(neck_from), 1e-6)
            rr = rr + (neck_r_mm - rr) * (w ** 0.8)
        if flare_mm and u >= float(flare_from):
            w = (u - float(flare_from)) / max(1.0 - float(flare_from), 1e-6)
            rr = rr + float(flare_mm) * (w ** 1.6)
        pts.append((float(max(rr, 0.0)), float(z)))
    return [(float(rr), float(z)) for rr, z in pts]



def _area_for_tags(mesh: trimesh.Trimesh, tags: np.ndarray, names: Iterable[str]) -> float:
    wanted = [TAG_INDEX[n] for n in names]
    mask = np.isin(np.asarray(tags), wanted)
    return float(np.asarray(mesh.area_faces)[mask].sum())


def revolve_charts(mesh: trimesh.Trimesh, tags: np.ndarray, profile: ShellProfile, *,
                   include_attachment: bool = True,
                   attachment_paths: Sequence[dict[str, Any]] = (),
                   stage: str = "mothers.charts.vessel") -> list[Chart]:
    """Body chart of revolution plus one developed chart per swept attachment."""
    tags = np.asarray(tags)
    body_present = tuple(TAG_INDEX[n] for n in BODY_TAGS
                         if np.any(tags == TAG_INDEX[n]))
    if not body_present:
        raise SynLabError(ErrorCode.MOTHER_INVALID, "no body faces to chart", stage=stage)
    profile_rzs = np.column_stack([profile.polyline.points[:, 0], profile.polyline.points[:, 1],
                                   profile.polyline.s_mm])
    centroids = np.asarray(mesh.triangles_center, dtype=np.float64)
    rz = np.column_stack([np.hypot(centroids[:, 0], centroids[:, 1]), centroids[:, 2]])
    _, dist, _ = profile.polyline.project(rz)
    body_mask = np.isin(tags, body_present)
    deviation = float(np.max(dist[body_mask])) if np.any(body_mask) else 0.0
    tol = max(0.6, 1.35 * deviation)
    charts = [revolve_chart(
        "body", body_present, profile_rzs=profile_rzs, r_ref_mm=float(profile.r_max),
        area_mm2=_area_for_tags(mesh, tags, BODY_TAGS), tol_mm=tol,
        legal_tags=[n for n in BODY_TAGS if np.any(tags == TAG_INDEX[n])],
        stage=stage,
    )]
    charts[0].meta["spec"]["meta"].update({
        "radial_deviation_mm": deviation,
        "x_period_rule": "x_period_mm = 2 pi r_max; exact circumference at s is 2 pi r(s) "
                         "with r(s) taken from the stored profile array (third column = s_mm)",
        "chart_selection": "single periodic chart shared by every shell tag",
    })
    if include_attachment and np.any(tags == TAG_INDEX["attachment"]) and attachment_paths:
        charts.extend(_attachment_charts(mesh, tags, attachment_paths))
    return charts


def _attachment_charts(mesh: trimesh.Trimesh, tags: np.ndarray,
                       paths: Sequence[dict[str, Any]]) -> list[Chart]:
    from ..tagging import TAG_INDEX as TI

    centroids = np.asarray(mesh.triangles_center, dtype=np.float64)
    areas = np.asarray(mesh.area_faces, dtype=np.float64)
    att_idx = np.nonzero(tags == TI["attachment"])[0]
    out: list[Chart] = []
    if att_idx.size == 0:
        return out
    assignments: dict[int, list[int]] = {i: [] for i in range(len(paths))}
    for face in att_idx:
        c = centroids[face]
        best = None
        best_d = np.inf
        for i, entry in enumerate(paths):
            path = np.asarray(entry["path_xyz"], dtype=np.float64)
            d = float(np.min(np.linalg.norm(path - c[None, :], axis=1)))
            if d < best_d:
                best_d = d
                best = i
        assignments[int(best)].append(int(face))
    for i, entry in enumerate(paths):
        faces = assignments.get(i, [])
        if not faces:
            continue
        area = float(areas[faces].sum())
        chart = sweep_chart(str(entry.get("name", f"attachment_{i}")), (TI["attachment"],),
                            path_xyz=np.asarray(entry["path_xyz"], dtype=np.float64),
                            area_mm2=area, tol_mm=float(entry.get("tol_mm", 4.0)),
                            meta={"component_id": int(entry.get("component_id", i)),
                                  "definition": "u = arclength along the swept attachment path"})
        out.append(chart)
    return out


def prism_charts(mesh: trimesh.Trimesh, tags: np.ndarray, polygon, *,
                 z_min_mm: float, z_max_mm: float, cap_tag_names: Sequence[str] = ("rim", "base"),
                 stage: str = "mothers.charts.prism") -> list[Chart]:
    """Developed wall chart + planar cap charts of an extrusion."""
    tags = np.asarray(tags)
    exterior = np.asarray(polygon.exterior.coords, dtype=np.float64)[:-1]
    charts: list[Chart] = []
    wall_tags = tuple(TAG_INDEX[n] for n in ("outer_wall", "inner_wall")
                      if np.any(tags == TAG_INDEX[n]))
    if wall_tags:
        tol = 1.2
        charts.append(prism_chart("wall", wall_tags, ring_xy=exterior,
                                  z_min_mm=float(z_min_mm), z_max_mm=float(z_max_mm),
                                  area_mm2=_area_for_tags(mesh, tags, ("outer_wall", "inner_wall")),
                                  tol_mm=tol, stage=stage))
    for name in cap_tag_names:
        idx = TAG_INDEX[name]
        if not np.any(tags == idx):
            continue
        z_plane = float(z_max_mm) if name == "rim" else float(z_min_mm)
        extent = float(max(polygon.bounds[2] - polygon.bounds[0],
                           polygon.bounds[3] - polygon.bounds[1]))
        charts.append(planar_chart(
            f"{name}_plane", (idx,), origin=(0.0, 0.0, z_plane), e_u=(1.0, 0.0, 0.0),
            e_v=(0.0, 1.0, 0.0), area_mm2=_area_for_tags(mesh, tags, (name,)),
            extent_u_mm=(-extent, extent), extent_v_mm=(-extent, extent),
            meta={"definition": "orthographic projection of the cap plane", "z_plane_mm": z_plane},
        ))
    if not charts:
        raise SynLabError(ErrorCode.MOTHER_INVALID, "extrusion produced no chartable tags",
                          stage=stage)
    return charts


def arc_band_charts(mesh: trimesh.Trimesh, tags: np.ndarray, *, center_axis: np.ndarray,
                    r_outer_mm: float, r_inner_mm: float, band_length_mm: float,
                    stage: str = "mothers.charts.arc") -> list[Chart]:
    """Developed chart of a curved shell: ``u`` = angle around the ruling axis."""
    tags = np.asarray(tags)
    centre = np.asarray(center_axis, dtype=np.float64).reshape(3)
    present = tuple(TAG_INDEX[n] for n in BODY_TAGS if np.any(tags == TAG_INDEX[n]))
    if not present:
        raise SynLabError(ErrorCode.MOTHER_INVALID, "arc band has no chartable tags",
                          stage=stage)
    r_mid = 0.5 * (float(r_outer_mm) + float(r_inner_mm))

    def to_uv(points: np.ndarray) -> np.ndarray:
        pts = np.atleast_2d(np.asarray(points, dtype=np.float64))
        d = pts - centre[None, :]
        ang = np.mod(np.arctan2(d[:, 1], d[:, 0]) / (2.0 * np.pi), 1.0)
        s = pts[:, 2]
        return np.column_stack([ang, s])

    def region_mask(points: np.ndarray) -> np.ndarray:
        pts = np.atleast_2d(np.asarray(points, dtype=np.float64))
        rad = np.linalg.norm(pts - centre[None, :], axis=1)
        return np.asarray((rad >= float(r_inner_mm) - 1.5) & (rad <= float(r_outer_mm) + 1.5),
                          dtype=bool)

    area = _area_for_tags(mesh, tags, BODY_TAGS)
    from ..charts import CHART_ARRAY_KEY, CHART_SPEC_KEY
    from ...schemas.runtime import Chart

    spec = {
        "name": "band", "kind": "planar",
        "surface_tags": [int(t) for t in present], "u_periodic": True,
        "x_period_mm": float(2.0 * np.pi * r_mid), "area_mm2": area,
        "origin": [float(v) for v in centre], "e_u": [1.0, 0.0, 0.0], "e_v": [0.0, 1.0, 0.0],
        "extent_u_mm": None, "extent_v_mm": None, "array_key": None,
        "legal_tags": [n for n in BODY_TAGS if np.any(tags == TAG_INDEX[n])],
        "meta": {"definition": "u = azimuth around the ruling axis (periodic), s = z in mm",
                 "r_mid_mm": r_mid, "band_length_mm": float(band_length_mm)},
    }
    return [Chart(name="band", surface_tags=present, kind="planar", u_periodic=True,
                  x_period_mm=float(2.0 * np.pi * r_mid), area_mm2=area, to_uv=to_uv,
                  region_mask=region_mask,
                  meta={CHART_SPEC_KEY: spec, CHART_ARRAY_KEY: {}})]
