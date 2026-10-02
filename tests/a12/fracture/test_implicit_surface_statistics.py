"""Realized implicit fracture-surface statistics: slope calibration and banded roughness.

Measured on the *built* cutter (the surface both halves carry), which is the same artifact the
frozen plane/rough backends measure with ``surface_features.measure_cutter_surface``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixtures as fx  # noqa: E402

from synlab.fracture import surface_features as sf  # noqa: E402
from synlab.fracture.implicit.backend import build_implicit_cutter  # noqa: E402
from synlab.fracture.implicit.field import SLOPE_P95_TARGET_DEG  # noqa: E402
from synlab.materials.api import build_material_profile, default_material_params  # noqa: E402
from synlab.seeds import make_rng  # noqa: E402

LIN = "a12_fracture_implicit_test"
#: the declared band for a real ceramic fracture surface (A12 realism doc 9.4): a few degrees up to
#: about 20 deg.  The test asserts the *upper* bound of the declared band, not a fitted number.
SLOPE_BAND_MAX_DEG = 20.0
SLOPE_BAND_MIN_DEG = 2.0


@pytest.fixture(scope="module")
def measured():
    mother = fx.box_mother((12.0, 12.0, 12.0), mother_id="implicit_stats")
    profile = build_material_profile("M01", default_material_params("M01"),
                                     make_rng(20261001, LIN, "material"))
    cutter, field, params, report = build_implicit_cutter(
        mother, material_profile=profile, rng=make_rng(20261001, LIN, "build"),
        event_id="stats", options={"max_sheet_triangles": 60_000})
    stats = sf.measure_cutter_surface(cutter.mesh, cutter.basis, params,
                                      window=field.envelope, n_samples=200_000)
    return cutter, field, params, report, stats


def test_slope_is_calibrated_into_the_declared_band(measured) -> None:
    _cutter, _field, _params, report, stats = measured
    slope = report["field"]["slope"]
    assert float(slope["target_deg"]) == pytest.approx(SLOPE_P95_TARGET_DEG)
    assert float(slope["before_deg"]) > SLOPE_BAND_MAX_DEG, (
        "the frozen model must be measured as too steep before the calibration, otherwise the "
        "calibration proves nothing")
    assert float(slope["after_deg"]) <= SLOPE_BAND_MAX_DEG
    assert float(slope["after_deg"]) >= SLOPE_BAND_MIN_DEG
    assert bool(slope["achieved_within_band"]) is True
    assert 0.0 < float(slope["scale"]) < 1.0, "the calibration only ever scales the relief down"
    # the delivered surface's own normal spread, measured independently of the calibration
    angles = np.asarray(_normal_angles(_cutter, _field), dtype=np.float64)
    assert float(np.percentile(angles, 95)) <= SLOPE_BAND_MAX_DEG + 5.0


def _normal_angles(cutter, field) -> np.ndarray:
    """P95 normal deviation of the *sheet* triangles from the mean surface normal."""
    from synlab.fracture.implicit.assembler import sheet_normal, sheet_distance

    mesh = cutter.mesh
    faces = np.asarray(mesh.faces)
    verts = np.asarray(mesh.vertices, dtype=np.float64)
    matrix = np.stack([cutter.basis.e_u, cutter.basis.e_v, cutter.basis.normal], axis=0)
    local = (verts - np.asarray(cutter.basis.origin)[None, :]) @ matrix.T
    centroids = verts[faces].mean(axis=1)
    d_sheet, local_centroids = sheet_distance(cutter.basis, cutter.h_fn, centroids)
    keep = d_sheet <= max(float(cutter.realized_error_mm), 1.0e-9)
    del local
    if not bool(np.any(keep)):
        return np.zeros(0)
    normals = sheet_normal(cutter.basis, cutter.h_fn, local_centroids[keep])
    face_normals = np.asarray(mesh.face_normals, dtype=np.float64)[keep]
    cos = np.clip(np.einsum("ij,ij->i", normals, face_normals), -1.0, 1.0)
    return np.degrees(np.arccos(cos))


def test_banded_roughness_is_non_zero_in_all_three_bands(measured) -> None:
    _cutter, field, params, _report, stats = measured
    u, v, w = stats["u"], stats["v"], stats["w"]
    assert u.size > 10_000
    detrend = sf.detrend_plane(u, v, w)
    bands = _band_decomposition(u, v, detrend["residual"])
    for key in ("Ra_gt_1mm", "Ra_0p25_to_1mm", "Ra_lt_0p25mm"):
        assert float(bands[key]) > 0.0, f"{key} must carry real geometric content"
    assert float(detrend["waviness_rms_mm"]) >= 0.0
    # the measurement is of the delivered surface, not of an upsampled texture
    assert float(stats["Ra_mm"]) > 0.0
    assert float(params.requested_rms_mm) > 0.0


def _band_decomposition(u, v, residual, *, raster_mm: float = 0.04) -> dict:
    from scipy import ndimage

    u = np.asarray(u, dtype=np.float64)
    v = np.asarray(v, dtype=np.float64)
    r = np.asarray(residual, dtype=np.float64)
    u0, v0 = float(u.min()), float(v.min())
    nu = min(int(np.ceil((u.max() - u0) / raster_mm)) + 1, 2048)
    nv = min(int(np.ceil((v.max() - v0) / raster_mm)) + 1, 2048)
    gi = np.clip(((u - u0) / raster_mm).astype(np.int64), 0, nu - 1)
    gj = np.clip(((v - v0) / raster_mm).astype(np.int64), 0, nv - 1)
    flat = gi * nv + gj
    count = np.bincount(flat, minlength=nu * nv).astype(np.float64).reshape(nu, nv)
    total = np.bincount(flat, weights=r, minlength=nu * nv).reshape(nu, nv)
    grid = np.where(count > 0, total / np.maximum(count, 1.0), 0.0)
    mask = count > 0

    def blur(sigma_mm: float) -> np.ndarray:
        sigma = max(sigma_mm / raster_mm, 1e-6)
        num = ndimage.gaussian_filter(grid, sigma=sigma, mode="nearest")
        den = ndimage.gaussian_filter(mask.astype(float), sigma=sigma, mode="nearest")
        return np.where(den > 1e-6, num / np.maximum(den, 1e-12), 0.0)

    low = blur(0.5)
    mid_all = blur(0.125)
    return {"Ra_gt_1mm": float(np.abs(low[mask]).mean()),
            "Ra_0p25_to_1mm": float(np.abs(mid_all - low)[mask].mean()),
            "Ra_lt_0p25mm": float(np.abs(grid - mid_all)[mask].mean())}


def test_correlation_length_and_ls_plane_rms_are_measured(measured) -> None:
    _cutter, _field, _params, _report, stats = measured
    correlation = float(stats["correlation_length_mm"])
    assert 0.0 < correlation <= 20.0
    u, v, w = stats["u"], stats["v"], stats["w"]
    detrend = sf.detrend_plane(u, v, w)
    rms = float(np.sqrt(np.mean(detrend["residual"] ** 2)))
    assert rms > 0.0
    assert float(stats["Rt_mm"]) >= float(stats["Ra_mm"]) >= 0.0


def test_boundary_height_is_bounded_by_the_relief_amplitude(measured) -> None:
    """The taper keeps the relief at the rim (a real fracture face does not flatten there).

    The measured boundary height must therefore be *bounded by the relief amplitude the calibration
    realised* -- that is the honest invariant of this construction, and the number is published in
    the module record rather than asserted to be zero (forcing it to zero is what produced the
    medial-axis ridge measured in ``docs/a12/fracture_implicit.md``).
    """
    _cutter, field, _params, report, _stats = measured
    ring = report["field"]["ring"]
    amplitude = float(max(
        [float(b.amplitude_mm) for b in field.bands]
        + [float(field.hackle_amplitude_mm), float(field.rib_amplitude_mm),
           float(field.fiber_amplitude_mm), float(field.pits.depth_mm if field.pits else 0.0),
           float(abs(field.dome_term(np.array([field.origin_uv[0] + 20.0]),
                                     np.array([field.origin_uv[1]]))[0]))],))
    assert float(ring["boundary_height_max_mm"]) <= amplitude + 1.0e-6
    assert int(ring["samples"]) > 100
