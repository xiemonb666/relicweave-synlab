"""Run the full evidence chain and write the reports the acceptance harness consumes.

    python tools/run_evidence.py --config configs/a12/sandbox.yaml --profile SANDBOX_CORE

Each step is attempted for real.  A missing capability is recorded as NOT_RUN/PENDING with
the concrete reason instead of being skipped silently, so the acceptance report stays honest.
"""

from __future__ import annotations

import argparse
import json
import time
import traceback
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]


def write_report(store_root: Path, name: str, payload: dict[str, Any]) -> Path:
    path = store_root / "reports" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str),
                    encoding="utf-8")
    return path


def attempt(name: str, func: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    start = time.perf_counter()
    try:
        payload = func()
        payload.setdefault("ok", False)
    except Exception as exc:  # noqa: BLE001 - evidence collection must never crash the run
        payload = {"ok": False, "status": "NOT_RUN", "error": f"{type(exc).__name__}: {exc}",
                   "traceback": traceback.format_exc()[-1500:]}
    payload["seconds"] = round(time.perf_counter() - start, 3)
    print(f"[{name}] {'OK' if payload.get('ok') else 'NOT_OK'} "
          f"{json.dumps({k: v for k, v in payload.items() if k in ('status', 'error')}, ensure_ascii=False)[:200]}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/a12/sandbox.yaml")
    parser.add_argument("--profile", default="SANDBOX_CORE")
    parser.add_argument("--data-root", default="data/a12")
    parser.add_argument("--max-mothers", type=int, default=0)
    parser.add_argument("--skip-generate", action="store_true")
    parser.add_argument("--train-steps", type=int, default=0)
    args = parser.parse_args()

    store_root = (ROOT / args.data_root) if not Path(args.data_root).is_absolute() else Path(args.data_root)
    store_root.mkdir(parents=True, exist_ok=True)

    from synlab.config import compile_spec, load_generation_spec
    from synlab.qc.acceptance import run_acceptance
    from synlab.registry import load_all
    from synlab.storage.store import AssetStore, health_check

    load_all()
    store = AssetStore(store_root)
    spec = load_generation_spec(ROOT / args.config)
    spec.storage.root = str(store_root)
    summaries: dict[str, Any] = {}

    # ---------------------------------------------------------------- generation
    run_id: str | None = None
    if not args.skip_generate:
        def do_generate() -> dict[str, Any]:
            from synlab.pipeline import run_generation

            report = run_generation(spec, store_root=store_root,
                                    max_mothers=args.max_mothers or None)
            report["ok"] = report.get("accepted", 0) > 0
            report["status"] = "QA_PASSED" if report["ok"] else "FAILED"
            return report

        summary = attempt("generate", do_generate)
        summaries["generate"] = summary
        run_id = summary.get("run_id")
    else:
        latest = sorted((store_root / "reports").glob("generation_run_*.json"))
        if latest:
            summary = json.loads(latest[-1].read_text(encoding="utf-8"))
            run_id = summary.get("run_id")
            summaries["generate"] = summary
    print(f"run_id = {run_id}")

    # ---------------------------------------------------------------- run audit
    if run_id:
        def do_audit() -> dict[str, Any]:
            from synlab.qc.audit import audit_run

            report = audit_run(store, run_id)
            write_report(store_root, f"audit_{run_id}", report)
            write_report(store_root, "audit_latest", report)
            return report

        summaries["audit"] = attempt("audit", do_audit)

        def do_profile() -> dict[str, Any]:
            from synlab.qc.profile import profile_run

            report = profile_run(store, run_id)
            write_report(store_root, "resource_profile", report)
            return report

        summaries["profile"] = attempt("profile", do_profile)

    # ---------------------------------------------------------------- aggregate fracture / physical audits
    if run_id:
        def do_fracture_audit() -> dict[str, Any]:
            ledger = store_root / "reports" / "coverage_rows.json"
            rows = json.loads(ledger.read_text(encoding="utf-8")) if ledger.exists() else []
            backends: dict[str, Any] = {}
            conservation: list[float] = []
            overlap: list[float] = []
            distances: list[float] = []
            for row in rows:
                audit = row.get("fracture_audit") or {}
                backend = row.get("backend") or "unknown"
                entry = backends.setdefault(backend, {"status": "PASS", "cases": 0, "failures": []})
                entry["cases"] += 1
                if not audit.get("ok", False):
                    entry["status"] = "FAIL"
                    entry["failures"].append(row.get("lineage_id"))
                for key, bucket in (("volume_relative_error", conservation),
                                    ("overlap_ratio", overlap),
                                    ("shared_distance_p95_mm", distances)):
                    value = audit.get(key)
                    if isinstance(value, (int, float)):
                        bucket.append(float(value))
            report = {
                "ok": bool(rows) and all(v["status"] == "PASS" for v in backends.values()),
                "backends": backends,
                "conservation_ratio_max": max(conservation) if conservation else None,
                "overlap_ratio_max": max(overlap) if overlap else None,
                "shared_distance_p95_max": max(distances) if distances else None,
                "cases": len(rows),
                "note": "aggregated from per-mother fracture audits recorded by the pipeline",
            }
            write_report(store_root, "fracture_audit", report)
            return report

        summaries["fracture_audit"] = attempt("fracture_audit", do_fracture_audit)

        def do_physical_audit() -> dict[str, Any]:
            ledger = store_root / "reports" / "coverage_rows.json"
            rows = json.loads(ledger.read_text(encoding="utf-8")) if ledger.exists() else []
            audits = [r.get("physical_audit") or {} for r in rows]
            ok = bool(audits) and all(a.get("ok", False) for a in audits)
            report = {
                "ok": ok,
                "cases": len(audits),
                "no_material_added": all(a.get("no_material_added", True) for a in audits),
                "nested_levels": all(a.get("nested", True) for a in audits),
                "watertight": all(a.get("watertight", True) for a in audits),
                "max_lost_volume_ratio": max((a.get("lost_volume_ratio", 0.0) or 0.0) for a in audits)
                if audits else None,
                "per_case": audits[:20],
            }
            write_report(store_root, "physical_audit", report)
            return report

        summaries["physical_audit"] = attempt("physical_audit", do_physical_audit)

    # ---------------------------------------------------------------- pattern audit
    def do_pattern_audit() -> dict[str, Any]:
        from synlab.patterns.audit_all import audit_all_patterns

        report = audit_all_patterns(store)
        write_report(store_root, "pattern_audit", report)
        return report

    summaries["pattern_audit"] = attempt("pattern_audit", do_pattern_audit)

    # ---------------------------------------------------------------- operator audit
    def do_operator_audit() -> dict[str, Any]:
        from synlab.degrade.api import audit_all_axes

        report = audit_all_axes(store, levels=[0, 1, 2, 3, 4])
        write_report(store_root, "operator_audit", report)
        return report

    summaries["operator_audit"] = attempt("operator_audit", do_operator_audit)

    # ---------------------------------------------------------------- observation audits
    def do_channel_audit() -> dict[str, Any]:
        from synlab.observe.audit import audit_channels

        report = audit_channels(store)
        write_report(store_root, "channel_audit", report)
        return report

    summaries["channel_audit"] = attempt("channel_audit", do_channel_audit)

    def do_spurious_audit() -> dict[str, Any]:
        from synlab.observe.audit import audit_spurious

        report = audit_spurious(store)
        write_report(store_root, "spurious_audit", report)
        return report

    summaries["spurious_audit"] = attempt("spurious_audit", do_spurious_audit)

    def do_camera_audit() -> dict[str, Any]:
        from synlab.observe.audit import audit_camera_profiles

        report = audit_camera_profiles(store)
        write_report(store_root, "camera_profile_audit", report)
        return report

    summaries["camera_profile_audit"] = attempt("camera_profile_audit", do_camera_audit)

    def do_pixel_contract() -> dict[str, Any]:
        from synlab.cameras.audit import audit_pixel_contract

        report = audit_pixel_contract(store)
        write_report(store_root, "pixel_contract", report)
        return report

    summaries["pixel_contract"] = attempt("pixel_contract", do_pixel_contract)

    # ---------------------------------------------------------------- pools
    def do_pool() -> dict[str, Any]:
        from synlab.relations.api import build_pool_from_config

        report = build_pool_from_config(store, f"{run_id}_release" if run_id else "sandbox",
                                        str(ROOT / "configs/a12/pool_dev.yaml"))
        write_report(store_root, "pool_audit", report)
        return report

    summaries["pool_audit"] = attempt("pool_audit", do_pool)

    # ---------------------------------------------------------------- fixtures
    def do_fixtures() -> dict[str, Any]:
        from synlab.diagnostics.fixtures import run_fixtures

        report = run_fixtures()
        write_report(store_root, "metric_fixture", report.get("metrics", {"ok": False}))
        write_report(store_root, "stat_fixture", report.get("stats", {"ok": False}))
        write_report(store_root, "diagnostics_fixtures", report)
        return report

    summaries["diagnostics_fixtures"] = attempt("diagnostics_fixtures", do_fixtures)

    # ---------------------------------------------------------------- training / diagnostics / episodes
    def do_train() -> dict[str, Any]:
        from synlab.config import load_train_spec
        from synlab.training.api import train

        train_spec = load_train_spec(ROOT / "configs/a12/train_sandbox.yaml")
        if args.train_steps:
            train_spec.optimization.max_steps = args.train_steps
        report = train(train_spec, store)
        write_report(store_root, "train_report", report)
        resume = report.get("resume_check")
        if resume:
            write_report(store_root, "train_resume", resume)
        return report

    summaries["train"] = attempt("train", do_train)

    def do_diagnose() -> dict[str, Any]:
        from synlab.config import load_diagnose_spec
        from synlab.diagnostics.api import run_diagnosis

        diagnose_spec = load_diagnose_spec(ROOT / "configs/a12/diagnose_sandbox.yaml")
        report = run_diagnosis(diagnose_spec, store)
        write_report(store_root, "diagnostic_report", report)
        return report

    summaries["diagnose"] = attempt("diagnose", do_diagnose)

    def do_episode() -> dict[str, Any]:
        from synlab.episodes.api import run_episode_config

        report = run_episode_config(store, str(ROOT / "configs/a12/pool_dev.yaml"))
        write_report(store_root, "episode_trace", report)
        return report

    summaries["episode"] = attempt("episode", do_episode)

    # ---------------------------------------------------------------- mvs subset
    def do_mvs() -> dict[str, Any]:
        from synlab.observe.mvs_subset import run_mvs_subset

        report = run_mvs_subset(store, limit_mothers=1)
        write_report(store_root, "mvs_subset", report)
        return report

    summaries["mvs_subset"] = attempt("mvs_subset", do_mvs)

    # ---------------------------------------------------------------- leakage negative control
    def do_leakage() -> dict[str, Any]:
        from synlab.qc.leakage import run_negative_control

        report = run_negative_control(store, run_id)
        write_report(store_root, "leakage_negative_control", report)
        return report

    summaries["leakage_negative_control"] = attempt("leakage_negative_control", do_leakage)

    # ---------------------------------------------------------------- health + release
    def do_health() -> dict[str, Any]:
        report = health_check(str(store_root))
        write_report(store_root, "store_health", report)
        return report

    summaries["store_health"] = attempt("store_health", do_health)

    # ---------------------------------------------------------------- scale accounting
    def do_scale() -> dict[str, Any]:
        fragments = store.list_assets(role="fragment_mesh", limit=1000000)
        mothers = store.list_assets(role="mother_mesh", limit=1000000)
        lineages = {a.lineage_id for a in mothers if a.lineage_id}
        splits: dict[str, int] = {}
        for asset in fragments:
            splits[asset.split or "unknown"] = splits.get(asset.split or "unknown", 0) + 1
        report = {
            "ok": bool(fragments),
            "accepted_fragments": len(fragments),
            "accepted_max": len(fragments),
            "independent_mothers": len(lineages),
            "per_split_fragments": splits,
            "note": ("accepted counts are read from committed fragment assets; L2/L3 targets are "
                     "480 mothers / 1e5 fragments and stay PENDING until those runs exist"),
        }
        write_report(store_root, "scale_report", report)
        return report

    summaries["scale_report"] = attempt("scale_report", do_scale)

    # ---------------------------------------------------------------- API/UI evidence
    def do_api_ui() -> dict[str, Any]:
        from synlab.api import create_app
        from fastapi.testclient import TestClient

        app = create_app(store_root, role="researcher")
        client = TestClient(app)
        try:
            capabilities = client.get("/api/synlab/capabilities")
            vessels = client.get("/api/synlab/registry/vessel")
            assets = client.get("/api/synlab/assets", params={"limit": 5})
        finally:
            client.close()
        frontend_dist = ROOT / "frontend" / "dist"
        frontend_doc = ROOT / "docs" / "a12" / "api_ui.md"
        api_ok = all(r.status_code < 500 for r in (capabilities, vessels, assets))
        report = {
            "ok": api_ok and frontend_dist.exists(),
            "metrics": {
                "capabilities_status": capabilities.status_code,
                "registry_status": vessels.status_code,
                "assets_status": assets.status_code,
                "asset_page_size": len(assets.json().get("items", [])) if assets.status_code == 200 else None,
                "frontend_build_present": frontend_dist.exists(),
                "frontend_doc_present": frontend_doc.exists(),
                "frontend_doc": str(frontend_doc) if frontend_doc.exists() else None,
            },
            "note": ("API responses are real; the frontend build artefact is required for a PASS. "
                     "When the frontend is absent the item stays PENDING instead of being mocked"),
        }
        write_report(store_root, "api_ui_evidence", report)
        return report

    summaries["api_ui_evidence"] = attempt("api_ui_evidence", do_api_ui)

    write_report(store_root, "evidence_summary", {
        "ok": True, "run_id": run_id,
        "steps": {k: {"ok": v.get("ok"), "status": v.get("status"), "error": v.get("error"),
                      "seconds": v.get("seconds")} for k, v in summaries.items()},
    })

    acceptance = run_acceptance(store_root=store_root, profile=args.profile,
                                report_path=ROOT / "docs/a12/acceptance_report.md")
    print("acceptance counts:", acceptance["counts"])

    proc = __import__("subprocess").run(
        [__import__("sys").executable, str(ROOT / "tools" / "gen_status_matrix.py"),
         "--data-root", str(store_root)],
        capture_output=True, text=True, check=False)
    print(proc.stdout[-2000:] or proc.stderr[-2000:])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
