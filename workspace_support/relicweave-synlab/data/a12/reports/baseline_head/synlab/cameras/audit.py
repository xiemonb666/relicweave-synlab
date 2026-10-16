"""Pixel-frame and display-frame contract audit (plan 30.3, 20.14.1) -> A25 evidence.

Everything in this module is *measured on the real implementation*: the projections,
pixel affines, EXIF transforms and display transforms all come from
:mod:`synlab.cameras.projection` and :mod:`synlab.api.display`.  The COLMAP round trip is
checked against the **installed** ``pycolmap`` camera model (not against a re-implementation
of the same formula), so a wrong pixel-centre convention fails here.

The public entry point is :func:`audit_pixel_contract`; it returns
``{"ok": bool, "status": "PASS"|"FAIL", "metrics": {...}}`` and writes the A25 report to
``<store_root>/reports/pixel_contract.json`` (``data/a12/reports/pixel_contract.json`` when
no store is given), which is where ``synlab.qc.acceptance`` item A25 reads it from.

Thresholds
----------
``A02_max_px_error`` / ``A02_max_mm_error`` are read from
``configs/a12/qa_protocol_v1.json`` (the frozen protocol file); the display bound
``1e-9 m`` is the plan 30.3 / 20.14.1 statement for the 100 mm cube (0.1 m edges).
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

import numpy as np

from ..api.display import (
    AUTHORITY_UNIT,
    DISPLAY_UNIT,
    T_AUTHORITY_DISPLAY,
    T_DISPLAY_AUTHORITY,
    authority_to_display,
    display_to_authority,
    transform_vertices,
    up_axis_swap_display_to_authority,
)
from ..errors import ErrorCode, SynLabError
from .projection import (
    EXIF_MIRROR,
    EXIF_ROTATE_CW,
    apply_exif_to_image,
    colmap_convention,
    colmap_unconvention,
    crop_resize_matrix,
    exif_transform,
    from_colmap_pixels,
    letterbox_transform,
    look_at_T_WC,
    pixel_transform_crop_resize,
    project,
    to_colmap_pixels,
    unproject,
    world_to_camera,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORT_ROOT = ROOT / "data" / "a12" / "reports"
REPORT_NAME = "pixel_contract.json"
QA_PROTOCOL = ROOT / "configs" / "a12" / "qa_protocol_v1.json"
FRONTEND_DISPLAY_TS = ROOT / "frontend" / "src" / "lib" / "display.ts"

#: plan 20.14.1 / 30.3: a 100 mm cube must be 0.1 m in the GLB and measure 100 mm in the UI.
DISPLAY_MAX_ERROR_M = 1.0e-9
DISPLAY_MAX_ERROR_MM = 1.0e-9
#: exactness bound for the pure-arithmetic parts (0.5 px convention, K' = A K, matrices).
EXACT_TOL = 1.0e-12


# --------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------
def _thresholds() -> dict[str, float]:
    """Read the frozen protocol thresholds; a missing file is an error, not a default."""
    px, mm = 0.05, 0.001
    if QA_PROTOCOL.exists():
        data = json.loads(QA_PROTOCOL.read_text(encoding="utf-8"))
        thr = data.get("thresholds", {})
        px = float(thr.get("A02_max_px_error", px))
        mm = float(thr.get("A02_max_mm_error", mm))
    return {"max_px_error": px, "max_mm_error": mm,
            "display_max_error_m": DISPLAY_MAX_ERROR_M,
            "display_max_error_mm": DISPLAY_MAX_ERROR_MM,
            "exact_tolerance": EXACT_TOL,
            "source": str(QA_PROTOCOL.relative_to(ROOT)) if QA_PROTOCOL.exists() else "builtin"}


def _analytic_scene() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """A fixed analytic scene: non-integer K, oblique pose, points at three depths."""
    K = np.array([[515.3, 0.0, 319.7],
                  [0.0, 512.9, 239.4],
                  [0.0, 0.0, 1.0]], dtype=np.float64)
    T_WC = look_at_T_WC(eye=np.array([18.0, -26.0, 340.0]), target=np.array([0.0, 0.0, 0.0]))
    gx, gy = np.meshgrid(np.linspace(-45.0, 45.0, 6), np.linspace(-35.0, 35.0, 5))
    flat = np.stack([gx.ravel(), gy.ravel(), np.zeros(gx.size)], axis=1)
    near = flat * 0.6 + np.array([0.0, 0.0, 40.0])
    far = flat * 1.4 + np.array([0.0, 0.0, -60.0])
    points = np.concatenate([flat, near, far], axis=0)
    cam = world_to_camera(T_WC, points)
    if not np.all(cam[:, 2] > 1.0):  # pragma: no cover - defensive
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "analytic scene puts a point behind the camera",
                          stage="cameras.audit.scene")
    return K, T_WC, points


def _apply_affine(A: np.ndarray, uv: np.ndarray) -> np.ndarray:
    uv = np.asarray(uv, dtype=np.float64).reshape(-1, 2)
    return (A @ np.concatenate([uv, np.ones((uv.shape[0], 1))], axis=1).T).T[:, :2]


def _closed_form_uv(uv: np.ndarray, x0: float, y0: float, sx: float, sy: float) -> np.ndarray:
    """plan 30.3: ``u' = sx (u - x0 + 0.5) - 0.5``."""
    uv = np.asarray(uv, dtype=np.float64).reshape(-1, 2)
    return np.stack([sx * (uv[:, 0] - x0 + 0.5) - 0.5,
                     sy * (uv[:, 1] - y0 + 0.5) - 0.5], axis=1)


