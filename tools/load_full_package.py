"""Load a ``flavour="full"`` package by ablation group and print real shapes and counts.

Usage
-----
    python tools/load_full_package.py --package <dir> --list-groups
    python tools/load_full_package.py --package <dir> --groups G-IMG-RGB,G-FRAC-ATTR
    python tools/load_full_package.py --package <dir> --groups G-LABEL-CLEAN --fragments <id>
    python tools/load_full_package.py --package <dir> --check        # exit 0 = consistent, 3 = not

What it does
------------
* reads ``manifest.json`` + ``ablation_index.json`` (never invents a group or a field);
* for every requested group, resolves the group's ``field_patterns`` against the manifest's
  ``<modality_id>#<array key>`` names and loads exactly those arrays from the package's own
  ``.npz`` files;
* prints, per group and per fragment, the array shapes and measured counts (element counts,
  boolean true-counts, integer value histograms, byte totals) -- the numbers are computed
  from the loaded bytes, not copied from the manifest;
* never imports torch: torch is used **only** if it is already importable, and then only to
  print the tensor shape a consumer would see.

Exit codes
----------
``0`` success (and ``--check`` consistent), ``2`` bad arguments / unknown group,
``3`` ``--check`` found a mismatch between the manifest and the files on disk.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:                      # direct ``python tools/load_full_package.py``
    sys.path.insert(0, str(REPO_ROOT))

from synlab.storage.export_full import check_full_package  # noqa: E402

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_INCONSISTENT = 3

MANIFEST_NAME = "manifest.json"
INDEX_NAME = "ablation_index.json"


# --------------------------------------------------------------------------------------
# package reading (no torch, no synlab.export dependency)
# --------------------------------------------------------------------------------------
def load_manifest(package: str | Path) -> dict[str, Any]:
    path = Path(package) / MANIFEST_NAME
    if not path.is_file():
        raise FileNotFoundError(f"no {MANIFEST_NAME} under {package}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_index(package: str | Path) -> dict[str, Any]:
    path = Path(package) / INDEX_NAME
    if not path.is_file():
        raise FileNotFoundError(f"no {INDEX_NAME} under {package}")
    return json.loads(path.read_text(encoding="utf-8"))


def group_ids(index: Mapping[str, Any]) -> list[str]:
    return [str(group["group_id"]) for group in index.get("groups", [])]


def find_group(index: Mapping[str, Any], group_id: str) -> dict[str, Any]:
    for group in index.get("groups", []):
        if group["group_id"] == group_id:
            return group
    raise KeyError(group_id)


def group_fields(group: Mapping[str, Any],
                 modalities: Mapping[str, Mapping[str, Any]]) -> list[tuple[str, str, str]]:
    """``[(modality_id, array key, file path)]`` selected by the group's field patterns."""
    selected: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    patterns = list(group.get("field_patterns") or [])
    for modality_id in group.get("modality_ids") or []:
        row = modalities.get(modality_id)
        if row is None or row.get("status") != "present":
            continue
        for key in sorted(row.get("arrays") or {}):
            qualname = f"{modality_id}#{key}"
            if patterns and not any(fnmatch.fnmatchcase(qualname, pattern) or
                                    fnmatch.fnmatchcase(key, pattern)
                                    for pattern in patterns):
                continue
            for entry in row.get("files") or []:
                if entry.get("format") != "npz" or key not in (entry.get("arrays") or []):
                    continue
                triple = (modality_id, key, str(entry["path"]))
                if triple not in seen:
                    seen.add(triple)
                    selected.append(triple)
    return selected


