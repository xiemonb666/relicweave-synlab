"""Archive or restore shared project sources without bundling solver runtimes.

This is a handover utility, not a development or solver launcher. Restoration
checks every conflict before copying and never replaces a differing file.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil

REPO = Path(__file__).resolve().parents[2]
SOURCE_EXT = {".py", ".jl", ".ps1", ".sh", ".bat", ".cmd", ".js", ".mjs",
              ".ts", ".tsx", ".toml", ".yaml", ".yml", ".geo", ".dat"}
EVIDENCE_EXT = SOURCE_EXT | {".md", ".json", ".jsonl", ".txt", ".csv", ".npz",
                             ".png", ".jpg", ".svg", ".step", ".msh"}
SKIP_PARTS = {".git", ".venv", "venv", "__pycache__", "node_modules", "site-packages",
              ".pytest_cache", ".mplconfig", "_temp_matplotlib", "depot", "extract",
              "sdk", "downloads", "source-v5.0.7", "share", "lib", "Lib", "DLLs"}
MAX_FILE = 10 * 1024 * 1024


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def selected_files(workspace: Path):
    groups = [("docs/continuation", EVIDENCE_EXT), ("docs/a12", EVIDENCE_EXT),
              ("experiments", EVIDENCE_EXT), ("data", SOURCE_EXT),
              ("tmp", SOURCE_EXT), ("SynLab", SOURCE_EXT), ("VFtmp", SOURCE_EXT),
              ("relicweave-synlab/tmp", SOURCE_EXT),
              ("relicweave-synlab/data", SOURCE_EXT),
              ("relicweave-synlab/tmp/review_20261004/implementation/cohesive_event_probe_20261004/coarse654_20261004_01", EVIDENCE_EXT)]
    found = {}
    for name, extensions in groups:
        base = workspace / name
        if not base.exists():
            continue
        for path in iter_files(base):
            if (not path.is_file() or path.is_symlink() or path.suffix.lower() not in extensions
                    or any(part in SKIP_PARTS for part in path.relative_to(base).parts)
                    or path.stat().st_size > MAX_FILE):
                continue
            found[path.relative_to(workspace).as_posix()] = path
    # Preserve source-level support at the shared root, including old one-off scripts.
    for path in workspace.iterdir():
        if path.is_file() and path.suffix.lower() in SOURCE_EXT | {".md"}:
            found[path.name] = path
    # Metadata/install scripts document dependencies; packages, SDKs and wheels stay external.
    dep = workspace / "third_party"
    if dep.exists():
        for path in iter_files(dep, max_depth=4):
            rel = path.relative_to(dep)
            if (not path.is_file() or path.is_symlink() or len(rel.parts) > 4
                    or any(part in SKIP_PARTS or part.startswith("LibreOffice-") for part in rel.parts)
                    or path.suffix.lower() not in {".json", ".md", ".txt", ".ps1", ".sh"}
                    or path.stat().st_size > 1024 * 1024):
                continue
            found[path.relative_to(workspace).as_posix()] = path
    return sorted(found.items())


def iter_files(base: Path, max_depth: int | None = None):
    for folder, directories, names in os.walk(base, followlinks=False):
        here = Path(folder)
        depth = len(here.relative_to(base).parts)
        directories[:] = [name for name in directories
                          if name not in SKIP_PARTS and not name.startswith("LibreOffice-")
                          and not (here / name).is_symlink()]
        if max_depth is not None and depth >= max_depth-1:
            directories[:] = []
        for name in names:
            candidate = here / name
            try:
                if candidate.is_symlink() or not candidate.is_file():
                    continue
            except OSError:
                # Linux-runtime reparse points are not portable Windows files.
                continue
            yield candidate


def archive(workspace: Path, target: Path):
    workspace, target = workspace.resolve(), target.resolve()
    if workspace == target or workspace in target.parents and target.name != "workspace_support":
        raise ValueError("Archive target must be the dedicated workspace_support directory")
    records = []
    for rel, source in selected_files(workspace):
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
        sha = digest(source)
        if digest(dest) != sha:
            raise RuntimeError(f"Archive hash mismatch: {rel}")
        records.append({"workspace_relative_path": rel, "bytes": source.stat().st_size,
                        "sha256": sha})
    result = {"schema": "shardforge.shared_workspace_archive.v1", "as_of": "2026-10-16",
              "scope": "Shared project sources and small evidence; solver runtimes and large raw data are excluded",
              "file_count": len(records), "bytes": sum(x["bytes"] for x in records),
              "files": records, "manifest_self_hash": "OMITTED"}
    (target / "archive_manifest.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "files"}))


def restore(archive_dir: Path, workspace: Path, dry_run: bool):
    archive_dir, workspace = archive_dir.resolve(), workspace.resolve()
    data = json.loads((archive_dir / "archive_manifest.json").read_text(encoding="utf-8"))
    if data.get("schema") != "shardforge.shared_workspace_archive.v1":
        raise ValueError("Unsupported shared archive schema")
    operations, conflicts = [], []
    for record in data["files"]:
        rel = Path(record["workspace_relative_path"])
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError("Unsafe archive-relative path")
        src, dst = (archive_dir / rel).resolve(), (workspace / rel).resolve()
        if not src.is_relative_to(archive_dir) or not dst.is_relative_to(workspace):
            raise ValueError("Archive path escapes its declared root")
        if not src.is_file() or src.stat().st_size != record["bytes"] or digest(src) != record["sha256"]:
            raise ValueError(f"Archive file integrity failed: {rel}")
        if dst.exists():
            if not dst.is_file() or digest(dst) != record["sha256"]:
                conflicts.append(rel.as_posix())
        else:
            operations.append((src, dst))
    if conflicts:
        raise FileExistsError("Restoration conflicts; nothing copied: " + ", ".join(conflicts[:20]))
    if not dry_run:
        for src, dst in operations:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    print(json.dumps({"dry_run": dry_run, "files_to_copy": len(operations),
                      "unchanged_files": len(data["files"])-len(operations), "solver_launched": False}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    a = sub.add_parser("archive")
    a.add_argument("--workspace", type=Path, default=REPO.parent)
    a.add_argument("--target", type=Path, default=REPO / "workspace_support")
    r = sub.add_parser("restore")
    r.add_argument("--archive", type=Path, default=REPO / "workspace_support")
    r.add_argument("--workspace", type=Path, default=REPO.parent)
    r.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.action == "archive":
        archive(args.workspace, args.target)
    else:
        restore(args.archive, args.workspace, args.dry_run)


if __name__ == "__main__":
    main()
