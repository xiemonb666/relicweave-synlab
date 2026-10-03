"""Recession bases, ROI weights and surface-height models for the P01–P08 operators.

Every field built here is *non-negative* and *frozen*: it is a pure function of the clean
source body, the ROI definition and the frozen basis payload.  The only-remove-material
update is ``M_t = {x : d0(x) + t·α(x)·b(x) ≤ 0}`` with ``t ≥ 0``, ``α ∈ [0,1]`` the ROI
weight and ``b ≥ 0`` the recession base (plan 12.1, 30.7).

The ROI itself is *damage-side* information: it comes from clean geometry only and is
never used as an input feature (plan 30.7 for P02).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy import ndimage
from scipy.spatial import cKDTree

from ..errors import ErrorCode, SynLabError
from ..schemas.runtime import ORIGIN_INTERFACE, ORIGIN_MOTHER_SURFACE

# ---------------------------------------------------------------------------- ROI selection


def _face_attr(mesh, fragment, name: str) -> np.ndarray | None:
    """Face attribute from the fragment or the mesh metadata (same length as faces)."""
    arrays = dict((getattr(mesh, "metadata", None) or {}).get("face_attr_arrays") or {})
    if name in arrays and len(arrays[name]) == len(mesh.faces):
        return np.asarray(arrays[name])
    if fragment is not None:
        for attr in ("face_origin_kind", "face_interface_id", "face_source_tri", "face_side"):
            if attr.endswith(name.replace("origin_kind", "origin_kind")):
                value = getattr(fragment, attr, None)
                if value is not None and len(value) == len(mesh.faces) and attr == name:
                    return np.asarray(value)
    if fragment is not None and name == "origin_kind":
        value = getattr(fragment, "face_origin_kind", None)
        if value is not None and len(value) == len(mesh.faces):
            return np.asarray(value)
    if fragment is not None and name == "interface_id":
        value = getattr(fragment, "face_interface_id", None)
        if value is not None and len(value) == len(mesh.faces):
            return np.asarray(value)
    return None


def face_channel(mesh, fragment, name: str) -> np.ndarray | None:
    """Public name of :func:`_face_attr`: one face channel of the source, or ``None``.

    ``None`` means *the channel is absent* - it never means "zero everywhere"; readers that need
    a default must choose one explicitly (see ``physical.api._source_face_channels``).
    """
    return _face_attr(mesh, fragment, name)


def roi_faces(mesh, fragment, spec: dict[str, Any] | None) -> tuple[np.ndarray, dict[str, Any]]:
    """Select the ROI faces (int interface / outer wall / explicit plane / normal cone)."""
    spec = dict(spec or {"kind": "interface"})
    kind = str(spec.get("kind", "interface"))
    normals = np.asarray(mesh.face_normals, dtype=np.float64)
    centroids = np.asarray(mesh.triangles_center, dtype=np.float64)
    n_faces = len(mesh.faces)

    if kind == "interface":
        interface_id = _face_attr(mesh, fragment, "interface_id")
        origin_kind = _face_attr(mesh, fragment, "origin_kind")
        if interface_id is not None and int(interface_id.max(initial=-1)) >= 0:
            ids = np.flatnonzero(np.asarray(interface_id) >= 0)
            return ids, {"roi_kind": "interface", "roi_source": "face_interface_id",
                         "n_faces": int(len(ids))}
        if origin_kind is not None and int((np.asarray(origin_kind) == ORIGIN_INTERFACE).sum()) > 0:
            ids = np.flatnonzero(np.asarray(origin_kind) == ORIGIN_INTERFACE)
            return ids, {"roi_kind": "interface", "roi_source": "face_origin_kind",
                         "n_faces": int(len(ids))}
        raise SynLabError(
            ErrorCode.NA_NOT_APPLICABLE,
            "fragment carries no interface face attribute (face_interface_id/face_origin_kind); "
            "P-axis interface operators are not applicable to this body",
            stage="physical.roi")

    if kind == "normal_cone":
        direction = np.asarray(spec["direction"], dtype=np.float64).reshape(3)
        direction = direction / max(np.linalg.norm(direction), 1e-12)
        cos_min = float(spec.get("cos_min", 0.5))
        ids = np.flatnonzero(normals @ direction >= cos_min)
        return ids, {"roi_kind": "normal_cone", "roi_source": "declared_direction",
                     "direction": [float(v) for v in direction], "cos_min": cos_min,
                     "n_faces": int(len(ids))}

    if kind == "plane":
        point = np.asarray(spec["point"], dtype=np.float64).reshape(3)
        normal = np.asarray(spec["normal"], dtype=np.float64).reshape(3)
        normal = normal / max(np.linalg.norm(normal), 1e-12)
        band = float(spec.get("band_mm", 0.5))
        cos_min = float(spec.get("cos_min", 0.5))
        dist = np.abs((centroids - point[None, :]) @ normal)
        ids = np.flatnonzero((dist <= band) & (normals @ normal >= cos_min))
        return ids, {"roi_kind": "plane", "roi_source": "declared_plane", "band_mm": band,
                     "cos_min": cos_min, "n_faces": int(len(ids))}

    if kind == "outer":
        origin_kind = _face_attr(mesh, fragment, "origin_kind")
        if origin_kind is not None:
            ids = np.flatnonzero(np.asarray(origin_kind) == ORIGIN_MOTHER_SURFACE)
            if len(ids):
                return ids, {"roi_kind": "outer", "roi_source": "face_origin_kind",
                             "n_faces": int(len(ids))}
        direction = np.asarray(spec.get("direction", [0.0, 0.0, 1.0]), dtype=np.float64)
        direction = direction / max(np.linalg.norm(direction), 1e-12)
        cos_min = float(spec.get("cos_min", 0.25))
        ids = np.flatnonzero(normals @ direction >= cos_min)
        return ids, {"roi_kind": "outer", "roi_source": "declared_outward_direction",
                     "direction": [float(v) for v in direction], "cos_min": cos_min,
                     "n_faces": int(len(ids))}

    if kind == "all":
        return np.arange(n_faces), {"roi_kind": "all", "roi_source": "declared", "n_faces": n_faces}

    raise SynLabError(ErrorCode.SCHEMA_INVALID, f"unknown ROI kind {kind!r}", stage="physical.roi")


def interface_contact(mesh, fragment, roi: dict[str, Any] | None, body, *,
                      eps_mm: float = 2e-3, density_mm: float = 0.5) -> dict[str, float]:
    """Residual contact area of the original interface patch after damage (measured).

    ``body`` is the damaged solid; a source interface sample still counts as contact when
    the damaged body occupies the point just *inside* the original surface.
    """
    face_ids, info = roi_faces(mesh, fragment, roi)
    anchors = roi_anchor_points(mesh, face_ids, density_mm=density_mm)
    face_normals = np.asarray(mesh.face_normals, dtype=np.float64)[face_ids]
    centroids = np.asarray(mesh.triangles_center, dtype=np.float64)[face_ids]
    from scipy.spatial import cKDTree as _KDTree

    _dist, idx = _KDTree(anchors).query(centroids, workers=1) if len(centroids) else (None, None)
    # per-anchor outward normal: nearest ROI face normal (anchors lie on ROI faces)
    tri = np.asarray(mesh.vertices)[np.asarray(mesh.faces)[face_ids]]
    nearest = _KDTree(np.vstack([tri.reshape(-1, 3)])).query(anchors, workers=1)[1] // 3
    normals = face_normals[np.clip(nearest, 0, len(face_normals) - 1)]
    area = float(np.sum(np.asarray(mesh.area_faces, dtype=np.float64)[face_ids]))
    from .sdf import scene_for

    inside = anchors - normals * float(eps_mm)
    occ = scene_for(body).occupancy(inside)
    residual = float(occ.mean()) if len(occ) else 0.0
    return {
        "roi": info, "interface_area_mm2": area, "anchors": float(len(anchors)),
        "residual_fraction": residual, "lost_fraction": 1.0 - residual,
        "residual_area_mm2": residual * area, "lost_area_mm2": (1.0 - residual) * area,
    }


def roi_anchor_points(mesh, face_ids: np.ndarray, *, density_mm: float = 0.5) -> np.ndarray:
    """Dense sample points over the ROI faces (used for distance/weight fields)."""
    faces = np.asarray(mesh.faces)[np.asarray(face_ids, dtype=np.int64)]
    if len(faces) == 0:
        raise SynLabError(ErrorCode.NA_NOT_APPLICABLE, "empty ROI face set", stage="physical.roi")
    triangles = np.asarray(mesh.vertices)[faces]
    max_edge = float(np.max(np.linalg.norm(triangles[:, 1] - triangles[:, 0], axis=1))) if len(faces) else 1.0
    steps = int(np.clip(np.ceil(max_edge / max(density_mm, 1e-3)), 2, 12))
    bary = []
    for i in range(steps + 1):
        for j in range(steps + 1 - i):
            bary.append([i / steps, j / steps, 1.0 - (i + j) / steps])
    bary = np.asarray(bary, dtype=np.float64)
    pts = np.einsum("bk,fkc->fbc", bary, triangles).reshape(-1, 3)
    return np.unique(np.round(pts, 9), axis=0)


# ---------------------------------------------------------------------------- weights


def smoothstep(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def roi_weight(points: np.ndarray, anchors: np.ndarray, *, core_mm: float = 0.0,
               halo_mm: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    """ROI weight α(x) ∈ [0,1] (1 inside ``core_mm``, 0 beyond ``halo_mm``) + anchor distance."""
    halo_mm = max(float(halo_mm), 1e-6)
    core_mm = float(min(max(core_mm, 0.0), halo_mm * 0.999))
    tree = cKDTree(np.asarray(anchors, dtype=np.float64))
    dist, _ = tree.query(np.asarray(points, dtype=np.float64), workers=1)
    alpha = smoothstep((halo_mm - dist) / max(halo_mm - core_mm, 1e-9))
    return alpha, dist


# ---------------------------------------------------------------------------- height models


@dataclass
class InterfaceFrame:
    """Own outward-height frame of a (near-planar) interface patch (plan 12.2 P01)."""

    origin: np.ndarray
    e_u: np.ndarray
    e_v: np.ndarray
    normal: np.ndarray
    u_range: tuple[float, float]
    v_range: tuple[float, float]
    normal_scatter_deg: float = 0.0
    frame_id: str = ""

    @classmethod
    def fit(cls, points: np.ndarray, normals: np.ndarray | None = None) -> "InterfaceFrame":
        pts = np.asarray(points, dtype=np.float64)
        origin = pts.mean(axis=0)
        if normals is not None and len(normals):
            nrm = np.asarray(normals, dtype=np.float64)
            mean_dir = nrm.mean(axis=0)
            if np.linalg.norm(mean_dir) < 1e-9:
                mean_dir = np.array([0.0, 0.0, 1.0])
            normal = mean_dir / np.linalg.norm(mean_dir)
            scatter = float(np.degrees(np.arccos(np.clip(
                nrm @ normal / np.maximum(np.linalg.norm(nrm, axis=1), 1e-12), -1.0, 1.0))).max())
        else:
            centred = pts - origin[None, :]
            _u, _s, vt = np.linalg.svd(centred, full_matrices=False)
            normal = vt[-1]
            scatter = 0.0
        seed = np.array([1.0, 0.0, 0.0]) if abs(normal[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
        e_u = np.cross(normal, seed)
        e_u = e_u / np.linalg.norm(e_u)
        e_v = np.cross(normal, e_u)
        local = np.stack([(pts - origin) @ e_u, (pts - origin) @ e_v], axis=1)
        return cls(origin=origin, e_u=e_u, e_v=e_v, normal=normal,
                   u_range=(float(local[:, 0].min()), float(local[:, 0].max())),
                   v_range=(float(local[:, 1].min()), float(local[:, 1].max())),
                   normal_scatter_deg=scatter)

    def to_uvw(self, points: np.ndarray) -> np.ndarray:
        p = np.asarray(points, dtype=np.float64) - self.origin[None, :]
        return np.stack([p @ self.e_u, p @ self.e_v, p @ self.normal], axis=1)

    def as_dict(self) -> dict[str, Any]:
        return {"origin_mm": [float(v) for v in self.origin], "normal": [float(v) for v in self.normal],
                "e_u": [float(v) for v in self.e_u], "e_v": [float(v) for v in self.e_v],
                "u_range_mm": [float(v) for v in self.u_range],
                "v_range_mm": [float(v) for v in self.v_range],
                "normal_scatter_deg": float(self.normal_scatter_deg)}


@dataclass
class HeightModel:
    """Height lattice ``f(u, v)`` of a single-valued interface patch."""

    frame: InterfaceFrame
    u0: float
    v0: float
    du: float
    dv: float
    f: np.ndarray
    valid: np.ndarray
    w_spread_mm: np.ndarray
    multi_valued_mm: float = 2.0
    source: str = "roi_faces"

    @property
    def shape(self) -> tuple[int, int]:
        return self.f.shape

    @property
    def cell_area_mm2(self) -> float:
        return float(self.du * self.dv)

    @property
    def coverage(self) -> float:
        return float(self.valid.mean()) if self.valid.size else 0.0

    @property
    def multi_valued_cells(self) -> int:
        return int(np.sum(self.valid & (self.w_spread_mm > self.multi_valued_mm)))

    @property
    def single_valued_fraction(self) -> float:
        n_valid = int(self.valid.sum())
        return 1.0 - (self.multi_valued_cells / n_valid) if n_valid else 0.0

    def sample(self, points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Nearest-cell sample of the height map at world points (hit mask returned)."""
        uvw = self.frame.to_uvw(points)
        iu = np.rint((uvw[:, 0] - self.u0) / self.du).astype(np.int64)
        iv = np.rint((uvw[:, 1] - self.v0) / self.dv).astype(np.int64)
        ok = (iu >= 0) & (iu < self.shape[0]) & (iv >= 0) & (iv < self.shape[1])
        out = np.zeros(len(uvw), dtype=np.float64)
        hit = np.zeros(len(uvw), dtype=bool)
        if ok.any():
            ii, jj = iu[ok], iv[ok]
            valid = self.valid[ii, jj]
            out[ok] = np.where(valid, self.f[ii, jj], 0.0)
            hit[ok] = valid
        return out, hit

    def lowpass(self, sigma_cells: float) -> np.ndarray:
        """Masked Gaussian low-pass ``g`` of the height map (normalised convolution)."""
        weight = self.valid.astype(np.float64)
        filled = np.where(self.valid, self.f, 0.0)
        sigma = max(float(sigma_cells), 1e-3)
        num = ndimage.gaussian_filter(filled, sigma=sigma, mode="nearest")
        den = ndimage.gaussian_filter(weight, sigma=sigma, mode="nearest")
        return np.where(den > 1e-9, num / np.maximum(den, 1e-9), filled)

    def high_frequency_rms(self, sigma_cells: float, mask: np.ndarray | None = None) -> float:
        g = self.lowpass(sigma_cells)
        use = self.valid if mask is None else (self.valid & mask)
        if not use.any():
            return 0.0
        return float(np.sqrt(np.mean((self.f[use] - g[use]) ** 2)))

    def static_target(self, sigma_cells: float) -> tuple[np.ndarray, dict[str, Any]]:
        """``g + c`` with ``c = min(f - g)`` so that ``target ≤ f`` cell-wise (plan 12.2)."""
        g = self.lowpass(sigma_cells)
        use = self.valid
        if not use.any():
            raise SynLabError(ErrorCode.NA_NOT_APPLICABLE, "empty height lattice",
                              stage="physical.height")
        diff = self.f[use] - g[use]
        c = float(diff.min())
        target = g + c
        recession = self.f - target
        info = {
            "sigma_cells": float(sigma_cells), "sigma_mm": float(sigma_cells * 0.5 * (self.du + self.dv)),
            "c_mm": c, "recession_max_mm": float(recession[use].max()),
            "recession_mean_mm": float(recession[use].mean()),
            "target_le_f": bool(np.all(recession[use] >= -1e-12)),
            "hf_rms_before_mm": float(np.sqrt(np.mean(diff ** 2))),
            "cells": int(use.sum()),
        }
        return target, info