def load_group(package: str | Path, group: Mapping[str, Any], manifest: Mapping[str, Any], *,
               fragments: Sequence[str] | None = None,
               max_files: int | None = None) -> dict[str, Any]:
    """Load the arrays of one group and return them with measured statistics."""
    root = Path(package)
    modalities = {row["modality_id"]: row for row in manifest.get("modalities", [])}
    selected = group_fields(group, modalities)
    wanted = set(fragments) if fragments else None
    by_fragment: dict[str, dict[str, dict[str, np.ndarray]]] = defaultdict(
        lambda: defaultdict(dict))
    file_cache: dict[str, dict[str, np.ndarray]] = {}
    loaded_files: list[str] = []
    for modality_id, key, rel in selected:
        if max_files is not None and len(loaded_files) >= max_files and rel not in file_cache:
            continue
        if rel not in file_cache:
            path = root / rel
            if not path.is_file():
                file_cache[rel] = {}
                continue
            with np.load(path, allow_pickle=False) as data:
                file_cache[rel] = {name: data[name] for name in data.files}
            loaded_files.append(rel)
        arrays = file_cache[rel]
        if key not in arrays:
            continue
        fragment = _fragment_of(manifest, rel)
        if wanted is not None and fragment not in wanted:
            continue
        by_fragment[fragment][modality_id][key] = arrays[key]

    report: dict[str, Any] = {
        "group_id": group["group_id"],
        "title": group.get("title", ""),
        "availability": group.get("availability"),
        "fields_selected": len(selected),
        "files_loaded": len(loaded_files),
        "fragments": {},
    }
    for fragment, per_modality in sorted(by_fragment.items()):
        entry: dict[str, Any] = {"modalities": {}, "arrays": 0, "elements": 0, "bytes": 0}
        for modality_id, arrays in sorted(per_modality.items()):
            shapes = {}
            for key, array in sorted(arrays.items()):
                array = np.asarray(array)
                shapes[key] = {
                    "shape": list(array.shape), "dtype": str(array.dtype),
                    "elements": int(array.size), "bytes": int(array.nbytes),
                    **_measured(array),
                }
                entry["arrays"] += 1
                entry["elements"] += int(array.size)
                entry["bytes"] += int(array.nbytes)
            entry["modalities"][modality_id] = shapes
        report["fragments"][fragment] = entry
    return report


def _fragment_of(manifest: Mapping[str, Any], rel: str) -> str:
    if rel.startswith("fragments/"):
        return rel.split("/", 2)[1]
    if rel.startswith("mothers/"):
        return f"mother:{rel.split('/', 2)[1]}"
    if rel.startswith("store/"):
        return f"store:{rel.split('/', 2)[1]}"
    return "_assets"


def _measured(array: np.ndarray) -> dict[str, Any]:
    """Real counts computed from the loaded bytes (never copied from the manifest)."""
    if array.dtype == bool:
        true_count = int(np.count_nonzero(array))
        return {"true_count": true_count,
                "true_fraction": (true_count / array.size) if array.size else None}
    if array.dtype.kind in ("i", "u") and array.size:
        values, counts = np.unique(array, return_counts=True)
        out: dict[str, Any] = {"unique_count": int(values.size)}
        if values.size <= 64:
            out["histogram"] = {str(int(v)): int(c) for v, c in zip(values, counts)}
        return out
    if array.dtype.kind == "f" and array.size:
        finite = array[np.isfinite(array)]
        if finite.size:
            return {"min": float(finite.min()), "max": float(finite.max()),
                    "mean": float(finite.mean(dtype=np.float64))}
        return {"finite_values": 0}
    if array.dtype.kind in ("U", "S", "O"):
        values = np.unique(array)
        return {"unique_count": int(values.size),
                "sample_values": [str(item) for item in values[:8].tolist()]}
    return {}


# --------------------------------------------------------------------------------------
# printing
# --------------------------------------------------------------------------------------
def print_tensor_shapes(report: Mapping[str, Any], *, indent: str = "  ") -> None:
    """Print what a torch consumer would receive, if torch happens to be importable."""
    try:                                                # optional: never a hard dependency
        import torch                                    # type: ignore[import-not-found]
    except Exception as exc:                            # pragma: no cover - environment dependent
        print(f"{indent}(torch not importable: {type(exc).__name__}: {exc}; shapes above are "
              f"numpy)")
        return
    print(f"{indent}torch {torch.__version__} (cuda={torch.cuda.is_available()}) — "
          f"tensor shapes per fragment:")
    for fragment, entry in list(report["fragments"].items())[:3]:
        names = [f"{modality}#{key}" for modality, shapes in entry["modalities"].items()
                 for key in shapes]
        print(f"{indent}  {fragment}: {len(names)} tensors, e.g. {names[:3]}")


