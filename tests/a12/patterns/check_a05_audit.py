"""Run ``audit_pattern`` for one family on the real audit mother (A05 fix verification)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "a12" / "patterns"))

from probe_a05_cut_continuity import build_family  # noqa: E402


def main() -> int:
    from synlab.patterns.audit import audit_pattern

    families = sys.argv[1:] or ["PAT07"]
    out: dict[str, object] = {}
    out_path = ROOT / "data" / "a12" / "reports" / "_a05_fix_check.json"
    for family in families:
        built = build_family(family)
        report = audit_pattern(built["recipe"], built["mother"], n_pairs=150, geometry_probe=True)
        inheritance = report.get("inheritance", {})
        cut = inheritance.get("cut_continuity", {})
        out[family] = {
            "pass": bool(report.get("pass")),
            "failures": report.get("failures"),
            "inheritance_pass": inheritance.get("pass"),
            "cut": {k: v for k, v in cut.items() if k != "detail"},
            "seam_max": report.get("seam", {}).get("chart_space", {}).get("max_abs_color_error"),
        }
        out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True),
                            encoding="utf-8")
        print(f"[{family}] pass={report.get('pass')} failures={report.get('failures')}")
        print(f"    cut: {json.dumps({k: v for k, v in cut.items() if k != 'detail'}, ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
