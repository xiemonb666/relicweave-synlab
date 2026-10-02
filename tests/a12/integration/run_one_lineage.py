"""Run exactly one lineage and report the *complete* outcome, traceback included.

Why this file exists
--------------------
``tools/batch_generate.py`` records only ``error.code``/``error.message`` in its ledger, and a
heavy Python process on this host is occasionally killed without a traceback at all.  Both make
"which stage raised, and why" a guessing game.  This driver:

* runs **one** lineage per invocation (the host kills long heavy processes),
* prints the full ``traceback`` string that :func:`synlab.pipeline.build_one_mother` captures for
  an unhandled exception, plus the per-stage wall times,
* never edits ``synlab/**`` just to print, and never swallows an exception: the pipeline already
  converts a raised exception into a real outcome, and this driver surfaces that outcome verbatim.

Usage::

    python tests/a12/integration/run_one_lineage.py --config configs/a12/next_experiment.yaml \
        --root data/a12_final/store --mother-index 0 --out data/a12_reports/run_one.json
    python tests/a12/integration/run_one_lineage.py --config configs/a12/realistic.yaml \
        --root data/a12_final/store --lineage LIN0000_V10_M11_PAT15
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synlab.canonical import hash_file  # noqa: E402
from synlab.config import load_generation_spec  # noqa: E402
from synlab.pipeline import build_one_mother, plan_generation  # noqa: E402
from synlab.registry import load_all  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402


def _strip(value: Any) -> Any:
    """JSON-safe view that keeps long strings (tracebacks) intact."""
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _import_closure() -> dict[str, Any]:
    """Hash every ``synlab`` module file this process really imported.

    The tree-wide fingerprint of ``frozen_revision.py`` answers "did any tracking-relevant file
    change", which other agents editing unrelated modules makes noisy.  This closure answers the
    sharper question a single-lineage result needs: **was the code that actually executed the
    same?**  Both are reported; neither replaces the other.
    """
    import hashlib

    files: dict[str, dict[str, Any]] = {}
    for name, module in sorted(sys.modules.items()):
        if not name.startswith("synlab"):
            continue
        raw = getattr(module, "__file__", None)
        if not raw:
            continue
        path = Path(raw)
        if not path.is_file():
            continue
        try:
            rel = path.resolve().relative_to(REPO_ROOT).as_posix()
        except ValueError:
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        files[rel] = {"module": name, "sha256": "sha256:" + digest, "size": path.stat().st_size}
    aggregate = hashlib.sha256()
    for rel in sorted(files):
        aggregate.update(rel.encode("utf-8"))
        aggregate.update(files[rel]["sha256"].encode("ascii"))
        aggregate.update(b"\n")
    return {
        "schema": "synlab.a12.import_closure.v1",
        "module_count": len(files),
        "content_digest": "sha256:" + aggregate.hexdigest(),
        "files": files,
    }


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="run_one_lineage")
    ap.add_argument("--config", required=True)
    ap.add_argument("--root", required=True, help="store root, e.g. data/a12_final/store")
    ap.add_argument("--mother-index", type=int, default=None)
    ap.add_argument("--lineage", default=None, help="lineage_id to run (overrides --mother-index)")
    ap.add_argument("--out", default=None, help="write the outcome JSON here")
    ap.add_argument("--closure-out", default=None,
                    help="write the executed-import-closure fingerprint here")
    ap.add_argument("--run-id", default=None)
    args = ap.parse_args(argv)

    store = AssetStore(args.root)
    load_all()
    spec = load_generation_spec(args.config)
    plan = plan_generation(spec)
    config_hash = hash_file(args.config)

    lineage = None
    if args.lineage:
        lineage = next((l for l in plan.lineages if l.lineage_id == args.lineage), None)
    elif args.mother_index is not None:
        lineage = next((l for l in plan.lineages if l.mother_index == args.mother_index), None)
    if lineage is None:
        raise SystemExit(f"no planned lineage matches {args.lineage or args.mother_index}; "
                         f"planned ids: {[l.lineage_id for l in plan.lineages][:8]} ...")

    run_id = args.run_id or f"one_{plan.job_id.split('_', 1)[-1][:16]}"
    store.create_run(run_id, plan.spec_hash, scope=spec.data_scope.value,
                     profile=spec.release_profile.value,
                     meta={"plan": plan.as_dict(), "spec": plan.compiled.expanded,
                           "driver": "tests/a12/integration/run_one_lineage.py"})

    started = time.time()
    try:
        outcome = build_one_mother(plan, lineage, store, run_id=run_id)
    except BaseException as exc:  # noqa: BLE001 - the driver must never hide a crash
        report = {
            "schema": "synlab.a12.run_one_lineage.v1",
            "ok": False,
            "escaped_exception": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
            "config": args.config, "config_hash": config_hash,
            "lineage_id": lineage.lineage_id, "run_id": run_id,
            "seconds": round(time.time() - started, 3),
        }
        closure = _import_closure()
        report["imported_synlab_modules"] = closure["module_count"]
        report["import_closure_digest"] = closure["content_digest"]
        if args.closure_out:
            Path(args.closure_out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.closure_out).write_text(
                json.dumps(closure, ensure_ascii=False, indent=2), encoding="utf-8")
        text = json.dumps(report, ensure_ascii=False, indent=2)
        if args.out:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(text, encoding="utf-8")
        print(text)
        return 1

    row = outcome["coverage_row"]
    report = {
        "schema": "synlab.a12.run_one_lineage.v1",
        "ok": bool(outcome["ok"]),
        "config": args.config,
        "config_hash": config_hash,
        "spec_hash": plan.spec_hash,
        "run_id": run_id,
        "store_root": args.root,
        "lineage_id": lineage.lineage_id,
        "mother_index": lineage.mother_index,
        "split": lineage.split,
        "vessel_id": lineage.vessel_id,
        "material_id": lineage.material_id,
        "pattern_id": lineage.pattern_id,
        "layer_combo_id": lineage.layer_combo_id,
        "seconds": round(time.time() - started, 3),
        "error": outcome.get("error"),
        "stages": row.get("stages"),
        "fragments": row.get("fragments"),
        "observations": row.get("observations"),
        "r2_pairs": row.get("r2_pairs"),
        "obs_endpoint_failures": row.get("obs_endpoint_failures"),
        "context_assets": row.get("context_assets"),
        "feature_asset": row.get("feature_asset"),
        "label_asset": row.get("label_asset"),
        "provenance_asset": row.get("provenance_asset"),
        "physical_result_qa": row.get("physical_result_qa"),
        "coverage_row": row,
    }
    report = _strip(report)
    closure = _import_closure()
    report["imported_synlab_modules"] = closure["module_count"]
    report["import_closure_digest"] = closure["content_digest"]
    if args.closure_out:
        Path(args.closure_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.closure_out).write_text(json.dumps(closure, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "coverage_row"},
                     ensure_ascii=False, indent=2))
    if not outcome["ok"]:
        print("--- traceback ---")
        print((outcome.get("error") or {}).get("traceback") or "(none recorded; SynLabError)")
        return 1
    print(f"OK: {lineage.lineage_id} fragments={row.get('fragments')} "
          f"observations={row.get('observations')} r2={row.get('r2_pairs')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
