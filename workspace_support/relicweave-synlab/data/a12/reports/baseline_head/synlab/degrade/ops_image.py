"""OpenCV/numpy image primitives for the I axes (plan 15.3, 30.2 rows 3–5).

Every function here is a pure function of its arguments; the only randomness is the
explicit ``rng`` argument of :func:`sensor_noise`, which the caller derives from the frozen
:class:`~synlab.schemas.runtime.DegradationBasis` (never from a fresh global stream).

Image payload contract (``synlab.degrade.sources``)::

    frame = {
        "view_id": str,
        "rgb": (H, W, 3) uint8          delivered, encoded pixels
        "rgb_linear": (H, W, 3) float32 pre-response sensor linear signal
        "encoding": "LINEAR" | "GAMMA_SRGB"
        "K": (3, 3) float64, "T_WC": (4, 4) float64, "dist": (k,) float64
        "image_size": (W, H)            optional; derived from rgb when absent
        "depth_z": (H, W) float32       optional, invalid = NaN
        "valid": bool
    }

All I axes work on the **post-sensor linear** plane (``rgb_linear``) and rewrite ``rgb``
through the frame's declared encoding.  For the linear operations (PSF, motion, exposure,
white balance, digital gain, resampling) that plane is the correct place: convolution and
scaling commute with the linear sensor chain, so the PSF is not re-drawn on top of a
re-rendered scene and the axis stays a single factor (plan 30.9: "前者在 shot noise 前；不把
暗/亮合为一个序列").  I03 is the one axis whose *content* is the sensor noise model, and it
uses exactly the declared formula ``y = Poisson(g·x)/g + N(0, sigma^2)`` with
``x = max(L·2^EV, 0)``.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ..errors import ErrorCode, SynLabError
from .sources import ENCODING_GAMMA as ENCODING_GAMMA_SRGB
from .sources import ENCODING_LINEAR

DOMAIN_SENSOR_LINEAR = "SENSOR_LINEAR"

#: Fixed white-balance direction (plan 15.3 I05: "固定方向向量"): +R / -B, G anchored.
WB_DIRECTION = (1.0, 0.0, -1.0)

#: Fixed motion direction in degrees (plan 15.3 I02: the direction is a frozen decision).
MOTION_DIRECTION_DEG = 27.0

FULL_SCALE = 255.0


# ---------------------------------------------------------------------------- frame access
def frames_of(bundle: Any) -> list[dict[str, Any]]:
    frames = bundle.get("frames") if hasattr(bundle, "get") else None
    if not frames:
        raise SynLabError(
            ErrorCode.NA_NOT_APPLICABLE,
            "image payload has no 'frames'; the I axes need delivered views "
            "(frames: view_id/rgb/rgb_linear/encoding/K)",
            stage="degrade.image.frames_of",
        )
    return list(frames)


def frame_linear(frame: dict[str, Any]) -> np.ndarray:
    """Post-sensor linear signal of one frame as float32 (H,W,3)."""
    linear = frame.get("rgb_linear")
    if linear is None:
        rgb = frame.get("rgb")
        if rgb is None:
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              "frame carries neither rgb_linear nor rgb",
                              stage="degrade.image.frame_linear")
        linear = np.asarray(rgb, dtype=np.float32) / FULL_SCALE
    linear = np.asarray(linear, dtype=np.float32)
    if linear.ndim != 3 or linear.shape[2] != 3:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"rgb_linear must be (H,W,3), got {linear.shape}",
                          stage="degrade.image.frame_linear")
    return linear


def frame_encoding(frame: dict[str, Any]) -> str:
    return str(frame.get("encoding", ENCODING_LINEAR))


def encode_linear(linear: np.ndarray, encoding: str) -> np.ndarray:
    """Encode a linear signal into uint8 with the *declared* response (never silently sRGB)."""
    work = np.clip(np.asarray(linear, dtype=np.float32), 0.0, 1.0)
    enc = str(encoding).upper()
    if enc in (ENCODING_GAMMA_SRGB, "SRGB", "GAMMA"):
        srgb = np.where(work <= 0.0031308, work * 12.92,
                        1.055 * np.power(np.maximum(work, 0.0), 1.0 / 2.4) - 0.055)
        work = np.clip(srgb, 0.0, 1.0)
    elif enc not in (ENCODING_LINEAR, "NONE"):
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"unknown frame encoding {encoding!r}; expected "
                          f"{ENCODING_LINEAR!r} or {ENCODING_GAMMA_SRGB!r}",
                          stage="degrade.image.encode_linear")
    return np.rint(work * FULL_SCALE).astype(np.uint8)


def rewritten_frame(frame: dict[str, Any], linear: np.ndarray, **updates: Any) -> dict[str, Any]:
    """New frame dict with a rewritten linear plane, encoding-consistent ``rgb``."""
    out = dict(frame)
    linear = np.asarray(linear, dtype=np.float32)
    out["rgb_linear"] = linear
    out["rgb"] = encode_linear(linear, frame_encoding(frame))
    out["image_size"] = (int(linear.shape[1]), int(linear.shape[0]))
    out.update(updates)
    return out


# ---------------------------------------------------------------------------- PSF
def gaussian_psf(sigma_px: float) -> tuple[np.ndarray, dict[str, Any]]:
    """Normalised Gaussian PSF kernel plus its frozen description."""
    sigma = float(sigma_px)
    if sigma <= 0:
        raise SynLabError(ErrorCode.OPERATOR_NOT_REALIZED,
                          "gaussian_psf needs sigma_px > 0 (level 0 must not be re-applied)",
                          stage="degrade.image.gaussian_psf")
    radius = max(int(np.ceil(3.0 * sigma)), 1)
    y, x = np.mgrid[-radius:radius + 1, -radius:radius + 1].astype(np.float64)
    kernel = np.exp(-(x * x + y * y) / (2.0 * sigma * sigma))
    kernel /= kernel.sum()
    return kernel.astype(np.float32), {"psf": "GAUSSIAN", "sigma_px": sigma,
                                       "kernel_shape": list(kernel.shape)}


def motion_kernel(length_px: float, angle_deg: float) -> tuple[np.ndarray, dict[str, Any]]:
    """Directional (single-exposure) linear-motion PSF of the given length and direction.

    ``angle_deg`` is measured in **array coordinates** (x right, y down): the trajectory is the
    line through the kernel centre along ``(cos, sin)``.  The same direction vector is used by
    :func:`motion_integrate`, so the two variants of I02 blur along one frozen trajectory.
    """
    import cv2

    length = int(max(round(float(length_px)), 2))
    size = length if length % 2 == 1 else length + 1
    kernel = np.zeros((size, size), dtype=np.float32)
    theta = np.radians(float(angle_deg))
    direction = np.array([np.cos(theta), np.sin(theta)], dtype=np.float64)
    centre = np.array([(size - 1) / 2.0, (size - 1) / 2.0])
    half = (length - 1) / 2.0
    p0 = centre - direction * half
    p1 = centre + direction * half
    cv2.line(kernel, (int(round(p0[0])), int(round(p0[1]))),
             (int(round(p1[0])), int(round(p1[1]))), 1.0, 1)
    total = float(kernel.sum())
    if total <= 1e-9:
        raise SynLabError(ErrorCode.OPERATOR_NOT_REALIZED, "motion kernel vanished",
                          stage="degrade.image.motion_kernel")
    kernel = (kernel / total).astype(np.float32)
    n_support = int(np.count_nonzero(kernel > 1e-6))
    return kernel, {"psf": "DIRECTIONAL_KERNEL", "length_px": float(length_px),
                    "angle_deg": float(angle_deg), "kernel_shape": list(kernel.shape),
                    "kernel_support_px": n_support,
                    "angle_convention": "array_coordinates_x_right_y_down"}


def convolve(image: np.ndarray, kernel: np.ndarray) -> np.ndarray:
    import cv2

    return cv2.filter2D(np.asarray(image, dtype=np.float32), -1,
                        np.asarray(kernel, dtype=np.float32), borderType=cv2.BORDER_REFLECT101)


def motion_integrate(image: np.ndarray, *, length_px: float, angle_deg: float,
                     samples: int) -> tuple[np.ndarray, dict[str, Any]]:
    """Exposure-period motion integral: average of ``samples`` sub-exposures along the path."""
    import cv2

    n = int(max(samples, 2))
    length = float(length_px)
    if length <= 0:
        raise SynLabError(ErrorCode.OPERATOR_NOT_REALIZED,
                          "motion_integrate needs length_px > 0",
                          stage="degrade.image.motion_integrate")
    theta = np.radians(float(angle_deg))
    direction = np.array([np.cos(theta), np.sin(theta)], dtype=np.float64)
    offsets = np.linspace(-0.5, 0.5, n) * length
    acc = np.zeros_like(np.asarray(image, dtype=np.float32))
    height, width = acc.shape[0], acc.shape[1]
    for offset in offsets:
        shift = direction * float(offset)
        M = np.array([[1.0, 0.0, shift[0]], [0.0, 1.0, shift[1]]], dtype=np.float64)
        acc += cv2.warpAffine(np.asarray(image, dtype=np.float32), M, (width, height),
                              flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    return acc / float(n), {"psf": "EXPOSURE_PERIOD_INTEGRAL", "length_px": length,
                            "angle_deg": float(angle_deg), "sub_exposures": n,
                            "trajectory_px": [float(offsets.min()), float(offsets.max())]}


# ---------------------------------------------------------------------------- sensor / ISP
def sensor_noise(linear: np.ndarray, *, photon_gain: float, read_sigma: float,
                 exposure_ev: float, rng: np.random.Generator
                 ) -> tuple[np.ndarray, dict[str, Any]]:
    """``y = Poisson(g·x)/g + N(0, sigma^2)`` with ``x = max(L·2^EV, 0)`` (plan 15.3 I03)."""
    gain = float(photon_gain)
    if gain <= 0:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, f"photon gain must be > 0, got {gain}",
                          stage="degrade.image.sensor_noise")
    x = np.maximum(np.asarray(linear, dtype=np.float64) * float(2.0 ** float(exposure_ev)), 0.0)
    photons = rng.poisson(x * gain) / gain
    noisy = photons
    if float(read_sigma) > 0:
        noisy = noisy + rng.normal(scale=float(read_sigma), size=noisy.shape)
    info = {"sensor_model": "POISSON_READ_LINEAR",
            "formula": "y = Poisson(g*x)/g + N(0, sigma_read^2), x = max(L*2^EV, 0)",
            "photon_gain": gain, "read_noise_sigma": float(read_sigma),
            "exposure_ev": float(exposure_ev)}
    return noisy.astype(np.float32), info


def exposure_scale(linear: np.ndarray, ev: float, *, saturation: float = 1.0
                   ) -> tuple[np.ndarray, dict[str, Any]]:
    """Exposure gain before the photon count: ``L' = clip(L·2^EV, 0, saturation)``."""
    factor = float(2.0 ** float(ev))
    work = np.asarray(linear, dtype=np.float32) * factor
    saturated = float(np.mean(work >= saturation)) if work.size else 0.0
    work = np.clip(work, 0.0, float(saturation))
    return work.astype(np.float32), {"op": "exposure_gain_before_photons", "exposure_ev": float(ev),
                                     "factor": factor, "saturated_fraction": saturated,
                                     "saturation": float(saturation)}


