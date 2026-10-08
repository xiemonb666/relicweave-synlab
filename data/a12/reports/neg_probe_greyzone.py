"""Dump the recorded grey-zone attempts of the cached mother records (read-only probe)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

WORK = REPO / "data" / "a12_exports" / "relation_negatives" / "work"

for path in sorted(WORK.glob("mother_*.json")):
    record = json.loads(path.read_text(encoding="utf-8"))
    print(f"== {path.name} ok={record.get('ok')} events_ok={record.get('events_ok')} "
          f"seconds={record.get('seconds')}")
    print(f"   mother: verts={record['mother'].get('vertices')} "
          f"area={record['mother'].get('area_mm2')} r2_thr={record['mother'].get('r2_area_threshold_mm2')} "
          f"tiny_thr={record['mother'].get('tiny_area_threshold_mm2')}")
    for event in record.get("events", []):
        role = (event.get("plan") or {}).get("role")
        print(f"   event={event.get('event_id')!r} role={role} ok={event.get('ok')} "
              f"status={event.get('truth_status')} hist={event.get('relation_histogram')}")
        for attempt in event.get("attempts", []):
            keep = {k: v for k, v in attempt.items()
                    if k in ("attempt", "kind", "target_area_mm2", "dialed_section_area_mm2",
                             "ok", "error", "error_code", "role_satisfied", "role_check",
                             "fragment_ids", "relation_histogram", "seconds",
                             "dial_search_steps")}
            print(f"      attempt: {json.dumps(keep, ensure_ascii=False)}")
