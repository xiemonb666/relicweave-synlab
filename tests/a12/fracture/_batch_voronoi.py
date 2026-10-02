"""Batch-production acceptance run for the ``warp_voronoi_cut`` backend (measurement, no asserts).

``synlab.pipeline.run_generation`` is handed a generation spec whose fracture backend is
``warp_voronoi_cut`` and whose storage root is the calibration store ``data/a12_fcal/store``; the
run then walks the **whole** asset DAG (mother -> material -> pattern -> fracture -> clean truth ->
physical -> observe -> features/labels/context) exactly as the production path does.  This module
builds the spec and runs it; the driver in ``_run_calibration.py`` records the outcome.

The spec is derived from a real config file (default ``configs/a12/sandbox.yaml``) with only the
fields listed in :data:`OVERRIDES` replaced, so nothing else about the production spec is changed
for the acceptance run and every replaced field is visible in the JSON report.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Sequence

__all__ = ["build_spec_document", "run_batch", "STORE_ROOT", "OVERRIDES"]

#: store of the calibration library (never a frozen data root)
STORE_ROOT = "data/a12_fcal/store"
#: the only fields the acceptance run replaces, with the reason
OVERRIDES: dict[str, Any] = {
    "dataset.target_mothers": "the acceptance run is 1-2 lineages, not the sandbox's 4",
    "dataset.sobol": "not a field",
    "fracture.backend": "the backend under acceptance (warp_voronoi_cut)",
    "fracture.target_piece_range": "declared range of the new backend's own count law",
    "storage.root": "the calibration store, so no frozen data root is written",
}


def build_spec_document(base_config: str | Path = "configs/a12/sandbox.yaml", *,
                        target_mothers: int = 1,
                        backend: str = "warp_voronoi_cut",
                        store_root: str = STORE_ROOT,
                        max_piece_range: Sequence[int] = (2, 32)) -> dict[str, Any]:
    """Load a real generation config and replace exactly the acceptance-run fields."""
    import yaml

    document = yaml.safe_load(Path(base_config).read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"{base_config} must contain a mapping")
    dataset = dict(document.get("dataset") or {})
    dataset["target_mothers"] = int(target_mothers)
    fracture = dict(document.get("fracture") or {})
    fracture["backend"] = str(backend)
    fracture["target_piece_range"] = [int(x) for x in max_piece_range]
    storage = dict(document.get("storage") or {})
    storage["root"] = str(store_root)
    storage["database"] = f"{store_root}/metadata.sqlite"
    document["dataset"] = dataset
    document["fracture"] = fracture
    document["storage"] = storage
    document["notes"] = (
        f"calibration acceptance run: backend={backend}, target_mothers={target_mothers}, "
        f"storage.root={store_root}; derived from {base_config}")
    return document


def run_batch(base_config: str | Path = "configs/a12/sandbox.yaml", *,
              target_mothers: int = 1, backend: str = "warp_voronoi_cut",
              store_root: str = STORE_ROOT,
              progress_path: str | Path | None = None) -> dict[str, Any]:
    """Run the real pipeline on the derived spec and report what the chain did.

    Returns the coverage ledger plus the measured per-lineage fracture rows: the row's ``backend``
    is the one the *event* actually ran (read back from the commit record, not assumed), and the
    stage timings are the pipeline's own.
    """
    from synlab.pipeline import run_generation
    from synlab.schemas.spec import GenerationSpec

    document = build_spec_document(base_config, target_mothers=target_mothers, backend=backend,
                                   store_root=store_root)
    spec = GenerationSpec.model_validate(document)
    started = time.perf_counter()
    report = run_generation(spec, store_root=store_root, max_mothers=int(target_mothers))
    elapsed = time.perf_counter() - started
    payload = {
        "schema": "synlab.fracture_calibration.batch.v1",
        "base_config": str(base_config),
        "backend_requested": str(backend),
        "store_root": str(store_root),
        "target_mothers": int(target_mothers),
        "wall_seconds_total": round(elapsed, 3),
        "generation": report,
    }
    if progress_path is not None:
        path = Path(progress_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
    return payload


def verify_batch(store_root: str = STORE_ROOT, *,
                 coverage_rows: str | Path = "") -> dict[str, Any]:
    """Read the store back: which backends the committed fragments actually came from."""
    from synlab.storage.store import AssetStore

    store = AssetStore(Path(store_root))
    rows = store.list_assets()
    by_role: dict[str, int] = {}
    backends: dict[str, int] = {}
    lineages: set[str] = set()
    for row in rows:
        role = str(getattr(row, "role", "") or "")
        by_role[role] = by_role.get(role, 0) + 1
        meta = dict(getattr(row, "meta", {}) or {})
        if role == "fragment_mesh":
            backend = str(meta.get("backend", "<missing>"))
            backends[backend] = backends.get(backend, 0) + 1
        if getattr(row, "lineage_id", None):
            lineages.add(str(row.lineage_id))
    payload: dict[str, Any] = {
        "store_root": str(store_root),
        "assets": len(rows),
        "assets_by_role": dict(sorted(by_role.items())),
        "fragment_backends": dict(sorted(backends.items())),
        "lineages": sorted(lineages),
    }
    if coverage_rows:
        path = Path(coverage_rows)
        if path.is_file():
            payload["coverage_rows"] = json.loads(path.read_text(encoding="utf-8"))
    return payload
