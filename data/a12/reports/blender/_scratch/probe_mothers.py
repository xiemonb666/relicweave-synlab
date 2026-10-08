"""Scratch probe: build real mothers (V01/V13) and report the renderable target facts.

Not part of the library; lives under the report directory because that is the allowed
scratch area for this task.  Usage::

    .venv\\Scripts\\python.exe data/a12/reports/blender/_scratch/probe_mothers.py
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

from synlab.mothers.api import create_mother, default_params
from synlab.seeds import make_rng

OUT = Path(__file__).with_name("probe_mothers.json")


def main() -> int:
    report: dict[str, object] = {"mothers": []}
    for vessel_id in ("V01", "V13"):
        t0 = time.perf_counter()
        rng = make_rng(20261001, "probe", vessel_id)
        try:
            mother = create_mother(vessel_id, "M01", default_params(vessel_id), rng,
                                   mother_id=f"{vessel_id}-probe")
        except Exception as exc:  # noqa: BLE001 - the probe reports what happened
            report["mothers"].append({"vessel_id": vessel_id,
                                      "error": f"{type(exc).__name__}: {exc}"})
            continue
        tags = np.asarray(mother.face_surface_tag, dtype=np.int64)
        uniq, counts = np.unique(tags, return_counts=True)
        entry = {
            "vessel_id": vessel_id,
            "seconds": time.perf_counter() - t0,
            "n_faces": int(mother.n_faces),
            "n_vertices": int(np.asarray(mother.mesh.vertices).shape[0]),
            "bbox_mm": [float(v) for v in (mother.mesh.bounds[1] - mother.mesh.bounds[0])],
            "center_mm": [float(v) for v in mother.mesh.bounds.mean(axis=0)],
            "watertight": bool(mother.mesh.is_watertight),
            "surface_tag_names": {str(k): v for k, v in mother.surface_tag_names.items()},
            "tag_histogram": {int(k): int(c) for k, c in zip(uniq, counts)},
            "params": {k: (v if isinstance(v, (int, float, str, bool, type(None)))
                           else str(v)) for k, v in dict(mother.params).items()},
        }
        report["mothers"].append(entry)
    OUT.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True)[:4000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
