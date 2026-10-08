"""Dump one cached event record (measured facts only)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
WORK = REPO / "data" / "a12" / "reports" / "relation_negatives" / "work"

index = int(sys.argv[1]), int(sys.argv[2])
payload = json.loads((WORK / f"event_{index[0]}_{index[1]}.json").read_text(encoding="utf-8"))
event = payload["event"]
print("event:", event.get("event_id"), "role:", event["plan"]["role"], "ok:", event.get("ok"))
print("truth_status:", event.get("truth_status"), "histogram:", event.get("relation_histogram"))
print("thresholds: r2=", event.get("r2_area_threshold_mm2"), "tiny=",
      event.get("tiny_area_threshold_mm2"))
print("role_satisfied:", event.get("role_satisfied"), event.get("role_check"))
print("fracture_spec:", json.dumps(event.get("fracture_spec"), ensure_ascii=False))
print("grey_zone_dial:", json.dumps(event.get("grey_zone_dial"), ensure_ascii=False))
print("fragments:")
for f in event.get("fragments", []):
    print("  ", f["fragment_id"], "vol=", round(f["volume_mm3"], 4), "area=",
          round(f["area_mm2"], 4), "is_tiny=", f["is_tiny"], "iface_faces=",
          f["interface_face_count"], "iface_area=", round(f["interface_face_area_mm2"], 6),
          "plane=", json.dumps(f.get("interface_plane"), ensure_ascii=False))
print("interfaces:")
for p in event.get("interfaces", []):
    print("  ", json.dumps(p, ensure_ascii=False))
print("relations:")
for r in event.get("relations", []):
    print("  ", json.dumps(r, ensure_ascii=False))
print("clean_qa:", json.dumps(event.get("clean_qa"), ensure_ascii=False)[:600])
print("clean_meta:", json.dumps(event.get("clean_meta"), ensure_ascii=False))
