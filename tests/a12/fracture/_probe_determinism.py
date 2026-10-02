"""Is the refined cutter tree itself reproducible across two in-process builds?"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
TESTS_A12 = Path(__file__).resolve().parents[2]
for _path in (str(REPO_ROOT), str(TESTS_A12)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import _probe_rough_topology as probe  # noqa: E402


def signature(tag: str, out: dict) -> dict:
    tree, leaves, top_faces, top_edge_use, vertices, top_index = out
    payload = json.dumps({
        "leaves": sorted([list(c) for c in leaves]),
        "faces": [list(map(int, f)) for f in top_faces],
        "verts": [[round(float(x), 12) for x in v] for v in vertices],
    }).encode()
    undirected = {}
    for (a, b), uses in top_edge_use.items():
        key = (min(int(a), int(b)), max(int(a), int(b)))
        undirected[key] = undirected.get(key, 0) + uses
    return {
        "tag": tag,
        "cells": len(leaves),
        "faces": len(top_faces),
        "verts": len(vertices),
        "cells_sha": hashlib.sha256(
            json.dumps(sorted([list(c) for c in leaves])).encode()).hexdigest()[:16],
        "faces_sha": hashlib.sha256(
            json.dumps([list(map(int, f)) for f in top_faces]).encode()).hexdigest()[:16],
        "verts_sha": hashlib.sha256(
            json.dumps([[round(float(x), 12) for x in v] for v in vertices]).encode()
        ).hexdigest()[:16],
        "edge_use_histogram": {str(k): int(v)
                               for k, v in sorted(__import__("collections").Counter(
                                   undirected.values()).items())},
        "height_field_bands_sha": "",
        "leaf_sample": sorted([list(c) for c in leaves])[:5],
    }


def main() -> int:
    built, info, basis, height = probe.build("box", 0.05, 0.01)
    first = signature("first", probe.top_surface(basis, height, 0.01))
    second = signature("second", probe.top_surface(basis, height, 0.01))
    # third: rebuild the height field from scratch with the same seed
    built2, info2, basis2, height2 = probe.build("box", 0.05, 0.01)
    third = signature("third", probe.top_surface(basis2, height2, 0.01))
    out = {"first": first, "second": second, "third": third,
           "same_in_process": first["faces_sha"] == second["faces_sha"],
           "same_across_build": first["faces_sha"] == third["faces_sha"],
           "hash_seed": __import__("os").environ.get("PYTHONHASHSEED", "unset")}
    text = json.dumps(out, indent=2)
    Path(r"data/a12_reports/_fprec_determinism.json").write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