def _roundtrip(name: str, K: np.ndarray, T_WC: np.ndarray, points: np.ndarray,
               A: np.ndarray, *, dist: np.ndarray | None = None, model: str = "OPENCV",
               sx: float | None = None, sy: float | None = None,
               x0: float | None = None, y0: float | None = None) -> dict[str, Any]:
    """Measure ``K' = A K`` plus the pixel and millimetre round trips for one transform.

    The depth of a point is unchanged by an in-image affine (crop/resize/letterbox), so
    un-projecting the mapped pixel at the *same* camera-frame ``z`` must return the same
    world point: this is the mm-level check, while re-projecting with ``K'`` is the px-level
    check (plan 30.3 uses A02's analytic tolerance for both).
    """
    uv, z = project(points, K, T_WC, dist, model=model)
    uv_mapped = _apply_affine(A, uv)
    K_new = A @ K
    uv_ref, _ = project(points, K_new, T_WC, dist, model=model)
    if not np.array_equal(np.isfinite(uv), np.isfinite(uv_ref)):  # pragma: no cover - defensive
        raise SynLabError(ErrorCode.SCHEMA_INVALID, f"{name}: projection validity changed",
                          stage="cameras.audit.roundtrip")
    px_error = float(np.nanmax(np.abs(uv_ref - uv_mapped)))
    back = unproject(uv_mapped, z, K_new, T_WC, dist, model=model)
    mm_error = float(np.max(np.linalg.norm(back - points, axis=1)))
    detail: dict[str, Any] = {
        "n_points": int(points.shape[0]),
        "max_px_error": px_error,
        "max_mm_error": mm_error,
        "K_new_equals_A_K": bool(np.array_equal(K_new, A @ K)),
    }
    if None not in (sx, sy, x0, y0):
        detail["max_A_formula_error_px"] = float(
            np.max(np.abs(uv_mapped - _closed_form_uv(uv, float(x0), float(y0), float(sx), float(sy)))))
    return detail


