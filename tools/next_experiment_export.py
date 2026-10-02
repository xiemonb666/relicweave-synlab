"""Freeze the next-experiment release and run the documented export + loader steps.

Why this is a separate tool
---------------------------
``tools/closed_loop.py`` owns the export and loader steps and is reused verbatim below.  Its
``release_freeze`` step is **not** reused, because that step hard-codes the *sandbox* corner of
the closed loop as literal manifest text:

* ``"relation_status": {"r2_edges": 0, ...}`` and a ``scope_declaration`` that says the release
  "contains NO relation with an R2 label";
* ``"r2_relations_in_scope": 0`` in the release coverage;
* ``scope_declaration`` describing "3 mothers / 3 materials / 3 patterns / 6 fragments".

This batch has 100+ accepted lineages and real R2 positives, so running that step would write a
frozen manifest whose own text contradicts its contents -- exactly the kind of fabricated
evidence this repository forbids.  The freeze is therefore performed here with the *measured*
coverage, the real gate verdicts from ``qc.gates`` (no overrides, no downgrades, no relaxation),
and the closure of every QA_PASS asset of the batch's runs.

Steps and the exact commands they correspond to::

    python tools/next_experiment_export.py --step freeze
    python tools/closed_loop.py --step export_training_package --store data/a12
    python tools/closed_loop.py --step loader_probe

The second and third commands are run by this tool in-process through the same functions the CLI
uses (``storage.export.export_training_package`` / ``qc.loader_probe.probe_training_package``),
seeded from the release this tool froze, because ``closed_loop.py`` resolves its release from its
own ledger's ``release_freeze`` entry.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synlab.errors import SynLabError  # noqa: E402
from synlab.qc import gates as gates_mod  # noqa: E402
from synlab.roles import (  # noqa: E402
    ROLE_CLEAN_TRUTH,
    ROLE_FEATURE_BUNDLE,
    ROLE_FRAGMENT_MESH,
    ROLE_LABEL_BUNDLE,
    ROLE_MOTHER_MESH,
    ROLE_OBS_RESULT,
    ROLE_PHYSICAL_COMPONENT,
    ROLE_PHYSICAL_TRUTH,
    ROLE_PATTERN_RECIPE,
    ROLE_VISIBLE_LABELS,
)
from synlab.storage.release import PROFILE_GATES, ReleaseManager  # noqa: E402
from synlab.storage.store import QA_PASS, AssetStore  # noqa: E402

DEFAULT_STORE = "data/a12"
DEFAULT_OUT = "data/a12_exports/next_experiment"
DEFAULT_LEDGER = "data/a12/reports/next_experiment_batches.json"
PROFILE = "PILOT"
EXPORT_FORMATS = ("parquet", "npz", "zarr", "tar")


def _batch_run_ids(ledger_path: Path) -> list[str]:
    if not ledger_path.exists():
        return []
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    run_ids: list[str] = []
    for entry in ledger.get("batches", []):
        run_id = entry.get("run_id")
        if run_id and run_id not in run_ids:
            run_ids.append(run_id)
    return run_ids


def _qa_count(assets: Sequence[Any]) -> int:
    return len([a for a in assets if a.qa_status == QA_PASS])


def step_freeze(store: AssetStore, *, ledger_path: Path, out_dir: Path,
                evidence_root: str | None) -> dict[str, Any]:
    run_ids = _batch_run_ids(ledger_path)
    all_assets = store.list_assets(limit=500000)
    # The batch's assets are exactly those whose meta.run_id is one of this batch's run ids.
    run_set = set(run_ids)
    batch_assets = [a for a in all_assets if (a.meta or {}).get("run_id") in run_set]
    keep = [a for a in batch_assets if a.qa_status == QA_PASS]
    excluded = [{"asset_id": a.asset_id, "role": a.role, "qa_status": a.qa_status,
                 "lineage_id": a.lineage_id}
                for a in batch_assets if a.qa_status != QA_PASS]
    if not keep:
        return {"status": "FAILED", "error": {"code": "STOP_QA",
                                              "message": "the batch has no QA_PASS asset"}}
    # A lineage whose label_bundle is not QA_PASS never entered the accepted set; its other
    # assets are real but the release must not present them as a complete lineage.
    accepted_lineages = sorted({a.lineage_id for a in keep
                                if a.role == ROLE_LABEL_BUNDLE and a.lineage_id})
    release_assets = [a for a in keep if a.lineage_id in set(accepted_lineages)]
    evidence_dirs = [evidence_root] if evidence_root and Path(evidence_root).exists() else []
    gates, _gate_assets, profile = gates_mod.evaluate_gates(
        store, run_ids[0], evidence_dirs=evidence_dirs)
    evidence = gates_mod.gate_evidence(store, run_ids[0], evidence_dirs=evidence_dirs)

    fragments = [a for a in release_assets if a.role == ROLE_FRAGMENT_MESH]
    lineages = sorted({a.lineage_id for a in release_assets if a.lineage_id})
    r2_total = 0
    relation_total = 0
    for asset in release_assets:
        if asset.role != ROLE_LABEL_BUNDLE:
            continue
        r2_total += int((asset.meta or {}).get("r2_count") or 0)
        relation_total += int((asset.meta or {}).get("relation_count") or 0)
    roles: dict[str, int] = {}
    for asset in release_assets:
        roles[asset.role] = roles.get(asset.role, 0) + 1
    vessels = sorted({str((a.meta or {}).get("vessel_id")) for a in release_assets
                      if (a.meta or {}).get("vessel_id")})
    materials = sorted({str((a.meta or {}).get("material_id")) for a in release_assets
                        if (a.meta or {}).get("material_id")})
    splits: dict[str, int] = {}
    for asset in release_assets:
        splits[str(asset.split)] = splits.get(str(asset.split), 0) + 1

    manager = ReleaseManager(store)
    closure = manager.verify_closure([a.asset_id for a in release_assets])
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "gates_evaluated.json").write_text(
        json.dumps({"profile": profile, "gates": gates, "evidence": evidence},
                   ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    if not closure["ok"]:
        return {"status": "FAILED", "frozen": False, "closure": closure,
                "gates": gates, "profile": profile,
                "error": {"code": "ASSET_HASH_MISMATCH",
                          "message": "reference closure does not verify",
                          "measurements": {"problems": closure["problems"][:8]}}}

    release_id = f"rel_nexp_{int(time.time())}"
    coverage = {
        "run_ids": run_ids,
        "roles": roles,
        "lineages": len(lineages),
        "splits": splits,
        "vessels": vessels,
        "materials": materials,
        "fragment_assets_in_scope": len(fragments),
        "r2_relations_in_scope": r2_total,
        "relations_in_scope": relation_total,
        "ledger": str(ledger_path),
    }
    extra = {
        "batch": "next_experiment",
        "config": "configs/a12/next_experiment.yaml",
        "spec_hash": None,
        "batch_runs": run_ids,
        "store_derived_gates": gates,
        "evidence_reports": evidence,
        "excluded_assets": excluded[:200],
        "excluded_asset_count": len(excluded),
        "scope_declaration": (
            "PILOT-profile release of the A12 next-experiment batch. The frozen scope is every "
            "QA_PASS asset of the batch's generation runs whose lineage reached an accepted "
            "(QA_PASS label_bundle) state; reference closure is verified by "
            "ReleaseManager.verify_closure. Counts, splits, coverage and the R2 relation count "
            "in this manifest are recomputed from the store, not declared."),
        "relation_status": {"r2_edges": r2_total, "relation_edges": relation_total,
                            "source": "sum of label_bundle.meta r2_count / relation_count "
                                      "over the frozen scope"},
    }
    try:
        record = manager.freeze(release_id=release_id, profile=PROFILE, scope="SYNTHETIC",
                               asset_ids=[a.asset_id for a in release_assets], gates=gates,
                               coverage=coverage, extra=extra)
    except SynLabError as exc:
        code = getattr(getattr(exc, "code", None), "value", str(getattr(exc, "code", "")))
        blocked = {
            "schema": "synlab.release_freeze_blocked.v1", "frozen": False,
            "release_id_attempted": release_id, "profile": PROFILE,
            "required_gates": PROFILE_GATES[PROFILE],
            "gates": gates, "coverage": coverage,
            "error": {"code": code, "stage": exc.stage, "message": exc.message,
                      "measurements": getattr(exc, "measurements", None)},
            "note": "no gate was relaxed, overridden or downgraded to obtain this release",
        }
        (out_dir / "release_freeze_blocked.json").write_text(
            json.dumps(blocked, ensure_ascii=False, indent=2, sort_keys=True, default=str),
            encoding="utf-8")
        return {"status": "FAILED", "frozen": False, "release_id_attempted": release_id,
                "profile": PROFILE, "gates": gates, "coverage": coverage,
                "error": blocked["error"],
                "artifacts": [str(out_dir / "release_freeze_blocked.json")]}
    manifest = manager.load(release_id)
    return {
        "status": "OK", "frozen": True, "release_id": record.release_id,
        "release_profile": record.profile, "manifest_hash": record.manifest_hash,
        "manifest_path": record.manifest_path, "assets": len(record.asset_ids),
        "assets_by_role": roles, "coverage": coverage, "gates": gates,
        "scope_completed": record.scope_completed, "scope_pending": record.scope_pending,
        "closure": manifest.get("closure"), "evidence_reports": evidence,
        "excluded_asset_count": len(excluded),
        "artifacts": [record.manifest_path, str(out_dir / "gates_evaluated.json")],
    }


def step_export(store: AssetStore, *, release_id: str, out_dir: Path) -> dict[str, Any]:
    """The body of ``tools/closed_loop.py --step export_training_package``."""
    from synlab.storage.export import export_release, export_training_package

    legacy_dir = out_dir / "release_index"
    legacy = export_release(store, release_id, fmt="parquet", out_dir=str(legacy_dir))
    package_dir = out_dir / "training_package"
    package = export_training_package(store, release_id, package_dir, formats=EXPORT_FORMATS)
    counts = package.get("counts") or {}
    return {
        "status": "OK", "release_id": release_id, "package_dir": str(package_dir),
        "package_manifest": str(package_dir / "export_manifest.json"),
        "manifest_hash": package.get("manifest_hash"), "counts": counts,
        "relations": counts.get("relations"), "relation_kinds": counts.get("relation_kinds"),
        "bytes_total": package.get("bytes_total"), "files_total": package.get("counts_total"),
        "views": package.get("views"), "separation": package.get("separation"),
        "reference_closure": package.get("reference_closure"),
        "token_cache": package.get("token_cache"), "labels": package.get("labels"),
        "legacy_export": {"dir": str(legacy_dir), "hash": legacy.get("export_hash"),
                          "assets": legacy.get("assets")},
        "artifacts": [str(package_dir / "export_manifest.json"),
                      str(legacy_dir / "export_manifest.json")],
    }


def step_loader_probe(*, package_dir: Path, report_path: Path) -> dict[str, Any]:
    """The body of ``tools/closed_loop.py --step loader_probe``."""
    from synlab.qc.loader_probe import probe_training_package

    report = probe_training_package(package_dir, out_path=report_path)
    return {
        "status": "OK" if report.get("ok") else "FAILED", "ok": bool(report.get("ok")),
        "report_ref": str(report_path), "files_ok": report.get("files_ok"),
        "counts": report.get("counts"), "relation_pool": report.get("relation_pool"),
        "feature_shapes": report.get("feature_shapes"),
        "real_denominator": report.get("real_denominator"), "batch": report.get("batch"),
        "negative_audit": report.get("negative_audit"), "degenerate": report.get("degenerate"),
        "blocking_attempt": report.get("blocking_attempt"), "attempts": report.get("attempts"),
        "error": report.get("error"), "artifacts": [str(report_path)],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="next_experiment_export")
    parser.add_argument("--step", default="all",
                        help="freeze | export_training_package | loader_probe | all")
    parser.add_argument("--store", default=DEFAULT_STORE)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--ledger", default=DEFAULT_LEDGER)
    parser.add_argument("--evidence", default="data/a12")
    parser.add_argument("--release", default=None,
                        help="release id for the export step (default: the last frozen one)")
    args = parser.parse_args(argv)

    store = AssetStore(Path(args.store))
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    state_path = out_dir / "next_experiment_export_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    steps = (["freeze", "export_training_package", "loader_probe"]
             if args.step == "all" else [args.step])
    failed = False
    for name in steps:
        print(f"[{name}] running ...", flush=True)
        started = time.time()
        if name == "freeze":
            result = step_freeze(store, ledger_path=Path(args.ledger), out_dir=out_dir,
                                 evidence_root=args.evidence)
        elif name == "export_training_package":
            release_id = args.release or state.get("release_id")
            if not release_id:
                result = {"status": "FAILED",
                          "error": {"code": "INPUT_UNAVAILABLE",
                                    "message": "no frozen release: run the freeze step first"}}
            else:
                result = step_export(store, release_id=release_id, out_dir=out_dir)
        elif name == "loader_probe":
            result = step_loader_probe(package_dir=out_dir / "training_package",
                                       report_path=Path("data/a12/reports/loader_probe.json"))
        else:
            parser.error(f"unknown step {name!r}")
        result["seconds"] = round(time.time() - started, 3)
        state[name] = result
        if result.get("release_id"):
            state["release_id"] = result["release_id"]
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2, default=str),
                              encoding="utf-8")
        print(f"[{name}] {result['status']} in {result['seconds']}s", flush=True)
        if result["status"] != "OK":
            failed = True
            break
    print(json.dumps({k: {kk: vv for kk, vv in v.items()
                          if kk not in ("counts", "views", "batch", "gates", "coverage")}
                      for k, v in state.items() if isinstance(v, dict)},
                     ensure_ascii=False, indent=2, default=str))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
