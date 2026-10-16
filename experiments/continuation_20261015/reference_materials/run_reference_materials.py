"""Regenerate same-point reference-material samples and process checks."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synlab.materials.api import build_material_profile  # noqa: E402
from synlab.materials.reference_materials import (  # noqa: E402
    list_reference_materials,
    process_compatibility,
    reference_material,
    sample_reference_material,
)
from synlab.seeds import make_rng  # noqa: E402

SEED = 20261015
POINTS = np.asarray([
    [30.0, 0.0, 11.0],  # lower-wall query coordinate within the Aberdeen D/H envelope
    [28.0, 0.0, 27.0],  # inner-wall query coordinate
    [54.0, 0.0, 53.0],  # Aberdeen rim envelope
    [15.5, 0.0, 0.0],   # Aberdeen foot-ring radius
], dtype=np.float64)


def _sample_profiles() -> dict[str, Any]:
    rows: dict[str, Any] = {}
    for style in list_reference_materials():
        style_id = style["style_id"]
        profile = reference_material(style_id, seed=SEED)
        rows[style_id] = {
            "profile_hash": profile["profile_hash"],
            "source_id": profile["source_conditioned"]["source_object"]["source_id"],
            "optical_measurements_status": profile["source_conditioned"][
                "optical_measurements_status"],
            "mechanics_status": profile["source_conditioned"]["mechanics_status"],
            "field_kernel": profile["field_kernel"],
            "field_kernel_version": profile["field_kernel_version"],
            "coating_surface_policy": profile["coating_surface_policy"],
            "layer_semantics": profile["source_conditioned"]["layer_semantics"],
            "outer_wall": sample_reference_material(profile, POINTS, "outer_wall"),
            "inner_wall": sample_reference_material(profile, POINTS[1:2], "inner_wall"),
            "rim": sample_reference_material(profile, POINTS[2:3], "rim"),
            "foot": sample_reference_material(profile, POINTS[3:4], "foot"),
            "new_interface_same_mother_points": sample_reference_material(
                profile, POINTS[:1], "interface"),
        }

    # The wood and metal profiles are deliberately the standard synthetic catalogue profiles.
    # They supply actual material_at channel comparisons, not source-conditioned object claims.
    for material_id, label in (("M11", "catalogue_wood"), ("M12", "catalogue_metal")):
        profile = build_material_profile(
            material_id, {}, make_rng(SEED, "material", material_id))
        rows[label] = {
            "profile_hash": profile["profile_hash"],
            "catalogue_material_id": material_id,
            "source_status": "SYNTHETIC_CATALOGUE_PROFILE",
            "field_kernel": profile["field_kernel"],
            "field_kernel_version": profile.get("field_kernel_version", 1),
            "outer_wall": sample_reference_material(profile, POINTS, "outer_wall"),
            "new_interface_same_mother_points": sample_reference_material(
                profile, POINTS[:1], "interface"),
        }
    return rows


def _process_matrix() -> list[dict[str, Any]]:
    pairs = [
        ("porcelain", "ceramic_glaze_firing"),
        ("stoneware", "ceramic_glaze_firing"),
        ("earthenware", "ceramic_glaze_firing"),
        ("wood", "ceramic_glaze_firing"),
        ("metal", "ceramic_glaze_firing"),
        ("porcelain", "surface_paint"),
        ("stoneware", "engrave_body"),
    ]
    return [process_compatibility(material, process) for material, process in pairs]


def _srgb_hex(linear_rgb: list[float]) -> str:
    channels = []
    for component in linear_rgb:
        value = float(component)
        srgb = 12.92 * value if value <= 0.0031308 else 1.055 * value ** (1.0 / 2.4) - 0.055
        channels.append(max(0, min(255, round(255.0 * srgb))))
    return "#" + "".join(f"{channel:02x}" for channel in channels)


def _preview_svg(samples: dict[str, Any]) -> str:
    """Make a compact true-query swatch sheet; colors come from the material_at samples."""
    rows = []
    for index, (name, record) in enumerate(samples.items()):
        outer = record["outer_wall"]
        face = record["new_interface_same_mother_points"]
        outer_color = _srgb_hex(outer["albedo"][0])
        face_color = _srgb_hex(face["albedo"][0])
        y = 64 + index * 134
        rows.append(f'''<g>
  <text x="32" y="{y}" class="title">{name}</text>
  <rect x="32" y="{y + 16}" width="260" height="78" rx="8" fill="{outer_color}" stroke="#555"/>
  <rect x="308" y="{y + 16}" width="260" height="78" rx="8" fill="{face_color}" stroke="#555"/>
  <text x="44" y="{y + 112}" class="label">outer wall · layer {outer['layer_id'][0]} · r {outer['roughness'][0]:.3f} · τ {outer['transmission'][0]:.3f} · IOR {outer['ior'][0]:.3f}</text>
  <text x="320" y="{y + 112}" class="label">new interface · layer {face['layer_id'][0]} · r {face['roughness'][0]:.3f} · τ {face['transmission'][0]:.3f} · IOR {face['ior'][0]:.3f}</text>
</g>''')
    height = 96 + len(rows) * 134
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="620" height="{height}" viewBox="0 0 620 {height}">
<rect width="100%" height="100%" fill="#f4f2ed"/>
<style>text{{font-family:Segoe UI,Arial,sans-serif;fill:#171717}}.title{{font-size:16px;font-weight:600}}.label{{font-size:12px}}</style>
<text x="32" y="32" style="font-size:19px;font-weight:700">Sampled material channels at shared mother coordinates</text>
{''.join(rows)}
</svg>
'''


def main() -> None:
    profile_samples = _sample_profiles()
    reference_profiles = {key: value for key, value in profile_samples.items()
                          if not key.startswith("catalogue_")}
    catalogue_comparators = {key: value for key, value in profile_samples.items()
                             if key.startswith("catalogue_")}
    payload = {
        "schema": "shardforge.reference_material_samples.v2",
        "seed": SEED,
        "mother_coordinate_points_mm": POINTS.tolist(),
        "query_note": "All rows query the same mother coordinates through the pure material_at field. Versioned ceramic reference profiles select original outer_wall, inner_wall, and rim faces by semantic tag at query depth zero; foot/base and interface expose bare body. Volume queries require explicit depth_mm. Landmark coordinates are bounded by source dimensions but are not registered to source meshes.",
        "reference_profiles": reference_profiles,
        "catalogue_comparators": catalogue_comparators,
        "process_compatibility": _process_matrix(),
        "mechanics": {
            "status": "UNKNOWN",
            "automatic_physics_card": False,
            "note": "Primary studies are partial condition-specific comparators; no values are promoted to any named object or project lot.",
        },
    }
    destination = Path(__file__).with_name("material_samples.json")
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                           encoding="utf-8")
    preview = destination.with_name("material_samples_preview.svg")
    preview.write_text(_preview_svg(profile_samples), encoding="utf-8")
    print(destination)
    print(preview)


if __name__ == "__main__":
    main()