def digital_gain(linear: np.ndarray, factor: float) -> tuple[np.ndarray, dict[str, Any]]:
    work = np.asarray(linear, dtype=np.float32) * float(factor)
    return work.astype(np.float32), {"op": "digital_gain_after_sensor", "factor": float(factor),
                                     "note": "digital gain is not interchangeable with exposure_ev"}


def white_balance(linear: np.ndarray, deviation: float) -> tuple[np.ndarray, dict[str, Any]]:
    """Fixed-direction white-balance error: gains ``1 + d·direction`` (green anchored)."""
    direction = np.asarray(WB_DIRECTION, dtype=np.float64)
    gains = 1.0 + float(deviation) * direction
    work = np.asarray(linear, dtype=np.float32) * gains.astype(np.float32).reshape(1, 1, 3)
    return work.astype(np.float32), {"op": "white_balance", "deviation": float(deviation),
                                     "direction": list(WB_DIRECTION),
                                     "gains": [float(v) for v in gains]}


# ---------------------------------------------------------------------------- derivation
def downsample_antialiased(linear: np.ndarray, scale: float, K: np.ndarray
                           ) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    """Anti-aliased resample (``INTER_AREA``) with the matching pixel transform and ``K``."""
    import cv2

    from ..cameras.api import pixel_transform_crop_resize

    s = float(scale)
    if not 0.0 < s < 1.0:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"resize scale must be in (0,1) for a downsampling axis, got {s}",
                          stage="degrade.image.downsample_antialiased")
    src = np.asarray(linear, dtype=np.float32)
    height, width = src.shape[0], src.shape[1]
    new_w = max(int(round(width * s)), 8)
    new_h = max(int(round(height * s)), 8)
    out = cv2.resize(src, (new_w, new_h), interpolation=cv2.INTER_AREA)
    A, K_new = pixel_transform_crop_resize(0.0, 0.0, new_w / float(width), new_h / float(height),
                                           np.asarray(K, dtype=np.float64))
    info = {"op": "antialiased_downsample", "scale_requested": s,
            "scale_realized": [new_w / float(width), new_h / float(height)],
            "interpolation": "INTER_AREA", "size_before": [width, height],
            "size_after": [new_w, new_h], "A": np.asarray(A).tolist()}
    return out, np.asarray(K_new, dtype=np.float64), np.asarray(A, dtype=np.float64), info


