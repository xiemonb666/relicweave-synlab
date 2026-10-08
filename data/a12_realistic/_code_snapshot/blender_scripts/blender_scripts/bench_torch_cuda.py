"""Real CUDA evidence: device facts plus timed tensor operations, CPU vs GPU.

This is the artefact behind any "CUDA is enabled" statement.  It records the device identity,
the compiled architecture list (``sm_120`` must be present for an RTX 50-series part), the
CUDA/driver versions torch reports, and wall-clock times for real kernels with the numerical
agreement between the two devices.

Usage::

    python blender_scripts/bench_torch_cuda.py --out data/a12/reports/gpu/torch_cuda.json
"""

from __future__ import annotations

import argparse
import json
import platform
import time
from pathlib import Path

import numpy as np


def timed(fn, *, warmup: int = 3, repeat: int = 10, sync=None) -> tuple[float, object]:
    """Return (best seconds, result of the last call).

    ``sync`` must be ``torch.cuda.synchronize`` for GPU work.  Without it the measurement
    captures only the **asynchronous kernel launch** and reports absurd throughput (measured:
    a 4096^3 matmul "completed" in 20 microseconds, i.e. 6.8 PFLOP/s, which is how this bug
    was caught).
    """
    out = None
    for _ in range(warmup):
        out = fn()
    if sync is not None:
        sync()
    best = float("inf")
    for _ in range(repeat):
        if sync is not None:
            sync()
        t0 = time.perf_counter()
        out = fn()
        if sync is not None:
            sync()
        best = min(best, time.perf_counter() - t0)
    return best, out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    ap.add_argument("--matmul-n", type=int, default=4096)
    ap.add_argument("--repeat", type=int, default=10)
    args = ap.parse_args()

    import torch

    torch.manual_seed(0)
    np.random.seed(0)

    info: dict = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "torch": torch.__version__,
        "torch_cuda_build": torch.version.cuda,
        "torch_cudnn": torch.backends.cudnn.version() if torch.backends.cudnn.is_available()
        else None,
        "cuda_is_available": bool(torch.cuda.is_available()),
        "arch_list": torch.cuda.get_arch_list(),
        "device_count": torch.cuda.device_count() if torch.cuda.is_available() else 0,
    }
    if not torch.cuda.is_available():
        info["verdict"] = "NO_CUDA"
        print(json.dumps(info, indent=2))
        if args.out:
            Path(args.out).write_text(json.dumps(info, indent=2), encoding="utf-8")
        return 1

    props = torch.cuda.get_device_properties(0)
    info["device_name"] = torch.cuda.get_device_name(0)
    info["capability"] = list(torch.cuda.get_device_capability(0))
    info["sm_count"] = props.multi_processor_count
    info["total_memory_mb"] = round(props.total_memory / 1024 ** 2, 1)
    info["sm_120_kernel_present"] = "sm_120" in info["arch_list"]
    info["torch_cuda_version"] = torch.version.cuda
    try:
        info["driver_version"] = torch.cuda.driver_version
    except Exception:  # noqa: BLE001 - attribute varies by build
        info["driver_version"] = None

    results: dict = {}

    # ---------------------------------------------------------------- fp32 matmul
    n = int(args.matmul_n)
    a_cpu = torch.randn(n, n, dtype=torch.float32)
    b_cpu = torch.randn(n, n, dtype=torch.float32)
    a_gpu = a_cpu.cuda()
    b_gpu = b_cpu.cuda()

    cpu_s, cpu_out = timed(lambda: a_cpu @ b_cpu, repeat=args.repeat)
    gpu_s, gpu_out = timed(lambda: a_gpu @ b_gpu, repeat=args.repeat,
                           sync=torch.cuda.synchronize)
    gpu_out_cpu = gpu_out.cpu()
    diff = (cpu_out - gpu_out_cpu).abs()
    results["matmul_fp32"] = {
        "n": n, "flops": 2 * n ** 3,
        "cpu_seconds": cpu_s, "gpu_seconds": gpu_s,
        "speedup": round(cpu_s / gpu_s, 2),
        "cpu_gflops": round(2 * n ** 3 / cpu_s / 1e9, 1),
        "gpu_gflops": round(2 * n ** 3 / gpu_s / 1e9, 1),
        "max_abs_diff": float(diff.max()), "mean_abs_diff": float(diff.mean()),
        "allclose_rtol1e-3": bool(torch.allclose(cpu_out, gpu_out_cpu, rtol=1e-3, atol=1e-3)),
    }

    # ---------------------------------------------------------------- fp16 matmul
    try:
        ah, bh = a_cpu.half().cuda(), b_cpu.half().cuda()
        gpu16_s, out16 = timed(lambda: ah @ bh, repeat=args.repeat,
                               sync=torch.cuda.synchronize)
        results["matmul_fp16"] = {
            "n": n, "gpu_seconds": gpu16_s,
            "gpu_gflops": round(2 * n ** 3 / gpu16_s / 1e9, 1),
            "speedup_vs_cpu_fp32": round(cpu_s / gpu16_s, 2),
            "max_abs_diff_vs_cpu_fp32": float(
                (cpu_out - out16.float().cpu()).abs().max()),
        }
    except Exception as exc:  # noqa: BLE001
        results["matmul_fp16"] = {"error": f"{type(exc).__name__}: {exc}"}

    # ---------------------------------------------------------------- conv2d batch
    try:
        import torch.nn.functional as F
        batch, ch, h, w, k = 12, 3, 768, 1024, 7
        x_cpu = torch.randn(batch, ch, h, w)
        wgt = torch.randn(ch, 1, k, k)
        x_gpu, w_gpu = x_cpu.cuda(), wgt.cuda()
        cpu_s2, c_out = timed(
            lambda: F.conv2d(F.pad(x_cpu, (3, 3, 3, 3), mode="reflect"), wgt, groups=ch),
            repeat=max(3, args.repeat // 3))
        gpu_s2, g_out = timed(
            lambda: F.conv2d(F.pad(x_gpu, (3, 3, 3, 3), mode="reflect"), w_gpu, groups=ch),
            repeat=args.repeat, sync=torch.cuda.synchronize)
        d2 = (c_out - g_out.cpu()).abs()
        results["conv2d_batch12_1024x768_k7"] = {
            "shape": [batch, ch, h, w], "kernel": k, "groups": ch,
            "cpu_seconds": cpu_s2, "gpu_seconds": gpu_s2,
            "speedup": round(cpu_s2 / gpu_s2, 2),
            "max_abs_diff": float(d2.max()), "mean_abs_diff": float(d2.mean()),
            "allclose_atol1e-4": bool(torch.allclose(c_out, g_out.cpu(), atol=1e-4, rtol=1e-4)),
        }
    except Exception as exc:  # noqa: BLE001
        results["conv2d_batch12_1024x768_k7"] = {"error": f"{type(exc).__name__}: {exc}"}

    # ---------------------------------------------------------------- transfer cost
    t0 = time.perf_counter()
    _ = a_cpu.cuda()
    torch.cuda.synchronize()
    h2d = time.perf_counter() - t0
    t0 = time.perf_counter()
    _ = a_gpu.cpu()
    d2h = time.perf_counter() - t0
    results["transfer"] = {
        "tensor_mb": round(a_cpu.numel() * 4 / 1024 ** 2, 1),
        "host_to_device_seconds": h2d, "device_to_host_seconds": d2h,
        "note": ("a single 64 MiB transfer already costs more than many small kernels; this "
                 "sets the floor for any per-view GPU offload"),
    }

    info["operations"] = results
    info["verdict"] = "CUDA_OK"
    payload = json.dumps(info, indent=2, default=str)
    print(payload)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(payload, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
