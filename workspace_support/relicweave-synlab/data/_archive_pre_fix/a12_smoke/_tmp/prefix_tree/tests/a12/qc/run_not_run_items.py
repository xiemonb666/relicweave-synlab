"""Run the acceptance items that were NOT_RUN but whose prerequisites exist.

Each step is one process and writes its report immediately, so a killed run never loses the
evidence of the steps that already finished.

Steps
-----
``pool``      A15  real pool build from ``configs/a12/pool_dev.yaml`` -> ``pool_audit.json``
``episode``   A19  rule episode on the built pool -> ``episode_trace.json``
``truth``     A08  truth/relation fixture over the committed fracture events -> ``truth_fixture.json``
``precision`` A07  error budget of a real fracture event -> ``precision_report.json``
``origin``    A27  origin-triangle correspondence across a real event -> ``origin_correspondence_audit.json``

Run:  .venv\\Scripts\\python.exe tests\\a12\\qc\\run_not_run_items.py --step pool
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

STORE_ROOT = ROOT / "data" / "a12"


def write_report(name: str, payload: dict[str, Any]) -> Path:
    path = STORE_ROOT / "reports" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str),
                    encoding="utf-8")
    return path


def _store():
    from synlab.storage.store import AssetStore

    return AssetStore(str(STORE_ROOT))


def step_pool() -> dict[str, Any]:
    from synlab.relations.api import build_pool_from_config

    report = build_pool_from_config(_store(), "sandbox", str(ROOT / "configs/a12/pool_dev.yaml"))
    write_report("pool_audit", report)
    return {"ok": report.get("ok"), "status": report.get("status")}


def step_episode() -> dict[str, Any]:
    from synlab.episodes.api import run_episode_config

    report = run_episode_config(_store(), str(ROOT / "configs/a12/pool_dev.yaml"))
    write_report("episode_trace", report)
    return {"ok": report.get("ok"), "status": report.get("status")}


def step_truth() -> dict[str, Any]:
    """A08: run the truth contract on the committed fracture events (no invented relations)."""
    from synlab.truth.api import audit_truth_relations

    report = audit_truth_relations(_store())
    write_report("truth_fixture", report)
    return {"ok": report.get("ok"), "status": report.get("status")}


def step_precision() -> dict[str, Any]:
    from synlab.truth.api import audit_cut_precision

    report = audit_cut_precision(_store())
    write_report("precision_report", report)
    return {"ok": report.get("ok"), "status": report.get("status")}


def step_origin() -> dict[str, Any]:
    from synlab.truth.api import audit_origin_correspondence

    report = audit_origin_correspondence(_store())
    write_report("origin_correspondence_audit", report)
    return {"ok": report.get("ok"), "status": report.get("status")}


STEPS = {"pool": step_pool, "episode": step_episode, "truth": step_truth,
         "precision": step_precision, "origin": step_origin}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--step", required=True, choices=sorted(STEPS) + ["probe"])
    args = parser.parse_args()
    if args.step == "probe":
        return probe()
    started = time.time()
    try:
        summary = STEPS[args.step]()
    except Exception as exc:  # noqa: BLE001 - reported, never hidden
        import traceback

        summary = {"ok": False, "status": "RAISED", "error": f"{type(exc).__name__}: {exc}",
                   "traceback": traceback.format_exc()[-2000:]}
    summary["seconds"] = round(time.time() - started, 2)
    print(json.dumps(summary, ensure_ascii=False, indent=1, default=str))
    return 0


def probe() -> int:
    """What prerequisites actually exist in the store for the remaining NOT_RUN items?"""
    store = _store()
    roles: dict[str, int] = {}
    for asset in store.list_assets(limit=100000):
        roles[asset.role] = roles.get(asset.role, 0) + 1
    print(json.dumps({"roles": roles}, ensure_ascii=False, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