def jpeg_roundtrip(rgb_uint8: np.ndarray, quality: int) -> tuple[np.ndarray, bytes, dict[str, Any]]:
    """Real JPEG encode/decode; the level-0 identity never calls this (no re-encode)."""
    import cv2

    q = int(np.clip(int(quality), 1, 100))
    ok, buf = cv2.imencode(".jpg", np.asarray(rgb_uint8, dtype=np.uint8),
                           [int(cv2.IMWRITE_JPEG_QUALITY), q])
    if not ok:
        raise SynLabError(ErrorCode.OPERATOR_NOT_REALIZED, "JPEG encoding failed",
                          stage="degrade.image.jpeg_roundtrip")
    data = bytes(buf.tobytes())
    decoded = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if decoded is None:
        raise SynLabError(ErrorCode.OPERATOR_NOT_REALIZED, "JPEG decoding failed",
                          stage="degrade.image.jpeg_roundtrip")
    return np.asarray(decoded, dtype=np.uint8), data, {"codec": "JPEG", "quality": q,
                                                       "bytes": len(data)}


# ---------------------------------------------------------------------------- measurements
def _luma(image: np.ndarray) -> np.ndarray:
    arr = np.asarray(image, dtype=np.float64)
    if arr.ndim == 3:
        return 0.2126 * arr[..., 0] + 0.7152 * arr[..., 1] + 0.0722 * arr[..., 2]
    return arr