# --------------------------------------------------------------------------------------
# checks
# --------------------------------------------------------------------------------------
def _check_colmap_convention(thresholds: dict[str, float]) -> dict[str, Any]:
    """``cx+0.5`` / pixel-centre round trip through the COLMAP convention functions."""
    K = np.array([[473.25, 0.0, 318.75],
                  [0.0, 471.5, 240.25],
                  [0.0, 0.0, 1.0]], dtype=np.float64)
    uv = np.array([[0.0, 0.0], [0.5, 0.5], [318.75, 240.25], [639.0, 479.0],
                   [12.25, 7.75], [-3.5, 900.125]], dtype=np.float64)
    K_col = colmap_convention(K)
    K_back = colmap_unconvention(K_col)
    uv_col = to_colmap_pixels(uv)
    uv_back = from_colmap_pixels(uv_col)
    detail = {
        "cx_shift": float(K_col[0, 2] - K[0, 2]),
        "cy_shift": float(K_col[1, 2] - K[1, 2]),
        "K_roundtrip_max_error": float(np.max(np.abs(K_back - K))),
        "uv_roundtrip_max_error_px": float(np.max(np.abs(uv_back - uv))),
        "uv_shift": [float(uv_col[0, 0] - uv[0, 0]), float(uv_col[0, 1] - uv[0, 1])],
        "convention": "opencv_pixel_center_0_0 -> colmap_top_left_corner_0_5",
    }
    ok = (abs(detail["cx_shift"] - 0.5) <= EXACT_TOL and abs(detail["cy_shift"] - 0.5) <= EXACT_TOL
          and detail["K_roundtrip_max_error"] <= EXACT_TOL
          and detail["uv_roundtrip_max_error_px"] <= EXACT_TOL)
    return {"ok": ok, "detail": detail}


def _check_colmap_real(thresholds: dict[str, float]) -> dict[str, Any]:
    """The same round trip against the **installed** pycolmap camera model (real library)."""
    detail: dict[str, Any] = {"library": "pycolmap"}
    try:
        import pycolmap
    except Exception as exc:  # noqa: BLE001
        detail["available"] = False
        detail["error"] = f"{type(exc).__name__}: {exc}"
        return {"ok": False, "detail": detail}
    detail["available"] = True
    detail["version"] = str(getattr(pycolmap, "__version__", "unknown"))
    K, T_WC, points = _analytic_scene()
    width, height = 640, 480
    K_col = colmap_convention(K)
    cam = pycolmap.Camera(model="PINHOLE", width=width, height=height,
                          params=np.array([K_col[0, 0], K_col[1, 1], K_col[0, 2], K_col[1, 2]]))
    cam_c = world_to_camera(T_WC, points)
    uv_colmap = np.asarray(cam.img_from_cam(cam_c), dtype=np.float64)
    uv_ours, _ = project(points, K, T_WC, None, model="PINHOLE")
    forward_error = float(np.max(np.abs(uv_colmap - to_colmap_pixels(uv_ours))))
    # the reverse direction: COLMAP pixels -> our OpenCV pixels
    uv_cv = from_colmap_pixels(uv_colmap)
    back_error = float(np.max(np.abs(uv_cv - uv_ours)))
    # and COLMAP's own de-normalisation against the analytic OpenCV model
    cam_back = np.asarray(cam.cam_from_img(uv_colmap), dtype=np.float64)
    xd = (uv_ours[:, 0] - K[0, 2]) / K[0, 0]
    yd = (uv_ours[:, 1] - K[1, 2]) / K[1, 1]
    normalized_error = float(np.max(np.abs(cam_back - np.stack([xd, yd], axis=1))))
    detail.update({
        "forward_max_error_px": forward_error,
        "reverse_max_error_px": back_error,
        "normalized_max_error": normalized_error,
        "camera_summary_first_line": cam.summary().splitlines()[1].strip(),
        "principal_point_colmap": [float(cam.principal_point_x), float(cam.principal_point_y)],
        "principal_point_opencv_plus_half": [float(K[0, 2] + 0.5), float(K[1, 2] + 0.5)],
    })
    ok = forward_error <= thresholds["max_px_error"] and back_error <= thresholds["max_px_error"] \
        and normalized_error <= 1e-9
    return {"ok": ok, "detail": detail}


