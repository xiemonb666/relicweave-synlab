#!/usr/bin/env python
"""Plane-backend bit-for-bit regression: same mother, same seed, before/after the cut.py rewrite.

Builds ``plane_shared_cut`` (and the zero-amplitude rough cut, which must regress to the plane)
through the production path twice -- once against the **live** ``synlab.fracture.cut`` and once
against the frozen pre-fix snapshot ``data/a12_reports/cutfix/baseline_src`` -- and compares

* ``mesh_hash`` of the cutter body,
* the raw vertex array (``np.array_equal``, bitwise) and the face array,
* the sorted fragment volumes and their per-fragment vertex/face hashes,
* the reported ``gap_p95``/conservation numbers of a real fracture event.

The baseline snapshot is imported under a private package name so both revisions can coexist in
one process.

Output: ``data/a12_reports/cutfix/plane_regression.json``.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
TESTS_A12 = Path(__file__).resolve().parents[2]
for _path in (str(REPO_ROOT), str(TESTS_A12)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from synlab.seeds import make_rng  # noqa: E402

BACKEND_PLANE = "plane_shared_cut"
BACKEND_ROUGH = "rough_shared_cut"


def _sha(array: np.ndarray) -> str:
    a = np.ascontiguousarray(array)
    h = hashlib.sha256()
    h.update(str(a.dtype.str).encode())
    h.update(str(a.shape).encode())
    h.update(a.tobytes())
    return "sha256:" + h.hexdigest()


def load_baseline_package(tmp: Path):
    """Import the frozen ``synlab`` tree under the name ``synlab_baseline``."""
    src = REPO_ROOT / "data" / "a12_reports" / "cutfix" / "baseline_src" / "synlab"
    dst = tmp / "synlab_baseline"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    spec = importlib.util.spec_from_file_location(
        "synlab_baseline", dst / "__init__.py",
        submodule_search_locations=[str(dst)])
    module = importlib.util.module_from_spec(spec)
    sys.modules["synlab_baseline"] = module
    spec.loader.exec_module(module)
    return module


def restore_baseline_files() -> list[tuple[Path, Path]]:
    """Temporarily install the frozen ``cut.py``/``morphology.py`` into the live package."""
    live_dir = REPO_ROOT / "synlab" / "fracture"
    frozen_dir = REPO_ROOT / "data" / "a12_reports" / "cutfix" / "baseline_src" / "synlab" / "fracture"
    saved: list[tuple[Path, Path]] = []
    for name in ("cut.py", "morphology.py"):
        live = live_dir / name
        frozen = frozen_dir / name
        if not frozen.exists():
            continue
        backup = live.with_suffix(".cutfix_backup")
        shutil.copy2(live, backup)
        shutil.copy2(frozen, live)
        saved.append((live, backup))
    return saved


def restore_live(saved: list[tuple[Path, Path]]) -> None:
    for live, backup in saved:
        shutil.copy2(backup, live)
        backup.unlink()


def purge_modules() -> None:
    for name in [n for n in sys.modules if n.startswith("synlab")]:
        del sys.modules[name]


def build_cutter(backend: str, rms: float, *, tag: str) -> dict[str, Any]:
    # imported *inside* the function on purpose: the module cache is purged between the before and
    # after runs so each run really uses its own source tree (same for the spec class identity,
    # which ``api._coerce_spec`` compares by type).
    import fixtures as fx
    from synlab.fracture.api import make_closed_cutter
    from synlab.fracture.spec import FractureSpec

    mother = fx.thin_bowl_mother()
    spec = FractureSpec(backend=backend, target_rms_mm=rms)
    rng = make_rng(20261001, "cutfix_plane_regression", tag)
    cutter = make_closed_cutter(mother, spec, rng)
    mesh = cutter.mesh
    verts = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    from synlab.fracture.booleans import mesh_hash

    return {
        "mesh_hash": mesh_hash(mesh),
        "vertices_sha256": _sha(verts),
        "faces_sha256": _sha(faces),
        "vertices": verts,
        "faces": faces,
        "volume_mm3": float(mesh.volume),
        "realized_error_mm": float(cutter.realized_error_mm),
        "requested_error_mm": float(cutter.requested_error_mm),
        "report": {k: v for k, v in dict(cutter.meta).items()
                   if k in ("cells", "leaf_level", "triangles", "vertices", "top_triangles",
                            "bottom_triangles", "side_triangles", "degenerate_faces",
                            "edge_use_histogram", "cutter_local_hash", "realized_error_mm")},
    }


def build_event(*, tag: str) -> dict[str, Any]:
    """A real plane fracture event: fragment volumes/hashes + the audit's gap and conservation."""
    import fixtures as fx
    from synlab.fracture.api import fracture_event
    from synlab.fracture.spec import BACKEND_PLANE as PLANE
    from synlab.fracture.spec import FractureSpec

    mother = fx.thin_bowl_mother()
    spec = FractureSpec(backend=PLANE)
    rng = make_rng(20261001, "cutfix_plane_event", tag)
    result = fracture_event(mother, spec, rng, event_id="cutfix-regression-0001")
    fragments = list(getattr(result, "fragments", []) or [])
    rows = []
    for frag in fragments:
        v = np.asarray(frag.mesh.vertices, dtype=np.float64)
        f = np.asarray(frag.mesh.faces, dtype=np.int64)
        rows.append({"fragment_id": str(getattr(frag, "fragment_id", "?")),
                     "volume_mm3": float(frag.mesh.volume),
                     "vertices_sha256": _sha(v), "faces_sha256": _sha(f),
                     "vertices": int(v.shape[0]), "faces": int(f.shape[0])})
    rows.sort(key=lambda r: r["fragment_id"])
    audit = None
    for attr in ("audit", "qa", "report"):
        value = getattr(result, attr, None)
        if isinstance(value, dict):
            audit = {k: value[k] for k in value
                     if k in ("passed", "gap_p95_mm", "volume_rel_diff", "overlap_ratio",
                              "source_coverage", "ambiguous_area_ratio_total",
                              "normal_angle_p95_deg", "failures")}
            break
    return {"fragments": rows, "audit": audit,
            "fragment_volume_sum_mm3": float(sum(r["volume_mm3"] for r in rows))}


