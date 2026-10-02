"""Observation quality estimates (OBS_EST) -- plan 14.2, 30.2 stage 9.

Every entry returned by :func:`estimate_quality` carries its own ``valid`` flag, its
``source`` (``OBS_EST`` / ``MANUAL_OBS`` / ``SENSOR_SIM``) and the ``estimator_version``
that produced it.  Ground-truth quality (clean surface area, true blur, exact hole
geometry) is **never** prefilled into these fields: it may only be attached separately as
an ``ORACLE`` comparison by the caller, and is then labelled as such.
"""

from __future__ import annotations

from typing import Any, Iterable

import numpy as np

from ..errors import ErrorCode, SynLabError
from ..roles import SOURCE_OBS_EST

#: Version of the OBS_EST estimator bundle.  Any change invalidates downstream caches.
OBS_EST_VERSION = "obs_est.v1"


def _entry(value: float, *, unit: str, source: str = SOURCE_OBS_EST,
           valid: bool = True, note: str = "") -> dict[str, Any]:
    return {
        "value": float(value),
        "unit": unit,
        "source_kind": source,
        "source_ref": f"{OBS_EST_VERSION}",
        "valid": bool(valid),
        "estimator_version": OBS_EST_VERSION,
        "note": note,
        "oracle": False,
    }


def blur_metric(image: np.ndarray) -> float:
    """Variance of the Laplacian on the luminance of an 8-bit or float image.

    Higher is sharper.  This is a monotone blur proxy, not an MTF measurement: the value
    is only comparable within one estimator version and one image size.
    """
    import cv2

    arr = np.asarray(image)
    if arr.ndim == 3:
        if arr.dtype == np.uint8:
            gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        else:
            gray = arr[..., :3].mean(axis=2)
    else:
        gray = arr
    if gray.dtype != np.uint8:
        gray = np.clip(gray.astype(np.float32) * 255.0, 0, 255).astype(np.uint8)
    if gray.size == 0:
        return 0.0
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def exposure_clip_metrics(image: np.ndarray, mask: np.ndarray | None = None
                          ) -> tuple[float, float, float]:
    """Fraction of saturated highlights, crushed shadows and the mean level."""
    arr = np.asarray(image)
    scale = 255.0 if arr.dtype == np.uint8 else 1.0
    data = arr.astype(np.float64) / scale
    if data.ndim == 3:
        data = data[..., :3]
    if mask is not None:
        sel = np.asarray(mask, dtype=bool)
        if sel.shape == data.shape[:2] and sel.any():
            data = data[sel]
        else:
            data = data.reshape(-1, data.shape[-1])
    flat = data.reshape(-1) if data.ndim <= 1 else data.reshape(-1, data.shape[-1])
    if flat.size == 0:
        return 0.0, 0.0, 0.0
    over = float(np.mean(flat >= 0.995))
    under = float(np.mean(flat <= 0.005))
    return over, under, float(np.mean(flat))