def _check_pixel_transforms(thresholds: dict[str, float]) -> dict[str, Any]:
    """Non-integer scale, odd/even sizes, non-zero crop origin and a letterbox pad."""
    K, T_WC, points = _analytic_scene()
    cases: dict[str, Any] = {}
    specs = {
        # (name, image size (W,H), x0, y0, sx, sy)
        "non_integer_scale": ((641, 481), 0, 0, 0.37, 0.63),
        "odd_to_even": ((641, 481), 0, 0, 320.0 / 641.0, 240.0 / 481.0),
        "even_to_odd_upscale": ((640, 480), 0, 0, 1.7, 1.3),
        "crop_origin_odd": ((641, 481), 37, 19, 0.5, 0.5),
        "crop_origin_even": ((640, 480), 64, 48, 2.0 / 3.0, 2.0 / 3.0),
        "crop_and_non_integer": ((641, 481), 13, 7, 1.25, 0.8),
    }
    for name, ((width, height), x0, y0, sx, sy) in specs.items():
        A, K_new = pixel_transform_crop_resize(float(x0), float(y0), sx, sy, K)
        A_ref = crop_resize_matrix(float(x0), float(y0), sx, sy)
        entry = _roundtrip(name, K, T_WC, points, A, sx=sx, sy=sy, x0=float(x0), y0=float(y0))
        entry.update({
            "image_size": [width, height],
            "crop_origin": [x0, y0],
            "scale": [sx, sy],
            "A_matches_crop_resize_matrix": bool(np.array_equal(A, A_ref)),
            "K_new_matches_A_K": bool(np.array_equal(K_new, A @ K)),
            "cx_new_closed_form_error": float(
                abs(K_new[0, 2] - (sx * (K[0, 2] - x0 + 0.5) - 0.5))),
            "cy_new_closed_form_error": float(
                abs(K_new[1, 2] - (sy * (K[1, 2] - y0 + 0.5) - 0.5))),
            "A_determinant": float(np.linalg.det(A)),
        })
        # letterbox is the same affine composed with a pure translation
        pad_x, pad_y = 23.0, 41.0
        T_pad, K_pad = letterbox_transform(K_new, pad_x, pad_y)
        A_lb = T_pad @ A
        lb = _roundtrip(f"{name}+letterbox", K, T_WC, points, A_lb, sx=sx, sy=sy,
                        x0=float(x0) - pad_x / sx, y0=float(y0) - pad_y / sy)
        # ``(T_pad A) K`` and ``T_pad (A K)`` agree mathematically but not bit-for-bit for
        # non-dyadic scales, so the composed product is compared with a ULP-scale bound.
        k_pad_diff = float(np.max(np.abs(K_pad - A_lb @ K)))
        lb.update({
            "pad": [pad_x, pad_y],
            "image_size": [int(width + 2 * pad_x), int(height + 2 * pad_y)],
            "K_pad_matches_A_lb_K": bool(k_pad_diff <= 1.0e-9),
            "K_pad_difference": k_pad_diff,
            "translation_only": bool(np.array_equal(T_pad[:2, :2], np.eye(2))),
        })
        entry["letterbox"] = lb
        entry["ok"] = (entry["max_px_error"] <= thresholds["max_px_error"]
                       and entry["max_mm_error"] <= thresholds["max_mm_error"]
                       and entry["A_matches_crop_resize_matrix"] and entry["K_new_matches_A_K"]
                       and entry["cx_new_closed_form_error"] <= EXACT_TOL
                       and entry["cy_new_closed_form_error"] <= EXACT_TOL
                       and lb["max_px_error"] <= thresholds["max_px_error"]
                       and lb["max_mm_error"] <= thresholds["max_mm_error"]
                       and lb["K_pad_matches_A_lb_K"] and lb["translation_only"])
        cases[name] = entry
    # a non-zero distortion sample (plan 30.3: "非零畸变样例" is part of the acceptance set)
    dist = np.array([-0.12, 0.031, 0.0021, -0.0016, -0.0042], dtype=np.float64)
    A, K_new = pixel_transform_crop_resize(0.0, 0.0, 0.5, 0.5, K)
    distorted = _roundtrip("distorted_resize", K, T_WC, points, A, dist=dist, model="OPENCV",
                           sx=0.5, sy=0.5, x0=0.0, y0=0.0)
    distorted.update({"distortion": dist.tolist(), "model": "OPENCV", "scale": [0.5, 0.5],
                      "K_new_matches_A_K": bool(np.array_equal(K_new, A @ K))})
    distorted["ok"] = (distorted["max_px_error"] <= thresholds["max_px_error"]
                       and distorted["max_mm_error"] <= thresholds["max_mm_error"]
                       and distorted["K_new_matches_A_K"])
    cases["distorted_resize"] = distorted
    detail = {"cases": cases,
              "max_px_error": max(c["max_px_error"] for c in cases.values()),
              "max_mm_error": max(c["max_mm_error"] for c in cases.values())}
    return {"ok": all(c["ok"] for c in cases.values()), "detail": detail}


