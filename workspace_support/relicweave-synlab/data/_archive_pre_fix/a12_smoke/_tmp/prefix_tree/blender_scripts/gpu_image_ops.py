"""GPU (CUDA/torch) equivalents of the frozen CPU image-domain operators.

The synthesis chain applies its optical operators to **one view at a time** in a Python loop
(``synlab.observe.imaging._convolve_linear`` -> ``cv2.filter2D``, and
``synlab.degrade.ops_image.convolve`` -> the same OpenCV call).  A single 1024x768 convolution
is far too small to be worth a GPU round trip; the win only appears when the views of one
cache are *batched* into a single kernel launch, which is what :func:`convolve_batch` does.

Numerical contract
------------------
``cv2.filter2D`` with ``borderType=BORDER_REFLECT101`` is **cross-correlation** with
reflect-101 padding (the edge sample is not repeated), which is exactly
``torch.nn.functional.conv2d`` with ``padding=k//2`` after ``F.pad(mode="reflect")``.  The
frozen kernels are odd-sized (Gaussian PSF radius ``ceil(3*sigma)`` -> ``2r+1``; motion
kernels are forced odd), so the default centred anchor matches on both sides.
:func:`verify_against_cv2` asserts that equivalence numerically instead of assuming it.
"""

from __future__ import annotations

import numpy as np


def gaussian_psf(sigma_px: float) -> np.ndarray:
    """Same normalised Gaussian kernel as ``synlab.observe.imaging._gaussian_psf``."""
    radius = max(int(np.ceil(3.0 * sigma_px)), 1)
    y, x = np.mgrid[-radius:radius + 1, -radius:radius + 1].astype(np.float64)
    psf = np.exp(-(x * x + y * y) / (2.0 * sigma_px * sigma_px))
    return (psf / psf.sum()).astype(np.float32)


def require_cuda():
    """Import torch lazily and fail loudly if no CUDA device is usable."""
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError(
            "gpu_image_ops needs a CUDA-enabled torch build; "
            f"torch {torch.__version__} reports cuda.is_available()=False")
    return torch


def convolve_batch(images: np.ndarray, kernel: np.ndarray, *, device: str = "cuda",
                   dtype=None) -> np.ndarray:
    """Correlate a stack of images with one kernel on the GPU.

    ``images`` is ``(N, H, W)`` or ``(N, H, W, C)`` float; ``kernel`` is 2-D.  Returns the same
    layout as ``numpy`` float32.  All N images are correlated in one kernel launch.
    """
    import torch
    import torch.nn.functional as F

    torch_dtype = dtype or torch.float32
    arr = np.asarray(images, dtype=np.float32)
    if arr.ndim == 3:
        n, h, w = arr.shape
        channels = 1
    elif arr.ndim == 4:
        n, h, w, channels = arr.shape
    else:
        raise ValueError(f"images must be (N,H,W) or (N,H,W,C), got {arr.shape}")
    k = np.asarray(kernel, dtype=np.float32)
    if k.ndim != 2 or k.shape[0] != k.shape[1] or k.shape[0] % 2 == 0:
        raise ValueError(f"kernel must be odd and square, got {k.shape}")
    r = k.shape[0] // 2

    t = torch.from_numpy(arr).to(device=device, dtype=torch_dtype)
    if channels > 1:
        t = t.permute(0, 3, 1, 2)                      # (N, C, H, W)
    else:
        t = t.unsqueeze(1)                             # (N, 1, H, W)
    # reflect-101 == numpy 'reflect': (d c b a | a b c d | d c b a), edge not repeated
    padded = F.pad(t, (r, r, r, r), mode="reflect")
    weight = torch.from_numpy(k).to(device=device, dtype=torch_dtype).expand(
        t.shape[1], 1, *k.shape).contiguous()
    out = F.conv2d(padded, weight, groups=t.shape[1])
    out = out.squeeze(1) if channels == 1 else out.permute(0, 2, 3, 1)
    return out.contiguous().cpu().numpy().astype(np.float32)


def convolve_cpu_reference(images: np.ndarray, kernel: np.ndarray) -> np.ndarray:
    """The frozen CPU path: ``cv2.filter2D`` per image, exactly as the pipeline calls it."""
    import cv2

    arr = np.asarray(images, dtype=np.float32)
    k = np.asarray(kernel, dtype=np.float32)
    if arr.ndim == 3:
        return np.stack([cv2.filter2D(a, -1, k, borderType=cv2.BORDER_REFLECT101)
                         for a in arr])
    if arr.ndim == 4:
        return np.stack([cv2.filter2D(a, -1, k, borderType=cv2.BORDER_REFLECT101)
                         for a in arr])
    raise ValueError(f"images must be (N,H,W) or (N,H,W,C), got {arr.shape}")


def verify_against_cv2(shape=(2, 64, 64), sigma: float = 2.0, seed: int = 0) -> dict:
    """Measure the GPU-vs-OpenCV difference on random data (never assume bit equality)."""
    rng = np.random.default_rng(seed)
    images = rng.random(shape, dtype=np.float32)
    kernel = gaussian_psf(sigma)
    ref = convolve_cpu_reference(images, kernel)
    got = convolve_batch(images, kernel)
    diff = np.abs(ref.astype(np.float64) - got.astype(np.float64))
    return {"shape": list(shape), "sigma_px": float(sigma),
            "kernel_shape": list(kernel.shape),
            "max_abs_diff": float(diff.max()), "mean_abs_diff": float(diff.mean()),
            "bitwise_equal": bool(np.array_equal(ref, got)),
            "cv2_dtype": str(np.asarray(ref).dtype), "torch_dtype": str(np.asarray(got).dtype),
            "equivalent": bool(diff.max() <= 1e-5)}
