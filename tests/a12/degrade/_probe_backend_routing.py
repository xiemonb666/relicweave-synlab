"""S12 probe: what each of the 31 axes *declares* vs which backend actually runs.

Run::

    .venv\\Scripts\\python.exe tests\\a12\\degrade\\_probe_backend_routing.py

Two routes are probed per axis/level:

* ``degrade`` -- ``synlab.degrade.api.apply_axis`` (the operator audit / 155-level contract route);
* ``physical`` -- ``synlab.physical.api.apply_damage`` (the production route used by
  ``synlab/pipeline.py:1705``).

Only the P family crosses the two routes; I/G/X have a single implementation each.  Nothing is
written; the report is printed as JSON.
"""

from __future__ import annotations

import json
import sys
from typing import Any

import numpy as np

from synlab.degrade.api import probe_sources
from synlab.degrade.axes import physical_fragment
from synlab.degrade.registry import AXIS_REGISTRY
from synlab.physical.api import apply_damage
from synlab.schemas.spec import AXIS_IDS as ALL_AXIS_IDS


def _degrade_backend(measurement: Any) -> dict[str, Any]:
    extra = dict(getattr(measurement, "extra", None) or {})
    measured = dict(getattr(measurement, "measured", None) or {})
    detail_keys = sorted(k for k in extra if "backend" in k or "grid" in k)
    return {
        "realized": bool(getattr(measurement, "realized", False)),
        "failure_code": getattr(measurement, "failure_code", None),
        "measured_backend_keys": detail_keys,
        "grid_spacing_mm": measured.get("grid_spacing_mm"),
        "grid_spacing_requested_mm": measured.get("grid_spacing_requested_mm"),
        "roi_external_drift_mm": measured.get("roi_external_drift_mm"),
        "lost_volume_mm3": measured.get("lost_volume_mm3"),
        "watertight": measured.get("watertight"),
        "drift_keys": sorted(k for k in measured if "drift" in k),
    }


def _physical_backend(recipe: Any, source: Any, fragment: Any) -> dict[str, Any]:
    try:
        result = apply_damage(source, fragment, recipe, rng=None)
    except Exception as exc:  # noqa: BLE001 - a probe reports the code instead of crashing
        return {"error": f"{type(exc).__name__}: {exc}",
                "code": getattr(getattr(exc, "code", None), "value", None)}
    details = dict((result.meta or {}).get("details") or {})
    measured = dict((result.meta or {}).get("measured") or {})
    return {
        "damage_backend": details.get("damage_backend"),
        "backend_selection": details.get("backend_selection"),
        "grid_spacing_mm": measured.get("grid_spacing_mm"),
        "roi_external_drift_mm": measured.get("roi_external_drift_mm"),
        "drift_keys": sorted(k for k in measured if "drift" in k),
        "watertight": measured.get("watertight"),
        "status": (result.qa or {}).get("status"),
        "failure_code": (result.qa or {}).get("failure_code"),
    }


def main() -> int:
    sources = probe_sources()
    out: dict[str, Any] = {"axes": [], "routes": {}}
    out_path = (sys.argv[1] if len(sys.argv) > 1
                else "data/a12_reports/s12_probe_backend_routing.json")
    for axis_id in ALL_AXIS_IDS:
        operator = AXIS_REGISTRY.get(axis_id)
        family = axis_id[0]
        source = sources[family]
        declared = {
            "axis_id": axis_id,
            "family": family,
            "declared_backend": "narrowband" if getattr(operator, "NARROWBAND", False)
            else "global_sdf" if family == "P" else f"degrade.axes.{type(operator).__name__}",
            "declared_narrowband": bool(getattr(operator, "NARROWBAND", False)),
            "stage": operator.STAGE,
            "default_variant": operator.default_variant,
            "spacing_from": getattr(operator, "SPACING_FROM", None),
            "grid": dict(getattr(operator, "GRID", {}) or {}),
            "observed": [],
        }
        for level in (1, 2, 3, 4):
            row: dict[str, Any] = {"level": level}
            try:
                _ref, measurement = None, None
                from synlab.degrade.api import apply_axis

                _ref, measurement = apply_axis(axis_id, level, source, None,
                                               lineage_id=f"lin_{axis_id}_s12")
                row["degrade"] = _degrade_backend(measurement)
            except Exception as exc:  # noqa: BLE001
                row["degrade"] = {"error": f"{type(exc).__name__}: {exc}",
                                  "code": getattr(getattr(exc, "code", None), "value", None)}
            if family == "P":
                try:
                    fragment = physical_fragment(source)
                    basis = operator.sample_basis(
                        {"source": source, "lineage_id": f"lin_{axis_id}_s12",
                         "fragment_id": str(getattr(fragment, "fragment_id", "fragment")),
                         "master_seed": 1234},
                        np.random.default_rng(1234), operator.default_variant)
                    recipe = operator.recipe(level=level, variant=operator.default_variant,
                                             params=operator.params_for(level, operator.default_variant),
                                             basis=basis, fragment=fragment, source=source)
                    row["physical"] = _physical_backend(recipe, source, fragment)
                    row["physical"]["recipe_grid"] = dict(recipe.grid or {})
                except Exception as exc:  # noqa: BLE001
                    row["physical"] = {"error": f"{type(exc).__name__}: {exc}"}
            declared["observed"].append(row)
        out["axes"].append(declared)
        print(f".. {axis_id} done", file=sys.stderr)
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(out, handle, indent=2, sort_keys=True, default=str)
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
