"""Write deterministic off-grid source-resolved versus legacy sampling probes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import numpy as np


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO))

from synlab.integrations.reference_generator import BLUEWHITE_PANEL_STYLE, compose_reference_instance  # noqa: E402
from synlab.patterns.bluewhite_panel import GRID_BILINEAR_SAMPLING  # noqa: E402


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output_root = args.output.expanduser().resolve()
    experiment_path = output_root / "experiment_manifest.json"
    if not experiment_path.is_file():
        raise FileNotFoundError(f"experiment manifest is missing: {experiment_path}")
    experiment = json.loads(experiment_path.read_text(encoding="utf-8"))
    probes = []
    geometry_hashes = set()
    for item in experiment.get("instances", []):
        bundle = output_root / item["bundle"]
        recipe = json.loads((bundle / "recipe.json").read_text(encoding="utf-8"))
        controls = dict(recipe["pattern"]["mapping_and_spread_controls"])
        controls.pop("glaze_white_linear_rgb", None)
        if controls.get("continuous_sampling_mode") != "source_resolved_stationary_v1":
            raise ValueError(f"{item['instance_id']} did not opt in to source-resolved sampling")
        material = recipe["material"]
        material_controls = recipe["controls_requested"]["material"]
        seeds = recipe["seeds"]
        candidate = item["source_geometry_directory"]
        source_instance = compose_reference_instance(
            candidate, material["style_id"], BLUEWHITE_PANEL_STYLE, seeds,
            {"material": material_controls, "pattern": controls})
        legacy_controls = {**controls, "continuous_sampling_mode": GRID_BILINEAR_SAMPLING}
        legacy_instance = compose_reference_instance(
            candidate, material["style_id"], BLUEWHITE_PANEL_STYLE, seeds,
            {"material": material_controls, "pattern": legacy_controls})
        source_panel = source_instance.pigment_panel
        legacy_panel = legacy_instance.pigment_panel
        if source_panel is None or legacy_panel is None:
            raise RuntimeError("panel composition did not produce both comparison fields")
        for name in ("initial_density", "bound_density", "mobile_density", "total_density"):
            if not np.array_equal(getattr(source_panel, name), getattr(legacy_panel, name)):
                raise RuntimeError(f"source mode changed recorded FV array {name}")
        geometry_hash = source_instance.metrics["geometry_array_sha256_after"]
        if not source_instance.metrics["geometry_unchanged"]:
            raise RuntimeError("source-resolved appearance changed geometry arrays")
        geometry_hashes.add(geometry_hash)

        source_density = source_panel.source_density
        if source_density is None:
            raise RuntimeError("source-resolved result omitted its immutable source density")
        row, column = np.unravel_index(int(np.argmax(source_density)), source_density.shape)
        panel = source_panel.receipt["panel"]
        s_low = float(panel["s_bounds_mm"][0])
        s_value = s_low + (row + 0.5) / source_density.shape[0] * float(panel["height_mm"])
        x_value = ((column + 0.5) / source_density.shape[1] - 0.5) * float(panel["width_mm"])
        radius = float(np.interp(s_value, source_panel.profile_s_mm,
                                 source_panel.profile_radius_mm))
        theta_value = float(source_panel.center_theta_rad + x_value / radius)
        source_components = {
            name: float(source_panel.sample_density(s_value, theta_value, component=name))
            for name in ("initial", "bound", "mobile", "total")
        }
        legacy_components = {
            name: float(legacy_panel.sample_density(s_value, theta_value, component=name))
            for name in ("initial", "bound", "mobile", "total")
        }
        with np.load(bundle / "bluewhite_panel_fields.npz", allow_pickle=False) as arrays:
            recorded_source = np.asarray(arrays["normalized_source_density"])
            if not np.array_equal(recorded_source, source_density):
                raise RuntimeError("persisted full-resolution source differs from sampled source")
        probes.append({
            "instance_id": item["instance_id"],
            "sampling_mode": source_panel.continuous_sampling_mode,
            "legacy_comparison_mode": GRID_BILINEAR_SAMPLING,
            "source_geometry_array_sha256": geometry_hash,
            "source_mask_sha256": source_panel.receipt["source"]["source_mask_sha256"],
            "normalized_density_sha256": source_panel.receipt["source"][
                "normalized_density_sha256"],
            "normalized_density_shape": list(source_density.shape),
            "normalized_density_dtype": source_density.dtype.str,
            "source_pixel_rc": [int(row), int(column)],
            "query_s_mm": s_value,
            "query_theta_rad": theta_value,
            "source_resolved_components": source_components,
            "legacy_grid_bilinear_components": legacy_components,
            "total_density_difference_source_resolved_minus_legacy": (
                source_components["total"] - legacy_components["total"]),
            "mobile_transport_is_zero": source_panel.mobile_transport_is_zero,
            "finite_volume_grid_arrays_bitwise_equal_between_modes": True,
        })
    if len(geometry_hashes) != 1:
        raise RuntimeError("controlled comparison instances do not share one geometry hash")
    document = {
        "schema": "synlab.bluewhite_source_detail_probe.v1",
        "purpose": "off-grid continuous source-detail comparison against legacy grid-bilinear sampling",
        "mass_scope": "DISCRETE_GRID_MASS_ONLY",
        "continuous_source_quadrature_equality_claimed": False,
        "fine_grid_convergence_claimed": False,
        "geometry_array_sha256_shared": next(iter(geometry_hashes)),
        "geometry_changed": False,
        "probe_method": "deterministic maximum-density source pixel center mapped through the recorded actual-profile panel transform",
        "instances": probes,
        "source_receipts": {
            item["instance_id"]: _sha256(output_root / item["bundle"] / "bluewhite_panel_receipt.json")
            for item in experiment["instances"]
        },
    }
    target = output_root / "source_detail_probe.json"
    target.write_text(json.dumps(document, ensure_ascii=False,
                                 sort_keys=True, indent=2) + "\n", encoding="utf-8")
    target_hash = _sha256(target)
    experiment["numeric_source_detail_probe"] = {
        "file": target.name,
        "sha256": target_hash,
        "mass_scope": "DISCRETE_GRID_MASS_ONLY",
    }
    preview_manifest_path = output_root / experiment.get("previews", {}).get(
        "manifest", "preview_manifest_source_resolved_v1.json")
    if preview_manifest_path.is_file():
        preview_manifest = json.loads(preview_manifest_path.read_text(encoding="utf-8"))
        preview_manifest["numeric_source_detail_probe"] = {
            "file": target.name, "sha256": target_hash}
        preview_manifest_path.write_text(json.dumps(
            preview_manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8")
        experiment.setdefault("previews", {})["manifest_sha256"] = _sha256(
            preview_manifest_path)
    for _ in range(10):
        current_total = sum(path.stat().st_size for path in output_root.rglob("*")
                            if path.is_file() and path != experiment_path)
        payload = json.dumps(experiment, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        disk_payload = payload.replace("\n", os.linesep)
        output_bytes = current_total + len(disk_payload.encode("utf-8"))
        if experiment.get("output_bytes") == output_bytes:
            break
        experiment["output_bytes"] = output_bytes
    payload = json.dumps(experiment, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    experiment_path.write_bytes(payload.replace("\n", os.linesep).encode("utf-8"))
    actual_total = sum(path.stat().st_size for path in output_root.rglob("*")
                       if path.is_file())
    if actual_total != experiment.get("output_bytes"):
        raise RuntimeError("experiment output byte count did not converge to exact total")
    print(json.dumps({"probe": str(target), "sha256": _sha256(target),
                      "instances": len(probes), "output_bytes": actual_total}, indent=2))


if __name__ == "__main__":
    main()
