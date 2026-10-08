"""Run the relation-negative track mother by mother, per-event process, with a real ledger.

Phases (each resumable, each writing to disk before the next starts):

1. ``events``  -- 3 real fracture events per mother, one process per event, cached under
   ``negatives/work/event_<m>_<e>.json``.  A host kill costs one event.
2. ``assemble`` -- merge the caches into ``negatives/library.json`` (the layout
   ``synlab.relations.negatives.commit_library`` consumes) and run the library's own
   ``verify_event_exclusion``.
3. ``observe``  -- for every mother whose library record is ok, render every fragment of every one
   of its events for real (``negatives.observe_library``) and commit ``obs_result`` +
   ``feature_bundle``.  One mother per process.  Without this step the *mate* of an R2 edge would
   be modelled but unobserved and could not be encoded.
4. ``commit``   -- ``negatives.commit_library`` once over the whole assembled library: one
   ``label_bundle`` per fragment carrying that fragment's own measured rows (including the legal
   ``R0``/``R1`` negatives), one ``clean_truth`` per event, the real ``fragment_mesh`` of every
   fragment.  Committing per mother would write duplicate assets for the same fragment, so this
   step runs exactly once over the full library.
5. ``ledger``   -- append a truthful row per committed lineage to the batch ledger so the frozen
   export's ``--ledger``-driven scope selection can see this run.  The row states what actually
   happened (``driver: negatives.commit_library``), it does not impersonate a single-event mother.

The stop condition is "N mothers whose library record is ok AND whose fragments were all
observed", i.e. N lineages in which both ends of every measured pair can actually be encoded.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DRIVER = REPO / "data" / "a12_trainable" / "tools" / "neg_driver.py"
CONFIG_SHA256 = "8186653101612cbc20e9eeba3f60ffbc241e3d1e3ebd690fdecb60746ab1fb16"
SCHEMA = "synlab.a12.trainable.neg_run.v1"
N_EVENTS = 3


def run(args: list[str], log: Path) -> tuple[int, str]:
    proc = subprocess.run([sys.executable, str(DRIVER)] + args, capture_output=True, text=True,
                          cwd=str(REPO), encoding="utf-8", errors="replace")
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("CMD: " + " ".join(args) + f"\nEXIT: {proc.returncode}\n--- stdout ---\n"
                   + (proc.stdout or "") + "\n--- stderr ---\n" + (proc.stderr or ""),
                   encoding="utf-8")
    payload = {}
    text = (proc.stdout or "").split("--- stderr ---")[0]
    start = text.find("{")
    if start >= 0:
        try:
            payload = json.loads(text[start:])
        except ValueError:
            payload = {}
    return proc.returncode, payload


def observed_ok(base: Path) -> list[int]:
    """Mothers whose observation report says ``ok``.

    Every ``observe_*.json`` is scanned (not just ``observe_m*``) and the mother index is taken
    from the report's own ``requested_events`` (``LIN0101_...`` -> 101), so a run started with a
    different ``--tag`` still counts once and is never re-observed -- re-observing would commit a
    second observation asset for the same fragment.
    """
    found: dict[int, str] = {}
    reports = base / "reports"
    if not reports.exists():
        return []
    for path in sorted(reports.glob("observe_*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if not payload.get("ok"):
            continue
        events = payload.get("requested_events") or []
        mothers = payload.get("requested_mothers")
        if mothers:
            for index in mothers:
                found[int(index)] = str(path)
            continue
        for event in events:
            match = re.match(r"LIN(\d{4})_", str(event))
            if match:
                found[int(match.group(1))] = str(path)
                break
    return sorted(found)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="neg_run")
    parser.add_argument("--indices", default=",".join(str(i) for i in range(100, 120)))
    parser.add_argument("--base", default="data/a12_trainable/negatives")
    parser.add_argument("--store", default="data/a12_trainable/store")
    parser.add_argument("--run-id", default="run_trainable_relneg")
    parser.add_argument("--ledger",
                        default="data/a12_trainable/store/reports/next_experiment_batches.json")
    parser.add_argument("--target", type=int, default=10)
    parser.add_argument("--logs", default="data/a12_trainable/logs")
    parser.add_argument("--out", default="data/a12_trainable/reports/neg_run.json")
    parser.add_argument("--views", type=int, default=12)
    parser.add_argument("--renderer", default="auto")
    parser.add_argument("--phase", default="all",
                        choices=["all", "events", "assemble", "observe", "commit", "ledger"])
    parser.add_argument("--demote-unverified", action="store_true",
                        help="commit phase: demote cross-event pairs whose events the exclusion "
                             "verifier could not prove distinct")
    args = parser.parse_args(argv)

    indices = [int(x) for x in args.indices.split(",") if x.strip()]
    base = Path(args.base)
    logs = Path(args.logs)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    report: dict = {"schema": SCHEMA, "indices": indices, "target_mothers_ok": int(args.target),
                    "base": str(base), "store": args.store, "run_id": args.run_id,
                    "mothers": [], "started_at": time.time()}
    common = ["--base", str(base), "--store", args.store, "--config-sha256", CONFIG_SHA256,
              "--indices", ",".join(str(i) for i in indices), "--run-id", args.run_id,
              "--views", str(args.views), "--renderer", args.renderer]
    if args.demote_unverified:
        common.append("--demote-unverified")

    def save() -> None:
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str),
                            encoding="utf-8")

    # ---------------------------------------------------------------- phase 1: events
    if args.phase in ("all", "events"):
        rc, _ = run(["plan"] + common, logs / "neg_plan.log")
        report["plan_exit_code"] = rc
        for index in indices:
            entry: dict = {"mother_index": index, "events": [], "started_at": time.time()}
            for event_index in range(N_EVENTS):
                cache = base / "work" / f"event_{index}_{event_index}.json"
                if cache.exists():
                    cached = json.loads(cache.read_text(encoding="utf-8"))
                    event = cached.get("event") or {}
                    entry["events"].append({"event_index": event_index, "cached": True,
                                            "event_id": event.get("event_id"),
                                            "ok": bool(event.get("ok")),
                                            "histogram": event.get("relation_histogram"),
                                            "seconds": cached.get("seconds")})
                    continue
                rc, payload = run(["step", "--mother", str(index), "--event", str(event_index)]
                                  + common, logs / f"neg_step_{index}_{event_index}.log")
                entry["events"].append({"event_index": event_index, "exit_code": rc,
                                        "event_id": payload.get("event_id"),
                                        "ok": payload.get("ok"),
                                        "histogram": payload.get("histogram"),
                                        "seconds": payload.get("seconds"),
                                        "last_error": payload.get("last_error")})
            entry["seconds"] = round(time.time() - entry["started_at"], 3)
            report["mothers"].append(entry)
            report["phase_reached"] = "events"
            save()
            print(json.dumps({"events": entry["mother_index"],
                              "ok": [e.get("ok") for e in entry["events"]],
                              "seconds": entry["seconds"]}, ensure_ascii=False), flush=True)

    # ---------------------------------------------------------------- phase 2: assemble
    if args.phase in ("all", "assemble"):
        rc, payload = run(["assemble"] + common, logs / "neg_assemble.log")
        report["assemble"] = {"exit_code": rc, **payload}
        report["phase_reached"] = "assemble"
        save()
        print(json.dumps(report["assemble"], ensure_ascii=False), flush=True)

    library_path = base / "library.json"
    library = json.loads(library_path.read_text(encoding="utf-8")) if library_path.exists() else {}
    ok_mothers = [int(m["mother"]["mother_index"]) for m in library.get("mothers", [])
                  if m.get("ok")]

    # ---------------------------------------------------------------- phase 3: observe
    if args.phase in ("all", "observe"):
        done = observed_ok(base)
        for index in ok_mothers:
            if len(observed_ok(base)) >= int(args.target):
                break
            if index in done:
                continue
            rc, payload = run(["observe", "--mothers", str(index), "--tag", f"m{index}"] + common,
                              logs / f"neg_observe_{index}.log")
            report.setdefault("observe", []).append({"mother_index": index, "exit_code": rc,
                                                     **payload})
            report["phase_reached"] = "observe"
            save()
            print(json.dumps({"observe": index, "exit_code": rc,
                              "observed": payload.get("observed_fragments"),
                              "failed": payload.get("failed_fragments")}, ensure_ascii=False),
                  flush=True)

    # ---------------------------------------------------------------- phase 4: commit
    if args.phase in ("all", "commit") and library:
        rc, payload = run(["commit"] + common, logs / "neg_commit.log")
        report["commit"] = {"exit_code": rc, **payload}
        report["phase_reached"] = "commit"
        save()
        print(json.dumps(report["commit"], ensure_ascii=False), flush=True)

    # ---------------------------------------------------------------- phase 5: ledger
    if args.phase in ("all", "ledger") and library:
        ledger_path = Path(args.ledger)
        ledger = (json.loads(ledger_path.read_text(encoding="utf-8"))
                  if ledger_path.exists() else {"schema": "synlab.next_experiment.batches.v1",
                                                "batches": [], "lineages": {}})
        existing = {row.get("lineage_id") for row in ledger.get("batches", [])
                    if row.get("driver") == "negatives.commit_library"}
        added = []
        for mother in library.get("mothers", []):
            lineage = str(mother["mother"]["lineage_id"])
            if lineage in existing:
                continue
            row = {"run_id": args.run_id, "driver": "negatives.commit_library",
                   "lineage_id": lineage,
                   "mother_index": int(mother["mother"]["mother_index"]),
                   "split": mother["mother"]["split"],
                   "vessel_id": mother["mother"]["vessel_id"],
                   "material_id": mother["mother"]["material_id"],
                   "pattern_id": mother["mother"]["pattern_id"],
                   "layer_combo_id": mother["mother"].get("layer_combo_id"),
                   "ok": bool(mother.get("ok")), "events_ok": int(mother.get("events_ok") or 0),
                   "events_planned": N_EVENTS,
                   "library_hash": library.get("library_hash"),
                   "exclusion_ok": bool((library.get("exclusion") or {}).get("ok")),
                   "seconds": round(float(mother.get("seconds") or 0.0), 3),
                   "at": time.time()}
            ledger.setdefault("batches", []).append(row)
            ledger.setdefault("lineages", {})[lineage] = {
                "accepted": bool(mother.get("ok")), "split": mother["mother"]["split"],
                "vessel_id": mother["mother"]["vessel_id"],
                "material_id": mother["mother"]["material_id"],
                "pattern_id": mother["mother"]["pattern_id"],
                "layer_combo_id": mother["mother"].get("layer_combo_id"),
                "driver": "negatives.commit_library", "updated_at": time.time()}
            added.append(lineage)
        ledger_path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2, default=str),
                              encoding="utf-8")
        report["ledger_rows_added"] = added
        report["ledger"] = str(ledger_path)
        save()
        print(json.dumps({"ledger_rows_added": len(added)}, ensure_ascii=False), flush=True)

    report["mothers_library_ok"] = ok_mothers
    report["mothers_observed_ok"] = sorted(observed_ok(base))
    report["mothers_observed_ok_count"] = len(report["mothers_observed_ok"])
    report["finished_at"] = time.time()
    report.setdefault("phase_reached", "all")
    save()
    print("FINAL library-ok mothers =", len(ok_mothers),
          "observed-ok mothers =", report["mothers_observed_ok_count"], "->", out_path)
    return 0 if report["mothers_observed_ok_count"] >= int(args.target) else 1


if __name__ == "__main__":
    raise SystemExit(main())
