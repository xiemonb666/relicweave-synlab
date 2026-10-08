"""precision audit probe 00 - read-only inventory of available evidence.

Enumerates every store that can hold observation / geometry evidence and reports
the role histogram so the audit knows which snapshot to quote.  READ ONLY.
"""
from __future__ import annotations

import json
import pathlib
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]

CANDIDATES = [
    "data/a12/metadata.sqlite",
    "data/a12_final/store/metadata.sqlite",
    "data/a12_campaign/store/metadata.sqlite",
    "data/a12_campaign/store_control/metadata.sqlite",
    "data/a12_realistic/metadata.sqlite",
    "data/a12_realistic/control_ideal/metadata.sqlite",
    "data/a12_verify/store/metadata.sqlite",
    "data/a12_exports/closed_loop/store/metadata.sqlite",
    "data/a12_demo/store/metadata.sqlite",
    "data/a12_diversity/store/metadata.sqlite",
    "data/a12_trainable/store/metadata.sqlite",
]

INTERESTING = (
    "obs_result", "obs_view", "obs_fused_geometry", "feature_bundle", "label_bundle",
    "clean_truth", "physical_truth", "visible_labels", "fragment_mesh", "mother_mesh",
    "physical_component", "physical_result", "degrade_measurement", "display_lod_glb",
    "episode_trace", "mvs_result", "context_pack",
)


def main() -> int:
    out = {}
    for rel in CANDIDATES:
        path = ROOT / rel
        rec = {"exists": path.exists()}
        if not path.exists():
            out[rel] = rec
            continue
        rec["bytes"] = path.stat().st_size
        try:
            con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
            cur = con.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            rec["tables"] = sorted(r[0] for r in cur.fetchall())
            try:
                cur.execute("SELECT role, COUNT(*) FROM assets GROUP BY role ORDER BY 2 DESC")
                hist = {r[0]: int(r[1]) for r in cur.fetchall()}
                rec["roles_total"] = sum(hist.values())
                rec["roles"] = {k: v for k, v in hist.items() if k in INTERESTING}
                rec["roles_other"] = {k: v for k, v in hist.items() if k not in INTERESTING}
            except sqlite3.Error as exc:  # pragma: no cover - defensive
                rec["assets_error"] = str(exc)
            con.close()
        except sqlite3.Error as exc:  # pragma: no cover - defensive
            rec["sqlite_error"] = str(exc)
        out[rel] = rec
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
