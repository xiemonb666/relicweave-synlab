"""Scratch smoke probe for synlab.observe.realism (not a test; run manually).

Checks, without rendering:
  * level 0 -> ImagingSpec.is_identity() is True, level 1 -> False
  * the declared ladder values are read back from a *synthesised* stage list
  * distortion policy resolution for the three profiles x {blender, software}
  * observe_spec_from_config on configs/a12/realistic.yaml (fields + declared values)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from synlab.cameras.api import camera_profiles  # noqa: E402
from synlab.config import load_generation_spec  # noqa: E402
from synlab.errors import SynLabError  # noqa: E402
from synlab.observe.realism import (  # noqa: E402
    APPLIED_AXES,
    degradation_report,
    distortion_evidence,
    imaging_spec_for,
    observe_spec_from_config,
    resolve_distortion_policy,
)


def main() -> int:
    out: dict = {"applied_axes": list(APPLIED_AXES)}
    ident = imaging_spec_for({axis: 0 for axis in APPLIED_AXES})
    out["level0_identity"] = bool(ident.is_identity())
    lvl1 = imaging_spec_for()
    out["level1_identity"] = bool(lvl1.is_identity())
    out["level1_spec"] = {
        "defocus_sigma_px": lvl1.defocus_sigma_px, "effective_gain": lvl1.effective_gain,
        "read_noise_sigma": lvl1.read_noise_sigma, "exposure_ev": lvl1.exposure_ev,
        "white_balance": list(lvl1.white_balance), "encode": lvl1.encode,
        "jpeg_quality": lvl1.jpeg_quality,
    }
    out["degradation_report_levels"] = degradation_report()["levels"]

    profiles = {p.profile_id: p for p in camera_profiles()}
    out["distortion"] = {pid: distortion_evidence(p) for pid, p in profiles.items()}
    policies = {}
    for pid, profile in profiles.items():
        for backend in ("BLENDER_CYCLES", "SOFTWARE_RASTERIZER"):
            for policy in (None, "error", "undistort", "ignore"):
                key = f"{pid}|{backend}|{policy}"
                try:
                    policies[key] = resolve_distortion_policy(profile, backend,
                                                              policy=policy)["decision"]
                except SynLabError as exc:
                    policies[key] = f"RAISED:{exc.code.value}"
    out["policy_matrix"] = policies

    spec = load_generation_spec(str(ROOT / "configs" / "a12" / "realistic.yaml"))
    plan = observe_spec_from_config(spec, store_root=ROOT / "data" / "a12_realistic",
                                    lineage_id="LIN0000_probe")
    out["plan"] = plan.as_dict()
    out["obs_spec"] = {
        "renderer": plan.obs_spec.renderer,
        "distortion_policy": plan.obs_spec.distortion_policy,
        "delivered_size": list(plan.obs_spec.delivered_size),
        "max_render_pixels": plan.obs_spec.max_render_pixels,
        "view_count": plan.obs_spec.view_count,
        "imaging_identity": plan.obs_spec.imaging.is_identity(),
        "route_params": {k: v for k, v in plan.obs_spec.route_params.items()},
        "blender_config": {k: v for k, v in (plan.obs_spec.blender_config.as_config().items())
                           if k in ("samples", "f_number", "coc_px_threshold",
                                    "distortion_policy", "work_root", "run_label", "denoise",
                                    "seed", "timeout_s")},
    }
    print(json.dumps(out, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
