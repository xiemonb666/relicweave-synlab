"""Materialize the repaired P05/P06 outputs on the existing audit fixture."""

from __future__ import annotations

import hashlib
import json
import runpy
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from synlab.degrade.api import apply_axis
from synlab.degrade.sources import mesh_geometry_hash
from synlab.schemas.runtime import CleanTruth


REPO = Path(__file__).resolve().parents[4]
AUDIT_SCRIPT = (REPO / "tmp" / "review_20261003" / "implementation" /
                "degradation_audit" / "probe_degradation_axes.py")
OUT = Path(__file__).resolve().parent
OUT.mkdir(parents=True, exist_ok=True)
LINEAGE = "degradation_audit_small_probe_20261003"


def jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bundle(output: Any) -> Any:
    return output.as_bundle() if hasattr(output, "as_bundle") else output


def _physical_truth(bundle: Any) -> dict[str, Any]:
    physical = bundle.get("physical_result")
    truth = getattr(physical, "physical_truth", None)
    return {
        "physical_truth_present": truth is not None,
        "clean_truth_ref": getattr(truth, "clean_truth_ref", None),
        "physical_truth_version": getattr(truth, "version", None),
        "physical_truth_qa": jsonable(getattr(truth, "qa", None)),
        "physical_truth_status": (getattr(physical, "meta", {}) or {}).get(
            "physical_truth_status") if physical is not None else None,
    }


def _render(audit: dict[str, Any], mesh: Any, top: np.ndarray, bundle: Any,
            filename: str, title: str) -> None:
    appearance = bundle.get("appearance")
    audit["raster_top"](mesh, np.asarray(appearance["texel_albedo"], dtype=np.float64),
                        top, OUT / filename, title)