def height_model(points: np.ndarray, normals: np.ndarray | None = None, *, cell_mm: float,
                 frame: InterfaceFrame | None = None, multi_valued_mm: float = 2.0,
                 source: str = "roi_faces") -> HeightModel:
    """Build the own-outward height lattice from interface samples."""
    pts = np.asarray(points, dtype=np.float64)
    if len(pts) < 8:
        raise SynLabError(ErrorCode.NA_NOT_APPLICABLE,
                          f"interface patch has only {len(pts)} samples; height model needs >= 8",
                          stage="physical.height")
    frame = frame or InterfaceFrame.fit(pts, normals)
    uvw = frame.to_uvw(pts)
    u_min, u_max = float(uvw[:, 0].min()), float(uvw[:, 0].max())
    v_min, v_max = float(uvw[:, 1].min()), float(uvw[:, 1].max())
    nu = int(np.clip(np.ceil((u_max - u_min) / cell_mm) + 1, 8, 160))
    nv = int(np.clip(np.ceil((v_max - v_min) / cell_mm) + 1, 8, 160))
    du = max((u_max - u_min) / max(nu - 1, 1), 1e-6)
    dv = max((v_max - v_min) / max(nv - 1, 1), 1e-6)
    iu = np.clip(np.rint((uvw[:, 0] - u_min) / du).astype(np.int64), 0, nu - 1)
    iv = np.clip(np.rint((uvw[:, 1] - v_min) / dv).astype(np.int64), 0, nv - 1)
    f = np.full((nu, nv), -np.inf, dtype=np.float64)
    lo = np.full((nu, nv), np.inf, dtype=np.float64)
    np.maximum.at(f, (iu, iv), uvw[:, 2])
    np.minimum.at(lo, (iu, iv), uvw[:, 2])
    valid = np.isfinite(f)
    spread = np.where(valid, f - lo, 0.0)
    f = np.where(valid, f, 0.0)
    return HeightModel(frame=frame, u0=u_min, v0=v_min, du=du, dv=dv, f=f, valid=valid,
                       w_spread_mm=spread, multi_valued_mm=float(multi_valued_mm), source=source)


