"""Probe: geometric layer combos (L01/L03) -> glaze step numbers (read-only, real code)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from synlab.materials import (  # noqa: E402
    MODE_GEOMETRIC, MODE_SHADING, combo_definition, combo_geometric_layers, combo_ids,
    layer_combo, measure_layer_thickness,
)
from synlab.seeds import make_rng  # noqa: E402

OUT = ROOT / "data/a12_reports/physical_layer/probe_layers.json"

def _jsonable(obj):
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (np.floating, np.integer)):
        return obj.item()
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return repr(obj)

report = {"modes": {"GEOMETRIC": MODE_GEOMETRIC, "SHADING": MODE_SHADING},
          "combos": {}, "thickness": {}}
for cid in combo_ids():
    try:
        definition = _jsonable(combo_definition(cid))
    except Exception as exc:  # noqa: BLE001
        definition = {"error": f"{type(exc).__name__}: {exc}"}
    entry = {"definition": definition}
    try:
        layers = combo_geometric_layers(cid, None, rng=make_rng(20261001, f"combo_{cid}", "layer"))
        entry["n_geometric_layers"] = len(layers)
        entry["geometric_layers"] = [
            {"layer_id": getattr(l, "layer_id", None), "name": getattr(l, "name", None),
             "kind": getattr(l, "kind", None), "thickness_mm": getattr(l, "thickness_mm", None)}
            for l in layers]
    except Exception as exc:  # noqa: BLE001
        entry["geometric_layers_error"] = f"{type(exc).__name__}: {exc}"
    try:
        spec = layer_combo(cid, None, make_rng(20261001, f"combo_{cid}", "layer"))
        entry["layer_combo"] = [
            {"layer_id": getattr(l, "layer_id", None), "name": getattr(l, "name", None),
             "kind": getattr(l, "kind", None), "mode": getattr(l, "mode", None),
             "thickness_mm": getattr(l, "thickness_mm", None)}
            for l in spec]
    except Exception as exc:  # noqa: BLE001
        entry["layer_combo_error"] = f"{type(exc).__name__}: {exc}"
    report["combos"][cid] = entry

# measure_layer_thickness: what does it need?
report["measure_layer_thickness_signature"] = str(measure_layer_thickness.__doc__ or "")[:600]
OUT.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
print("combos:", list(report["combos"]))
for cid, e in report["combos"].items():
    print(cid, "geom_layers:", e.get("n_geometric_layers"),
          [(l["layer_id"], l["name"], l["thickness_mm"]) for l in (e.get("geometric_layers") or [])],
          "combo:", [(l["layer_id"], l["name"], l["mode"], l["thickness_mm"])
                     for l in (e.get("layer_combo") or [])])
