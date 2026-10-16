"""Classify the measured event library and write the real relation-negative summary.

Reads the per-mother records assembled by ``neg_run_library.py assemble``, re-derives every
fragment-pair verdict with ``synlab.relations.multi_event.classify_library`` and writes

    data/a12/reports/relation_negatives_summary.json    per-class real counts, event counts,
                                                        relation-graph spectrum, exclusion
                                                        verification, grey-zone attempt ledger
    data/a12/reports/relation_negatives_rows.json       every labelled pair (traceable)
    data/a12/reports/relation_negatives_library.json    the measured library itself

Nothing is filled in: a class with no measured member is reported as 0 together with the
measured reason it is empty (see ``grey_zone`` and ``r1_sources``).
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from synlab.relations.multi_event import (  # noqa: E402
    ROLE_UNRESOLVED, classify_library, library_fragments, library_hash, relation_histogram,
    verify_event_exclusion,
)
from synlab.schemas.runtime import (  # noqa: E402
    RELATION_R0, RELATION_R1, RELATION_R2, RELATION_TINY, RELATION_UNKNOWN,
)

BASE = REPO / "data" / "a12" / "reports" / "relation_negatives"
WORK = BASE / "work"
REPORTS = REPO / "data" / "a12" / "reports"


def load_library() -> dict:
    plan = json.loads((BASE / "library_plan.json").read_text(encoding="utf-8"))
    mothers = []
    for path in sorted(WORK.glob("mother_*.json")):
        mothers.append(json.loads(path.read_text(encoding="utf-8")))
    library = {"schema": "synlab.relations.event_library.v1",
               "version": "relations.multi_event.v1", "master_seed": plan["master_seed"],
               "plan": plan, "mothers": mothers}
    library["exclusion"] = verify_event_exclusion(library)
    usable = [e for m in mothers for e in m.get("events", []) if e.get("ok")]
    library["ok"] = bool(mothers) and all(m.get("ok") for m in mothers) and library["exclusion"]["ok"]
    library["events_ok"] = len(usable)
    return library


def spectrum(rows: list[dict], fragment_ids: list[str]) -> dict:
    """Relation-graph spectrum of the measured R2 adjacency (the only real adjacency).

    ``A[i, j] = 1`` iff the pair shares a measured new fracture surface above the R2 threshold.
    The reported coefficients are the adjacency eigenvalues (real, symmetric), the connected
    components (union-find, and independently the multiplicity of the zero eigenvalue), the
    degree sequence, and the L0 sparsity.  A graph that is a disjoint union of single edges --
    which is what a single-plane cut per event must produce -- has ``lambda_1 = 1``,
    ``components = n - edges`` and every eigenvalue in ``{-1, 0, +1}``.
    """
    index = {fid: i for i, fid in enumerate(fragment_ids)}
    n = len(fragment_ids)
    adjacency = np.zeros((n, n), dtype=np.float64)
    for row in rows:
        if str(row["kind"]) != RELATION_R2:
            continue
        adjacency[index[str(row["a"])], index[str(row["b"])]] = 1.0
        adjacency[index[str(row["b"])], index[str(row["a"])]] = 1.0
    eigenvalues = np.linalg.eigvalsh(adjacency) if n else np.zeros(0)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    edges = int(adjacency.sum() // 2)
    for i in range(n):
        for j in range(i + 1, n):
            if adjacency[i, j]:
                ra, rb = find(i), find(j)
                if ra != rb:
                    parent[ra] = rb
    components = len({find(i) for i in range(n)}) if n else 0
    degrees = adjacency.sum(axis=1).astype(int)
    return {
        "nodes": n, "r2_edges": edges,
        "eigenvalues_sorted": [float(v) for v in eigenvalues],
        "lambda_max": (float(eigenvalues.max()) if n else None),
        "lambda_min": (float(eigenvalues.min()) if n else None),
        "spectral_radius": (float(np.abs(eigenvalues).max()) if n else None),
        "trace": (float(eigenvalues.sum()) if n else 0.0),
        "frobenius_norm_squared": float((adjacency ** 2).sum()),
        "zero_eigenvalue_multiplicity": int(np.sum(np.abs(eigenvalues) < 1e-9)),
        "connected_components_union_find": components,
        "degree_sequence": sorted(int(d) for d in degrees),
        "degree_histogram": {str(k): int(v) for k, v in sorted(Counter(int(d) for d in degrees).items())},
        "self_loops": int(np.trace(adjacency)),
        "symmetric": bool(np.array_equal(adjacency, adjacency.T)),
        "note": ("spectrum of the measured R2 adjacency; R1/R0/UNKNOWN are non-adjacency "
                 "labels and are deliberately not part of A"),
    }


def grey_zone_ledger(library: dict) -> dict:
    attempts, satisfied = [], 0
    for mother in library["mothers"]:
        for event in mother.get("events", []):
            role = str((event.get("plan") or {}).get("role", ""))
            if role != "grey_zone":
                continue
            if event.get("role_satisfied"):
                satisfied += 1
            for attempt in event.get("attempts", []):
                attempts.append({"lineage_id": mother["mother"]["lineage_id"],
                                 "event_id": (event.get("plan") or {}).get("event_id"),
                                 "attempt": attempt.get("attempt"), "kind": attempt.get("kind"),
                                 "target_area_mm2": attempt.get("target_area_mm2"),
                                 "dialed_section_area_mm2": attempt.get("dialed_section_area_mm2"),
                                 "ok": bool(attempt.get("ok")), "error": attempt.get("error"),
                                 "seconds": attempt.get("seconds")})
    errors = Counter(str(a["error"]).split(":")[-1].strip()[:80] for a in attempts
                     if not a["ok"])
    return {"events_with_role_grey_zone": sum(
        1 for m in library["mothers"] for e in m.get("events", [])
        if str((e.get("plan") or {}).get("role", "")) == "grey_zone"),
        "events_satisfying_the_grey_zone_role": satisfied,
        "attempts": len(attempts), "attempts_ok": sum(1 for a in attempts if a["ok"]),
        "attempts_failed": sum(1 for a in attempts if not a["ok"]),
        "error_histogram": {k: v for k, v in errors.most_common()},
        "ledger": attempts}


def main() -> int:
    library = load_library()
    rows = classify_library(library)
    histogram = relation_histogram(rows)
    fragments = library_fragments(library)
    fragment_ids = sorted(fragments)
    events = [e for m in library["mothers"] for e in m.get("events", [])]
    ok_events = [e for e in events if e.get("ok")]

    r1 = [r for r in rows if r["kind"] == RELATION_R1]
    unknown = [r for r in rows if r["kind"] == RELATION_UNKNOWN]
    negatives = [r for r in rows if r["kind"] in (RELATION_R0, RELATION_R1)
                 and r.get("valid") and r.get("loss_mask")]
    summary = {
        "schema": "synlab.relations.negatives_summary.v1",
        "generated_at": time.time(),
        "library_hash": library_hash(library),
        "ok": bool(library.get("ok")),
        "master_seed": library["master_seed"],
        "mothers": len(library["mothers"]),
        "mothers_ok": sum(1 for m in library["mothers"] if m.get("ok")),
        "events_planned": len(library["plan"]["events"]),
        "events_run_ok": len(ok_events),
        "events_per_mother": library["plan"]["events_per_mother"],
        "event_roles": {str(r): c for r, c in Counter(
            str((e.get("plan") or {}).get("role", "")) for e in ok_events).items()},
        "event_ids": [str(e["event_id"]) for e in ok_events],
        "fragments": len(fragment_ids),
        "unordered_pairs": len(rows),
        "counts_by_kind": histogram,
        "counts_by_kind_recomputed": {k: sum(1 for r in rows if r["kind"] == k)
                                      for k in (RELATION_R2, RELATION_R1, RELATION_R0,
                                                RELATION_TINY, RELATION_UNKNOWN)},
        "negative_eligible_rows": len(negatives),
        "r1_sources": {str(d): c for d, c in Counter(str(r["decidability"]) for r in r1).items()},
        "r1_within_event": sum(1 for r in r1 if r["decidability"] == "within_event"),
        "r1_cross_event": sum(1 for r in r1 if r["decidability"] == "mutually_exclusive_event"),
        "unknown_reasons": {str(k): c for k, c in Counter(
            str(r["reason"]) for r in unknown).items()},
        "unknown_loss_mask_true": sum(1 for r in unknown if r.get("loss_mask")),
        "unknown_valid_true": sum(1 for r in unknown if r.get("valid")),
        "measured_areas_mm2": {
            RELATION_R2: sorted({round(float(r["area_mm2"]), 6) for r in rows
                                 if r["kind"] == RELATION_R2}),
            RELATION_TINY: sorted({round(float(r["area_mm2"]), 6) for r in rows
                                   if r["kind"] == RELATION_TINY})},
        "event_pairs_checked_by_exclusion": library["exclusion"]["event_pairs_checked"],
        "exclusion": library["exclusion"],
        "grey_zone": grey_zone_ledger(library),
        "relation_graph_spectrum": spectrum(rows, fragment_ids),
        "unresolved_events": [str(e["event_id"]) for e in ok_events
                              if str((e.get("plan") or {}).get("role")) == ROLE_UNRESOLVED],
        "per_mother": [{"lineage_id": m["mother"]["lineage_id"],
                        "split": m["mother"]["split"],
                        "events_ok": m.get("events_ok"),
                        "r2_area_threshold_mm2": m["mother"].get("r2_area_threshold_mm2"),
                        "tiny_area_threshold_mm2": m["mother"].get("tiny_area_threshold_mm2"),
                        "fragments": sorted(f for f, i in fragments.items()
                                            if i["mother_id"] == m["mother"]["lineage_id"])}
                       for m in library["mothers"]],
        "citations": {
            "plan_2_4_r1": "R1 = 同一母体且无直接共享断面 (docs/a12/v144_data_requirements.md:230)",
            "plan_2_4_hard_constraint": ("来自同母体不同替代碎裂事件的碎片不混放进一次候选库"
                                         " (docs/a12/v144_data_requirements.md:239) -- the "
                                         "cross-event R1 rows below are exactly such pairs and "
                                         "must NOT be co-enrolled in one candidate pool as-is"),
            "plan_2_5_r1_source": ("R1 难例生成方式 = 同母体非邻片 "
                                   "(docs/a12/v144_data_requirements.md:251)"),
            "plan_2_4_unknown": ("UNKNOWN 退出监督分母、UNKNOWN 不转负例 "
                                 "(docs/a12/v144_data_requirements.md:233)"),
            "plan_2_4_grey": ("真实微小接触单独标记 TINY_CONTACT，不悄悄改成 R1；保留原始面积、"
                              "阈值和灰区记录 (docs/a12/v144_data_requirements.md:232)"),
        },
    }
    (REPORTS / "relation_negatives_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (REPORTS / "relation_negatives_rows.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (REPORTS / "relation_negatives_library.json").write_text(
        json.dumps(library, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items()
                      if k not in ("exclusion", "grey_zone", "relation_graph_spectrum",
                                   "citations", "per_mother", "event_ids",
                                   "measured_areas_mm2")}, ensure_ascii=False, indent=2,
                     default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
