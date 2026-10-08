"""One-shot patch: thread the per-fragment context through the remaining call sites."""
from __future__ import annotations

import pathlib

P = pathlib.Path(r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\synlab\pipeline.py")
SRC = P.read_text(encoding="utf-8")

PAIRS = [
    ("physical_truth_ref = commit_truth(store, stamp_context(physical_truth, context),",
     "physical_truth_ref = commit_truth(store, stamp_context(physical_truth, lineage_context),"),
    ("        stamp_context(observation, context)\n",
     "        stamp_context(observation, context_for_fragment.get(primary_fragment_id,\n"
     "                                                            lineage_context))\n"),
    ("            stamp_context(endpoint, context)\n",
     "            stamp_context(endpoint, context_for_fragment.get(fragment_id, lineage_context))\n"),
    ('visible_ref = commit_truth(store, stamp_context(visible, context), role="visible_labels",',
     'visible_ref = commit_truth(store, stamp_context(visible, lineage_context),\n'
     '                                   role="visible_labels",'),
    ("                                   run_id=run_id, context=context)",
     "                                   run_id=run_id, context=lineage_context)"),
    ("                                            label_ref.asset_id, run_id=run_id, context=context)",
     "                                            label_ref.asset_id, run_id=run_id,\n"
     "                                            context=lineage_context)"),
]

for old, new in PAIRS:
    count = SRC.count(old)
    if count != 1:
        raise SystemExit(f"expected 1 occurrence, found {count}: {old[:70]!r}")
    SRC = SRC.replace(old, new)

P.write_text(SRC, encoding="utf-8")
print("patched", P)