# ---------------------------------------------------------------------------- frozen smooth fields


@dataclass
class FourierField:
    """Frozen smooth field in [0,1] over mm coordinates (nested level sets by threshold)."""

    amplitudes: np.ndarray
    frequencies: np.ndarray
    phases: np.ndarray
    scale_mm: float
    floor: float = 0.0
    field_id: str = ""

    @classmethod
    def sample_frozen(cls, rng: np.random.Generator, *, scale_mm: float, n_components: int = 8,
                      field_id: str = "") -> "FourierField":
        n = int(n_components)
        amplitudes = rng.normal(size=n)
        amplitudes /= max(np.abs(amplitudes).sum(), 1e-9)
        directions = rng.normal(size=(n, 3))
        directions /= np.maximum(np.linalg.norm(directions, axis=1, keepdims=True), 1e-9)
        frequencies = directions * (2.0 * np.pi / max(scale_mm, 1e-6))
        phases = rng.uniform(0.0, 2.0 * np.pi, size=n)
        return cls(amplitudes=amplitudes, frequencies=frequencies, phases=phases,
                   scale_mm=float(scale_mm), field_id=field_id)

    def raw(self, points: np.ndarray) -> np.ndarray:
        pts = np.asarray(points, dtype=np.float64)
        phase = pts @ self.frequencies.T + self.phases[None, :]
        values = np.cos(phase) @ self.amplitudes
        return values / max(np.abs(self.amplitudes).sum(), 1e-9)

    def __call__(self, points: np.ndarray) -> np.ndarray:
        """Normalised field in [0,1]; ``{x : field(x) < q}`` is nested in ``q``."""
        return np.clip(0.5 * (self.raw(points) + 1.0), 0.0, 1.0)

    def payload(self) -> dict[str, Any]:
        return {"amplitudes": self.amplitudes, "frequencies": self.frequencies,
                "phases": self.phases, "scale_mm": float(self.scale_mm), "field_id": self.field_id}

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "FourierField":
        return cls(amplitudes=np.asarray(payload["amplitudes"], dtype=np.float64),
                   frequencies=np.asarray(payload["frequencies"], dtype=np.float64),
                   phases=np.asarray(payload["phases"], dtype=np.float64),
                   scale_mm=float(payload["scale_mm"]), field_id=str(payload.get("field_id", "")))


