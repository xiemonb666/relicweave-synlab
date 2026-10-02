"""Drive the multi-event relation-negative library end to end, one bounded step at a time.

Why a step-wise driver
----------------------
The host kills long, heavy Python processes, so the library is built in **separate
invocations**, and every step writes what it measured to disk before returning:

``plan``      freeze the event library plan (>= 3 mutually exclusive events per mother)
``run``       run the planned events of ONE mother (``--only-mother``), real fracture + truth
``assemble``  read every ``work/mother_*.json``, verify mutual exclusion, classify every pair
``observe``   observe the fragments of up to ``--max-events`` events through the pipeline route
``commit``    commit the library into ``--store``, build + freeze the relation pool/roster,
              then freeze a closure-verified release
``export``    export the training package of that release
``summary``   print the measured counts (histogram, eligibility, observations)

Nothing here invents a label: the relation verdict of every pair comes from
``synlab.relations.multi_event.classify_library``, which reads the measured truth of the events.
An ``UNKNOWN`` pair is never turned into a negative.

Usage::

    python tools/relation_negatives_run.py --step plan
    python tools/relation_negatives_run.py --step run --only-mother 0
    python tools/relation_negatives_run.py --step assemble
    python tools/relation_negatives_run.py --step observe --event LIN0000_V01_M01_PAT01_E01
    python tools/relation_negatives_run.py --step commit
    python tools/relation_negatives_run.py --step export
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synlab.canonical import hash_file, hash_json  # noqa: E402
from synlab.relations.multi_event import (  # noqa: E402
    MULTI_EVENT_VERSION,
    classify_library,
    plan_event_library,
    relation_histogram,
    run_event_library,
    verify_event_exclusion,
)
from synlab.storage.store import AssetStore  # noqa: E402

DEFAULT_OUT = "data/a12_neg"
DEFAULT_STORE = "data/a12_neg/store"
DEFAULT_SPEC = "data/a12/reports/run_spec_run_1df8391b47af6fb9.json"
DEFAULT_CONFIG = "configs/a12/next_experiment.yaml"
DEFAULT_POOL_CONFIG = "configs/a12/negative_pool.yaml"
RUN_ID = "neglib_events_v1"
RELEASE_ID = "rel_neglib_events_v1"
MASTER_SEED = 20261001


# ---------------------------------------------------------------------------------- plumbing
def _write_json(path: Path, payload: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str)
    path.write_text(text, encoding="utf-8")
    return hash_json(json.loads(text))


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def run_args(out: Path) -> dict[str, Any]:
    """The single source of truth for what plan each step rebuilds (deterministic)."""
    path = out / "run_args.json"
    if not path.exists():
        raise SystemExit(f"{path} is missing: run --step plan first")
    return _read_json(path)


def build_plan(args: argparse.Namespace) -> Any:
    """Rebuild the frozen ``LibraryPlan`` from the same arguments every step uses."""
    spec = _read_json(Path(args.spec))
    rows = spec["plan"] if isinstance(spec, dict) else spec
    wanted = {int(i) for i in args.mothers}
    mothers = [dict(row) for row in rows if int(row["mother_index"]) in wanted]
    if not mothers:
        raise SystemExit(f"no planned mother matches --mothers {sorted(wanted)}")
    return plan_event_library(
        mothers, n_events=int(args.events_per_mother), master_seed=int(args.master_seed),
        grey_zone_mothers=[int(i) for i in args.grey_zone],
        distractor_indices=[int(i) for i in args.distractor],
        unresolved_mothers=[int(i) for i in args.unresolved])


def _generation_spec(config: str) -> Any:
    from synlab.config import load_generation_spec
    return load_generation_spec(config)


# -------------------------------------------------------------------------------------- plan
def step_plan(args: argparse.Namespace, out: Path) -> dict[str, Any]:
    from synlab.registry import load_all

    load_all()
    plan = build_plan(args)
    plan_payload = plan.as_dict()
    plan_path = out / "library_plan.json"
    _write_json(plan_path, plan_payload)
    _write_json(out / "run_args.json", {
        "spec": str(args.spec), "spec_hash": _read_json(Path(args.spec)).get("spec_hash"),
        "config": str(args.config), "mothers": [int(i) for i in args.mothers],
        "events_per_mother": int(args.events_per_mother), "master_seed": int(args.master_seed),
        "grey_zone": [int(i) for i in args.grey_zone],
        "distractor": [int(i) for i in args.distractor],
        "unresolved": [int(i) for i in args.unresolved],
        "route": str(args.route), "views": int(args.views),
        "run_id": str(args.run_id), "release_id": str(args.release_id),
    })
    per_mother: dict[str, list[str]] = {}
    for event in plan.events:
        per_mother.setdefault(str(event.lineage_id), []).append(
            f"{event.event_id}({event.role})")
    return {"ok": True, "step": "plan", "plan": str(plan_path),
            "plan_hash": hash_json(plan_payload), "mothers": len(plan.mothers),
            "events_total": plan.events_total, "events_per_mother": plan.events_per_mother,
            "per_mother": per_mother,
            "spec_hash": _read_json(Path(args.spec)).get("spec_hash"),
            "config_hash": hash_file(args.config)}


# --------------------------------------------------------------------------------------- run
def step_run(args: argparse.Namespace, out: Path) -> dict[str, Any]:
    from synlab.registry import load_all

    load_all()
    plan = build_plan(args)
    spec = _generation_spec(args.config)
    started = time.time()
    only = [int(i) for i in args.only_mother]
    library = run_event_library(plan, fracture_config=spec.fracture,
                                work_dir=out / "work", mesh_dir=out / "meshes",
                                only_mothers=(only or None))
    summary = {"ok": bool(library.get("ok")), "step": "run", "only_mother": only,
               "seconds": round(time.time() - started, 3),
               "mothers_returned": len(library.get("mothers") or []),
               "mothers_ok": sum(1 for m in library.get("mothers") or [] if m.get("ok")),
               "events_ok": sum(1 for m in library.get("mothers") or []
                                for e in m.get("events") or [] if e.get("ok")),
               "per_mother": [
                   {"lineage_id": m["mother"]["lineage_id"], "ok": m.get("ok"),
                    "events_ok": m.get("events_ok"),
                    "r2_area_threshold_mm2": m["mother"].get("r2_area_threshold_mm2"),
                    "events": [{"event_id": e.get("event_id"), "ok": e.get("ok"),
                                "role": (e.get("plan") or {}).get("role"),
                                "truth_status": e.get("truth_status"),
                                "relation_histogram": e.get("relation_histogram"),
                                "fragment_ids": e.get("fragment_ids"),
                                "last_error": e.get("last_error"),
                                "seconds": e.get("seconds")}
                               for e in m.get("events") or []]}
                   for m in library.get("mothers") or []],
               "exclusion": library.get("exclusion")}
    _write_json(out / "run_summary.json", summary)
    _write_json(out / "library.json", library)
    return summary


# ---------------------------------------------------------------------------------- assemble
def assemble_library(plan_path: Path, work_dir: Path) -> dict[str, Any]:
    """Build the library mapping from every cached mother record (no fracture is re-run)."""
    plan_payload = _read_json(plan_path)
    mothers = []
    for path in sorted(work_dir.glob("mother_*.json")):
        mothers.append(_read_json(path))
    library: dict[str, Any] = {
        "schema": "synlab.relations.event_library.v1", "version": MULTI_EVENT_VERSION,
        "master_seed": int(plan_payload.get("master_seed", MASTER_SEED)),
        "plan": plan_payload, "mothers": mothers, "ok": False,
    }
    library["ok"] = bool(mothers) and all(m.get("ok") for m in mothers)
    library["exclusion"] = verify_event_exclusion(library)
    library["ok"] = bool(library["ok"] and library["exclusion"]["ok"])
    return library


def step_assemble(args: argparse.Namespace, out: Path) -> dict[str, Any]:
    plan = build_plan(args)
    library = assemble_library(out / "library_plan.json", out / "work")
    # the plan object rebuilt from args must agree with the frozen plan on disk
    if plan.as_dict() != library["plan"]:
        raise SystemExit("the rebuilt plan differs from library_plan.json: re-run --step plan")
    rows = classify_library(library)
    histogram = relation_histogram(rows)
    eligible = [r for r in rows if r["kind"] in ("R1", "R0") and r["valid"] and r["loss_mask"]]
    unknown = [r for r in rows if r["kind"] == "UNKNOWN"]
    by_kind_decidability: dict[str, int] = {}
    for row in rows:
        key = f'{row["kind"]}/{row["decidability"]}'
        by_kind_decidability[key] = by_kind_decidability.get(key, 0) + 1
    clusters: dict[str, list[str]] = {}
    for row in rows:
        clusters.setdefault(str(row.get("lineage_a", "")), [])
    summary = {
        "ok": bool(library["ok"]) and bool(eligible),
        "step": "assemble",
        "library_hash": hash_json({k: v for k, v in library.items() if k != "ok"}),
        "mothers": len(library["mothers"]),
        "mothers_ok": sum(1 for m in library["mothers"] if m.get("ok")),
        "events_ok": sum(1 for m in library["mothers"] for e in m.get("events") or []
                         if e.get("ok")),
        "fragments": len({f for m in library["mothers"] for e in m.get("events") or []
                          if e.get("ok") for f in e.get("fragment_ids") or []}),
        "unordered_pairs": len(rows),
        "counts_by_kind": histogram,
        "counts_by_kind_and_decidability": dict(sorted(by_kind_decidability.items())),
        "legal_negatives": len(eligible),
        "legal_negatives_by_kind": {
            kind: sum(1 for r in eligible if r["kind"] == kind) for kind in ("R1", "R0")},
        "positives_R2": sum(1 for r in rows if r["kind"] == "R2" and r["valid"]),
        "unknown_rows": len(unknown),
        "unknown_loss_mask_true": sum(1 for r in unknown if r["loss_mask"]),
        "unknown_valid_true": sum(1 for r in unknown if r["valid"]),
        "exclusion": library["exclusion"],
        "cross_event_R1": sum(1 for r in rows
                              if r["kind"] == "R1"
                              and r["decidability"] == "mutually_exclusive_event"),
        "within_event_R1": sum(1 for r in rows if r["decidability"] == "within_event"),
    }
    _write_json(out / "library.json", library)
    _write_json(out / "relations.json", {"schema": "synlab.relations.library_rows.v1",
                                         "library_hash": summary["library_hash"],
                                         "rows": rows})
    _write_json(out / "assemble_summary.json", summary)
    return summary


# ------------------------------------------------------------------------------------ observe
def step_observe(args: argparse.Namespace, out: Path) -> dict[str, Any]:
    from synlab.pipeline import _resolve_observe_spec
    from synlab.registry import load_all
    from synlab.relations.negatives import observe_library
    from synlab.storage.store import AssetStore as _Store

    load_all()
    plan = build_plan(args)
    library = _read_json(out / "library.json")
    store = _Store(Path(args.store))
    spec = _generation_spec(args.config)
    obs_spec = (None if args.observe_spec == "default"
                else _resolve_observe_spec(spec, store))
    done = _observed_events(out / "observe_report.json")
    wanted: list[str] = []
    for mother in library.get("mothers") or []:
        for event in mother.get("events") or []:
            if not event.get("ok"):
                continue
            event_id = str(event.get("event_id"))
            if args.event and event_id not in set(args.event):
                continue
            if event_id in done:
                continue
            wanted.append(event_id)
    if args.max_events:
        wanted = wanted[: int(args.max_events)]
    if not wanted:
        return {"ok": True, "step": "observe", "status": "NOTHING_TO_DO",
                "already_observed": sorted(done), "requested": list(args.event)}
    started = time.time()
    report = observe_library(plan, store, fracture_config=spec.fracture, events=wanted,
                             run_id=str(args.run_id), route=str(args.route),
                             view_count=int(args.views), renderer=str(args.renderer),
                             library=library, obs_spec=obs_spec)
    merged = _merge_observe_reports(out / "observe_report.json", report)
    _write_json(out / "observe_report.json", merged)
    return {"ok": bool(report.get("ok")), "step": "observe", "events": wanted,
            "seconds": round(time.time() - started, 3),
            "observed_fragments": sorted(report.get("features", {})),
            "failed_fragments": report.get("failed_fragments"),
            "obs_spec_source": report.get("obs_spec_source"),
            "merged_observed_total": len(merged.get("features", {})),
            "per_event": [{"event_id": e.get("event_id"), "ok": e.get("ok"),
                           "error": e.get("error"),
                           "fragments": [{"fragment_id": f.get("fragment_id"), "ok": f.get("ok"),
                                          "error": f.get("error"),
                                          "tokens_total": f.get("tokens_total"),
                                          "points": f.get("points")}
                                         for f in e.get("fragments") or []]}
                          for e in report.get("events", [])]}


def _observed_events(path: Path) -> set[str]:
    if not path.exists():
        return set()
    report = _read_json(path)
    return {str(e.get("event_id")) for e in report.get("events", []) if e.get("ok")}


def _merge_observe_reports(path: Path, report: dict[str, Any]) -> dict[str, Any]:
    merged = _read_json(path) if path.exists() else {
        "schema": report.get("schema"), "observations": {}, "features": {}, "events": []}
    merged["schema"] = report.get("schema", merged.get("schema"))
    merged["obs_spec_source"] = report.get("obs_spec_source")
    merged["data_semantics"] = report.get("data_semantics")
    merged.setdefault("observations", {}).update(report.get("observations", {}))
    merged.setdefault("features", {}).update(report.get("features", {}))
    known = {str(e.get("event_id")) for e in merged.get("events", [])}
    for entry in report.get("events", []):
        if str(entry.get("event_id")) in known:
            merged["events"] = [entry if str(e.get("event_id")) == str(entry.get("event_id"))
                                else e for e in merged["events"]]
        else:
            merged["events"].append(entry)
    merged["ok"] = bool(merged.get("features"))
    merged["observed_fragments"] = sorted(merged.get("features", {}))
    return merged


# ------------------------------------------------------------------------------------- commit
def step_commit(args: argparse.Namespace, out: Path) -> dict[str, Any]:
    from synlab.registry import load_all
    from synlab.relations.api import build_pool_from_config
    from synlab.relations.negatives import commit_library, freeze_library_release

    load_all()
    store = AssetStore(Path(args.store))
    library = _read_json(out / "library.json")
    if not library.get("mothers"):
        raise SystemExit("library.json has no mother: run --step run first")
    run_id = str(args.run_id)
    spec_hash = _read_json(Path(args.spec)).get("spec_hash")
    existing = {r["run_id"] for r in store.list_runs()} if hasattr(store, "list_runs") else set()
    if run_id not in existing:
        store.create_run(run_id, spec_hash, scope="SYNTHETIC", profile="PILOT",
                         meta={"library": "relations.multi_event",
                               "master_seed": int(args.master_seed),
                               "plan_path": str(out / "library_plan.json"),
                               "driver": "tools/relation_negatives_run.py"})
    started = time.time()
    commit = commit_library(store, library, run_id=run_id, mesh_dir=out / "meshes")
    pool_report = build_pool_from_config(store, None, args.pool_config, run_id=run_id)
    freeze = freeze_library_release(store, release_id=str(args.release_id), run_id=run_id,
                                    evidence_dirs=("data/a12",),
                                    extra={"library": "relations.multi_event",
                                           "library_path": str(out / "library.json"),
                                           "relations_path": str(out / "relations.json"),
                                           "run_args": run_args(out)})
    summary = {"ok": bool(freeze.get("frozen")), "step": "commit",
               "seconds": round(time.time() - started, 3), "run_id": run_id,
               "commit": {"label_bundles": len(commit["label_bundles"]),
                          "clean_truth": len(commit["clean_truth"]),
                          "fragment_mesh": len(commit["fragment_mesh"]),
                          "relations": commit["relations"],
                          "histogram": commit["histogram"],
                          "library_hash": commit["library_hash"]},
               "pool": {k: v for k, v in pool_report.items()
                        if k not in ("pool", "metrics")} | {"metrics": pool_report.get("metrics")},
               "freeze": {k: v for k, v in freeze.items() if k != "gates"}}
    _write_json(out / "commit_summary.json", summary)
    return summary


# ------------------------------------------------------------------------------------- export
def step_export(args: argparse.Namespace, out: Path) -> dict[str, Any]:
    from synlab.storage.export import export_training_package

    store = AssetStore(Path(args.store))
    package_dir = Path(args.package)
    started = time.time()
    package = export_training_package(store, str(args.release_id), package_dir,
                                      formats=("parquet", "npz", "zarr", "tar"))
    counts = package.get("counts") or {}
    summary = {"ok": True, "step": "export", "seconds": round(time.time() - started, 3),
               "package": str(package_dir), "manifest_hash": package.get("manifest_hash"),
               "counts": counts, "relations": counts.get("relations"),
               "relation_kinds": counts.get("relation_kinds"),
               "files_total": package.get("counts_total"),
               "bytes_total": package.get("bytes_total"),
               "views": package.get("views")}
    _write_json(out / "export_summary.json", summary)
    return summary


# ------------------------------------------------------------------------------------ summary
def step_summary(args: argparse.Namespace, out: Path) -> dict[str, Any]:
    plan = _read_json(out / "library_plan.json")
    library = _read_json(out / "library.json")
    rows = _read_json(out / "relations.json")["rows"]
    observed = set((_read_json(out / "observe_report.json").get("features") or {})
                   if (out / "observe_report.json").exists() else {})
    eligible = [r for r in rows if r["kind"] in ("R1", "R0") and r["valid"] and r["loss_mask"]]
    observed_eligible = [r for r in eligible if r["a"] in observed and r["b"] in observed]
    return {"step": "summary", "plan_events": plan.get("events_total"),
            "library_ok": library.get("ok"),
            "exclusion_ok": (library.get("exclusion") or {}).get("ok"),
            "histogram": relation_histogram(rows),
            "legal_negatives": len(eligible),
            "legal_negatives_with_both_ends_observed": len(observed_eligible),
            "observed_fragments": len(observed),
            "total_fragments": len({f for m in library.get("mothers", [])
                                    for e in m.get("events", []) if e.get("ok")
                                    for f in e.get("fragment_ids") or []})}


STEPS = {"plan": step_plan, "run": step_run, "assemble": step_assemble,
         "observe": step_observe, "commit": step_commit, "export": step_export,
         "summary": step_summary}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="relation_negatives_run")
    parser.add_argument("--step", required=True, choices=sorted(STEPS))
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--store", default=DEFAULT_STORE)
    parser.add_argument("--package", default="data/a12_exports/relation_negatives/training_package")
    parser.add_argument("--spec", default=DEFAULT_SPEC)
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--pool-config", default=DEFAULT_POOL_CONFIG)
    parser.add_argument("--mothers", default="0,1,2",
                        help="mother_index values of the run spec to enrol")
    parser.add_argument("--events-per-mother", type=int, default=3)
    parser.add_argument("--master-seed", type=int, default=MASTER_SEED)
    parser.add_argument("--grey-zone", default="")
    parser.add_argument("--distractor", default="")
    parser.add_argument("--unresolved", default="0")
    parser.add_argument("--only-mother", default="")
    parser.add_argument("--event", action="append", default=[],
                        help="observe only these event ids (repeatable)")
    parser.add_argument("--max-events", type=int, default=0)
    parser.add_argument("--route", default="proxy_scan")
    parser.add_argument("--views", type=int, default=12)
    parser.add_argument("--renderer", default="auto")
    parser.add_argument("--observe-spec", default="pipeline", choices=("pipeline", "default"))
    parser.add_argument("--run-id", default=RUN_ID)
    parser.add_argument("--release-id", default=RELEASE_ID)
    args = parser.parse_args(argv)
    for name in ("mothers", "grey_zone", "distractor", "unresolved", "only_mother"):
        raw = getattr(args, name)
        setattr(args, name, [int(x) for x in str(raw).split(",") if str(x).strip()])

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    started = time.time()
    try:
        result = STEPS[args.step](args, out)
    except BaseException as exc:  # noqa: BLE001 - a driver must never hide a crash
        result = {"ok": False, "step": args.step,
                  "escaped_exception": f"{type(exc).__name__}: {exc}",
                  "traceback": traceback.format_exc()[-4000:]}
        _write_json(out / f"error_{args.step}.json", result)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 1
    result["seconds"] = round(time.time() - started, 3)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
