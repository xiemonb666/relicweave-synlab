from __future__ import annotations

import hashlib
import json
import runpy
import sys
from pathlib import Path

from synlab.degrade.api import apply_axis
from synlab.degrade.sources import mesh_geometry_hash
from synlab.schemas.runtime import CleanTruth


ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
AUDIT_SCRIPT = ROOT / "tmp" / "review_20261003" / "implementation" / "degradation_audit" / "probe_degradation_axes.py"


def jsonable(value):
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    try:
        import numpy as np

        if isinstance(value, np.ndarray):
            return value.tolist()
        if isinstance(value, np.generic):
            return value.item()
    except ImportError:
        pass
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def clean_truth(fragment_id: str) -> CleanTruth:
    return CleanTruth(
        mother_id="appearance_finish_probe_mother",
        event_id="appearance_finish_probe_event",
        version=1,
        relations={},
        interfaces=[],
        correspondence=[],
        event_tree={"event_id": "appearance_finish_probe_event", "events": []},
        qa={"pass": True, "truth_incomplete": False},
        meta={"truth_hash": "sha256:appearance-finish-probe-clean-truth",
              "fragment_ids": [fragment_id], "truth_incomplete": False},
    )


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    import numpy as np

    OUT.mkdir(parents=True, exist_ok=True)
    probe = runpy.run_path(str(AUDIT_SCRIPT), run_name="appearance_finish_probe_fixture")
    mesh, top, base_source = probe["small_box"]()
    truth = clean_truth(base_source.get("fragment").fragment_id)
    source = base_source.with_payload(clean_truth=truth)
    original_hash = source.content_hash()
    original_mesh_hash = mesh_geometry_hash(mesh)
    results = []

    for order in (("P05", "P06"), ("P06", "P05")):
        for strength, level in (("weak", 1), ("strong", 4)):
            current = source
            step_rows = []
            for axis_id in order:
                result, measurement = apply_axis(
                    axis_id, level, current, None,
                    lineage_id=f"appearance_finish_{'_'.join(order)}_{strength}",
                    commit=False,
                )
                current = result.as_bundle()
                physical = current.get("physical_result")
                step_rows.append({
                    "axis": axis_id,
                    "level": level,
                    "measured": jsonable(measurement.measured),
                    "extra": jsonable(measurement.extra),
                    "physical_details": jsonable((physical.meta or {}).get("details", {})),
                    "physical_measured": jsonable((physical.meta or {}).get("measured", {})),
                })
            appearance = current.get("appearance")
            image_name = f"{'_then_'.join(order)}_{strength}.png"
            probe["raster_top"](
                current.get("mesh"), np.asarray(appearance["texel_albedo"], dtype=np.float64),
                top, OUT / image_name, f"{' then '.join(order)} / {strength} L{level}",
            )
            removed = np.asarray(appearance.get("paint_mask_removed", []), dtype=bool)
            pattern = np.asarray(appearance.get("pattern_region", []), dtype=bool)
            area = np.asarray(appearance.get("texel_area_mm2", []), dtype=np.float64)
            results.append({
                "scenario": f"{'_then_'.join(order)}_{strength}",
                "order": list(order),
                "strength": strength,
                "level": level,
                "image": image_name,
                "geometry_hash_unchanged": mesh_geometry_hash(current.get("mesh")) == original_mesh_hash,
                "source_bundle_unchanged": source.content_hash() == original_hash,
                "clean_truth_same_object": current.get("clean_truth") is truth,
                "paint_removed_area_mm2": float(area[removed].sum()) if removed.size else 0.0,
                "original_pattern_area_mm2": float(area[pattern].sum()) if pattern.size else 0.0,
                "current_visible_pattern_area_mm2": float(area[pattern & ~removed].sum())
                if pattern.size and removed.size else float(area[pattern].sum()) if pattern.size else 0.0,
                "steps": step_rows,
            })

    source_files = [
        ROOT / "synlab" / "physical" / "fields.py",
        ROOT / "synlab" / "physical" / "operators.py",
        ROOT / "synlab" / "degrade" / "axes.py",
        ROOT / "tests" / "a12" / "operators" / "test_appearance_continuity_20261003.py",
        Path(__file__).resolve(),
        AUDIT_SCRIPT,
    ]
    report = {
        "fixture": "synthetic subdivided small box with face appearance channels",
        "source_content_hash": original_hash,
        "source_mesh_geometry_hash": original_mesh_hash,
        "source_unchanged_after_all_chains": source.content_hash() == original_hash,
        "chains": results,
        "scope_note": "P05/P06 are appearance-only in these chains. P08 was tested only for lower-tail endpoint direction.",
    }
    (OUT / "appearance_chains.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    (OUT / "argv.json").write_text(
        json.dumps({"argv": sys.argv}, indent=2), encoding="utf-8")
    (OUT / "source_sha256.json").write_text(json.dumps(
        {str(path.relative_to(ROOT)): sha256(path) for path in source_files},
        indent=2, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
