"""CPU vs GPU Cycles benchmark on the repository's own 1024x768 observe task.

This is a *measurement* harness, not a test.  It drives the real pipeline path
(``synlab.observe.routes.render_views`` with ``backend="blender"``) at the resolution the
project actually delivers (``delivered_size=(1024, 768)``, ``max_render_pixels=786432``) and
records, per view and in total:

* wall-clock seconds for the whole run **including one Blender process per view**,
* the worker's own in-process elapsed seconds and per-render-pass seconds,
* the resolved compute device reported by the worker manifest (never the requested one),
* the delivered channels, so two runs can be compared numerically afterwards.

Usage::

    python blender_scripts/bench_gpu_render.py run --device CPU --views 12 --out cpu.json
    python blender_scripts/bench_gpu_render.py run --device GPU --views 12 --out gpu.json
    python blender_scripts/bench_gpu_render.py compare --cpu cpu.json --gpu gpu.json \
        --out compare.json

``run`` also samples ``nvidia-smi`` memory in a background thread so the GPU run reports a
measured peak VRAM figure instead of a claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import trimesh  # noqa: E402

#: Channels compared between the two runs, in the order they are stored in the result .npz.
CHANNELS = ("rgb_linear", "depth_z", "depth_z_aa", "id_map", "surface_tag", "visibility",
            "uncertain_mask", "occlusion", "target_visibility", "object_index")


# --------------------------------------------------------------------------------------
# VRAM sampling
# --------------------------------------------------------------------------------------
class VramSampler:
    """Poll ``nvidia-smi`` and system CPU load while a run is in flight.

    The CPU baseline of a CPU-vs-GPU comparison is only meaningful if the host is not busy
    with unrelated work, and this repository is worked on by several processes at once.  The
    sampler therefore records the machine-wide CPU utilisation next to the timing so a
    contended baseline is visible instead of being silently reported as a CPU speed.
    """

    def __init__(self, interval_s: float = 0.25) -> None:
        self.interval_s = interval_s
        self.samples: list[int] = []
        self.cpu_samples: list[float] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.error: str | None = None

    @staticmethod
    def _query() -> tuple[int, int] | None:
        try:
            proc = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.used,memory.total",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=10, check=False)
        except Exception:  # noqa: BLE001
            return None
        line = (proc.stdout or "").strip().splitlines()
        if not line:
            return None
        try:
            used, total = (int(float(v)) for v in line[0].split(","))
        except ValueError:
            return None
        return used, total

    def _loop(self) -> None:
        try:
            import psutil
            psutil.cpu_percent(interval=None)  # prime the counter
        except Exception:  # noqa: BLE001
            psutil = None
        while not self._stop.is_set():
            q = self._query()
            if q is not None:
                self.samples.append(q[0])
                self._total = q[1]
            if psutil is not None:
                self.cpu_samples.append(float(psutil.cpu_percent(interval=None)))
            self._stop.wait(self.interval_s)

    def start(self) -> None:
        base = self._query()
        self.baseline_mb = base[0] if base else 0
        self._total = base[1] if base else 0
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> dict:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        peak = max(self.samples) if self.samples else None
        return {
            "baseline_used_mb": int(getattr(self, "baseline_mb", 0)),
            "total_mb": int(getattr(self, "_total", 0)),
            "peak_used_mb": None if peak is None else int(peak),
            "peak_delta_mb": None if peak is None else int(peak - self.baseline_mb),
            "n_samples": len(self.samples),
            "method": "poll nvidia-smi --query-gpu=memory.used every 0.25 s during the run",
            "note": ("delta is relative to the pre-run baseline and therefore includes any "
                     "other process activity; it bounds Blender's VRAM use rather than "
                     "isolating it"),
        }

    def load_report(self) -> dict:
        """Machine-wide CPU load seen during the run (contention evidence)."""
        s = self.cpu_samples
        if not s:
            return {"available": False}
        return {"available": True, "n_samples": len(s),
                "mean_percent": round(sum(s) / len(s), 1),
                "max_percent": round(max(s), 1),
                "method": "psutil.cpu_percent sampled every 0.25 s across all cores",
                "note": ("a high figure means unrelated processes were competing for the CPU "
                         "during this run; the CPU baseline is then pessimistic")}


# --------------------------------------------------------------------------------------
# scene (identical to tests/a12/observe/_probe_realism_timing.py)
# --------------------------------------------------------------------------------------
def build_target():
    from synlab.observe.routes import resolve_target

    box = trimesh.creation.box(extents=(60.0, 42.0, 26.0))
    # ``allow_unlabeled`` is the documented escape hatch for a mesh with no fracture
    # provenance: a bare box carries no origin_kind/interface_id, so without it
    # resolve_target refuses (OBS_TARGET_PROVENANCE_MISSING).  It changes only the
    # surface_tag vocabulary, not the geometry, and both devices use it identically.
    return resolve_target(box, fragment_id="timing_box", allow_unlabeled=True), box


def sha256_array(arr: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(arr).tobytes()).hexdigest()


# --------------------------------------------------------------------------------------
# run
# --------------------------------------------------------------------------------------
def cmd_run(args: argparse.Namespace) -> int:
    from synlab.cameras.profiles import profile_by_id
    from synlab.observe.blender import BlenderBackendConfig
    from synlab.observe.imaging import ImagingSpec
    from synlab.observe.routes import ObsSpec, render_views
    from synlab.seeds import make_rng

    target, box = build_target()
    profile = profile_by_id("CAM_MID_V3")
    work_root = ROOT / "data" / "a12" / "reports" / "gpu" / f"bench_{args.device.lower()}"
    spec = ObsSpec(
        view_count=int(args.views), delivered_size=(1024, 768), max_render_pixels=786432,
        master_seed=20261001, lineage_id="gpu_bench",
        renderer="blender", distortion_policy="undistort",
        imaging=ImagingSpec(encode="JPEG", jpeg_quality=85, defocus_sigma_px=1.0,
                            effective_gain=0.02, read_noise_sigma=0.004),
    )
    spec.blender_config = BlenderBackendConfig(
        samples=int(args.samples), f_number=float(profile.f_number),
        coc_px_threshold=0.75 * float(profile.f_number), run_label="gpu_bench",
        device=args.device,
        compute_device_type=args.compute_device_type,
        gpu_require=bool(args.require_gpu),
        work_root=str(work_root))

    rng = make_rng(20261001, "gpu_bench", "camera")
    sampler = VramSampler()
    sampler.start()
    t0 = time.perf_counter()
    bundles = render_views(target, profile, spec, rng, backend="blender")
    total_s = time.perf_counter() - t0
    vram = sampler.stop()
    load = sampler.load_report()
    if args.device.upper() == "CPU":
        vram = None

    per_view = []
    arrays: dict[str, list[np.ndarray]] = {name: [] for name in CHANNELS}
    for i, b in enumerate(bundles):
        meta = dict(b.render.meta)
        row = {
            "index": i,
            "view_id": meta.get("view_id") or f"view{i}",
            "worker_wall_seconds": meta.get("worker_wall_seconds"),
            "worker_elapsed_seconds": meta.get("elapsed_seconds"),
            "render_seconds": meta.get("render_seconds"),
            "cycles_device": meta.get("cycles_device"),
            "cycles_device_selection": meta.get("cycles_device_selection"),
            "samples_used": meta.get("samples_used"),
            "raycast_status": (meta.get("checks", {})
                               .get("raycast_vs_exact_pass", {}).get("status")),
            "camera_check_px": (meta.get("checks", {})
                                .get("camera_model", {}).get("max_uv_error_px")),
        }
        # the worker's own per-view elapsed time is the fair "render only" figure; the wall
        # figure includes Blender startup, which is a fixed per-view cost
        for name in CHANNELS:
            arr = np.asarray(getattr(b.render, name))
            arrays[name].append(arr)
            row[f"sha256_{name}"] = sha256_array(arr)
        per_view.append(row)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    npz = out.with_suffix(".npz")
    np.savez_compressed(npz, **{name: np.stack(v) for name, v in arrays.items()})

    worker_total = sum(float(r["worker_wall_seconds"] or 0.0) for r in per_view)
    inproc_total = sum(float(r["worker_elapsed_seconds"] or 0.0) for r in per_view)
    render_total = sum(sum((r["render_seconds"] or {}).values()) for r in per_view)
    sel0 = next((r["cycles_device_selection"] for r in per_view
                 if r["cycles_device_selection"]), None)
    report = {
        "device_requested": args.device,
        "compute_device_type_requested": args.compute_device_type,
        "gpu_require": bool(args.require_gpu),
        "views": len(bundles),
        "samples": int(args.samples),
        "delivered_size": [1024, 768],
        "max_render_pixels": 786432,
        "scene": {"kind": "trimesh box 60x42x26 mm via resolve_target",
                  "faces": int(np.asarray(box.faces).shape[0]),
                  "vertices": int(np.asarray(box.vertices).shape[0])},
        "camera_profile": "CAM_MID_V3",
        "total_wall_seconds_incl_process_start": round(total_s, 3),
        "seconds_per_view_incl_process_start": round(total_s / max(len(bundles), 1), 3),
        "sum_worker_wall_seconds": round(worker_total, 3),
        "sum_worker_inprocess_elapsed_seconds": round(inproc_total, 3),
        "sum_render_pass_seconds": round(render_total, 3),
        "process_start_overhead_seconds": round(total_s - worker_total, 3),
        "resolved_device_selection": sel0,
        "vram": vram,
        "system_cpu_load_during_run": load,
        "per_view": per_view,
        "npz": str(npz),
        "renders_per_view": 6,
        "renders_per_view_note": ("RGB(32 sp) + AA geometry pack a(32 sp) + pack b(32 sp) "
                                  "+ exact pack a/b and target-only(1 sp each)"),
    }
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str),
                   encoding="utf-8")
    print(json.dumps({k: report[k] for k in
                      ("device_requested", "views", "total_wall_seconds_incl_process_start",
                       "seconds_per_view_incl_process_start", "sum_worker_wall_seconds",
                       "sum_render_pass_seconds", "process_start_overhead_seconds",
                       "resolved_device_selection", "vram", "system_cpu_load_during_run")},
                     indent=2, ensure_ascii=False, default=str))
    return 0


# --------------------------------------------------------------------------------------
# compare
# --------------------------------------------------------------------------------------
def cmd_compare(args: argparse.Namespace) -> int:
    cpu = json.loads(Path(args.cpu).read_text(encoding="utf-8"))
    gpu = json.loads(Path(args.gpu).read_text(encoding="utf-8"))
    a = np.load(cpu["npz"])
    b = np.load(gpu["npz"])

    def stats(name: str) -> dict:
        x = np.asarray(a[name], dtype=np.float64)
        y = np.asarray(b[name], dtype=np.float64)
        if x.shape != y.shape:
            return {"status": "SHAPE_MISMATCH", "cpu_shape": list(x.shape),
                    "gpu_shape": list(y.shape)}
        both_nan = np.isnan(x) & np.isnan(y)
        one_nan = np.isnan(x) ^ np.isnan(y)
        d = np.abs(np.nan_to_num(x, nan=0.0) - np.nan_to_num(y, nan=0.0))
        d = d[~both_nan]
        finite = d[np.isfinite(d)]
        exact = bool(np.array_equal(np.nan_to_num(x, nan=-1e30),
                                    np.nan_to_num(y, nan=-1e30)))
        return {
            "identical_bitwise": exact,
            "n_compared": int(d.size),
            "max_abs_diff": float(finite.max()) if finite.size else 0.0,
            "median_abs_diff": float(np.median(finite)) if finite.size else 0.0,
            "p99_abs_diff": float(np.percentile(finite, 99)) if finite.size else 0.0,
            "mean_abs_diff": float(finite.mean()) if finite.size else 0.0,
            "n_differing": int(np.count_nonzero(finite > 0)),
            "fraction_differing": float(np.count_nonzero(finite > 0) / max(d.size, 1)),
            "nan_mismatch_px": int(np.count_nonzero(one_nan)),
        }

    diffs = {name: stats(name) for name in CHANNELS}
    cpu_hashes = {r["view_id"]: {k: v for k, v in r.items() if k.startswith("sha256_")}
                  for r in cpu["per_view"]}
    gpu_hashes = {r["view_id"]: {k: v for k, v in r.items() if k.startswith("sha256_")}
                  for r in gpu["per_view"]}
    identical_views = sorted(v for v in cpu_hashes
                             if v in gpu_hashes and cpu_hashes[v] == gpu_hashes[v])

    speed = {
        "total_wall_cpu_s": cpu["total_wall_seconds_incl_process_start"],
        "total_wall_gpu_s": gpu["total_wall_seconds_incl_process_start"],
        "speedup_total_wall": round(cpu["total_wall_seconds_incl_process_start"]
                                    / max(gpu["total_wall_seconds_incl_process_start"], 1e-9), 3),
        "sum_worker_wall_cpu_s": cpu["sum_worker_wall_seconds"],
        "sum_worker_wall_gpu_s": gpu["sum_worker_wall_seconds"],
        "speedup_worker_wall": round(cpu["sum_worker_wall_seconds"]
                                     / max(gpu["sum_worker_wall_seconds"], 1e-9), 3),
        "sum_render_pass_cpu_s": cpu["sum_render_pass_seconds"],
        "sum_render_pass_gpu_s": gpu["sum_render_pass_seconds"],
        "speedup_render_pass": round(cpu["sum_render_pass_seconds"]
                                     / max(gpu["sum_render_pass_seconds"], 1e-9), 3),
    }
    per_pass = {}
    for tag in ("rgb", "geometry_exact", "geometry_aa", "geometry_targetonly"):
        c = sum(float((r["render_seconds"] or {}).get(tag, 0.0)) for r in cpu["per_view"])
        g = sum(float((r["render_seconds"] or {}).get(tag, 0.0)) for r in gpu["per_view"])
        per_pass[tag] = {"cpu_s": round(c, 3), "gpu_s": round(g, 3),
                         "speedup": round(c / g, 3) if g > 0 else None}
    report = {
        "cpu_report": args.cpu, "gpu_report": args.gpu,
        "cpu_resolved_device": cpu.get("resolved_device_selection"),
        "gpu_resolved_device": gpu.get("resolved_device_selection"),
        "speed": speed, "per_pass": per_pass,
        "vram_gpu": gpu.get("vram"),
        "channel_diff_cpu_vs_gpu": diffs,
        "views_with_all_channel_hashes_identical": identical_views,
        "n_views_hash_identical": len(identical_views),
        "n_views": cpu["views"],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str),
                   encoding="utf-8")
    print(json.dumps({"speed": speed, "per_pass": per_pass,
                      "vram_gpu": report["vram_gpu"],
                      "n_views_hash_identical": report["n_views_hash_identical"],
                      "n_views": report["n_views"],
                      "diff_summary": {k: {"identical_bitwise": v.get("identical_bitwise"),
                                           "max_abs_diff": v.get("max_abs_diff"),
                                           "median_abs_diff": v.get("median_abs_diff"),
                                           "p99_abs_diff": v.get("p99_abs_diff"),
                                           "fraction_differing": v.get("fraction_differing")}
                                       for k, v in diffs.items()}},
                     indent=2, ensure_ascii=False, default=str))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--device", default="CPU")
    r.add_argument("--compute-device-type", dest="compute_device_type", default="AUTO")
    r.add_argument("--require-gpu", action="store_true")
    r.add_argument("--views", type=int, default=12)
    r.add_argument("--samples", type=int, default=32)
    r.add_argument("--out", required=True)
    r.set_defaults(func=cmd_run)
    c = sub.add_parser("compare")
    c.add_argument("--cpu", required=True)
    c.add_argument("--gpu", required=True)
    c.add_argument("--out", required=True)
    c.set_defaults(func=cmd_compare)
    args = ap.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