def threshold_for_fraction(values: np.ndarray, fraction: float, *, tail: str = "legacy") -> float:
    """Return a scalar quantile cutoff while preserving the historical default semantics.

    ``tail="legacy"`` preserves the original ``quantile(1 - fraction)`` behavior, including its
    historical boundary cutoffs.  New callers should state ``lower`` or ``upper`` explicitly.
    Ties can still make a threshold level set include more samples than requested; area-weighted
    appearance masks should use :func:`rank_mask_for_area_fraction` instead.
    """
    vals = np.asarray(values, dtype=np.float64).ravel()
    if vals.size == 0:
        return 0.0
    if tail not in ("legacy", "lower", "upper"):
        raise ValueError("tail must be 'legacy', 'lower' or 'upper'")
    fraction = float(np.clip(fraction, 0.0, 1.0))
    if tail == "legacy":
        if fraction <= 0:
            return float(vals.min()) - 1e-9
        if fraction >= 1:
            return float(vals.max()) + 1e-9
        return float(np.quantile(vals, 1.0 - fraction))
    if tail == "lower":
        if fraction <= 0:
            return float(vals.min()) - 1e-9
        if fraction >= 1:
            return float(vals.max()) + 1e-9
        return float(np.quantile(vals, fraction))
    if fraction <= 0:
        return float(vals.max()) + 1e-9
    if fraction >= 1:
        return float(vals.min()) - 1e-9
    return float(np.quantile(vals, 1.0 - fraction))


