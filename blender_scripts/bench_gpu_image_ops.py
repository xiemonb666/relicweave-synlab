"""Measure whether GPU-batching the image-domain operators is worth it, and by how much.

The frozen pipeline convolves **one view at a time** with ``cv2.filter2D``
(``synlab.observe.imaging._convolve_linear``; the degrade axes call the identical
``synlab.degrade.ops_image.convolve``).  This harness compares that exact CPU call against the
batched torch equivalent in :mod:`gpu_image_ops` on the workload the pipeline really produces:
a 12-view cache at the delivered 1024x768, with the real depth-dependent defocus pair
(sigma and 1.6*sigma).

It also sweeps batch size and sigma, because the honest answer is regime-dependent: a single
small-sigma view is far too small to pay for a GPU round trip, and saying "GPU convolution is
Nx faster" without the regime would be misleading.

Usage::

    python blender_scripts/bench_gpu_image_ops.py --out data/a12/reports/gpu/image_ops.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from blender_scripts.gpu_image_ops import (  # noqa: E402
    convolve_batch, convolve_cpu_reference, gaussian_psf, require_cuda,
    verify_against_cv2,
)


def time_cpu(images: np.ndarray, kernel: np.ndarray, repeat: int) -> float:
    best = float("inf")
    for _ in range(repeat):
        t0 = time.perf_counter()
        convolve_cpu_reference(images, kernel)
        best = min(best, time.perf_counter() - t0)
    return best


def time_gpu(images: np.ndarray, kernel: np.ndarray, repeat: int) -> float:
    import torch

    best = float("inf")
    for _ in range(repeat):
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        out = convolve_batch(images, kernel)
        torch.cuda.synchronize()
        best = min(best, time.perf_counter() - t0)
        del out
    return best


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    ap.add_argument("--height", type=int, default=768)
    ap.add_argument("--width", type=int, default=1024)
    ap.add_argument("--channels", type=int, default=3)
    ap.add_argument("--repeat", type=int, default=5)
    args = ap.parse_args()

    require_cuda()
    import torch

    report: dict = {
        "device": torch.cuda.get_device_name(0),
        "torch": torch.__version__,
        "resolution": [args.width, args.height],
        "channels": args.channels,
        "cpu_reference": "synlab.observe.imaging._convolve_linear -> cv2.filter2D "
                         "(BORDER_REFLECT101), one image per call",
        "gpu_impl": "torch.nn.functional.conv2d on the whole batch in one launch",
        "equivalence": verify_against_cv2(shape=(2, 96, 96), sigma=2.0),
    }

    rng = np.random.default_rng(7)

    # --- the actual pipeline workload: 12 delivered views, near/far defocus pair ---------
    n_views = 12
    sigma = 1.0
    images = rng.random((n_views, args.height, args.width, args.channels), dtype=np.float32)
    pairs = {}
    for label, s in (("near_sigma_1.0", sigma), ("far_sigma_1.6", sigma * 1.6)):
        k = gaussian_psf(s)
        cpu_s = time_cpu(images, k, args.repeat)
        gpu_s = time_gpu(images, k, args.repeat)
        ref = convolve_cpu_reference(images, k)
        got = convolve_batch(images, k)
        d = np.abs(ref.astype(np.float64) - got.astype(np.float64))
        pairs[label] = {
            "sigma_px": s, "kernel_shape": list(k.shape),
            "batch": n_views, "cpu_seconds": cpu_s, "gpu_seconds": gpu_s,
            "speedup": round(cpu_s / gpu_s, 2) if gpu_s > 0 else None,
            "max_abs_diff": float(d.max()), "mean_abs_diff": float(d.mean()),
            "within_1e-5": bool(d.max() <= 1e-5),
        }
    report["pipeline_workload_12_views"] = pairs
    both_cpu = sum(v["cpu_seconds"] for v in pairs.values())
    both_gpu = sum(v["gpu_seconds"] for v in pairs.values())
    report["pipeline_workload_total"] = {
        "cpu_seconds": round(both_cpu, 4), "gpu_seconds": round(both_gpu, 4),
        "speedup": round(both_cpu / both_gpu, 2) if both_gpu else None,
        "note": "the two convolutions the depth-dependent defocus path performs per view",
    }

    # --- where the GPU stops paying: batch size and kernel size sweep --------------------
    sweep = []
    for batch in (1, 4, 12, 48):
        for s in (1.0, 2.0, 4.0, 8.0):
            k = gaussian_psf(s)
            imgs = rng.random((batch, args.height, args.width, args.channels),
                              dtype=np.float32)
            cpu_s = time_cpu(imgs, k, max(2, args.repeat // 2))
            gpu_s = time_gpu(imgs, k, max(2, args.repeat // 2))
            ref = convolve_cpu_reference(imgs, k)
            got = convolve_batch(imgs, k)
            d = np.abs(ref.astype(np.float64) - got.astype(np.float64)).max()
            sweep.append({"batch": batch, "sigma_px": s, "kernel": int(k.shape[0]),
                          "cpu_seconds": cpu_s, "gpu_seconds": gpu_s,
                          "speedup": round(cpu_s / gpu_s, 2) if gpu_s > 0 else None,
                          "max_abs_diff": float(d),
                          "gpu_worth_it": bool(cpu_s / gpu_s > 1.5) if gpu_s > 0 else None})
    report["sweep"] = sweep
    report["crossover_note"] = (
        "a run is only worth offloading when the batch is large enough to amortise the "
        "host->device transfer and the kernel-launch latency; see the sweep rows")

    payload = json.dumps(report, indent=2, default=str)
    print(payload)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(payload, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
