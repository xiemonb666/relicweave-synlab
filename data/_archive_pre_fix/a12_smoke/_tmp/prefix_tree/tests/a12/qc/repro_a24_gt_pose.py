"""A24 independent reproduction: does a corrupted GT pose table reach the SfM chain?

Runs ``synlab.observe.mvs_subset.audit_source_dependency`` (the real pycolmap chain on real
rendered frames) several times and records, per run:

* whether the feature/descriptor hashes of the true-pose and corrupted-pose runs are
  bit-identical,
* the sparse-point and reprojection deltas between them,
* the repeat-to-repeat band the audit measures as its tolerance,
* the verdict of every check.

The point is to separate two very different findings: a real GT-pose leak (the corrupted run
would move far outside anything the identical-input repeats do) versus an audit whose
tolerance is smaller than the matcher's own run-to-run band.

Run:  .venv\\Scripts\\python.exe tests\\a12\\qc\\repro_a24_gt_pose.py --runs 2
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT = ROOT / "data" / "a12" / "reports" / "a24_gt_pose_repro.json"
DEMO_STORE = ROOT / "data" / "a12_demo" / "store"
AUDIT_CONFIG = dict(frames_per_fragment=4, delivered_size=(640, 480),
                    render_pixels=640 * 480, max_image_size=640, max_num_features=8192)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--out-dir", default=str(ROOT / "data" / "a12" / "tmp" / "a24_repro"))
    args = parser.parse_args()

    from synlab.observe.mvs_subset import MvsConfig, audit_source_dependency

    payload: dict[str, Any] = {"check": "A24 gt_pose_invariance independent reproduction",
                               "command": "tests/a12/qc/repro_a24_gt_pose.py",
                               "runs": []}
    for index in range(args.runs):
        workdir = Path(args.out_dir) / f"run{index}"
        started = time.time()
        audit = audit_source_dependency(DEMO_STORE, out_dir=workdir, frames=4,
                                        repeats=4, config=MvsConfig(**AUDIT_CONFIG))
        metrics = audit["metrics"]
        check = audit["checks"]["gt_pose_invariance"]
        detail = check["detail"]
        repeats = [r["mean_reprojection_error_px"] for r in metrics["repeat_runs"]]
        entry = {
            "index": index,
            "seconds": round(time.time() - started, 2),
            "ok": bool(audit["ok"]),
            "status": audit["status"],
            "checks": {k: v["ok"] for k, v in audit["checks"].items()},
            "gt_pose_invariance": {
                "identical": detail["identical"],
                "keypoints_hash_identical": detail["keypoints_hash_identical"],
                "same_registered_set": detail["same_registered_set"],
                "point_delta": detail["point_delta"],
                "reprojection_delta_px": detail["reprojection_delta_px"],
                "tolerance": detail["tolerance"],
                "true_points": metrics["true_run"]["sparse_points"],
                "corrupted_points": metrics["corrupted_run"]["sparse_points"],
                "true_reproj_px": metrics["true_run"]["mean_reprojection_error_px"],
                "corrupted_reproj_px": metrics["corrupted_run"]["mean_reprojection_error_px"],
                "repeat_points": [r["sparse_points"] for r in metrics["repeat_runs"]],
                "repeat_reproj_px": repeats,
                "repeat_points_spread": max([r["sparse_points"] for r in metrics["repeat_runs"]])
                - min([r["sparse_points"] for r in metrics["repeat_runs"]]),
                "repeat_reproj_spread_px": max(repeats) - min(repeats),
            },
            "control_keypoints_hash_identical": (
                metrics["control_run"]["keypoints_hash"] == metrics["true_run"]["keypoints_hash"]),
            "pose_table_translation_delta_mm": metrics["pose_table_translation_delta_mm"],
            "pose_table_rotation_delta_deg": metrics["pose_table_rotation_delta_deg"],
            "workdir": str(workdir),
        }
        payload["runs"].append(entry)
        payload["summary"] = {
            "n_runs": len(payload["runs"]),
            "all_checks_ok": all(all(r["checks"].values()) for r in payload["runs"]),
            "gt_pose_invariance_all_true": all(r["gt_pose_invariance"]["identical"]
                                               for r in payload["runs"]),
            "keypoints_identical_all_runs": all(r["gt_pose_invariance"]["keypoints_hash_identical"]
                                                for r in payload["runs"]),
            "max_point_delta": max(r["gt_pose_invariance"]["point_delta"] for r in payload["runs"]),
            "max_reprojection_delta_px": max(r["gt_pose_invariance"]["reprojection_delta_px"]
                                             for r in payload["runs"]),
            "min_points_tolerance": min(r["gt_pose_invariance"]["tolerance"]["points"]
                                        for r in payload["runs"]),
            "min_reprojection_tolerance_px": min(
                r["gt_pose_invariance"]["tolerance"]["reprojection_px"] for r in payload["runs"]),
            "observed_repeat_reproj_values_px": [v for r in payload["runs"]
                                                 for v in r["gt_pose_invariance"]["repeat_reproj_px"]],
        }
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
                       encoding="utf-8")
        g = entry["gt_pose_invariance"]
        print(f"[run {index}] ok={entry['ok']} identical={g['identical']} "
              f"kp_hash_same={g['keypoints_hash_identical']} d_points={g['point_delta']} "
              f"d_reproj={g['reprojection_delta_px']:.6f} tol_points={g['tolerance']['points']} "
              f"tol_reproj={g['tolerance']['reprojection_px']:.6f} "
              f"repeat_reproj={[round(v, 4) for v in g['repeat_reproj_px']]}")
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
