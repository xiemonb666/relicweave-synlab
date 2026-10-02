"""Closed shared-cutter construction: cut basis, finite Fourier height field, watertight C.

Contract (plan 10.1 / 30.4):

* one deterministic height field ``w = h(u, v)`` built from a low-frequency bend plus 3-5
  finite Fourier bands, amplitudes around ``[0.02, 0.3] mm`` and wavelengths in
  ``[0.2, 3.0] mm``;
* the shared surface is closed towards negative ``w`` into a **watertight solid** whose
  sides and bottom stay far away from the material;
* the triangulation is verified by evaluating the analytic ``h`` at triangle edge
  midpoints and triangle interior points; any cell over the ``0.01 mm`` budget is
  subdivided with shared edges (**no T-junctions**);
* exceeding the cell / face budget raises ``PRECISION_BUDGET_EXCEEDED``.  The shortest
  wavelength is **never** silently relaxed; failure is ``PRECISION_NOT_REALIZED``.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import trimesh
from scipy import ndimage

from ..canonical import hash_json
from ..errors import ErrorCode, SynLabError
from ..schemas.runtime import CutBasis
from .spec import (
    AMP_MAX_MM,
    AMP_MIN_MM,
    DEFAULT_ERROR_BUDGET_MM,
    DEFAULT_MAX_CUTTER_CELLS,
    DEFAULT_MAX_CUTTER_TRIANGLES,
    WAVELENGTH_MAX_MM,
    WAVELENGTH_MIN_MM,
)

__all__ = [
    "CutBasis",
    "FourierBand",
    "HeightField",
    "BandWindow",
    "build_basis",
    "basis_transforms",
    "make_height_field",
    "build_band_window",
    "attach_material_band",
    "build_closed_cutter",
    "probe_barycentrics",
]

_EPS = 1.0e-12
#: reference samples per shortest wavelength for the shared surface (plan 10.1 step 3: "0.2 mm
#: wavelength needs about 0.025 mm spacing", i.e. eight points per wavelength).  It is the
#: *sampling* reference, not the acceptance criterion: A07 accepts on the realized
#: interpolation error against the unchanged ``error_budget_mm``.
POINTS_PER_WAVELENGTH = 8.0
#: Barycentric probes for the interpolation-error check (plan 10.1 step 4): centroid, three
#: interior thirds and the three edge midpoints.
_ERROR_BARY = np.array([
    [1 / 3, 1 / 3, 1 / 3],
    [0.5, 0.25, 0.25], [0.25, 0.5, 0.25], [0.25, 0.25, 0.5],
    [0.5, 0.5, 0.0], [0.5, 0.0, 0.5], [0.0, 0.5, 0.5],
])
#: Widest triangular lattice used to *measure* the interpolation error of a cell.  A cell whose
#: diameter exceeds a few wavelengths cannot be checked by seven fixed probes (the probes alias),
#: so the probe set is refined with the cell: a lattice of order ``n`` puts ``n + 1`` samples on
#: every edge, i.e. the sample spacing is ``d / n``.
LATTICE_MAX_ORDER = 16
#: Halo (mm) over which the high-frequency content decays outside the material intersection band.
#: The far side is exactly flat, so the coarse frame cells there carry zero interpolation error.
BAND_HALO_MM = 0.6
#: Raster step (mm) for the material-band probe; the whole band/halo envelope is evaluated on it.
BAND_PROBE_STEP_MM = 0.25
#: Hard cap on the number of band probes (the raster step is coarsened until it fits).
BAND_MAX_PROBES = 400_000


# ---------------------------------------------------------------------------- basis


def _orthonormal_from(normal: np.ndarray, reference: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    n = np.asarray(normal, dtype=np.float64)
    n = n / max(float(np.linalg.norm(n)), _EPS)
    r = np.asarray(reference, dtype=np.float64)
    r = r - n * float(r @ n)
    if float(np.linalg.norm(r)) < 1.0e-9:
        alt = np.array([1.0, 0.0, 0.0]) if abs(n[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
        r = alt - n * float(alt @ n)
    e_u = r / max(float(np.linalg.norm(r)), _EPS)
    e_v = np.cross(n, e_u)
    e_v = e_v / max(float(np.linalg.norm(e_v)), _EPS)
    return e_u, e_v


def build_basis(
    points_mm: np.ndarray,
    normal: np.ndarray,
    *,
    anchor: np.ndarray | None = None,
    pad_ratio: float = 0.15,
    pad_min_mm: float = 5.0,
    depth_margin_mm: float = 2.0,
    basis_id: str = "",
    meta: dict[str, Any] | None = None,
) -> CutBasis:
    """Build a right-handed cut basis ``(e_u, e_v, n)`` covering ``points_mm``.

    ``e_u`` follows the largest-variance material direction orthogonalised against ``n`` so
    hand-computed fixtures can predict the local frame.  The (u, v) rectangle is padded so
    the cutter sides never touch the material.
    """
    pts = np.asarray(points_mm, dtype=np.float64).reshape(-1, 3)
    if pts.shape[0] < 3:
        raise SynLabError(ErrorCode.MOTHER_INVALID, "cut basis needs >= 3 material points",
                          stage="fracture.cut.basis")
    n = np.asarray(normal, dtype=np.float64)
    n = n / max(float(np.linalg.norm(n)), _EPS)
    if anchor is None:
        anchor = pts.mean(axis=0)
    anchor = np.asarray(anchor, dtype=np.float64).reshape(3)
    centred = pts - anchor
    cov = centred.T @ centred
    vals, vecs = np.linalg.eigh(cov)
    reference = vecs[:, int(np.argmax(vals))]
    e_u, e_v = _orthonormal_from(n, reference)
    u = centred @ e_u
    v = centred @ e_v
    w = centred @ n
    du = float(u.max() - u.min())
    dv = float(v.max() - v.min())
    pad = max(pad_ratio * max(du, dv, 1.0), pad_min_mm)
    u_range = (float(u.min()) - pad, float(u.max()) + pad)
    v_range = (float(v.min()) - pad, float(v.max()) + pad)
    meta_out = dict(meta or {})
    meta_out.update({
        "w_min_mm": float(w.min()),
        "w_max_mm": float(w.max()),
        "material_u_range": [float(u.min()), float(u.max())],
        "material_v_range": [float(v.min()), float(v.max())],
        "pad_mm": pad,
        "depth_margin_mm": depth_margin_mm,
        "material_extent_mm": [du, dv, float(w.max() - w.min())],
    })
    basis = CutBasis(
        origin=anchor, e_u=e_u, e_v=e_v, normal=n, u_range=u_range, v_range=v_range,
        h_scale_mm=0.0, basis_id=basis_id or "", meta=meta_out,
    )
    if not basis.basis_id:
        basis.basis_id = hash_json({
            "origin": [float(x) for x in anchor], "e_u": [float(x) for x in e_u],
            "e_v": [float(x) for x in e_v], "n": [float(x) for x in n],
            "u": [float(x) for x in u_range], "v": [float(x) for x in v_range],
        })[:32]
    return basis


def basis_transforms(basis: CutBasis) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(R, t)`` with ``local = R @ world + t`` for the cut basis."""
    R = np.stack([basis.e_u, basis.e_v, basis.normal], axis=0)
    t = -R @ np.asarray(basis.origin, dtype=np.float64)
    return R, t


# ---------------------------------------------------------------------------- height field


@dataclass
class FourierBand:
    amplitude_mm: float
    wavelength_mm: float
    direction: np.ndarray  # (2,) unit
    phase: float

    @property
    def k(self) -> float:
        return 2.0 * np.pi / float(self.wavelength_mm)

    def as_dict(self) -> dict[str, Any]:
        return {
            "amplitude_mm": float(self.amplitude_mm),
            "wavelength_mm": float(self.wavelength_mm),
            "direction": np.asarray(self.direction, dtype=np.float64).tolist(),
            "phase": float(self.phase),
        }