def rank_mask_for_area_fraction(values: np.ndarray, fraction: float, area_weights: np.ndarray,
                                *, tail: str = "lower") -> tuple[np.ndarray, dict[str, Any]]:
    """Select a nested stable rank prefix closest to a requested physical-area fraction.

    Ties are resolved by original texel order.  Since a texel cannot be split, the selected area
    can differ from the target; both realized area fraction and signed/absolute quantization error
    are returned instead of claiming an exact coverage.  ``tail`` makes score direction explicit.
    """
    raw_values = np.asarray(values)
    scores = np.asarray(values, dtype=np.float64).ravel()
    weights = np.asarray(area_weights, dtype=np.float64).ravel()
    if scores.size != weights.size:
        raise ValueError("rank values and area weights must have the same number of texels")
    try:
        requested = float(fraction)
    except (TypeError, ValueError) as exc:
        raise ValueError("fraction must be a finite number in [0, 1]") from exc
    if not np.isfinite(requested) or requested < 0.0 or requested > 1.0:
        raise ValueError("fraction must be a finite number in [0, 1]")
    if tail not in ("lower", "upper"):
        raise ValueError("tail must be 'lower' or 'upper'")
    if not np.all(np.isfinite(scores)):
        raise ValueError("rank values must be finite")
    if not np.all(np.isfinite(weights)) or np.any(weights <= 0.0):
        raise ValueError("area weights must be finite and strictly positive")
    if scores.size == 0:
        if requested != 0.0:
            raise ValueError("a nonzero fraction cannot be selected from an empty rank field")
        return np.zeros(raw_values.shape, dtype=bool), {
            "selection": "stable_area_rank_prefix_nearest_target",
            "tail": tail,
            "requested_fraction": requested,
            "total_area": 0.0,
            "target_area": 0.0,
            "selected_area": 0.0,
            "realized_fraction": 0.0,
            "signed_fraction_error": 0.0,
            "absolute_fraction_error": 0.0,
            "quantized": False,
            "boundary_score": None,
            "boundary_tie_split": False,
        }

    total = float(np.sum(weights, dtype=np.float64))
    if not np.isfinite(total) or total <= 0.0:
        raise ValueError("total area weight must be finite and positive")
    target = requested * total
    if requested <= 0.0:
        selected_count = 0
    elif requested >= 1.0:
        selected_count = int(scores.size)
    else:
        order = np.argsort(scores if tail == "lower" else -scores, kind="stable")
        cumulative = np.concatenate(([0.0], np.cumsum(weights[order], dtype=np.float64)))
        upper_prefix = min(int(np.searchsorted(cumulative, target, side="left")),
                           int(scores.size))
        lower_prefix = max(0, upper_prefix - 1)
        lower_error = abs(float(cumulative[lower_prefix]) - target)
        upper_error = abs(float(cumulative[upper_prefix]) - target)
        # On an exact tie prefer the smaller prefix.  Prefix choice remains monotone as the
        # requested target grows, which makes level masks nested on one frozen rank field.
        selected_count = lower_prefix if lower_error <= upper_error else upper_prefix

    order = np.argsort(scores if tail == "lower" else -scores, kind="stable")
    mask_flat = np.zeros(scores.size, dtype=bool)
    mask_flat[order[:selected_count]] = True
    selected = float(np.sum(weights[mask_flat], dtype=np.float64))
    realized = selected / total
    signed_error = realized - requested
    boundary_score = (float(scores[order[selected_count - 1]]) if selected_count else
                      (float(scores[order[0]]) if scores.size else None))
    next_score = (float(scores[order[selected_count]])
                  if 0 < selected_count < scores.size else None)
    return mask_flat.reshape(raw_values.shape), {
        "selection": "stable_area_rank_prefix_nearest_target",
        "tail": tail,
        "requested_fraction": requested,
        "total_area": total,
        "target_area": target,
        "selected_area": selected,
        "realized_fraction": realized,
        "signed_fraction_error": signed_error,
        "absolute_fraction_error": abs(signed_error),
        "quantized": bool(selected != target),
        "boundary_score": boundary_score,
        "boundary_tie_split": bool(next_score is not None and boundary_score == next_score),
    }


