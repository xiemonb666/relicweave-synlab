"""Scratch: verify the extras view and the untouched training-package checker."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.stdout.reconfigure(encoding="utf-8")

PY = str(REPO / ".venv" / "Scripts" / "python.exe")
PKG = REPO / "data" / "a12_exports" / "a12_extras"


def run(argv: list[str]) -> tuple[int, str]:
    proc = subprocess.run(argv, cwd=str(REPO), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=1800)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


out: dict = {}

# 1. the sibling training package must still be consistent
for label, pkg in (
    ("a12_extras/training_package", PKG / "training_package"),
    ("closed_loop/training_package (untouched)", REPO / "data" / "a12_exports"
     / "closed_loop" / "training_package"),
):
    code, text = run([PY, str(REPO / "tools" / "load_package.py"),
                      "--package", str(pkg), "--check"])
    tail = [line for line in text.splitlines()
            if line.startswith("[FAIL]") or line.startswith("[PASS] file_set")
            or "exit" in line.lower()][:6]
    out[f"load_package::{label}"] = {"exit": code, "lines": tail}

# 2. the extras view itself
code, text = run([PY, str(REPO / "tools" / "load_extras.py"),
                  "--package", str(PKG), "--check"])
out["load_extras::check"] = {"exit": code, "text": text.strip().splitlines()}

code, text = run([PY, str(REPO / "tools" / "load_extras.py"),
                  "--package", str(PKG), "--json", "--list"])
listing = json.loads(text) if code == 0 else {}
out["load_extras::list"] = {"exit": code, "totals": listing.get("totals")}

# 3. the deploy view's channel set vs the extras channel set
deploy_index = PKG / "training_package" / "deploy" / "obs" / "index.json"
deploy_channels = []
if deploy_index.exists():
    deploy_channels = json.loads(deploy_index.read_text(encoding="utf-8")).get(
        "channel_names", [])
extras_index = json.loads((PKG / "synthetic_extra" / "index.json").read_text("utf-8"))
extras_channels = sorted({name for row in extras_index["rows"].values()
                          for name in row["arrays"]})
out["channel_diff"] = {
    "deploy_index_exists": deploy_index.exists(),
    "deploy_channel_names": deploy_channels,
    "extras_channel_count": len(extras_channels),
    "extras_only": sorted(set(extras_channels) - set(deploy_channels)),
    "shared": sorted(set(extras_channels) & set(deploy_channels)),
}

# 4. files under deploy/research and the extras directory listing
all_files = sorted(str(p.relative_to(PKG)).replace("\\", "/")
                   for p in PKG.rglob("*") if p.is_file())
out["package_files"] = {
    "total": len(all_files),
    "under_deploy": [f for f in all_files if f.startswith("training_package/deploy/")][:12],
    "under_research": [f for f in all_files if f.startswith("training_package/research/")],
    "under_synthetic_extra": [f for f in all_files
                              if f.startswith("synthetic_extra/")][:24],
    "top_level": sorted({f.split("/")[0] for f in all_files}),
}

(REPO / "_tmp_extras_verify.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
