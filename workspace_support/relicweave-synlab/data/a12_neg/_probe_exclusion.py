import json, sys
sys.path.insert(0, ".")
from synlab.relations.multi_event import verify_event_exclusion, classify_library, relation_histogram, _event_plane

rec = json.load(open("data/a12_exports/relation_negatives/work/mother_0000.json", encoding="utf-8"))
lib = {"schema": "synlab.relations.event_library.v1", "mothers": [rec], "master_seed": 20261001,
       "plan": json.load(open("data/a12_exports/relation_negatives/library_plan.json", encoding="utf-8"))}
for e in rec["events"]:
    ep = _event_plane(e) if e.get("ok") else None
    print(e.get("event_id"), "ok=", e.get("ok"), "truth=", e.get("truth_status"),
          "plane_src=", (ep or {}).get("source"), "offset=", (ep or {}).get("offset_mm"))
ex = verify_event_exclusion(lib)
print("EXCLUSION ok=", ex["ok"], "pairs=", ex["event_pairs_checked"])
for p in ex["problems"]:
    print("  problem:", json.dumps(p, ensure_ascii=False)[:300])
lib["exclusion"] = ex
rows = classify_library(lib)
print("HISTOGRAM", relation_histogram(rows))
elig = [r for r in rows if r["kind"] in ("R1","R0") and r["valid"] and r["loss_mask"]]
print("eligible_as_negative", len(elig), "of rows", len(rows))
