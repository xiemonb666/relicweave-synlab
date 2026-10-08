"""Boundary tests for ``synlab.observe.routes::_carve_holes`` (plan 14.2 G03).

Defect under test
-----------------
The historical implementation carved a disc through

    ``np.mgrid[max(y0 - r, 0):y0 + r + 1, max(x0 - r, 0):x0 + r + 1]``

and wrote ``out[yy[disc], xx[disc]] = np.nan``.  Only the *lower* bound was clipped to the
raster, so any hole whose centre satisfied ``y0 + r > h - 1`` or ``x0 + r > w - 1`` asked for
row ``h`` / column ``w`` and raised ``IndexError``, aborting the whole lineage.  The real
lineage ``LIN0016_V19_M04_PAT08`` hit it on a 1024-wide raster
(``IndexError: index 1024 is out of bounds for axis 1 with size 1024``); a 320x240 raster with
``hole_count=2`` hits the row axis (``index 240 ... axis 0 with size 240``).

Fixed rule
----------
A hole is ``disc ∩ raster``: the disc test keeps absolute pixel coordinates and only the
written window is clipped, so every in-raster pixel keeps exactly the verdict it had before and
the ``rng`` draw sequence is unchanged.  Clipped discs are reported through ``clip_report``
(and by ``route_proxy_scan`` in its ``G03_holes`` degradation record) instead of being skipped
silently.  Structurally unusable requests (non-2-D raster, non-floating raster, empty raster,
non-pixel radius range) raise a structured ``SynLabError`` carrying the actual raster and the
requested geometry - never a bare ``IndexError``.

The two expectations used below are written independently of the implementation:

* :func:`_reference_padded` runs the *historical* loop on a zero-padded canvas (where its own
  window can never leave the array) and crops back - the pre-fix semantics inside the raster;
* :func:`_expected_union_discs` replays the recorded draws from a fresh ``PCG64`` and builds the
  union of the full discs intersected with the raster through fancy indexing.

Two mask comparisons appear below and they are deliberately different:

* ``np.isnan(out)`` vs the reference's ``np.isnan`` - the full NaN pattern;
* :func:`_changed` - the pixels a call turned *from a valid depth into NaN*, which is what a
  depth-map consumer observes.  On a map whose background is already NaN the written disc can
  be larger than the observable change; both numbers are asserted where they differ.
"""

from __future__ import annotations

import numpy as np
import pytest

from synlab.errors import ErrorCode, SynLabError
from synlab.observe import routes as rt

#: The radius range ``route_proxy_scan`` uses (asserted against the route report below).
RMIN, RMAX = 3, 7

#: Sizes that matter: the reported 320x240 case and the real lineage's 1024-wide raster, in both
#: orientations so a transposed window cannot hide.
SIZES_HW = ((240, 320), (768, 1024), (320, 240), (1024, 768))


# --------------------------------------------------------------------------------------
# helpers / independent expectations
# --------------------------------------------------------------------------------------
def _single_pixel_map(h: int, w: int, y0: int, x0: int, value: float = 500.0) -> np.ndarray:
    """Depth map with exactly one valid pixel, so the drawn hole centre is deterministic."""
    depth = np.full((h, w), np.nan, dtype=np.float64)
    depth[y0, x0] = value
    return depth


def _random_map(h: int, w: int, seed: int) -> np.ndarray:
    rng = np.random.Generator(np.random.PCG64(np.uint64(seed)))
    depth = rng.uniform(300.0, 700.0, size=(h, w))
    depth[rng.random((h, w)) < 0.25] = np.nan
    return depth


def _carve(depth: np.ndarray, count: int, *, seed: int = 0,
           rmin: int = RMIN, rmax: int = RMAX, report: list | None = None) -> np.ndarray:
    rng = np.random.Generator(np.random.PCG64(np.uint64(seed)))
    kwargs = {} if report is None else {"clip_report": report}
    return rt._carve_holes(depth, count, rng, min_radius_px=rmin, max_radius_px=rmax, **kwargs)


def _finite(depth: np.ndarray) -> np.ndarray:
    return np.isfinite(depth) & (depth > 0)


