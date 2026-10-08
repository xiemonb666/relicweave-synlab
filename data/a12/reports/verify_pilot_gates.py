"""Report every gate of a release profile with its *measured* reason (no verdict is invented).

Usage::

    python data/a12/reports/verify_pilot_gates.py --store <store_root> --run <run_id> \
        [--profile PILOT] [--evidence data/a12] [--out <report.json>]

It prints one line per required gate of the profile (verdict + the evidence it was read from) and
writes the same content as JSON.  ``qc.gates.evaluate_gates`` decides the verdicts; this script
only explains them from the store and the report files the gates themselves read, so a PENDING /
FAIL gate always carries a real number or a missing file name instead of prose.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synlab.qc import gates as gates_mod  # noqa: E402
from synlab.roles import (  # noqa: E402
    ROLE_CLEAN_TRUTH,
    ROLE_FEATURE_BUNDLE,
    ROLE_LABEL_BUNDLE,
    ROLE_OBS_RESULT,
    ROLE_POOL,
    ROLE_ROSTER,
)
from synlab.storage.release import PROFILE_GATES  # noqa: E402
from synlab.storage.store import QA_PASS, AssetStore  # noqa: E402


def _report(dirs: list[Path], name: str) -> tuple[dict[str, Any] | None, str | None]:
    return gates_mod.load_report_from(dirs, name)


def explain(store: AssetStore, run_id: str, profile: str, evidence_dirs: list[str]) -> dict[str, Any]:
    gates, asset_ids, run_profile = gates_mod.evaluate_gates(
        store, run_id, evidence_dirs=evidence_dirs)
    dirs = gates_mod.reports_dirs(store, evidence_dirs)
    measurements = gates_mod.gate_measurements(store, run_id, evidence_dirs)
    assets = [a for a in store.list_assets(limit=500000) if (a.meta or {}).get("run_id") == run_id]

    def role_qa(role: str) -> dict[str, int]:
        out: dict[str, int] = {}
        for asset in assets:
            if asset.role == role:
                out[asset.qa_status] = out.get(asset.qa_status, 0) + 1
        return out

    audit, audit_path = _report(dirs, f"audit_{run_id}")
    audit = audit or {}
    operator_audit, operator_path = _report(dirs, "operator_audit")
    acceptance, acceptance_path = _report(dirs, "acceptance_summary")
    recovery, recovery_path = _report(dirs, "recovery_probe")
    coverage_aggregate, aggregate_path = _report(dirs, gates_mod.COVERAGE_AGGREGATE_NAME)
    coverage_ledger, ledger_path = _report(dirs, "coverage")

    reasons: dict[str, Any] = {}

    def put(gate: str, reason: str, numbers: dict[str, Any] | None = None) -> None:
        reasons[gate] = {"reason": reason, "measured": numbers or {}}

    put("fixture_contract", "reuse manifest present in the repository or staged into the reports dir",
        {"staged_or_repo": bool(gates_mod.load_report_from(dirs, "reuse_manifest")[1]
                                or (REPO_ROOT / "docs/a12/reuse_manifest.json").exists())})
    put("coordinate_contract", "acceptance_summary.json item A02",
        {"report": acceptance_path, "A02": gates_mod.acceptance_item(acceptance, "A02").get("status")})
    put("source_map", "QA_PASS fragment_mesh assets of this run", {"fragment_mesh": role_qa("fragment_mesh")})
    put("readonly_commit", "audit_<run>.json store_health.ok",
        {"report": audit_path, "store_health_ok": (audit.get("store_health") or {}).get("ok")})
    put("fracture_operator_runs", "QA_PASS clean_truth assets of this run",
        {"clean_truth": role_qa(ROLE_CLEAN_TRUTH)})
    put("observation_operator_runs", "QA_PASS obs_result assets of this run",
        {"obs_result": role_qa(ROLE_OBS_RESULT)})
    put("train_dev_lineage", "audit_<run>.json lineage_splits must carry train and dev",
        {"lineage_splits": audit.get("lineage_splits")})
    put("operators_used_pass", "operator_audit.json ok", {"report": operator_path,
                                                         "ok": (operator_audit or {}).get("ok")})
    put("legal_inputs", "QA_PASS feature_bundle + label_bundle and audit_run ok",
        {"feature_bundle": role_qa(ROLE_FEATURE_BUNDLE), "label_bundle": role_qa(ROLE_LABEL_BUNDLE),
         "audit_ok": audit.get("ok"), "audit_problems": (audit.get("problems") or [])[:5]})
    put("relations_complete", "QA_PASS relation_pool assets carrying meta.run_id == this run",
        {"relation_pool": role_qa(ROLE_POOL), "query_roster": role_qa(ROLE_ROSTER),
         "run_scoped_pool_assets": [a.asset_id for a in assets if a.role == ROLE_POOL
                                    and a.qa_status == QA_PASS]})
    put("read_recovery", "audit_<run>.store_health.ok and recovery_probe.json ok",
        {"store_health_ok": (audit.get("store_health") or {}).get("ok"),
         "recovery_report": recovery_path, "recovery_ok": (recovery or {}).get("ok")})
    put("leakage_audit", "acceptance_summary.json item A32",
        {"A32": gates_mod.acceptance_item(acceptance, "A32").get("status")})
    for gate, entry in measurements["gates"].items():
        put(gate, f"coverage {entry['key']} read from "
                  f"{'the aggregate' if aggregate_path and gates_mod.COVERAGE_AGGREGATE_NAME in str(aggregate_path) else 'the single-run ledger'}",
            entry)
    for name in ("mvs_subset_real_run", "core_ui_api", "l2_qualification", "loader_index_runnable",
                 "resource_profile", "accepted_nested_10k", "accepted_nested_50k",
                 "accepted_nested_100k", "references_loadable"):
        payload, path = _report(dirs, {"mvs_subset_real_run": "mvs_subset",
                                       "core_ui_api": "api_ui_evidence",
                                       "l2_qualification": "l2_scale",
                                       "loader_index_runnable": "loader_probe",
                                       "resource_profile": "resource_profile",
                                       "references_loadable": f"audit_{run_id}"}.get(
                                           name, "scale_report"))
        put(name, "report file read by the gate", {"report": path,
                                                   "ok": (payload or {}).get("ok")
                                                   if name != "references_loadable"
                                                   else (audit.get("closure") or {}).get("ok")})
    for name in ("real_capture_dataset", "phone_rgb_mvs", "scale_source", "mask_source",
                 "capture_profile", "proxy_calibration"):
        put(name, "no real capture data on this host", {})
    research, research_path = _report(dirs, "research_evidence")
    for name in ("frozen_protocol", "training_runs", "risk_calibration", "confirmation_complete"):
        put(name, "research_evidence.json", {"report": research_path,
                                             "value": (research or {}).get(name)})

    required = PROFILE_GATES[profile]
    return {
        "store_root": str(store.root),
        "run_id": run_id,
        "run_profile": run_profile,
        "profile": profile,
        "gates": gates,
        "required_gates": required,
        "required_status": {gate: gates.get(gate) for gate in required},
        "pending": [gate for gate in required if gates.get(gate) != "PASS"],
        "reasons": {gate: reasons.get(gate) for gate in required},
        "coverage_measurements": measurements,
        "assets_of_run": len(assets),
        "assets_qa_pass_of_run": len(asset_ids),
        "evidence_paths": {"coverage_aggregate": aggregate_path, "coverage_ledger": ledger_path,
                           "audit": audit_path, "operator_audit": operator_path,
                           "acceptance_summary": acceptance_path, "recovery_probe": recovery_path},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="verify_pilot_gates")
    parser.add_argument("--store", required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--profile", default="PILOT")
    parser.add_argument("--evidence", action="append", default=[])
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    payload = explain(AssetStore(args.store), args.run, args.profile.upper(), list(args.evidence))
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True,
                                             default=str), encoding="utf-8")
    print(f"store={payload['store_root']} run={payload['run_id']} "
          f"profile={payload['profile']} (generation profile {payload['run_profile']})")
    for gate in payload["required_gates"]:
        verdict = payload["gates"].get(gate)
        entry = payload["reasons"].get(gate) or {}
        numbers = entry.get("measured") or {}
        shown = {k: v for k, v in numbers.items() if k != "report"}
        print(f"  {gate:<28} {verdict:<8} {entry.get('reason', '')} {shown}")
    print(f"  -> {len(payload['required_gates']) - len(payload['pending'])}/"
          f"{len(payload['required_gates'])} required gates PASS; pending={payload['pending']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