def estimate_quality(obs: Any, *, mask: np.ndarray | None = None) -> dict[str, Any]:
    """Estimate observation quality from the observed data only.

    Accepts an :class:`~synlab.schemas.runtime.ObservationResult` or a single
    :class:`~synlab.schemas.runtime.ObsView`.  Returns a flat mapping of
    ``OBS_EST`` entries plus a ``groups`` summary; nothing here reads truth.
    """
    views = []
    points = None
    point_valid = None
    if hasattr(obs, "views"):
        views = list(obs.views)
        points = getattr(obs, "points", None)
        point_valid = getattr(obs, "point_valid", None)
        route = str(getattr(obs, "route", "unknown"))
        scale_valid = bool(getattr(obs, "scale_valid", False))
        fused_mesh = getattr(obs, "fused_mesh", None)
    elif hasattr(obs, "rgb"):
        views = [obs]
        route = "single_view"
        scale_valid = False
        fused_mesh = None
    else:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          "estimate_quality expects an ObservationResult or ObsView",
                          stage="observe.quality.estimate_quality")

    out: dict[str, Any] = {}
    blurs: list[float] = []
    overs: list[float] = []
    unders: list[float] = []
    means: list[float] = []
    coverage: list[float] = []
    roi_cover: list[float] = []
    hole_ratios: list[float] = []
    for view in views:
        rgb = np.asarray(view.rgb)
        dep = np.asarray(view.depth_z)
        dep_valid = np.isfinite(dep) & (dep > 0)
        blurs.append(blur_metric(rgb))
        over, under, mean = exposure_clip_metrics(rgb)
        overs.append(over)
        unders.append(under)
        means.append(mean)
        coverage.append(float(np.mean(dep_valid)) if dep.size else 0.0)
        roi = getattr(view, "roi", None)
        if roi is not None and np.asarray(roi).size:
            roi_cover.append(float(np.mean(dep_valid & np.asarray(roi, dtype=bool))))
        hole_ratios.append(_hole_ratio(dep_valid))

    out["blur_laplacian_p95"] = _entry(float(np.percentile(blurs, 95)) if blurs else 0.0,
                                       unit="1", valid=bool(blurs),
                                       note="variance of Laplacian; monotone blur proxy")
    out["blur_laplacian_min"] = _entry(float(np.min(blurs)) if blurs else 0.0,
                                       unit="1", valid=bool(blurs),
                                       note="worst view in the set")
    out["overexposed_fraction"] = _entry(float(np.max(overs)) if overs else 0.0,
                                         unit="1", valid=bool(overs))
    out["underexposed_fraction"] = _entry(float(np.max(unders)) if unders else 0.0,
                                          unit="1", valid=bool(unders))
    out["mean_level"] = _entry(float(np.mean(means)) if means else 0.0, unit="1",
                               valid=bool(means))

    # -- point density and validity
    if points is not None:
        pts = np.asarray(points)
        n_pts = int(pts.shape[0])
        valid_ratio = (float(np.mean(np.asarray(point_valid, dtype=bool)))
                       if point_valid is not None and len(point_valid) else 0.0)
        out["point_count"] = _entry(float(n_pts), unit="1", valid=True)
        out["point_valid_fraction"] = _entry(valid_ratio, unit="1",
                                             valid=point_valid is not None)
        if n_pts >= 2:
            extent = np.ptp(pts, axis=0)
            diag = float(np.linalg.norm(extent))
            out["point_cloud_diagonal"] = _entry(diag, unit="mm" if scale_valid else "unknown",
                                                 valid=True,
                                                 note="unit is reconstruction units unless "
                                                      "scale_valid")
            # nearest-neighbour spacing through a KD-tree (never an O(N^2) loop)
            try:
                from scipy.spatial import cKDTree

                tree = cKDTree(pts)
                dist, _ = tree.query(pts, k=2)
                nn = dist[:, 1]
                nn = nn[np.isfinite(nn)]
                out["nn_spacing_median"] = _entry(float(np.median(nn)) if nn.size else 0.0,
                                                  unit="mm" if scale_valid else "unknown",
                                                  valid=bool(nn.size))
                out["nn_spacing_p95"] = _entry(
                    float(np.percentile(nn, 95)) if nn.size else 0.0,
                    unit="mm" if scale_valid else "unknown", valid=bool(nn.size))
            except Exception as exc:  # noqa: BLE001 - estimator is optional, report it
                out["nn_spacing_median"] = _entry(0.0, unit="unknown", valid=False,
                                                  note=f"cKDTree unavailable: {exc}")
        else:
            out["nn_spacing_median"] = _entry(0.0, unit="unknown", valid=False,
                                              note="fewer than 2 points")
    else:
        out["point_count"] = _entry(0.0, unit="1", valid=False, note="no fused points")
        out["point_valid_fraction"] = _entry(0.0, unit="1", valid=False)

    # -- holes and coverage
    out["view_coverage_mean"] = _entry(float(np.mean(coverage)) if coverage else 0.0,
                                       unit="1", valid=bool(coverage),
                                       note="fraction of pixels with a valid depth")
    out["hole_ratio_max"] = _entry(float(np.max(hole_ratios)) if hole_ratios else 0.0,
                                   unit="1", valid=bool(hole_ratios),
                                   note="largest interior invalid-depth hole fraction")
    out["roi_coverage_mean"] = _entry(float(np.mean(roi_cover)) if roi_cover else 0.0,
                                      unit="1", valid=bool(roi_cover),
                                      note="valid depth inside the estimated ROI")
    if fused_mesh is not None:
        try:
            import trimesh

            mesh = fused_mesh
            out["fused_area"] = _entry(float(mesh.area), unit="mm2" if scale_valid else "unknown",
                                       valid=True)
            out["fused_component_count"] = _entry(float(_component_count(mesh)), unit="1",
                                                  valid=True)
        except Exception as exc:  # noqa: BLE001
            out["fused_area"] = _entry(0.0, unit="unknown", valid=False,
                                       note=f"mesh metrics unavailable: {exc}")

    # -- scale credibility (never borrowed from a simulator or a clean model)
    out["scale_valid"] = {
        "value": 1.0 if scale_valid else 0.0,
        "unit": "bool",
        "source_kind": SOURCE_OBS_EST,
        "source_ref": OBS_EST_VERSION,
        "valid": True,
        "estimator_version": OBS_EST_VERSION,
        "note": "true only when the observation itself carries a qualified scale source",
        "oracle": False,
    }
    out["route"] = {
        "value": route,
        "unit": "",
        "source_kind": SOURCE_OBS_EST,
        "source_ref": OBS_EST_VERSION,
        "valid": True,
        "estimator_version": OBS_EST_VERSION,
        "note": "route that produced this observation",
        "oracle": False,
    }
    out["groups"] = {
        "blur": ["blur_laplacian_p95", "blur_laplacian_min"],
        "exposure": ["overexposed_fraction", "underexposed_fraction", "mean_level"],
        "density": ["point_count", "point_valid_fraction", "nn_spacing_median",
                    "nn_spacing_p95", "point_cloud_diagonal"],
        "holes": ["hole_ratio_max", "view_coverage_mean", "roi_coverage_mean"],
        "scale": ["scale_valid"],
    }
    out["estimator_version"] = OBS_EST_VERSION
    out["oracle_prefilled"] = False
    return out


