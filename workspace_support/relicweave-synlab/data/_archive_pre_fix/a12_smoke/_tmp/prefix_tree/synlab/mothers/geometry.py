"""Two-dimensional profile construction for vessels of revolution (plan 7.1).

The plan requires a *thick* closed material body, not a surface of revolution:

1. build the profile mid-line ``q(s) = (r(s), z(s))`` from ordered control points with
   a shape-preserving SciPy PCHIP (no overshoot, ``r >= 0``);
2. compute the two-dimensional unit normal and offset it by half the local thickness
   field: ``q±(s) = q(s) ± 0.5 * t(s) * n(s)`` so that slanted walls keep a *normal*
   thickness instead of only a radial one;
3. reject profiles whose offsets self-intersect, leave the axis, or become thinner than
   the minimum wall thickness;
4. hand the resulting closed half-profile to :func:`trimesh.creation.revolve`.

The labelled poly-line produced here is the single source of truth for face
``surface_tag`` values, for the revolve chart arclength coordinate and for the
thickness audit, so construction and semantics cannot drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy.interpolate import PchipInterpolator
from shapely.geometry import LineString

from ..errors import ErrorCode, SynLabError

# Region labels carried by the closed profile poly-line.  They map onto the frozen
# ``SurfaceTag`` vocabulary of ``synlab.schemas.runtime``.
REGION_OUTER = "outer_wall"
REGION_INNER = "inner_wall"
REGION_RIM = "rim"
REGION_FOOT = "foot"
REGION_BASE = "base"
REGION_ATTACHMENT = "attachment"

#: Regions that belong to the material body of a shell (used by the thickness audit).
SHELL_REGIONS = (REGION_OUTER, REGION_INNER, REGION_RIM, REGION_FOOT, REGION_BASE)

#: A sharp corner only rejects the profile when the offset is *also* above the local curvature
#: radius; a filleted outline is covered by the curvature margin alone.  See
#: :func:`offset_clearance`.
MIN_CLEARANCE_RATIO = 0.5


@dataclass
class LabelledPolyline:
    """Ordered, region-labelled poly-line plus arclength table."""

    points: np.ndarray          # (P, 2) float64 in (r, z)
    labels: np.ndarray          # (P-1,) object/str labels per segment
    s_mm: np.ndarray            # (P,) cumulative arclength at the points

    def __post_init__(self) -> None:
        self.points = np.asarray(self.points, dtype=np.float64)
        self.labels = np.asarray(self.labels, dtype=object)
        self.s_mm = np.asarray(self.s_mm, dtype=np.float64)

    @property
    def length_mm(self) -> float:
        return float(self.s_mm[-1])

    def project(self, rz: np.ndarray, *, chunk: int = 20000) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Nearest point on the poly-line: returns (s_mm, distance_mm, segment_index)."""
        rz = np.atleast_2d(np.asarray(rz, dtype=np.float64))
        p0 = self.points[:-1]
        p1 = self.points[1:]
        seg = p1 - p0
        seg_len2 = np.einsum("ij,ij->i", seg, seg)
        seg_len2 = np.where(seg_len2 <= 0, 1e-30, seg_len2)
        s0 = self.s_mm[:-1]
        seg_len = np.sqrt(seg_len2)

        n = rz.shape[0]
        best_d = np.full(n, np.inf)
        best_s = np.zeros(n)
        best_i = np.zeros(n, dtype=np.int64)
        for start in range(0, n, chunk):
            block = rz[start:start + chunk]
            ap = block[:, None, :] - p0[None, :, :]
            t = np.einsum("nki,ki->nk", ap, seg) / seg_len2[None, :]
            t = np.clip(t, 0.0, 1.0)
            proj = p0[None, :, :] + t[:, :, None] * seg[None, :, :]
            d = np.linalg.norm(block[:, None, :] - proj, axis=2)
            idx = np.argmin(d, axis=1)
            rows = np.arange(block.shape[0])
            best_d[start:start + chunk] = d[rows, idx]
            best_i[start:start + chunk] = idx
            best_s[start:start + chunk] = s0[idx] + t[rows, idx] * seg_len[idx]
        return best_s, best_d, best_i

    def label_at(self, rz: np.ndarray) -> np.ndarray:
        _, _, idx = self.project(rz)
        return self.labels[idx]

    def offset_curve(self, s_query: np.ndarray, *, side: str = "outer") -> np.ndarray:
        """Interpolate a point on the poly-line at given arclength (piecewise linear)."""
        pts = self.points
        if side == "inner":
            pts = pts[::-1]
            s_tab = self.length_mm - self.s_mm[::-1]
        else:
            s_tab = self.s_mm
        s_query = np.clip(np.asarray(s_query, dtype=np.float64), s_tab[0], s_tab[-1])
        out = np.empty((s_query.shape[0], 2), dtype=np.float64)
        out[:, 0] = np.interp(s_query, s_tab, pts[:, 0])
        out[:, 1] = np.interp(s_query, s_tab, pts[:, 1])
        return out


