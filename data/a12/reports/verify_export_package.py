"""Independent cross-check of an exported training package (no exporter code reused).

Everything here re-derives its answer from the bytes on disk:

* the ``files[]`` of each view is compared with the real directory listing (both set
  differences are printed, so a file that is written but not declared *and* a file that is
  declared but not written are both visible);
* every declared hash is recomputed with ``hashlib.sha256``;
* the deployment view is scanned for ``roles.FORBIDDEN_FEATURE_FIELDS`` with a key reader
  written here (JSON at every depth / parquet columns / npz array names / tar member names /
  the zarr replica's declared array names), and the number of keys read is the denominator;
* ``contains_truth`` is decided from each view's own content (supervision column names, a
  non-empty ``truth_channels`` list, or an ``{opaque: real id}`` map).

Usage::

    python data/a12/reports/verify_export_package.py --package <pkg dir> --out <json>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tarfile
from pathlib import Path
from typing import Any, Mapping

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synlab.roles import FORBIDDEN_FEATURE_FIELDS  # noqa: E402

VIEWS = ("deploy", "research")
ZARR_DIR = "zarr"
STORAGE_METADATA_NAMES = frozenset({"zarr.json", ".zarray", ".zattrs", ".zgroup",
                                    ".zmetadata"})
SUPERVISION_FIELDS = frozenset({
    "kind", "loss_mask", "eligible_as_negative", "label_layer", "candidate", "candidate_id",
    "query", "area_mm2", "reason", "lineage_cluster", "unique_source_triangle",
    "relation", "relations", "labels",
})


# ---------------------------------------------------------------------------- helpers
def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def disk_files(package: Path, view: str) -> list[str]:
    root = package / view
    if not root.exists():
        return []
    return sorted(str(path.relative_to(package)).replace("\\", "/")
                  for path in root.rglob("*") if path.is_file())


def json_keys(node: Any, out: set[str]) -> None:
    if isinstance(node, Mapping):
        for key, value in node.items():
            out.add(str(key))
            json_keys(value, out)
    elif isinstance(node, (list, tuple)):
        for item in node:
            json_keys(item, out)


def field_name(raw: str) -> str:
    text = str(raw).replace("\\", "/").rsplit("/", 1)[-1]
    if "__" in text:
        text = text.rsplit("__", 1)[-1]
    for suffix in (".npy", ".npz", ".json"):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
    return text


def container_fields(path: Path) -> tuple[set[str] | None, str]:
    suffix = path.suffix.lower()
    try:
        if suffix == ".json":
            out: set[str] = set()
            json_keys(json.loads(path.read_text(encoding="utf-8")), out)
            return out, ""
        if suffix == ".parquet":
            import pyarrow.parquet as pq

            return {str(name) for name in pq.read_schema(path).names}, ""
        if suffix == ".npz":
            with np.load(path, allow_pickle=False) as data:
                return {field_name(name) for name in data.files}, ""
        if suffix == ".tar":
            with tarfile.open(path, "r") as tar:
                return ({field_name(member.name) for member in tar.getmembers()
                         if member.isfile()}, "")
    except Exception as exc:  # noqa: BLE001 - reported, never silently dropped
        return None, f"{type(exc).__name__}: {exc}"
    return None, "binary payload (carries no field name)"


def zarr_declared_arrays(package: Path, view: str) -> set[str]:
    meta = package / view / ZARR_DIR / "zarr.json"
    if not meta.exists():
        return set()
    try:
        payload = json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    attrs = payload.get("attributes") if isinstance(payload, Mapping) else None
    declared = attrs.get("arrays") if isinstance(attrs, Mapping) else None
    if isinstance(declared, (list, tuple)):
        return {str(item) for item in declared}
    return {child.name for child in (package / view / ZARR_DIR).iterdir() if child.is_dir()}


def looks_opaque(name: Any) -> bool:
    text = str(name)
    return len(text) == 24 and all(char in "0123456789abcdef" for char in text)


def declares_truth_channels(node: Any) -> bool:
    if isinstance(node, Mapping):
        channels = node.get("truth_channels")
        if isinstance(channels, (list, tuple)) and len(channels) > 0:
            return True
        return any(declares_truth_channels(value) for value in node.values())
    if isinstance(node, (list, tuple)):
        return any(declares_truth_channels(item) for item in node)
    return False


def maps_opaque_names_to_ids(node: Any) -> bool:
    if isinstance(node, Mapping):
        for key, value in node.items():
            if looks_opaque(key) and isinstance(value, str) and not looks_opaque(value):
                return True
        return any(maps_opaque_names_to_ids(value) for value in node.values())
    if isinstance(node, (list, tuple)):
        return any(maps_opaque_names_to_ids(item) for item in node)
    return False


def scan_view(package: Path, view: str) -> dict[str, Any]:
    root = package / view
    containers: dict[str, int] = {}
    keys_by_container: dict[str, list[str]] = {}
    skipped: list[dict[str, str]] = []
    if root.exists():
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            rel = str(path.relative_to(package)).replace("\\", "/")
            if path.name in STORAGE_METADATA_NAMES:
                skipped.append({"file": rel, "reason": "storage-format metadata"})
                continue
            found, reason = container_fields(path)
            if found is None:
                skipped.append({"file": rel, "reason": reason})
                continue
            keys_by_container[rel] = sorted(found)
            containers[rel] = len(found)
        declared = zarr_declared_arrays(package, view)
        if declared:
            label = f"{view}/{ZARR_DIR}/* (declared array names)"
            keys_by_container[label] = sorted(declared)
            containers[label] = len(declared)
    unique: set[str] = set()
    for keys in keys_by_container.values():
        unique |= set(keys)
    return {"containers": containers, "keys_by_container": keys_by_container,
            "keys_scanned": int(sum(containers.values())), "unique_keys": sorted(unique),
            "skipped": skipped}


def truth_bearing(package: Path, view: str, scan: Mapping[str, Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for rel, keys in sorted(scan["keys_by_container"].items()):
        supervision = sorted(set(keys) & SUPERVISION_FIELDS)
        if supervision:
            out.append({"file": rel, "reason": "supervision fields: " + ", ".join(supervision)})
            continue
        path = package / rel
        if path.suffix.lower() != ".json" or not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if declares_truth_channels(payload):
            out.append({"file": rel, "reason": "declares truth channels"})
        elif maps_opaque_names_to_ids(payload):
            out.append({"file": rel, "reason": "maps opaque names back to real ids"})
    return out


# ---------------------------------------------------------------------------- checks
def verify(package: Path) -> dict[str, Any]:
    manifest = json.loads((package / "export_manifest.json").read_text(encoding="utf-8"))
    declared = [str(entry["path"]) for entry in manifest.get("files", [])]
    report: dict[str, Any] = {"package": str(package), "checks": {}, "ok": True}

    def record(name: str, ok: bool, detail: Any) -> None:
        report["checks"][name] = {"ok": bool(ok), "detail": detail}
        if not ok:
            report["ok"] = False

    for view in VIEWS:
        on_disk = set(disk_files(package, view))
        in_manifest = {path for path in declared if path.startswith(view + "/")}
        record(f"{view}.file_set_matches_manifest",
               on_disk == in_manifest,
               {"files_on_disk": len(on_disk), "files_in_manifest": len(in_manifest),
                "on_disk_not_in_manifest": sorted(on_disk - in_manifest),
                "in_manifest_not_on_disk": sorted(in_manifest - on_disk)})

    mismatches: list[dict[str, str]] = []
    missing: list[str] = []
    for entry in manifest.get("files", []):
        path = package / entry["path"]
        if not path.exists():
            missing.append(str(entry["path"]))
            continue
        actual = sha256_file(path)
        if actual != entry["hash"]:
            mismatches.append({"path": str(entry["path"]), "manifest": str(entry["hash"]),
                               "actual": actual})
    record("hashes_match_manifest", not mismatches and not missing,
           {"files_checked": len(declared), "missing": missing, "mismatches": mismatches})

    forbidden = {str(name).lower() for name in FORBIDDEN_FEATURE_FIELDS}
    scans = {view: scan_view(package, view) for view in VIEWS}
    deploy_scan = scans["deploy"]
    hits = [{"file": rel, "field": key}
            for rel, keys in sorted(deploy_scan["keys_by_container"].items())
            for key in keys if key.lower() in forbidden]
    record("deploy.forbidden_feature_fields_empty", not hits,
           {"hits": hits, "keys_scanned": deploy_scan["keys_scanned"],
            "unique_keys": len(deploy_scan["unique_keys"]),
            "containers": len(deploy_scan["containers"]),
            "not_read": sorted({entry["reason"] for entry in deploy_scan["skipped"]}),
            "not_read_files": len(deploy_scan["skipped"])})

    truth = {view: truth_bearing(package, view, scans[view]) for view in VIEWS}
    declared_truth = {view: bool((manifest.get("views", {}).get(view) or {})
                                 .get("contains_truth")) for view in VIEWS}
    separation = manifest.get("separation") or {}
    record("deploy.contains_truth_false_by_content",
           bool(truth["deploy"]) is False and declared_truth["deploy"] is False,
           {"content_truth_files": truth["deploy"], "manifest": declared_truth["deploy"]})
    record("research.contains_truth_true_by_content",
           bool(truth["research"]) is True and declared_truth["research"] is True,
           {"content_truth_files": truth["research"], "manifest": declared_truth["research"]})
    record("separation.features_carry_answer_fields_matches_scan",
           bool(separation.get("features_carry_answer_fields")) == bool(hits),
           {"manifest": separation.get("features_carry_answer_fields"), "scan_hits": len(hits)})

    report["views"] = {
        view: {"keys_scanned": scans[view]["keys_scanned"],
               "unique_keys": len(scans[view]["unique_keys"]),
               "containers": len(scans[view]["containers"]),
               "truth_bearing_files": truth[view],
               "containers_detail": scans[view]["containers"]}
        for view in VIEWS}
    report["manifest_files_total"] = len(declared)
    report["manifest_hash"] = manifest.get("manifest_hash")
    report["deploy_answer_field_scan"] = {
        "forbidden_hits": hits, "keys_scanned": deploy_scan["keys_scanned"],
        "unique_keys": len(deploy_scan["unique_keys"]),
        "skipped": deploy_scan["skipped"]}
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="verify_export_package")
    parser.add_argument("--package", required=True)
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    report = verify(Path(args.package))
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)
    print("\n=== summary ===")
    for name, entry in report["checks"].items():
        detail = entry["detail"]
        if isinstance(detail, Mapping) and "keys_scanned" in detail:
            print(f"  {name}: ok={entry['ok']} keys_scanned={detail['keys_scanned']} "
                  f"hits={len(detail.get('hits') or [])}")
        else:
            print(f"  {name}: ok={entry['ok']}")
    print(f"  overall ok={report['ok']}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
