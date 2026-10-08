"""Analytic revolve-mother fixtures for the pattern module (plan 7.1 / 9.2).

``synlab.mothers.api.create_mother`` is delivered by a different work package and is not
on disk yet.  This module therefore provides a **documented analytic fixture**: a closed
body of revolution whose chart, profile arc length, wall thickness and surface tags are
known in closed form.

It is *not* a re-implementation of the parametric mother generator.  It exists so the
pattern contract (periodic seam, real millimetre scale, geometry presence, source
inheritance) can be built, evaluated, audited and tested without it, and so the A05 pattern
audit has a real body when the mother module is missing.  Every report that uses it records
its source, so a fixture result can never be mistaken for a real vessel:

* :func:`analytic_revolve_mother` - the fixture (closed shell, foot ring, real wall);
* :func:`try_real_mother` - ``synlab.mothers.api.create_mother`` when it is importable and
  returns a mother that carries a periodic chart with a measurable outer-wall region;
* :func:`mother_for_audit` - prefers the real generator, falls back to the fixture, and
  always returns the source string plus the reasons.

The fixture profile is ``r(z) = r_base - taper*t + bulge*sin(pi*t)*(1 - 0.4*t)`` with
``t = z/height``; the chart is the standard revolve chart of ``docs/a12/interfaces.md`` §1
(``u = atan2(y, x)/(2 pi) mod 1``, ``s`` = true profile arc length in millimetres measured
from the base plane) and ``x_period_mm = 2 pi r_ref`` with ``r_ref`` the outer radius at the
middle of the legal drawing region.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import trimesh

from ..errors import ErrorCode, SynLabError
from ..schemas.runtime import Chart, MotherGeometry

#: Frozen integer encoding of ``synlab.schemas.runtime.SurfaceTag`` (interfaces §1).
OUTER_WALL = 0
INNER_WALL = 1
RIM = 2
FOOT = 3
BASE = 4
ATTACHMENT = 5
INTERFACE = 6

TAG_NAMES: dict[int, str] = {
    OUTER_WALL: "outer_wall", INNER_WALL: "inner_wall", RIM: "rim", FOOT: "foot",
    BASE: "base", ATTACHMENT: "attachment", INTERFACE: "interface",
}
TAG_INDEX: dict[str, int] = {name: index for index, name in TAG_NAMES.items()}

#: Labels of the five cross-section segments that follow the outer profile.
_CLOSING_LABELS: tuple[str, ...] = ("rim", "inner_wall", "base", "foot", "base")

_CACHE: dict[str, MotherGeometry] = {}


# ---------------------------------------------------------------------------------------
# analytic profile
# ---------------------------------------------------------------------------------------
@dataclass(frozen=True)
class RevolveProfile:
    """Dense outer profile with its true arc length, its cross-section and an inverse map."""

    z_tab: np.ndarray          # (M,) sample heights, ascending
    r_tab: np.ndarray          # (M,) outer radius
    s_tab: np.ndarray          # (M,) arc length from the base plane
    loop: np.ndarray           # (P,2) closed cross-section polyline (r, z), first == last
    segments: np.ndarray       # (K,4) cross-section segments (r0, z0, r1, z1)
    labels: tuple[str, ...]    # (K,) surface-tag name per segment
    n_outer: int               # first ``n_outer`` segments belong to the outer profile
    height_mm: float
    wall_mm: float
    base_thickness_mm: float
    r_foot_mm: float
    r_ref_mm: float

    @property
    def s_total_mm(self) -> float:
        return float(self.s_tab[-1])

    def radius_at_z(self, z_mm: np.ndarray | float) -> np.ndarray:
        return np.interp(np.asarray(z_mm, dtype=np.float64), self.z_tab, self.r_tab)

    def s_at_z(self, z_mm: np.ndarray | float) -> np.ndarray:
        z = np.clip(np.asarray(z_mm, dtype=np.float64), self.z_tab[0], self.z_tab[-1])
        return np.interp(z, self.z_tab, self.s_tab)

    def z_at_s(self, s_mm: np.ndarray | float) -> np.ndarray:
        s = np.clip(np.asarray(s_mm, dtype=np.float64), self.s_tab[0], self.s_tab[-1])
        return np.interp(s, self.s_tab, self.z_tab)

    def xy_at(self, x_mm: np.ndarray, s_mm: np.ndarray) -> np.ndarray:
        """Exact chart inverse: ``(x_mm, s_mm) -> world mm`` on the outer wall."""
        z = self.z_at_s(s_mm)
        r = self.radius_at_z(z)
        theta = np.asarray(x_mm, dtype=np.float64) / float(self.r_ref_mm)
        return np.stack([r * np.cos(theta), r * np.sin(theta), z], axis=1)

    def as_dict(self) -> dict[str, Any]:
        return {
            "height_mm": float(self.height_mm), "wall_mm": float(self.wall_mm),
            "base_thickness_mm": float(self.base_thickness_mm),
            "r_foot_mm": float(self.r_foot_mm), "r_ref_mm": float(self.r_ref_mm),
            "s_total_mm": self.s_total_mm, "n_samples": int(self.z_tab.size),
            "n_segments": int(self.segments.shape[0]), "n_loop_points": int(self.loop.shape[0]),
            "longest_loop_edge_mm": float(np.hypot(*np.diff(self.loop, axis=0).T).max()),
            "s_definition": "true arc length along the outer profile from the base plane",
        }


def build_profile(*, height_mm: float = 60.0, r_base_mm: float = 18.0, taper_mm: float = 4.0,
                  bulge_mm: float = 6.0, wall_mm: float = 5.0, base_thickness_mm: float = 6.0,
                  n_samples: int = 96, max_segment_mm: float = 1.5) -> RevolveProfile:
    """Build the dense analytic profile tables (arc length by cumulative trapezoid).

    ``max_segment_mm`` bounds every cross-section edge of the revolved body.  A body with
    one 13 mm edge across the base would force ``trimesh.remesh.subdivide_to_size`` to
    explode the face count when a pattern needs real geometric detail, so the fixture is
    built with a bounded edge length from the start.
    """
    if wall_mm <= 0 or height_mm <= 0 or base_thickness_mm <= 0:
        raise SynLabError(ErrorCode.MOTHER_INVALID,
                          "fixture needs positive height, wall and base thickness",
                          stage="patterns.fixtures.build_profile")
    t = np.linspace(0.0, 1.0, int(n_samples))
    z = t * float(height_mm)
    r = (float(r_base_mm) - float(taper_mm) * t
         + float(bulge_mm) * np.sin(np.pi * t) * (1.0 - 0.4 * t))
    if float(r.min()) - float(wall_mm) <= 1.0:
        raise SynLabError(ErrorCode.MOTHER_INVALID,
                          f"fixture wall {wall_mm} mm leaves no inner cavity "
                          f"(min outer radius {float(r.min()):.2f} mm)",
                          stage="patterns.fixtures.build_profile")
    if float(base_thickness_mm) >= float(height_mm) * 0.5:
        raise SynLabError(ErrorCode.MOTHER_INVALID,
                          "fixture base thickness must be below half the height",
                          stage="patterns.fixtures.build_profile")
    seg = np.hypot(np.diff(r), np.diff(z))
    s = np.concatenate([[0.0], np.cumsum(seg)])
    r_in = r - float(wall_mm)
    r_foot = max(1.5, 0.35 * float(r_in[0]))
    r_floor = float(np.interp(base_thickness_mm, z, r_in))

    outer = np.stack([r[:-1], z[:-1], r[1:], z[1:]], axis=1)
    inner = np.stack([r_in[1:], z[1:], r_in[:-1], z[:-1]], axis=1)
    floor_level = float(base_thickness_mm)
    k0 = int(np.clip(np.searchsorted(z, floor_level), 1, z.size - 1))
    closing_pts: list[tuple[float, float]] = []
    closing_segments: list[list[float]] = []
    closing_labels: list[str] = []
    # the rim annulus is drawn by the loop directly; it still needs a labelled segment so
    # that the face tagging can find it
    closing_segments.append([float(r[-1]), float(z[-1]), float(r_in[-1]), float(z[-1])])
    closing_labels.append("rim")
    # cross-section: outer profile up, rim, inner profile down to the cavity floor, cavity
    # floor inward, foot wall down, bottom annulus outward -> simple closed loop, all r > 0
    loop_inner = np.column_stack([r_in[k0:-1], z[k0:-1]])[::-1]
    cursor = (float(r_in[k0]), float(z[k0]))

    def add_chain(end: tuple[float, float], label: str) -> None:
        nonlocal cursor
        start = np.asarray(cursor, dtype=np.float64)
        stop = np.asarray(end, dtype=np.float64)
        steps = max(1, int(np.ceil(float(np.hypot(*(stop - start))) / float(max_segment_mm))))
        for index in range(1, steps + 1):
            point = start + (stop - start) * (index / steps)
            closing_segments.append([float(start[0]), float(start[1]),
                                     float(point[0]), float(point[1])])
            closing_labels.append(label)
            closing_pts.append((float(point[0]), float(point[1])))
            start = point
        cursor = (float(stop[0]), float(stop[1]))

    add_chain((r_floor, floor_level), "base")
    add_chain((r_foot, floor_level), "base")
    add_chain((r_foot, 0.0), "foot")
    add_chain((float(r[0]), 0.0), "base")

    segments = np.vstack([outer, inner, np.asarray(closing_segments, dtype=np.float64)])
    labels = tuple(["outer_wall"] * outer.shape[0] + ["inner_wall"] * inner.shape[0]
                   + closing_labels)
    loop = np.vstack([np.column_stack([r, z]),
                      np.array([[float(r_in[-1]), float(z[-1])]]),
                      loop_inner,
                      np.asarray(closing_pts, dtype=np.float64)])
    r_ref = float(np.interp(0.5 * float(height_mm), z, r))
    return RevolveProfile(z_tab=z, r_tab=r, s_tab=s, loop=loop, segments=segments,
                          labels=labels, n_outer=int(outer.shape[0]),
                          height_mm=float(height_mm), wall_mm=float(wall_mm),
                          base_thickness_mm=float(base_thickness_mm), r_foot_mm=float(r_foot),
                          r_ref_mm=r_ref)


def _point_segment_distance(rz: np.ndarray, segments: np.ndarray) -> np.ndarray:
    """Exact distance from (M,2) points to each of (K,4) segments -> (M,K)."""
    p0 = segments[:, 0:2]
    d = segments[:, 2:4] - p0
    denom = np.where((d ** 2).sum(axis=1) > 0, (d ** 2).sum(axis=1), 1.0)
    rel = rz[:, None, :] - p0[None, :, :]
    t = np.clip((rel * d[None, :, :]).sum(axis=2) / denom[None, :], 0.0, 1.0)
    closest = p0[None, :, :] + t[:, :, None] * d[None, :, :]
    return np.sqrt(((rz[:, None, :] - closest) ** 2).sum(axis=2))


# ---------------------------------------------------------------------------------------
# mother fixture
# ---------------------------------------------------------------------------------------
def analytic_revolve_mother(*, mother_id: str = "fixture_revolve", sections: int = 72,
                            height_mm: float = 60.0, r_base_mm: float = 18.0,
                            wall_mm: float = 5.0, base_thickness_mm: float = 6.0,
                            taper_mm: float = 4.0, bulge_mm: float = 6.0,
                            vessel_id: str = "V01", material_id: str = "M01",
                            profile_samples: int = 96, max_segment_mm: float = 1.5
                            ) -> MotherGeometry:
    """Closed body of revolution with a real wall, a foot ring and frozen surface tags."""
    profile = build_profile(height_mm=height_mm, r_base_mm=r_base_mm, taper_mm=taper_mm,
                            bulge_mm=bulge_mm, wall_mm=wall_mm,
                            base_thickness_mm=base_thickness_mm, n_samples=profile_samples,
                            max_segment_mm=max_segment_mm)
    z_tab = profile.z_tab
    mesh = trimesh.creation.revolve(profile.loop, sections=int(sections))
    mesh = trimesh.Trimesh(vertices=np.asarray(mesh.vertices, dtype=np.float64),
                           faces=np.asarray(mesh.faces, dtype=np.int64), process=False)
    mesh.fix_normals()
    if not bool(mesh.is_watertight) or float(mesh.volume) <= 0:
        raise SynLabError(ErrorCode.MOTHER_INVALID,
                          "fixture revolve is not a closed positive-volume body",
                          stage="patterns.fixtures.analytic_revolve_mother")

    centroids = np.asarray(mesh.triangles_center, dtype=np.float64)
    rz = np.column_stack([np.hypot(centroids[:, 0], centroids[:, 1]), centroids[:, 2]])
    distances = _point_segment_distance(rz, profile.segments)
    nearest = np.argmin(distances, axis=1)
    tag_of_face = np.array([TAG_INDEX[profile.labels[int(index)]] for index in nearest],
                           dtype=np.int32)

    def to_uv(points: np.ndarray) -> np.ndarray:
        pts = np.atleast_2d(np.asarray(points, dtype=np.float64))
        u = np.mod(np.arctan2(pts[:, 1], pts[:, 0]) / (2.0 * np.pi), 1.0)
        # the fixture outer profile is a graph r(z): the profile coordinate is s(z).  Inner
        # wall / rim points share the height of the outer profile at the same z, and the
        # pattern region (outer wall) lies exactly on the profile.
        return np.column_stack([u, profile.s_at_z(pts[:, 2])])

    def region_mask(points: np.ndarray) -> np.ndarray:
        pts = np.atleast_2d(np.asarray(points, dtype=np.float64))
        rz_pts = np.column_stack([np.hypot(pts[:, 0], pts[:, 1]), pts[:, 2]])
        outer = _point_segment_distance(rz_pts, profile.segments[: profile.n_outer])
        return np.asarray(outer.min(axis=1) <= 1.0, dtype=bool)

    x_period = float(2.0 * np.pi * profile.r_ref_mm)
    chart = Chart(
        name="body_outer", surface_tags=(OUTER_WALL,), kind="revolve", u_periodic=True,
        x_period_mm=x_period, area_mm2=float(mesh.area), to_uv=to_uv, region_mask=region_mask,
        meta={
            "r_ref_mm": float(profile.r_ref_mm),
            "r_ref_rule": "outer radius at the middle of the legal drawing region",
            "s_range_mm": [0.0, float(profile.s_total_mm)],
            "s_range_source": "declared:analytic profile arc length",
            "s_periodic": False,
            "uv_to_xyz": profile.xy_at,
            "profile": profile.as_dict(),
            "fixture": True,
            "u_definition": "atan2(y, x) / (2 pi) mod 1",
            "s_definition": "true arc length mm along the outer profile from the base plane",
            "x_mm_definition": "u * x_period_mm (reference circumference 2 pi r_ref)",
        },
    )
    return MotherGeometry(
        mesh=mesh, face_surface_tag=tag_of_face, surface_tag_names=dict(TAG_NAMES),
        charts=[chart], vessel_id=vessel_id, material_id=material_id,
        params={"fixture": "analytic_revolve", "profile": profile.as_dict(),
                "wall_mm": float(profile.wall_mm),
                "min_wall_thickness_mm": float(profile.wall_mm),
                "base_thickness_mm": float(profile.base_thickness_mm),
                "height_mm": float(profile.height_mm)},
        mother_id=mother_id,
        meta={"fixture": True,
              "fixture_kind": "analytic_revolve_mother (synlab.patterns.fixtures)",
              "min_wall_thickness_mm": float(profile.wall_mm),
              "mother_source": "synlab.patterns.fixtures.analytic_revolve_mother",
              "wall_thickness_source": "analytic profile (outer minus inner radius)"},
    )


def builtin_mother(**kwargs: Any) -> MotherGeometry:
    """Cached default fixture instance (the same object for repeated audits)."""
    if kwargs:
        return analytic_revolve_mother(**kwargs)
    if "default" not in _CACHE:
        _CACHE["default"] = analytic_revolve_mother()
    return _CACHE["default"]


def _usable_for_patterns(mother: MotherGeometry) -> tuple[bool, str]:
    """A mother is usable when it carries a periodic chart with a measurable region."""
    from .charts import resolve_frame

    if not getattr(mother, "charts", None):
        return False, "mother has no chart"
    candidates = sorted({mother.tag_name(int(tag)) for chart in mother.charts
                         for tag in chart.surface_tags})
    reason = "no tagged chart"
    for name in candidates:
        try:
            frame = resolve_frame(mother, name)
        except SynLabError as exc:
            reason = f"{name}: {exc.code}"
            continue
        if frame.x_period_mm and frame.s_span_mm > 1.0 and frame.area_mm2 > 1.0:
            return True, f"{name}: periodic, {frame.area_mm2:.1f} mm2, {frame.s_span_mm:.1f} mm"
        reason = f"{name}: no usable period/area"
    return False, reason


def try_real_mother(vessel_id: str = "V01", material_id: str = "M01", *,
                    seed: int = 11, params: dict[str, Any] | None = None
                    ) -> tuple[MotherGeometry | None, str]:
    """Use ``synlab.mothers.api.create_mother`` when it is importable and usable."""
    try:
        from ..mothers.api import create_mother  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on parallel development
        return None, f"synlab.mothers.api unavailable ({type(exc).__name__}: {exc})"
    try:
        from ..seeds import make_rng

        mother = create_mother(vessel_id, material_id, dict(params or {}),
                               make_rng(int(seed), "shape"),
                               mother_id=f"{vessel_id}-{material_id}-{int(seed)}")
    except Exception as exc:  # pragma: no cover - depends on parallel development
        return None, f"create_mother failed ({type(exc).__name__}: {exc})"
    ok, reason = _usable_for_patterns(mother)
    if not ok:
        return None, f"create_mother returned an unusable mother ({reason})"
    return mother, f"synlab.mothers.api.create_mother ({reason})"


def mother_for_audit(*, vessel_id: str = "V01", material_id: str = "M01", seed: int = 11,
                     prefer_real: bool = True, **fixture_kwargs: Any
                     ) -> tuple[MotherGeometry, str, list[str]]:
    """Prefer the real generator, fall back to the analytic fixture with the reason."""
    notes: list[str] = []
    if prefer_real:
        mother, source = try_real_mother(vessel_id, material_id, seed=seed)
        if mother is not None:
            return mother, source, notes
        notes.append(f"fallback to analytic fixture: {source}")
    mother = analytic_revolve_mother(vessel_id=vessel_id, material_id=material_id,
                                     mother_id=f"fixture-{vessel_id}-{seed}", **fixture_kwargs)
    return mother, "synlab.patterns.fixtures.analytic_revolve_mother", notes


__all__ = ["OUTER_WALL", "INNER_WALL", "RIM", "FOOT", "BASE", "ATTACHMENT", "INTERFACE",
           "TAG_NAMES", "TAG_INDEX", "RevolveProfile", "build_profile",
           "analytic_revolve_mother", "builtin_mother", "try_real_mother", "mother_for_audit"]