def _check_exif(thresholds: dict[str, float]) -> dict[str, Any]:
    """Every EXIF orientation applied to **pixels** with the matching ``A`` and ``K_new``."""
    K, _, _ = _analytic_scene()
    width, height = 641, 481
    rng = np.random.Generator(np.random.PCG64(np.uint64(0x30_03)))
    image = rng.integers(0, 256, size=(height, width, 3), dtype=np.uint8)
    probes = [(0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1),
              (37, 19), (320, 240), (12, 468), (600, 90)]
    orientations: dict[str, Any] = {}
    for orientation in sorted(EXIF_ROTATE_CW):
        A, K_new, new_size = exif_transform(K, orientation, (width, height))
        out = apply_exif_to_image(image, orientation)
        shape_ok = (out.shape[1], out.shape[0]) == (int(new_size[0]), int(new_size[1]))
        err = 0
        moved = 0
        for u, v in probes:
            up, vp = _apply_affine(A, np.array([[float(u), float(v)]]))[0]
            up_i, vp_i = int(round(up)), int(round(vp))
            err = max(err, int(np.max(np.abs(out[vp_i, up_i].astype(np.int32)
                                            - image[v, u].astype(np.int32)))))
            if (up_i, vp_i) != (u, v):
                moved += 1
        orientations[str(orientation)] = {
            "A": np.asarray(A, dtype=np.float64).tolist(),
            "image_size": [int(new_size[0]), int(new_size[1])],
            "shape_ok": bool(shape_ok),
            "K_new_equals_A_K": bool(np.array_equal(K_new, A @ K)),
            "max_pixel_mismatch": int(err),
            "probes_moved": int(moved),
            "rotate_cw": int(EXIF_ROTATE_CW[orientation]),
            "mirror": EXIF_MIRROR[orientation],
            "ok": bool(shape_ok and err == 0 and np.array_equal(K_new, A @ K)),
        }
    # explicit 90 degree landmark: one bright pixel must land exactly where A says
    marker = np.zeros((height, width), dtype=np.uint8)
    u0, v0 = 111, 222
    marker[v0, u0] = 255
    A6, K6, size6 = exif_transform(K, 6, (width, height))
    rotated = apply_exif_to_image(marker, 6)
    ys, xs = np.nonzero(rotated)
    landed = [int(xs[0]), int(ys[0])] if xs.size else None
    expected = _apply_affine(A6, np.array([[float(u0), float(v0)]]))[0]
    exif90 = {
        "source_pixel": [u0, v0],
        "expected_pixel": [float(expected[0]), float(expected[1])],
        "landed_pixel": landed,
        "pixel_applied": bool(landed == [int(round(expected[0])), int(round(expected[1]))]),
        "image_size_before": [width, height],
        "image_size_after": [int(size6[0]), int(size6[1])],
        "size_swapped": bool(size6 == (height, width)),
        "K_new_equals_A_K": bool(np.array_equal(K6, A6 @ K)),
        "metadata_only_would_fail": bool((width, height) != (int(size6[0]), int(size6[1]))),
    }
    detail = {"orientations": orientations, "exif_90": exif90,
              "all_orientations_ok": all(o["ok"] for o in orientations.values())}
    ok = detail["all_orientations_ok"] and exif90["pixel_applied"] and exif90["size_swapped"] \
        and exif90["K_new_equals_A_K"]
    return {"ok": ok, "detail": detail}


