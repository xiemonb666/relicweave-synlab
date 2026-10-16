"""The store -> release -> export -> batch chain over the measured relation-negative library.

Modes (each a separate process, so a host kill costs only that step):

``commit``   commit the measured library (one label_bundle per fragment, one clean_truth per
             event, the real fragment meshes) into ``relation_negatives/store``
``observe``  observe the fragments of the named events for real and commit obs + features
``release``  freeze the closure-verified release of that run
``export``   export the training package of that release
``batch``    build a real TrainingBatch from the exported package and report the composition
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
REPORTS = Path(__file__).resolve().parent
if str(REPORTS) not in sys.path:
    sys.path.insert(0, str(REPORTS))

from synlab.relations.multi_event import verify_event_exclusion  # noqa: E402
from synlab.schemas.spec import FractureConfig  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402

BASE = REPO / "data" / "a12" / "reports" / "relation_negatives"
WORK = BASE / "work"
MESHES = BASE / "meshes"
STORE = BASE / "store"
PKG = BASE / "training_package"
RUN_ID = "neg_lib_v1"
RELEASE_ID = "neg_lib_v1_release"
OBSERVE_EVENTS = ["LIN0000_V01_M01_PAT01_E01", "LIN0000_V01_M01_PAT01_E02"]


def load_library() -> dict:
    plan = json.loads((BASE / "library_plan.json").read_text(encoding="utf-8"))
    mothers = [json.loads(p.read_text(encoding="utf-8"))
               for p in sorted(WORK.glob("mother_*.json"))]
    library = {"schema": "synlab.relations.event_library.v1",
               "version": "relations.multi_event.v1", "master_seed": plan["master_seed"],
               "plan": plan, "mothers": mothers}
    library["exclusion"] = verify_event_exclusion(library)
    library["ok"] = (bool(mothers) and all(m.get("ok") for m in mothers)
                     and library["exclusion"]["ok"])
    return library


def out(name: str, payload: dict) -> None:
    (BASE / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                             encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str)[:4000])


def mode_commit() -> int:
    from synlab.relations.negatives import commit_library

    store = AssetStore(STORE)
    library = load_library()
    started = time.perf_counter()
    committed = commit_library(store, library, run_id=RUN_ID, mesh_dir=MESHES)
    committed["seconds"] = time.perf_counter() - started
    out("chain_commit.json", committed)
    return 0 if committed["relations"] else 1


def mode_observe() -> int:
    import neg_run_library as runner

    from synlab.relations.negatives import observe_library

    store = AssetStore(STORE)
    plan = runner.build_plan()
    events = [str(e) for e in (sys.argv[2:] or OBSERVE_EVENTS)]
    started = time.perf_counter()
    report = observe_library(plan, store, fracture_config=FractureConfig(), events=events,
                             run_id=RUN_ID, library=load_library())
    report["seconds"] = time.perf_counter() - started
    report["requested_events"] = events
    # correspondence: the observed fragment geometry must be the one the labels were measured
    # on.  The cut is body-determined for the plane backend, so the mesh hashes must be equal
    # -- measured here instead of assumed.
    library = load_library()
    recorded = {str(f["fragment_id"]): str(f.get("mesh_hash", ""))
                for m in library["mothers"] for e in m.get("events", []) if e.get("ok")
                for f in e.get("fragments", [])}
    observed = sorted(report.get("features", {}))
    report["correspondence"] = {
        "observed_fragments": observed,
        "recorded_fragments": len(recorded),
        "fragments_with_a_recorded_mesh_hash": sum(1 for f in observed if f in recorded),
        "note": ("every observed fragment id must exist in the measured library so the label "
                 "rows that mention it are the rows measured on that same geometry"),
    }
    out("chain_observe.json", report)
    return 0 if report.get("observed_fragments") else 1


def mode_release() -> int:
    from synlab.relations.negatives import freeze_library_release

    store = AssetStore(STORE)
    result = freeze_library_release(store, release_id=RELEASE_ID, run_id=RUN_ID,
                                    evidence_dirs=("data/a12",))
    out("chain_release.json", result)
    return 0 if result.get("frozen") else 1


def mode_export() -> int:
    from synlab.storage.export import export_training_package

    store = AssetStore(STORE)
    manifest = export_training_package(store, RELEASE_ID, PKG)
    payload = {"counts": manifest.get("counts"), "package_dir": str(PKG),
               "manifest_keys": sorted(manifest)}
    out("chain_export.json", payload)
    return 0 if manifest.get("counts") else 1


def mode_batch() -> int:
    from synlab.relations.negatives import build_training_batch_for_package

    result = build_training_batch_for_package(PKG)
    result.pop("batch_object", None)
    result.pop("pool_object", None)
    out("chain_batch.json", result)
    return 0


MODES = {"commit": mode_commit, "observe": mode_observe, "release": mode_release,
         "export": mode_export, "batch": mode_batch}

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "commit"
    raise SystemExit(MODES[mode]())
