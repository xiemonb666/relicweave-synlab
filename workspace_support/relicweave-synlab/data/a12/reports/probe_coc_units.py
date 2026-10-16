"""Is the delivered `uncertain_mask` (defocus / circle-of-confusion) physically justified?

The renderer marks a pixel uncertain when
``circle_of_confusion_px(depth, focus, f_number=1.0, f_px) > spec.coc_px_threshold``
(``synlab/observe/render.py``), and that helper returns ``f_px**2 / (N * z) * |z - zf| / zf``
with ``f_px`` in **pixels** and ``z`` in **millimetres**.  The correct delivered-pixel CoC is
the same expression *in millimetres* multiplied by the sensor sampling density
``D = delivered_width_px / sensor_width_mm`` (because ``f_px = f_mm * D``), i.e. the renderer
value is larger than the declared-optics CoC by ``D * N_declared``.

This probe measures, per delivered view:

* the committed mask/uncertain counters (what the pipeline actually produced);
* the renderer CoC recomputed from the committed depth;
* the same optics evaluated at the declared focal length and f-number, converted with ``D``;
* the declared thin-lens depth of field from ``cameras.profiles.thin_lens_dof`` at both the
  sensor pitch and the delivered-pixel criterion.

Usage:
  python data/a12/reports/probe_coc_units.py --store <store> --obs <asset_id>
                                             --profile CAM_MID_V3 --out <json>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synlab.cameras.profiles import profile_by_id, thin_lens_dof  # noqa: E402
from synlab.observe.render import circle_of_confusion_px  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402


def probe(store_root: Path, obs_id: str, profile_id: str) -> dict:
    store = AssetStore(store_root)
    profile = profile_by_id(profile_id)
    sensor_width_mm = float(profile.meta["sensor_width_mm"])
    focal_length_mm = float(profile.meta["focal_length_mm"])
    record = store.get_asset(obs_id)
    arrays = store.load_arrays(obs_id)
    views_meta = list((record.meta or {}).get("views") or [])
    out: dict = {
        "obs_asset": obs_id, "store": str(store_root),
        "profile": {"profile_id": profile.profile_id, "f_number": float(profile.f_number),
                    "focal_length_mm": focal_length_mm,
                    "sensor_width_mm": sensor_width_mm,
                    "native_image_size": [int(x) for x in profile.image_size],
                    "working_distance_mm": float(profile.working_distance_mm),
                    "declared_depth_of_field_mm": [float(x) for x in profile.depth_of_field_mm],
                    "coC_px": profile.meta.get("coC_px")},
        "views": [],
    }
    for index, view_meta in enumerate(views_meta):
        prefix = f"v{index:03d}."
        if prefix + "depth_z" not in arrays:
            continue
        depth = np.asarray(arrays[prefix + "depth_z"], dtype=np.float64)
        id_map = np.asarray(arrays[prefix + "id_map"])
        uncertain = np.asarray(arrays[prefix + "uncertain_mask"], dtype=bool)
        mask = np.asarray(arrays[prefix + "deployment_mask"], dtype=bool)
        K = np.asarray(arrays[prefix + "K"], dtype=np.float64)
        height, width = id_map.shape
        D = width / sensor_width_mm                       # delivered px per mm of sensor
        f_px = 0.5 * (float(K[0, 0]) + float(K[1, 1]))
        focus = float(view_meta.get("working_distance_mm") or profile.working_distance_mm)
        obj = id_map >= 0
        coc_render = circle_of_confusion_px(depth, focus, 1.0, f_px)
        coc_declared = circle_of_confusion_px(depth, focus, float(profile.f_number), f_px) / D
        mm_per_px = focus / max(float(K[0, 0]), 1e-9)
        sensor_pitch_mm = sensor_width_mm / float(profile.image_size[0])
        row = {
            "view": index, "view_id": view_meta.get("view_id"),
            "delivered_size": [int(width), int(height)],
            "delivered_px_per_mm_of_sensor": float(D),
            "f_px": f_px, "focal_length_mm_from_f_px": float(f_px / D),
            "focal_length_mm_declared": focal_length_mm,
            "working_distance_mm": focus, "mm_per_px_at_object": float(mm_per_px),
            "object_px": int(np.count_nonzero(obj)),
            "uncertain_px_on_object": int(np.count_nonzero(uncertain & obj)),
            "uncertain_ratio": float(np.count_nonzero(uncertain & obj)
                                     / max(int(np.count_nonzero(obj)), 1)),
            "mask_px": int(np.count_nonzero(mask)),
            "mask_over_object": float(np.count_nonzero(mask)
                                      / max(int(np.count_nonzero(obj)), 1)),
            "coc_render_p50_px": float(np.nanpercentile(coc_render[obj], 50)),
            "coc_render_p95_px": float(np.nanpercentile(coc_render[obj], 95)),
            "coc_declared_p50_px": float(np.nanpercentile(coc_declared[obj], 50)),
            "coc_declared_p95_px": float(np.nanpercentile(coc_declared[obj], 95)),
            "renderer_over_declared_ratio_p50": float(
                np.nanpercentile(coc_render[obj], 50) / max(np.nanpercentile(coc_declared[obj], 50), 1e-12)),
            "expected_ratio_D_times_fnumber": float(D * float(profile.f_number)),
            "depth_span_mm": float(np.nanmax(depth[obj]) - np.nanmin(depth[obj])),
            "depth_offset_p50_mm": float(np.nanpercentile(np.abs(depth[obj] - focus), 50)),
            "declared_markout_px": float(profile.meta.get("coC_px") or 0.75),
            "dof_sensor_pitch_mm": [float(x) for x in thin_lens_dof(
                focus, focal_length_mm, float(profile.f_number),
                float(profile.meta.get("coC_px") or 0.75), sensor_pitch_mm)],
            "dof_delivered_grid_mm": [float(x) for x in thin_lens_dof(
                focus, focal_length_mm, float(profile.f_number),
                float(profile.meta.get("coC_px") or 0.75), 1.0 / D)],
        }
        row["declared_coc_below_markout_ratio"] = float(
            np.mean(coc_declared[obj] <= row["declared_markout_px"]))
        row["renderer_coc_below_pipeline_threshold_ratio"] = float(
            np.mean(coc_render[obj] <= 0.75 * 8.0))
        out["views"].append(row)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", default="data/a12_exports/closed_loop/store")
    parser.add_argument("--obs", default="asset_dc7ee32fda6da99aba68")
    parser.add_argument("--profile", default="CAM_MID_V3")
    parser.add_argument("--out", default="data/a12/reports/visible_labels_coc_units.json")
    args = parser.parse_args()
    report = probe(Path(args.store), args.obs, args.profile)
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