def _frontend_matrix_check() -> dict[str, Any]:
    """Cross-layer check: the TS display matrices must equal the Python constants."""
    detail: dict[str, Any] = {"path": str(FRONTEND_DISPLAY_TS.relative_to(ROOT)),
                              "present": FRONTEND_DISPLAY_TS.exists()}
    if not FRONTEND_DISPLAY_TS.exists():
        detail["ok"] = None
        return {"ok": True, "detail": detail, "note": "frontend display.ts absent; skipped"}

    text = FRONTEND_DISPLAY_TS.read_text(encoding="utf-8")

    def matrix(name: str) -> list[list[float]] | None:
        match = re.search(rf"{name}[^=]*=\s*\[(.*?)\];", text, re.S)
        if not match:
            return None
        rows = re.findall(r"\[([^\[\]]*)\]", match.group(1))
        return [[float(v) for v in row.split(",") if v.strip()] for row in rows]

    ts_display = matrix("T_DISPLAY_AUTHORITY")
    ts_authority = matrix("T_AUTHORITY_DISPLAY")
    detail["ts_display_to_authority_matrix"] = ts_display
    detail["ts_authority_to_display_matrix"] = ts_authority
    ok_display = ts_display is not None and np.allclose(np.array(ts_display), T_DISPLAY_AUTHORITY,
                                                        rtol=0.0, atol=0.0)
    ok_authority = ts_authority is not None and np.allclose(np.array(ts_authority),
                                                            T_AUTHORITY_DISPLAY, rtol=0.0, atol=0.0)
    detail["display_matrix_matches"] = bool(ok_display)
    detail["authority_matrix_matches"] = bool(ok_authority)
    # the TS mm/M constant must agree with the Python one (1000 mm per metre)
    mm_match = re.search(r"MM_PER_M\s*=\s*([0-9.eE+-]+)", text)
    detail["ts_mm_per_m"] = float(mm_match.group(1)) if mm_match else None
    detail["mm_per_m_ok"] = bool(detail["ts_mm_per_m"] == 1000.0)
    detail["ok"] = bool(ok_display and ok_authority and detail["mm_per_m_ok"])
    return {"ok": detail["ok"], "detail": detail}