# ---------------------------------------------------------------------------- edge fields


def edge_face_pairs(mesh) -> np.ndarray:
    """Edge -> (face_a, face_b) table aligned with ``mesh.edges_unique``.

    trimesh 5.x changed ``Mesh.edges_face`` from the unique-edge face pairs ``(E, 2)`` to
    directed-edge face indices ``(3F,)``.  Rebuilding the table from ``edges_unique_inverse``
    keeps the legacy semantics without relying on either layout.
    """
    n_edges = len(np.asarray(mesh.edges_unique, dtype=np.int64))
    pairs = np.full((n_edges, 2), -1, dtype=np.int64)
    if n_edges == 0:
        return pairs
    faces = np.asarray(mesh.faces, dtype=np.int64)
    inverse = getattr(mesh, "edges_unique_inverse", None)
    if inverse is None:  # very old trimesh: derive from directed edges
        directed = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]], axis=0)
        _, inverse = np.unique(np.sort(directed, axis=1), axis=0, return_inverse=True)
        inverse = np.asarray(inverse, dtype=np.int64).ravel()
    else:
        inverse = np.asarray(inverse, dtype=np.int64).ravel()
    face_of = np.repeat(np.arange(faces.shape[0], dtype=np.int64), 3)
    order = np.argsort(inverse, kind="stable")
    inv_sorted = inverse[order]
    face_sorted = face_of[order]
    counts = np.bincount(inv_sorted, minlength=n_edges)
    starts = np.cumsum(counts) - counts
    valid = counts > 0
    pairs[valid, 0] = face_sorted[starts[valid]]
    two = counts >= 2
    pairs[two, 1] = face_sorted[starts[two] + 1]
    return pairs