def states(backends: list[tuple[str, float]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for backend, rms in backends:
        tag = f"{backend}_{rms}"
        cutter = build_cutter(backend, rms, tag=tag)
        event = build_event(tag=tag)
        out[tag] = {"cutter": {k: v for k, v in cutter.items()
                               if k not in ("vertices", "faces")},
                    "vertices": cutter["vertices"], "faces": cutter["faces"],
                    "event": event}
    return out


def compare(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    report: dict[str, Any] = {}
    for key in sorted(set(a) | set(b)):
        left, right = a.get(key), b.get(key)
        if left is None or right is None:
            report[key] = {"comparable": False}
            continue
        same_vertices = np.array_equal(left["vertices"], right["vertices"])
        same_faces = np.array_equal(left["faces"], right["faces"])
        entry = {
            "mesh_hash_before": left["cutter"]["mesh_hash"],
            "mesh_hash_after": right["cutter"]["mesh_hash"],
            "mesh_hash_equal": left["cutter"]["mesh_hash"] == right["cutter"]["mesh_hash"],
            "vertices_bitwise_equal": bool(same_vertices),
            "faces_bitwise_equal": bool(same_faces),
            "vertices_sha256_equal":
                left["cutter"]["vertices_sha256"] == right["cutter"]["vertices_sha256"],
            "faces_sha256_equal":
                left["cutter"]["faces_sha256"] == right["cutter"]["faces_sha256"],
            "volume_before_mm3": left["cutter"]["volume_mm3"],
            "volume_after_mm3": right["cutter"]["volume_mm3"],
            "realized_error_before_mm": left["cutter"]["realized_error_mm"],
            "realized_error_after_mm": right["cutter"]["realized_error_mm"],
            "report_equal": left["cutter"]["report"] == right["cutter"]["report"],
        }
        frag_before = left["event"]["fragments"]
        frag_after = right["event"]["fragments"]
        entry["fragment_count_before"] = len(frag_before)
        entry["fragment_count_after"] = len(frag_after)
        entry["fragment_rows_equal"] = frag_before == frag_after
        names = sorted({r["fragment_id"] for r in frag_before}
                       | {r["fragment_id"] for r in frag_after})
        by_before = {r["fragment_id"]: r for r in frag_before}
        by_after = {r["fragment_id"]: r for r in frag_after}
        diffs = []
        for name in names:
            lb, rb = by_before.get(name), by_after.get(name)
            if lb is None or rb is None:
                diffs.append({"fragment_id": name, "missing": "before" if lb is None else "after"})
                continue
            if (lb["vertices_sha256"] != rb["vertices_sha256"]
                    or lb["faces_sha256"] != rb["faces_sha256"]
                    or lb["volume_mm3"] != rb["volume_mm3"]):
                diffs.append({"fragment_id": name,
                              "volume_before": lb["volume_mm3"], "volume_after": rb["volume_mm3"],
                              "vertices_equal": lb["vertices_sha256"] == rb["vertices_sha256"],
                              "faces_equal": lb["faces_sha256"] == rb["faces_sha256"]})
        entry["fragment_differences"] = diffs
        entry["event_audit_before"] = left["event"]["audit"]
        entry["event_audit_after"] = right["event"]["audit"]
        entry["event_audit_equal"] = left["event"]["audit"] == right["event"]["audit"]
        entry["all_identical"] = bool(
            entry["vertices_bitwise_equal"] and entry["faces_bitwise_equal"]
            and entry["report_equal"] and not diffs
            and entry["fragment_count_before"] == entry["fragment_count_after"])
        report[key] = entry
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="data/a12_reports/cutfix/plane_regression.json")
    args = parser.parse_args()

    backends = [(BACKEND_PLANE, 0.0), (BACKEND_ROUGH, 0.0)]
    original = REPO_ROOT / "synlab" / "fracture" / "cut.py"
    live_copy = Path(tempfile.gettempdir()) / "cutfix_live_cut.py"
    shutil.copy2(original, live_copy)

    purge_modules()
    after = states(backends)
    purge_modules()

    saved = restore_baseline_files()
    try:
        purge_modules()
        before = states(backends)
    finally:
        restore_live(saved)
        purge_modules()

    comparison = compare(before, after)
    payload = {
        "note": ("before = frozen pre-fix sources installed temporarily; after = live tree.  Both "
                 "runs use the same mother fixture, the same master seed and the same spec, so any "
                 "difference is caused by the cut.py rewrite alone."),
        "backends": [{"backend": b, "target_rms_mm": r} for b, r in backends],
        "comparison": comparison,
    }
    out = REPO_ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1, default=str),
                   encoding="utf-8")
    print(f"[written] {out}")
    for key, entry in comparison.items():
        if not entry.get("comparable", True):
            print(f"  {key}: not comparable")
            continue
        print(f"  {key}: mesh_hash_equal={entry['mesh_hash_equal']} "
              f"vertices_bitwise={entry['vertices_bitwise_equal']} "
              f"faces_bitwise={entry['faces_bitwise_equal']} "
              f"report_equal={entry['report_equal']} "
              f"fragments={entry['fragment_count_before']}->{entry['fragment_count_after']} "
              f"frag_rows_equal={entry['fragment_rows_equal']} "
              f"audit_equal={entry['event_audit_equal']} "
              f"all_identical={entry['all_identical']}")
        print(f"      hash {entry['mesh_hash_before']}")
        print(f"      hash {entry['mesh_hash_after']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


