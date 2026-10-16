#!/usr/bin/env python
"""Stage-by-stage cost probe for one fracture event (time + peak RSS per stage)."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

MASTER_SEED = 20261001
LINEAGE_ID = "a12_demo"


def rss_mb() -> float:
    try:
        import resource

        return float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) / 1024.0
    except Exception:  # noqa: BLE001 - Windows has no resource module
        try:
            import ctypes
            import ctypes.wintypes

            class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = [("cb", ctypes.wintypes.DWORD),
                            ("PageFaultCount", ctypes.wintypes.DWORD),
                            ("PeakWorkingSetSize", ctypes.c_size_t),
                            ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                            ("PagefileUsage", ctypes.c_size_t),
                            ("PeakPagefileUsage", ctypes.c_size_t)]

            counters = PROCESS_MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
            ctypes.windll.psapi.GetProcessMemoryInfo(
                ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
            return float(counters.PeakWorkingSetSize) / (1024.0 * 1024.0)
        except Exception:  # noqa: BLE001
            return -1.0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vessel", default="V18")
    parser.add_argument("--backend", default="plane_shared_cut")
    parser.add_argument("--demo-root", default=str(REPO_ROOT / "data" / "a12_demo"))
    args = parser.parse_args()

    import trimesh

    from synlab.fracture.api import make_closed_cutter
    from synlab.fracture.booleans import (
        SourceResolver,
        boolean_difference,
        boolean_intersection,
        tag_source,
    )
    from synlab.fracture.event import _link_interfaces
    from synlab.fracture.fragment import split_components
    from synlab.fracture.spec import FractureSpec
    from synlab.mothers.api import load_mother
    from synlab.seeds import make_rng
    from synlab.storage.store import AssetStore

    started = time.time()

    def mark(label: str) -> None:
        print(f"[{time.time() - started:7.2f}s rss={rss_mb():7.1f}MB] {label}", flush=True)

    root = Path(args.demo_root)
    manifest = json.loads((root / "demo_manifest.json").read_text(encoding="utf-8"))
    entry = next(e for e in manifest["entries"] if e["entry_id"] == f"mother:{args.vessel}")
    mother = load_mother(AssetStore(root / "store"), str(entry["asset_id"]))
    mark(f"mother loaded faces={len(mother.mesh.faces)}")

    spec = FractureSpec(backend=args.backend, target_rms_mm=0.05)
    rng = make_rng(MASTER_SEED, LINEAGE_ID, "fracture", args.vessel, args.backend)
    cutter = make_closed_cutter(mother, spec, rng)
    mark(f"cutter built faces={len(cutter.mesh.faces)}")

    source_mother = tag_source(trimesh.Trimesh(vertices=np.asarray(mother.mesh.vertices),
                                               faces=np.asarray(mother.mesh.faces), process=False),
                               1.0, "mother")
    source_cutter = tag_source(trimesh.Trimesh(vertices=np.asarray(cutter.mesh.vertices),
                                               faces=np.asarray(cutter.mesh.faces), process=False),
                               2.0, "cutter")
    minus = boolean_intersection([source_mother, source_cutter], label="M_minus")
    plus = boolean_difference([source_mother, source_cutter], label="M_plus")
    mark(f"booleans done minus={minus.n_faces} plus={plus.n_faces}")

    resolver = SourceResolver([source_mother, source_cutter], tolerance_mm=1.0e-4)
    classifications = {}
    for name, side in (("M_minus", minus), ("M_plus", plus)):
        classification = resolver.classify(side, container=cutter.mesh,
                                           container_tolerance_mm=1.0e-4)
        classification["_faces"] = np.asarray(side.mesh.faces, dtype=np.int64)
        classification["area_faces"] = np.asarray(side.mesh.area_faces, dtype=np.float64)
        classification["mother_mesh_id"] = 1
        classification["cutter_mesh_id"] = 2
        classifications[name] = classification
        distance = np.asarray(classification["vertex_container_distance_mm"], dtype=np.float64)
        mark(f"classified {name}: ambiguous={int(np.sum(classification['vertex_ambiguous']))} "
             f"on_container={int(np.sum(classification['vertex_on_container']))} "
             f"inside={int(np.sum(classification['vertex_inside_container']))} "
             f"container_dist p50={np.percentile(distance, 50):.6f} "
             f"p95={np.percentile(distance, 95):.4f} max={np.max(distance):.4f}")

    from synlab.fracture.fragment import make_fragment

    fragments = []
    for name, side_tag in (("M_minus", -1), ("M_plus", 1)):
        side = minus if name == "M_minus" else plus
        parts = split_components(side.mesh)
        mark(f"split {name}: {len(parts)} components")
        for index, part in enumerate(parts):
            fragments.append(make_fragment(
                part, fragment_id=f"{name}_{index}", component_id=index, side=side_tag,
                classification=classifications[name], parent_id=None, backend=args.backend,
                cutter_hash="probe", extra_meta={}))
    mark(f"fragments built: {len(fragments)}")

    interfaces, correspondence, unmatched_faces, unmatched_area, matched_overlap = \
        _link_interfaces(
            fragments, minus, plus, classifications, cutter.mesh, sample_target=24,
            ambiguity_tolerance_mm=1.0e-4)
    mark(f"interfaces={len(interfaces)} correspondence={len(correspondence)} "
         f"unmatched={unmatched_faces} unmatched_area={unmatched_area:.3f} "
         f"matched_overlap={matched_overlap:.3f} ratio="
         f"{unmatched_area / max(unmatched_area + matched_overlap, 1e-9):.4f}")

    # where would the unmatched faces be, and how far is their nearest complementary face?
    from scipy.spatial import cKDTree

    from synlab.fracture.event import _face_area_sum, _interface_faces

    if len(fragments) == 2:
        fa, sa, ca = _interface_faces(fragments[0])
        fb, sb, cb = _interface_faces(fragments[1])
        if fa.size and fb.size:
            distances, _ = cKDTree(cb).query(ca, k=1)
            unmatched = distances > 1.0e-3
            local = cutter.basis.to_local(np.asarray(fragments[0].mesh.triangles_center)[fa])
            print(f"[unmatched] A={fa.size} B={fb.size} unmatched={int(np.sum(unmatched))} "
                  f"area={_face_area_sum(fragments[0], fa[unmatched]):.3f}mm2 "
                  f"dist_p50={np.percentile(distances[unmatched], 50) if np.any(unmatched) else 0:.5f} "
                  f"dist_p95={np.percentile(distances[unmatched], 95) if np.any(unmatched) else 0:.5f} "
                  f"|w|_p95={np.percentile(np.abs(local[unmatched, 2]), 95) if np.any(unmatched) else 0:.5f} "
                  f"|w|_all_p95={np.percentile(np.abs(local[:, 2]), 95):.5f}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