def convex_edges(mesh, *, min_angle_deg: float = 25.0, face_ids: np.ndarray | None = None) -> np.ndarray:
    """Edge segments whose dihedral angle is convex beyond ``min_angle_deg`` (plan 12.2 P02)."""
    edges = np.asarray(mesh.edges_unique, dtype=np.int64)
    if len(edges) == 0:
        return np.zeros((0, 2), dtype=np.int64)
    normals = np.asarray(mesh.face_normals, dtype=np.float64)
    edge_faces = edge_face_pairs(mesh)
    allowed = None if face_ids is None else set(int(v) for v in np.asarray(face_ids).ravel())
    keep = []
    for index, pair in enumerate(edge_faces):
        a, b = int(pair[0]), int(pair[1])
        if a < 0 or b < 0:
            continue
        if allowed is not None and a not in allowed and b not in allowed:
            continue
        cosang = float(np.clip(normals[a] @ normals[b], -1.0, 1.0))
        angle = float(np.degrees(np.arccos(cosang)))
        if angle < min_angle_deg:
            continue
        # convex when the neighbouring face centre lies behind this face's plane
        va, vb = edges[index]
        edge_dir = np.asarray(mesh.vertices[va] - mesh.vertices[vb], dtype=np.float64)
        if np.linalg.norm(edge_dir) < 1e-12:
            continue
        convex = float((np.asarray(mesh.triangles_center[b]) - np.asarray(mesh.triangles_center[a]))
                       @ normals[a]) < 0.0
        if convex:
            keep.append(index)
    return edges[np.asarray(keep, dtype=np.int64)] if keep else np.zeros((0, 2), dtype=np.int64)


