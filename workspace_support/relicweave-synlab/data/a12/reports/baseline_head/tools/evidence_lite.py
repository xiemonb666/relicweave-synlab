"""Evidence-lite: produce every report that the acceptance harness can read right now.

Each step runs in this process with a real command and real output; a step that cannot run
records the honest reason instead of being skipped silently.  Heavy steps (full generation,
training) are intentionally left to `tools/run_evidence.py`.

    python tools/evidence_lite.py --data-root data/a12 --profile SANDBOX_CORE
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def write(store_root: Path, name: str, payload: dict) -> Path:
    path = store_root / "reports" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str),
                    encoding="utf-8")
    return path


def step(name: str, fn) -> dict:
    start = time.perf_counter()
    try:
        payload = fn() or {}
        payload.setdefault("ok", False)
    except Exception as exc:  # noqa: BLE001
        payload = {"ok": False, "status": "NOT_RUN", "error": f"{type(exc).__name__}: {exc}",
                   "traceback": traceback.format_exc()[-1200:]}
    payload["seconds"] = round(time.perf_counter() - start, 2)
    print(f"[{name}] ok={payload.get('ok')} {payload.get('status', '')} "
          f"{str(payload.get('error', ''))[:160]}", flush=True)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", default="data/a12")
    parser.add_argument("--profile", default="SANDBOX_CORE")
    args = parser.parse_args()
    store_root = (ROOT / args.data_root) if not Path(args.data_root).is_absolute() else Path(args.data_root)
    store_root.mkdir(parents=True, exist_ok=True)

    from synlab.qc.acceptance import run_acceptance
    from synlab.registry import REGISTRY, load_all
    from synlab.storage.store import AssetStore, health_check

    modules = step("load_all", lambda: {"ok": True, "modules": load_all()})
    summary = REGISTRY.summary()
    write(store_root, "registry_summary", {"ok": bool(summary), "counts":
          {k: v["count"] for k, v in summary.items()}, "by_status":
          {k: v["by_status"] for k, v in summary.items()}})
    store = AssetStore(store_root)

    step("pattern_audit", lambda: _pattern_audit(store, store_root))
    step("operator_audit", lambda: _operator_audit(store, store_root))
    step("diagnostics_fixtures", lambda: _fixtures(store_root))
    step("observe_audits", lambda: _observe(store_root))
    step("store_health", lambda: _health(store_root))
    step("dry_runs", lambda: _dry_runs(store_root))

    acceptance = run_acceptance(store_root=store_root, profile=args.profile,
                               report_path=ROOT / "docs/a12/acceptance_report.md")
    print("acceptance:", acceptance["counts"], flush=True)
    proc = subprocess.run([sys.executable, str(ROOT / "tools" / "gen_status_matrix.py"),
                           "--data-root", str(store_root)], capture_output=True, text=True, check=False)
    print(proc.stdout.strip() or proc.stderr.strip()[-500:], flush=True)
    write(store_root, "evidence_lite_summary", {"ok": True, "modules": modules,
                                               "acceptance": acceptance["counts"]})
    return 0


def _pattern_audit(store, store_root: Path) -> dict:
    from synlab.patterns.audit_all import audit_all_patterns

    report = audit_all_patterns(store, commit=True)
    write(store_root, "pattern_audit", report)
    return {"ok": bool(report.get("ok")), "status": report.get("status"),
            "families": len(report.get("families", {})),
            "max_seam_error": report.get("max_seam_error"),
            "geometry_applied": report.get("geometry_applied")}


def _operator_audit(store, store_root: Path) -> dict:
    from synlab.degrade.api import audit_all_axes

    report = audit_all_axes(store, levels=[0, 1, 2, 3, 4])
    write(store_root, "operator_audit", report)
    axes = report.get("axes", {})
    return {"ok": bool(report.get("ok")), "status": report.get("status"),
            "axes": len(axes), "identity_ok": report.get("identity_ok"),
            "with_20_mothers": len([a for a, v in axes.items()
                                    if isinstance(v, dict) and v.get("independent_mothers", 0) >= 20])}


def _fixtures(store_root: Path) -> dict:
    from synlab.diagnostics.fixtures import run_fixtures

    report = run_fixtures()
    write(store_root, "metric_fixture", report.get("metrics", {"ok": False}))
    write(store_root, "stat_fixture", report.get("stats", {"ok": False}))
    return {"ok": bool(report.get("metrics", {}).get("ok")) and bool(report.get("stats", {}).get("ok")),
            "metrics_passed": report.get("metrics", {}).get("checks_passed"),
            "stats_passed": report.get("stats", {}).get("checks_passed")}


def _observe(store_root: Path) -> dict:
    from synlab.observe.audit import audit_camera_profiles, audit_channels, audit_spurious

    channels = audit_channels(None)
    spurious = audit_spurious(None)
    cameras = audit_camera_profiles(None)
    write(store_root, "channel_audit", channels)
    write(store_root, "spurious_audit", spurious)
    write(store_root, "camera_profile_audit", cameras)
    return {"ok": bool(channels.get("ok") and spurious.get("ok") and cameras.get("ok")),
            "status": cameras.get("status"),
            "channels": channels.get("metrics", {}).get("depth_median_abs_error_mm"),
            "spurious_variants": list(spurious.get("metrics", {}).get("variants", {})),
            "camera_engineering_ok": cameras.get("engineering_ok"),
            "camera_calibration_ok": cameras.get("calibration_ok")}


def _health(store_root: Path) -> dict:
    report = health_check(str(store_root))
    write(store_root, "store_health", report)
    return report


def _dry_runs(store_root: Path) -> dict:
    """CLI dry runs: validate/budget/genuine refusals (real exit codes)."""
    results: dict[str, dict] = {}
    for name, argv in (("validate_sandbox", ["-m", "synlab.cli", "validate", "--config",
                                             "configs/a12/sandbox.yaml", "--json"]),
                       ("budget_sandbox", ["-m", "synlab.cli", "budget", "--config",
                                           "configs/a12/sandbox.yaml", "--json"]),
                       ("registry_cli", ["-m", "synlab.cli", "registry", "--json"])):
        proc = subprocess.run([sys.executable, *argv], cwd=str(ROOT), capture_output=True, text=True,
                              timeout=600, check=False)
        results[name] = {"exit": proc.returncode,
                         "stdout": (proc.stdout or "")[:600], "stderr": (proc.stderr or "")[-300:]}
    write(store_root, "cli_dry_runs", results)
    return {"ok": all(v["exit"] == 0 for k, v in results.items() if k != "validate_sandbox")
            and results["validate_sandbox"]["exit"] in (0, 3),
            "cli": {k: v["exit"] for k, v in results.items()}}


if __name__ == "__main__":
    raise SystemExit(main())
