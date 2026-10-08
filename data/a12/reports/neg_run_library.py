"""Run the relation-negative event library **one fracture event per process**.

Why per event: the host kills long / heavy python processes (measured: a mother taking ~90 s
died with ``exit -1073740022`` after finishing two of its four events, losing the whole mother
record).  Each measured event is independent -- ``_run_one_mother`` rebuilds the mother from the
same shape seed and every event draws its own cut sub-stream -- so running them in separate
processes is outcome-identical and a kill costs at most one event.

Usage
-----
``python data/a12/reports/neg_run_library.py step <mother_index> <event_index>``
    run one planned event, cache it at ``work/event_<m>_<e>.json``
``python data/a12/reports/neg_run_library.py assemble``
    merge the cached events into ``work/mother_<m>.json`` in the exact record layout
    ``synlab.relations.multi_event.run_event_library`` produces
``python data/a12/reports/neg_run_library.py plan``
    write the frozen event-library plan

Everything is written under ``data/a12/reports/relation_negatives/`` (inside this task's scope).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from synlab.relations.multi_event import (  # noqa: E402
    LibraryPlan, _run_one_mother, plan_event_library,
)
from synlab.schemas.spec import FractureConfig  # noqa: E402

BASE = REPO / "data" / "a12" / "reports" / "relation_negatives"
WORK = BASE / "work"
MESHES = BASE / "meshes"
MASTER_SEED = 20261001
GREY_ZONE_MOTHERS = [0, 1, 2, 3]
DISTRACTOR_INDICES = [1]
UNRESOLVED_MOTHERS = [0, 2]
SOURCE_PLAN = REPO / "data" / "a12_exports" / "relation_negatives" / "library_plan.json"

#: events of one mother that together count as a usable record
MIN_EVENTS_PER_MOTHER = 3


def build_plan() -> LibraryPlan:
    source = json.loads(SOURCE_PLAN.read_text(encoding="utf-8"))
    plan = plan_event_library([dict(m) for m in source["mothers"]], n_events=3,
                              master_seed=MASTER_SEED,
                              grey_zone_mothers=GREY_ZONE_MOTHERS,
                              distractor_indices=DISTRACTOR_INDICES,
                              unresolved_mothers=UNRESOLVED_MOTHERS)
    BASE.mkdir(parents=True, exist_ok=True)
    (BASE / "library_plan.json").write_text(
        json.dumps(plan.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return plan


def run_step(mother_index: int, event_index: int) -> dict:
    WORK.mkdir(parents=True, exist_ok=True)
    MESHES.mkdir(parents=True, exist_ok=True)
    plan = build_plan()
    mother_plan = next(m for m in plan.mothers if m.mother_index == mother_index)
    events = plan.events_of(mother_index)
    event_plan = events[event_index]
    sub = LibraryPlan(master_seed=plan.master_seed, mothers=[mother_plan], events=[event_plan])
    record = _run_one_mother(
        mother_plan, sub, fracture_config=FractureConfig(),
        create_mother=_import("mothers"), fracture_event=_import("event"),
        audit_fracture=_import("audit"), finalize_clean_truth=_import("truth"),
        fracture_spec_cls=_import("spec"), plane_backend=_import("backend"),
        micro_events=True, mesh_dir=MESHES)
    payload = {"mother_index": mother_index, "event_index": event_index,
               "mother": record["mother"], "event": record["events"][0],
               "seconds": record["seconds"], "ran_at": time.time()}
    (WORK / f"event_{mother_index}_{event_index}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    event = payload["event"]
    return {"mother_index": mother_index, "event_index": event_index,
            "event_id": event.get("event_id"), "ok": bool(event.get("ok")),
            "role": (event.get("plan") or {}).get("role"),
            "truth_status": event.get("truth_status"),
            "histogram": event.get("relation_histogram"),
            "role_satisfied": event.get("role_satisfied"),
            "role_check": event.get("role_check"), "last_error": event.get("last_error"),
            "attempts": [{"attempt": a.get("attempt"), "kind": a.get("kind"),
                          "target_area_mm2": a.get("target_area_mm2"),
                          "dialed_section_area_mm2": a.get("dialed_section_area_mm2"),
                          "ok": a.get("ok"), "error": a.get("error"),
                          "seconds": a.get("seconds")}
                         for a in event.get("attempts", [])],
            "seconds": payload["seconds"]}


def _import(what: str):
    if what == "mothers":
        from synlab.mothers.api import create_mother
        return create_mother
    if what == "event":
        from synlab.fracture.api import fracture_event
        return fracture_event
    if what == "audit":
        from synlab.fracture.api import audit_fracture
        return audit_fracture
    if what == "truth":
        from synlab.truth.api import finalize_clean_truth
        return finalize_clean_truth
    if what == "spec":
        from synlab.fracture.spec import FractureSpec
        return FractureSpec
    if what == "backend":
        from synlab.fracture.spec import BACKEND_PLANE
        return BACKEND_PLANE
    raise KeyError(what)


def assemble() -> dict:
    """Merge ``work/event_*.json`` into ``work/mother_<m>.json`` (run_event_library layout)."""
    plan = build_plan()
    summary: dict = {"schema": "synlab.neg.assemble.v1", "mothers": [], "plan_written": True}
    for mother_plan in plan.mothers:
        index = mother_plan.mother_index
        events, mother_row, seconds = [], None, 0.0
        for event_index, _event_plan in enumerate(plan.events_of(index)):
            path = WORK / f"event_{index}_{event_index}.json"
            if not path.exists():
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            mother_row = mother_row or payload["mother"]
            events.append(payload["event"])
            seconds += float(payload.get("seconds") or 0.0)
        if not events:
            continue
        usable = [e for e in events if e.get("ok")]
        record = {
            "mother": mother_row, "events": events,
            "ok": (len(usable) >= MIN_EVENTS_PER_MOTHER
                   and len({e["event_id"] for e in usable}) == len(usable)),
            "events_ok": len(usable), "seconds": seconds,
        }
        (WORK / f"mother_{index:04d}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        summary["mothers"].append({
            "mother_index": index, "lineage_id": mother_plan.lineage_id, "ok": record["ok"],
            "events_ok": len(usable), "events_cached": len(events),
            "events": [{"event_id": e.get("event_id"), "ok": e.get("ok"),
                        "role": (e.get("plan") or {}).get("role"),
                        "truth_status": e.get("truth_status"),
                        "histogram": e.get("relation_histogram"),
                        "role_satisfied": e.get("role_satisfied"),
                        "role_check": e.get("role_check"), "last_error": e.get("last_error")}
                       for e in events]})
    (BASE / "assemble.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
    return summary


def main(argv: list[str]) -> int:
    mode = argv[1] if len(argv) > 1 else "plan"
    if mode == "plan":
        print(json.dumps(build_plan().as_dict(), ensure_ascii=False)[:400])
        return 0
    if mode == "step":
        result = run_step(int(argv[2]), int(argv[3]))
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0 if result["ok"] else 1
    if mode == "assemble":
        print(json.dumps(assemble(), ensure_ascii=False, indent=2))
        return 0
    raise SystemExit(f"unknown mode {mode!r}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