def edge_sample_points(mesh, edges: np.ndarray, *, density_mm: float = 0.3) -> np.ndarray:
    """Dense samples along edge polylines (used for the edge-distance field)."""
    if len(edges) == 0:
        return np.zeros((0, 3), dtype=np.float64)
    verts = np.asarray(mesh.vertices, dtype=np.float64)
    segments = verts[np.asarray(edges, dtype=np.int64)]
    lengths = np.linalg.norm(segments[:, 1] - segments[:, 0], axis=1)
    out = []
    for seg, length in zip(segments, lengths):
        steps = int(np.clip(np.ceil(length / max(density_mm, 1e-3)), 1, 24))
        t = np.linspace(0.0, 1.0, steps + 1)[:, None]
        out.append(seg[0][None, :] * (1 - t) + seg[1][None, :] * t)
    return np.unique(np.round(np.concatenate(out, axis=0), 9), axis=0)


def bump_profile(rho: np.ndarray, radius: float) -> np.ndarray:
    """``(1 - (rho/r)^2)^2``: value and first derivative vanish at ``rho = r`` (plan 15.4)."""
    r = max(float(radius), 1e-9)
    x = np.clip(np.asarray(rho, dtype=np.float64) / r, 0.0, 1.0)
    return (1.0 - x ** 2) ** 2


def dihedral_angles_at_edges(mesh, edges: np.ndarray) -> np.ndarray:
    """Material-side dihedral angle (deg) of the given edges; defaults to 90° when unknown."""
    edge_faces = edge_face_pairs(mesh)
    normals = np.asarray(mesh.face_normals, dtype=np.float64)
    angles = np.full(len(edges), 90.0, dtype=np.float64)
    for index, edge in enumerate(np.asarray(edges, dtype=np.int64)):
        key = tuple(sorted((int(edge[0]), int(edge[1]))))
        lookup = getattr(mesh, "_edge_lookup_cache", None)
        if lookup is None:
            lookup = {}
            for ei, pair in enumerate(np.asarray(mesh.edges_unique, dtype=np.int64)):
                lookup[tuple(sorted((int(pair[0]), int(pair[1]))))] = ei
            mesh._edge_lookup_cache = lookup
        ei = lookup.get(key)
        if ei is None:
            continue
        a, b = int(edge_faces[ei][0]), int(edge_faces[ei][1])
        if a < 0 or b < 0:
            continue
        cosang = float(np.clip(normals[a] @ normals[b], -1.0, 1.0))
        angles[index] = float(np.degrees(np.arccos(cosang)))
    return angles


def field_stats(values: np.ndarray, mask: np.ndarray | None = None) -> dict[str, float]:
    vals = np.asarray(values, dtype=np.float64)
    if mask is not None:
        vals = vals[np.asarray(mask, dtype=bool)]
    if vals.size == 0:
        return {"n": 0.0, "min": 0.0, "max": 0.0, "mean": 0.0, "rms": 0.0, "p95": 0.0}
    return {"n": float(vals.size), "min": float(vals.min()), "max": float(vals.max()),
            "mean": float(vals.mean()), "rms": float(np.sqrt(np.mean(vals ** 2))),
            "p95": float(np.percentile(vals, 95))}
