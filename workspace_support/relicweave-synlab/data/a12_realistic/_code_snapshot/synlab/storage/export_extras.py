"""Export the §8 "synthetic extras" into a package view **beside** ``deploy/``/``research/``.

Placement (measured, not assumed)
---------------------------------
A real export package is ``<pkg>/training_package/`` and it *contains* ``deploy/`` and
``research/``.  ``tools/load_package.py --check`` fails with exit 3 if any file inside the
package root is not declared in ``export_manifest.json["files"]`` (only
``export_manifest.json`` / ``dataset_card.json`` / ``README.md`` are tolerated extras), and
that checker and ``synlab/storage/export.py`` are owned by another teammate and are not
edited here.  Writing extras *inside* the package root would therefore silently turn a
passing package into exit 3.

So this module writes to ``<pkg>/synthetic_extra/`` -- a sibling of
``<pkg>/training_package/`` -- which is the literal path template
``data/a12_exports/<pkg>/synthetic_extra/`` and keeps ``--check`` on the package itself at
exit 0.  The deviation from "a sibling of ``deploy/`` on the same level" and the measured
exit codes are recorded in ``docs/a12/synthetic_extras.md``.

Nothing here is written into ``deploy/`` or ``research/``: :func:`check_extras` fails if it
ever finds an extras artifact there, and it fails if any extras array name collides with a
deploy-view channel name.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from ..observe.synthetic_extras import (
    CLAIM_BAN,
    EXTRA_DIRNAME,
    MODALITIES,
    MODALITY_BY_ID,
    MODALITY_IDS,
    SCHEMA_EXTRA_ANNOTATION,
    SCHEMA_EXTRA_INDEX,
    ExtrasResult,
    assert_claim_ban,
    generate_synthetic_extras,
)

#: Fallback deployment-view channel names.  The live list is the data-driven policy
#: ``synlab/schemas/view_channels.json``; :func:`deploy_channel_names` prefers it and only
#: falls back to this tuple when the policy cannot be read.  An extras array may never
#: reuse a deploy channel name, so no downstream reader can confuse the two views.
DEPLOY_CHANNEL_NAMES: tuple[str, ...] = (
    "tiles", "valid", "view_pos", "depth_z", "deployment_mask", "uncertain_mask", "roi", "K",
)
#: Sub-directories of a training package that the extras must never appear in.
PROTECTED_DIRS: tuple[str, ...] = ("deploy", "research")

#: Roles the store-backed driver uses to build the per-fragment index, in order.
_TARGET_ROLES: tuple[str, ...] = ("obs_result", "fragment_mesh")

__all__ = [
    "EXTRA_DIRNAME", "DEPLOY_CHANNEL_NAMES", "PROTECTED_DIRS", "deploy_channel_names",
    "extras_dir", "write_extras", "scan_extras", "check_extras", "export_extras",
]


def deploy_channel_names() -> tuple[list[str], list[str], str]:
    """``(deploy_channels, research_only_channels, source)`` from the live channel policy."""
    try:
        from .export import load_channel_policy

        policy = load_channel_policy()
        deploy = sorted(str(k) for k in (policy.get("deploy") or []))
        research = sorted(str(k) for k in (policy.get("research_only") or []))
        if deploy:
            return deploy, research, "synlab/schemas/view_channels.json via load_channel_policy"
    except Exception:
        pass
    return list(DEPLOY_CHANNEL_NAMES), [], "built-in fallback tuple (policy unreadable)"


# --------------------------------------------------------------------------------------
# paths
# --------------------------------------------------------------------------------------
def extras_dir(package_dir: str | Path) -> Path:
    """``<pkg>/synthetic_extra`` for a package directory ``<pkg>``."""
    return Path(package_dir) / EXTRA_DIRNAME


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                   encoding="utf-8")
    tmp.replace(path)


def _slug(text: str) -> str:
    keep = [c if (c.isalnum() or c in "-_.") else "_" for c in str(text)]
    return "".join(keep)


# --------------------------------------------------------------------------------------
# writer
# --------------------------------------------------------------------------------------
def write_extras(
    root: str | Path, results: Iterable[ExtrasResult], *,
    package_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Write every bundle to ``root`` and rebuild ``root/index.json`` by a real scan.

    One ``<fragment>__<modality>.npz`` (compressed arrays) plus a matching ``.json``
    annotation sidecar per bundle.  Nothing is written for a bundle that failed, so a
    failure can never leave placeholder data behind.
    """
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    seconds: dict[str, float] = {}
    for result in results:
        for bundle in result.bundles:
            if not bundle.ok:
                continue
            stem = f"{_slug(result.fragment_id)}__{_slug(bundle.modality_id)}"
            npz_path = root / f"{stem}.npz"
            # A string-valued entry is metadata, not a numeric channel: it goes into the
            # annotation instead of the npz so ``np.load`` never yields an object array.
            arrays: dict[str, np.ndarray] = {}
            text_fields: dict[str, Any] = {}
            for key, value in bundle.arrays.items():
                arr = np.asarray(value)
                if arr.dtype.kind in "US":
                    text_fields[key] = arr.tolist()
                else:
                    arrays[key] = arr
            np.savez_compressed(npz_path, **arrays)
            annotation = dict(bundle.annotation)
            annotation["fragment_id"] = result.fragment_id
            annotation["component_id"] = result.component_id
            annotation["lineage_id"] = result.lineage_id
            annotation["master_seed"] = int(result.master_seed)
            annotation["profile_id"] = result.profile_id
            annotation["npz"] = npz_path.name
            annotation["write_seconds"] = round(float(bundle.seconds), 4)
            if text_fields:
                annotation["text_fields"] = text_fields
            assert_claim_ban(annotation)
            _write_json(root / f"{stem}.json", annotation)
            written.append(npz_path.name)
            seconds[bundle.modality_id] = seconds.get(bundle.modality_id, 0.0) \
                + float(bundle.seconds)
    index = scan_extras(root, package_dir=package_dir)
    index["written_this_call"] = sorted(written)
    index["generate_seconds"] = {k: round(v, 4) for k, v in sorted(seconds.items())}
    _write_json(root / "index.json", index)
    return index


