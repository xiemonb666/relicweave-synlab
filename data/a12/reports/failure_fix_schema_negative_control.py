"""Negative control for failure class 1: the four real cross-vessel rows of the batch ledger.

``data/a12/reports/next_experiment_batches.json`` recorded four ``MOTHER_INVALID`` mothers whose
parameter dictionary belonged to another vessel.  Each case is replayed here against the fixed
code and must (a) be *reported* by the deterministic schema check and (b) still be refused by
``create_mother`` with the model's own ``extra_forbidden`` error - i.e. the fix removes the
cross-vessel *cause* without weakening ``extra="forbid"`` and without swallowing the error.

Usage::

    python data/a12/reports/failure_fix_schema_negative_control.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from synlab.errors import SynLabError  # noqa: E402
from synlab.mothers.api import canonical_params, create_mother, declared_fields, params_model_ok  # noqa: E402
from synlab.seeds import make_rng  # noqa: E402

OUT = ROOT / "data" / "a12" / "reports" / "failure_class1_negative_control.json"

#: (vessel the ledger built, foreign fields it received, ledger message fragment)
CASES = [
    ("V12", {"depth_ratio": 0.3463430657289447, "rim_flare": 0.32823968601938175}, "BasinParams"),
    ("V08", {"depth_mm": 68.29772066617953, "base_width_ratio": 0.6435624562265903}, "AmphoraParams"),
    ("V18", {"diameter_mm": 107.36068752328612, "wall_mm": 6.4654710696720095}, "BrickParams"),
    ("V07", {"with_handle": True, "handle_thickness_mm": 12.793730389137352}, "BottleParams"),
]


def main() -> int:
    report = {"cases": []}
    print(f"{'vessel':6s} {'foreign fields':44s} {'schema check':>13s}  create_mother")
    for vessel, foreign, model_name in CASES:
        declared = declared_fields(vessel)
        assert not (set(foreign) & set(declared)), (vessel, foreign)
        ok, why = params_model_ok(vessel, foreign)
        raised = None
        try:
            create_mother(vessel, "M01", dict(foreign), make_rng(20261001, "shape", vessel))
        except SynLabError as exc:
            raised = {"code": str(exc.code), "message": exc.message[:200]}
        valid, why_valid = params_model_ok(vessel, canonical_params(vessel, {}))
        row = {
            "vessel_id": vessel, "foreign_fields": sorted(foreign),
            "ledger_model": model_name,
            "declared_fields": sorted(declared),
            "schema_check_rejected": not ok,
            "schema_check_message": why[:200],
            "create_mother_error": raised,
            "own_params_validate": bool(valid),
            "own_params_message": why_valid[:120],
        }
        report["cases"].append(row)
        print(f"{vessel:6s} {','.join(sorted(foreign)):44s} {str(not ok):>13s}  "
              f"{(raised or {}).get('code')}")
    report["all_rejected_by_check"] = all(c["schema_check_rejected"] for c in report["cases"])
    report["all_refused_by_create_mother"] = all(
        (c["create_mother_error"] or {}).get("code") == "ErrorCode.MOTHER_INVALID"
        for c in report["cases"])
    report["all_own_params_valid"] = all(c["own_params_validate"] for c in report["cases"])
    report["note"] = ("the check is not vacuous: it rejects the exact dictionaries the ledger "
                      "recorded, while every vessel's own dictionary still validates")
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nrejected by check: {report['all_rejected_by_check']}; "
          f"refused by create_mother: {report['all_refused_by_create_mother']}; "
          f"own params valid: {report['all_own_params_valid']}")
    print(f"written {OUT.relative_to(ROOT)}")
    return 0 if all(report[key] for key in ("all_rejected_by_check",
                                            "all_refused_by_create_mother",
                                            "all_own_params_valid")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
