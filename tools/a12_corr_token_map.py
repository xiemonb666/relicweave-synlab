"""Rebuild ``research/labels/correspondence.parquet`` with a real token-space locator.

Why this exists (S1): ``correspondence_for`` in ``synlab/training/labels.py`` can only build the
``W[q, c, i, j]`` weight matrix the correspondence loss consumes when a labelled sample can be
located in the delivered **token** grid.  The shipped exporter wrote ``corr_index_a``/
``corr_index_b`` as that locator -- arrays that are the endpoint ids of the pair, constant within
a pair -- so every package reported ``correspondence n_allowed = 0`` with the blocker
``one_side_of_every_labelled_pair_has_no_token_evidence``.

The real locator is the surface point (``corr_point_a/b``) plus the mesh face it lies on
(``corr_face_a/b``), projected into each fragment's own delivered views with the real
``K``/``T_WC`` and identified against the render's per-face ``id_map``.  The projection lives in
``synlab/storage/export.py::_correspondence_token_rows`` (the same function a full export uses);
this driver runs it against an existing package's release store and rewrites the label table, so
the fix is measurable without re-exporting 3.3 GB.

    python tools/a12_corr_token_map.py --package <pkg> --store <store> [--write] [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synlab.storage.export import (  # noqa: E402
    CORRESPONDENCE_TOKEN_TOLERANCE_MM,
    TrainingPackage,
    _correspondence_token_rows,
    _obs_view_count,
    _project_point_into_view,
    _truth_relations,
    _write_parquet,
)
from synlab.storage.store import AssetStore  # noqa: E402

#: roles whose assets carry the ``corr_*`` correspondence block
CORRESPONDENCE_ROLES = ("clean_truth", "physical_truth")


def _store_for(package: Path, store: str | Path | None) -> Path:
    if store is not None:
        return Path(store)
    rel = REPO_ROOT / "data" / "a12_trainable" / "store"
    if rel.exists():
        return rel
    raise SystemExit("no --store given and data/a12_trainable/store does not exist")


def _all_assets(store: AssetStore, role: str) -> list[Any]:
    """Every asset of one role (``AssetStore.list_assets`` pages at 500 rows)."""
    out: list[Any] = []
    offset = 0
    while True:
        page = store.list_assets(role=role, limit=500, offset=offset)
        out.extend(page)
        if len(page) < 500:
            return out
        offset += 500


def observation_map(store: AssetStore) -> dict[str, str]:
    """``fragment_id -> obs_result asset id`` (the asset carrying K/T_WC/id_map/depth_z)."""
    out: dict[str, str] = {}
    for record in _all_assets(store, "obs_result"):
        fragment_id = str((record.meta or {}).get("fragment_id") or "")
        if fragment_id:
            out.setdefault(fragment_id, record.asset_id)
    return out


def relations_with_truth_assets(store: AssetStore) -> list[dict[str, Any]]:
    """Every ``(a, b)`` pair the release's truth layer really supervises, plus its asset id.

    The pool's ``relations`` block (written into the ``clean_truth`` metadata) is the
    authoritative statement about a pair; each row is tagged with the truth asset that carries
    its ``corr_*`` arrays, exactly as :func:`synlab.storage.export._truth_relations` does for a
    full export.
    """
    rows: list[dict[str, Any]] = []
    for role in CORRESPONDENCE_ROLES:
        for record in _all_assets(store, role):
            rows.extend(_truth_relations(store, [record]))
    return rows


def project(store: AssetStore) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Run the export-side projection over every supervised pair of the release.

    The observation channels are loaded through a **callable**, one fragment at a time: the 59
    observation assets of this release hold ~270 MB of arrays each, so a ready mapping costs
    ~16 GB and the host kills the process.
    """
    obs_of = observation_map(store)
    from synlab.storage.export import load_projection_arrays

    def lookup(fragment_id: str):
        asset = obs_of.get(fragment_id)
        return load_projection_arrays(store, asset) if asset else None

    return _correspondence_token_rows(store, relations_with_truth_assets(store), lookup)


def _write_label_table(package: Path, rows: Sequence[dict[str, Any]]) -> Path:
    target = package / "research" / "labels" / "correspondence.parquet"
    _write_parquet(target, rows, 512)
    return target


def _update_manifest(package: Path, provenance: dict[str, Any]) -> None:
    """Record the new provenance in the package manifest (the label tables are the same files)."""
    manifest_path = package / "export_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    labels = manifest.setdefault("supervision_labels", {})
    labels["correspondence"] = {k: v for k, v in provenance.items() if k != "skipped"}
    labels["correspondence"]["skipped"] = provenance.get("skipped", [])[:20]
    labels["correspondence"]["token_space_source"] = (
        "synlab/storage/export.py::_correspondence_token_rows "
        "(corr_point_*/corr_face_* projected with the observation K/T_WC and identified "
        "against the render id_map)")
    counts = manifest.setdefault("counts", {})
    counts["correspondence_samples"] = int(len(provenance.get("samples", []) or [])
                                           if isinstance(provenance.get("samples"), list)
                                           else provenance.get("samples", 0))
    counts["correspondence_token_mapped_samples"] = int(provenance.get("samples_mapped", 0))
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
                             encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True)
    parser.add_argument("--store", default=None)
    parser.add_argument("--write", action="store_true",
                        help="rewrite research/labels/correspondence.parquet in place")
    parser.add_argument("--json", default=None)
    args = parser.parse_args(argv)

    package = Path(args.package)
    store = AssetStore(_store_for(package, args.store))
    rows, provenance = project(store)

    mapped = [r for r in rows if r.get("token_valid")]
    report = {
        "package": str(package),
        "store": str(store.root),
        "tolerance_mm": CORRESPONDENCE_TOKEN_TOLERANCE_MM,
        "rows": len(rows),
        "rows_with_both_sides_in_token_space": len(mapped),
        "rows_one_side_only": int(sum(
            1 for r in rows if not r.get("token_valid")
            and (int(r.get("token_a", -1)) >= 0 or int(r.get("token_b", -1)) >= 0))),
        "rows_neither_side": int(sum(
            1 for r in rows if not r.get("token_valid")
            and int(r.get("token_a", -1)) < 0 and int(r.get("token_b", -1)) < 0)),
        "pairs_supervised": provenance.get("pairs_supervised"),
        "pairs_with_correspondence": provenance.get("pairs_with_correspondence"),
        "unmapped_reason_histogram": provenance.get("unmapped_reason_histogram"),
        "views_used_per_side": provenance.get("views_used_per_side"),
        "token_views": sorted({int(r["token_view_a"]) for r in mapped}
                              | {int(r["token_view_b"]) for r in mapped}),
        "distinct_token_pairs": len({(int(r["token_a"]), int(r["token_b"])) for r in mapped}),
        "weight_sum_mapped": float(sum(float(r.get("weight") or 0.0) for r in mapped)),
        "association_code_histogram": provenance.get("association_code_histogram"),
    }
    if args.write:
        target = _write_label_table(package, rows)
        _update_manifest(package, provenance)
        report["written"] = str(target)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if args.json:
        Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=2,
                                              sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
