"""Probe 5b: prove plane_normal is honoured, using a freshly built mother."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from synlab.fracture.api import fracture_event  # noqa: E402
from synlab.fracture.spec import FractureSpec  # noqa: E402
from synlab.mothers.api import create_mother  # noqa: E402
from synlab.seeds import make_rng  # noqa: E402


def interface_points(fracture) -> np.ndarray:
    pts = []
    for patch in fracture.interfaces:
        p = getattr(patch, "sample_points_a", None)
        if p is not None and np.asarray(p).size:
            pts.append(np.asarray(p, dtype=np.float64))
    return np.concatenate(pts, axis=0) if pts else np.zeros((0, 3))


def plane_normal(points: np.ndarray) -> np.ndarray | None:
    if points.shape[0] < 3:
        return None
    P = points - points.mean(axis=0)
    _, _, vt = np.linalg.svd(P, full_matrices=False)
    return vt[2] / max(float(np.linalg.norm(vt[2])), 1e-12)


params = {"base_mm": 5.173956834743791, "belly": 0.8044526411931665,
          "depth_ratio": 0.25813382003420415, "diameter_mm": 170.59528695766963,
          "foot_height_ratio": 0.04142833303108983, "foot_ring_ratio": 0.889988267999535,
          "rim_flare": -0.0341073992881093, "wall_mm": 9.324583657218447,
          "warp_amplitude": 0.028333870748001488, "warp_eccentricity_mm": 2.394345260187333,
          "warp_lobes": 2}

t0 = time.perf_counter()
mother = create_mother("V01", "M01", params, make_rng(20261001, "probe", "shape"),
                       mother_id="probe_V01")
print(f"mother built in {time.perf_counter() - t0:.2f}s "
      f"verts={len(mother.mesh.vertices)} bbox={np.round(mother.mesh.bounds, 2).tolist()}")

center = np.asarray(mother.mesh.vertices, dtype=np.float64).mean(axis=0)
cases = {
    "default(body-hash)": FractureSpec(backend="plane_shared_cut"),
    "explicit +Z": FractureSpec(backend="plane_shared_cut",
                                plane_normal=np.array([0.0, 0.0, 1.0]),
                                plane_point=center),
    "explicit +X": FractureSpec(backend="plane_shared_cut",
                                plane_normal=np.array([1.0, 0.0, 0.0]),
                                plane_point=center),
    "explicit tilted": FractureSpec(
        backend="plane_shared_cut",
        plane_normal=np.array([0.57735027, 0.57735027, 0.57735027]),
        plane_point=center),
}
out = {}
for name, spec in cases.items():
    t0 = time.perf_counter()
    fr = fracture_event(mother, spec, make_rng(20261001, "probe", "cut"),
                        event_id=f"probe_{name.replace(' ', '_')}")
    pts = interface_points(fr)
    n = plane_normal(pts)
    out[name] = None if n is None else n.tolist()
    if n is None or spec.plane_normal is None:
        d = None
    else:
        want = np.asarray(spec.plane_normal, dtype=np.float64)
        want = want / np.linalg.norm(want)
        d = float(np.degrees(np.arccos(np.clip(abs(float(np.dot(n, want))), -1.0, 1.0))))
    print(f"{name:20s} {time.perf_counter()-t0:6.2f}s frags={len(fr.fragments)} "
          f"ifaces={len(fr.interfaces)} n={None if n is None else np.round(n,5).tolist()} "
          f"angle_to_requested={None if d is None else round(d,5)} deg")
print(json.dumps(out, indent=1))