# --------------------------------------------------------------------------------------
# scanner (the index is built from disk, never from memory)
# --------------------------------------------------------------------------------------
def scan_extras(root: str | Path, *, package_dir: str | Path | None = None) -> dict[str, Any]:
    """Build the extras index by reading the files that are actually on disk."""
    root = Path(root)
    problems: list[str] = []
    rows: dict[str, dict[str, Any]] = {}
    per_modality: dict[str, dict[str, Any]] = {}
    total_bytes = 0

    for npz_path in sorted(root.glob("*.npz")):
        stem = npz_path.name[: -len(".npz")]
        side = root / f"{stem}.json"
        if not side.exists():
            problems.append(f"missing annotation sidecar for {npz_path.name}")
            continue
        try:
            annotation = json.loads(side.read_text(encoding="utf-8"))
        except Exception as exc:                                   # pragma: no cover
            problems.append(f"{side.name}: unreadable annotation ({exc})")
            continue
        try:
            assert_claim_ban(annotation)
        except ValueError as exc:
            problems.append(f"{side.name}: {exc}")
        modality_id = str(annotation.get("modality_id", ""))
        if modality_id not in MODALITY_BY_ID:
            problems.append(f"{stem}: unknown modality_id {modality_id!r}")
        arrays: dict[str, dict[str, Any]] = {}
        try:
            with np.load(npz_path, allow_pickle=False) as data:
                for key in data.files:
                    arr = data[key]
                    arrays[key] = {"shape": list(arr.shape), "dtype": str(arr.dtype),
                                   "bytes": int(arr.nbytes)}
        except Exception as exc:                                   # pragma: no cover
            problems.append(f"{npz_path.name}: unreadable npz ({exc})")
        file_bytes = int(npz_path.stat().st_size)
        total_bytes += file_bytes
        row_key = f"{annotation.get('fragment_id', 'unknown')}::{modality_id}"
        rows[row_key] = {
            "modality_id": modality_id,
            "item": annotation.get("item"),
            "fragment_id": annotation.get("fragment_id"),
            "component_id": annotation.get("component_id"),
            "lineage_id": annotation.get("lineage_id"),
            "master_seed": annotation.get("master_seed"),
            "profile_id": annotation.get("profile_id"),
            "rig_obtainable": annotation.get("rig_obtainable"),
            "synthetic_only": annotation.get("synthetic_only"),
            "rig_source": annotation.get("rig_source"),
            "claim_allowed": annotation.get("claim_allowed"),
            "unit": annotation.get("unit"),
            "frame": annotation.get("frame"),
            "generator": annotation.get("generator"),
            "shape": annotation.get("shape"),
            "dtype": annotation.get("dtype"),
            "annotation_file": side.name,
            "npz": npz_path.name,
            "file_bytes": file_bytes,
            "array_bytes": int(sum(v["bytes"] for v in arrays.values())),
            "sha256": _sha256(npz_path),
            "arrays": arrays,
            "annotation": annotation,
        }
        entry = per_modality.setdefault(modality_id, {
            "modality_id": modality_id, "instances": 0, "file_bytes": 0, "array_bytes": 0,
            "fragments": [], "arrays": {},
        })
        entry["instances"] += 1
        entry["file_bytes"] += file_bytes
        entry["array_bytes"] += int(sum(v["bytes"] for v in arrays.values()))
        entry["fragments"].append(annotation.get("fragment_id"))
        for key, meta in arrays.items():
            entry["arrays"].setdefault(key, meta)

    catalogue: list[dict[str, Any]] = []
    for spec in MODALITIES:
        entry = per_modality.get(spec.modality_id, {
            "modality_id": spec.modality_id, "instances": 0, "file_bytes": 0,
            "array_bytes": 0, "fragments": [], "arrays": {},
        })
        catalogue.append({
            "modality_id": spec.modality_id,
            "item": spec.item,
            "title": spec.title,
            "rig_obtainable": spec.rig_obtainable,
            "synthetic_only": spec.synthetic_only,
            "rig_source": spec.rig_source,
            "claim_allowed": spec.claim_allowed,
            "reason": spec.reason,
            "doc_refs": list(spec.doc_refs),
            "unit": spec.unit,
            "frame": spec.frame,
            "ablation": {"field": spec.ablation_field, "group": spec.ablation_group,
                         "hypothesis": spec.hypothesis},
            "arrays_declared": list(spec.arrays),
            "instances": entry["instances"],
            "file_bytes": entry["file_bytes"],
            "array_bytes": entry["array_bytes"],
            "fragments": sorted({f for f in entry["fragments"] if f}),
            "arrays": entry["arrays"],
        })

    index = {
        "schema": SCHEMA_EXTRA_INDEX,
        "index_source": "filesystem scan by synlab.storage.export_extras.scan_extras",
        "scanned_at": time.time(),
        "root": root.name,
        "claim_ban": CLAIM_BAN,
        "placement_note": (
            "extras live beside the training package that owns deploy/ and research/; "
            "nothing here is written into deploy/ or research/"
        ),
        "modalities": catalogue,
        "rows": rows,
        "totals": {
            "modalities": len(catalogue),
            "instances": len(rows),
            "file_bytes": total_bytes,
            "array_bytes": int(sum(r["array_bytes"] for r in rows.values())),
        },
        "problems": problems,
    }
    if package_dir is not None:
        index["isolation"] = _isolation_report(Path(package_dir), root)
    return index


