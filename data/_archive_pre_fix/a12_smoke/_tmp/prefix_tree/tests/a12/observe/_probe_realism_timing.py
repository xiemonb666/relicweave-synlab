"""Scratch timing probe for the realism work (not a test; run manually).

Measures, on this host and at the resolution the pipeline actually delivers
(``image_long_edge_px=1024`` -> 1024x768, ``max_render_pixels=786432``):

* one Blender/Cycles view  (``renderer="blender"``)
* one software-rasteriser view (``renderer="auto"``)

so the wall-clock budget of the realistic pilot can be stated from measurement
instead of a guess.  Writes ``data/a12/reports/realism_timing_probe.json`` when
``--out`` is given.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import trimesh  # noqa: E402

from synlab.cameras.profiles import profile_by_id  # noqa: E402
from synlab.observe.imaging import ImagingSpec  # noqa: E402
from synlab.observe.routes import ObsSpec, render_views, resolve_target  # noqa: E402
from synlab.seeds import make_rng  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--views", type=int, default=1)
    ap.add_argument("--backend", default="blender")
    ap.add_argument("--out", default=None)
    ap.add_argument("--samples", type=int, default=32)
    args = ap.parse_args()

    box = trimesh.creation.box(extents=(60.0, 42.0, 26.0))
    target = resolve_target(box, fragment_id="timing_box")
    profile = profile_by_id("CAM_MID_V3")
    spec = ObsSpec(
        view_count=int(args.views), delivered_size=(1024, 768), max_render_pixels=786432,
        master_seed=20261001, lineage_id="timing_probe",
        renderer=args.backend, distortion_policy="undistort",
        imaging=ImagingSpec(encode="JPEG", jpeg_quality=85, defocus_sigma_px=1.0,
                            effective_gain=0.02, read_noise_sigma=0.004),
    )
    if args.backend == "blender":
        from synlab.observe.blender import BlenderBackendConfig

        spec.blender_config = BlenderBackendConfig(
            samples=int(args.samples), f_number=float(profile.f_number),
            coc_px_threshold=0.75 * float(profile.f_number), run_label="timing_probe",
            work_root=str(ROOT / "data" / "a12" / "reports" / "blender" / "_work"))
    rng = make_rng(20261001, "timing_probe", "camera")
    t0 = time.time()
    bundles = render_views(target, profile, spec, rng, backend=args.backend)
    seconds = time.time() - t0
    b = bundles[0]
    report = {
        "backend_requested": args.backend,
        "views": len(bundles),
        "seconds": round(seconds, 3),
        "seconds_per_view": round(seconds / max(len(bundles), 1), 3),
        "delivered_size": list(b.imaging.image.shape[:2][::-1]),
        "render_size": list(b.render_frame.image_size),
        "render_backend": b.backend,
        "distortion": b.distortion,
        "delivered_K": np.asarray(b.K).tolist(),
        "delivered_dist_is_none": None,
        "imaging_labels": list(b.imaging.labels),
        "imaging_identity": bool(spec.imaging.is_identity()),
        "mask_coverage": float(np.mean(b.deploy_mask)),
        "depth_valid": float(np.mean(np.isfinite(b.render.depth_z))),
        "uncertain_fraction": float(np.mean(b.imaging.uncertain_mask)),
        "blender_meta": {
            k: b.render.meta.get(k) for k in
            ("backend", "engine", "samples_requested", "samples_used", "denoise",
             "elapsed_seconds", "render_seconds", "blender_version")
        } if args.backend == "blender" else None,
    }
    # the delivered frame's distortion state (None == undistorted pinhole delivery)
    from synlab.observe.routes import _frame_for_delivered

    frame = _frame_for_delivered(b, spec)
    report["delivered_dist_is_none"] = frame.dist is None
    report["delivered_camera_model"] = frame.camera_model
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str),
                       encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
