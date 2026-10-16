"""Record every campaign batch into data/a12/reports/campaign_batches.json from the real ledgers.

Design notes (why it works this way)
------------------------------------
* ``tools/batch_generate.py`` writes one row to its ledger **after every mother**, which is the
  durable record; ``last_batch`` is only written when an invocation reaches its end, so a
  host-killed process leaves no ``last_batch`` at all.  Everything below is therefore rebuilt from
  the per-mother rows.
* ``run_id`` is derived from the plan job id, so *every* invocation of the same config reuses the
  same id, and it also changes when the spec is recompiled.  Invocations are separated by the real
  time gap between consecutive mothers (the driver writes the next row ~100-155 s later) and by a
  job-id change.
* The output file is a faithful projection of the ledgers, so it is rewritten (not hand-appended):
  a killed batch can never be lost, and running this twice cannot duplicate a row.
* Honest counters only: ``attempted``/``accepted``/``failed`` come from the rows, and
  ``killed_by_host`` is true when the invocation has no matching ``last_batch`` -- i.e. the process
  died before it could finish, which is exactly the host-kill signature observed on this machine.
"""
from __future__ import annotations

import json
import time
from collections import OrderedDict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CAMPAIGN = REPO / "data" / "a12_campaign"
OUT = REPO / "data" / "a12" / "reports" / "campaign_batches.json"

LEDGERS = OrderedDict([
    ("realistic", CAMPAIGN / "campaign_ledger.json"),
    ("control_baseline", CAMPAIGN / "control_ledger.json"),
])

FIELDS = ("lineage_id", "mother_index", "split", "vessel_id", "material_id", "pattern_id",
          "layer_combo_id", "ok", "error", "error_message", "seconds", "fragments",
          "observations", "r2_pairs", "stages")

#: A gap larger than this between two consecutive per-mother rows means a new invocation started.
GAP_SECONDS = 45.0


def load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def sidecar_hashes(logs: Path) -> dict[str, str]:
    """The pinned-runner code fingerprints, keyed by batch name."""
    out: dict[str, str] = {}
    for path in sorted(logs.glob("*.code.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        out[path.name.replace(".code.json", "")] = doc.get("code_digest_before", "")
    return out


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    logs = CAMPAIGN / "logs"
    hashes = sidecar_hashes(logs)

    batches: list[dict] = []
    for label, path in LEDGERS.items():
        ledger = load(path)
        rows = ledger.get("batches", [])
        if not rows:
            continue
        grouped: dict[str, list[dict]] = OrderedDict()
        prev_at: float | None = None
        prev_job: str | None = None
        invocation = 0
        for row in rows:
            at = float(row.get("at") or 0)
            job = str(row.get("run_id") or "")
            if prev_at is None or (at - prev_at) > GAP_SECONDS or job != prev_job:
                invocation += 1
            prev_at, prev_job = at, job
            grouped.setdefault(f"{job}#i{invocation}", []).append(row)

        last = ledger.get("last_batch") or {}
        last_job = str(last.get("run_id") or "")
        last_batch_size = last.get("batch")

        for batch_key, group in grouped.items():
            job = batch_key.split("#")[0]
            attempted = len(group)
            accepted = sum(1 for r in group if r.get("ok"))
            errors: dict[str, int] = {}
            for row in group:
                if row.get("error"):
                    errors[str(row["error"])] = errors.get(str(row["error"]), 0) + 1
            record = {
                "campaign": label,
                "ledger": str(path.relative_to(REPO)).replace("\\", "/"),
                "batch_key": batch_key,
                "run_id": job,
                "mother_indices": [r.get("mother_index") for r in group],
                "first_at": min(float(r.get("at") or 0) for r in group),
                "last_at": max(float(r.get("at") or 0) for r in group),
                "attempted": attempted,
                "accepted": accepted,
                "failed": attempted - accepted,
                "error_codes": errors,
                "seconds_sum": round(sum(float(r.get("seconds") or 0) for r in group), 3),
                "lineages": [{k: r.get(k) for k in FIELDS} for r in group],
            }
            finished = (job == last_job and attempted == last_batch_size)
            record["killed_by_host"] = not finished
            if finished:
                record["driver_totals"] = {k: last.get(k) for k in
                                           ("batch", "attempted", "accepted", "failed", "seconds",
                                            "seconds_per_accepted_mother", "disk_delta_mb",
                                            "store_bytes")}
            batches.append(record)

    batches.sort(key=lambda r: (r.get("campaign", ""), float(r.get("first_at") or 0)))
    doc = {
        "schema": "synlab.a12_campaign.batches.v1",
        "note": ("rebuilt from the driver ledgers; per-mother rows are the durable record and a "
                 "host-killed invocation has no last_batch, so it is marked killed_by_host"),
        "code_digests_by_batch": hashes,
        "updated_at": time.time(),
        "totals": {
            "batches": len(batches),
            "attempted": sum(b["attempted"] for b in batches),
            "accepted": sum(b["accepted"] for b in batches),
            "failed": sum(b["failed"] for b in batches),
            "killed_batches": sum(1 for b in batches if b["killed_by_host"]),
            "wall_seconds": round(sum(b["seconds_sum"] for b in batches), 1),
        },
        "batches": batches,
    }
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(doc["totals"], ensure_ascii=False, indent=2))
    for b in batches:
        flag = " KILLED" if b["killed_by_host"] else ""
        print(f"  {b['campaign']:<16} {b['batch_key']:<28} attempted={b['attempted']} "
              f"accepted={b['accepted']} failed={b['failed']} {b['seconds_sum']}s "
              f"{b['error_codes']}{flag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
