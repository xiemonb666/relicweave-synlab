"""Measurement of a realized fracture surface: roughness, correlation length, ridge density.

Everything here measures the **realized discrete geometry** (the cutter top surface that both
sides of the event consumed, and the interface faces the boolean actually produced), never the
analytic field the model asked for.  That distinction is the point: the parameters in
:mod:`synlab.fracture.morphology` are the *request*, these numbers are the *realization*, and the
report publishes both.

Definitions used (stated because "Ra" is ambiguous otherwise):

* the conchoidal form is removed first by a least-squares plane over the measured band, so ``Ra``
  and ``Rz`` are roughness and the removed part is reported separately as ``waviness_rms_mm``;
* ``Ra`` is the area-weighted mean absolute residual;
* ``Rz`` is the mean, over evaluation cells of ``RZ_CELL_MM``, of the ``0.5/99.5`` percentile
  band of the residual inside the cell — the discrete-mesh analogue of the ISO 4287 ten-point
  height, which on a triangulated surface would otherwise be dominated by mesh resolution
  (``Rt`` reports the ``0.1/99.9`` band for the extreme value);
* the correlation length is the radial lag at which the mask-normalised autocorrelation of the
  binned residual drops to ``1/e``, with the within-bin noise variance removed;
* the ridge density counts crest lines per mm of arc on circles around the fracture origin.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

import numpy as np

__all__ = [
    "RZ_CELL_MM",
    "top_surface_samples",
    "detrend_plane",
    "amplitude_statistics",
    "correlation_length",
    "ridge_density",
    "measure_cutter_surface",
    "measure_interface_surface",
    "conjugate_profile_consistency",
]

#: evaluation-cell size (mm) for the ten-point height ``Rz``.
RZ_CELL_MM = 2.5
#: residual bin size (mm) used for the autocorrelation and the ridge circles.
BIN_STEP_MM = 0.08
_EPS = 1.0e-12


# ---------------------------------------------------------------------------- sampling


def _basis_matrix(basis: Any) -> np.ndarray:
    return np.stack([basis.e_u, basis.e_v, basis.normal], axis=0)


def top_surface_samples(mesh: Any, basis: Any, *, n_samples: int = 400_000,
                        rng: np.random.Generator | None = None) -> dict[str, np.ndarray]:
    """Area-weighted samples of the cutter's *top* surface in the cut basis ``(u, v, w)``.

    The top surface is identified structurally, not by a threshold: the closed cutter has exactly
    one flat bottom at ``w = bottom_w``, so a face with no vertex on that plane is a top face and
    a face with two or three such vertices is a side or bottom face.
    """
    rng = rng or np.random.default_rng(0)
    verts = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    R = _basis_matrix(basis)
    local = (verts - np.asarray(basis.origin, dtype=np.float64)[None, :]) @ R.T
    w = local[:, 2]
    at_bottom = np.abs(w - float(w.min())) <= 1.0e-9
    counts = at_bottom[faces].sum(axis=1)
    top = np.nonzero(counts == 0)[0]
    if top.size == 0:
        top = np.nonzero(counts <= 1)[0]
    triangles = local[faces[top]][:, :, 0:3]
    return _sample_triangles(triangles, int(n_samples), rng,
                            extra={"total_area_mm2": _triangle_area(triangles)})


def _triangle_area(triangles: np.ndarray) -> float:
    tri = np.asarray(triangles, dtype=np.float64).reshape(-1, 3, 3)
    if tri.shape[0] == 0:
        return 0.0
    return float(np.sum(np.linalg.norm(
        np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1) * 0.5))


def _sample_triangles(triangles: np.ndarray, n_samples: int, rng: np.random.Generator,
                      *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Area-weighted uniform samples of a local-frame triangle soup."""
    tri = np.asarray(triangles, dtype=np.float64).reshape(-1, 3, 3)
    areas = np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]),
                           axis=1) * 0.5 if tri.shape[0] else np.zeros(0)
    keep = areas > 0.0
    tri, areas = tri[keep], areas[keep]
    out: dict[str, Any] = {"area_mm2": areas, "total_area_mm2": float(areas.sum())}
    out.update(extra or {})
    if tri.shape[0] == 0 or n_samples <= 0:
        empty = np.zeros(0, dtype=np.float64)
        out.update({"u": empty, "v": empty, "w": empty})
        return out
    pick = rng.choice(tri.shape[0], size=int(n_samples), p=areas / float(areas.sum()))
    chosen = tri[pick]
    u1 = rng.random(int(n_samples))
    u2 = rng.random(int(n_samples))
    flip = u1 + u2 > 1.0
    u1[flip], u2[flip] = 1.0 - u1[flip], 1.0 - u2[flip]
    pts = (chosen[:, 0] + (chosen[:, 1] - chosen[:, 0]) * u1[:, None]
           + (chosen[:, 2] - chosen[:, 0]) * u2[:, None])
    out.update({"u": pts[:, 0].copy(), "v": pts[:, 1].copy(), "w": pts[:, 2].copy()})
    return out


