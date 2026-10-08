"""Scratch runner: generate N lineages with degradation diversity into data/a12_degrade/store.

Not a deliverable.  Writes the run report to ``data/a12_reports/``.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from synlab.config import load_generation_spec  # noqa: E402
from synlab.degrade.diversity import directory_bytes  # noqa: E402
from synlab.pipeline import run_generation  # noqa: E402

STORE = ROOT / "data" / "a12_degrade" / "store"
SPEC = ROOT / "configs" / "a12" / "sandbox.yaml"
REPORTS = ROOT / "data" / "a12_reports"
N = int(sys.argv[1]) if len(sys.argv) > 1 else 1
TAG = sys.argv[2] if len(sys.argv) > 2 else f"n{N}"
#: ``cv2.GaussianBlur`` in ``observe.routes`` intermittently raises "Unknown C++ exception"
#: under host load (many parallel agents); an attempt that fails there is retried, and every
#: attempt (its error and duration) is recorded in the run report.
MAX_ATTEMPTS = int(sys.argv[3]) if len(sys.argv) > 3 else 3


def patch_concurrent_edit_globals() -> dict[str, object]:
    """Satisfy roles constants a concurrent editor of ``pipeline.py`` uses before importing them.

    ``synlab/pipeline.py`` is shared with other agents working in this checkout; while they edit
    it, a constant can be referenced before it is imported (observed: SCHEMA_LABELS,
    SCHEMA_PROVENANCE) and every generation run dies with ``NameError``.  This scratch runner
    injects the *existing* ``synlab.roles`` constants that ``pipeline.py`` looks up but does not
    have, so the evidence run is not blocked by an unrelated in-flight edit.  Nothing is written
    to the repository and the injected names are reported in the run report.
    """
    import synlab.pipeline as pipeline
    from synlab import roles

    injected: dict[str, object] = {}
    for name in dir(roles):
        if name.isupper() and not hasattr(pipeline, name):
            value = getattr(roles, name)
            setattr(pipeline, name, value)
            injected[name] = value
    return injected


INJECTED = patch_concurrent_edit_globals()
if INJECTED:
    print("INJECTED_ROLES_CONSTANTS", json.dumps(sorted(INJECTED)), flush=True)


spec = load_generation_spec(SPEC)
spec.storage.root = str(STORE)
STORE.mkdir(parents=True, exist_ok=True)
before = directory_bytes(STORE) if STORE.exists() else 0


def progress(event: dict) -> None:
    event = {**event, "t": round(time.perf_counter() - t0, 1)}
    print(json.dumps(event, ensure_ascii=False), flush=True)


t0 = time.perf_counter()
attempts: list[dict] = []
report: dict = {}
for attempt in range(1, MAX_ATTEMPTS + 1):
    try:
        report = run_generation(spec, store_root=STORE, max_mothers=N, degrade_diversity=True,
                                progress=progress)
    except Exception as exc:  # noqa: BLE001 - a killed/failed attempt is retried, not hidden
        attempts.append({"attempt": attempt, "raised": f"{type(exc).__name__}: {exc}"[:300]})
        continue
    attempts.append({"attempt": attempt, "accepted": report.get("accepted"),
                     "failed": report.get("failed"),
                     "errors": [e.get("message", "")[:160] for e in (report.get("errors") or [])],
                     "seconds": round(float(report.get("seconds", 0.0)), 2)})
    if report.get("accepted"):
        break
after = directory_bytes(STORE)
report.update({"store": str(STORE), "store_bytes_before": before, "store_bytes_after": after,
               "store_bytes_delta": after - before,
               "injected_roles_constants": sorted(INJECTED),
               "generation_attempts": attempts,
               "wall_seconds": round(time.perf_counter() - t0, 2)})
REPORTS.mkdir(parents=True, exist_ok=True)
out = REPORTS / f"degrade_diversity_run_{TAG}.json"
out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
print("REPORT", out)
print(json.dumps({k: v for k, v in report.items() if k not in ("failures", "errors")},
                 ensure_ascii=False, indent=2, default=str))
