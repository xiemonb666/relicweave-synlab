"""Ordered imaging chain (plan 13.3, 30.2 stage order).

The order is frozen and validated at construction time::

    scene/physical
      -> exposure amount + optical defocus / exposure-period motion integration
      -> sensor sampling and noise
      -> gain / white balance / camera response / ISP
      -> quantisation / encoding
      -> legal crop / size derivation

Consequences that the code enforces rather than documents away:

* ``exposure_gain`` (I04) acts **before** photon counting.  Digital gain is a separate
  variant and is never interchangeable with the exposure amount.
* I06 (highlight clipping), I07 (occlusion), I08 (frame selection) are *scene* changes
  and must be re-rendered; :meth:`ImagingSpec.assert_scene_only` raises
  ``EXPERIMENT_PROTOCOL_VIOLATION`` if such a knob is routed through this module.
* Only JPEG output is labelled ``ISP_PROXY``/``JPEG_PROXY``; a linear-model claim on
  gamma/JPEG data is forbidden (plan 13.3).
* The final crop/resize is the *only* step that changes the pixel contract; it returns
  the affine ``A`` and ``K_new = A K`` alongside the image (plan 30.3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..cameras.projection import (
    crop_resize_matrix,
    letterbox_transform,
    pixel_transform_crop_resize,
)
from ..errors import ErrorCode, SynLabError
from ..roles import SOURCE_SENSOR_SIM

#: Ordered stage identifiers; the order is part of the interface.
STAGE_ORDER: tuple[str, ...] = (
    "SCENE", "EXPOSURE_OPTICS", "SENSOR_NOISE", "GAIN_ISP", "QUANTIZE_ENCODE",
    "IMAGE_DERIVATION",
)

#: Knobs that belong to the scene and therefore require a re-render.
SCENE_ONLY_KNOBS: tuple[str, ...] = ("highlight_clip", "occluder", "frame_selection",
                                     "lighting", "physical_pose")

#: Frozen label for the linear imaging proxy used when only encoded images exist.
LABEL_LINEAR_MODEL = "LINEAR_SENSOR_MODEL"
LABEL_ISP_PROXY = "ISP_PROXY"
LABEL_JPEG_PROXY = "JPEG_PROXY"


@dataclass
class ImagingSpec:
    """Frozen imaging parameters.  Defaults are a **true identity** pipeline."""

    # -- exposure / optics (before photon counting)
    exposure_ev: float = 0.0
    #: Optical defocus as an explicit PSF: Gaussian sigma in pixels at the image plane.
    defocus_sigma_px: float = 0.0
    defocus_depth_dependent: bool = True
    #: Motion integration: number of sub-exposures and the pose amplitude in mm/px.
    motion_samples: int = 1
    motion_amplitude_px: float = 0.0
    motion_kernel: tuple[float, ...] = (0.5, 0.5)
    # -- sensor
    effective_gain: float = 1.0
    read_noise_sigma: float = 0.0
    sensor_saturation: float = 1.0
    sensor_black_level: float = 0.0
    # -- gain / ISP
    digital_gain: float = 1.0
    white_balance: tuple[float, float, float] = (1.0, 1.0, 1.0)
    color_matrix: np.ndarray | None = None
    response: str = "LINEAR"          # LINEAR | BT709 | SRGB | REC709_OETF
    response_gamma: float = 1.0
    sharpening: float = 0.0
    denoise: float = 0.0
    # -- quantisation / encoding
    bit_depth: int = 8
    encode: str = "PNG"               # PNG | JPEG | NONE
    jpeg_quality: int = 95
    jpeg_subsampling: int = 0
    # -- derivation (image-space, after encoding coordinates are fixed)
    crop_origin: tuple[int, int] | None = None
    resize_scale: tuple[float, float] | None = None
    letterbox_pad: tuple[int, int] = (0, 0)
    exif_orientation: int = 1
    # -- bookkeeping
    version: str = "1.0"
    extra: dict[str, Any] = field(default_factory=dict)

    def assert_scene_only(self) -> None:
        for knob in SCENE_ONLY_KNOBS:
            if knob in self.extra:
                raise SynLabError(
                    ErrorCode.EXPERIMENT_PROTOCOL_VIOLATION,
                    f"{knob!r} is a scene-level change and must be re-rendered, not "
                    f"applied by the imaging chain (plan 13.3)",
                    stage="observe.imaging.ImagingSpec",
                )

    def stage_plan(self) -> list[str]:
        return list(STAGE_ORDER)

    def is_identity(self) -> bool:
        """True when nothing at all is changed (used for level-0 identity checks)."""
        return (
            self.exposure_ev == 0.0 and self.defocus_sigma_px == 0.0
            and self.motion_samples == 1 and self.motion_amplitude_px == 0.0
            and self.digital_gain == 1.0 and self.read_noise_sigma == 0.0
            and tuple(self.white_balance) == (1.0, 1.0, 1.0)
            and self.color_matrix is None and self.response == "LINEAR"
            and self.response_gamma == 1.0 and self.sharpening == 0.0 and self.denoise == 0.0
            and self.crop_origin is None and self.resize_scale is None
            and tuple(self.letterbox_pad) == (0, 0) and self.exif_orientation == 1
        )


@dataclass
class ImagingResult:
    image: np.ndarray                 # (H,W,3) uint8 encoded, delivered pixels
    linear: np.ndarray                # (H,W,3) float32 post-sensor linear (pre-response)
    scene_linear: np.ndarray          # (H,W,3) float32 linear scene radiance
    uncertain_mask: np.ndarray        # (H,W) bool in *delivered* pixel coordinates
    A: np.ndarray                     # (3,3) pixel affine from the pipeline grid
    K_new: np.ndarray                 # (3,3) intrinsics of the delivered image
    image_size: tuple[int, int]
    labels: list[str]
    stages: list[dict[str, Any]]
    meta: dict[str, Any]
    encode_bytes: bytes | None = None

    @property
    def is_isp_proxy(self) -> bool:
        return any(lbl in (LABEL_ISP_PROXY, LABEL_JPEG_PROXY) for lbl in self.labels)


def _gaussian_psf(shape: tuple[int, int], sigma_px: float) -> np.ndarray:
    radius = max(int(np.ceil(3.0 * sigma_px)), 1)
    y, x = np.mgrid[-radius:radius + 1, -radius:radius + 1].astype(np.float64)
    psf = np.exp(-(x * x + y * y) / (2.0 * sigma_px * sigma_px))
    return psf / psf.sum()


def _motion_psf(spec: ImagingSpec) -> np.ndarray:
    """OpenCV linear-motion PSF; the trajectory is the frozen sample set."""
    if spec.motion_samples <= 1 or spec.motion_amplitude_px <= 0:
        raise SynLabError(ErrorCode.OPERATOR_NOT_REALIZED,
                          "motion PSF requested without samples/amplitude",
                          stage="observe.imaging._motion_psf")
    length = max(int(round(spec.motion_amplitude_px * 2.0)) + 1, 3)
    if length % 2 == 0:
        length += 1
    kernel = np.zeros((length, length), dtype=np.float32)
    kernel[length // 2, :] = 1.0
    # A straight-line exposure-period trajectory; a curved trajectory is a replaceable
    # variant and must bring its own frozen samples.
    ang = float(np.rad2deg(np.arctan2(0.0, 1.0)))
    return _rotate_kernel(kernel, ang)


def _rotate_kernel(kernel: np.ndarray, angle_deg: float) -> np.ndarray:
    import cv2

    h, w = kernel.shape
    M = cv2.getRotationMatrix2D((w / 2.0 - 0.5, h / 2.0 - 0.5), angle_deg, 1.0)
    out = cv2.warpAffine(kernel, M, (w, h), flags=cv2.INTER_LINEAR,
                         borderMode=cv2.BORDER_CONSTANT, borderValue=0.0)
    s = float(out.sum())
    if s <= 1e-12:
        raise SynLabError(ErrorCode.OPERATOR_NOT_REALIZED, "motion kernel is empty",
                          stage="observe.imaging._rotate_kernel")
    return (out / s).astype(np.float32)


def _disc_psf(radius_px: float) -> np.ndarray:
    """Circular aperture PSF (geometric defocus disc) for depth-dependent defocus."""
    r = int(np.ceil(radius_px))
    y, x = np.mgrid[-r:r + 1, -r:r + 1].astype(np.float64)
    disc = ((x * x + y * y) <= radius_px * radius_px).astype(np.float32)
    if disc.sum() <= 0:
        disc[r, r] = 1.0
    return disc / disc.sum()


def _convolve_linear(image: np.ndarray, kernel: np.ndarray) -> np.ndarray:
    import cv2

    out = cv2.filter2D(image.astype(np.float32), -1, kernel.astype(np.float32),
                       borderType=cv2.BORDER_REFLECT101)
    return out


def apply_imaging_chain(scene_linear: np.ndarray, *, K: np.ndarray, dist: np.ndarray | None,
                        uncertain_mask: np.ndarray | None, depth_z: np.ndarray | None,
                        focus_distance_mm: float, rng: np.random.Generator,
                        spec: ImagingSpec | None = None,
                        camera_model: str = "PINHOLE") -> ImagingResult:
    """Run the frozen imaging chain on one linear render.

    ``rng`` is the ``sensor`` sub-stream (``synlab.seeds.make_rng(master, lineage, "sensor")``)
    so that replays are bit-identical.
    """
    spec = spec or ImagingSpec()
    spec.assert_scene_only()
    scene = np.asarray(scene_linear, dtype=np.float32)
    if scene.ndim != 3 or scene.shape[2] != 3:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"scene_linear must be (H,W,3), got {scene.shape}",
                          stage="observe.imaging.apply_imaging_chain")
    if spec.effective_gain <= 0:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"effective_gain must be > 0 (photon scale), got {spec.effective_gain}",
                          stage="observe.imaging.apply_imaging_chain")
    height, width = scene.shape[0], scene.shape[1]
    stages: list[dict[str, Any]] = []
    labels: list[str] = [LABEL_LINEAR_MODEL]
    K = np.asarray(K, dtype=np.float64).copy()
    mask = (np.zeros((height, width), dtype=bool) if uncertain_mask is None
            else np.asarray(uncertain_mask, dtype=bool).copy())

    # ---------------------------------------------------------------- 1. exposure
    exposed = scene * float(2.0 ** spec.exposure_ev)
    stages.append({"stage": "EXPOSURE_OPTICS", "op": "exposure_gain_before_photons",
                   "exposure_ev": spec.exposure_ev, "factor": float(2.0 ** spec.exposure_ev),
                   "digital_gain_applied": False})

    # ------------------------------------------------- 2. optical defocus / motion
    if spec.defocus_sigma_px > 0 or (spec.motion_samples > 1 and spec.motion_amplitude_px > 0):
        psf_meta: dict[str, Any] = {}
        if spec.defocus_depth_dependent and depth_z is not None and spec.defocus_sigma_px > 0:
            # Depth-dependent defocus: run two blurs for the near/far half of the DoF and
            # blend by depth.  The actual PSFs are saved, not a single blur level.
            depth = np.asarray(depth_z, dtype=np.float64)
            valid = np.isfinite(depth)
            near_sigma = spec.defocus_sigma_px
            far_sigma = spec.defocus_sigma_px * 1.6
            lo = _convolve_linear(exposed, _gaussian_psf((height, width), near_sigma))
            hi = _convolve_linear(exposed, _gaussian_psf((height, width), far_sigma))
            if valid.any():
                med = float(np.median(depth[valid]))
                w = np.clip((depth - med) / max(float(np.nanstd(depth[valid])) or 1.0, 1e-6),
                            -1.0, 1.0)
            else:
                w = np.zeros_like(depth)
            w3 = np.nan_to_num(w, nan=0.0)[:, :, None].astype(np.float32)
            blend = 0.5 * (1.0 + w3)
            exposed = (1.0 - blend) * lo + blend * hi
            psf_meta = {"defocus_model": "DEPTH_DEPENDENT_TWO_PSF_BLEND",
                        "sigma_near_px": near_sigma, "sigma_far_px": far_sigma,
                        "focus_distance_mm": float(focus_distance_mm)}
        elif spec.defocus_sigma_px > 0:
            exposed = _convolve_linear(exposed, _gaussian_psf((height, width),
                                                             spec.defocus_sigma_px))
            psf_meta = {"defocus_model": "GAUSSIAN_PSF",
                        "sigma_px": spec.defocus_sigma_px,
                        "focus_distance_mm": float(focus_distance_mm)}
        if spec.motion_samples > 1 and spec.motion_amplitude_px > 0:
            kernel = _motion_psf(spec)
            # Exposure-period integration: accumulate sub-exposures of the trajectory.
            acc = np.zeros_like(exposed)
            shifts = np.linspace(-0.5, 0.5, int(spec.motion_samples)) * spec.motion_amplitude_px
            import cv2

            for shift in shifts:
                M = np.array([[1.0, 0.0, float(shift)], [0.0, 1.0, 0.0]], dtype=np.float64)
                acc += cv2.warpAffine(exposed, M, (width, height), flags=cv2.INTER_LINEAR,
                                      borderMode=cv2.BORDER_REPLICATE)
            exposed = acc / float(len(shifts))
            psf_meta.update({"motion_model": "EXPOSURE_PERIOD_LINEAR_TRAJECTORY",
                             "motion_samples": int(spec.motion_samples),
                             "motion_amplitude_px": float(spec.motion_amplitude_px),
                             "motion_kernel_shape": list(kernel.shape),
                             "trajectory_px": [float(min(shifts)), float(max(shifts))]})
        if psf_meta:
            stages.append({"stage": "EXPOSURE_OPTICS", "op": "psf_applied", **psf_meta})

    # ------------------------------------------------------------------ 3. sensor
    x = np.maximum(exposed, 0.0).astype(np.float64)
    g = float(spec.effective_gain)
    photons = rng.poisson(x * g) / g
    noisy = photons
    if spec.read_noise_sigma > 0:
        noisy = noisy + rng.normal(scale=float(spec.read_noise_sigma), size=noisy.shape)
    noisy = noisy - float(spec.sensor_black_level)
    saturated = None
    if spec.sensor_saturation > 0:
        saturated = (noisy >= spec.sensor_saturation)
        noisy = np.clip(noisy, 0.0, float(spec.sensor_saturation))
    linear = noisy.astype(np.float32)
    stages.append({
        "stage": "SENSOR_NOISE", "op": "poisson_read_noise",
        "effective_gain": g, "read_noise_sigma": float(spec.read_noise_sigma),
        "black_level": float(spec.sensor_black_level),
        "saturation": float(spec.sensor_saturation),
        "formula": "y = Poisson(g*x)/g + N(0, sigma_read^2)",
        "saturated_fraction": float(np.mean(saturated)) if saturated is not None else 0.0,
    })

    # --------------------------------------------------------------- 4. gain / ISP
    work = linear.astype(np.float32)
    if spec.digital_gain != 1.0:
        work = work * float(spec.digital_gain)
        stages.append({"stage": "GAIN_ISP", "op": "digital_gain",
                       "digital_gain": float(spec.digital_gain),
                       "note": "digital gain is NOT interchangeable with exposure_ev"})
    wb = np.asarray(spec.white_balance, dtype=np.float32).reshape(1, 1, 3)
    if not np.allclose(wb, 1.0):
        work = work * wb
        stages.append({"stage": "GAIN_ISP", "op": "white_balance",
                       "gains": wb.ravel().tolist()})
    if spec.color_matrix is not None:
        M = np.asarray(spec.color_matrix, dtype=np.float32)
        if M.shape != (3, 3):
            raise SynLabError(ErrorCode.SCHEMA_INVALID, "color_matrix must be 3x3",
                              stage="observe.imaging.apply_imaging_chain")
        work = work.reshape(-1, 3) @ M.T
        work = work.reshape(height, width, 3).astype(np.float32)
        stages.append({"stage": "GAIN_ISP", "op": "color_matrix",
                       "matrix": M.tolist()})
    if spec.denoise > 0:
        import cv2

        d = float(np.clip(spec.denoise, 0.0, 1.0))
        work = cv2.fastNlMeansDenoisingColored(
            np.clip(work * 255.0, 0, 255).astype(np.uint8), None,
            int(3 + 7 * d), int(3 + 7 * d), 7, 21).astype(np.float32) / 255.0
        stages.append({"stage": "GAIN_ISP", "op": "denoise", "strength": d})
    if spec.sharpening > 0:
        import cv2

        blur = cv2.GaussianBlur(work, (0, 0), 1.0)
        work = work + float(spec.sharpening) * (work - blur)
        stages.append({"stage": "GAIN_ISP", "op": "unsharp_mask",
                       "amount": float(spec.sharpening)})
    response = spec.response.upper()
    if response == "LINEAR":
        pass
    elif response in ("BT709", "SRGB", "REC709_OETF"):
        gamma = 2.4 if response != "SRGB" else 2.4
        a, b = (1.099, 0.099) if response != "SRGB" else (1.055, 0.055)
        work = np.clip(work, 0.0, None)
        work = np.where(work < 0.0031308, work * 12.92,
                        a * np.power(np.maximum(work, 0.0), 1.0 / gamma) - b)
        response = f"{response}(BT709_OETF)"
    elif response == "POWER":
        gamma = float(spec.response_gamma)
        if gamma <= 0:
            raise SynLabError(ErrorCode.SCHEMA_INVALID, "response_gamma must be > 0",
                              stage="observe.imaging.apply_imaging_chain")
        work = np.power(np.clip(work, 0.0, None), 1.0 / gamma)
        response = f"POWER(1/{gamma})"
    else:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, f"unknown response {spec.response!r}",
                          stage="observe.imaging.apply_imaging_chain")
    stages.append({"stage": "GAIN_ISP", "op": "camera_response", "response": response,
                   "gamma": float(spec.response_gamma)})
    if response != "LINEAR" or spec.encode.upper() == "JPEG":
        labels.append(LABEL_ISP_PROXY)
    work = np.clip(work, 0.0, 1.0)

    # ------------------------------------------------------- 5. quantise / encode
    bit_depth = int(spec.bit_depth)
    if bit_depth not in (8, 16):
        raise SynLabError(ErrorCode.SCHEMA_INVALID, f"bit_depth {bit_depth} unsupported",
                          stage="observe.imaging.apply_imaging_chain")
    peak = 255.0 if bit_depth == 8 else 65535.0
    encoded_linear = work
    encode = spec.encode.upper()
    encoded_bytes: bytes | None = None
    if bit_depth == 8:
        quant = np.rint(work * 255.0).astype(np.uint8)
    else:
        quant = np.rint(work * 65535.0).astype(np.uint16)
    if encode == "JPEG":
        import cv2

        if bit_depth != 8:
            raise SynLabError(ErrorCode.SCHEMA_INVALID, "JPEG output requires bit_depth=8",
                              stage="observe.imaging.apply_imaging_chain")
        params = [int(cv2.IMWRITE_JPEG_QUALITY), int(np.clip(spec.jpeg_quality, 1, 100))]
        if spec.jpeg_subsampling:
            params += [int(cv2.IMWRITE_JPEG_OPTIMIZE), 1]
        ok, buf = cv2.imencode(".jpg", quant, params)
        if not ok:
            raise SynLabError(ErrorCode.OPERATOR_NOT_REALIZED, "JPEG encoding failed",
                              stage="observe.imaging.apply_imaging_chain")
        encoded_bytes = bytes(buf.tobytes())
        quant = cv2.imdecode(np.frombuffer(encoded_bytes, dtype=np.uint8),
                             cv2.IMREAD_COLOR)
        if quant is None:
            raise SynLabError(ErrorCode.OPERATOR_NOT_REALIZED, "JPEG decoding failed",
                              stage="observe.imaging.apply_imaging_chain")
        labels.append(LABEL_JPEG_PROXY)
    elif encode == "PNG":
        import cv2

        ok, buf = cv2.imencode(".png", quant)
        if not ok:
            raise SynLabError(ErrorCode.OPERATOR_NOT_REALIZED, "PNG encoding failed",
                              stage="observe.imaging.apply_imaging_chain")
        encoded_bytes = bytes(buf.tobytes())
        quant = cv2.imdecode(np.frombuffer(encoded_bytes, dtype=np.uint8),
                             cv2.IMREAD_UNCHANGED if bit_depth == 16 else cv2.IMREAD_COLOR)
        if quant is None:
            raise SynLabError(ErrorCode.OPERATOR_NOT_REALIZED, "PNG decoding failed",
                              stage="observe.imaging.apply_imaging_chain")
    elif encode == "NONE":
        pass
    else:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, f"unknown encode {spec.encode!r}",
                          stage="observe.imaging.apply_imaging_chain")
    stages.append({"stage": "QUANTIZE_ENCODE", "op": "quantise_encode",
                   "bit_depth": bit_depth, "encode": encode, "peak": peak,
                   "jpeg_quality": int(spec.jpeg_quality) if encode == "JPEG" else None,
                   "bytes": None if encoded_bytes is None else len(encoded_bytes)})

    # --------------------------------------------------- 6. legal crop / derivation
    A = np.eye(3, dtype=np.float64)
    K_new = K.copy()
    image = quant
    if image.ndim == 2:
        image = np.repeat(image[:, :, None], 3, axis=2)
    if spec.crop_origin is not None or spec.resize_scale is not None:
        x0 = int(spec.crop_origin[0]) if spec.crop_origin else 0
        y0 = int(spec.crop_origin[1]) if spec.crop_origin else 0
        crop_w = width - x0
        crop_h = height - y0
        if x0 < 0 or y0 < 0 or crop_w <= 0 or crop_h <= 0:
            raise SynLabError(ErrorCode.SCHEMA_INVALID, "illegal crop origin",
                              stage="observe.imaging.apply_imaging_chain")
        sx, sy = (1.0, 1.0) if spec.resize_scale is None else spec.resize_scale
        out_w = max(int(round(crop_w * sx)), 1)
        out_h = max(int(round(crop_h * sy)), 1)
        # Recompute the *realised* scales from the actual output size so K matches the
        # pixels that were written (plan 30.3: sx/sy from the actual output/crop size).
        sx_real, sy_real = out_w / crop_w, out_h / crop_h
        A_crop, K_crop = pixel_transform_crop_resize(x0, y0, sx_real, sy_real, K)
        import cv2

        cropped = image[y0:, x0:]
        interp = cv2.INTER_AREA if (sx_real < 1.0 or sy_real < 1.0) else cv2.INTER_LINEAR
        image = cv2.resize(cropped, (out_w, out_h), interpolation=interp)
        mask_crop = cv2.resize(mask[y0:, x0:].astype(np.uint8), (out_w, out_h),
                               interpolation=cv2.INTER_NEAREST).astype(bool)
        A, K_new = A_crop, K_crop
        mask = mask_crop
    else:
        out_w, out_h = image.shape[1], image.shape[0]

    if tuple(spec.letterbox_pad) != (0, 0):
        import cv2

        pad_x, pad_y = int(spec.letterbox_pad[0]), int(spec.letterbox_pad[1])
        A_pad, K_pad = letterbox_transform(K_new, pad_x, pad_y)
        image = cv2.copyMakeBorder(image, 0, 0, pad_x, pad_x, cv2.BORDER_CONSTANT,
                                   value=(0, 0, 0))
        mask = np.pad(mask, ((0, 0), (pad_x, pad_x)), constant_values=False)
        image = cv2.copyMakeBorder(image, pad_y, pad_y, 0, 0, cv2.BORDER_CONSTANT,
                                   value=(0, 0, 0))
        mask = np.pad(mask, ((pad_y, pad_y), (0, 0)), constant_values=False)
        A = A_pad @ A
        K_new = K_pad
        out_w, out_h = image.shape[1], image.shape[0]

    if int(spec.exif_orientation) != 1:
        from ..cameras.projection import apply_exif_to_image, exif_transform

        A_exif, K_new, (out_w, out_h) = exif_transform(K_new, int(spec.exif_orientation),
                                                       (out_w, out_h))
        image = apply_exif_to_image(image, int(spec.exif_orientation))
        mask = apply_exif_to_image(mask[:, :, None].astype(np.uint8),
                                   int(spec.exif_orientation))[:, :, 0].astype(bool)
        A = A_exif @ A
    stages.append({"stage": "IMAGE_DERIVATION", "op": "crop_resize_letterbox_exif",
                   "A": A.tolist(), "K_new": K_new.tolist(),
                   "output_size": [int(out_w), int(out_h)],
                   "convention": "cv_pixel_center_0_0",
                   "kernel": "cv2.INTER_AREA" if (spec.resize_scale and
                                                  min(spec.resize_scale) < 1.0) else "cv2.INTER_LINEAR"})

    return ImagingResult(
        image=np.ascontiguousarray(image),
        linear=np.ascontiguousarray(linear),
        scene_linear=np.ascontiguousarray(scene),
        uncertain_mask=mask,
        A=A,
        K_new=K_new,
        image_size=(int(image.shape[1]), int(image.shape[0])),
        labels=labels,
        stages=stages,
        meta={
            "spec": {
                "exposure_ev": spec.exposure_ev, "defocus_sigma_px": spec.defocus_sigma_px,
                "motion_samples": spec.motion_samples,
                "motion_amplitude_px": spec.motion_amplitude_px,
                "effective_gain": spec.effective_gain,
                "read_noise_sigma": spec.read_noise_sigma,
                "digital_gain": spec.digital_gain,
                "white_balance": list(spec.white_balance),
                "response": spec.response, "bit_depth": spec.bit_depth,
                "encode": spec.encode, "jpeg_quality": spec.jpeg_quality,
                "crop_origin": list(spec.crop_origin) if spec.crop_origin else None,
                "resize_scale": list(spec.resize_scale) if spec.resize_scale else None,
                "letterbox_pad": list(spec.letterbox_pad),
                "exif_orientation": int(spec.exif_orientation),
                "version": spec.version,
            },
            "identity": spec.is_identity(),
            "stage_order": list(STAGE_ORDER),
            "labels": list(labels),
            "pixel_convention": "opencv_pixel_center_0_0",
            "camera_model": camera_model,
            "source_kind": SOURCE_SENSOR_SIM,
            "isp_proxy_note": (
                "Only JPEG outputs are labelled ISP_PROXY/JPEG_PROXY.  Highlight clipping "
                "(I06) and occlusion (I07) are scene changes and require a re-render."
            ),
            "encode_bytes_sha256_len": None if encoded_bytes is None else len(encoded_bytes),
        },
        encode_bytes=encoded_bytes,
    )


__all__ = [
    "STAGE_ORDER", "SCENE_ONLY_KNOBS", "LABEL_LINEAR_MODEL", "LABEL_ISP_PROXY",
    "LABEL_JPEG_PROXY", "ImagingSpec", "ImagingResult", "apply_imaging_chain",
    "crop_resize_matrix",
]
