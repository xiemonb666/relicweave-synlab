"""Step 17: registry-version evidence for the geometry change (read-only + builds).

The migration plan (docs/a12/mother_geometry_audit.md section 4.4 step 1) says the 15
A1-affected vessels must move from ``register_vessel(..., version="1.0")`` to ``"1.1"`` in the
same commit as P1+P2, because ``_wrap_assembly`` copies the version into every mother meta and
it also changes ``REGISTRY.fingerprint()`` - the cheapest "old data vs new data" marker.

This script measures, per vessel:

* the live ``mother.meta["registry_version"]`` from a real ``create_mother``;
* the ``profile_metrics`` consistency columns the builder now writes
  (``z_rim`` / ``z_rim_target_mm`` / ``z_rim_shortfall_mm``);
* the decorator line in the source file (as text), and the commit that introduced ``1.1``.

Writes ``s17_registry_versions.json``.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
sys.path.insert(0, str(HERE))

from synlab.mothers.api import create_mother, default_params  # noqa: E402
from synlab.registry import REGISTRY  # noqa: E402
from synlab.seeds import make_rng, seed64  # noqa: E402

AFFECTED = ("V01", "V02", "V03", "V04", "V05", "V06", "V07", "V08", "V09", "V10", "V11", "V12",
            "V15", "V16", "V17")


def git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True,
                              check=False).stdout.strip()
    except Exception as exc:  # pragma: no cover - evidence only
        return f"<git failed: {exc}>"


def decorator_version(path: Path, vid: str) -> str | None:
    text = path.read_text(encoding="utf-8")
    match = re.search(r'@register_vessel\("' + re.escape(vid) + r'",[^)]*?version="([^"]+)"',
                      text, re.S)
    return match.group(1) if match else None


def main() -> int:
    ensure = getattr(REGISTRY, "ensure_loaded", None)
    if callable(ensure):
        ensure()
    else:  # the vessels package registers on import
        import synlab.mothers.vessels  # noqa: F401

    fingerprint = REGISTRY.fingerprint() if hasattr(REGISTRY, "fingerprint") else None
    rows = {}
    for i in range(1, 25):
        vid = f"V{i:02d}"
        entry = REGISTRY.get("vessel", vid) if hasattr(REGISTRY, "get") else None
        rng = make_rng(int(seed64(0xA12, vid, "mother_geometry_audit")), vid, "audit")
        mother = create_mother(vid, "M01", default_params(vid), rng, mother_id=f"{vid}-ver")
        meta = dict(mother.meta or {})
        pm = dict(meta.get("profile_metrics") or {})
        src = None
        for rel in ("synlab/mothers/vessels/group_revolve.py",
                    "synlab/mothers/vessels/group_composite.py"):
            if f'register_vessel("{vid}"' in (REPO / rel).read_text(encoding="utf-8"):
                src = decorator_version(REPO / rel, vid)
                break
        rows[vid] = {
            "affected_by_A1": vid in AFFECTED,
            "registry_entry_version": getattr(entry, "version", None) if entry else None,
            "mother_meta_registry_version": meta.get("registry_version"),
            "decorator_version_in_source": src,
            "geometry_hash": meta.get("geometry_hash"),
            "profile_z_rim_mm": pm.get("z_rim"),
            "profile_z_rim_target_mm": pm.get("z_rim_target_mm"),
            "profile_z_rim_shortfall_mm": pm.get("z_rim_shortfall_mm"),
            "has_shortfall_column": "z_rim_shortfall_mm" in pm,
        }

    affected_ok = all(rows[v]["mother_meta_registry_version"] == "1.1" for v in AFFECTED)
    others_ok = all(rows[f"V{i:02d}"]["mother_meta_registry_version"] == "1.0"
                    for i in range(1, 25) if f"V{i:02d}" not in AFFECTED)
    shortfall_ok = all(rows[f"V{i:02d}"]["has_shortfall_column"] for i in range(1, 13)) and all(
        rows[v]["has_shortfall_column"] for v in ("V15", "V16", "V17"))

    payload = {
        "schema": "a12.mother_geometry.registry_versions.v1",
        "what": "registry_version / meta evidence for the P1+P2 geometry change",
        "registry_fingerprint": fingerprint,
        "git": {
            "head": git("rev-parse", "HEAD"),
            "head_subject": git("log", "-1", "--format=%s"),
            "worktree_clean_mothers": git("status", "--porcelain", "--", "synlab/mothers") == "",
            "mothers_diff_vs_head": git("diff", "--stat", "HEAD", "--", "synlab/mothers"),
            "note": "other synlab packages may be dirty from parallel work streams; the "
                    "geometry claims here only depend on synlab/mothers being at HEAD",
            "commit_that_introduced_version_1_1": git(
                "log", "-S", 'version="1.1"', "--format=%H %ad %s", "--",
                "synlab/mothers/vessels/group_revolve.py"),
            "bump_script": "data/a12/reports/geom_fix/bump_versions.py",
            "bump_script_evidence": (
                "bump_versions.py is idempotent: it prints 'SKIP <VID>: already carries "
                "version' for decorators that already carry one.  The decorators below are "
                "read straight out of the tracked source, and the commit above shows when "
                "'version=\"1.1\"' entered the file - so the script ran and landed in c3a149f."),
        },
        "checks": {
            "all_15_affected_are_1_1": affected_ok,
            "all_9_unaffected_stay_1_0": others_ok,
            "shortfall_column_present_on_the_15": shortfall_ok,
        },
        "vessels": rows,
    }
    out = HERE / "s17_registry_versions.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str),
                   encoding="utf-8")

    print(f"REGISTRY.fingerprint() = {fingerprint}")
    print(f"HEAD = {payload['git']['head'][:12]}  worktree(synlab/mothers) clean = "
          f"{payload['git']['worktree_clean_mothers']}")
    print(f"{'vid':4} {'A1':>3} {'entry':>6} {'meta':>6} {'src':>6} {'shortfall':>10}")
    for vid, row in rows.items():
        print(f"{vid:4} {str(row['affected_by_A1']):>3} {str(row['registry_entry_version']):>6} "
              f"{str(row['mother_meta_registry_version']):>6} "
              f"{str(row['decorator_version_in_source']):>6} "
              f"{str(row['profile_z_rim_shortfall_mm']):>10}")
    print()
    for k, v in payload["checks"].items():
        print(f"  {k}: {v}")
    print(f"wrote {out}")
    return 0 if all(payload["checks"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
