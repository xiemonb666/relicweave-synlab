"""Probe the context pack of the a12_context store: field values, batches, coexistents, query."""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

REPO = Path(r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab")
ROOT = REPO / "data" / "a12_context" / "store"
sys.path.insert(0, str(REPO))

con = sqlite3.connect(f"file:{(ROOT / 'metadata.sqlite').as_posix()}?mode=ro", uri=True)
con.row_factory = sqlite3.Row

print("=== role census ===")
total = con.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
print("total assets:", total)
for row in con.execute("SELECT role, COUNT(*) c FROM assets GROUP BY role ORDER BY role"):
    print(f"  {row['role']:24s} {row['c']}")

print()
print("=== context packs ===")
packs = list(con.execute("SELECT asset_id, schema, unit, frame, qa_status, meta_json "
                         "FROM assets WHERE role='context_pack'"))
print("context_pack assets:", len(packs))
docs = []
for row in packs:
    meta = json.loads(row["meta_json"])
    docs.append(meta)
    print(f"  {row['asset_id']}  schema={row['schema']} unit={row['unit']} frame={row['frame']} "
          f"qa={row['qa_status']}")
    for key in ("simulated", "pack_id", "context_id", "batch_id", "batch_index", "batch_size",
                "bag_id", "pit_id", "site_id", "institution_id", "excavation_area_id", "grid_ref",
                "unit_code", "stratum_id", "stratum_depth_mm", "session_id", "operator_id",
                "captured_at"):
        if key in meta:
            print(f"      {key:20s} = {meta[key]!r}")
    print(f"      scale_reference      = {json.dumps(meta.get('scale_reference'), ensure_ascii=False)}")
    print(f"      coexistents          = {len(meta.get('coexistents') or [])} rows")
    print(f"      coexistent_counts    = {json.dumps(meta.get('coexistent_counts'), ensure_ascii=False)}")
    print(f"      site_notes           = {meta.get('site_notes')!r}")

print()
print("=== field presence across packs (denominator = %d) ===" % len(docs))
FIELDS = ["simulated", "excavation_area_id", "grid_ref", "stratum_id", "stratum_depth_mm",
          "bag_id", "pit_id", "context_id", "batch_id", "coexistents", "scale_reference",
          "session_id", "operator_id", "captured_at", "site_notes"]
for name in FIELDS:
    present = sum(1 for d in docs if d.get(name) not in (None, "", [], {}))
    print(f"  {name:20s} present in {present}/{len(docs)}")
print("  simulated is True     :", sum(1 for d in docs if d.get("simulated") is True), "/",
      len(docs))

print()
print("=== batch grouping ===")
batch_sizes = Counter(int(d.get("batch_size") or 0) for d in docs)
coexist = [len(d.get("coexistents") or []) for d in docs]
print("batch_size histogram   :", dict(sorted(batch_sizes.items())))
print("coexistents per pack   :", sorted(coexist))
print("distinct batch_id      :", len({d.get("batch_id") for d in docs}))
print("distinct context_id    :", len({d.get("context_id") for d in docs}))
print("distinct bag_id        :", len({d.get("bag_id") for d in docs}))
print("distinct pit_id        :", len({d.get("pit_id") for d in docs}))
print("distinct stratum_id    :", len({d.get("stratum_id") for d in docs}))
print("excavation areas       :", sorted({d.get("excavation_area_id") for d in docs}))
print("scale kinds            :", dict(sorted(Counter(
    (d.get("scale_reference") or {}).get("scale_reference_kind") for d in docs).items())))

print()
print("=== context carriers (meta.context_id per role) ===")
carriers: dict[str, int] = {}
without: dict[str, int] = {}
for row in con.execute("SELECT role, meta_json FROM assets"):
    meta = json.loads(row["meta_json"])
    if meta.get("context_id"):
        carriers[row["role"]] = carriers.get(row["role"], 0) + 1
    else:
        without[row["role"]] = without.get(row["role"], 0) + 1
for role in sorted(set(carriers) | set(without)):
    print(f"  {role:24s} with={carriers.get(role, 0):3d} without={without.get(role, 0):3d}")
print()
print("bag_id present flat (should be 0; it is nested under meta.context):",
      sum(1 for row in con.execute("SELECT meta_json FROM assets")
          if "bag_id" in json.loads(row["meta_json"])))
print("meta.context block present:",
      sum(1 for row in con.execute("SELECT meta_json FROM assets")
          if isinstance(json.loads(row["meta_json"]).get("context"), dict)))

print()
print("=== query example: fragment -> same-batch candidate scope ===")
from synlab.storage.store import AssetStore  # noqa: E402
from synlab.pipeline import context_query  # noqa: E402

store = AssetStore(ROOT)
fragment_rows = [r for r in con.execute(
    "SELECT asset_id, meta_json FROM assets WHERE role='fragment_mesh' ORDER BY asset_id")]
for row in fragment_rows[:1]:
    fragment_id = json.loads(row["meta_json"])["fragment_id"]
    answer = context_query(store, fragment_id)
    print("fragment:", fragment_id)
    print(json.dumps(answer, ensure_ascii=False, indent=2))

print()
print("=== every fragment's scope (batch id + candidate count) ===")
for row in fragment_rows:
    meta = json.loads(row["meta_json"])
    answer = context_query(store, meta["fragment_id"])
    print(f"  {meta['fragment_id']:40s} batch={answer.get('batch_id')} "
          f"candidates={len(answer.get('same_batch_candidates') or [])} "
          f"simulated={answer.get('simulated')}")
