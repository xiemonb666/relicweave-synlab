"""Fracture-ROI close-up run: whole-fragment views + ROI close-ups, one run, one basis.

Produces (all under the allowed write scope):

* ``data/a12_roi/store``            - one ``obs_result`` asset per study body: the whole-fragment
                                      views **plus** the ROI close-up views, with the resolution
                                      ledger (``px_per_mm`` / ``r_eff_mm`` / ``dof_cover_mm``).
* ``data/a12_reports/fracture_roi_views.json``   - per-view measured resolution and fracture pixels.
* ``data/a12_reports/fracture_roi_compare.json`` - whole-fragment vs ROI close-up hard metrics.
* ``data/a12_reports/fracture_roi_resolvability.json`` - the "can it be seen" ladder + inverse solve.
* ``data/a12_reports/fracture_roi_timing.json``  - wall seconds per phase and sampled GPU memory.

Usage (repository root, venv interpreter):
    python tests/a12/observe/_run_fracture_roi.py [--bodies N] [--quick] [--no-store]
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from synlab.observe import fracture_roi as fr  # noqa: E402
from synlab.observe import routes as rt  # noqa: E402
from synlab.observe.api import commit_observation, load_observation  # noqa: E402
from synlab.observe.blender import BlenderBackendConfig  # noqa: E402
from synlab.observe.render import RenderSpec  # noqa: E402
from synlab.seeds import make_rng  # noqa: E402
from synlab.storage.mesh_io import arrays_to_mesh  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402

#: Study bodies: 2 vessel types x 2 materials (and two more for the vessel x material grid).
STUDY = [
    {"store": "data/a12_campaign/store", "asset_id": "asset_745a78313d0d5b045b3a",
     "vessel": "V10", "material": "M11", "lineage": "LIN0000_V10_M11_PAT15"},
    {"store": "data/a12_campaign/store", "asset_id": "asset_73da9901b275bb65c04e",
     "vessel": "V21", "material": "M06", "lineage": "LIN0001_V21_M06_PAT16"},
    {"store": "data/a12_campaign/store", "asset_id": "asset_aba4549620450f1f6adf",
     "vessel": "V23", "material": "M07", "lineage": "LIN0002_V23_M07_PAT12"},
    {"store": "data/a12_iface/store", "asset_id": "asset_8ad98a2081675cc92587",
     "vessel": "V02", "material": "M01", "lineage": "LIN0000_V02_M02_PAT02"},
]

WHOLE_VIEW_COUNT = 12
WHOLE_LONG_EDGE = 1024
ROI_LONG_EDGE = 1024
BLENDER_SAMPLES = 16


class GpuSampler:
    """Sample ``nvidia-smi`` memory.used while a render runs (measured, not estimated)."""

    def __init__(self, interval_s: float = 0.25) -> None:
        self.interval_s = float(interval_s)
        self.samples: list[int] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.error: str | None = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                out = subprocess.run(
                    ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=10)
                for line in out.stdout.strip().splitlines():
                    try:
                        self.samples.append(int(float(line.strip())))
                    except ValueError:
                        continue
            except Exception as exc:  # noqa: BLE001
                self.error = f"{type(exc).__name__}: {exc}"
                return
            self._stop.wait(self.interval_s)

    def __enter__(self) -> "GpuSampler":
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)

    def report(self) -> dict[str, object]:
        if not self.samples:
            return {"samples": 0, "error": self.error,
                    "note": "no nvidia-smi sample was collected"}
        return {
            "samples": len(self.samples), "min_mib": int(min(self.samples)),
            "max_mib": int(max(self.samples)),
            "mean_mib": float(np.mean(self.samples)),
            "peak_mib": int(max(self.samples)), "error": self.error,
        }


def load_target(entry: dict) -> tuple[object, dict]:
    store = AssetStore(ROOT / entry["store"])
    asset = store.get_asset(entry["asset_id"])
    arrays = store.load_arrays(entry["asset_id"])
    mesh, attrs = arrays_to_mesh(arrays)
    target = rt.resolve_target({"mesh": mesh, "fragment_id": asset.meta.get("fragment_id", ""),
                               "component_id": asset.meta.get("component_id", "")},
                              fragment_id=str(asset.meta.get("fragment_id") or ""))
    return target, {
        "store": entry["store"], "asset_id": entry["asset_id"],
        "lineage_id": asset.lineage_id, "vessel_id": entry["vessel"],
        "material_id": entry["material"],
        "n_faces": int(np.asarray(mesh.faces).shape[0]),
        "interface_faces": int(np.count_nonzero(
            np.asarray(attrs["origin_kind"]).reshape(-1) == 1)),
        "asset_meta": {k: asset.meta.get(k) for k in
                       ("fragment_id", "component_id", "recipe_id", "axis_id", "level")},
    }


def build_specs(*, backend: str, blender_config, delivered: tuple[int, int],
                max_render_pixels: int, seed: int) -> rt.ObsSpec:
    return rt.ObsSpec(
        view_count=WHOLE_VIEW_COUNT, delivered_size=delivered,
        max_render_pixels=int(max_render_pixels), tiers=("GLOBAL", "MID", "LOCAL"),
        render_spec=RenderSpec(supersample=1), master_seed=int(seed),
        lineage_id="fracture_roi", frame_id="S_mm", renderer=backend,
        distortion_policy=rt.DISTORTION_POLICY_IGNORE, blender_config=blender_config,
    )


def run_body(entry: dict, config: fr.FractureRoiConfig, *, backend: str, samples: int,
             extra_rung: int | None, write_store: bool) -> dict:
    from synlab.cameras.profiles import camera_profiles

    target, body = load_target(entry)
    body["surface_tag_source"] = target.meta.get("surface_tag_source")
    body["target_rim_faces"] = target.meta.get("surface_tag_face_histogram", {}).get("2")
    blender_config = BlenderBackendConfig(samples=int(samples), device="GPU",
                                          compute_device_type="AUTO", gpu_require=True,
                                          distortion_policy=rt.DISTORTION_POLICY_IGNORE,
                                          denoise=False, run_label=f"roi_{entry['vessel']}")
    profiles = {p.tier: p for p in camera_profiles()}
    # both families are rendered by the *same* node at the same delivered grid; they differ only
    # in framing (whole fragment vs fracture close-up).  The delivered grid is the camera's own
    # grid, so no crop/resize sits between the render and the measurement (A = identity) and the
    # Blender worker's fx == fy requirement holds exactly.
    whole_profile = fr.delivered_profile(profiles["MID"], long_edge_px=WHOLE_LONG_EDGE)
    closeup = fr.closeup_profile(config, base=profiles[config.base_tier],
                                 delivered_long_edge_px=ROI_LONG_EDGE)
    f_px_closeup = float(closeup.K[0, 0]) * float(ROI_LONG_EDGE) / float(closeup.image_size[0])
    footprint_radius = fr.mm_per_px(working_distance_mm=config.working_distance_mm,
                                    f_px=f_px_closeup) * 0.5 * ROI_LONG_EDGE
    rois = fr.fracture_rois(target, config, footprint_radius_mm=footprint_radius)

    whole_spec = build_specs(backend=backend, blender_config=blender_config,
                             delivered=(WHOLE_LONG_EDGE, int(WHOLE_LONG_EDGE * 0.75)),
                             max_render_pixels=WHOLE_LONG_EDGE * WHOLE_LONG_EDGE,
                             seed=20261001)
    roi_spec = build_specs(backend=backend, blender_config=blender_config,
                           delivered=(ROI_LONG_EDGE, int(ROI_LONG_EDGE * 0.75)),
                           max_render_pixels=ROI_LONG_EDGE * ROI_LONG_EDGE,
                           seed=20261001)

    rng = make_rng(20261001, f"roi_{entry['vessel']}", "camera")
    timing: dict[str, object] = {}
    with GpuSampler() as gpu:
        started = time.perf_counter()
        observation, whole_bundles = rt.route_proxy_scan(target, whole_profile, whole_spec, rng,
                                                         backend=backend)
        timing["whole_fragment_seconds"] = float(time.perf_counter() - started)
        started = time.perf_counter()
        frames = fr.make_fracture_roi_frames(rois=rois, profile=closeup, spec=roi_spec,
                                             config=config, long_edge_px=ROI_LONG_EDGE,
                                             rng=rng, run_id=f"roi_{entry['vessel']}",
                                             mesh=target.mesh)
        roi_bundles, roi_seconds = fr.render_fracture_roi_views(
            target=target, frames=frames, spec=roi_spec, rng=rng, backend=backend,
            blender_config=blender_config)
        timing["fracture_roi_seconds"] = float(roi_seconds)
        timing["fracture_roi_frame_build_seconds"] = float(
            time.perf_counter() - started - roi_seconds)
        extra: dict[str, object] = {}
        if extra_rung and rois:
            extra_spec = build_specs(backend=backend, blender_config=blender_config,
                                     delivered=(int(extra_rung), int(extra_rung * 0.75)),
                                     max_render_pixels=int(extra_rung) * int(extra_rung),
                                     seed=20261001)
            extra_profile = fr.closeup_profile(config, base=profiles[config.base_tier],
                                               delivered_long_edge_px=int(extra_rung))
            extra_frames = fr.make_fracture_roi_frames(rois=rois[:1], profile=extra_profile,
                                                       spec=extra_spec, config=config,
                                                       long_edge_px=int(extra_rung), rng=rng,
                                                       run_id=f"roi_{entry['vessel']}_hi",
                                                       mesh=target.mesh)
            started = time.perf_counter()
            extra_bundles, _ = fr.render_fracture_roi_views(
                target=target, frames=extra_frames, spec=extra_spec, rng=rng, backend=backend,
                blender_config=blender_config)
            extra = {
                "long_edge_px": int(extra_rung),
                "seconds": float(time.perf_counter() - started),
                "records": [fr.view_resolution_record(b, mesh=target.mesh)
                            for b in extra_bundles],
            }
    timing["gpu_memory"] = gpu.report()

    whole_records = [fr.view_resolution_record(b, mesh=target.mesh) for b in whole_bundles]
    roi_records = [fr.view_resolution_record(b, mesh=target.mesh) for b in roi_bundles]
    for record, bundle in zip(roi_records, roi_bundles):
        roi_id = str((bundle.frame.meta or {}).get("fracture_roi_id") or "")
        roi = next((r for r in rois if r.roi_id == roi_id), None)
        if roi is not None:
            record["roi_amplitude_px"] = fr.amplitude_px_from_roi(
                roi=roi, mm_per_px_measured=float(record["mm_per_px_measured"] or float("nan")),
                band="plane")
            record["roi_amplitude_px_bands"] = {
                band: fr.amplitude_px_from_roi(
                    roi=roi,
                    mm_per_px_measured=float(record["mm_per_px_measured"] or float("nan")),
                    band=band)
                for band in (roi.height.get("bands") or {})
            }
    for record, bundle in zip(whole_records, whole_bundles):
        record["view_family"] = fr.VIEW_FAMILY_WHOLE

    observation = fr.append_roi_views(
        observation=observation, roi_bundles=roi_bundles, spec=roi_spec, config=config,
        rois=rois, whole_records=whole_records, roi_records=roi_records,
        timings=timing)
    summary = fr.roi_summary(rois=rois, whole_records=whole_records, roi_records=roi_records)
    observation.meta["fracture_roi"]["summary"] = summary
    observation.meta["fracture_roi"]["body"] = body

    stored = None
    if write_store:
        store = AssetStore(ROOT / "data/a12_roi/store")
        record = commit_observation(store, observation, lineage_id=str(body["lineage_id"]),
                                    split="train", ancestry=[str(entry["asset_id"])],
                                    run_id="fracture_roi_views")
        stored = record.asset_id
        back = load_observation(store, stored)
        assert len(back.views) == len(observation.views), "stored view count changed"
        assert back.meta["fracture_roi"]["n_roi_views"] == len(roi_bundles)
    return {"body": body, "rois": [r.as_dict() for r in rois],
            "whole_records": whole_records, "roi_records": roi_records,
            "summary": summary, "timing": timing, "extra_rung": extra,
            "stored_asset_id": stored, "observation_id": observation.observation_id,
            "closeup_profile": {"profile_id": closeup.profile_id,
                                "working_distance_mm": closeup.working_distance_mm,
                                "f_px_native": float(closeup.K[0, 0]),
                                "f_px_delivered": f_px_closeup,
                                "dof_cover_mm": closeup.meta.get("dof_cover_mm"),
                                "dof_near_mm": closeup.meta.get("dof_report", {}).get("near_mm"),
                                "dof_far_mm": closeup.meta.get("dof_report", {}).get("far_mm"),
                                "calibration_status": closeup.meta.get("calibration_status"),
                                "footprint_radius_mm": footprint_radius},
            "whole_spec": {"profile": whole_profile.profile_id,
                           "delivered": list(whole_profile.image_size),
                           "f_px_delivered": float(whole_profile.K[0, 0]),
                           "n_views": WHOLE_VIEW_COUNT},
            "roi_spec": {"delivered": [ROI_LONG_EDGE, int(ROI_LONG_EDGE * 0.75)],
                         "n_views_per_fracture": int(config.directions),
                         "n_fractures": len(rois)}}


def resolvability(config: fr.FractureRoiConfig, measurements: dict) -> dict:
    """The "can it be seen" computation: documented ladder + measured amplitudes + inverse solve."""
    ladder = fr.documented_ladder()
    from synlab.cameras.profiles import camera_profiles

    profiles = {p.tier: p for p in camera_profiles()}
    whole_f_px = float(fr.delivered_profile(profiles["MID"], long_edge_px=1024).K[0, 0])
    closeup = fr.closeup_profile(config, base=profiles[config.base_tier],
                                 delivered_long_edge_px=1024)
    closeup_f_px = float(closeup.K[0, 0]) * 1024.0 / float(closeup.image_size[0])
    rungs: dict[str, float] = {
        f"contract_{int(row['distance_mm'])}mm": float(row["mm_per_px"]) for row in ladder["rows"]
    }
    rungs["delivered_whole_fragment_mid_1024px"] = fr.mm_per_px(
        working_distance_mm=float(profiles["MID"].working_distance_mm), f_px=whole_f_px)
    rungs["roi_closeup_60mm_local_lens_1024px"] = fr.mm_per_px(
        working_distance_mm=float(config.working_distance_mm), f_px=closeup_f_px)
    measured = dict(measurements)
    table = fr.resolvability_report(mm_per_px_values=rungs, amplitudes_mm=measured)
    native = ladder["focal_px_native"]
    native_width = ladder["sensor_width_px"]
    inverse = {}
    zero_amplitude: list[str] = []
    for name, amplitude in measured.items():
        if not (float(amplitude) > 0.0):
            # a measured zero is a *finding* (the geometry carries no relief at that band), not a
            # number to be replaced by an estimate: it is recorded and skipped by the inverse solve
            zero_amplitude.append(name)
            inverse[name] = {"amplitude_mm": 0.0,
                             "verdict": "NO_MEASURABLE_RELIEF_NO_INVERSE_NEEDED"}
            continue
        inverse[name] = {
            "contract_camera_2304px": fr.inverse_solve(
                amplitude_mm=float(amplitude), working_distance_mm=float(config.working_distance_mm),
                f_px_delivered=float(native) * 1024.0 / float(native_width),
                f_px_native=float(native), native_width_px=int(native_width),
                long_edge_px=1024),
            "local_macro_lens_1024px": fr.inverse_solve(
                amplitude_mm=float(amplitude), working_distance_mm=float(config.working_distance_mm),
                f_px_delivered=closeup_f_px, f_px_native=float(closeup.K[0, 0]),
                native_width_px=int(closeup.image_size[0]), long_edge_px=1024),
        }
    return {
        "criterion": {
            "pilot_px": fr.PILOT_PX_PER_STRUCTURE, "detail_px": fr.DETAIL_PX_PER_STRUCTURE,
            "nyquist_px": fr.NYQUIST_PX,
            "source": fr.CONTRACT_POINTERS["sampling_target"],
        },
        "documented_ladder": ladder,
        "mm_per_px_rungs": rungs,
        "measured_amplitudes_mm": measured,
        "amplitudes_with_no_measurable_relief": zero_amplitude,
        "resolvability": table,
        "inverse_solve": inverse,
        "closeup_profile": {
            "working_distance_mm": closeup.working_distance_mm,
            "f_px_native": float(closeup.K[0, 0]), "f_px_delivered_1024": closeup_f_px,
            "z_max_0p2mm_4px_mm": fr.max_working_distance_mm(
                size_mm=0.2, f_px=closeup_f_px, k_px=4.0),
            "dof_cover_mm": closeup.meta.get("dof_cover_mm"),
            "calibration_status": closeup.meta.get("calibration_status"),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bodies", type=int, default=len(STUDY))
    parser.add_argument("--quick", action="store_true",
                        help="software rasteriser, 4 ROI views, no extra rung")
    parser.add_argument("--no-store", action="store_true")
    parser.add_argument("--samples", type=int, default=BLENDER_SAMPLES)
    parser.add_argument("--extra-rung", type=int, default=2048)
    args = parser.parse_args()

    config = fr.load_fracture_roi_config()
    if args.quick:
        backend = "software_rasterizer"
        args.extra_rung = None
    else:
        backend = "blender"
    bodies = STUDY[:max(1, int(args.bodies))]
    report: dict[str, object] = {
        "schema": "synlab.a12.fracture_roi_run.v1", "config": config.as_dict(),
        "backend": backend, "blender_samples": int(args.samples),
        "whole_view_count": WHOLE_VIEW_COUNT, "whole_long_edge": WHOLE_LONG_EDGE,
        "roi_long_edge": ROI_LONG_EDGE, "bodies": [],
    }
    all_roi_records: list[dict] = []
    all_whole_records: list[dict] = []
    timing_total: dict[str, float] = {"whole_fragment_seconds": 0.0,
                                      "fracture_roi_seconds": 0.0,
                                      "extra_rung_seconds": 0.0}
    gpu_peaks: list[int] = []
    for index, entry in enumerate(bodies):
        started = time.perf_counter()
        result = run_body(entry, config, backend=backend, samples=int(args.samples),
                          extra_rung=(int(args.extra_rung)
                                      if (args.extra_rung and index == 0) else None),
                          write_store=not args.no_store)
        result["wall_seconds"] = float(time.perf_counter() - started)
        print(f"[roi] {entry['vessel']}/{entry['material']} {entry['asset_id']}: "
              f"{result['summary']['fracture_roi']['n_views']} ROI views, "
              f"{result['summary']['whole_fragment']['n_views']} whole views, "
              f"mm/px {result['summary']['whole_fragment']['mm_per_px_median']:.5f} -> "
              f"{result['summary']['fracture_roi']['mm_per_px_median']:.5f}, "
              f"wall {result['wall_seconds']:.1f} s", flush=True)
        for key in timing_total:
            timing_total[key] += float(result["timing"].get(key, 0.0) or 0.0)
        if result["extra_rung"]:
            timing_total["extra_rung_seconds"] += float(result["extra_rung"].get("seconds", 0.0))
        peak = (result["timing"].get("gpu_memory") or {}).get("peak_mib")
        if peak:
            gpu_peaks.append(int(peak))
        all_roi_records.extend(result["roi_records"])
        all_whole_records.extend(result["whole_records"])
        report["bodies"].append(result)
        (ROOT / "data/a12_reports/fracture_roi_run.json").write_text(
            json.dumps(report, indent=1, ensure_ascii=False, default=str), encoding="utf-8")

    amplitudes: dict[str, float] = {}
    for body in report["bodies"]:
        for roi in body["rois"]:
            plane = (roi.get("height") or {}).get("plane") or {}
            amplitudes[f"{body['body']['vessel_id']}-{roi['roi_id']}-plane_Ra"] = float(
                plane.get("Ra_mm", 0.0))
            for band, stats in ((roi.get("height") or {}).get("bands") or {}).items():
                amplitudes[f"{body['body']['vessel_id']}-{roi['roi_id']}-{band}_Ra"] = float(
                    stats.get("Ra_mm", 0.0))
    resolv = resolvability(config, amplitudes)
    timing = {
        "schema": "synlab.a12.fracture_roi_timing.v1", "backend": backend,
        "blender_samples": int(args.samples),
        "totals_seconds": timing_total,
        "per_body_seconds": [
            {"vessel": b["body"]["vessel_id"], "material": b["body"]["material_id"],
             "wall_seconds": b["wall_seconds"], **{k: b["timing"].get(k) for k in timing_total},
             "gpu_memory": b["timing"].get("gpu_memory")}
            for b in report["bodies"]],
        "gpu_peak_mib_max": (max(gpu_peaks) if gpu_peaks else None),
        "gpu_memory_total_mib": 8151,
        "note": ("GPU memory sampled with nvidia-smi memory.used during the Blender renders; "
                 "the peak is the whole-device usage, not this job's allocation"),
    }
    compare = {
        "schema": "synlab.a12.fracture_roi_compare.v1",
        "whole_fragment": _aggregate(all_whole_records),
        "fracture_roi": _aggregate(all_roi_records),
        "per_body": [{"vessel": b["body"]["vessel_id"], "material": b["body"]["material_id"],
                      **b["summary"]} for b in report["bodies"]],
        "extra_rung": [b["extra_rung"] for b in report["bodies"] if b["extra_rung"]],
    }
    (ROOT / "data/a12_reports/fracture_roi_run.json").write_text(
        json.dumps(report, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    (ROOT / "data/a12_reports/fracture_roi_compare.json").write_text(
        json.dumps(compare, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    (ROOT / "data/a12_reports/fracture_roi_resolvability.json").write_text(
        json.dumps(resolv, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    (ROOT / "data/a12_reports/fracture_roi_timing.json").write_text(
        json.dumps(timing, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps({"whole": compare["whole_fragment"], "roi": compare["fracture_roi"],
                      "timing": timing["totals_seconds"],
                      "gpu_peak_mib": timing["gpu_peak_mib_max"]},
                     indent=1, ensure_ascii=False, default=str))
    return 0


def _aggregate(records: list[dict]) -> dict:
    def median(key: str) -> float | None:
        values = [float(r[key]) for r in records
                  if r.get(key) is not None and math.isfinite(float(r[key]))]
        return float(np.median(values)) if values else None

    return {
        "n_views": len(records),
        "mm_per_px_median": median("mm_per_px_measured"),
        "mm_per_px_axis_raycast_median": median("mm_per_px_axis_raycast"),
        "mm_per_px_at_centre_median": median("mm_per_px_at_centre"),
        "mm_per_px_min": min((float(r["mm_per_px_measured"]) for r in records
                              if r.get("mm_per_px_measured")), default=None),
        "px_per_mm_median": median("px_per_mm_measured"),
        "r_eff_mm_4px": median("r_eff_mm_4px"),
        "rim_px_total": int(sum(int(r.get("rim_px", 0)) for r in records)),
        "rim_fraction_of_object_median": median("rim_fraction_of_object"),
        "delivered_sizes": sorted({tuple(r["delivered_size_px"]) for r in records}),
        "structure_0p2mm_px_axis_raycast": (0.2 / median("mm_per_px_axis_raycast"))
        if median("mm_per_px_axis_raycast") else None,
        "rim_fraction_of_object_median_all": median("rim_fraction_of_object"),
        "structure_0p2mm_px": (
            (0.2 / median("mm_per_px_measured")) if median("mm_per_px_measured") else None),
    }


if __name__ == "__main__":
    raise SystemExit(main())