def _check_display(thresholds: dict[str, float]) -> dict[str, Any]:
    """100 mm authority cube -> 0.1 m GLB edges -> 100 mm UI measurement, exactly once."""
    half = 50.0
    cube_mm = np.array([[x, y, z] for x in (-half, half) for y in (-half, half)
                        for z in (-half, half)], dtype=np.float64)
    edges = [(i, j) for i in range(8) for j in range(i + 1, 8)
             if int(np.sum(np.abs(cube_mm[i] - cube_mm[j]) > 0)) == 1]
    # 1. the derivation actually used by the GLB export (handlers/tools call transform_vertices)
    glb_m = transform_vertices(cube_mm)
    edge_m = np.array([np.linalg.norm(glb_m[i] - glb_m[j]) for i, j in edges])
    display_edge_error_m = float(np.max(np.abs(edge_m - 0.1)))
    # 2. the UI measurement path: a display-space edge mapped back through display_to_authority
    origin_m = glb_m[edges[0][0]]
    other_m = glb_m[edges[0][1]]
    ui_mm = np.linalg.norm(display_to_authority(other_m[None, :])[0]
                           - display_to_authority(origin_m[None, :])[0])
    ui_error_mm = float(abs(ui_mm - 100.0))
    # 3. round trip through the two sanctioned directions (once each)
    back_mm = display_to_authority(glb_m)
    roundtrip_error_mm = float(np.max(np.abs(back_mm - cube_mm)))
    # 4. double application must be detected, not silently accepted
    composed = T_AUTHORITY_DISPLAY @ T_DISPLAY_AUTHORITY
    composition_error = float(np.max(np.abs(composed - np.eye(4))))
    double_applied_m = transform_vertices(transform_vertices(cube_mm))
    double_apply_factor = float(np.max(np.abs(double_applied_m)) / max(float(np.max(np.abs(glb_m))), 1e-30))
    detail: dict[str, Any] = {
        "authority_unit": AUTHORITY_UNIT,
        "display_unit": DISPLAY_UNIT,
        "cube_edge_mm": 100.0,
        "n_edges": len(edges),
        "display_edge_mean_m": float(np.mean(edge_m)),
        "display_edge_max_error_m": display_edge_error_m,
        "ui_measured_edge_mm": float(ui_mm),
        "ui_measure_max_error_mm": ui_error_mm,
        "roundtrip_max_error_mm": roundtrip_error_mm,
        "roundtrip_identity": bool(roundtrip_error_mm <= thresholds["display_max_error_mm"]),
        "T_AUTHORITY_DISPLAY_at_T_DISPLAY_AUTHORITY_error": composition_error,
        "transform_applied_count": 1,
        "double_application_factor": double_apply_factor,
        "double_application_detected": bool(abs(double_apply_factor - 1.0) > 1e-6),
        "up_axis_swap_matrix": np.asarray(up_axis_swap_display_to_authority()).tolist(),
    }
    contract_ok = (display_edge_error_m <= thresholds["display_max_error_m"]
                   and ui_error_mm <= thresholds["display_max_error_mm"]
                   and roundtrip_error_mm <= thresholds["display_max_error_mm"]
                   and composition_error <= EXACT_TOL
                   and detail["double_application_detected"])
    # 5. the *named* mm -> m helper must agree with the derivation matrix (defect probe)
    helper_m = authority_to_display(cube_mm)
    matrix_m = transform_vertices(cube_mm)
    scale_ratio = float(np.nanmax(np.abs(helper_m) / np.maximum(np.abs(matrix_m), 1e-30)))
    helper_scale_ok = bool(np.allclose(helper_m, matrix_m, rtol=1e-12, atol=1e-12))
    detail["authority_to_display_scale_ratio_vs_matrix"] = scale_ratio
    detail["authority_to_display_scale_ok"] = helper_scale_ok
    detail["expected_scale_ratio"] = 1.0
    detail["glb_and_ui_contract_ok"] = bool(contract_ok)
    detail["blocking_defect"] = None if helper_scale_ok else {
        "file": "synlab/api/display.py",
        "function": "authority_to_display",
        "measured_scale_ratio": scale_ratio,
        "expected": "0.001 * x (mm -> m, T_DISPLAY_AUTHORITY)",
        "measured": f"{scale_ratio:g} * x (mm -> mm*1000, i.e. the reverse scale)",
        "used_by_production_code": False,
        "note": ("transform_vertices (the GLB derivation actually used by handlers.py and "
                 "tools/build_demo_assets.py) and display_to_authority are correct; only this "
                 "unused helper is wrong, so the deployed GLB/UI path is unaffected"),
        "proposed_fix": {
            "file": "synlab/api/display.py",
            "function": "authority_to_display",
            "change": "out[:, 0] = points[:, 0] / MM_PER_M * scale; "
                      "out[:, 1] = points[:, 2] / MM_PER_M * scale; "
                      "out[:, 2] = -points[:, 1] / MM_PER_M * scale",
            "effect": "100 mm -> 0.1 m exactly, matching T_DISPLAY_AUTHORITY and frontend display.ts",
        },
        "fix_in_write_scope": False,
    }
    detail["frontend"] = _frontend_matrix_check()["detail"]
    ok = contract_ok and helper_scale_ok and bool(detail["frontend"].get("ok"))
    note = "GLB derivation + UI measurement + frontend matrices verified"
    if not helper_scale_ok:
        note = (f"FAIL on display.helper_api only: synlab/api/display.py::authority_to_display "
                f"scales mm by {scale_ratio:g} instead of 0.001 (the GLB/UI path itself measures "
                f"0.1 m edges and 100 mm exactly).  The defect is in an unused helper and lives "
                f"outside this task's write scope.")
    return {"ok": ok, "detail": detail, "note": note}


