"""Write data/a12_campaign/campaign_manifest.json -- the generation fingerprint of this campaign.

Read-only with respect to the store and the package; the only file written is the manifest.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from synlab.canonical import hash_file  # noqa: E402
from synlab.registry import REGISTRY, load_all  # noqa: E402

CAMPAIGN = REPO / "data" / "a12_campaign"
CONFIG = "configs/a12/realistic.yaml"
BASELINE_CONFIG = "configs/a12/next_experiment.yaml"


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True,
                          encoding="utf-8", errors="replace").stdout.strip()


def main() -> int:
    reports = load_all()
    dirty = [line for line in git("status", "--porcelain").splitlines() if line.strip()]
    validate = subprocess.run(
        [str(REPO / ".venv" / "Scripts" / "python.exe"), "-m", "synlab.cli", "validate",
         "--config", CONFIG],
        cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace")

    manifest = {
        "schema": "synlab.a12_campaign.manifest.v1",
        "campaign": "a12_campaign",
        "config_used": CONFIG,
        "config_sha256": hash_file(REPO / CONFIG),
        "baseline_config_frozen": {
            "path": BASELINE_CONFIG,
            "sha256": hash_file(REPO / BASELINE_CONFIG),
            "frozen_expected": "sha256:8186653101612cbc20e9eeba3f60ffbc241e3d1e3ebd690fdecb60746ab1fb16",
        },
        "baseline_config_unmodified": (
            hash_file(REPO / BASELINE_CONFIG)
            == "sha256:8186653101612cbc20e9eeba3f60ffbc241e3d1e3ebd690fdecb60746ab1fb16"),
        "registry_fingerprint": REGISTRY.fingerprint(),
        "registry_counts": {k: {"count": v["count"], "by_status": v["by_status"]}
                            for k, v in REGISTRY.summary().items()},
        "load_all_errors": {k: v for k, v in reports.items() if v != "OK"},
        "git": {
            "head": git("rev-parse", "HEAD"),
            "dirty": bool(dirty),
            "dirty_files": dirty,
            "dirty_count": len(dirty),
        },
        "validate": {
            "command": f"python -m synlab.cli validate --config {CONFIG}",
            "exit_code": validate.returncode,
            "first_line": (validate.stdout or "").splitlines()[0] if validate.stdout else "",
        },
        "store_root": "data/a12_campaign/store",
        "ledger": "data/a12_campaign/campaign_ledger.json",
        "batch_reports": "data/a12/reports/campaign_batches.json",
        "note": ("the plan is derived only from master_seed + vessel/material/pattern/layer lists "
                 "+ target_mothers, so lineage i equals lineage i of data/a12; batching cannot "
                 "shift any lineage"),
    }
    out = CAMPAIGN / "campaign_manifest.json"
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in manifest.items()
                      if k not in {"git", "registry_counts"}}, ensure_ascii=False, indent=2))
    print("dirty_count:", manifest["git"]["dirty_count"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