def _changed(depth: np.ndarray, out: np.ndarray) -> np.ndarray:
    """Pixels turned from a valid depth value into NaN by the call."""
    return np.isnan(np.asarray(out)) & _finite(depth)


def _reference_padded(depth: np.ndarray, count: int, *, seed: int = 0,
                      rmin: int = RMIN, rmax: int = RMAX) -> np.ndarray:
    """The *historical* loop on a padded canvas, cropped back to the raster."""
    if count <= 0:
        return np.asarray(depth).copy()
    pad = rmax + 2
    h, w = depth.shape
    big = np.full((h + 2 * pad, w + 2 * pad), np.nan, dtype=np.float64)
    big[pad:pad + h, pad:pad + w] = depth
    out = big.copy()
    valid = np.isfinite(out) & (out > 0)
    if not valid.any():
        return out[pad:pad + h, pad:pad + w]
    ys, xs = np.nonzero(valid)
    rng = np.random.Generator(np.random.PCG64(np.uint64(seed)))
    for _ in range(count):
        k = int(rng.integers(0, ys.size))
        r = int(rng.integers(rmin, rmax + 1))
        y0, x0 = int(ys[k]), int(xs[k])
        yy, xx = np.mgrid[max(y0 - r, 0):y0 + r + 1, max(x0 - r, 0):x0 + r + 1]
        disc = (yy - y0) ** 2 + (xx - x0) ** 2 <= r * r
        out[yy[disc], xx[disc]] = np.nan
    return out[pad:pad + h, pad:pad + w]


def _expected_union_discs(depth: np.ndarray, count: int, *, seed: int = 0,
                          rmin: int = RMIN, rmax: int = RMAX) -> tuple[np.ndarray, list[dict]]:
    """Union of the drawn discs ∩ raster, built without the implementation's window clipping."""
    h, w = int(depth.shape[0]), int(depth.shape[1])
    carved = np.zeros((h, w), dtype=bool)
    valid = _finite(depth)
    ys, xs = np.nonzero(valid)
    if count <= 0 or ys.size == 0:
        return carved, []
    rng = np.random.Generator(np.random.PCG64(np.uint64(seed)))
    discs: list[dict] = []
    for _ in range(count):
        k = int(rng.integers(0, ys.size))
        r = int(rng.integers(rmin, rmax + 1))
        y0, x0 = int(ys[k]), int(xs[k])
        fy, fx = np.mgrid[y0 - r:y0 + r + 1, x0 - r:x0 + r + 1]
        disc = (fy - y0) ** 2 + (fx - x0) ** 2 <= r * r
        dy, dx = fy[disc], fx[disc]
        inside = (dy >= 0) & (dy < h) & (dx >= 0) & (dx < w)
        carved[dy[inside], dx[inside]] = True
        discs.append({"centre_yx": [y0, x0], "radius_px": r,
                      "disc_pixels": int(disc.sum()), "carved_pixels": int(inside.sum()),
                      "out_of_raster_pixels": int(disc.sum() - inside.sum())})
    return carved, discs


def _pre_fix_window_leaves_raster(y0: int, x0: int, r: int, h: int, w: int) -> bool:
    """The exact trigger of the defect: the requested window needs row ``h`` / column ``w``."""
    return (y0 + r > h - 1) or (x0 + r > w - 1)


# --------------------------------------------------------------------------------------
# 1. mask semantics are unchanged for every request the historical code could answer
# --------------------------------------------------------------------------------------
@pytest.mark.parametrize("size_hw", SIZES_HW)
@pytest.mark.parametrize("count", (1, 2))
@pytest.mark.parametrize("seed", (0, 1, 2, 3, 4, 5))
def test_requests_are_pixel_identical_to_the_historical_algorithm(size_hw, count, seed):
    h, w = size_hw
    depth = _random_map(h, w, seed=seed + 11)
    before = depth.copy()
    out = _carve(depth, count, seed=seed)
    ref = _reference_padded(depth, count, seed=seed)
    # the full NaN pattern is identical ...
    assert np.array_equal(np.isnan(out), np.isnan(ref))
    # ... and every surviving value is bit-identical (no re-quantisation, no silent fill)
    finite = np.isfinite(ref)
    assert np.array_equal(np.asarray(out)[finite], np.asarray(ref)[finite])
    # ... and the pixels a consumer sees change are identical as well
    assert np.array_equal(_changed(depth, out), _changed(depth, ref))
    # the input array is never modified in place
    assert np.array_equal(np.asarray(depth)[_finite(before)],
                          np.asarray(before)[_finite(before)])
    assert np.array_equal(np.isnan(depth), np.isnan(before))