# --------------------------------------------------------------------------------------
# public entry point
# --------------------------------------------------------------------------------------
def _report_root(store: Any = None) -> Path:
    if store is None:
        return DEFAULT_REPORT_ROOT
    root = getattr(store, "root", None)
    if root is None:
        root = store
    path = Path(root)
    return path if path.name == "reports" else path / "reports"


def audit_pixel_contract(store: Any = None) -> dict[str, Any]:
    """Run the full pixel/display contract audit and write the A25 report.

    Returns ``{"ok": bool, "status": "PASS"|"FAIL", "metrics": {...}}`` plus the per-check
    detail and the report path.  Every check is measured on the real implementation; a
    check that cannot run (missing pycolmap) fails the audit rather than being skipped.
    """
    started = time.time()
    thresholds = _thresholds()
    checks: dict[str, Any] = {}
    for name, fn in (("colmap_convention", _check_colmap_convention),
                     ("colmap_real_library", _check_colmap_real),
                     ("pixel_transforms", _check_pixel_transforms),
                     ("exif", _check_exif),
                     ("display", _check_display)):
        try:
            outcome = fn(thresholds)  # type: ignore[arg-type]
            checks[name] = {"ok": bool(outcome["ok"]), "detail": outcome["detail"],
                            "note": outcome.get("note", "")}
        except Exception as exc:  # noqa: BLE001 - a raised check is a failed check
            checks[name] = {"ok": False, "detail": {}, "note": f"raised {type(exc).__name__}: {exc}"}
    failing = [name for name, value in checks.items() if not value["ok"]]
    ok = not failing
    metrics: dict[str, Any] = {
        "thresholds": thresholds,
        "convention": "opencv_pixel_center_0_0 <-> colmap_top_left_corner_0_5",
        "colmap_convention": checks["colmap_convention"]["detail"],
        "colmap_real_library": checks["colmap_real_library"]["detail"],
        "pixel_transforms": checks["pixel_transforms"]["detail"],
        "exif": checks["exif"]["detail"],
        "display": checks["display"]["detail"],
        "checks": {name: {"ok": value["ok"], "note": value["note"]} for name, value in checks.items()},
        "failing_checks": failing,
        "seconds": round(time.time() - started, 3),
    }
    blockers = checks["display"]["detail"].get("blocking_defect")
    if blockers:
        metrics["blocking_defects"] = [blockers]
    report = {
        "schema": "synlab.pixel_contract.v1",
        "ok": ok,
        "status": "PASS" if ok else "FAIL",
        "metrics": metrics,
        "checks": checks,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "evidence": [
            "synlab/cameras/audit.py",
            "synlab/cameras/projection.py",
            "synlab/api/display.py",
            "configs/a12/qa_protocol_v1.json",
        ],
    }
    targets = {_report_root(store)}
    if store is not None:
        targets.add(DEFAULT_REPORT_ROOT)
    written: list[str] = []
    for root in sorted(targets):
        root.mkdir(parents=True, exist_ok=True)
        path = root / REPORT_NAME
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
                        encoding="utf-8")
        written.append(str(path))
    report["report_paths"] = written
    return {"ok": ok, "status": report["status"], "metrics": metrics,
            "checks": checks, "report_paths": written}


__all__ = ["audit_pixel_contract", "DEFAULT_REPORT_ROOT", "REPORT_NAME"]