def main() -> dict[str, Any]:
    audit = runpy.run_path(str(AUDIT_SCRIPT), run_name="appearance_repair_audit_fixture")
    mesh, top, source = audit["small_box"]()
    fragment_id = source.get("fragment").fragment_id
    clean_truth = CleanTruth(
        mother_id="degradation_audit_mother", event_id="degradation_audit_event", version=1,
        relations={}, interfaces=[], correspondence=[],
        event_tree={"event_id": "degradation_audit_event", "events": []},
        qa={"pass": True, "truth_incomplete": False},
        meta={"truth_hash": "sha256:appearance-repair-clean-truth",
              "fragment_ids": [fragment_id], "truth_incomplete": False},
    )
    source = source.with_payload(clean_truth=clean_truth)
    source_hash = source.content_hash()
    source_geometry_hash = mesh_geometry_hash(mesh)
    source_appearance = source.get("appearance")
    source_arrays = {key: np.array(value, copy=True) for key, value in source_appearance.items()
                     if isinstance(value, np.ndarray)}

    output_rows: dict[str, dict[int, Any]] = {"P05": {}, "P06": {}}
    rows: dict[str, list[dict[str, Any]]] = {"P05": [], "P06": []}
    for axis_id in ("P05", "P06"):
        for level in (0, 1, 4):
            output, measurement = apply_axis(
                axis_id, level, source, None, lineage_id=LINEAGE, commit=False)
            bundle = _bundle(output)
            output_rows[axis_id][level] = (bundle, measurement)
            image_name = f"{axis_id.lower()}_L{level}_top_albedo.png"
            _render(audit, mesh, top, bundle, image_name,
                    f"{axis_id} L{level} repaired appearance")
            physical = bundle.get("physical_result")
            details = dict((getattr(physical, "meta", {}) or {}).get("details") or {})
            unchanged = all(np.array_equal(bundle.get("appearance").get(key), original)
                            for key, original in source_arrays.items()
                            if key not in ("texel_albedo", "texel_roughness"))
            rows[axis_id].append({
                "level": level,
                "identity": bool(measurement.identity),
                "realized": bool(measurement.realized),
                "planned": jsonable(measurement.planned),
                "measured": jsonable(measurement.measured),
                "units": jsonable(measurement.units),
                "basis_id": measurement.extra.get("basis_id"),
                "source_hash": measurement.source_hash,
                "result_hash": measurement.result_hash,
                "appearance_keys": sorted(bundle.get("appearance")),
                "unchanged_source_array_channels_preserved": bool(unchanged),
                "geometry_hash": mesh_geometry_hash(bundle.get("mesh")),
                "selection": jsonable(details.get("selection") or
                                       details.get("removed_area_selection")),
                "label_status": measurement.extra.get("label_status"),
                "label_dependency_status": jsonable(
                    measurement.extra.get("label_dependency_status", {})),
                "current_truth": _physical_truth(bundle),
                "calibration_status": getattr(measurement, "calibration_status", None),
                "image_png": image_name,
            })

    chains = {}
    chain_images = []
    for chain_id, axes in (
        ("P05_L1_then_P06_L1", (("P05", 1), ("P06", 1))),
        ("P06_L1_then_P05_L1", (("P06", 1), ("P05", 1))),
    ):
        current = source
        chain_measurements = []
        for axis_id, level in axes:
            output, measurement = apply_axis(
                axis_id, level, current, None, lineage_id=LINEAGE, commit=False)
            current = _bundle(output)
            chain_measurements.append(measurement)
        image_name = f"{chain_id.lower()}_top_albedo.png"
        _render(audit, mesh, top, current, image_name, chain_id.replace("_", " "))
        chain_images.append(image_name)
        physical_truth = _physical_truth(current)
        chains[chain_id] = {
            "executable": True,
            "axes": [measurement.axis_id for measurement in chain_measurements],
            "source_hashes": [measurement.source_hash for measurement in chain_measurements],
            "result_hashes": [measurement.result_hash for measurement in chain_measurements],
            "measured": [jsonable(measurement.measured) for measurement in chain_measurements],
            "units": [jsonable(measurement.units) for measurement in chain_measurements],
            "label_statuses": [measurement.extra.get("label_status")
                                for measurement in chain_measurements],
            "label_dependency_statuses": [jsonable(
                measurement.extra.get("label_dependency_status", {}))
                for measurement in chain_measurements],
            "clean_truth_reference_preserved_by_identity": current.get("clean_truth") is clean_truth,
            "current_truth": physical_truth,
            "appearance_keys": sorted(current.get("appearance")),
            "geometry_hash": mesh_geometry_hash(current.get("mesh")),
            "image_png": image_name,
        }

    panel_names = [
        "p05_l0_top_albedo.png", "p05_l1_top_albedo.png", "p05_l4_top_albedo.png",
        "p06_l0_top_albedo.png", "p06_l1_top_albedo.png", "p06_l4_top_albedo.png",
        *chain_images,
    ]
    panels = [Image.open(OUT / name).convert("RGB") for name in panel_names]
    tile_w, tile_h = panels[0].size
    gap = 8
    montage = Image.new("RGB", (4 * tile_w + 5 * gap, 2 * tile_h + 3 * gap), (235, 232, 224))
    for index, panel in enumerate(panels):
        x = gap + (index % 4) * (tile_w + gap)
        y = gap + (index // 4) * (tile_h + gap)
        montage.paste(panel, (x, y))
    montage_path = OUT / "appearance_levels_and_chains.png"
    montage.save(montage_path)

    preservation = all(np.array_equal(source_appearance[key], original)
                       for key, original in source_arrays.items())
    manifest = {
        "case": "P05/P06 appearance continuity repair on the original audit fixture",
        "lineage_id": LINEAGE,
        "seed_policy": "reuse the audit fixture's fixed master seed and deterministic axis basis",
        "fixture": {"vertices": int(len(mesh.vertices)), "faces": int(len(mesh.faces)),
                    "texels": int(len(source_appearance["texel_area_mm2"])),
                    "top_interface_faces": int(top.sum()), "length_unit": "mm",
                    "area_unit": "mm2", "source_volume_mm3": float(abs(mesh.volume))},
        "source_hash": source_hash,
        "source_hash_after_all_runs": source.content_hash(),
        "source_hash_unchanged": source.content_hash() == source_hash,
        "source_geometry_hash": source_geometry_hash,
        "source_geometry_hash_after_all_runs": mesh_geometry_hash(mesh),
        "source_geometry_unchanged": source_geometry_hash == mesh_geometry_hash(mesh),
        "source_annotation_arrays_unchanged": preservation,
        "clean_truth_reference": {"identity": id(clean_truth),
                                   "mother_id": clean_truth.mother_id,
                                   "event_id": clean_truth.event_id,
                                   "version": clean_truth.version,
                                   "truth_hash": clean_truth.meta["truth_hash"]},
        "axes": rows,
        "chains": chains,
        "real_world_calibration": "UNCALIBRATED",
        "image_sha256": {name: sha256(OUT / name) for name in panel_names +
                          ["appearance_levels_and_chains.png"]},
        "images": panel_names + ["appearance_levels_and_chains.png"],
    }
    (OUT / "appearance_repair_probe.json").write_text(
        json.dumps(jsonable(manifest), indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    result = main()
    print(json.dumps({
        "fixture": result["fixture"],
        "source_hash_unchanged": result["source_hash_unchanged"],
        "source_geometry_unchanged": result["source_geometry_unchanged"],
        "source_annotation_arrays_unchanged": result["source_annotation_arrays_unchanged"],
        "axes": {axis: [{"level": row["level"], "measured": row["measured"],
                         "basis_id": row["basis_id"], "label_status": row["label_status"],
                         "image_png": row["image_png"]} for row in rows]
                 for axis, rows in result["axes"].items()},
        "chains": {name: {"executable": row["executable"],
                           "label_statuses": row["label_statuses"],
                           "image_png": row["image_png"]}
                   for name, row in result["chains"].items()},
        "real_world_calibration": result["real_world_calibration"],
    }, indent=2, ensure_ascii=False))