def sharpness(image: np.ndarray) -> float:
    """Variance of the Laplacian of the luma plane (real, monotone in blur for one scene)."""
    import cv2

    return float(cv2.Laplacian(_luma(image).astype(np.float32), cv2.CV_32F).var())


def gradient_energy(image: np.ndarray) -> float:
    """Mean squared gradient magnitude — the quantity a PSF convolution reduces."""
    import cv2

    lum = _luma(image).astype(np.float32)
    gx = cv2.Sobel(lum, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(lum, cv2.CV_32F, 0, 1, ksize=3)
    return float(np.mean(gx * gx + gy * gy))


def dominant_direction_deg(image: np.ndarray) -> float:
    """Dominant gradient-orientation + 90 deg (the blur direction) from the structure tensor."""
    import cv2

    lum = _luma(image).astype(np.float32)
    gx = cv2.Sobel(lum, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(lum, cv2.CV_32F, 0, 1, ksize=3)
    jxx, jyy, jxy = float(np.mean(gx * gx)), float(np.mean(gy * gy)), float(np.mean(gx * gy))
    angle = 0.5 * np.degrees(np.arctan2(2.0 * jxy, jxx - jyy))
    return float((angle + 90.0) % 180.0)


def blockiness(rgb_uint8: np.ndarray, block: int = 8) -> float:
    """Mean |difference| across 8-pixel block boundaries minus the interior mean."""
    arr = np.asarray(rgb_uint8, dtype=np.float64)
    if arr.ndim == 3:
        arr = arr.mean(axis=2)
    if arr.shape[0] <= block or arr.shape[1] <= block:
        return 0.0
    vertical = np.abs(np.diff(arr, axis=1))
    horizontal = np.abs(np.diff(arr, axis=0))
    v_boundary = vertical[:, block - 1::block].mean() if vertical[:, block - 1::block].size else 0.0
    h_boundary = horizontal[block - 1::block, :].mean() if horizontal[block - 1::block, :].size else 0.0
    v_inner = np.delete(vertical, np.s_[block - 1::block], axis=1).mean()
    h_inner = np.delete(horizontal, np.s_[block - 1::block], axis=0).mean()
    return float(0.5 * ((v_boundary - v_inner) + (h_boundary - h_inner)))


def noise_sigma_estimate(linear: np.ndarray) -> float:
    """Robust high-frequency noise estimate (MAD of the 3x3 Laplacian residual / scale)."""
    import cv2

    lum = _luma(np.asarray(linear, dtype=np.float32)).astype(np.float32)
    resid = cv2.Laplacian(lum, cv2.CV_32F, ksize=3)
    mad = float(np.median(np.abs(resid - np.median(resid))))
    return float(mad / 0.6745 / np.sqrt(20.0))


def linear_stats(linear: np.ndarray) -> dict[str, float]:
    """Mean/variance of the bright and dark halves plus the saturation fraction."""
    arr = np.asarray(linear, dtype=np.float64)
    lum = _luma(arr)
    flat = lum.ravel()
    if flat.size == 0:
        return {"mean": 0.0, "std": 0.0, "bright_std": 0.0, "dark_std": 0.0,
                "saturated_fraction": 0.0}
    threshold = float(np.quantile(flat, 0.65))
    bright = flat[flat >= threshold]
    dark = flat[flat < float(np.quantile(flat, 0.35))]
    return {
        "mean": float(flat.mean()),
        "std": float(flat.std()),
        "bright_mean": float(bright.mean()) if bright.size else 0.0,
        "bright_std": float(bright.std()) if bright.size else 0.0,
        "dark_mean": float(dark.mean()) if dark.size else 0.0,
        "dark_std": float(dark.std()) if dark.size else 0.0,
        "saturated_fraction": float(np.mean(flat >= 0.999)),
    }


def channel_means(linear: np.ndarray) -> list[float]:
    arr = np.asarray(linear, dtype=np.float64)
    return [float(arr[..., c].mean()) for c in range(arr.shape[-1])]


def long_edge(image: np.ndarray) -> int:
    arr = np.asarray(image)
    return int(max(arr.shape[0], arr.shape[1]))


__all__ = [
    "DOMAIN_SENSOR_LINEAR", "WB_DIRECTION", "MOTION_DIRECTION_DEG",
    "frames_of", "frame_linear", "frame_encoding", "encode_linear", "rewritten_frame",
    "gaussian_psf", "motion_kernel", "convolve", "motion_integrate",
    "sensor_noise", "exposure_scale", "digital_gain", "white_balance",
    "downsample_antialiased", "jpeg_roundtrip",
    "sharpness", "gradient_energy", "dominant_direction_deg", "blockiness",
    "noise_sigma_estimate", "linear_stats", "channel_means", "long_edge",
]