@dataclass
class ShellProfile:
    """A thick-walled vessel profile: mid-line, thickness field and closed half-profile."""

    s_mm: np.ndarray
    r_mid: np.ndarray
    z_mid: np.ndarray
    t_mm: np.ndarray
    r_out: np.ndarray
    z_out: np.ndarray
    r_in: np.ndarray
    z_in: np.ndarray
    closed: np.ndarray                     # (P,2) linestring handed to trimesh.revolve
    polyline: LabelledPolyline             # closed profile, region-labelled, arclength
    region_of_segment: np.ndarray          # (P-1,) label per closed-profile segment
    metrics: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------ queries
    @property
    def z_rim(self) -> float:
        return float(self.metrics["z_rim"])

    @property
    def z_bottom(self) -> float:
        return float(self.metrics["z_bottom"])

    @property
    def r_max(self) -> float:
        return float(self.metrics["r_max"])

    @property
    def thickness_min_mm(self) -> float:
        return float(self.metrics["thickness_min_mm"])

    @property
    def thickness_max_mm(self) -> float:
        """Maximum wall thickness of the design field ``t(s)`` (plan 7.1 step 3).

        The realised thickness is always re-measured on the final triangles by
        ``audit_mother``; this value is only the *design* upper bound used to gate the
        audit tolerance, never a substitute for the measurement.
        """
        return float(self.metrics["thickness_max_mm"])

    @property
    def thickness_mean_mm(self) -> float:
        return float(self.metrics["thickness_mean_mm"])

    @property
    def z_table(self) -> np.ndarray:
        return self.metrics["z_table"]

    def outer_radius_at_z(self, z: np.ndarray) -> np.ndarray:
        table = self.metrics["outer_table"]
        return np.interp(np.asarray(z, dtype=np.float64), table[:, 0], table[:, 1])

    def inner_radius_at_z(self, z: np.ndarray) -> np.ndarray:
        table = self.metrics["inner_table"]
        return np.interp(np.asarray(z, dtype=np.float64), table[:, 0], table[:, 1])

    def profile_row(self, region: str) -> np.ndarray:
        """(M,2) mid-line points whose *closed* profile segment carries ``region``."""
        rows = []
        for i, label in enumerate(self.region_of_segment):
            if label == region:
                rows.append(i)
        return np.asarray(rows, dtype=np.int64)


def _chord_param(ctrl: np.ndarray) -> np.ndarray:
    seg = np.linalg.norm(np.diff(ctrl, axis=0), axis=1)
    if np.any(seg <= 0):
        raise SynLabError(ErrorCode.MOTHER_INVALID,
                          "profile control points contain duplicates",
                          stage="mothers.profile", measurements={"n_ctrl": int(len(ctrl))})
    p = np.concatenate([[0.0], np.cumsum(seg)])
    return p / p[-1]


