"""A08 evidence producer: hand-known relation fixtures from plan 11.1.

Builds the analytic 2/3/4-block events and every negative fixture through the real
``synlab.truth`` pipeline and records the observed relation kind/area per pair against the
hand-computed expectation.  The report is what the acceptance item ``A08`` reads as
``truth_fixture.json``.

Run:  .venv\\Scripts\\python.exe tests\\a12\\qc\\run_truth_fixture.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
TESTS_A12 = Path(__file__).resolve().parents[1]
for _path in (str(REPO_ROOT), str(TESTS_A12), str(TESTS_A12 / "truth")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from synlab.schemas.runtime import (  # noqa: E402
    RELATION_R1,
    RELATION_R2,
    RELATION_TINY,
    RELATION_UNKNOWN,
)
from synlab.truth.api import finalize_clean_truth, relation_audit  # noqa: E402

from truth_fixtures import (  # noqa: E402
    ambiguous_event,
    assembly_contact_event,
    cavity_adjacency_event,
    four_block_event,
    point_contact_event,
    three_block_event,
    two_block_event,
)

OUT = REPO_ROOT / "data" / "a12" / "reports" / "truth_fixture.json"


def _pair(clean, a: str, b: str):
    key = (a, b) if a <= b else (b, a)
    return clean.relations[key]


def _case_two_block() -> dict[str, Any]:
    mother, event = two_block_event()
    clean = finalize_clean_truth(mother, event)
    edge = _pair(clean, "A", "B")
    checks = {
        "one_relation": len(clean.relations) == 1,
        "kind_is_r2": edge.kind == RELATION_R2,
        "hand_area_400mm2": abs(float(edge.area_mm2) - 400.0) <= 1e-6,
        "loss_mask_and_valid": bool(edge.loss_mask) and bool(edge.valid),
        "interface_id_0": int(edge.interface_id) == 0,
        "clean_qa_pass": bool(clean.qa.get("pass")),
        "relation_audit_pass": bool(relation_audit(clean)["pass"]),
    }
    return {"fixture": "two_block_event", "expected": "A-B is exactly one R2 of 400 mm2",
            "observed": {"kind": edge.kind, "area_mm2": float(edge.area_mm2),
                         "relations": len(clean.relations)},
            "checks": checks, "ok": all(checks.values())}


def _case_three_block() -> dict[str, Any]:
    mother, event = three_block_event()
    clean = finalize_clean_truth(mother, event)
    ab, bc, ac = _pair(clean, "A", "B"), _pair(clean, "B", "C"), _pair(clean, "A", "C")
    checks = {
        "A_B_is_r2": ab.kind == RELATION_R2,
        "B_C_is_r2": bc.kind == RELATION_R2,
        "A_C_is_r1_not_r2": ac.kind == RELATION_R1,
        "A_C_area_zero": float(ac.area_mm2) == 0.0,
        "A_C_no_loss_mask": ac.loss_mask is False,
        "r2_not_transitive": relation_audit(clean)["transitively_closed"] is False,
        "qa_r2_pairs_2": int(clean.qa.get("r2_pairs", -1)) == 2,
        "qa_r1_pairs_1": int(clean.qa.get("r1_pairs", -1)) == 1,
    }
    return {"fixture": "three_block_event", "expected": "chain A-B-C: two R2, A-C stays R1",
            "observed": {"A_B": ab.kind, "B_C": bc.kind, "A_C": ac.kind},
            "checks": checks, "ok": all(checks.values())}


def _case_four_block() -> dict[str, Any]:
    mother, event = four_block_event()
    clean = finalize_clean_truth(mother, event)
    expected_r2 = {("A", "B"), ("C", "D"), ("A", "C"), ("B", "D")}
    expected_r1 = {("A", "D"), ("B", "C")}
    got_r2 = {pair for pair, edge in clean.relations.items() if edge.kind == RELATION_R2}
    got_r1 = {pair for pair, edge in clean.relations.items() if edge.kind == RELATION_R1}
    areas_ok = all(abs(float(clean.relations[pair].area_mm2) - 400.0) <= 1e-6 for pair in expected_r2)
    symmetric = all(clean.relations[a <= b and (a, b) or (b, a)] is edge
                    for (a, b), edge in clean.relations.items())
    checks = {
        "r2_set_matches_hand_computation": got_r2 == expected_r2,
        "r1_set_matches_hand_computation": got_r1 == expected_r1,
        "six_pairs": len(clean.relations) == 6,
        "all_r2_areas_400mm2": areas_ok,
        "symmetric_keys": symmetric,
        "relation_audit_pass": bool(relation_audit(clean)["pass"]),
    }
    return {"fixture": "four_block_event",
            "expected": "4 R2 (A-B, C-D, A-C, B-D) and 2 R1 (A-D, B-C)",
            "observed": {"r2": sorted(got_r2), "r1": sorted(got_r1)},
            "checks": checks, "ok": all(checks.values())}


def _case_cavity() -> dict[str, Any]:
    mother, event = cavity_adjacency_event()
    clean = finalize_clean_truth(mother, event)
    edge = _pair(clean, "A", "B")
    evidence = clean.meta["patch_evidence"]["0"]
    fraction = evidence.get("material_inside_fraction")
    checks = {
        "kind_unknown": edge.kind == RELATION_UNKNOWN,
        "no_loss_mask": edge.loss_mask is False,
        "not_valid": edge.valid is False,
        "reason_names_cavity_or_outside": ("cavity" in str(edge.reason)
                                           or "outside_material" in str(edge.reason)),
        "material_inside_fraction_measured": fraction is not None,
        "material_inside_fraction_below_0.9": (fraction is not None and float(fraction) < 0.9),
    }
    return {"fixture": "cavity_adjacency_event",
            "expected": "identical cavity walls are never R2 (never a new fracture surface)",
            "observed": {"kind": edge.kind, "reason": edge.reason,
                         "material_inside_fraction": fraction},
            "checks": checks, "ok": all(checks.values())}


def _case_assembly() -> dict[str, Any]:
    mother, event = assembly_contact_event()
    clean = finalize_clean_truth(mother, event)
    edge = _pair(clean, "A", "B")
    checks = {
        "kind_r1": edge.kind == RELATION_R1,
        "area_zero": float(edge.area_mm2) == 0.0,
        "reason_is_not_a_new_fracture": "not_a_new_fracture_surface" in str(edge.reason),
    }
    return {"fixture": "assembly_contact_event",
            "expected": "original assembly contact never becomes R2",
            "observed": {"kind": edge.kind, "area_mm2": float(edge.area_mm2),
                         "reason": edge.reason},
            "checks": checks, "ok": all(checks.values())}


def _case_point_contact() -> dict[str, Any]:
    mother, event = point_contact_event()
    clean = finalize_clean_truth(mother, event)
    edge = _pair(clean, "A", "B")
    checks = {
        "kind_tiny": edge.kind == RELATION_TINY,
        "hand_area_0.02mm2": abs(float(edge.area_mm2) - 0.02) <= 1e-9,
        "grey_zone_not_a_negative": edge.loss_mask is False,
    }
    return {"fixture": "point_contact_event",
            "expected": "point contact is TINY with measured area and no loss mask",
            "observed": {"kind": edge.kind, "area_mm2": float(edge.area_mm2)},
            "checks": checks, "ok": all(checks.values())}


def _case_ambiguous() -> dict[str, Any]:
    mother, event = ambiguous_event()
    clean = finalize_clean_truth(mother, event)
    edge = _pair(clean, "A", "B")
    checks = {
        "kind_unknown": edge.kind == RELATION_UNKNOWN,
        "no_loss_mask": edge.loss_mask is False,
        "reason_present": bool(edge.reason),
    }
    return {"fixture": "ambiguous_event",
            "expected": "ambiguous patch stays UNKNOWN and carries no loss mask",
            "observed": {"kind": edge.kind, "reason": edge.reason},
            "checks": checks, "ok": all(checks.values())}


CASES = (_case_two_block, _case_three_block, _case_four_block, _case_cavity,
         _case_assembly, _case_point_contact, _case_ambiguous)


def main() -> int:
    from synlab.storage.store import AssetStore

    results = [case() for case in CASES]
    ok = all(bool(case["ok"]) for case in results)
    report = {
        "ok": bool(ok),
        "status": "PASS" if ok else "FAIL",
        "check": "A08 truth relations on hand-known fixtures (plan 11.1)",
        "source": "tests/a12/truth/truth_fixtures.py via synlab.truth.api.finalize_clean_truth",
        "units": {"area_mm2": "mm^2"},
        "metrics": {
            "fixtures": len(results),
            "fixtures_ok": sum(1 for case in results if case["ok"]),
            "failed": [case["fixture"] for case in results if not case["ok"]],
            "hand_computed_cases": ["two_block", "three_block", "four_block"],
            "negative_cases": ["cavity_adjacency", "assembly_contact", "point_contact",
                               "ambiguous"],
            "cases": {case["fixture"]: {"ok": case["ok"], "checks": case["checks"],
                                        "observed": case["observed"],
                                        "expected": case["expected"]} for case in results},
        },
        "evidence": ["tests/a12/qc/run_truth_fixture.py",
                     "tests/a12/truth/truth_fixtures.py"],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, default=str),
                   encoding="utf-8")
    store = AssetStore(str(REPO_ROOT / "data" / "a12"))
    del store
    print(json.dumps({"ok": ok, "fixtures": len(results),
                      "fixtures_ok": report["metrics"]["fixtures_ok"],
                      "failed": report["metrics"]["failed"], "report": str(OUT)},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