@pytest.mark.parametrize("size_hw", SIZES_HW)
def test_carving_is_the_disc_intersected_with_the_raster(size_hw):
    h, w = size_hw
    depth = _random_map(h, w, seed=3)
    out = _carve(depth, 2, seed=3)
    expected, discs = _expected_union_discs(depth, 2, seed=3)
    assert np.array_equal(_changed(depth, out), expected & _finite(depth))
    assert len(discs) == 2
    # every changed pixel exists in the raster (nothing was written out of bounds)
    carved_yx = np.argwhere(_changed(depth, out))
    assert carved_yx[:, 0].max(initial=-1) < h and carved_yx[:, 1].max(initial=-1) < w


def test_written_disc_is_complete_when_the_map_is_valid_everywhere():
    depth = np.full((64, 96), 400.0, dtype=np.float64)
    out = _carve(depth, 1, seed=5, rmin=3, rmax=3)
    carved = _changed(depth, out)
    assert int(carved.sum()) == 29          # the r=3 disc has 29 pixels
    assert np.isfinite(out[~carved]).all()
    assert float(out[~carved].min()) == 400.0


# --------------------------------------------------------------------------------------
# 2. hole_count semantics
# --------------------------------------------------------------------------------------
@pytest.mark.parametrize("size_hw", SIZES_HW)
def test_hole_count_zero_is_the_identity_and_draws_nothing(size_hw):
    h, w = size_hw
    depth = _random_map(h, w, seed=7)
    rng = np.random.Generator(np.random.PCG64(np.uint64(99)))
    state_before = rng.bit_generator.state
    out = rt._carve_holes(depth, 0, rng, min_radius_px=RMIN, max_radius_px=RMAX)
    assert out is depth                                  # no copy, no draw, no change
    assert rng.bit_generator.state == state_before
    assert np.array_equal(np.isnan(out), np.isnan(depth))


@pytest.mark.parametrize("size_hw", SIZES_HW)
def test_hole_count_two_carves_the_two_drawn_discs(size_hw):
    h, w = size_hw
    depth = _random_map(h, w, seed=13)
    report: list[dict] = []
    out = _carve(depth, 2, seed=13, report=report)
    expected, discs = _expected_union_discs(depth, 2, seed=13)
    assert len(discs) == 2
    assert np.array_equal(_changed(depth, out), expected & _finite(depth))
    # the legacy "more holes" behaviour is kept: two holes change at least as many pixels as one
    one = _carve(depth, 1, seed=13)
    assert int(_changed(depth, out).sum()) >= int(_changed(depth, one).sum())
    # every drawn disc is either fully inside the raster (no record) or reported
    assert len(report) == sum(1 for d in discs if d["out_of_raster_pixels"] > 0)