def pchip_curve(ctrl: np.ndarray, *, samples: int = 220) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Shape-preserving mid-line through ``ctrl`` sampled uniformly in arclength.

    Returns ``(r, z, s_mm)`` with monotonically increasing ``s_mm`` anchored at 0.
    """
    ctrl = np.asarray(ctrl, dtype=np.float64)
    if ctrl.ndim != 2 or ctrl.shape[1] != 2 or ctrl.shape[0] < 3:
        raise SynLabError(ErrorCode.MOTHER_INVALID, "profile needs >=3 control points (K,2)",
                          stage="mothers.profile", measurements={"shape": list(ctrl.shape)})
    if np.any(ctrl[:, 0] < 0):
        raise SynLabError(ErrorCode.MOTHER_INVALID, "profile radius control point is negative",
                          stage="mothers.profile",
                          measurements={"r_min": float(ctrl[:, 0].min())})
    param = _chord_param(ctrl)
    fr = PchipInterpolator(param, ctrl[:, 0], extrapolate=False)
    fz = PchipInterpolator(param, ctrl[:, 1], extrapolate=False)
    dense_p = np.linspace(0.0, 1.0, max(400, samples * 8))
    r_dense = fr(dense_p)
    z_dense = fz(dense_p)
    r_dense = np.maximum(r_dense, 0.0)
    ds = np.hypot(np.diff(r_dense), np.diff(z_dense))
    s_dense = np.concatenate([[0.0], np.cumsum(ds)])
    if s_dense[-1] <= 0:
        raise SynLabError(ErrorCode.MOTHER_INVALID, "degenerate profile (zero arclength)",
                          stage="mothers.profile")
    s = np.linspace(0.0, s_dense[-1], int(samples))
    r = np.interp(s, s_dense, r_dense)
    z = np.interp(s, s_dense, z_dense)
    r[0] = ctrl[0, 0]
    z[0] = ctrl[0, 1]
    return r, z, s


def thickness_field(s_mm: np.ndarray, ctrl: np.ndarray) -> np.ndarray:
    """Thickness field ``t(s)`` from ``(s_normalised, t_mm)`` control points (PCHIP)."""
    ctrl = np.asarray(ctrl, dtype=np.float64)
    if ctrl.ndim != 2 or ctrl.shape[1] != 2 or ctrl.shape[0] < 2:
        raise SynLabError(ErrorCode.MOTHER_INVALID, "thickness control points need (K,2)",
                          stage="mothers.profile")
    p = ctrl[:, 0]
    if np.any(np.diff(p) <= 0):
        raise SynLabError(ErrorCode.MOTHER_INVALID, "thickness control points must be ordered",
                          stage="mothers.profile")
    f = PchipInterpolator(p, ctrl[:, 1], extrapolate=True)
    t = np.asarray(f(np.asarray(s_mm, dtype=np.float64) / float(s_mm[-1])), dtype=np.float64)
    # A PCHIP through the pole blend (t = 0 at s = 0) can extrapolate to a small negative
    # value just before the first control point; the material field is clamped to zero
    # there because that is exactly what the pole blend means.
    return np.maximum(t, 0.0)


def _tangent_normal(r: np.ndarray, z: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    dr = np.gradient(r)
    dz = np.gradient(z)
    norm = np.hypot(dr, dz)
    norm = np.where(norm <= 1e-12, 1e-12, norm)
    tr = dr / norm
    tz = dz / norm
    # outward normal of a path running from the base centre outwards and up the wall
    nr = tz
    nz = -tr
    return np.column_stack([tr, tz]), np.column_stack([nr, nz])


def _curvature(r: np.ndarray, z: np.ndarray, *, window: int = 9) -> np.ndarray:
    """Curvature of a sampled curve with a stencil wide enough to reject sampling noise.

    A plain second difference of a 900-sample poly-line is dominated by discretisation noise,
    which would turn the curvature guard into a coin flip.  The derivative is estimated from a
    least-squares line fit over a sliding window of ``window`` samples (a Savitzky-Golay first
    derivative), which is stable for the chord-error sampled profiles used here.
    """
    pts = np.column_stack([np.asarray(r, dtype=np.float64), np.asarray(z, dtype=np.float64)])
    n = len(pts)
    if n < 3:
        return np.zeros(n, dtype=np.float64)
    win = int(np.clip(window, 3, max(3, n // 4)))
    if win % 2 == 0:
        win += 1
    half = win // 2
    idx = np.arange(n)
    offsets = np.arange(-half, half + 1, dtype=np.float64)
    denom = float(np.sum(offsets ** 2))
    der = np.zeros((n, 2), dtype=np.float64)
    for axis in (0, 1):
        padded = np.pad(pts[:, axis], half, mode="edge")
        windows = np.lib.stride_tricks.sliding_window_view(padded, win)
        der[:, axis] = (windows * offsets[None, :]).sum(axis=1) / denom
    d1 = der
    d2 = np.zeros_like(d1)
    for axis in (0, 1):
        padded = np.pad(d1[:, axis], half, mode="edge")
        windows = np.lib.stride_tricks.sliding_window_view(padded, win)
        d2[:, axis] = (windows * offsets[None, :]).sum(axis=1) / denom
    cross = d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0]
    speed = np.hypot(d1[:, 0], d1[:, 1])
    denom_curv = np.maximum(speed ** 3, 1e-12)
    return np.abs(cross) / denom_curv


def smooth_polyline(points: np.ndarray, *, radius_mm: float) -> np.ndarray:
    """Corner fillet of a poly-line as a physical-length moving average (plan 7.1 step 3).

    A foot ring or a shoulder is described by control points that meet at a sharp corner.
    Offsetting the mid-line by half the *base* thickness at such a corner folds the inner or
    outer wall onto itself, which is exactly what the plan forbids.  Real built vessels have a
    fillet there, so the mid-line is resampled uniformly in arclength and filtered with a box
    kernel of physical half-length ``radius_mm``: the silhouette is preserved (the kernel stays
    far shorter than the profile features) and the offset becomes an embedding again.  The two
    axis endpoints are pinned so the profile still closes on the revolution axis.
    """
    pts = np.asarray(points, dtype=np.float64)
    if radius_mm <= 1e-9 or len(pts) < 3:
        return pts
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    keep = np.concatenate([[True], seg > 1e-12])
    pts = pts[keep]
    if len(pts) < 3:
        return pts
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    total = float(s[-1])
    if total <= 1e-9:
        return pts
    count = int(np.clip(len(pts) * 4, 128, 4000))
    grid = np.linspace(0.0, total, count)
    dense = np.column_stack([np.interp(grid, s, pts[:, 0]), np.interp(grid, s, pts[:, 1])])
    step = total / float(count - 1)
    half = int(max(1, round(float(radius_mm) / max(step, 1e-9))))
    if half <= 0:
        return pts
    kernel = np.ones(2 * half + 1) / float(2 * half + 1)
    padded = np.vstack([np.repeat(dense[:1], half, axis=0), dense,
                        np.repeat(dense[-1:], half, axis=0)])
    filtered = np.column_stack([np.convolve(padded[:, 0], kernel, mode="valid"),
                                np.convolve(padded[:, 1], kernel, mode="valid")])
    filtered[0] = dense[0]
    filtered[-1] = dense[-1]
    return filtered


def offset_clearance(points: np.ndarray, *, side: str = "inner") -> float:
    """Smallest offset distance that would fold a poly-line on the given side.

    Only a bend whose centre of curvature lies on the *offset* side can collapse the offset
    curve: a convex corner where the offset moves away from the bend centre is safe however
    sharp it is.  For each interior vertex the clearance is the local in-circle radius of the
    two neighbouring vertices (``r = sqrt((s-a)(s-b)(s-c)/s)`` with the vertex as the apex),
    which is a tight lower bound on the offset that folds the curve.  The minimum is taken over
    the vertices whose bend opens towards ``side`` (``"inner"`` = the ``-normal`` direction the
    wall offset uses, ``"outer"`` = ``+normal``).
    """
    pts = np.asarray(points, dtype=np.float64)
    if len(pts) < 3:
        return float("inf")
    prev_dir = pts[1:-1] - pts[:-2]
    next_dir = pts[2:] - pts[1:-1]
    la = np.linalg.norm(prev_dir, axis=1)
    lc = np.linalg.norm(next_dir, axis=1)
    lb = np.linalg.norm(pts[2:] - pts[:-2], axis=1)
    valid = (la > 1e-12) & (lb > 1e-12) & (lc > 1e-12)
    if not np.any(valid):
        return float("inf")
    cross = prev_dir[:, 0] * next_dir[:, 1] - prev_dir[:, 1] * next_dir[:, 0]
    turn_left = cross > 1e-9
    turn_right = cross < -1e-9
    unsafe = turn_left if side == "inner" else turn_right
    unsafe &= valid
    if not np.any(unsafe):
        return float("inf")
    a = la[unsafe]
    b = lb[unsafe]
    c = lc[unsafe]
    # r = perpendicular distance from the vertex to the chord of its neighbours
    s = 0.5 * (a + b + c)
    product = np.maximum(s * (s - a) * (s - b) * (s - c), 0.0)
    area = np.sqrt(product)
    r_vertex = 2.0 * area / np.maximum(b, 1e-12)
    # the offset lines meet at r / tan(phi/2); a nearly straight vertex has no fold distance
    sin_half = np.sqrt(np.maximum(product, 0.0) / np.maximum(a * b * c, 1e-18))
    cos_half = np.sqrt(np.maximum(1.0 - sin_half ** 2, 0.0))
    tan_half = sin_half / np.maximum(cos_half, 1e-12)
    fold = np.where(tan_half > 1e-6, r_vertex / np.maximum(tan_half, 1e-12), np.inf)
    if not np.any(np.isfinite(fold)):
        return float("inf")
    return float(np.min(fold))


def _self_intersects(points: np.ndarray) -> bool:
    if len(points) < 4:
        return False
    line = LineString(np.asarray(points, dtype=np.float64))
    return not bool(line.is_simple)


def rdp_indices(points: np.ndarray, tol_mm: float) -> np.ndarray:
    """Ramer-Douglas-Peucker selection of a chord-error bounded subsequence.

    Adaptive sampling is an acceptance criterion (plan 7.1 step 5), not a fixed section
    count: an index is kept only when dropping it would bend the curve by more than
    ``tol_mm``.
    """
    pts = np.asarray(points, dtype=np.float64)
    n = len(pts)
    if n <= 2:
        return np.arange(n)
    keep = np.zeros(n, dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        i0, i1 = stack.pop()
        if i1 <= i0 + 1:
            continue
        a = pts[i0]
        b = pts[i1]
        seg = b - a
        seg_len = float(np.hypot(seg[0], seg[1]))
        mid = pts[i0 + 1:i1]
        if seg_len <= 1e-12:
            d = np.linalg.norm(mid - a, axis=1)
        else:
            d = np.abs((mid[:, 0] - a[0]) * seg[1] - (mid[:, 1] - a[1]) * seg[0]) / seg_len
        k = int(np.argmax(d))
        if float(d[k]) > tol_mm:
            idx = i0 + 1 + k
            keep[idx] = True
            stack.append((i0, idx))
            stack.append((idx, i1))
    return np.nonzero(keep)[0]


def sections_for_chord_error(radius_mm: float, tol_mm: float, *,
                             minimum: int = 48, maximum: int = 256) -> int:
    """Circumferential section count whose sagitta stays below ``tol_mm``."""
    r = float(max(radius_mm, 1e-6))
    tol = float(min(max(tol_mm, 1e-4), 0.49 * r))
    ratio = 1.0 - tol / r
    ratio = float(np.clip(ratio, -1.0, 1.0))
    n = int(np.ceil(np.pi / max(np.arccos(ratio), 1e-6)))
    return int(np.clip(n, minimum, maximum))


def build_shell_profile(
    ctrl: np.ndarray,
    thickness_ctrl: np.ndarray,
    *,
    chord_tol_mm: float = 0.06,
    dense_samples: int = 900,
    rim_mode: str = "flat",
    rim_bulge: float = 1.0,
    min_wall_mm: float = 1.0,
    stage: str = "mothers.profile",
) -> ShellProfile:
    """Build a thick closed half-profile (plan 7.1 steps 1-4).

    ``ctrl`` are the mid-line control points ``(r_mm, z_mm)`` starting on the axis
    (``r = 0``) with a horizontal tangent; ``thickness_ctrl`` is ``(s_norm, t_mm)``.
    """
    ctrl = np.asarray(ctrl, dtype=np.float64)
    if ctrl[0, 0] > 1e-9:
        raise SynLabError(ErrorCode.MOTHER_INVALID,
                          "profile mid-line must start on the axis (r=0)",
                          stage=stage, measurements={"r_start": float(ctrl[0, 0])})
    t_max = float(np.max(thickness_ctrl[:, 1]))
    # A sharp corner in the control poly-line would fold the offset wall: the mid-line is
    # filleted with a kernel shorter than any real profile feature (plan 7.1 step 3).
    fillet_mm = max(0.6, min(0.6 * t_max, 0.06 * max(float(ctrl[:, 0].max()), 1.0)))
    ctrl = smooth_polyline(ctrl, radius_mm=fillet_mm)
    r_mid, z_mid, s_mm = pchip_curve(ctrl, samples=dense_samples)
    t_mm = thickness_field(s_mm, thickness_ctrl)
    if np.any(t_mm < 0):
        raise SynLabError(ErrorCode.MOTHER_INVALID, "negative thickness field",
                          stage=stage, measurements={"t_min": float(t_mm.min())})
    tangent, normal = _tangent_normal(r_mid, z_mid)
    half = 0.5 * t_mm
    r_out_full = r_mid + half * normal[:, 0]
    z_out_full = z_mid + half * normal[:, 1]
    r_in_full = r_mid - half * normal[:, 0]
    z_in_full = z_mid - half * normal[:, 1]

    # --- guards: axis crossing, offset clearance, self-intersection -----------------
    r_in_clipped = float(np.min(r_in_full))
    clearance = offset_clearance(np.column_stack([r_mid, z_mid]))
    offset_margin = float(clearance / max(float(np.max(half)), 1e-9))
    kappa = _curvature(r_mid, z_mid)
    radius = np.where(kappa > 1e-12, 1.0 / np.maximum(kappa, 1e-12), np.inf)
    curvature_margin = float(np.min(radius / np.maximum(half, 1e-9)))
    if r_in_clipped < -1e-6:
        raise SynLabError(
            ErrorCode.MOTHER_INVALID,
            "inner wall crosses the revolution axis: thickness too large near the centre",
            stage=stage,
            measurements={"r_in_min_mm": r_in_clipped, "t_max_mm": float(t_mm.max())},
        )
    # A smooth arc is already covered by the curvature margin (the local radius must exceed the
    # half thickness); the clearance test exists for *sharp* corners, where the curvature
    # estimate is meaningless.  Failing only when both are violated avoids rejecting a vessel
    # whose outline is simply filleted over many samples.
    if offset_margin <= MIN_CLEARANCE_RATIO and curvature_margin <= 1.02:
        raise SynLabError(
            ErrorCode.MOTHER_INVALID,
            "the wall offset is larger than the local corner clearance (offset would fold)",
            stage=stage,
            measurements={"offset_margin": offset_margin, "clearance_mm": clearance,
                          "half_thickness_max_mm": float(np.max(half)),
                          "curvature_margin": curvature_margin,
                          "fillet_mm": float(fillet_mm),
                          "min_clearance_ratio": MIN_CLEARANCE_RATIO},
        )
    if curvature_margin <= 1.02:
        raise SynLabError(
            ErrorCode.MOTHER_INVALID,
            "half thickness exceeds the local profile curvature radius (offset would fold)",
            stage=stage,
            measurements={"curvature_margin": curvature_margin,
                          "t_max_mm": float(t_mm.max()),
                          "r_min_curvature_mm": float(np.min(radius)),
                          "fillet_mm": float(fillet_mm)},
        )

    # --- adaptive chord-error sampling of the mid-line -----------------------------
    mid_pts = np.column_stack([r_mid, z_mid])
    tol = float(chord_tol_mm)
    keep = rdp_indices(mid_pts, tol)
    realized_err = 0.0
    for _ in range(4):
        outer_probe = np.column_stack([np.maximum(r_out_full[keep], 0.0), z_out_full[keep]])
        inner_probe = np.column_stack([np.maximum(r_in_full[keep], 0.0), z_in_full[keep]])
        if len(outer_probe) < 2 or len(inner_probe) < 2:
            break
        d_out = LabelledPolyline(outer_probe, np.array([REGION_OUTER] * (len(outer_probe) - 1),
                                                       dtype=object),
                                 np.concatenate([[0.0], np.cumsum(
                                     np.linalg.norm(np.diff(outer_probe, axis=0), axis=1))]))
        d_in = LabelledPolyline(inner_probe, np.array([REGION_INNER] * (len(inner_probe) - 1),
                                                     dtype=object),
                                np.concatenate([[0.0], np.cumsum(
                                    np.linalg.norm(np.diff(inner_probe, axis=0), axis=1))]))
        dense_outer = np.column_stack([np.maximum(r_out_full, 0.0), z_out_full])
        dense_inner = np.column_stack([np.maximum(r_in_full, 0.0), z_in_full])
        _, err_o, _ = d_out.project(dense_outer)
        _, err_i, _ = d_in.project(dense_inner)
        realized_err = float(max(err_o.max(), err_i.max()))
        if realized_err <= tol:
            break
        keep = rdp_indices(mid_pts, tol * 0.5)
        tol *= 0.5
    r_out = r_out_full[keep]
    z_out = z_out_full[keep]
    r_in = r_in_full[keep]
    z_in = z_in_full[keep]
    t_kept = t_mm[keep]
    t_base = float(t_mm[0])
    tangent = tangent[keep]
    normal = normal[keep]
    radius = radius[keep]
    kappa = kappa[keep]

    outer_pts = np.column_stack([np.maximum(r_out, 0.0), z_out])
    inner_pts = np.column_stack([np.maximum(r_in, 0.0), z_in])
    # `trimesh.creation.revolve` only closes a pole when the radius is *exactly* zero;
    # a residual radius of 1e-3 mm leaves a pinhole ring.  Snap the two axis ends.
    axis_snap = float(max(outer_pts[0, 0], inner_pts[0, 0]))
    outer_pts[0, 0] = 0.0
    inner_pts[0, 0] = 0.0
    if _self_intersects(outer_pts) or _self_intersects(inner_pts):
        raise SynLabError(ErrorCode.MOTHER_INVALID,
                          "offset profile self-intersects",
                          stage=stage,
                          measurements={"outer_simple": not _self_intersects(outer_pts),
                                        "inner_simple": not _self_intersects(inner_pts)})

    # --- close the half-profile across the rim ------------------------------------
    rim_outer = outer_pts[-1]
    rim_inner = inner_pts[-1]
    if rim_mode == "flat":
        rim_pts = np.vstack([rim_outer, rim_inner])
    elif rim_mode in ("rounded", "bevel"):
        width = float(np.linalg.norm(rim_inner - rim_outer))
        n_arc = 9
        # parameter runs from `rim_outer` (ang = pi) to `rim_inner` (ang = 0)
        ang = np.linspace(np.pi, 0.0, n_arc)
        mid = 0.5 * (rim_outer + rim_inner)
        # bulge along the mid-line tangent continued outward
        t_end = tangent[-1]
        bulge = float(rim_bulge) * 0.5 * width
        arc = mid[None, :] + np.outer(np.cos(ang), 0.5 * (rim_inner - rim_outer)) \
            + np.outer(np.sin(ang), bulge * t_end)
        rim_pts = np.vstack([rim_outer, arc[1:-1], rim_inner])
    elif rim_mode == "flared":
        t_end = tangent[-1]
        n_end = normal[-1]
        flare = float(rim_bulge) * 0.5 * float(np.linalg.norm(rim_inner - rim_outer))
        lip_a = rim_outer + flare * (0.6 * t_end + 0.25 * n_end)
        lip_b = lip_a + flare * (0.8 * t_end - 0.35 * n_end)
        rim_pts = np.vstack([rim_outer, lip_a, lip_b, rim_inner])
    else:
        raise SynLabError(ErrorCode.MOTHER_INVALID, f"unknown rim_mode {rim_mode!r}", stage=stage)

    # --- resolve base / foot / wall bands on the outer path ------------------------
    # The mid-line starts horizontal on the axis, so "underside" is the part of the path
    # whose tangent is still (nearly) horizontal; a protruding contact ring on that
    # underside is what the plan calls 底足 (foot).
    tz_abs = np.abs(tangent[:, 1])
    wall_start = int(np.argmax(tz_abs > 0.55)) if np.any(tz_abs > 0.55) else len(tz_abs) - 1
    under = slice(0, max(wall_start, 1))
    z_ground = float(np.min(z_out[under]))
    contact_tol = max(0.3, 0.18 * t_base)
    contact = (z_out[under] <= z_ground + contact_tol)
    contact_r = r_out[under][contact]
    has_foot_ring = bool(contact_r.size and float(contact_r.min()) > 0.35 * t_base)
    foot_r_inner = float(contact_r.min()) if has_foot_ring else 0.0
    outer_labels = np.array([REGION_OUTER] * (len(outer_pts) - 1), dtype=object)
    for i in range(len(outer_pts) - 1):
        if i >= wall_start:
            break
        r_seg = 0.5 * (outer_pts[i, 0] + outer_pts[i + 1, 0])
        z_seg = 0.5 * (outer_pts[i, 1] + outer_pts[i + 1, 1])
        if has_foot_ring and z_seg <= z_ground + 3.0 * contact_tol and r_seg >= foot_r_inner - 0.35 * t_base:
            outer_labels[i] = REGION_FOOT
        elif z_seg <= z_ground + 2.5 * contact_tol:
            outer_labels[i] = REGION_BASE
        else:
            outer_labels[i] = REGION_BASE if i < wall_start // 2 else REGION_OUTER

    # --- assemble the closed half-profile as labelled segments ---------------------
    segments: list[tuple[np.ndarray, np.ndarray, str]] = []
    for i in range(len(outer_pts) - 1):
        segments.append((outer_pts[i], outer_pts[i + 1], str(outer_labels[i])))
    for i in range(len(rim_pts) - 1):
        segments.append((rim_pts[i], rim_pts[i + 1], REGION_RIM))
    inner_rev = inner_pts[::-1]
    for i in range(len(inner_rev) - 1):
        segments.append((inner_rev[i], inner_rev[i + 1], REGION_INNER))
    # drop zero-length segments: they would revolve into degenerate triangles
    kept = []
    for a, b, label in segments:
        if float(np.linalg.norm(b - a)) > 1e-9:
            kept.append((a, b, label))
    if len(kept) < 4:
        raise SynLabError(ErrorCode.MOTHER_INVALID, "degenerate profile (too few segments)",
                          stage=stage)
    points = np.vstack([kept[0][0][None, :], np.array([b for _, b, _ in kept])])
    labels = np.array([lab for _, _, lab in kept], dtype=object)

    # winding: counter-clockwise in (r, z) gives outward normals after revolution
    signed = float(np.sum(points[:, 0] * np.roll(points[:, 1], -1)
                          - np.roll(points[:, 0], -1) * points[:, 1]) * 0.5)
    if signed < 0:
        order = np.arange(len(points))[::-1]
        points = points[order]
        labels = labels[::-1]
        closed = points
    else:
        closed = points
    if _self_intersects(closed):
        raise SynLabError(ErrorCode.MOTHER_INVALID,
                          "closed revolve profile self-intersects (rim or foot overlaps wall)",
                          stage=stage)

    seg_vec = np.diff(closed, axis=0)
    seg_len = np.hypot(seg_vec[:, 0], seg_vec[:, 1])
    s_closed = np.concatenate([[0.0], np.cumsum(seg_len)])
    polyline = LabelledPolyline(points=closed, labels=labels, s_mm=s_closed)
    n_out = len(outer_pts)
    z_rim = float(np.max(closed[:, 1]))
    r_max = float(np.max(closed[:, 0]))

    # --- monotone-z radius tables for the wall region (charts, coarse tagging) -----
    wall = np.arange(n_out)
    z_wall = closed[wall, 1]
    order = np.argsort(z_wall, kind="stable")
    outer_table = np.column_stack([z_wall[order], closed[wall[order], 0]])
    inner_table = np.column_stack([z_in[::-1], r_in[::-1]])
    inner_table = inner_table[np.argsort(inner_table[:, 0], kind="stable")]

    metrics: dict[str, Any] = {
        "z_rim": z_rim,
        "z_bottom": float(np.min(closed[:, 1])),
        "r_max": r_max,
        "z_table": np.array([float(closed[:, 1].min()), z_rim]),
        "outer_table": outer_table,
        "inner_table": inner_table,
        "thickness_min_mm": float(np.min(t_mm)),
        "thickness_max_mm": float(np.max(t_mm)),
        "thickness_mean_mm": float(np.mean(t_mm)),
        "profile_samples": int(len(closed)),
        "chord_tol_mm": float(chord_tol_mm),
        "realized_chord_error_mm": float(realized_err),
        "dense_profile_samples": int(len(mid_pts)),
        "curvature_margin": curvature_margin,
        "offset_clearance_mm": float(clearance),
        "offset_margin": offset_margin,
        "fillet_mm": float(fillet_mm),
        "midline_length_mm": float(s_mm[-1]),
        "has_foot_ring": has_foot_ring,
        "foot_r_inner_mm": float(foot_r_inner),
        "axis_snap_mm": axis_snap,
        "profile_area_mm2": abs(float(np.sum(closed[:, 0] * np.roll(closed[:, 1], -1)
                                             - np.roll(closed[:, 0], -1) * closed[:, 1]) * 0.5)),
    }
    if metrics["thickness_min_mm"] < min_wall_mm - 1e-9:
        # The pole blend and the base plate are not walls: the plan's pole topology closes the
        # underside on the axis, and the floor thickness is re-measured on the final triangles
        # by ``audit_mother``.  The wall gate therefore applies to the *kept* (chord-error
        # sampled) profile past the pole blend, and it starts at the first upright sample
        # rather than the very first one (a tall foot ring turns upright before the wall does).
        kept_s = s_mm[keep]
        blend_end = float(metrics.get("pole_blend_fraction", 0.0)) * float(s_mm[-1])
        upright = np.abs(tangent[:, 1]) >= 0.5          # tangent is already reduced by ``keep``
        candidates = np.nonzero(upright & (kept_s > blend_end + 1e-9))[0]
        first_wall = int(candidates[0]) if candidates.size else int(np.argmax(upright))
        wall = t_kept[first_wall:]
        wall_min = float(np.min(wall)) if wall.size else float(metrics["thickness_min_mm"])
        metrics["wall_thickness_min_mm"] = wall_min
        metrics["wall_region_start_mm"] = float(kept_s[first_wall]) if kept_s.size else 0.0
        if wall_min < min_wall_mm - 1e-9:
            raise SynLabError(
                ErrorCode.MOTHER_INVALID,
                f"wall thickness {wall_min:.3f} mm below minimum {min_wall_mm:.3f} mm",
                stage=stage,
                measurements={"thickness_min_mm": metrics["thickness_min_mm"],
                              "wall_thickness_min_mm": wall_min,
                              "wall_region_start_mm": metrics["wall_region_start_mm"],
                              "pole_blend_end_mm": blend_end,
                              "min_wall_mm": float(min_wall_mm)},
            )
    return ShellProfile(
        s_mm=s_mm, r_mid=r_mid, z_mid=z_mid, t_mm=t_mm,
        r_out=r_out, z_out=z_out, r_in=r_in, z_in=z_in,
        closed=closed, polyline=polyline, region_of_segment=labels, metrics=metrics,
    )


def revolve_thickness_extremes(profile: ShellProfile) -> tuple[float, float]:
    return float(np.min(profile.t_mm)), float(np.max(profile.t_mm))
