"""Bounded launcher/worker for the first conformal bowl volume mesh."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "vesselforge/src"))
sys.path.insert(0, str(ROOT / "pgfrag/experiments"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    out = Path(args.out)
    if args.worker:
        from cad_volume_spike import _load_gmsh
        from vesselforge.tetra_partition import partition_step_at_x
        gmsh = _load_gmsh()
        gmsh.initialize()
        try:
            result = partition_step_at_x(gmsh, ROOT / "vesselforge/data/continuation_20261015/spherical_bowl/three_bands", out / "mesh")
            print(json.dumps(result, indent=2))
        finally:
            gmsh.finalize()
        return
    out.mkdir(parents=True, exist_ok=False)
    snapshot = out / "source_snapshot"
    snapshot.mkdir()
    sources = [Path(__file__), ROOT / "vesselforge/src/vesselforge/tetra_partition.py",
               ROOT / "pgfrag/experiments/cad_volume_spike.py"]
    records = []
    for source in sources:
        target = snapshot / source.name
        shutil.copy2(source, target)
        records.append({"path": str(source), "snapshot": target.name, "sha256": digest(target), "bytes": target.stat().st_size})
    argv = [sys.executable, "-B", str(Path(__file__).resolve()), "--worker", "--out", str(out.resolve())]
    started = time.monotonic()
    receipt = {"argv": argv, "sources": records, "timeout_s": 120, "output_cap_bytes": 128 * 1024 * 1024}
    try:
        completed = subprocess.run(argv, capture_output=True, text=True, timeout=120, check=False)
        (out / "stdout.log").write_text(completed.stdout, encoding="utf-8")
        (out / "stderr.log").write_text(completed.stderr, encoding="utf-8")
        receipt["return_code"] = completed.returncode
        receipt["status"] = "PASS_GEOMETRY_DIAGNOSTIC" if completed.returncode == 0 else "FAILED"
    except subprocess.TimeoutExpired:
        receipt["status"] = "FAILED_TIMEOUT"
    receipt["elapsed_s"] = time.monotonic() - started
    receipt["source_unchanged"] = all(digest(Path(r["path"])) == r["sha256"] for r in records)
    receipt["output_bytes"] = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
    if receipt["output_bytes"] > receipt["output_cap_bytes"] or not receipt["source_unchanged"]:
        receipt["status"] = "FAILED_BOUND_OR_SOURCE"
    (out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2))
    raise SystemExit(0 if receipt["status"] == "PASS_GEOMETRY_DIAGNOSTIC" else 2)


if __name__ == "__main__":
    main()