def _declares_extras_index(path: Path) -> bool:
    """True when ``path`` is a JSON file that really is a synthetic-extras index.

    Generic file names such as ``index.json`` occur in the deploy view legitimately, so a
    bare name match would be a false positive; the content schema is the honest oracle.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return isinstance(data, dict) and data.get("schema") == SCHEMA_EXTRA_INDEX


def _isolation_report(package_dir: Path, extras_root: Path) -> dict[str, Any]:
    """Prove that the deploy/research views are untouched by the extras."""
    collisions: list[str] = []
    leaked: list[str] = []
    deploy_channels, research_channels, policy_source = deploy_channel_names()
    # payload artifacts are uniquely named ``<fragment>__<modality>.{npz,json}``; the generic
    # ``index.json`` is recognised by its declared schema instead of by its name.
    payload_names = {p.name for p in extras_root.glob("*.npz")}
    payload_names |= {p.name for p in extras_root.glob("*.json") if p.name != "index.json"}
    for protected in PROTECTED_DIRS:
        base = package_dir / protected
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            hit = path.name in payload_names
            if not hit and path.name == "index.json":
                hit = _declares_extras_index(path)
            if hit:
                leaked.append(str(path.relative_to(package_dir)).replace("\\", "/"))
    for name in sorted(set(_iter_array_names(extras_root))):
        if name in deploy_channels or name in research_channels:
            collisions.append(name)
    return {
        "channel_policy_source": policy_source,
        "deploy_channel_names": deploy_channels,
        "research_only_channel_names": research_channels,
        "extras_channel_collisions": sorted(set(collisions)),
        "extras_files_under_protected_dirs": sorted(leaked),
        "ok": not collisions and not leaked,
    }


def _iter_array_names(extras_root: Path) -> Iterable[str]:
    for npz_path in extras_root.glob("*.npz"):
        with np.load(npz_path, allow_pickle=False) as data:
            for key in data.files:
                yield key


# --------------------------------------------------------------------------------------
# store-backed driver
# --------------------------------------------------------------------------------------
def _load_record_mesh(store: Any, record: Any) -> Any:
    """Load a mesh from a record, accepting both payload layouts used in this store.

    ``fragment_mesh`` commits the mesh under ``mesh.*`` while ``physical_component`` commits
    ``vertices``/``faces``/``face__*`` at the top level; both round-trip their face
    attributes through :mod:`synlab.storage.mesh_io`.
    """
    from .mesh_io import arrays_to_mesh

    try:
        return store.load_mesh(record.asset_id, "mesh")
    except Exception:
        pass
    arrays = store.load_arrays(record.asset_id)
    if "vertices" in arrays and "faces" in arrays:
        mesh, _attrs = arrays_to_mesh(arrays)
        return mesh
    raise KeyError(f"asset {record.asset_id} ({record.role}) carries no mesh payload "
                   f"(keys: {sorted(arrays)[:8]})")


def _resolve_targets(store: Any, *, lineage_id: str | None,
                     fragment_ids: Sequence[str] | None) -> list[dict[str, Any]]:
    """Find one render target per fragment, preferring the post-damage physical component.

    The per-fragment index is the observation record (it is the only role that always
    carries ``fragment_id`` together with ``component_id``); a ``physical_component`` is
    matched on that ``component_id`` and a clean ``fragment_mesh`` on the ``fragment_id``.
    """
    from ..observe.routes import resolve_target

    wanted = set(fragment_ids) if fragment_ids else None
    index: dict[str, dict[str, Any]] = {}
    for role in ("obs_result", "fragment_mesh"):
        for record in store.list_assets(role=role, lineage_id=lineage_id, limit=2000):
            fragment_id = str(record.meta.get("fragment_id")
                              or record.meta.get("clean_fragment_id") or "")
            if not fragment_id or (wanted is not None and fragment_id not in wanted):
                continue
            entry = index.setdefault(fragment_id, {})
            entry["component_id"] = str(record.meta.get("component_id") or entry.get(
                "component_id") or f"comp_{fragment_id}")
            if role == "fragment_mesh":
                entry["fragment_mesh_record"] = record
    by_component: dict[str, Any] = {}
    for record in store.list_assets(role="physical_component", lineage_id=lineage_id,
                                    limit=2000):
        component_id = str(record.meta.get("component_id") or "")
        if component_id:
            by_component.setdefault(component_id, record)

    out: list[dict[str, Any]] = []
    for fragment_id in sorted(index):
        entry = index[fragment_id]
        record = by_component.get(entry.get("component_id", ""))
        if record is None:
            record = entry.get("fragment_mesh_record")
        if record is None:
            continue
        mesh = _load_record_mesh(store, record)
        target = resolve_target({
            "mesh": mesh,
            "fragment_id": fragment_id,
            "component_id": entry.get("component_id"),
            "face_origin_kind": record.meta.get("face_origin_kind"),
            "face_interface_id": record.meta.get("face_interface_id"),
        }, allow_unlabeled=True)
        out.append({"fragment_id": fragment_id, "target": target, "source_role": record.role,
                    "source_asset_id": record.asset_id})
    return out


def export_extras(
    store: Any,
    package_dir: str | Path,
    *,
    lineage_id: str | None = None,
    fragment_ids: Sequence[str] | None = None,
    modalities: Iterable[str] | None = None,
    master_seed: int = 20261001,
    long_edge_px: int = 128,
    baseline_mm: float = 60.0,
    rotation_step_deg: float = 5.0,
    polarizer_step_deg: float = 15.0,
    claim_mm: float = 0.1,
    profile: Any = None,
) -> dict[str, Any]:
    """Generate extras for every resolved fragment and write them under ``<pkg>/synthetic_extra``."""
    root = extras_dir(package_dir)
    targets = _resolve_targets(store, lineage_id=lineage_id, fragment_ids=fragment_ids)
    results: list[ExtrasResult] = []
    failures: list[dict[str, Any]] = []
    for entry in targets:
        try:
            results.append(generate_synthetic_extras(
                entry["target"], store=store, profile=profile, master_seed=master_seed,
                lineage_id=lineage_id or "", fragment_id=entry["fragment_id"],
                modalities=modalities, long_edge_px=long_edge_px, baseline_mm=baseline_mm,
                rotation_step_deg=rotation_step_deg,
                polarizer_step_deg=polarizer_step_deg, claim_mm=claim_mm))
        except Exception as exc:
            failures.append({"fragment_id": entry["fragment_id"],
                             "error": f"{type(exc).__name__}: {exc}"})
    index = write_extras(root, results, package_dir=package_dir)
    index["resolved_targets"] = [
        {"fragment_id": e["fragment_id"], "source_role": e["source_role"],
         "source_asset_id": e["source_asset_id"]} for e in targets]
    index["generation_failures"] = [
        {"fragment_id": r.fragment_id, "modality_id": b.modality_id, "failure": b.failure}
        for r in results for b in r.bundles if not b.ok] + failures
    _write_json(root / "index.json", index)
    return index


# --------------------------------------------------------------------------------------
# checker (used by tools/load_extras.py --check)
# --------------------------------------------------------------------------------------
def check_extras(package_dir: str | Path, *, root: str | Path | None = None,
                 require_all_modalities: bool = True) -> dict[str, Any]:
    """Verify the extras view end to end.  ``ok`` False means exit 3 at the CLI."""
    package = Path(package_dir)
    extras_root = Path(root) if root is not None else extras_dir(package)
    problems: list[str] = []
    checks: list[dict[str, Any]] = []

    def record(name: str, ok: bool, detail: Any) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})
        if not ok:
            problems.append(f"{name}: {detail}")

    index_path = extras_root / "index.json"
    if not index_path.exists():
        record("index_present", False, f"{index_path} does not exist")
        return {"ok": False, "problems": problems, "checks": checks,
                "package_dir": str(package), "extras_root": str(extras_root)}
    index = json.loads(index_path.read_text(encoding="utf-8"))
    record("index_schema", index.get("schema") == SCHEMA_EXTRA_INDEX,
           {"found": index.get("schema"), "expected": SCHEMA_EXTRA_INDEX})

    on_disk = sorted(p.name for p in extras_root.glob("*.npz"))
    in_index = sorted({row.get("npz") for row in index.get("rows", {}).values()})
    record("npz_set_matches_index", on_disk == in_index,
           {"on_disk": len(on_disk), "in_index": len(in_index),
            "missing_from_index": [n for n in on_disk if n not in in_index],
            "missing_on_disk": [n for n in in_index if n not in on_disk]})

    bad_hash: list[str] = []
    bad_sidecar: list[str] = []
    key_problems: list[dict[str, Any]] = []
    claim_violations: list[str] = []
    for key, row in sorted(index.get("rows", {}).items()):
        npz_path = extras_root / str(row.get("npz"))
        if not npz_path.exists():
            bad_hash.append(f"{row.get('npz')}: missing")
            continue
        if int(npz_path.stat().st_size) != int(row.get("file_bytes", -1)):
            bad_hash.append(f"{row.get('npz')}: size mismatch")
        elif _sha256(npz_path) != row.get("sha256"):
            bad_hash.append(f"{row.get('npz')}: sha256 mismatch")
        side = extras_root / str(row.get("annotation_file"))
        if not side.exists():
            bad_sidecar.append(f"{row.get('annotation_file')}: missing")
            continue
        annotation = json.loads(side.read_text(encoding="utf-8"))
        if annotation.get("schema") != SCHEMA_EXTRA_ANNOTATION:
            bad_sidecar.append(f"{side.name}: schema {annotation.get('schema')!r}")
        try:
            assert_claim_ban(annotation)
        except ValueError as exc:
            claim_violations.append(f"{side.name}: {exc}")
        required = ("modality_id", "item", "rig_obtainable", "synthetic_only", "rig_source",
                    "claim_allowed", "reason", "doc_refs", "unit", "frame", "shape",
                    "generator")
        missing = [k for k in required if k not in annotation]
        seed_ok = bool((annotation.get("generator") or {}).get("seed_path"))
        if missing or not seed_ok:
            key_problems.append({"annotation": side.name, "missing": missing,
                                 "seed_path_present": seed_ok})
    record("npz_bytes_and_hashes", not bad_hash, bad_hash[:10])
    record("annotation_sidecars", not bad_sidecar, bad_sidecar[:10])
    record("annotation_keys_complete", not key_problems, key_problems[:10])
    record("claim_ban_holds", not claim_violations, claim_violations[:10])

    present = {str(m.get("modality_id")) for m in index.get("modalities", [])
               if int(m.get("instances", 0)) > 0}
    missing_modalities = [m for m in MODALITY_IDS if m not in present]
    if require_all_modalities:
        record("all_nine_modalities_present", not missing_modalities, missing_modalities)

    forbidden_on: list[str] = []
    for modality in index.get("modalities", []):
        if modality.get("rig_obtainable") is not False or modality.get("claim_allowed") is not False:
            forbidden_on.append(str(modality.get("modality_id")))
    record("catalogue_claim_ban", not forbidden_on, forbidden_on)

    isolation = _isolation_report(package, extras_root)
    record("no_view_channel_collision", not isolation["extras_channel_collisions"],
           isolation["extras_channel_collisions"])
    record("no_extras_under_deploy_or_research",
           not isolation["extras_files_under_protected_dirs"],
           isolation["extras_files_under_protected_dirs"])

    return {
        "ok": not problems,
        "problems": problems,
        "checks": checks,
        "package_dir": str(package),
        "extras_root": str(extras_root),
        "isolation": isolation,
        "totals": index.get("totals", {}),
        "index_problems": index.get("problems", []),
    }
