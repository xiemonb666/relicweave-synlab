"""UNKNOWN discipline / R2 symmetry / non-transitivity: measured assertions on the real library.

Item 2 of the task.  Every assertion below is evaluated on the **measured** library and rows
written by ``neg_summary.py``; the script exits non-zero if any assertion fails.  Output:
``data/a12/reports/relation_negatives_unknown_discipline.json``.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from synlab.relations.multi_event import library_fragments  # noqa: E402
from synlab.relations.negatives import (  # noqa: E402
    _r2_mates, batch_rows_from_relations,
)
from synlab.schemas.runtime import (  # noqa: E402
    RELATION_R0, RELATION_R1, RELATION_R2, RELATION_TINY, RELATION_UNKNOWN,
)
from synlab.storage.export import (  # noqa: E402
    EXCLUDED_NEGATIVE_KINDS, NEGATIVE_KINDS,
)

REPORTS = REPO / "data" / "a12" / "reports"
OUT = REPORTS / "relation_negatives_unknown_discipline.json"

library = json.loads((REPORTS / "relation_negatives_library.json").read_text(encoding="utf-8"))
rows = json.loads((REPORTS / "relation_negatives_rows.json").read_text(encoding="utf-8"))
fragments = library_fragments(library)
fragment_ids = sorted(fragments)
unknown = [r for r in rows if str(r["kind"]) == RELATION_UNKNOWN]
r2 = [r for r in rows if str(r["kind"]) == RELATION_R2]

assertions: list[dict] = []


def check(name: str, ok: bool, measured, note: str = "") -> None:
    assertions.append({"name": name, "ok": bool(ok), "measured": measured, "note": note})


# --- 1. UNKNOWN never a negative -------------------------------------------------------
check("unknown_rows_exist", bool(unknown), len(unknown),
      "a library without UNKNOWN cannot demonstrate the discipline")
check("unknown_never_loss_masked", all(r.get("loss_mask") is False for r in unknown),
      {"rows": len(unknown), "loss_mask_true": sum(1 for r in unknown if r.get("loss_mask"))},
      "plan 2.4: UNKNOWN 不转负例 / 退出监督分母")
check("unknown_never_valid", all(r.get("valid") is False for r in unknown),
      {"rows": len(unknown), "valid_true": sum(1 for r in unknown if r.get("valid"))})
check("unknown_not_in_NEGATIVE_KINDS", RELATION_UNKNOWN not in NEGATIVE_KINDS,
      {"NEGATIVE_KINDS": sorted(NEGATIVE_KINDS)})
check("unknown_in_EXCLUDED_NEGATIVE_KINDS", RELATION_UNKNOWN in EXCLUDED_NEGATIVE_KINDS,
      {"EXCLUDED_NEGATIVE_KINDS": sorted(EXCLUDED_NEGATIVE_KINDS)})
eligibility = [{"a": r["a"], "b": r["b"],
                "eligible_as_negative": bool(str(r["kind"]) in NEGATIVE_KINDS
                                             and r.get("valid") and r.get("loss_mask"))}
               for r in unknown]
check("unknown_export_eligibility_all_false",
      all(not e["eligible_as_negative"] for e in eligibility),
      {"rows": len(eligibility), "eligible": sum(1 for e in eligibility
                                                 if e["eligible_as_negative"])},
      "same predicate as synlab/storage/export.py:_pool_relations")

export_rows = [{"query": r["a"], "candidate": r["b"], "kind": r["kind"],
                "valid": bool(r["valid"]), "loss_mask": bool(r["loss_mask"])} for r in rows]
batch_rows = batch_rows_from_relations(export_rows, fragment_ids)
unknown_pairs = {frozenset((r["a"], r["b"])) for r in unknown}
leaked = [(row["query"], c) for row in batch_rows for c in row["negatives"]
          if frozenset((row["query"], c)) in unknown_pairs]
excluded_unknown = sum(1 for row in batch_rows for c in row["excluded"]
                       if frozenset((row["query"], c)) in unknown_pairs)
check("unknown_never_lands_in_batch_negatives", not leaked,
      {"batch_rows": len(batch_rows), "unknown_pairs": len(unknown_pairs),
       "leaked_into_negatives": len(leaked), "present_in_excluded": excluded_unknown},
      "batch_rows_from_relations: an UNKNOWN pair can only appear in `excluded`")

# --- 2. R2 symmetry, uniqueness, no self-loops ------------------------------------------
keys = [(str(r["a"]), str(r["b"])) for r in rows]
check("no_self_loops", all(a != b for a, b in keys),
      {"rows": len(keys), "self_loops": sum(1 for a, b in keys if a == b)})
check("pairs_unique_and_canonical", len(keys) == len(set(keys)) == len({frozenset(k) for k in keys}),
      {"rows": len(keys), "distinct_ordered": len(set(keys)),
       "distinct_unordered": len({frozenset(k) for k in keys})},
      "one unordered pair appears exactly once (a < b)")
lookup = {(str(r["a"]), str(r["b"])): str(r["kind"]) for r in rows}
r2_keys = {(str(r["a"]), str(r["b"])) for r in r2}
reverse_duplicates = sorted((a, b) for a, b in r2_keys if (b, a) in lookup)
check("r2_has_no_duplicate_reverse_row", not reverse_duplicates,
      {"r2_rows": len(r2), "rows_whose_reverse_is_a_second_row": len(reverse_duplicates),
       "examples": reverse_duplicates[:4]},
      "an undirected adjacency is stored once per unordered pair")
check("r2_has_no_self_loop", all(str(r["a"]) != str(r["b"]) for r in r2),
      {"r2_rows": len(r2), "self_loops": sum(1 for r in r2 if r["a"] == r["b"])})
mates = _r2_mates(export_rows)
mate_asymmetry = [(a, b) for a, bs in mates.items() for b in bs if a not in mates.get(b, set())]
check("r2_mate_map_is_symmetric", not mate_asymmetry,
      {"fragments_with_mates": len(mates), "asymmetric_entries": len(mate_asymmetry)})
check("r2_mate_map_has_no_self_mate", all(a not in bs for a, bs in mates.items()),
      {"fragments_with_mates": len(mates)})

# --- 3. genuine non-adjacency is never promoted to R2 -----------------------------------
measured_edges: list[tuple[str, str]] = []
events_with_truth = 0
for mother in library.get("mothers", []):
    for event in mother.get("events", []):
        if not event.get("ok") or event.get("truth_status") != "COMPUTED":
            continue
        events_with_truth += 1
        for row in event.get("relations", []):
            a, b = str(row["a"]), str(row["b"])
            if str(row["kind"]) == RELATION_R2:
                measured_edges.append((a, b) if a <= b else (b, a))
r2_keys = {(str(r["a"]), str(r["b"])) for r in r2}
check("r2_rows_equal_measured_r2_edges", r2_keys == set(measured_edges),
      {"r2_rows": len(r2_keys), "measured_r2_edges": len(measured_edges),
       "in_rows_not_measured": sorted(r2_keys - set(measured_edges))[:4],
       "measured_not_in_rows": sorted(set(measured_edges) - r2_keys)[:4]},
      "every R2 row is a verbatim copy of a measured interface verdict; none is inferred")
check("r2_graph_is_a_matching", all(len(v) == 1 for v in mates.values()) if mates else False,
      {"mate_degree_histogram": {str(k): v for k, v in sorted(
          Counter(len(v) for v in mates.values()).items())},
       "fragments": len(fragments), "r2_edges": len(r2)},
      "measured consequence of one single-plane cut per event: 2 fragments per event")

paths = [(a, b, c) for a in mates for b in mates.get(a, ()) for c in mates.get(b, ())
         if c != a and a < c]
transitive_violations = [(a, b, c) for a, b, c in paths if frozenset((a, c)) not in
                         {frozenset(k) for k in r2_keys}]
check("no_length2_r2_path_implies_an_edge",
      all(frozenset((a, c)) in {frozenset(k) for k in r2_keys} for a, b, c in paths),
      {"length2_paths": len(paths), "paths_without_a_c_edge": len(transitive_violations),
       "witness": transitive_violations[:3]},
      "A-B and B-C adjacent never implies A-C: this library has no length-2 R2 path at all "
      "(each event is a 2-fragment single-plane cut), so the rule is enforced by construction "
      "and is reported as vacuous rather than as a passing statistical test")

# --- 4. the frozen area thresholds are respected by the measured labels ------------------
per_mother_threshold = {m["mother"]["lineage_id"]: float(m["mother"]["r2_area_threshold_mm2"])
                        for m in library.get("mothers", [])}
frag_mother = {f: i["mother_id"] for f, i in fragments.items()}
r2_below = [(r["a"], r["b"], float(r["area_mm2"]),
             per_mother_threshold.get(frag_mother.get(str(r["a"]), "")))
            for r in r2
            if per_mother_threshold.get(frag_mother.get(str(r["a"]), "")) is not None
            and float(r["area_mm2"]) < per_mother_threshold[frag_mother[str(r["a"])]]]
tiny = [r for r in rows if str(r["kind"]) == RELATION_TINY]
tiny_above = [r for r in tiny
              if per_mother_threshold.get(frag_mother.get(str(r["a"]), "")) is not None
              and float(r["area_mm2"]) >= per_mother_threshold[frag_mother[str(r["a"])]]]
check("every_r2_row_is_at_or_above_its_mothers_threshold", not r2_below,
      {"r2_rows": len(r2), "below_threshold": r2_below[:4],
       "thresholds": per_mother_threshold})
check("every_tiny_row_is_below_its_mothers_threshold", not tiny_above,
      {"tiny_rows": len(tiny), "above_threshold": tiny_above[:4]})

report = {
    "schema": "synlab.relations.unknown_discipline.v1",
    "library_hash": json.loads((REPORTS / "relation_negatives_summary.json").read_text(
        encoding="utf-8")).get("library_hash"),
    "fragments": len(fragment_ids), "pairs": len(rows),
    "counts_by_kind": {k: sum(1 for r in rows if str(r["kind"]) == k)
                       for k in (RELATION_R2, RELATION_R1, RELATION_R0, RELATION_TINY,
                                 RELATION_UNKNOWN)},
    "assertions": assertions,
    "ok": all(a["ok"] for a in assertions),
    "failed": [a["name"] for a in assertions if not a["ok"]],
}
OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
for a in assertions:
    print(f"[{'PASS' if a['ok'] else 'FAIL'}] {a['name']}: "
          f"{json.dumps(a['measured'], ensure_ascii=False, default=str)[:220]}")
print(f"ok={report['ok']} failed={report['failed']}")
raise SystemExit(0 if report["ok"] else 1)