def build_report(package: str | Path, manifest: Mapping[str, Any],
                 index: Mapping[str, Any]) -> dict[str, Any]:
    """The reproducible summary of a full package (every number read from the manifest)."""
    root = Path(package)
    files_on_disk = [path for path in root.rglob("*") if path.is_file()
                     and not path.name.endswith(".part")]
    present = [row for row in manifest.get("modalities", []) if row["status"] == "present"]
    missing = [row for row in manifest.get("modalities", []) if row["status"] != "present"]
    return {
        "package": str(root),
        "schema": manifest.get("schema"),
        "flavor": manifest.get("flavor"),
        "store": manifest.get("generated_from", {}).get("store"),
        "selection": manifest.get("selection", {}),
        "generated_from": manifest.get("generated_from", {}),
        "role_counts": manifest.get("role_counts", {}),
        "counts": manifest.get("counts", {}),
        "files_on_disk": len(files_on_disk),
        "bytes_on_disk": int(sum(path.stat().st_size for path in files_on_disk)),
        "wall_seconds": manifest.get("wall_seconds"),
        "modalities_present": [
            {"modality_id": row["modality_id"], "role": row["role"],
             "files": row["counts"]["files"], "bytes": row["counts"]["bytes"],
             "assets": row["counts"]["assets"], "fragments": row["counts"]["fragments"],
             "arrays": row["counts"]["arrays"], "instances": row["counts"]["instances"],
             "deploy": row["deployment_view_allowed"], "truth": row["is_truth"],
             "label": row["is_label"], "derived": row["derived"],
             "fields": sorted(row["arrays"])[:32]}
            for row in present],
        "modalities_missing": [
            {"modality_id": row["modality_id"], "role": row["role"],
             "unlock_condition": row["unlock_condition"]} for row in missing],
        "ablation_summary": index.get("summary", {}),
        "ablation_groups": [
            {"group_id": row["group_id"], "availability": row["availability"],
             "fields": len(row["fields"]), "permission": row["permission"],
             "modalities_present": row["counts"]["modalities_present"],
             "modalities_missing": row["counts"]["modalities_missing"],
             "files": row["counts"]["files"], "bytes": row["counts"]["bytes"],
             "missing": [item["modality_id"] for item in row.get("missing", [])]}
            for row in index.get("groups", [])],
        "findings": manifest.get("findings", {}),
        "measurements": manifest.get("measurements", {}),
        "degradation": manifest.get("degradation", {}),
        "synthetic_evidence": manifest.get("synthetic_evidence", {}),
        "permission_policy": manifest.get("permission_policy", {}),
        "truth_permission": manifest.get("truth_permission", {}),
        "assets_skipped": manifest.get("assets_skipped", []),
    }


