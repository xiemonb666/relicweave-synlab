"""Freeze the reviewed coupled-patch attempt without changing earlier evidence."""
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]
EXP = ROOT / "pgfrag/experiments/free_cohesive_patch_20261015"


def main():
    destination = EXP / "frozen_run03"
    destination.mkdir(exist_ok=False)
    case = json.loads((EXP / "case.json").read_text(encoding="utf-8"))
    bound_report = ROOT / "experiments/continuation_20261015/root_cohesive_bound.json"
    bound = json.loads(bound_report.read_text(encoding="utf-8"))
    envelope = bound["bounds"]["isotropic_material_envelope"]
    assert bound["proposed_dt_passes_initial_bound"]
    case["stability"].update({
        "total_stability_status": "ESTABLISHED_PARENT_REVIEWED_BOUND",
        "lambda_max_upper_bound_per_s2": envelope["lambda_upper_bound_per_s2"],
        "fraction_limit": .5,
        "scope": bound["scope"],
        "preflight_state_file": "native_zero_step_state.npz",
        "preflight_state_sha256": bound["preflight_state_sha256"],
        "initial_bound_report_sha256": hashlib.sha256(bound_report.read_bytes()).hexdigest(),
        "trajectory_limit": "initial/material high-frequency bound only; current-normal geometric derivatives and softening integration accuracy remain independently assessed",
    })
    case["run_authorization"] = "ROOT_CONTINUATION_20261015_REVIEWED_NEW_RUN"
    (destination / "case.json").write_text(json.dumps(case, indent=2) + "\n", encoding="utf-8")
    names = ["run_native_free_patch.py", "analyze_native_free_patch.py", "free_patch_contract.py",
             "test_source_contract.py", "block_2x2x4mm.msh", "material.dat", "launch_free_patch.sh"]
    for name in names:
        shutil.copy2(EXP / name, destination / name)
    shutil.copy2(EXP / "preflight_readback_02/native_zero_step_state.npz", destination / "native_zero_step_state.npz")
    shutil.copy2(bound_report, destination / "root_cohesive_bound.json")
    shutil.copy2(ROOT / "pgfrag/src/pgfrag/cohesive_stability.py", destination / "cohesive_stability.py")
    records = [{"path": p.name, "bytes": p.stat().st_size,
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(destination.iterdir()) if p.is_file()]
    (destination / "source_freeze.json").write_text(json.dumps({"scope": "reviewed new coupled-patch attempt", "files": records}, indent=2) + "\n", encoding="utf-8")
    print(destination)


if __name__ == "__main__":
    main()