def triangle_vertices_local(mesh: Any, basis: Any, faces: Sequence[int]) -> np.ndarray:
    """Vertices (world) of the given faces, expressed in the cut basis."""
    verts = np.asarray(mesh.vertices, dtype=np.float64)
    ids = np.asarray(list(faces), dtype=np.int64)
    ids = ids[(ids >= 0) & (ids < np.asarray(mesh.faces).shape[0])]
    if ids.size == 0:
        return np.zeros((0, 3), dtype=np.float64)
    pts = verts[np.asarray(mesh.faces, dtype=np.int64)[ids].reshape(-1)]
    R = _basis_matrix(basis)
    return (pts - np.asarray(basis.origin, dtype=np.float64)[None, :]) @ R.T


# ---------------------------------------------------------------------------- amplitude


def detrend_plane(u: np.ndarray, v: np.ndarray, w: np.ndarray,
                  weights: np.ndarray | None = None) -> dict[str, Any]:
    """Remove the best-fit plane (form) and return the residual (roughness)."""
    u = np.asarray(u, dtype=np.float64).reshape(-1)
    v = np.asarray(v, dtype=np.float64).reshape(-1)
    w = np.asarray(w, dtype=np.float64).reshape(-1)
    if weights is None:
        weights = np.ones_like(w)
    weights = np.asarray(weights, dtype=np.float64).reshape(-1)
    design = np.stack([np.ones_like(u), u, v], axis=1)
    sw = np.sqrt(np.maximum(weights, 0.0))
    coef, *_rest = np.linalg.lstsq(design * sw[:, None], w * sw, rcond=None)
    plane = design @ coef
    residual = w - plane
    waviness = float(np.sqrt(np.average(plane ** 2, weights=weights))
                     - np.average(plane, weights=weights) ** 2)
    return {"coef": coef, "plane": plane, "residual": residual,
            "waviness_rms_mm": float(np.sqrt(max(waviness, 0.0)))}


def amplitude_statistics(u: np.ndarray, v: np.ndarray, residual: np.ndarray,
                         *, cell_mm: float = RZ_CELL_MM,
                         weights: np.ndarray | None = None) -> dict[str, Any]:
    """Area-weighted ``Ra`` / ``Rq`` / ``Rz`` / ``Rt`` of a detrended residual."""
    u = np.asarray(u, dtype=np.float64).reshape(-1)
    v = np.asarray(v, dtype=np.float64).reshape(-1)
    r = np.asarray(residual, dtype=np.float64).reshape(-1)
    if r.size == 0:
        return {"Ra_mm": 0.0, "Rq_mm": 0.0, "Rz_mm": 0.0, "Rz_cells": 0, "Rt_mm": 0.0,
                "samples": 0}
    if weights is None:
        weights = np.ones_like(r)
    weights = np.asarray(weights, dtype=np.float64).reshape(-1)
    total = float(weights.sum())
    ra = float(np.sum(np.abs(r) * weights) / max(total, _EPS))
    rq = float(np.sqrt(np.sum(r ** 2 * weights) / max(total, _EPS)))
    cell = max(float(cell_mm), 1.0e-3)
    gi = np.floor((u - u.min()) / cell).astype(np.int64)
    gj = np.floor((v - v.min()) / cell).astype(np.int64)
    key = gi * (int(gj.max()) + 1) + gj
    order = np.argsort(key, kind="stable")
    key_sorted = key[order]
    r_sorted = r[order]
    w_sorted = weights[order]
    starts = np.flatnonzero(np.r_[True, key_sorted[1:] != key_sorted[:-1]])
    ends = np.r_[starts[1:], key_sorted.size]
    heights = []
    for a, b in zip(starts, ends):
        if b - a < 3:
            continue
        seg = r_sorted[a:b]
        ww = w_sorted[a:b]
        if float(ww.sum()) <= 0.0:
            continue
        heights.append(float(np.percentile(seg, 99.5) - np.percentile(seg, 0.5)))
    rz = float(np.mean(heights)) if heights else 0.0
    return {"Ra_mm": ra, "Rq_mm": rq, "Rz_mm": rz, "Rz_cells": len(heights),
            "Rt_mm": float(np.percentile(r, 99.9) - np.percentile(r, 0.1)),
            "samples": int(r.size)}