def print_report(report: Mapping[str, Any], *, verbose: bool, max_fields: int) -> None:
    print(f"[{report['group_id']}] {report['title']}")
    print(f"  availability={report['availability']} fields_selected={report['fields_selected']} "
          f"files_loaded={report['files_loaded']} fragments={len(report['fragments'])}")
    shown = 0
    for fragment, entry in report["fragments"].items():
        print(f"  - {fragment}: {entry['arrays']} arrays, {entry['elements']} elements, "
              f"{entry['bytes']} bytes")
        if not verbose:
            continue
        for modality_id, shapes in entry["modalities"].items():
            for key, info in shapes.items():
                if shown >= max_fields:
                    print(f"      … ({max_fields} fields shown; use --max-fields to see more)")
                    return
                extra = ""
                if "true_count" in info:
                    extra = f" true={info['true_count']} ({info['true_fraction']:.4f})"
                elif "histogram" in info:
                    extra = f" hist={info['histogram']}"
                elif "unique_count" in info:
                    extra = f" unique={info['unique_count']}"
                print(f"      {modality_id}#{key} {info['shape']} {info['dtype']}{extra}")
                shown += 1


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------
def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python tools/load_full_package.py",
        description="Load a flavour=full export by ablation group, or check its file set.")
    parser.add_argument("--package", required=True, help="a directory holding manifest.json")
    parser.add_argument("--groups", default=None,
                        help="comma-separated ablation group ids (see --list-groups)")
    parser.add_argument("--fragments", default=None, help="comma-separated fragment ids to load")
    parser.add_argument("--list-groups", action="store_true", help="print the ablation index")
    parser.add_argument("--check", action="store_true",
                        help="verify the file set against the manifest; exit 0 / 3")
    parser.add_argument("--verbose", action="store_true", help="print every loaded field")
    parser.add_argument("--max-fields", type=int, default=40,
                        help="cap on printed fields per group with --verbose")
    parser.add_argument("--max-files", type=int, default=None,
                        help="cap on .npz files actually read (a scouting aid, not a default)")
    parser.add_argument("--summary", action="store_true",
                        help="print modality counts and the missing list, then stop")
    parser.add_argument("--report", default=None,
                        help="write the reproducible JSON summary of the package to this path")
    args = parser.parse_args(argv)

    package = Path(args.package)

    if args.check:
        verdict = check_full_package(package)
        print(json.dumps(verdict, ensure_ascii=False, indent=2))
        return int(verdict["exit_code"])

    try:
        manifest = load_manifest(package)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_USAGE

    if args.report:
        try:
            index_for_report = load_index(package)
        except FileNotFoundError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return EXIT_USAGE
        report = build_report(package, manifest, index_for_report)
        target = Path(args.report)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
                          encoding="utf-8")
        print(f"wrote {target} "
              f"(modalities {len(report['modalities_present'])}/"
              f"{len(report['modalities_present']) + len(report['modalities_missing'])}, "
              f"files_on_disk {report['files_on_disk']}, "
              f"bytes_on_disk {report['bytes_on_disk']})")
        if not (args.summary or args.list_groups or args.groups):
            return EXIT_OK

    if args.summary:
        counts = manifest.get("counts", {})
        print(f"package: {package}")
        print(f"schema={manifest.get('schema')} flavor={manifest.get('flavor')}")
        print(f"store={manifest.get('generated_from', {}).get('store')}")
        print(f"files={counts.get('files')} bytes={counts.get('bytes')} "
              f"fragments={counts.get('fragments')} mothers={counts.get('mothers')}")
        print(f"modalities present={counts.get('modalities_present')} "
              f"missing={counts.get('modalities_missing')}")
        print("present:")
        for row in manifest.get("modalities", []):
            if row["status"] == "present":
                print(f"  {row['modality_id']:44s} files={row['counts']['files']:5d} "
                      f"bytes={row['counts']['bytes']:>12d} arrays={row['counts']['arrays']:3d} "
                      f"deploy={'Y' if row['deployment_view_allowed'] else 'n'} "
                      f"truth={'Y' if row['is_truth'] else 'n'} "
                      f"derived={'Y' if row['derived'] else 'n'}")
        print("missing (modality_id -> unlock condition):")
        for row in manifest.get("modalities", []):
            if row["status"] != "present":
                print(f"  {row['modality_id']:44s} {row['unlock_condition']}")
        return EXIT_OK

    try:
        index = load_index(package)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_USAGE

    if args.list_groups:
        summary = index.get("summary", {})
        print(f"ablation groups: {summary.get('groups')} "
              f"(present {summary.get('present')} / partial {summary.get('partial')} / "
              f"missing {summary.get('missing')})")
        for group in index.get("groups", []):
            counts = group["counts"]
            print(f"  {group['group_id']:22s} {group['availability']:8s} "
                  f"modalities {counts['modalities_present']}/{counts['modalities_missing']} "
                  f"fields={len(group['fields']):4d} files={counts['files']:5d} "
                  f"perm={group['permission']:8s} | {group['question']}")
            if group.get("missing"):
                for row in group["missing"]:
                    print(f"      missing {row['modality_id']}: {row['unlock_condition']}")
        if not args.groups:
            return EXIT_OK

    if not args.groups:
        print("ERROR: nothing to do: pass --groups, --list-groups, --summary or --check",
              file=sys.stderr)
        return EXIT_USAGE

    fragments = [item.strip() for item in args.fragments.split(",") if item.strip()] \
        if args.fragments else None
    exit_code = EXIT_OK
    for group_id in [item.strip() for item in args.groups.split(",") if item.strip()]:
        try:
            group = find_group(index, group_id)
        except KeyError:
            print(f"ERROR: unknown group {group_id!r}; known: {', '.join(group_ids(index))}",
                  file=sys.stderr)
            exit_code = EXIT_USAGE
            continue
        report = load_group(package, group, manifest, fragments=fragments,
                            max_files=args.max_files)
        print_report(report, verbose=args.verbose, max_fields=args.max_fields)
        print_tensor_shapes(report)
        if group["availability"] == "missing":
            print(f"  NOTE: this group is declared missing; unlock condition(s): "
                  f"{[row['unlock_condition'] for row in group.get('missing', [])]}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