# --------------------------------------------------------------------------------------
# 3. the out-of-bounds geometry: every edge, every radius, both defect reports
# --------------------------------------------------------------------------------------
EDGE_CASES = []
for _h, _w in SIZES_HW:
    for _r in (1, 3, 5, 7):
        EDGE_CASES.extend([
            (_h, _w, _h // 2, _w - 1, _r),          # right edge (the 1024-column case)
            (_h, _w, _h - 1, _w // 2, _r),          # bottom edge (the 240-row case)
            (_h, _w, 0, 0, _r),                     # top-left corner
            (_h, _w, _h - 1, _w - 1, _r),           # bottom-right corner
            (_h, _w, _h // 2, _w - 1 - _r, _r),     # last column that still fits
            (_h, _w, _h // 2, _w - _r, _r),         # first column that does not fit
        ])


@pytest.mark.parametrize("h,w,y0,x0,r", EDGE_CASES)
def test_edge_centres_are_clipped_not_skipped(h, w, y0, x0, r):
    depth = _single_pixel_map(h, w, y0, x0)
    report: list[dict] = []
    out = _carve(depth, 1, seed=0, rmin=r, rmax=r, report=report)
    expected, discs = _expected_union_discs(depth, 1, seed=0, rmin=r, rmax=r)
    # the centre is the only valid pixel, so exactly it is observed to change ...
    assert np.array_equal(_changed(depth, out), expected & _finite(depth)), (h, w, y0, x0, r)
    assert int(_changed(depth, out).sum()) == 1
    # ... while the written window is the whole in-raster part of the disc, never empty
    assert discs[0]["carved_pixels"] >= 1
    # a disc that leaves the raster in *any* direction is reported (the historical code already
    # clipped the lower bound, so only the upper bound could raise - that split is asserted here
    # as well, because it is exactly why the defect stayed unnoticed on top/left edges)
    if discs[0]["out_of_raster_pixels"] > 0:
        assert len(report) == 1 and report[0]["out_of_raster_pixels"] > 0
        assert report[0]["carved_pixels"] == discs[0]["carved_pixels"]
    else:
        assert report == []
    if _pre_fix_window_leaves_raster(y0, x0, r, h, w):
        assert discs[0]["out_of_raster_pixels"] > 0


def test_at_least_one_case_per_size_would_have_crashed_before():
    """Guard the fixture itself: the suite must keep covering the real trigger."""
    for h, w in SIZES_HW:
        triggering = [c for c in EDGE_CASES
                      if c[0] == h and c[1] == w and _pre_fix_window_leaves_raster(c[2], c[3],
                                                                                  c[4], h, w)]
        assert triggering, (h, w)


def test_real_lineage_geometry_1024_wide_right_edge():
    """The exact geometry of the live ``IndexError``: 1024 columns, centre on the last one."""
    h, w, r = 768, 1024, 7
    y0, x0 = 384, w - 1
    assert x0 + r + 1 - w == 7, "the historical window ran 7 columns past the right edge"
    depth = _single_pixel_map(h, w, y0, x0)
    report: list[dict] = []
    out = _carve(depth, 1, seed=0, rmin=r, rmax=r, report=report)
    expected, discs = _expected_union_discs(depth, 1, seed=0, rmin=r, rmax=r)
    assert np.array_equal(_changed(depth, out), expected & _finite(depth))
    assert discs[0]["carved_pixels"] > 0 and discs[0]["out_of_raster_pixels"] > 0
    assert report[0]["raster_size_hw"] == [h, w]
    assert report[0]["requested_bbox_yxhw"] == [y0 - r, x0 - r, 2 * r + 1, 2 * r + 1]
    # only the column axis is clipped here; the row window fits and is kept in full
    assert report[0]["written_bbox_yxhw"] == [y0 - r, x0 - r, 2 * r + 1, w - (x0 - r)]
    assert report[0]["out_of_raster_pixels"] == discs[0]["out_of_raster_pixels"]
    assert report[0]["carved_pixels"] == report[0]["disc_pixels"] - \
        report[0]["out_of_raster_pixels"]


def test_reported_320x240_hole_count_two_case():
    """``delivered_size=(320, 240)`` + ``hole_count=2`` was reported to raise ``IndexError``."""
    h, w = 240, 320
    depth = _single_pixel_map(h, w, h - 1, w - 1)
    report: list[dict] = []
    out = _carve(depth, 2, seed=0, rmin=3, rmax=3, report=report)
    # one valid pixel => both holes share the centre; only the in-raster quarter disc is written
    assert _changed(depth, out)[h - 1, w - 1]
    assert int(_changed(depth, out).sum()) == 1        # the centre was the only valid pixel
    assert _changed(depth, out)[:h - 1, :w - 1].sum() == 0
    expected, discs = _expected_union_discs(depth, 2, seed=0, rmin=3, rmax=3)
    assert np.array_equal(_changed(depth, out), expected & _finite(depth))
    assert discs[0]["disc_pixels"] == 29 and discs[0]["carved_pixels"] == 11
    assert report[0]["written_bbox_yxhw"] == [h - 1 - 3, w - 1 - 3, 4, 4]
    # the same call with the historical window would have needed row 240 of a 240-row raster
    assert _pre_fix_window_leaves_raster(h - 1, w - 1, 3, h, w)


@pytest.mark.parametrize("size_hw", ((5, 7), (9, 4)))
def test_every_centre_radius_and_count_stays_inside_the_raster(size_hw):
    """Exhaustive small-raster sweep: no request can leave the array any more."""
    h, w = size_hw
    for y0 in range(h):
        for x0 in range(w):
            depth = _single_pixel_map(h, w, y0, x0)
            for r in (1, 2, 3, 4):
                for count in (1, 2, 3):
                    out = _carve(depth, count, seed=r, rmin=r, rmax=r)
                    expected, _ = _expected_union_discs(depth, count, seed=r, rmin=r, rmax=r)
                    assert np.array_equal(_changed(depth, out),
                                          expected & _finite(depth)), (y0, x0, r, count)


# --------------------------------------------------------------------------------------
# 4. the clip report is structured, exact and never silent
# --------------------------------------------------------------------------------------
def test_clip_report_fields_and_pixel_accounting():
    h, w, r = 240, 320, 7
    y0, x0 = 239, 319
    depth = _single_pixel_map(h, w, y0, x0)
    report: list[dict] = []
    _carve(depth, 1, seed=0, rmin=r, rmax=r, report=report)
    assert len(report) == 1
    entry = report[0]
    assert entry["rule"] == rt.HOLE_CLIP_RULE == "disc_intersect_raster"
    assert entry["centre_yx"] == [y0, x0] and entry["radius_px"] == r
    assert entry["raster_size_hw"] == [h, w]
    assert entry["requested_bbox_yxhw"] == [y0 - r, x0 - r, 2 * r + 1, 2 * r + 1]
    assert entry["written_bbox_yxhw"] == [y0 - r, x0 - r, r + 1, r + 1]  # the corner survives
    assert entry["out_of_raster_pixels"] == entry["disc_pixels"] - entry["carved_pixels"] > 0
    expected, discs = _expected_union_discs(depth, 1, seed=0, rmin=r, rmax=r)
    assert entry["disc_pixels"] == discs[0]["disc_pixels"] == 149     # Gauss disc, r = 7
    assert entry["carved_pixels"] == discs[0]["carved_pixels"] == 45  # the in-raster quarter
    assert entry["out_of_raster_pixels"] == 104
    # the written window is bigger than the observable change: the rest of the map was NaN
    assert int(_changed(depth, _carve(depth, 1, seed=0, rmin=r, rmax=r)).sum()) == 1


def test_in_raster_discs_are_not_reported():
    depth = np.full((240, 320), 500.0, dtype=np.float64)
    report: list[dict] = []
    _carve(depth, 2, seed=1, report=report)
    assert report == []


# --------------------------------------------------------------------------------------
# 5. structurally unusable requests raise a structured SynLabError
# --------------------------------------------------------------------------------------
def test_empty_raster_is_refused_with_actual_and_requested_sizes():
    depth = np.zeros((0, 0), dtype=np.float64)
    with pytest.raises(SynLabError) as excinfo:
        _carve(depth, 2, seed=0)
    err = excinfo.value
    assert err.code == ErrorCode.TARGET_INFEASIBLE
    assert err.measurements["actual_size_hw"] == [0, 0]
    assert err.measurements["requested_hole_count"] == 2
    assert err.measurements["requested_radius_px"] == [RMIN, RMAX]
    assert "0x0" in err.message
    assert not isinstance(err, IndexError)


def test_empty_row_raster_is_refused():
    with pytest.raises(SynLabError) as excinfo:
        _carve(np.zeros((0, 32), dtype=np.float64), 1, seed=0)
    assert excinfo.value.code == ErrorCode.TARGET_INFEASIBLE
    assert excinfo.value.measurements["actual_size_hw"] == [0, 32]


def test_non_2d_raster_is_refused():
    with pytest.raises(SynLabError) as excinfo:
        _carve(np.zeros((4, 4, 3), dtype=np.float64), 2, seed=0)
    err = excinfo.value
    assert err.code == ErrorCode.SCHEMA_INVALID
    assert err.measurements["actual_shape"] == [4, 4, 3]
    assert err.measurements["requested_radius_px"] == [RMIN, RMAX]


def test_non_floating_raster_is_refused():
    """A hole is expressed as NaN, so an integer raster cannot carry the result."""
    with pytest.raises(SynLabError) as excinfo:
        _carve(np.full((240, 320), 500, dtype=np.int32), 1, seed=0)
    err = excinfo.value
    assert err.code == ErrorCode.SCHEMA_INVALID
    assert err.measurements["actual_dtype"] == "int32"
    assert err.measurements["actual_size_hw"] == [240, 320]


@pytest.mark.parametrize("rmin,rmax", ((-1, 7), (5, 3), (-4, -2)))
def test_non_pixel_radius_range_is_refused(rmin, rmax):
    depth = np.full((240, 320), 500.0, dtype=np.float64)
    with pytest.raises(SynLabError) as excinfo:
        _carve(depth, 1, seed=0, rmin=rmin, rmax=rmax)
    err = excinfo.value
    assert err.code == ErrorCode.SCHEMA_INVALID
    assert err.measurements["requested_radius_px"] == [rmin, rmax]
    assert err.measurements["actual_size_hw"] == [240, 320]


def test_radius_zero_is_accepted_and_carves_the_single_centre_pixel():
    depth = np.full((32, 32), 500.0, dtype=np.float64)
    out = _carve(depth, 1, seed=0, rmin=0, rmax=0)
    assert int(_changed(depth, out).sum()) == 1


def test_no_valid_pixel_is_a_no_op_copy():
    depth = np.full((240, 320), np.nan, dtype=np.float64)
    out = _carve(depth, 2, seed=0)
    assert out is not depth
    assert np.isnan(out).all()


# --------------------------------------------------------------------------------------
# 6. route wiring: the clip rule is part of the reported degradation, not a silent fix
# --------------------------------------------------------------------------------------
def test_route_proxy_scan_320x240_hole_count_two_runs_and_reports_the_clip_rule():
    from synlab.cameras.api import camera_profiles
    from synlab.mothers.api import create_mother, default_params
    from synlab.observe.render import RenderSpec
    from synlab.seeds import make_rng

    mother = create_mother("V13", "M01", default_params("V13"),
                           make_rng(7, "carve_holes_bounds", "V13"), mother_id="V13-carve")
    target = rt.resolve_target(mother, None)
    profile = camera_profiles()[0]
    spec = rt.ObsSpec(view_count=1, delivered_size=(320, 240), max_render_pixels=320 * 240,
                      render_spec=RenderSpec(supersample=1), master_seed=7,
                      lineage_id="carve_holes_bounds",
                      route_params={"hole_count": 2, "stride": 1})
    obs, bundles = rt.route_proxy_scan(target, profile, spec,
                                       make_rng(7, "carve_holes_bounds", "proxy"))
    g03 = obs.backend_report["degradations"]["G03_holes"]
    assert g03["requested"] == 2
    assert g03["clip_rule"] == rt.HOLE_CLIP_RULE
    assert g03["radius_px"] == [RMIN, RMAX]          # the route's own range
    assert isinstance(g03["clipped"], list) and g03["clipped_count"] == len(g03["clipped"])
    # the depth raster really is 240x320 here (the reported shape of the defect)
    depth = np.asarray(bundles[0].render.depth_z, dtype=np.float64)
    assert depth.shape == (240, 320)
    assert np.asarray(obs.views[0].depth_z).shape == (240, 320)
    # the route's own raster really does lose valid pixels to the two holes
    changed = _changed(depth, _carve(depth, 2, seed=4))
    assert int(changed.sum()) > 0
    assert int(changed.sum()) <= 2 * int(np.pi * RMAX ** 2) + 2
    # and the observation is a complete, hashed result rather than a stopped one
    assert obs.route == rt.ROUTE_PROXY_SCAN and obs.observation_id
