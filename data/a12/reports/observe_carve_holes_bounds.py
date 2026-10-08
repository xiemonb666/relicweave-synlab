"""Reproduce (pre-fix) and re-check (post-fix) the ``_carve_holes`` out-of-bounds defect.

The script only *observes*: it calls ``synlab.observe.routes::_carve_holes`` with constructed
depth maps of known geometry and records, for every case, whether the call raised, which pixels
became NaN and how the request was clipped.  Run it before and after the fix and diff the JSON.

Cases
-----
A. exact trigger, 1024-wide raster: one valid pixel at the right edge (the real lineage's grid);
B. exact trigger, 320x240 raster: one valid pixel at the bottom-right corner, ``hole_count=2``;
C. no-trigger control: interior centre, same rasters (must carve the same disc as before);
D. boundary sweep: for each radius, the largest ``x0`` that still fits and the smallest that
   crossed the array limit in the pre-fix code (the analytic condition x0 + r > W - 1);
E. trigger probability: Monte-Carlo over all-valid depth maps with the route's default
   ``hole_count=2`` and radius range [3, 7] (why the defect is intermittent per lineage);
F. semantics reference: the pre-fix algorithm evaluated on a zero-padded canvas (so its mgrid
   can never leave the array) cropped back to the raster - the in-raster mask the fix must keep.

Usage::

    .venv\\Scripts\\python.exe data\\a12\\reports\\observe_carve_holes_bounds.py \
        --out data\\a12\\reports\\observe_carve_holes_bounds_before.json
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

import inspect  # noqa: E402

from synlab.observe.routes import _carve_holes  # noqa: E402

#: The clip diagnostics parameter only exists after the fix; the same script must run on both trees.
_ACCEPTS_CLIP_REPORT = "clip_report" in inspect.signature(_carve_holes).parameters


def _carve(depth: np.ndarray, count: int, rng, *, rmin: int, rmax: int, report: list[dict]):
    kwargs = {"min_radius_px": rmin, "max_radius_px": rmax}
    if _ACCEPTS_CLIP_REPORT:
        kwargs["clip_report"] = report
    return _carve_holes(depth, count, rng, **kwargs)


def _single_pixel_map(h: int, w: int, y0: int, x0: int) -> np.ndarray:
    """Depth map with exactly one valid pixel (so the hole centre is deterministic)."""
    depth = np.full((h, w), np.nan, dtype=np.float64)
    depth[y0, x0] = 500.0
    return depth


def _call(depth: np.ndarray, count: int, *, seed: int = 0, rmin: int = 3, rmax: int = 7):
    """Call ``_carve_holes`` and describe the outcome without ever swallowing a silent error."""
    rng = np.random.Generator(np.random.PCG64(np.uint64(seed)))
    report: list[dict] = []
    try:
        out = _carve(depth, count, rng, rmin=rmin, rmax=rmax, report=report)
    except Exception as exc:  # noqa: BLE001 - the pre-fix run must keep the real IndexError
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                "exception_type": type(exc).__name__,
                "traceback_tail": traceback.format_exc().strip().splitlines()[-3:],
                "clip_report": report}
    carved = np.isnan(np.asarray(out)) & np.isfinite(np.asarray(depth))
    return {"ok": True, "carved_pixels": int(np.count_nonzero(carved)),
            "carved_yx": [[int(y), int(x)] for y, x in np.argwhere(carved)],
            "clip_report": report}


def _reference_in_raster(depth: np.ndarray, count: int, *, seed: int = 0,
                         rmin: int = 3, rmax: int = 7) -> np.ndarray:
    """The historical algorithm on a padded canvas, cropped back: crash-free by construction."""
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


def _random_map(h: int, w: int, seed: int = 12345) -> np.ndarray:
    rng = np.random.Generator(np.random.PCG64(np.uint64(seed)))
    depth = rng.uniform(300.0, 700.0, size=(h, w))
    depth[rng.random((h, w)) < 0.25] = np.nan
    return depth


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/a12/reports/observe_carve_holes_bounds.json")
    args = ap.parse_args()
    result: dict = {"cases": {}, "sweep": {}, "monte_carlo": {}, "semantics": {}}

    # -- A: the real-lineage geometry (1024 wide), centre on the right edge
    result["cases"]["A_1024_right_edge"] = _call(_single_pixel_map(768, 1024, 384, 1023), 1)
    result["cases"]["A_1024_right_edge_r7"] = _call(_single_pixel_map(768, 1024, 384, 1017), 1)
    # -- B: 320x240 raster (the independently reported configuration), corner centre
    result["cases"]["B_320x240_corner_count2"] = _call(_single_pixel_map(240, 320, 239, 319), 2)
    result["cases"]["B_320x240_right_edge_count2"] = _call(_single_pixel_map(240, 320, 120, 319), 2)
    # -- C: interior control (must be unaffected by the fix)
    result["cases"]["C_1024_interior"] = _call(_single_pixel_map(768, 1024, 384, 512), 1)
    result["cases"]["C_320x240_interior_count2"] = _call(_single_pixel_map(240, 320, 120, 160), 2)
    # -- hole_count = 0 must be the identity (same object, no draw)
    depth0 = _random_map(240, 320)
    zero = _carve_holes(depth0, 0, np.random.Generator(np.random.PCG64(7)),
                        min_radius_px=3, max_radius_px=7)
    result["cases"]["D_count0_identity"] = {
        "ok": True, "is_same_object": zero is depth0,
        "identical_values": bool(np.array_equal(np.nan_to_num(zero, nan=-1.0),
                                                np.nan_to_num(depth0, nan=-1.0)))}

    # -- E: analytic boundary sweep: smallest x0 whose disc leaves the raster
    #    (radius pinned to exactly r via min_radius_px == max_radius_px == r)
    for (h, w) in ((768, 1024), (240, 320)):
        rows = []
        for r in (3, 4, 5, 6, 7):
            x_last_fit = w - 1 - r          # x0 + r == w - 1 -> still inside
            x_first_oob = x_last_fit + 1    # x0 + r == w     -> np.mgrid needs index w
            fits = _call(_single_pixel_map(h, w, h // 2, x_last_fit), 1, rmin=r, rmax=r)
            oob = _call(_single_pixel_map(h, w, h // 2, x_first_oob), 1, rmin=r, rmax=r)
            y_last_fit = h - 1 - r
            y_first_oob = y_last_fit + 1
            rows.append({"size_hw": [h, w], "radius_px": r,
                         "x_last_fit": x_last_fit, "x_last_fit_ok": fits["ok"],
                         "x_first_oob": x_first_oob, "x_first_oob_ok": oob["ok"],
                         "x_first_oob_error": oob.get("error"),
                         "y_last_fit": y_last_fit, "y_first_oob": y_first_oob,
                         "y_first_oob_ok": _call(_single_pixel_map(h, w, y_first_oob, w // 2),
                                                 1, rmin=r, rmax=r)["ok"]})
        result["sweep"][f"{h}x{w}"] = rows

    # -- F: Monte-Carlo trigger probability (all-valid depth map, route defaults)
    for (h, w) in ((768, 1024), (240, 320)):
        depth = np.full((h, w), 500.0, dtype=np.float64)
        n_trials, n_fail = 200, 0
        for seed in range(n_trials):
            rng = np.random.Generator(np.random.PCG64(np.uint64(seed)))
            try:
                _carve(depth, 2, rng, rmin=3, rmax=7, report=[])
            except IndexError:
                n_fail += 1
        result["monte_carlo"][f"{h}x{w}"] = {"trials": n_trials, "holes_per_trial": 2,
                                             "IndexError_trials": n_fail,
                                             "rate": n_fail / n_trials}

    # -- G: semantics reference on random maps (crash-free pre-fix algorithm on a padded canvas)
    for (h, w) in ((768, 1024), (240, 320)):
        for seed in (0, 1, 2, 3, 4, 5):
            depth = _random_map(h, w, seed=seed)
            ref = _reference_in_raster(depth, 2, seed=seed)
            got = _call(depth, 2, seed=seed)
            key = f"{h}x{w}_seed{seed}"
            if not got["ok"]:
                result["semantics"][key] = {"call_ok": False, "error": got["error"]}
                continue
            rng = np.random.Generator(np.random.PCG64(np.uint64(seed)))
            out = _carve(depth, 2, rng, rmin=3, rmax=7, report=[])
            both_nan = np.isnan(out) & np.isnan(ref)
            mismatch = int(np.count_nonzero(np.isnan(out) != np.isnan(ref)))
            finite = np.isfinite(ref) & np.isfinite(out)
            value_mismatch = int(np.count_nonzero(
                np.asarray(out)[finite] != np.asarray(ref)[finite]))
            result["semantics"][key] = {
                "call_ok": True, "nan_mask_mismatch_px": mismatch,
                "value_mismatch_px": value_mismatch, "shared_nan_px": int(both_nan.sum())}

    out_path = ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str),
                        encoding="utf-8")
    print(json.dumps({k: result["cases"][k] for k in ("A_1024_right_edge", "B_320x240_corner_count2")},
                     ensure_ascii=False, indent=2)[:2000])
    print("sweep 240x320:", json.dumps(result["sweep"]["240x320"], ensure_ascii=False))
    print("monte_carlo:", json.dumps(result["monte_carlo"], ensure_ascii=False))
    sem_bad = {k: v for k, v in result["semantics"].items()
               if not v.get("call_ok") or v.get("nan_mask_mismatch_px") or v.get("value_mismatch_px")}
    print("semantics mismatches:", json.dumps(sem_bad, ensure_ascii=False))
    print(f"written {out_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
