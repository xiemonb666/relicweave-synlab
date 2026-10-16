"""Archive the §14 evidence into the repository's report directory (one-off, idempotent).

Copies the run_id-coverage measurements, the freeze logs and the integration-test logs into
``data/a12/reports/`` (UTF-8), so the document's numbers can be re-read without the scratch
stores, and writes a compact key-field extract of both frozen manifests.

Usage:  & .venv\\Scripts\\python.exe data\\a12_exports\\archive_evidence.py
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "data" / "a12" / "reports"
FIX = ROOT / "data" / "a12_exports" / "runid_fix"
CL = ROOT / "data" / "a12_exports" / "closed_loop"
CLF = ROOT / "data" / "a12_exports" / "cl_fresh"

#: (source, archived name)
COPIES: tuple[tuple[Path, str], ...] = (
    (FIX / "before.json", "runid_fix_before.json"),
    (FIX / "after.json", "runid_fix_after.json"),
    (FIX / "runid_fix_comparison.json", "runid_fix_comparison.json"),
    (ROOT / "data" / "a12_exports" / "runid_fix_before.txt", "runid_fix_before.txt"),
    (ROOT / "data" / "a12_exports" / "runid_fix_after.txt", "runid_fix_after.txt"),
    (ROOT / "data" / "a12_exports" / "closed_loop_release_freeze.txt",
     "closed_loop_freeze_after_runid_fix.txt"),
    (ROOT / "data" / "a12_exports" / "closed_loop_release_freeze_exit.txt",
     "closed_loop_freeze_after_runid_fix_exit.txt"),
    (ROOT / "data" / "a12_exports" / "cl_fresh_generate.txt",
     "closed_loop_fresh_generate_after_runid_fix.txt"),
    (ROOT / "data" / "a12_exports" / "cl_fresh_audit.txt",
     "closed_loop_fresh_audit_after_runid_fix.txt"),
    (ROOT / "data" / "a12_exports" / "cl_fresh_freeze2.txt",
     "closed_loop_fresh_freeze_after_runid_fix.txt"),
    (ROOT / "data" / "a12_exports" / "cl_fresh_freeze2_exit.txt",
     "closed_loop_fresh_freeze_after_runid_fix_exit.txt"),
    (ROOT / "data" / "a12_exports" / "pytest_integration_after_runid_fix.txt",
     "pytest_integration_after_runid_fix.txt"),
    (ROOT / "data" / "a12_exports" / "pytest_integration_after_runid_fix_exit.txt",
     "pytest_integration_after_runid_fix_exit.txt"),
    (ROOT / "data" / "a12_exports" / "pytest_integration_collected.txt",
     "pytest_integration_collected_after_runid_fix.txt"),
    (ROOT / "data" / "a12_exports" / "pytest_integration_after_runid_fix.xml",
     "pytest_integration_after_runid_fix.xml"),
    (ROOT / "data" / "a12_exports" / "pytest_integration_after_runid_fix_run2.txt",
     "pytest_integration_after_runid_fix_run2.txt"),
    (ROOT / "data" / "a12_exports" / "pytest_integration_after_runid_fix_run2_exit.txt",
     "pytest_integration_after_runid_fix_run2_exit.txt"),
    (ROOT / "data" / "a12_exports" / "list_releases.txt",
     "release_manifests_after_runid_fix.txt"),
    (ROOT / "data" / "a12_exports" / "pytest_units_touched_modules.xml",
     "pytest_units_touched_modules.xml"),
    (ROOT / "data" / "a12_exports" / "pytest_units_touched_modules.txt",
     "pytest_units_touched_modules.txt"),
    (ROOT / "data" / "a12_exports" / "pytest_units_touched_modules_exit.txt",
     "pytest_units_touched_modules_exit.txt"),
    (ROOT / "data" / "a12_exports" / "census_fresh_store.txt",
     "census_fresh_store_after_runid_fix.txt"),
)

#: The two releases frozen by the fixed ``release_freeze`` step (one per store).
MANIFESTS: dict[str, Path] = {
    "closed_loop_store": CL / "store" / "releases" / "rel_852ab2a1e4c3_1790909619" / "manifest.json",
    "fresh_store": CLF / "store" / "releases" / "rel_9a5c5a39a8ad_1790909613" / "manifest.json",
}


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def main() -> int:
    REPORTS.mkdir(parents=True, exist_ok=True)
    for source, name in COPIES:
        if not source.exists():
            print("MISSING", source)
            continue
        target = REPORTS / name
        target.write_text(_read_text(source), encoding="utf-8")
        print(f"archived {name}  ({source.stat().st_size} B)")
    extract: dict[str, object] = {"schema": "synlab.runid_fix_manifests.v1", "releases": {}}
    for label, path in MANIFESTS.items():
        if not path.exists():
            print("MISSING manifest", path)
            continue
        manifest = json.loads(path.read_text(encoding="utf-8"))
        coverage = manifest["coverage"]
        extract["releases"][label] = {
            "manifest_path": str(path.relative_to(ROOT)),
            "release_id": manifest["release_id"],
            "profile": manifest["profile"],
            "manifest_hash": manifest["manifest_hash"],
            "assets": len(manifest["assets"]),
            "gates": manifest["gates"],
            "required_gates": manifest["required_gates"],
            "scope_completed": manifest["scope_completed"],
            "scope_pending": manifest["scope_pending"],
            "gate_overrides": manifest["extra"]["gate_overrides"],
            "refused_gate_overrides": manifest["extra"]["refused_gate_overrides"],
            "closure": manifest["closure"],
            "coverage": {k: v for k, v in coverage.items() if k != "mother_ids"},
            "relation_status": manifest["extra"]["relation_status"],
            "visibility_status": manifest["extra"]["visibility_status"],
            "excluded_role_reasons": manifest["extra"]["excluded_role_reasons"],
            "scope_declaration": manifest["extra"]["scope_declaration"],
        }
        print(f"extracted manifest key fields: {label} ({manifest['release_id']})")
    out = REPORTS / "runid_fix_manifests.json"
    out.write_text(json.dumps(extract, ensure_ascii=False, indent=2, sort_keys=True),
                   encoding="utf-8")
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
