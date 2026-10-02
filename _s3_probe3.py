import sys, collections; sys.path.insert(0,'.')
from pathlib import Path
import pyarrow.parquet as pq
pkg = Path(r"data\a12_exports\trainable\next_experiment\training_package")
rel = pq.read_table(pkg/"research"/"relations.parquet").to_pylist()
q = pq.read_table(pkg/"deploy"/"queries.parquet").to_pylist()
roster = {r["fragment"] for r in q}
in_rel = {r["query"] for r in rel} | {r["candidate"] for r in rel}
print("roster", len(roster), "in relations", len(in_rel), "roster-only", len(roster - in_rel))
print("relations-side fragments not on roster:", len(in_rel - roster))
# mask stats by kind
t = collections.Counter()
for r in rel:
    t[(r["kind"], bool(r.get("valid")), bool(r.get("loss_mask")))] += 1
for k in sorted(t, key=lambda x: (x[0], x[1], x[2])):
    print(f"   kind={k[0]:14s} valid={k[1]!s:5s} loss_mask={k[2]!s:5s} -> {t[k]}")
print()
# UNKNOWN rows: candidates whose kind is UNKNOWN are excluded from negatives
unk = {r["candidate"] for r in rel if r["kind"]=="UNKNOWN"}
print("UNKNOWN candidates:", len(unk))
print()
# 1588 supervised = 28 R2 + 1560 R0.  Where did the R0 loss_mask come from?
print("R0 valid+loss_mask:", sum(1 for r in rel if r["kind"]=="R0" and r.get("valid") and r.get("loss_mask")))
print("R2 valid+loss_mask:", sum(1 for r in rel if r["kind"]=="R2" and r.get("valid") and r.get("loss_mask")))
print("R1 rows:", sum(1 for r in rel if r["kind"]=="R1"), "with loss_mask:", sum(1 for r in rel if r["kind"]=="R1" and r.get("loss_mask")))
print()
print("=> the 1721 rows are split as: supervised-with-loss_mask", sum(1 for r in rel if r.get("valid") and r.get("loss_mask")),
      "| no loss_mask", sum(1 for r in rel if not r.get("loss_mask")))
