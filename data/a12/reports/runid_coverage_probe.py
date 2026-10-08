"""Measure ``meta.run_id`` coverage + the real gate verdicts of one minimal generation run.

This is the probe that produced the evidence quoted in ``docs/a12/closed_loop.md`` §14.1.  It was
executed from the repository root; it lives here (``data/a12/reports/``) so the artefact and its
script stay together.

Usage::

    & .venv\\Scripts\\python.exe data\\a12\\reports\\runid_coverage_probe.py before
    & .venv\\Scripts\\python.exe data\\a12\\reports\\runid_coverage_probe.py after

It generates exactly one mother with ``configs/a12/closed_loop.yaml`` into a private store
(``data/a12_exports/runid_fix/<tag>_store``) and then, using ONLY read-only queries, records:

* how many assets of each role carry ``meta.run_id == <this run>`` (the defect: the truth layers,
  the observation and the pattern assets used to carry none);
* the full ``qc.gates.evaluate_gates`` verdict map plus the required gates of the run profile.

Nothing is tagged, promoted or overridden here: the numbers are the pipeline's own output.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

#: ``<repo>/data/a12/reports/`` -> find the repository root by its own markers.
def _repo_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / "pyproject.toml").exists() and (candidate / "synlab").is_dir():
            return candidate
    raise SystemExit(f"repository root not found above {start}")


ROOT = _repo_root(Path(__file__).resolve().parent)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from synlab.config import load_generation_spec  # noqa: E402
from synlab.pipeline import run_generation  # noqa: E402
from synlab.qc import gates as gates_mod  # noqa: E402
from synlab.storage.release import PROFILE_GATES  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402

CONFIG = ROOT / "configs" / "a12" / "closed_loop.yaml"
OUT = ROOT / "data" / "a12_exports" / "runid_fix"
#: Files whose content decides the measurement; hashed before and after the run so the
#: measurement can be attributed to an exact revision (several agents edit this checkout).
WATCHED = ("synlab/pipeline.py", "synlab/truth/api.py", "synlab/observe/api.py",
           "synlab/patterns/commit.py", "synlab/qc/gates.py")


def _hashes() -> dict[str, str]:
    import hashlib

    out: dict[str, str] = {}
    for name in WATCHED:
        path = ROOT / name
        out[name] = hashlib.sha256(path.read_bytes()).hexdigest()[:16] if path.exists() else "MISSING"
    return out


def main() -> int:
    tag = sys.argv[1] if len(sys.argv) > 1 else "after"
    store_root = OUT / f"{tag}_store"
    OUT.mkdir(parents=True, exist_ok=True)
    code_before = _hashes()

    spec = load_generation_spec(CONFIG)
    spec.storage.root = str(store_root)
    started = time.time()
    report = run_generation(spec, store_root=store_root, max_mothers=1)
    run_id = report["run_id"]
    store = AssetStore(store_root)
    elapsed = time.time() - started

    # --- read-only per-role run_id census ------------------------------------------------
    census: dict[str, dict[str, int]] = {}
    with store.connect() as conn:
        rows = conn.execute("SELECT role, meta_json FROM assets").fetchall()
        for row in rows:
            meta = json.loads(row["meta_json"] or "{}")
            bucket = census.setdefault(row["role"], {"total": 0, "with_run_id": 0,
                                                     "other_run_id": 0, "no_run_id": 0})
            bucket["total"] += 1
            value = meta.get("run_id")
            if value == run_id:
                bucket["with_run_id"] += 1
            elif value is None:
                bucket["no_run_id"] += 1
            else:
                bucket["other_run_id"] += 1

    # --- real gate verdicts (no tagging, no promotion, no override) ----------------------
    gates, gate_asset_ids, profile = gates_mod.evaluate_gates(store, run_id)
    required = PROFILE_GATES.get(profile, [])
    payload = {
        "tag": tag,
        "phase": "BEFORE the run_id fix" if tag == "before" else "AFTER the run_id fix",
        "store_root": str(store_root),
        "run_id": run_id,
        "seconds": round(elapsed, 1),
        "code_hashes_before": code_before,
        "code_hashes_after": _hashes(),
        "generation": {k: report.get(k) for k in ("planned", "attempted", "accepted", "failed")},
        "profile": profile,
        "required_gates": required,
        "required_pass": [g for g in required if gates.get(g) == "PASS"],
        "required_pending": [g for g in required if gates.get(g) != "PASS"],
        "gates": gates,
        "gate_asset_ids": len(gate_asset_ids),
        "role_run_id_census": census,
    }
    (OUT / f"{tag}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    print(f"[{tag}] run_id={run_id} accepted={report.get('accepted')}/{report.get('attempted')} "
          f"profile={profile} in {elapsed:.1f}s")
    print("code hashes:", json.dumps(payload["code_hashes_before"]))
    print("code hashes after:", json.dumps(payload["code_hashes_after"]))
    print("role                     total  run_id  none  other")
    for role in sorted(census):
        row = census[role]
        print(f"{role:<24} {row['total']:>5} {row['with_run_id']:>7} {row['no_run_id']:>5} "
              f"{row['other_run_id']:>5}")
    print("required gates:")
    for gate in required:
        print(f"    {gate:<28} {gates.get(gate)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