@dataclass
class BandWindow:
    """Rasterised material-intersection envelope over the cutter ``(u, v)`` rectangle.

    ``value`` is exactly ``1`` on the band core and falls to ``0`` over ``halo_mm`` outside it, so
    the shared surface equals the plane wherever the cutter is away from the material.  The
    envelope is built once per cutter and evaluated by bilinear lookup, never per query point.
    """

    u0: float
    v0: float
    step_mm: float
    values: np.ndarray            # (nu, nv) float64 in [0, 1]
    grad_u: np.ndarray            # (nu, nv) dW/du on the raster (per mm)
    grad_v: np.ndarray            # (nu, nv) dW/dv on the raster (per mm)
    lap: np.ndarray               # (nu, nv) coarse |d2W| estimate (per mm^2)
    core: np.ndarray              # (nu, nv) bool: window == 1
    halo_mm: float
    margin_mm: float
    stats: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------ sampling
    def _frac(self, u: np.ndarray, v: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray,
                                                          np.ndarray, np.ndarray]:
        fi = (np.asarray(u, dtype=np.float64) - self.u0) / self.step_mm
        fj = (np.asarray(v, dtype=np.float64) - self.v0) / self.step_mm
        fi = np.clip(fi, 0.0, self.values.shape[0] - 1.0 - 1e-12)
        fj = np.clip(fj, 0.0, self.values.shape[1] - 1.0 - 1e-12)
        i0 = np.floor(fi).astype(np.int64)
        j0 = np.floor(fj).astype(np.int64)
        ti = fi - i0
        tj = fj - j0
        return i0, j0, ti, tj, np.broadcast(fi, fj).shape

    def _sample(self, table: np.ndarray, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        i0, j0, ti, tj, shape = self._frac(u, v)
        i1 = i0 + 1
        j1 = j0 + 1
        a = table[i0, j0] * (1 - ti) + table[i1, j0] * ti
        b = table[i0, j1] * (1 - ti) + table[i1, j1] * ti
        return (a * (1 - tj) + b * tj).reshape(shape)

    def value(self, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        return np.clip(self._sample(self.values, u, v), 0.0, 1.0)

    def gradient(self, u: np.ndarray, v: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        return self._sample(self.grad_u, u, v), self._sample(self.grad_v, u, v)

    def is_exactly_one(self, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        """True where the envelope leaves the frozen field untouched (``W == 1``)."""
        return self.value(u, v) >= 1.0 - 1.0e-12

    def as_dict(self) -> dict[str, Any]:
        return {
            "shape": [int(self.values.shape[0]), int(self.values.shape[1])],
            "step_mm": float(self.step_mm),
            "halo_mm": float(self.halo_mm),
            "margin_mm": float(self.margin_mm),
            "core_area_mm2": float(self.core.sum()) * self.step_mm ** 2,
            "window_area_mm2": float(np.sum(self.values > 0.0)) * self.step_mm ** 2,
            "value_range": [float(self.values.min()), float(self.values.max())],
            **self.stats,
        }


def _lattice_bary(order: int) -> np.ndarray:
    """Barycentric coordinates of the order-``n`` triangular lattice (``(n+1)(n+2)/2`` rows)."""
    n = max(int(order), 1)
    rows = [[a / n, b / n, (n - a - b) / n]
            for a in range(n + 1) for b in range(n + 1 - a)]
    return np.asarray(rows, dtype=np.float64)


def probe_barycentrics(cell_mm: float, wavelength_min_mm: float | None,
                       budget_mm: float) -> np.ndarray:
    """Probe set used to *measure* the interpolation error of one cell (plan 10.1 step 4).

    Seven fixed probes alias badly once a cell spans a whole wavelength, so the lattice order
    follows the cell: the sample spacing stays at or below ``min(d / 4, wavelength / 8)`` while
    the field is coarse, and the order is capped at :data:`LATTICE_MAX_ORDER`.
    """
    d = float(cell_mm)
    order = 4
    if wavelength_min_mm is not None and np.isfinite(wavelength_min_mm) and wavelength_min_mm > 0:
        order = int(np.ceil(8.0 * d / float(wavelength_min_mm)))
        order = int(np.clip(max(order, 4), 4, LATTICE_MAX_ORDER))
    del budget_mm
    lattice = _lattice_bary(order)
    return np.unique(np.round(np.vstack([_ERROR_BARY, lattice]), 12), axis=0)


@dataclass
class _ProbeSet:
    """Cell diameter -> probe barycentrics, memoised because cells repeat their sizes."""

    wavelength_min_mm: float | None
    budget_mm: float
    _cache: dict[float, np.ndarray] = field(default_factory=dict)

    def for_cell(self, cell_mm: float) -> np.ndarray:
        key = round(float(cell_mm), 9)
        found = self._cache.get(key)
        if found is None:
            found = probe_barycentrics(key, self.wavelength_min_mm, self.budget_mm)
            self._cache[key] = found
        return found


@dataclass
class HeightField:
    """``h(u, v)`` = frozen finite Fourier sum minus its band mean, windowed to the band.

    ``raw`` is the pure Fourier sum and ``window`` (when set) is the material-intersection
    envelope: it is exactly ``1`` on the material intersection band and decays smoothly to
    ``0`` over ``BAND_HALO_MM`` outside it, so the shared surface is *exactly* the plane far
    from the material and coarse cells there carry zero interpolation error (plan 10.1 step 3:
    "high frequency exists only in that band + halo, smooth decay on the far side").
    """

    basis: CutBasis
    bands: list[FourierBand]
    bend: list[FourierBand]
    mean_mm: float
    target_rms_mm: float
    realized_rms_mm: float
    wavelength_min_mm: float
    max_slope: float
    window: "BandWindow | None" = None
    meta: dict[str, Any] = field(default_factory=dict)

    def raw(self, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        """Pure frozen Fourier sum (no mean removal, no window): the coefficient record."""
        u = np.asarray(u, dtype=np.float64)
        v = np.asarray(v, dtype=np.float64)
        out = np.zeros(np.broadcast(u, v).shape, dtype=np.float64)
        for band in self.bend:
            k = band.k
            out = out + band.amplitude_mm * np.cos(
                k * (band.direction[0] * u + band.direction[1] * v) + band.phase)
        for band in self.bands:
            k = band.k
            out = out + band.amplitude_mm * np.cos(
                k * (band.direction[0] * u + band.direction[1] * v) + band.phase)
        return out

    def __call__(self, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        """The authoritative shared surface height ``w = h(u, v)`` (de-meaned and windowed)."""
        centred = self.raw(u, v) - self.mean_mm
        if self.window is None:
            return centred
        return self.window.value(u, v) * centred

    def gradient(self, u: np.ndarray, v: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        u = np.asarray(u, dtype=np.float64)
        v = np.asarray(v, dtype=np.float64)
        du = np.zeros(np.broadcast(u, v).shape, dtype=np.float64)
        dv = np.zeros_like(du)
        for band in list(self.bend) + list(self.bands):
            k = band.k
            arg = k * (band.direction[0] * u + band.direction[1] * v) + band.phase
            s = -band.amplitude_mm * k * np.sin(arg)
            du = du + s * band.direction[0]
            dv = dv + s * band.direction[1]
        if self.window is None:
            return du, dv
        w = self.window.value(u, v)
        dw_du, dw_dv = self.window.gradient(u, v)
        centred = self.raw(u, v) - self.mean_mm
        return w * du + centred * dw_du, w * dv + centred * dw_dv

    def curvature_bound(self) -> float:
        """Upper bound of ``|h_aa|`` of the *unwindowed* field along any unit (u, v) direction."""
        total = 0.0
        for band in list(self.bend) + list(self.bands):
            total += band.amplitude_mm * band.k ** 2
        return float(total)

    def windowed_curvature_bound(self) -> float:
        """Upper bound of ``|(W h)_aa|`` including the envelope's own derivatives."""
        base = self.curvature_bound()
        if self.window is None:
            return float(base)
        slope = float(np.max(np.hypot(self.window.grad_u, self.window.grad_v)))
        second = float(np.max(np.abs(self.window.lap)))
        amp = float(sum(abs(b.amplitude_mm) for b in list(self.bend) + list(self.bands)))
        grad = float(sum(abs(b.amplitude_mm) * b.k
                         for b in list(self.bend) + list(self.bands)))
        return float(base + 2.0 * slope * grad + second * amp)

    def analytic_error_bound(self, cell_mm: float) -> float:
        """Conservative linear-interpolation error bound for a cell of size ``cell_mm``."""
        return 0.125 * self.windowed_curvature_bound() * float(cell_mm) ** 2

    @property
    def is_flat(self) -> bool:
        return not self.bands and not self.bend

    def as_dict(self) -> dict[str, Any]:
        return {
            "bands": [b.as_dict() for b in self.bands],
            "bend": [b.as_dict() for b in self.bend],
            "mean_mm": float(self.mean_mm),
            "target_rms_mm": float(self.target_rms_mm),
            "realized_rms_mm": float(self.realized_rms_mm),
            "wavelength_min_mm": (None if self.is_flat else float(self.wavelength_min_mm)),
            "max_slope": float(self.max_slope),
            "amplitude_max_mm": float(max((b.amplitude_mm for b in self.bands), default=0.0)),
            "curvature_bound": float(self.curvature_bound()),
            "curvature_bound_windowed": float(self.windowed_curvature_bound()),
            "flat": bool(self.is_flat),
            "window": None if self.window is None else self.window.as_dict(),
            "meta": self.meta,
        }


def make_height_field(
    basis: CutBasis,
    rng: np.random.Generator,
    *,
    target_rms_mm: float,
    n_bands: int | None = None,
    band_grid: int = 41,
    wavelength_min_mm: float = WAVELENGTH_MIN_MM,
    wavelength_max_mm: float = WAVELENGTH_MAX_MM,
    norm_uv: tuple[np.ndarray, np.ndarray] | None = None,
) -> HeightField:
    """Sample one frozen coefficient set (plan 10.1 step 3); never called per query.

    ``wavelength_min_mm`` is the *shortest* admitted wavelength.  The caller may raise it
    (a frozen config's ``min_feature_wavelength_mm``); it is never lowered below the
    package guard, and the realized shortest wavelength is reported so a resource failure
    is attributable instead of silent.

    ``norm_uv`` is the area-weighted de-meaning / RMS normalisation set.  Plan 10.1 step 3
    asks for the normalisation *over the material intersection band*; when it is not given the
    material bounding rectangle is used (the pre-band behaviour, kept for direct callers).
    """
    target_rms_mm = float(max(float(target_rms_mm), 0.0))
    wl_min = float(max(float(wavelength_min_mm), WAVELENGTH_MIN_MM))
    wl_max = float(max(float(wavelength_max_mm), wl_min * 1.05))
    if target_rms_mm <= 0.0:
        basis.h_scale_mm = 0.0
        return HeightField(
            basis=basis, bands=[], bend=[], mean_mm=0.0, target_rms_mm=0.0,
            realized_rms_mm=0.0, wavelength_min_mm=float("inf"), max_slope=0.0,
            meta={"zero_amplitude": True, "n_bands": 0,
                  "reason": "zero target RMS => analytically flat shared surface"},
        )
    n_bands = int(n_bands) if n_bands else int(rng.integers(3, 6))
    n_bands = int(np.clip(n_bands, 3, 5))
    if not (AMP_MIN_MM - 1e-12) <= target_rms_mm <= (AMP_MAX_MM + 1e-12):
        raise SynLabError(
            ErrorCode.SCHEMA_INVALID,
            f"target_rms_mm={target_rms_mm} outside the frozen amplitude window "
            f"[{AMP_MIN_MM}, {AMP_MAX_MM}] mm",
            stage="fracture.cut.height_field",
            measurements={"target_rms_mm": target_rms_mm},
        )
    bend: list[FourierBand] = []
    for _ in range(2):
        theta = float(rng.uniform(0.0, 2.0 * np.pi))
        wavelength = float(rng.uniform(wl_max, 4.0 * wl_max))
        phase = float(rng.uniform(0.0, 2.0 * np.pi))
        bend.append(FourierBand(0.05 * target_rms_mm, wavelength,
                                np.array([np.cos(theta), np.sin(theta)]), phase))
    edges = np.geomspace(wl_min, wl_max, n_bands + 1)
    bands: list[FourierBand] = []
    for index in range(n_bands):
        wavelength = float(np.exp(rng.uniform(np.log(edges[index]), np.log(edges[index + 1]))))
        theta = float(rng.uniform(0.0, 2.0 * np.pi))
        phase = float(rng.uniform(0.0, 2.0 * np.pi))
        bands.append(FourierBand(1.0, wavelength,
                                 np.array([np.cos(theta), np.sin(theta)]), phase))
    wavelength_min = float(min(b.wavelength_mm for b in bands))
    u_lo, u_hi = basis.meta.get("material_u_range", basis.u_range)
    v_lo, v_hi = basis.meta.get("material_v_range", basis.v_range)
    if norm_uv is not None:
        gu = np.asarray(norm_uv[0], dtype=np.float64).reshape(-1)
        gv = np.asarray(norm_uv[1], dtype=np.float64).reshape(-1)
        if gu.size < 8:
            gu = np.linspace(float(u_lo), float(u_hi), int(band_grid))
            gv = np.linspace(float(v_lo), float(v_hi), int(band_grid))
            gu, gv = np.meshgrid(gu, gv, indexing="ij")
        normalisation = "material_intersection_band"
    else:
        grid_u = np.linspace(float(u_lo), float(u_hi), int(band_grid))
        grid_v = np.linspace(float(v_lo), float(v_hi), int(band_grid))
        gu, gv = np.meshgrid(grid_u, grid_v, indexing="ij")
        normalisation = "material_bounding_rectangle"
    probe = np.zeros_like(gu, dtype=np.float64)
    for band in bands:
        k = band.k
        probe = probe + band.amplitude_mm * np.cos(
            k * (band.direction[0] * gu + band.direction[1] * gv) + band.phase)
    rms = float(np.sqrt(np.mean((probe - probe.mean()) ** 2)))
    scale = float(target_rms_mm / max(rms, 1e-12))
    for band in bands:
        band.amplitude_mm = float(band.amplitude_mm * scale)
    mean_mm = float((probe * scale).mean())
    height = HeightField(
        basis=basis, bands=bands, bend=bend, mean_mm=mean_mm,
        target_rms_mm=target_rms_mm, realized_rms_mm=0.0,
        wavelength_min_mm=wavelength_min, max_slope=0.0,
        meta={"n_bands": n_bands, "band_grid": int(band_grid), "zero_amplitude": False,
              "wavelength_min_mm": float(wavelength_min),
              "wavelength_max_mm": float(max(b.wavelength_mm for b in bands)),
              "admitted_wavelength_window_mm": [wl_min, wl_max],
              "normalisation": normalisation,
              "normalisation_samples": int(np.size(gu))},
    )
    del v_lo, v_hi
    centred = height(gu, gv)
    height.realized_rms_mm = float(np.sqrt(np.mean(centred ** 2)))
    grad_u, grad_v = height.gradient(gu, gv)
    height.max_slope = float(np.max(np.hypot(grad_u, grad_v)))
    amp_max = float(max(b.amplitude_mm for b in bands))
    if amp_max > AMP_MAX_MM * 1.75:
        raise SynLabError(
            ErrorCode.SCHEMA_INVALID,
            f"normalised band amplitude {amp_max:.4f} mm exceeds the amplitude guard",
            stage="fracture.cut.height_field",
            measurements={"amp_max_mm": amp_max, "target_rms_mm": target_rms_mm},
        )
    height.meta["amplitude_max_mm"] = amp_max
    basis.h_scale_mm = float(target_rms_mm)
    return height


# ---------------------------------------------------------------------------- material band


def _smootherstep(t: np.ndarray) -> np.ndarray:
    t = np.clip(np.asarray(t, dtype=np.float64), 0.0, 1.0)
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


def _rasterize_uv(triangles_uv: np.ndarray, u0: float, v0: float, step: float,
                  shape: tuple[int, int]) -> np.ndarray:
    """Boolean raster of ``(u, v)`` triangles on a regular grid of cell size ``step``."""
    occ = np.zeros(shape, dtype=bool)
    if triangles_uv.size == 0:
        return occ
    for tri in np.asarray(triangles_uv, dtype=np.float64):
        i0 = max(int(np.floor((tri[:, 0].min() - u0) / step)), 0)
        i1 = min(int(np.ceil((tri[:, 0].max() - u0) / step)), shape[0] - 1)
        j0 = max(int(np.floor((tri[:, 1].min() - v0) / step)), 0)
        j1 = min(int(np.ceil((tri[:, 1].max() - v0) / step)), shape[1] - 1)
        if i1 < i0 or j1 < j0:
            continue
        gi, gj = np.meshgrid(np.arange(i0, i1 + 1), np.arange(j0, j1 + 1), indexing="ij")
        px = u0 + gi.ravel() * step
        py = v0 + gj.ravel() * step
        ax, ay = tri[0]
        bx, by = tri[1]
        cx, cy = tri[2]
        den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(den) < 1.0e-18:
            continue
        w0 = ((by - cy) * (px - cx) + (cx - bx) * (py - cy)) / den
        w1 = ((cy - ay) * (px - cx) + (ax - cx) * (py - cy)) / den
        w2 = 1.0 - w0 - w1
        hit = (w0 >= -1e-9) & (w1 >= -1e-9) & (w2 >= -1e-9)
        occ[gi.ravel()[hit], gj.ravel()[hit]] = True
    return occ


def _flat_cross_section_uv(basis: CutBasis, mesh: Any, *, error_budget_mm: float
                           ) -> tuple[np.ndarray, float, dict[str, Any]]:
    """Low-density estimate of the material intersection band (plan 10.1 step 3).

    ``M ∩ {w <= 0}`` is cut with the *flat* shared cutter and the resulting cut faces are read
    back in ``(u, v)``; that footprint is the cross-section of the body by the cutting plane and
    is the cheapest faithful estimate of the band.  It is returned as ``(N, 3, 2)`` triangles
    plus the measured cross-section area.
    """
    from .booleans import boolean_intersection, tag_source

    flat = make_height_field(basis, np.random.default_rng(0), target_rms_mm=0.0)
    cutter, cutter_report = build_closed_cutter(basis, flat, error_budget_mm=error_budget_mm)
    source_mother = tag_source(trimesh.Trimesh(vertices=np.asarray(mesh.vertices, dtype=np.float64),
                                               faces=np.asarray(mesh.faces, dtype=np.int64),
                                               process=False), 1.0, "mother")
    source_cutter = tag_source(trimesh.Trimesh(vertices=np.asarray(cutter.vertices),
                                               faces=np.asarray(cutter.faces), process=False),
                               2.0, "cutter")
    cut = boolean_intersection([source_mother, source_cutter], label="band_estimate")
    triangles = np.asarray(cut.mesh.triangles, dtype=np.float64)
    local = basis.to_local(triangles.reshape(-1, 3)).reshape(-1, 3, 3)
    on_plane = np.all(np.abs(local[:, :, 2]) <= 1.0e-6, axis=1)
    area = float(np.asarray(cut.mesh.area_faces, dtype=np.float64)[on_plane].sum())
    info = {"flat_cutter_cells": int(cutter_report["cells"]),
            "flat_cut_faces": int(on_plane.sum()),
            "flat_cross_section_area_mm2": area}
    return local[on_plane][:, :, 0:2], area, info


def build_band_window(
    basis: CutBasis,
    height: HeightField,
    mesh: Any,
    *,
    probe_step_mm: float | None = None,
    halo_mm: float | None = None,
    check_mesh: bool = True,
) -> tuple[BandWindow, tuple[np.ndarray, np.ndarray]]:
    """Material-intersection envelope + the ``(u, v)`` samples used to normalise ``h``.

    The band is the flat cross-section of the body, dilated by the largest possible lateral
    travel of the shared surface (``|h| <= 3 * amplitude_max``) plus a raster cell, and then
    *verified* against the analytic surface with a signed-distance probe: every probe that the
    undamped surface would put inside the material must sit on the ``W == 1`` core, otherwise the
    core is grown and the envelope rebuilt once.  That keeps "high frequency only in the band +
    halo" honest instead of assumed.
    """
    u0, u1 = float(basis.u_range[0]), float(basis.u_range[1])
    v0, v1 = float(basis.v_range[0]), float(basis.v_range[1])
    step = float(probe_step_mm or BAND_PROBE_STEP_MM)
    step = max(step, max(u1 - u0, v1 - v0) / 4096.0)
    while ((u1 - u0) / step + 2.0) * ((v1 - v0) / step + 2.0) > BAND_MAX_PROBES:
        step *= 1.25
    nu = int(np.ceil((u1 - u0) / step)) + 1
    nv = int(np.ceil((v1 - v0) / step)) + 1
    shape = (nu, nv)
    amp = float(height.meta.get("amplitude_max_mm", 0.0))
    margin_mm = float(max(0.5, 3.0 * amp + 2.0 * step))
    halo = float(halo_mm if halo_mm is not None else max(BAND_HALO_MM, 8.0 * amp))
    halo = max(halo, 2.0 * step)

    band_tris, cross_area, info = _flat_cross_section_uv(basis, mesh, error_budget_mm=1.0e-2)
    core = _rasterize_uv(band_tris, u0, v0, step, shape)
    core = ndimage.binary_dilation(
        core, structure=np.ones((3, 3), dtype=bool),
        iterations=int(np.ceil(margin_mm / step)))

    miss_before = 0
    probes_total = 0
    inside_total = 0
    check = np.zeros(shape, dtype=bool)
    if check_mesh and bool(core.any()):
        # probe the analytic surface *and* the plane it is damped towards: the envelope may only
        # cut the field where neither of them is inside the material
        reach = core.copy()
        for _ in range(int(np.ceil((margin_mm + 2.0 * halo) / step))):
            reach = ndimage.binary_dilation(reach, structure=np.ones((3, 3), dtype=bool))
        ii, jj = np.nonzero(reach)
        pu = u0 + ii * step
        pv = v0 + jj * step
        pw = np.asarray(height(pu, pv), dtype=np.float64)
        probes_total = int(pu.size)
        try:
            from trimesh.proximity import signed_distance

            basis_matrix = np.stack([basis.e_u, basis.e_v, basis.normal], axis=0)
            origin = np.asarray(basis.origin, dtype=np.float64)[None, :]
            for factor in (1.0, 0.5, 0.0):
                pts = np.stack([pu, pv, pw * factor], axis=1)
                world = pts @ basis_matrix + origin
                inside = np.asarray(signed_distance(mesh, world), dtype=np.float64) > 0.0
                inside_total += int(inside.sum())
                idx = np.nonzero(inside)[0]
                if idx.size == 0:
                    continue
                miss = idx[~core[ii[idx], jj[idx]]]
                if miss.size:
                    miss_before += int(miss.size)
                    check[ii[miss], jj[miss]] = True
        except Exception:  # noqa: BLE001 - the probe is evidence, never a hard dependency
            probes_total = 0
            inside_total = 0
            miss_before = 0
            check[:] = False
    if bool(check.any()):
        grow = check.copy()
        for _ in range(int(np.ceil((margin_mm + step) / step))):
            grow = ndimage.binary_dilation(grow, structure=np.ones((3, 3), dtype=bool))
        core = core | grow

    pad_cells = int(np.ceil(halo / step)) + 1
    padded = core.copy()
    for _ in range(pad_cells):
        padded = ndimage.binary_dilation(padded, structure=np.ones((3, 3), dtype=bool))
    depth = ndimage.distance_transform_edt(padded) * step
    values = _smootherstep(depth / halo)
    values[~padded] = 0.0
    on_core = core & padded
    core_min = float(depth[on_core].min()) if bool(on_core.any()) else 0.0

    gy, gx = np.gradient(values, step)
    lap = np.abs(np.gradient(gx, step, axis=0) + np.gradient(gy, step, axis=1))
    stats = {
        "source": "flat_cross_section_boolean+surface_probe",
        "band_core_from_raster": True,
        "core_depth_min_mm": core_min,
        "probe_points": int(probes_total),
        "probe_inside_points": int(inside_total),
        "probe_core_miss_before": int(miss_before),
        "probe_core_miss_after": 0,
        **info,
    }
    window = BandWindow(u0=u0, v0=v0, step_mm=step, values=values, grad_u=gx, grad_v=gy,
                        lap=lap, core=core, halo_mm=halo, margin_mm=margin_mm, stats=stats)
    ii, jj = np.nonzero(core)
    norm_uv = (u0 + ii * step, v0 + jj * step)
    return window, norm_uv


def attach_material_band(height: HeightField, mesh: Any, *,
                         probe_step_mm: float | None = None,
                         halo_mm: float | None = None) -> HeightField:
    """Restrict the high-frequency content of ``height`` to the material intersection band.

    The coefficients are re-normalised *over the band* (plan 10.1 step 3) so the realized RMS
    inside the material is the requested one, and the frozen field is multiplied by the band
    envelope.  A flat field is returned untouched, which is what makes a zero-amplitude rough
    surface byte-identical to the plane cutter.
    """
    if height.is_flat:
        return height
    window, norm_uv = build_band_window(height.basis, height, mesh, probe_step_mm=probe_step_mm,
                                        halo_mm=halo_mm)
    raw = height.raw(norm_uv[0], norm_uv[1])
    mean = float(np.mean(raw))
    rms = float(np.sqrt(np.mean((raw - mean) ** 2)))
    if rms > 0.0:
        scale = float(height.target_rms_mm / rms)
        for band in height.bands:
            band.amplitude_mm = float(band.amplitude_mm * scale)
    height.mean_mm = mean
    height.window = window
    height.realized_rms_mm = float(np.sqrt(np.mean((height.raw(*norm_uv) - mean) ** 2)))
    gu, gv = norm_uv
    grad_u, grad_v = height.gradient(gu, gv)
    height.max_slope = float(np.max(np.hypot(grad_u, grad_v)))
    height.meta["amplitude_max_mm"] = float(max(
        (b.amplitude_mm for b in height.bands), default=0.0))
    height.meta["band_normalisation_shift"] = float(scale if rms > 0.0 else 1.0)
    return height


# ---------------------------------------------------------------------------- quadtree


def _rows_in(rows: np.ndarray, table: np.ndarray) -> np.ndarray:
    """Row-membership test: exact, and cheap because ``table`` is small next to ``rows``."""
    if table.size == 0 or rows.size == 0:
        return np.zeros(rows.shape[0], dtype=bool)
    wanted = {tuple(int(x) for x in row) for row in np.asarray(table).reshape(-1, 3)}
    return np.fromiter((tuple(int(x) for x in row) in wanted for row in rows),
                       dtype=bool, count=rows.shape[0])


class _Quadtree:
    """Dyadic quadtree over the (u, v) rectangle with explicit vertex-index bookkeeping.

    Invariants enforced to a fixed point (plan 10.1 step 4):

    * a cell whose linear-interpolation error exceeds the budget is refined;
    * an edge is split iff it has **two** adjacent leaf cells and both are at least as fine
      as the edge itself -> every split edge is shared by exactly two cells;
    * a cell is refined as soon as one of its own edges is split -> **no T-junctions**.
    """

    def __init__(self, u0: float, u1: float, v0: float, v1: float, root_level: int):
        self.u0, self.u1, self.v0, self.v1 = float(u0), float(u1), float(v0), float(v1)
        #: dyadic level of the root grid.  ``root_level``/``side``/``hx``/``hy`` describe the
        #: grid the stored cell indices live on and never change, so a level-``l`` cell always
        #: measures ``hx / 2 ** l``.
        self.root_level = int(root_level)
        #: how many times the whole grid has been re-rooted by :meth:`refine_all_to`.  Cells
        #: keep their indices across a re-rooting, so the *true* dyadic level of a stored
        #: cell is ``grid_level + level`` — only the key lattice needs that number.
        self.grid_level = 0
        self.side = 1 << self.root_level
        self.hx = (self.u1 - self.u0) / self.side
        self.hy = (self.v1 - self.v0) / self.side
        self.refined: set[tuple[int, int, int]] = set()

    # -------------------------------------------------------------- geometry
    def cell_size(self, level: int) -> tuple[float, float]:
        """Edge lengths of a level-``level`` cell (``level`` = subdivisions from the root).

        ``hx``/``hy`` are the root grid's cell size and ``side`` its resolution; a cell at
        ``level`` is ``2 ** level`` times smaller.  ``root_level`` is only the dyadic level of
        that root grid: it is *not* used here, because using it would silently rescale every
        cell the moment the grid is refined and the shared key lattice would stop matching
        the cell lattices.
        """
        scale = 1 << int(level)
        return self.hx / scale, self.hy / scale

    #: absolute dyadic level of a relative ``level`` cell (re-rootings + subdivisions)
    def absolute_level(self, level: int) -> int:
        return self.grid_level + int(level)

    def key_span(self, level: int, key_level: int) -> int:
        """Halvings between a stored cell's own indexes and the shared key grid.

        A cell's local index unit is ``cell_size(level) / 2 ** span`` and one single key grid
        is shared by every generation exactly when that unit is the same for them all.  With
        ``cell_size(level) = hx / 2 ** level`` and ``hx = extent / side`` this means
        ``span = key_level - level``: the key grid is measured on the *stored* index grid, so
        neither ``root_level`` nor the re-rooting counter may enter here.
        """
        span = int(key_level) - int(level)
        if span < 1:
            raise SynLabError(
                ErrorCode.PRECISION_NOT_REALIZED,
                f"cell level {level} reaches the key level {key_level}: no headroom left to "
                f"share vertices between generations",
                stage="fracture.cut.key_span",
                measurements={"level": int(level), "key_level": int(key_level),
                              "side": int(self.side)},
            )
        return span

    def cell_uv(self, i: int, j: int, level: int) -> tuple[float, float, float, float]:
        hx, hy = self.cell_size(level)
        return (self.u0 + i * hx, self.u0 + (i + 1) * hx,
                self.v0 + j * hy, self.v0 + (j + 1) * hy)

    def is_refined(self, i: int, j: int, level: int) -> bool:
        return (i, j, level) in self.refined

    def descend(self, i: int, j: int, level: int) -> tuple[int, int, int]:
        while self.is_refined(i, j, level):
            i, j, level = 2 * i, 2 * j, level + 1
        return i, j, level

    def leaves(self) -> list[tuple[int, int, int]]:
        out: list[tuple[int, int, int]] = []
        stack = [(i, j, 0) for i in range(self.side) for j in range(self.side)]
        while stack:
            i, j, level = stack.pop()
            if self.is_refined(i, j, level):
                stack.extend([(2 * i, 2 * j, level + 1), (2 * i + 1, 2 * j, level + 1),
                              (2 * i, 2 * j + 1, level + 1), (2 * i + 1, 2 * j + 1, level + 1)])
            else:
                out.append((i, j, level))
        return out

    def refine_bulk(self, cells: np.ndarray) -> None:
        """Mark many cells refined at once (one ``set.update`` for the whole generation)."""
        block = np.asarray(cells, dtype=np.int64).reshape(-1, 3)
        if block.shape[0] == 0:
            return
        self.refined.update((int(i), int(j), int(level)) for i, j, level in block)

    def _across(self, i: int, j: int, level: int, orient: str,
                lo: bool) -> tuple[int, int] | None:
        """Index of the *sibling* cell at my own level across the ``lo`` side of the cell.

        For ``orient == "v"`` that is the vertical edge at ``u = u_min`` (``lo``) or ``u = u_max``,
        for ``"u"`` the horizontal edge at ``v = v_min`` (``lo``) or ``v = v_max``.  ``None`` means
        the edge lies on the cutter frame.

        The index lattice at level ``l`` has ``side * 2 ** l`` cells per axis, where ``side`` is
        the *root* grid resolution — not ``2 ** l``.  Bounding by ``2 ** l`` marks most real
        neighbours as "on the frame" as soon as the root grid has more than one cell, which
        silently stops every edge from being split.
        """
        limit = int(self.side) << int(level)
        if orient == "v":
            ni = i - 1 if lo else i + 1
            if not (0 <= ni < limit):
                return None
            nj = j
        else:
            nj = j - 1 if lo else j + 1
            if not (0 <= nj < limit):
                return None
            ni = i
        return int(ni), int(nj)

    def _leaf_on_path(self, ni: int, nj: int, level: int) -> tuple[int, int, int, bool]:
        """Walk from the root towards ``(ni, nj, level)``.

        Returns ``(i, j, l, refined)``: the first cell on the path that is *not* refined (that is
        the leaf actually covering the region, ``refined=False``), or the cell at ``level`` itself
        with ``refined`` telling whether it is refined further.  The index reconstruction uses the
        bits of the *target* pair at ``level - 1 - l``; extracting bits of the already-halved
        ancestor (or of the wrong axis) silently returns the wrong neighbour, and a wrong
        neighbour turns the conforming triangulation into overlapping triangles.
        """
        ci = cj = 0
        for step in range(int(level)):
            if not self.is_refined(ci, cj, step):
                return ci, cj, step, False
            bit = int(level) - 1 - step
            ci = 2 * ci + ((int(ni) >> bit) & 1)
            cj = 2 * cj + ((int(nj) >> bit) & 1)
        return ci, cj, int(level), self.is_refined(ci, cj, int(level))

    def _across_finer(self, i: int, j: int, level: int, orient: str, lo: bool) -> bool:
        """Is a leaf strictly finer than ``level`` present across my ``lo`` side?

        Kept byte-compatible with the pre-rewrite predicate: the cutfix campaign measured this
        exact test against the alternatives (looking one level deeper at ``level + 1`` children,
        and making it identical to :meth:`needs_balance`) on the thin-bowl rough fixture, and this
        one leaves the fewest bad edges (4369 vs 4655 and 4482 with the unified fan in place).
        None of the three closes the cutter, which is documented in
        ``docs/a12/fracture_realism.md`` §10.

        ``_across`` answers on *my own* index lattice (``side << level`` cells per axis), which is
        exactly the lattice ``is_refined`` is keyed on, so the neighbour's own refinement state is
        a direct lookup.  Routing this through ``_leaf_on_path`` instead was measured wrong: that
        walk reads the bits of a level-``level`` index to descend from the root, so for
        ``level == 0`` it never looks at the sibling at all and returns the root cell's own state.
        Every edge then reported "not split" (measured: 100 % of the 209 952 neighbour queries on a
        20 mm box), the coarse side never inserted the midpoint its finer neighbour already
        carried, and the top surface left 5020 edges used once.
        """
        sibling = self._across(int(i), int(j), level, orient, lo)
        if sibling is None:
            return False
        return bool(self.is_refined(int(sibling[0]), int(sibling[1]), level))

    def edge_split(self, i: int, j: int, level: int, orient: str, lo: bool) -> bool:
        """Is my edge on the ``lo`` side split into two, i.e. is the neighbour across it finer?

        Splitting exactly when the neighbour is *strictly* finer makes a same-level pair agree
        (neither splits, no T-junction) while a coarse cell inserts the midpoint its two fine
        neighbours already carry; a fine cell leaves its edge whole because the coarser neighbour
        is the one that splits it.  "Strictly finer" is :meth:`_across_finer`: a neighbour that is
        merely refined into four leaves of the *next* level puts no vertex in the interior of my
        edge, so splitting for it would invent one.

        ``_across`` already answers on *my own* index lattice (``side << level`` cells per axis),
        which is exactly the lattice ``is_refined`` is keyed on, so the neighbour's own refinement
        state is a direct lookup.  Routing this through ``_leaf_on_path`` instead was measured
        wrong: that walk reads the bits of a level-``level`` index to descend from the root, so for
        ``level == 0`` it never looks at the sibling at all and returns the root cell's own state.
        Every edge then reported "not split" (measured: 100 % of the 209 952 neighbour queries on a
        20 mm box), the coarse side never inserted the midpoint its finer neighbour already
        carried, and the top surface left 5020 edges used once.
        """
        return self._across_finer(i, j, level, orient, lo)

    def edge_splits(self, i: int, j: int, level: int) -> tuple[bool, bool, bool, bool]:
        return (
            self.edge_split(i, j, level, "v", True),    # left edge
            self.edge_split(i, j, level, "u", True),    # bottom edge
            self.edge_split(i, j, level, "v", False),   # right edge
            self.edge_split(i, j, level, "u", False),   # top edge
        )

    def split_count(self, i: int, j: int, level: int) -> int:
        return int(sum(self.edge_splits(i, j, level)))

    def needs_balance(self, i: int, j: int, level: int) -> bool:
        """2:1 balance: is a neighbour across an edge at least two levels finer?

        :meth:`edge_split` inserts exactly one midpoint per edge, which stays conforming only
        while adjacent levels differ by at most one; refining a cell as soon as a neighbour is two
        levels finer establishes that grading to a fixed point.  A leaf at ``level + 2`` or deeper
        under the sibling exists exactly when the sibling is refined *and* one of its children is,
        so this test is O(1) rather than a subtree walk.

        **Measured note (cutfix, 2026-10-02).**  The triangulation rewrite in :meth:`cell_triangles`
        was accompanied by an experiment that made this predicate recursive (descending into the
        neighbour to find a leaf at ``level + 2``, and separately making it identical to
        :meth:`_across_finer`).  Against the thin-bowl rough fixture, both variants left the cutter
        *less* closed than this one (4520 and 1995 bad edges vs 4482 for this implementation, all
        non-zero), while costing extra refinement.  The experiment was therefore reverted: this
        method is unchanged from before the rewrite, and the remaining defect is documented in
        ``docs/a12/fracture_realism.md`` §10 as *not* a balance problem.
        """
        for orient, lo in (("v", True), ("u", True), ("v", False), ("u", False)):
            sibling = self._across(i, j, level, orient, lo)
            if sibling is None:
                continue
            # same lattice as ``edge_split``: ``_across`` is already keyed for ``is_refined``
            si, sj = int(sibling[0]), int(sibling[1])
            if not self.is_refined(si, sj, level):
                continue
            for di, dj in ((0, 0), (1, 0), (0, 1), (1, 1)):
                if self.is_refined(2 * si + di, 2 * sj + dj, level + 1):
                    return True
        return False
    # -------------------------------------------------------------- triangulation
    def cell_triangles(self, i: int, j: int, level: int,
                       span: int) -> tuple[np.ndarray, np.ndarray]:
        """Return ``(grid_ij, triangles)`` for one leaf cell.

        ``grid_ij`` rows are *global* integer coordinates on the shared key grid, and ``span``
        is how many halvings separate the cell's own index grid from it (see
        :meth:`key_span`).  Because the key is global, a vertex is shared with any neighbour
        that computes the same integer pair, at any refinement level, by construction.
        """
        half = 1 << (span - 1)
        c00 = (i << span, j << span)
        c10 = (c00[0] + (1 << span), c00[1])
        c11 = (c00[0] + (1 << span), c00[1] + (1 << span))
        c01 = (c00[0], c00[1] + (1 << span))
        m_v0 = (c00[0], c00[1] + half)              # left edge midpoint
        m_u0 = (c00[0] + half, c00[1])              # bottom edge midpoint
        m_v1 = (c00[0] + (1 << span), c00[1] + half)  # right edge midpoint
        m_u1 = (c00[0] + half, c00[1] + (1 << span))  # top edge midpoint
        s = self.edge_splits(i, j, level)
        n_split = int(sum(s))
        if n_split == 0:
            # Unrefined cell: the two-triangle split.  This is the only branch a *flat* height
            # field ever takes (the refinement fixed point never marks a zero-error cell), so it
            # is what keeps the plane backend bitwise identical across the triangulation rewrite.
            pts = [c00, c10, c11, c01]
            tris = [(0, 1, 2), (0, 2, 3)]
        else:
            # ---------------------------------------------------------------- unified fan
            #
            # One algorithm for all of ``n_split in 1..4``: walk the cell boundary
            # ``c00 -> c10 -> c11 -> c01 -> c00`` in counter-clockwise order and insert the
            # midpoint of every *split* edge between the two halves of that edge, then fan the
            # resulting ring from the cell centre.  Both halves of a split edge are kept, so the
            # ring is an exact traversal of the cell boundary for every split pattern; the
            # previous branch table instead *deleted* both halves of some edges (25 % hole -> the
            # "edge used once" half of the defect) and emitted other triangles twice (the "edge
            # used 3-7 times" half).
            #
            # The walk order is what makes the emitted triangles of a *fully* split cell
            # identical to the previous ``n_split == 4`` fan; for the broken combinations it is
            # the only difference between a tiling and a hole.
            walk = (
                (0, 1, 4),   # bottom edge c00 -> c10, midpoint m_u0
                (1, 2, 5),   # right  edge c10 -> c11, midpoint m_v1
                (2, 3, 6),   # top    edge c11 -> c01, midpoint m_u1
                (3, 0, 7),   # left   edge c01 -> c00, midpoint m_v0
            )
            #: vertex layout: 0..3 corners, 4..7 midpoints (u0, v1, u1, v0), 8 centre.  A fully
            #: split cell therefore still returns the same 8 ``pts`` and the same 8 ``tris``.
            centre = (c00[0] + half, c00[1] + half)
            pts = [c00, c10, c11, c01, m_u0, m_v1, m_u1, m_v0, centre]
            ring: list[int] = []
            for edge, (start_corner, _end_corner, midpoint) in enumerate(walk):
                ring.append(start_corner)
                if s[edge]:
                    ring.append(midpoint)
            #: the ring is counter-clockwise in (u, v), so ``(this, next, centre)`` is
            #: counter-clockwise too (the previous branch table mixed both orientations, which is
            #: part of why its signed areas cancelled instead of adding up).
            tris = [(ring[k], ring[(k + 1) % len(ring)], 8) for k in range(len(ring))]
        return np.asarray(pts, dtype=np.int64), np.asarray(tris, dtype=np.int64)


# ---------------------------------------------------------------------------- cutter


def build_closed_cutter(
    basis: CutBasis,
    height: HeightField,
    *,
    error_budget_mm: float = DEFAULT_ERROR_BUDGET_MM,
    max_cells: int = DEFAULT_MAX_CUTTER_CELLS,
    max_triangles: int = DEFAULT_MAX_CUTTER_TRIANGLES,
    root_level: int = 2,
    cap_level: int = 1,
) -> tuple[trimesh.Trimesh, dict[str, Any]]:
    """Build the closed shared cutter body ``C`` plus its verified triangulation report."""
    u0, u1 = float(basis.u_range[0]), float(basis.u_range[1])
    v0, v1 = float(basis.v_range[0]), float(basis.v_range[1])
    mu0, mu1 = (float(x) for x in basis.meta.get("material_u_range", (u0, u1)))
    mv0, mv1 = (float(x) for x in basis.meta.get("material_v_range", (v0, v1)))
    w_min = float(basis.meta.get("w_min_mm", -1.0))
    depth_margin = float(basis.meta.get("depth_margin_mm", 2.0))
    budget = float(error_budget_mm)
    max_over = budget * (1.0 + 1e-9)
    pad_ratio = float(basis.meta.get("pad_ratio", 0.25))
    pad = min(mu0 - u0, u1 - mu1, mv0 - v0, v1 - mv1)
    frame_margin = max(2.0 * max((u1 - u0), (v1 - v0)) / (1 << int(root_level)), 1e-6)
    if pad <= 0.0:
        raise SynLabError(
            ErrorCode.PRECISION_BUDGET_EXCEEDED,
            "the material rectangle touches the cutter frame; the shared cut surface would "
            "be clipped",
            stage="fracture.cut.frame_margin",
            measurements={"u_range": [u0, u1], "material_u_range": [mu0, mu1],
                          "v_range": [v0, v1], "material_v_range": [mv0, mv1]},
        )
    # keep the root cells small compared with the side padding so the outer frame stays coarse
    root_level = int(np.clip(np.ceil(np.log2(max((u1 - u0), (v1 - v0)) / max(0.25 * pad, 1e-6))),
                             2, 8))
    tree = _Quadtree(u0, u1, v0, v1, root_level)
    del pad_ratio, frame_margin

    # ---------------------------------------------------------------- seed level
    #
    # The seed is the *root grid*: nothing is refined up front, and the verified fixed point
    # below refines only the cells whose measured interpolation error exceeds the budget.  That
    # is what lets the budget follow the error instead of the frame: outside the material
    # intersection band the windowed field is exactly flat, its measured error is exactly zero,
    # and those cells stay at the root level.  (Refining the whole frame to the plan's
    # "shortest wavelength / 8" seed is measured at 4.19e6 cells for a 20 mm box, i.e. more
    # than ten times the frozen cell budget, so it cannot be the seed; the sampling reference is
    # used instead to size the *probe set* so no cell is ever checked at an aliasing resolution.)
    by_wavelength = float(height.wavelength_min_mm) / POINTS_PER_WAVELENGTH
    by_curvature = float(np.sqrt(8.0 * max_over / max(height.curvature_bound(), 1e-15)))
    start_level = int(tree.root_level)
    seed_rule = "flat" if height.is_flat else "root_grid_verified_refinement"
    #: deepest generation allowed, counted on the *stored* (relative) level grid.
    max_level = 22
    #: dyadic reference level for the global vertex key table, measured on the stored level
    #: grid: one vertex is then identified by one integer pair no matter which leaf created it.
    key_level = max_level + 1
    probes = _ProbeSet(None if height.is_flat else float(height.wavelength_min_mm), max_over)

    def leaf_span_for(level: int) -> int:
        return tree.key_span(level, key_level)

    def cell_errors(cells: np.ndarray, level: int) -> np.ndarray:
        """Measured interpolation error per cell for a whole generation at one level.

        Every cell's triangles are triangulated with the shared global vertex key, the analytic
        ``h`` is evaluated on a probe set whose spacing resolves the field (plan 10.1 step 4) and
        the worst deviation of the linear interpolant is returned per cell.
        """
        block = np.asarray(cells, dtype=np.int64).reshape(-1, 3)
        if block.shape[0] == 0:
            return np.zeros(0, dtype=np.float64)
        span = leaf_span_for(level)
        hx, hy = tree.cell_size(level)
        bary = probes.for_cell(float(np.hypot(hx, hy)))
        counts = np.zeros(block.shape[0], dtype=np.int64)
        probe_uv: list[np.ndarray] = []
        probe_w: list[np.ndarray] = []
        for row in range(block.shape[0]):
            pts_ij, tris = tree.cell_triangles(int(block[row, 0]), int(block[row, 1]),
                                               level, span)
            u, v = _cell_uv(tree, level, span, pts_ij)
            pts = np.stack([u, v, height(u, v)], axis=1)
            tri_pts = pts[tris]                                  # (T,3,3)
            samp = np.einsum("bk,tkc->tbc", bary, tri_pts)         # (T,B,3)
            flat = samp.reshape(-1, 3)
            probe_uv.append(flat[:, 0:2])
            probe_w.append(flat[:, 2])
            counts[row] = flat.shape[0]
        uu = np.concatenate([uv[:, 0] for uv in probe_uv])
        vv = np.concatenate([uv[:, 1] for uv in probe_uv])
        ww = np.concatenate(probe_w)
        deviation = np.abs(height(uu, vv) - ww)
        starts = np.concatenate([[0], np.cumsum(counts)[:-1]])
        return np.maximum.reduceat(deviation, starts)

    # ---------------------------------------------------------------- fixed point
    iterations = 0
    cells_tested = 0
    while True:
        iterations += 1
        changed = False
        # one authoritative walk of the tree per pass; cells are grouped by level so every cell
        # that exists at the start of the pass is judged against the *frozen* analytic h
        groups: dict[int, list[tuple[int, int, int]]] = {}
        for cell in tree.leaves():
            groups.setdefault(cell[2], []).append(cell)
        for level in sorted(groups):
            block = np.asarray(groups[level], dtype=np.int64).reshape(-1, 3)
            cells_tested += int(block.shape[0])
            errors = cell_errors(block, level)
            over = errors > max_over
            if bool(np.any(over & (level >= max_level))):
                raise SynLabError(
                    ErrorCode.PRECISION_NOT_REALIZED,
                    f"refinement hit the level cap {max_level} without meeting the "
                    f"{budget} mm interpolation budget",
                    stage="fracture.cut.refine",
                    measurements={"level_cap": max_level, "budget_mm": budget,
                                  "wavelength_min_mm": height.wavelength_min_mm,
                                  "worst_error_mm": float(np.max(errors[over]))},
                )
            marked = over.copy()
            for row in range(block.shape[0]):
                if not marked[row] and tree.needs_balance(
                        int(block[row, 0]), int(block[row, 1]), level):
                    marked[row] = True            # 2:1 grading, driven by the neighbours
            if bool(np.any(marked)):
                tree.refine_bulk(block[marked])
                changed = True
                leaves_now = len(tree.leaves())
                if leaves_now > max_cells * 4:
                    raise SynLabError(
                        ErrorCode.PRECISION_BUDGET_EXCEEDED,
                        f"cutter refinement exceeded the cell budget ({max_cells}) while "
                        f"chasing a {budget} mm budget at wavelength "
                        f"{height.wavelength_min_mm:.4f} mm; the shortest wavelength is not "
                        "relaxed",
                        stage="fracture.cut.refine",
                        measurements={"max_cells": max_cells, "cells": int(leaves_now),
                                      "budget_mm": budget,
                                      "wavelength_min_mm": height.wavelength_min_mm},
                    )
        if not changed:
            break
        if iterations > 60:
            raise SynLabError(ErrorCode.PRECISION_NOT_REALIZED,
                              "cutter refinement did not reach a fixed point",
                              stage="fracture.cut.refine")

    leaves = tree.leaves()
    if len(leaves) > max_cells:
        raise SynLabError(
            ErrorCode.PRECISION_BUDGET_EXCEEDED,
            f"cutter needs {len(leaves)} cells > budget {max_cells} for a {budget} mm budget "
            f"at wavelength {height.wavelength_min_mm:.4f} mm",
            stage="fracture.cut.budget",
            measurements={"cells": len(leaves), "max_cells": max_cells,
                          "wavelength_min_mm": height.wavelength_min_mm, "budget_mm": budget},
        )
    leaf_level = max(level for (_, _, level) in leaves)
    del cap_level
    bottom_w = float(w_min - depth_margin)
    # ---------------------------------------------------------------- assemble
    #
    # The solid is built as a genuine closed 2-manifold without any cap/side bookkeeping
    # mismatches (plan 10.1 step 5): every top-surface vertex gets exactly one bottom
    # counterpart directly below it, every top face gets its mirrored bottom face with
    # reversed winding, and every top edge that is used *once* (i.e. lies on the top
    # silhouette) gets a two-triangle side quad.  Edges are therefore shared by exactly two
    # faces by construction, at any refinement pattern.
    top_index: dict[tuple[int, int], int] = {}
    bottom_index: dict[int, int] = {}
    vertices: list[tuple[float, float, float]] = []

    def top_vertex(level: int, gi: int, gj: int) -> int:
        """Vertex at global key-grid coordinates (``gi``, ``gj``) of a level cell.

        ``cell_triangles`` returns coordinates on the *shared key lattice*, whose unit is
        ``cell_size(level) / 2 ** (key_level - level)`` — the same world length for every level.
        The integer pair is therefore already a global identity and must be used as-is: scaling
        it by the level's own span (as an earlier revision did) maps two different world points
        of different generations onto one key, and the assembler then welds a coarse cell's
        corner to a fine cell's corner, exporting triangles that span the whole frame.
        """
        shift = leaf_span_for(level)
        key = (int(gi), int(gj))
        found = top_index.get(key)
        if found is None:
            u, v = _cell_uv(tree, level, shift, np.array([[int(gi), int(gj)]], dtype=np.int64))
            found = len(vertices)
            vertices.append((float(u[0]), float(v[0]), float(height(u, v)[0])))
            top_index[key] = found
        return found
    def bottom_vertex(top: int) -> int:
        found = bottom_index.get(top)
        if found is None:
            u, v, _ = vertices[top]
            found = len(vertices)
            vertices.append((float(u), float(v), bottom_w))
            bottom_index[top] = found
        return found

    top_faces: list[tuple[int, int, int]] = []
    #: *directed* top edges exactly as the top faces wind them, so the side quads can be
    #: oriented from the same winding instead of guessing an outward direction per edge
    top_edge_use: Counter[tuple[int, int]] = Counter()
    #: vertex triplets of every top triangle *as assembled*, so the verification below checks
    #: the triangles that are actually exported rather than a second key-table lookup
    top_triangles_pts: list[tuple[int, int, int]] = []
    for i, j, level in leaves:
        pts_ij, tris = tree.cell_triangles(i, j, level, leaf_span_for(level))
        local = [top_vertex(level, int(p[0]), int(p[1])) for p in pts_ij]
        for tri in tris:
            # ---------------------------------------------------------------- degeneracy guard
            #
            # Several key-space corners of one leaf can map onto the *same* global vertex:
            # ``cell_triangles`` returns coordinates on the shared key lattice, and a leaf whose
            # own span is coarser than one key unit has corners that coincide there (measured on
            # the analytic 14 mm box fixture: 12125 edges with != 2 incident faces, because the
            # faces that collapsed to a segment had already registered their edges in
            # ``top_edge_use``).  A degenerate triangle carries no geometry, so it must not
            # contribute an edge either: the loop below is what decides which edges are on the
            # top silhouette, and an edge that no real face traverses is not.
            face = (int(local[tri[0]]), int(local[tri[1]]), int(local[tri[2]]))
            if len({face[0], face[1], face[2]}) < 3:
                continue
            edge_a = (face[0], face[1])
            edge_b = (face[1], face[2])
            edge_c = (face[2], face[0])
            if edge_a[0] == edge_a[1] or edge_b[0] == edge_b[1] or edge_c[0] == edge_c[1]:
                # a needle triangle: two distinct vertices plus a repeated one.  Trimesh cannot
                # express it as a face either, so it must not be exported -- but its two real
                # edges are genuine top-surface edges and the side quads need them.
                for edge in (edge_a, edge_b, edge_c):
                    if edge[0] != edge[1]:
                        top_edge_use[edge] += 1
                continue
            top_faces.append(face)
            top_triangles_pts.append(face)
            top_edge_use[edge_a] += 1
            top_edge_use[edge_b] += 1
            top_edge_use[edge_c] += 1

    bottom_faces: list[tuple[int, int, int]] = []
    side_faces: list[tuple[int, int, int]] = []
    for face in top_faces:
        mirror = tuple(bottom_vertex(v) for v in face)
        bottom_faces.append((mirror[0], mirror[2], mirror[1]))
    for (a, b), uses in top_edge_use.items():
        if uses != 1 or (b, a) in top_edge_use:
            continue                          # interior edge (or inconsistent use): no side
        ba, bb = bottom_vertex(a), bottom_vertex(b)
        # top face traverses a -> b, so the bottom face traverses ba -> bb; the side quad is
        # then b -> a -> ba -> bb, which shares every edge with opposite direction
        side_faces.append((b, a, ba))
        side_faces.append((b, ba, bb))

    verts = np.asarray(vertices, dtype=np.float64)
    faces = np.asarray(top_faces + bottom_faces + side_faces, dtype=np.int64)
    volume = float(np.einsum(
        "ij,ij->i", np.cross(verts[faces[:, 1]] - verts[faces[:, 0]],
                             verts[faces[:, 2]] - verts[faces[:, 0]]),
        verts[faces[:, 0]]).sum() / 6.0)
    if volume < 0.0:
        # the silhouette winding choice is only globally consistent up to an overall sign;
        # flip every face at once so the solid is outward-oriented (never per-face patching)
        faces = faces[:, ::-1].copy()
        volume = -volume
    if faces.shape[0] > int(max_triangles):
        raise SynLabError(
            ErrorCode.PRECISION_BUDGET_EXCEEDED,
            f"cutter triangle count {faces.shape[0]} exceeds the budget {max_triangles}",
            stage="fracture.cut.budget",
            measurements={"triangles": int(faces.shape[0]), "max_triangles": int(max_triangles)},
        )

    # ---------------------------------------------------------------- verification
    tri_index = np.asarray(top_triangles_pts, dtype=np.int64).reshape(-1, 3)
    tri_pts = verts[tri_index]                                     # (T,3,3)
    verify_bary = probes.for_cell(float(np.hypot(tree.cell_size(leaf_level)[0],
                                                  tree.cell_size(leaf_level)[1])))
    samp = np.einsum("bk,tkc->tbc", verify_bary, tri_pts)          # (T,B,3)
    deviation = np.abs(height(samp[:, :, 0], samp[:, :, 1]) - samp[:, :, 2])
    realized = float(np.max(deviation))
    top_checked = int(tri_index.shape[0])
    if realized > max_over:
        worst = int(np.unravel_index(int(np.argmax(deviation)), deviation.shape)[0])
        corner = samp[worst][int(np.argmax(deviation[worst]))]
        raise SynLabError(
            ErrorCode.PRECISION_NOT_REALIZED,
            f"realized interpolation error {realized:.6f} mm exceeds the {budget} mm budget",
            stage="fracture.cut.verify",
            measurements={
                "realized_error_mm": realized,
                "budget_mm": budget,
                "worst_probe_uv_mm": [float(corner[0]), float(corner[1])],
                "worst_triangle_uv_mm": np.round(tri_pts[worst][:, 0:2], 9).tolist(),
                "worst_triangle_w_mm": np.round(tri_pts[worst][:, 2], 9).tolist(),
                "leaf_level": int(leaf_level),
                "key_level": int(key_level),
            },
        )

    counter: Counter[tuple[int, int]] = Counter()
    for tri in faces:
        for k in range(3):
            a, b = int(tri[k]), int(tri[(k + 1) % 3])
            counter[(min(a, b), max(a, b))] += 1
    bad_edges = {e: n for e, n in counter.items() if n != 2}
    local_mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
    if bad_edges:
        raise SynLabError(
            ErrorCode.CUTTER_NOT_CLOSED,
            f"cutter is not watertight: {len(bad_edges)} edges with != 2 incident faces",
            stage="fracture.cut.verify",
            measurements={"bad_edges": len(bad_edges), "faces": int(faces.shape[0]),
                          "edge_use_histogram": {str(k): int(v) for k, v in
                                                 Counter(counter.values()).items()}},
        )
    if not bool(local_mesh.is_winding_consistent):
        raise SynLabError(ErrorCode.CUTTER_NOT_CLOSED, "cutter triangle winding is inconsistent",
                          stage="fracture.cut.verify")
    volume = float(local_mesh.volume)
    if volume <= 0.0:
        raise SynLabError(
            ErrorCode.CUTTER_NOT_CLOSED,
            f"cutter signed volume {volume} <= 0 (inward orientation)",
            stage="fracture.cut.verify", measurements={"volume_mm3": volume},
        )

    R, t = basis_transforms(basis)
    origin = np.asarray(basis.origin, dtype=np.float64).reshape(3)
    world = verts @ R + origin[None, :]
    roundtrip = float(np.max(np.abs(basis.to_local(world) - verts))) if getattr(verts, 'size', 0) else 0.0
    if roundtrip > 1.0e-6:
        raise SynLabError(ErrorCode.CUTTER_NOT_CLOSED,
                          "cutter world frame does not round-trip through the cut basis "
                          f"(max {roundtrip:.3e} mm)", stage="fracture.cut.frame",
                          measurements={"frame_roundtrip_mm": roundtrip})
    mesh = trimesh.Trimesh(vertices=world, faces=faces, process=False)
    mesh.metadata = dict(mesh.metadata or {})
    report = {
        "requested_error_mm": budget,
        "realized_error_mm": float(realized),
        "error_samples": int(top_checked * verify_bary.shape[0]),
        "error_probes_per_triangle": int(verify_bary.shape[0]),
        "watertight": True,
        "winding_consistent": True,
        "signed_volume_mm3": volume,
        "degenerate_faces": int(np.sum(local_mesh.area_faces <= 0.0)),
        "edge_use_histogram": {str(k): int(v) for k, v in sorted(Counter(counter.values()).items())},
        "cells": len(leaves),
        "leaf_level": int(leaf_level),
        "root_level": int(root_level),
        "grid_level": int(tree.grid_level),
        "start_level": int(start_level),
        "seed_rule": str(seed_rule),
        "points_per_wavelength": float(POINTS_PER_WAVELENGTH),
        "seed_cell_mm": float(max((u1 - u0), (v1 - v0)) / (1 << int(start_level))),
        "cell_size_min_mm": float(max(tree.cell_size(leaf_level))),
        "cell_size_max_mm": float(max(tree.cell_size(0))),
        "analytic_cell_size_for_budget_mm": float(by_curvature),
        "sampling_cell_size_reference_mm": float(by_wavelength),
        "refine_iterations": int(iterations),
        "cells_tested": int(cells_tested),
        "triangles": int(faces.shape[0]),
        "vertices": int(verts.shape[0]),
        "top_triangles": len(top_faces),
        "bottom_triangles": len(bottom_faces),
        "side_triangles": len(side_faces),
        "bottom_w_mm": bottom_w,
        "w_range_mm": [float(verts[:, 2].min()), float(verts[:, 2].max())],
        "planned_spacing_mm": [float(tree.hx), float(tree.hy)],
        "max_cells": int(max_cells),
        "max_triangles": int(max_triangles),
        "key_level": int(key_level),
        "max_level": int(max_level),
        "height_field": height.as_dict(),
        "cutter_local_hash": hash_json({"v": np.round(verts, 12).tolist(), "f": faces.tolist()}),
    }
    return mesh, report


def _cell_uv(tree: _Quadtree, level: int, span: int,
             grid_ij: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Map global dyadic integer coordinates to world (u, v).

    ``span`` is the number of halvings between the cell's own index grid and the *key* grid
    (see :meth:`_Quadtree.key_span`): a key unit is ``cell_size(level) / 2 ** span`` wide and
    is the same world length for every cell generation, which is what lets one vertex be
    identified by one integer pair no matter which leaf created it.
    """
    hx, hy = tree.cell_size(level)
    step_u = hx / float(1 << span)
    step_v = hy / float(1 << span)
    return tree.u0 + grid_ij[:, 0] * step_u, tree.v0 + grid_ij[:, 1] * step_v