def _hole_ratio(valid: np.ndarray) -> float:
    """Fraction of *interior* invalid pixels (holes), not counting the outer background."""
    import cv2

    mask = np.asarray(valid, dtype=np.uint8)
    if mask.size == 0 or mask.all():
        return 0.0
    # Fill from the border: everything the border flood-fill cannot reach is interior.
    h, w = mask.shape
    flood = mask.copy()
    ff = np.zeros((h + 2, w + 2), np.uint8)
    reachable = flood.copy()
    cv2.floodFill(reachable, ff, (0, 0), 1)
    filled = reachable.astype(bool) | mask.astype(bool)
    holes = (~mask.astype(bool)) & filled
    total = float(mask.size)
    return float(np.count_nonzero(holes) / total) if total else 0.0


def _component_count(mesh: Any) -> int:
    """Connected components of the observed mesh (via the face-adjacency graph)."""
    try:
        import trimesh

        comps = trimesh.graph.connected_components(mesh.face_adjacency)
        return int(len(comps))
    except Exception:  # noqa: BLE001 - reported as an invalid estimate upstream
        return 0


def attach_oracle_comparison(quality: dict[str, Any], oracle: dict[str, float],
                             *, oracle_ref: str) -> dict[str, Any]:
    """Attach a *separate* GT/oracle comparison block; never merged into OBS_EST values."""
    out = dict(quality)
    out["oracle_comparison"] = {
        "source_kind": "GT_ORACLE",
        "source_ref": oracle_ref,
        "note": "oracle values are comparison-only and must not be used as inputs",
        "values": {k: float(v) for k, v in oracle.items()},
    }
    return out


def summary_keys(quality: dict[str, Any]) -> list[str]:
    return sorted(k for k, v in quality.items()
                  if isinstance(v, dict) and "valid" in v)


__all__ = [
    "OBS_EST_VERSION", "blur_metric", "exposure_clip_metrics", "estimate_quality",
    "attach_oracle_comparison", "summary_keys",
]