# ---------------------------------------------------------------------------- correlation


def _bin_raster(u: np.ndarray, v: np.ndarray, r: np.ndarray, step_mm: float,
                bounds: tuple[float, float, float, float] | None = None,
                max_bins: int = 4_000_000
                ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    u0, u1, v0, v1 = bounds if bounds else (float(u.min()), float(u.max()),
                                           float(v.min()), float(v.max()))
    step_mm = float(step_mm)
    while (np.ceil((u1 - u0) / step_mm) + 1) * (np.ceil((v1 - v0) / step_mm) + 1) > max_bins:
        step_mm *= 1.25
    nu = int(np.ceil((u1 - u0) / step_mm)) + 1
    nv = int(np.ceil((v1 - v0) / step_mm)) + 1
    nu, nv = max(nu, 2), max(nv, 2)
    gi = np.clip(((u - u0) / step_mm).astype(np.int64), 0, nu - 1)
    gj = np.clip(((v - v0) / step_mm).astype(np.int64), 0, nv - 1)
    flat = gi * nv + gj
    count = np.bincount(flat, minlength=nu * nv).astype(np.float64)
    total = np.bincount(flat, weights=r, minlength=nu * nv)
    total_sq = np.bincount(flat, weights=r ** 2, minlength=nu * nv)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(count > 0, total / np.maximum(count, 1.0), 0.0)
    return (mean.reshape(nu, nv), count.reshape(nu, nv), total.reshape(nu, nv),
            total_sq.reshape(nu, nv), np.array([u0, v0, step_mm]))


def correlation_length(u: np.ndarray, v: np.ndarray, residual: np.ndarray, *,
                       step_mm: float = BIN_STEP_MM) -> dict[str, Any]:
    """Correlation length (mm) of the residual from its mask-normalised autocorrelation.

    The within-bin noise variance is estimated from the samples and removed from lag 0, otherwise
    a sparsely sampled raster would report a correlation length biased towards the bin size.
    """
    mean, count, _total, total_sq, _meta = _bin_raster(u, v, residual, step_mm)
    mask = count > 0
    if int(mask.sum()) < 16:
        return {"correlation_length_mm": 0.0, "anisotropy": 0.0, "bins": int(mask.sum()),
                "step_mm": float(step_mm), "note": "too few occupied bins"}
    n_in = count[mask]
    within = float(np.sum(total_sq[mask] - count[mask] * mean[mask] ** 2))
    noise_var = within / max(float(n_in.sum()), _EPS)
    z = np.where(mask, mean, 0.0)
    m = mask.astype(np.float64)
    signal_var = float(np.mean(z[mask] ** 2) - noise_var)
    if signal_var <= 0.0:
        return {"correlation_length_mm": 0.0, "anisotropy": 0.0, "bins": int(mask.sum()),
                "step_mm": float(step_mm), "noise_var_mm2": noise_var,
                "note": "signal variance is not above the binned noise floor"}
    fz = np.fft.rfft2(z)
    fm = np.fft.rfft2(m)
    num = np.fft.irfft2(fz * np.conj(fz), s=z.shape)
    den = np.fft.irfft2(fm * np.conj(fm), s=z.shape)
    ac = np.where(den > 1.0, num / np.maximum(den, _EPS), 0.0)
    ac = ac / signal_var
    du = np.fft.fftfreq(z.shape[0], d=step_mm) * z.shape[0] * step_mm
    dv = np.fft.fftfreq(z.shape[1], d=step_mm) * z.shape[1] * step_mm
    lag = np.hypot(du[:, None], dv[None, :])
    max_lag = 0.5 * min(z.shape[0], z.shape[1]) * step_mm
    shells = np.arange(step_mm, max_lag, step_mm)
    profile = []
    for radius in shells:
        shell = (lag >= radius - 0.5 * step_mm) & (lag < radius + 0.5 * step_mm)
        if int(shell.sum()) < 4:
            continue
        profile.append((float(radius), float(np.mean(ac[shell]))))
    length = 0.0
    for radius, value in profile:
        if value <= 1.0 / np.e:
            length = float(radius)
            break
    else:
        if profile:
            length = float(profile[-1][0])
    # axial profile along u and v for the anisotropy ratio
    axial_u = float(np.mean(ac[1:min(8, z.shape[0]), 0])) if z.shape[0] > 1 else 0.0
    axial_v = float(np.mean(ac[0, 1:min(8, z.shape[1])])) if z.shape[1] > 1 else 0.0
    anis = float(abs(axial_u - axial_v) / max(abs(axial_u), abs(axial_v), _EPS))
    return {"correlation_length_mm": length, "anisotropy": anis, "bins": int(mask.sum()),
            "step_mm": float(step_mm), "noise_var_mm2": float(noise_var),
            "signal_var_mm2": float(signal_var),
            "profile": [[round(r, 4), round(v_, 6)] for r, v_ in profile[:64]]}


# ---------------------------------------------------------------------------- ridges


def ridge_density(u: np.ndarray, v: np.ndarray, residual: np.ndarray,
                  origin_uv: Sequence[float], radii_mm: Iterable[float], *,
                  step_mm: float = BIN_STEP_MM, samples: int = 1440) -> dict[str, Any]:
    """Crest-line density (lines per mm of arc) on circles around the fracture origin."""
    mean, count, _t, _t2, meta = _bin_raster(u, v, residual, step_mm)
    u0, v0, step = float(meta[0]), float(meta[1]), float(meta[2])
    mask = count > 0
    origin = np.asarray(origin_uv, dtype=np.float64).reshape(2)
    out: list[dict[str, Any]] = []
    from scipy.signal import find_peaks

    for radius in radii_mm:
        radius = float(radius)
        if radius <= 0.0:
            continue
        theta = np.linspace(0.0, 2.0 * np.pi, int(samples), endpoint=False)
        pu = origin[0] + radius * np.cos(theta)
        pv = origin[1] + radius * np.sin(theta)
        gi = np.floor((pu - u0) / step).astype(np.int64)
        gj = np.floor((pv - v0) / step).astype(np.int64)
        inside = (gi >= 0) & (gi < mean.shape[0] - 1) & (gj >= 0) & (gj < mean.shape[1] - 1)
        if int(inside.sum()) < 0.5 * theta.size:
            continue
        prof = np.full(theta.size, np.nan, dtype=np.float64)
        prof[inside] = mean[gi[inside], gj[inside]]
        filled = ~np.isnan(prof)
        if int(filled.sum()) < 8:
            continue
        # close the circle: resample the valid arc onto a contiguous run if needed
        if not bool(filled.all()):
            idx = np.flatnonzero(filled)
            prof = prof[idx]
        z = prof - float(np.mean(prof))
        scale = float(np.std(z))
        if scale <= 1.0e-12:
            continue
        peaks, props = find_peaks(z, prominence=0.35 * scale)
        crest = peaks[z[peaks] > 0.0]
        arc = 2.0 * np.pi * radius * (prof.size / float(samples))
        _ = props
        out.append({
            "radius_mm": radius,
            "arc_mm": float(arc),
            "ridges": int(crest.size),
            "lines_per_mm": float(crest.size / max(arc, _EPS)),
            "crest_height_rms_mm": float(np.sqrt(np.mean(z[crest] ** 2))) if crest.size else 0.0,
            "profile_rms_mm": float(scale),
        })
    densities = [row["lines_per_mm"] for row in out]
    return {"circles": out,
            "lines_per_mm_mean": float(np.mean(densities)) if densities else 0.0,
            "lines_per_mm_max": float(np.max(densities)) if densities else 0.0}


# ---------------------------------------------------------------------------- combined


def _stats_from_samples(samples: dict[str, Any], params: Any, *, bin_step_mm: float,
                        rz_cell_mm: float, band_samples: int | None = None,
                        extra: dict[str, Any] | None = None) -> dict[str, Any]:
    u, v, w = samples["u"], samples["v"], samples["w"]
    if u.size < 64:
        return {"samples": int(u.size), "note": "fewer than 64 samples"}
    detrend = detrend_plane(u, v, w)
    residual = detrend["residual"]
    amplitude = amplitude_statistics(u, v, residual, cell_mm=rz_cell_mm)
    correlation = correlation_length(u, v, residual, step_mm=bin_step_mm)
    origin = tuple(params.origin_uv_mm)
    mirror = float(params.mirror_radius_mm)
    mist = float(params.mist_radius_mm)
    radii = [max(mirror * 1.2, 0.5), max(mist, mirror * 1.5), max(3.0 * mirror, 3.0),
             max(6.0 * mirror, 6.0), max(12.0 * mirror, 12.0)]
    ridges = ridge_density(u, v, residual, origin, radii, step_mm=bin_step_mm)
    du = u - origin[0]
    dv = v - origin[1]
    radius = np.hypot(du, dv)
    zones: dict[str, Any] = {}
    for name, selector in (("mirror", radius < mirror),
                           ("mist", (radius >= mirror) & (radius < mist)),
                           ("hackle", radius >= mist)):
        if int(selector.sum()) < 32:
            zones[name] = {"samples": int(selector.sum()), "Ra_mm": None, "Rq_mm": None}
            continue
        stats = amplitude_statistics(u[selector], v[selector], residual[selector],
                                     cell_mm=rz_cell_mm)
        zones[name] = {"samples": int(selector.sum()), "Ra_mm": stats["Ra_mm"],
                       "Rq_mm": stats["Rq_mm"], "Rz_mm": stats["Rz_mm"]}
    out = {
        "samples": int(u.size),
        "band_samples": int(band_samples if band_samples is not None else u.size),
        "measured_area_mm2": float(samples["total_area_mm2"]),
        "form": {"waviness_rms_mm": detrend["waviness_rms_mm"],
                 "plane_coef": [float(x) for x in detrend["coef"]]},
        "roughness": amplitude,
        "correlation": correlation,
        "ridges": ridges,
        "zones": zones,
        "Ra_mm": amplitude["Ra_mm"], "Rq_mm": amplitude["Rq_mm"],
        "Rz_mm": amplitude["Rz_mm"], "Rt_mm": amplitude["Rt_mm"],
        "correlation_length_mm": correlation["correlation_length_mm"],
        "ridge_lines_per_mm": ridges["lines_per_mm_mean"],
        "waviness_rms_mm": detrend["waviness_rms_mm"],
    }
    out.update(extra or {})
    return out


def measure_interface_surface(fragments: Iterable[Any], basis: Any, params: Any, *,
                              n_samples: int = 400_000, bin_step_mm: float = BIN_STEP_MM,
                              rz_cell_mm: float = RZ_CELL_MM,
                              seed: int = 20261001) -> dict[str, Any]:
    """Measure the fracture face *as delivered*: the interface faces of the produced fragments.

    This is the downstream number — a neighbour-piece search sees the fragment mesh, not the
    cutter — so it is reported next to the cutter measurement.
    """
    from ..schemas.runtime import ORIGIN_AMBIGUOUS, ORIGIN_INTERFACE

    rng = np.random.default_rng(int(seed) + 1)
    triangles: list[np.ndarray] = []
    faces_total = 0
    for fragment in fragments:
        origin = np.asarray(fragment.face_origin_kind)
        ids = np.nonzero((origin == ORIGIN_INTERFACE) | (origin == ORIGIN_AMBIGUOUS))[0]
        if ids.size == 0:
            continue
        faces_total += int(ids.size)
        local = triangle_vertices_local(fragment.mesh, basis, ids)
        triangles.append(local.reshape(-1, 3, 3))
    if not triangles:
        return {"samples": 0, "note": "no interface faces in the result"}
    soup = np.concatenate(triangles, axis=0)
    samples = _sample_triangles(soup, int(n_samples), rng)
    return _stats_from_samples(samples, params, bin_step_mm=bin_step_mm,
                               rz_cell_mm=rz_cell_mm,
                               extra={"interface_faces": int(faces_total)})


def measure_cutter_surface(mesh: Any, basis: Any, params: Any, *, window: Any = None,
                           n_samples: int = 400_000, bin_step_mm: float = BIN_STEP_MM,
                           rz_cell_mm: float = RZ_CELL_MM,
                           seed: int = 20261001) -> dict[str, Any]:
    """Full realized-surface measurement of one cutter: form, roughness, correlation, ridges.

    With ``window`` given (the frozen material-band envelope) the samples are restricted to the
    band core, i.e. exactly the part of the shared surface that lies inside the material.  Without
    that restriction the cutter's own flat frame — which is orders of magnitude larger than the
    fracture face — would dilute every amplitude statistic towards zero.
    """
    rng = np.random.default_rng(int(seed))
    samples = top_surface_samples(mesh, basis, n_samples=int(n_samples), rng=rng)
    u, v, w = samples["u"], samples["v"], samples["w"]
    if u.size == 0:
        return {"samples": 0, "note": "cutter has no top surface triangles"}
    band_samples = int(u.size)
    if window is not None:
        core = np.asarray(window.is_exactly_one(u, v), dtype=bool)
        u, v, w = u[core], v[core], w[core]
    samples = {**samples, "u": u, "v": v, "w": w}
    return _stats_from_samples(samples, params, bin_step_mm=bin_step_mm,
                               rz_cell_mm=rz_cell_mm, band_samples=band_samples)


# ---------------------------------------------------------------------------- conjugation


def conjugate_profile_consistency(fragments: Iterable[Any], patches: Iterable[Any], basis: Any,
                                  *, step_mm: float = BIN_STEP_MM,
                                  max_faces_per_side: int = 4000) -> dict[str, Any]:
    """Conjugation of the two fracture faces: same surface, mirrored outward normals.

    Both sides of one shared cut carry the *same* discrete cutter surface, so binning the two
    sides' interface faces onto one common ``(u, v)`` raster and comparing the bin means is a
    direct test of conjugacy: the correlation must be ``~1`` and the residual RMS must be at the
    boolean round-off level.  Per-patch gap / normal statistics and the measured A/B areas are
    reported next to it.
    """
    by_id = {f.fragment_id: f for f in fragments}
    rows: list[dict[str, Any]] = []
    all_da: list[np.ndarray] = []
    all_db: list[np.ndarray] = []
    for patch in patches:
        fa = by_id.get(patch.fragment_a)
        fb = by_id.get(patch.fragment_b)
        if fa is None or fb is None:
            continue
        faces_a = np.asarray(patch.meta.get("faces_a", []), dtype=np.int64)[:max_faces_per_side]
        faces_b = np.asarray(patch.meta.get("faces_b", []), dtype=np.int64)[:max_faces_per_side]
        pa = triangle_vertices_local(fa.mesh, basis, faces_a)
        pb = triangle_vertices_local(fb.mesh, basis, faces_b)
        row: dict[str, Any] = {
            "interface_id": int(patch.interface_id),
            "fragment_a": patch.fragment_a, "fragment_b": patch.fragment_b,
            "area_mm2": float(patch.area_mm2),
            "area_a_mm2": float(patch.meta.get("area_a_mm2", 0.0)),
            "area_b_mm2": float(patch.meta.get("area_b_mm2", 0.0)),
            "area_rel_error": float(patch.meta.get("area_rel_error", 0.0)),
            "gap_p95_mm": float(patch.gap_p95_mm),
            "gap_max_mm": float(patch.meta.get("gap_max_mm", 0.0)),
            "normal_angle_p95_deg": float(patch.normal_angle_p95_deg),
            "vertex_identity_ratio": float(patch.meta.get("vertex_identity_ratio", 0.0)),
            "nearest_p95_mm": float(patch.meta.get("nearest_p95_mm", 0.0)),
            "samples": int(patch.sample_points_a.shape[0]),
        }
        if pa.shape[0] and pb.shape[0]:
            row.update(_raster_agreement(pa, pb, step_mm=step_mm))
            if patch.sample_points_a.shape[0]:
                all_da.append(np.asarray(patch.sample_points_a, dtype=np.float64))
                all_db.append(np.asarray(patch.sample_points_b, dtype=np.float64))
        rows.append(row)
    gap_all = 0.0
    if all_da:
        a = np.concatenate(all_da, axis=0)
        b = np.concatenate(all_db, axis=0)
        gap_all = float(np.percentile(np.linalg.norm(a - b, axis=1), 95))
    correlated = [row for row in rows if row.get("profile_correlation") is not None]
    return {
        "patches": rows,
        "patch_count": len(rows),
        "conjugate_gap_p95_mm": gap_all,
        "profile_correlation_min": (min(row["profile_correlation"] for row in correlated)
                                    if correlated else None),
        "profile_correlation_mean": (float(np.mean([row["profile_correlation"]
                                                    for row in correlated]))
                                     if correlated else None),
        "profile_rms_diff_mm_max": (float(np.max([row["profile_rms_diff_mm"]
                                                  for row in correlated]))
                                    if correlated else None),
        "area_rel_error_max": max((row["area_rel_error"] for row in rows), default=0.0),
        "gap_p95_mm_max": max((row["gap_p95_mm"] for row in rows), default=0.0),
        "normal_angle_p95_deg_max": max((row["normal_angle_p95_deg"] for row in rows), default=0.0),
        "measured_area_mm2": float(sum(row["area_mm2"] for row in rows)),
    }


def _raster_agreement(pa: np.ndarray, pb: np.ndarray, *, step_mm: float) -> dict[str, Any]:
    """Bin two point clouds onto one raster and compare the shared occupied bins."""
    both = np.concatenate([pa, pb], axis=0)
    lo = both[:, 0:2].min(axis=0)
    hi = both[:, 0:2].max(axis=0)
    span = np.maximum(hi - lo, 1.0e-6)
    nu = int(np.clip(np.ceil(span[0] / step_mm) + 1, 2, 2048))
    nv = int(np.clip(np.ceil(span[1] / step_mm) + 1, 2, 2048))
    su = span[0] / (nu - 1)
    sv = span[1] / (nv - 1)

    def raster(points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        gi = np.clip(((points[:, 0] - lo[0]) / su).astype(np.int64), 0, nu - 1)
        gj = np.clip(((points[:, 1] - lo[1]) / sv).astype(np.int64), 0, nv - 1)
        flat = gi * nv + gj
        count = np.bincount(flat, minlength=nu * nv).astype(np.float64)
        total = np.bincount(flat, weights=points[:, 2], minlength=nu * nv)
        mean = np.where(count > 0, total / np.maximum(count, 1.0), np.nan)
        return mean, count

    ma, ca = raster(pa)
    mb, cb = raster(pb)
    shared = (ca > 0) & (cb > 0)
    if int(shared.sum()) < 8:
        return {"profile_bins": int(shared.sum()), "profile_correlation": None,
                "profile_rms_diff_mm": None}
    za = ma[shared]
    zb = mb[shared]
    za = za - float(np.mean(za))
    zb = zb - float(np.mean(zb))
    denom = float(np.linalg.norm(za) * np.linalg.norm(zb))
    correlation = float(np.dot(za, zb) / denom) if denom > _EPS else None
    return {"profile_bins": int(shared.sum()), "profile_correlation": correlation,
            "profile_rms_diff_mm": float(np.sqrt(np.mean((ma[shared] - mb[shared]) ** 2)))}
