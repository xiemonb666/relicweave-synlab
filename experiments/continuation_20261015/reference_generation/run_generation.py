"""Build one to eight recipe-controlled footed bowls, then compose reference appearance.

Run with the SynLab environment from any working directory:

    .venv/Scripts/python.exe experiments/continuation_20261015/reference_generation/run_generation.py

The geometry candidates are made by VesselForge's existing CAD driver. They are stored in a
new, non-overwriting subtree under ``vesselforge/.../reference_forms/outputs``. Composed
evidence is stored under this experiment's ``outputs_v3_pbr`` directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
WORKSPACE = HERE.parents[3]
sys.path.insert(0, str(REPO))

from synlab.errors import SynLabError  # noqa: E402
from synlab.integrations.reference_generator import (  # noqa: E402
    BLUEWHITE_PANEL_STYLE,
    compose_reference_instance,
    sample_outer_wall_texture,
    validate_bluewhite_material_compatibility,
    validate_bluewhite_panel_controls,
    validate_bluewhite_source_asset,
    write_reference_instance,
)
from synlab.materials.reference_materials import reference_material  # noqa: E402
from synlab.patterns.reference_styles import reference_style_record  # noqa: E402


VF_ROOT = WORKSPACE / "vesselforge"
VF_DRIVER = (VF_ROOT / "experiments" / "continuation_20261015" / "reference_forms"
             / "build_reference_candidates.py")
VF_OUTPUTS = VF_DRIVER.parent / "outputs"
VF_PYTHON = WORKSPACE / "third_party" / "vesselforge-runtime" / "venv" / "Scripts" / "python.exe"
DEFAULT_RECIPE = HERE / "recipe.json"
DEFAULT_OUTPUT = HERE / "outputs_v3_pbr"
MAX_RECIPE_BYTES = 1024 * 1024
MAX_CAD_SECONDS = 60
MAX_INSTANCE_BYTES = 64 * 1024 * 1024
MAX_EXPERIMENT_BYTES = 256 * 1024 * 1024
_SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def _canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _array_sha256(arrays: dict[str, np.ndarray]) -> str:
    digest = hashlib.sha256(b"synlab.reference_replay_arrays.v1\0")
    for name in sorted(arrays):
        array = np.ascontiguousarray(arrays[name])
        digest.update(name.encode("utf-8") + b"\0")
        digest.update(array.dtype.str.encode("ascii") + b"\0")
        digest.update(json.dumps(list(array.shape), separators=(",", ":")).encode())
        digest.update(array.tobytes())
    return digest.hexdigest()


def _read_recipe(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"recipe file does not exist: {path}")
    if path.stat().st_size > MAX_RECIPE_BYTES:
        raise ValueError(f"recipe file exceeds the {MAX_RECIPE_BYTES}-byte limit")
    recipe = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(recipe, dict):
        raise ValueError("recipe root must be a JSON object")
    return recipe


def _validate_recipe(recipe: dict[str, Any]) -> None:
    allowed_root = {"schema", "recipe_id", "family", "geometry", "instances"}
    unknown_root = sorted(set(recipe) - allowed_root)
    if unknown_root:
        raise ValueError(f"recipe has unsupported keys: {unknown_root}")
    if recipe.get("schema") != "synlab.footed_bowl_reference_generation_recipe.v2":
        raise ValueError("unsupported or missing recipe schema")
    if recipe.get("family") != "footed_bowl":
        raise ValueError("this generator slice accepts family='footed_bowl' only")
    geometry = recipe.get("geometry")
    if not isinstance(geometry, dict) or set(geometry) != {"preset", "design_model"}:
        raise ValueError("recipe.geometry must be an object")
    if geometry.get("preset") not in {"daily", "met"}:
        raise ValueError("geometry.preset must be 'daily' or 'met'")
    if geometry.get("design_model") != "FootedBowlDesign":
        raise ValueError("geometry.design_model must name the existing FootedBowlDesign")
    instances = recipe.get("instances")
    if not isinstance(instances, list) or not 1 <= len(instances) <= 8:
        raise ValueError("recipe.instances must contain between one and eight controlled variants")
    if any(not isinstance(item, dict) for item in instances):
        raise ValueError("each recipe instance must be an object")
    names: set[str] = set()
    for index, item in enumerate(instances):
        unknown_instance = sorted(set(item) - {"name", "design", "material", "pattern", "seeds"})
        if unknown_instance:
            raise ValueError(f"instances[{index}] has unsupported keys: {unknown_instance}")
        name = item.get("name")
        if not isinstance(name, str) or not _SLUG.fullmatch(name) or name in names:
            raise ValueError(f"instances[{index}].name must be a unique lowercase slug")
        names.add(name)
        design = item.get("design")
        if (not isinstance(design, dict) or set(design) != {"model", "overrides"}
                or design.get("model") != "FootedBowlDesign"
                or not isinstance(design.get("overrides"), dict)):
            raise ValueError(f"instances[{index}].design must name FootedBowlDesign and its overrides")
        for key in design["overrides"]:
            if not isinstance(key, str):
                raise ValueError(f"instances[{index}].design override keys must be strings")
        for group in ("material", "pattern"):
            value = item.get(group)
            if (not isinstance(value, dict) or set(value) != {"style_id", "controls"}
                    or not isinstance(value.get("style_id"), str)
                    or not isinstance(value.get("controls"), dict)):
                raise ValueError(f"instances[{index}].{group} needs style_id and controls")
        seeds = item.get("seeds")
        if not isinstance(seeds, dict) or set(seeds) != {"material", "pattern"}:
            raise ValueError(f"instances[{index}].seeds must separate material and pattern seeds")
        if any(isinstance(value, bool) or not isinstance(value, int) for value in seeds.values()):
            raise ValueError(f"instances[{index}] material and pattern seeds must be integers")

        # Reject invalid appearance choices before invoking the slower CAD builder.
        material_profile = reference_material(
            item["material"]["style_id"], item["material"]["controls"],
            seed=seeds["material"])
        controls = item["pattern"]["controls"]
        if item["pattern"]["style_id"] == BLUEWHITE_PANEL_STYLE:
            validate_bluewhite_panel_controls(controls)
            validate_bluewhite_source_asset()
            try:
                validate_bluewhite_material_compatibility(material_profile)
            except SynLabError as exc:
                raise ValueError(
                    f"instances[{index}] blue-white pigment requires a known ceramic "
                    "material class compatible with underglaze_cobalt") from exc
        else:
            style = reference_style_record(item["pattern"]["style_id"])
            mapping = style.get("pattern_mapping") or {}
            ranges = mapping.get("override_ranges") or {}
            if style.get("render_status") == "RESEARCH_ONLY_NOT_BUILDABLE":
                raise ValueError(f"pattern style {item['pattern']['style_id']!r} is research-only")
            if set(controls) - set(ranges):
                raise ValueError(f"instances[{index}] has unsupported pattern controls: "
                                 f"{sorted(set(controls) - set(ranges))}")
            for key, value in controls.items():
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError(f"pattern control {key!r} must be numeric")
                low, high = ranges[key]
                if not low <= float(value) <= high:
                    raise ValueError(f"pattern control {key!r}={value} is outside [{low}, {high}]")


def _replay_matches(left: Any, right: Any, left_texture: dict[str, Any],
                    right_texture: dict[str, Any]) -> dict[str, Any]:
    if left.recipe != right.recipe or left.provenance != right.provenance:
        raise RuntimeError("deterministic replay changed recipe or provenance")
    if left.metrics != right.metrics:
        raise RuntimeError("deterministic replay changed geometry or material metrics")
    if set(left.fields) != set(right.fields):
        raise RuntimeError("deterministic replay changed the field inventory")
    for key in left.fields:
        if not np.array_equal(left.fields[key], right.fields[key]):
            raise RuntimeError(f"deterministic replay changed field {key!r}")
    for key in ("outer_texture_linear_rgb", "outer_pattern_region", "outer_pigment_density",
                "s_centers_mm", "theta_centers_rad", "profile_radius_mm"):
        if not np.array_equal(left_texture[key], right_texture[key]):
            raise RuntimeError(f"deterministic replay changed texture array {key!r}")
    return {
        "passed": True,
        "field_array_sha256": _array_sha256(left.fields),
        "texture_linear_rgb_sha256": _sha256_bytes(
            np.ascontiguousarray(left_texture["outer_texture_linear_rgb"]).tobytes()),
        "texture_arrays_bitwise_equal": True,
        "face_fields_bitwise_equal": True,
    }


def _run_cad_candidate(preset: str, output: Path, overrides: dict[str, Any]) -> dict[str, Any]:
    overrides_json = json.dumps(overrides, ensure_ascii=False, sort_keys=True,
                                separators=(",", ":"))
    argv = [str(VF_PYTHON), str(VF_DRIVER), "--preset", preset,
            "--output", str(output), "--overrides-json", overrides_json]
    started = time.perf_counter()
    result = subprocess.run(argv, cwd=WORKSPACE, capture_output=True, text=True,
                            timeout=MAX_CAD_SECONDS, check=False)
    elapsed = time.perf_counter() - started
    record = {
        "argv": argv,
        "cwd": str(WORKSPACE),
        "exit_code": int(result.returncode),
        "duration_seconds": elapsed,
        "timeout_seconds": MAX_CAD_SECONDS,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "output": str(output),
    }
    if result.returncode != 0:
        raise RuntimeError(f"VesselForge CAD candidate failed ({result.returncode}): "
                           f"{result.stderr[-2000:]}")
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipe", type=Path, default=DEFAULT_RECIPE,
                        help="unified recipe JSON (defaults to this experiment's recipe.json)")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help="new output directory under this experiment; existing directories are refused")
    parser.add_argument("--texture-grid", type=int, nargs=2, metavar=("N_S", "N_THETA"),
                        default=(512, 1024),
                        help="bounded continuous texture grid (default: 512 1024)")
    args = parser.parse_args()

    recipe_path = args.recipe.expanduser().resolve()
    output_root = args.output.expanduser().resolve()
    bluewhite_experiment = (REPO / "experiments" / "continuation_20261016"
                            / "bluewhite_reference_generation").resolve()
    bluewhite_source_resolution = (REPO / "experiments" / "continuation_20261016"
                                   / "bluewhite_source_resolution").resolve()
    allowed_output_roots = (HERE, bluewhite_experiment, bluewhite_source_resolution)
    if not any(root in output_root.parents for root in allowed_output_roots):
        raise ValueError("output must be a new child of the reference_generation or "
                         f"continuation_20261016 blue-white experiment: {output_root}")
    if not _SLUG.fullmatch(output_root.name):
        raise ValueError("output directory name must be a lowercase slug")
    if output_root.exists():
        raise FileExistsError(f"refusing to overwrite experiment output: {output_root}")
    texture_n_s, texture_n_theta = (int(args.texture_grid[0]), int(args.texture_grid[1]))
    texture_cells = texture_n_s * texture_n_theta
    texture_output_preflight = texture_cells * 20 + 64 * 1024
    if (texture_n_s < 2 or texture_n_s > 2048 or texture_n_theta < 3
            or texture_n_theta > 4096 or texture_cells > 1_000_000
            or texture_output_preflight > MAX_INSTANCE_BYTES):
        raise ValueError("texture grid exceeds bounded dimensions/cells or 64 MiB output preflight")
    if not VF_PYTHON.is_file() or not VF_DRIVER.is_file():
        raise FileNotFoundError("the bundled VesselForge runtime or CAD driver is unavailable")

    recipe = _read_recipe(recipe_path)
    _validate_recipe(recipe)
    preset = str(recipe["geometry"]["preset"])
    geometry_suffix = (output_root.name if output_root.parent == HERE
                       else f"{output_root.parent.name}_{output_root.name}")
    geometry_output_root = VF_OUTPUTS / f"reference_generation_{geometry_suffix}"
    if geometry_output_root.exists():
        raise FileExistsError(f"refusing to overwrite generated CAD candidates: {geometry_output_root}")
    for item in recipe["instances"]:
        candidate = geometry_output_root / item["name"]
        if candidate.exists():
            raise FileExistsError(f"refusing to overwrite generated CAD candidate: {candidate}")

    output_root.mkdir(parents=False, exist_ok=False)
    (output_root / "instances").mkdir()
    canonical_recipe = _canonical_json(recipe)
    recipe_hash = _sha256_bytes(canonical_recipe)
    (output_root / "recipe.json").write_bytes(canonical_recipe)
    cad_records: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for item in recipe["instances"]:
        name = item["name"]
        overrides = dict(item["design"]["overrides"])
        candidate_path = geometry_output_root / name
        cad_record = _run_cad_candidate(preset, candidate_path, overrides)
        cad_record["instance"] = name
        cad_records.append(cad_record)
        (output_root / "cad_invocations.json").write_text(
            json.dumps(cad_records, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8")
        candidate_bytes = sum(path.stat().st_size for path in candidate_path.rglob("*")
                              if path.is_file())
        if candidate_bytes > MAX_INSTANCE_BYTES:
            raise RuntimeError(f"generated CAD candidate exceeds {MAX_INSTANCE_BYTES} bytes")

        material = item["material"]
        pattern = item["pattern"]
        seeds = item["seeds"]
        instance = compose_reference_instance(
            candidate_path, material["style_id"], pattern["style_id"], seeds,
            {"material": material["controls"], "pattern": pattern["controls"]})
        texture = sample_outer_wall_texture(
            instance, n_s=texture_n_s, n_theta=texture_n_theta)
        replay = compose_reference_instance(
            candidate_path, material["style_id"], pattern["style_id"], seeds,
            {"material": material["controls"], "pattern": pattern["controls"]})
        replay_texture = sample_outer_wall_texture(
            replay, n_s=texture_n_s, n_theta=texture_n_theta)
        replay_status = _replay_matches(instance, replay, texture, replay_texture)
        instance.recipe["experiment_recipe"] = {
            "canonical_recipe_sha256": recipe_hash,
            "instance_id": name,
            "family": recipe["family"],
            "geometry_preset": preset,
            "design_model": item["design"]["model"],
            "design_overrides": overrides,
        }
        bundle = output_root / "instances" / name
        bundle_result = write_reference_instance(instance, bundle, texture=texture)
        bundle_bytes = sum(path.stat().st_size for path in bundle.rglob("*") if path.is_file())
        if bundle_bytes > MAX_INSTANCE_BYTES:
            raise RuntimeError(f"appearance bundle exceeds {MAX_INSTANCE_BYTES} bytes")
        rows.append({
            "instance_id": name,
            "family": recipe["family"],
            "geometry_preset": preset,
            "design_model": item["design"]["model"],
            "design_overrides": overrides,
            "material_style": material["style_id"],
            "material_controls": material["controls"],
            "pattern_style": pattern["style_id"],
            "pattern_controls": pattern["controls"],
            "seeds": seeds,
            "source_geometry_directory": str(candidate_path),
            "source_geometry_file_sha256": instance.mother.meta["source_file_sha256"],
            "geometry_array_sha256_before_appearance": instance.metrics[
                "geometry_array_sha256_before"],
            "geometry_array_sha256_after_appearance": instance.metrics[
                "geometry_array_sha256_after"],
            "geometry_unchanged": instance.metrics["geometry_unchanged"],
            "dimensions_mm": instance.metrics["dimensions_mm"],
            "signed_volume_mm3": instance.metrics["signed_volume_mm3"],
            "pattern_region_triangle_count": instance.metrics["pattern_region_triangle_count"],
            "material_layer_triangle_counts": instance.metrics["material_layer_triangle_counts"],
            "continuous_texture_validation": texture["metrics"],
            "deterministic_replay": replay_status,
            "bundle": str(bundle.relative_to(output_root)),
            "bundle_manifest_sha256": _sha256_file(bundle / "manifest.json"),
            "files": bundle_result["files"],
            "bundle_bytes": bundle_bytes,
            "cad_duration_seconds": cad_record["duration_seconds"],
        })

    experiment = {
        "schema": "synlab.reference_generation_experiment.v2",
        "status": "REFERENCE_GUIDED_DESIGN_CANDIDATE",
        "canonical_recipe_sha256": recipe_hash,
        "recipe_file": "recipe.json",
        "family": recipe["family"],
        "geometry_preset": preset,
        "design_model": recipe["geometry"]["design_model"],
        "generated_geometry_root": str(geometry_output_root),
        "cad_invocations_file": "cad_invocations.json",
        "continuous_texture_grid_s_theta": [texture_n_s, texture_n_theta],
        "texture_output_preflight_upper_bound_bytes_per_instance": texture_output_preflight,
        "instances": rows,
        "scope": {
            "geometry": (f"{len(rows)} new recipe-driven FootedBowlDesign candidate(s) from the existing VesselForge CAD driver."),
            "appearance": "Existing source-conditioned SynLab material and either a buildable reference-pattern style or the explicit Met 50899 photo-derived blue-white panel route, sampled on unchanged CAD sources.",
            "refinement": "Original source geometry and profile are retained; appearance composition performs no vertex, face, or topology edits.",
            "chart": "Finite-polyline chart arclength is validated against the original general-purpose chart on selected points.",
            "interpretation": "Mixed-source reference-guided design candidates; not exact museum, maker, or archaeological object clones.",
            "physical_materials": "No calibrated optical values, chemistry, thickness, forming or firing mechanics are asserted. The blue-white panel is an already-fired-photo appearance proxy with uncalibrated spread/color controls.",
            "native_fracture": "NOT_RUN",
            "training_export": "NONE",
            "resource_limits": {
                "recipe_bytes": MAX_RECIPE_BYTES,
                "cad_timeout_seconds_per_instance": MAX_CAD_SECONDS,
                "instance_bytes": MAX_INSTANCE_BYTES,
                "experiment_bytes": MAX_EXPERIMENT_BYTES,
            },
        },
    }
    total_bytes = sum(path.stat().st_size for path in output_root.rglob("*") if path.is_file())
    if total_bytes > MAX_EXPERIMENT_BYTES:
        raise RuntimeError(f"experiment output exceeds {MAX_EXPERIMENT_BYTES} bytes")
    manifest_path = output_root / "experiment_manifest.json"
    manifest_path.write_text(json.dumps(experiment, ensure_ascii=False,
                                        sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"instances": len(rows), "output": str(output_root),
                      "canonical_recipe_sha256": recipe_hash,
                      "manifest": str(manifest_path),
                      "manifest_sha256": _sha256_file(manifest_path),
                      "output_bytes": total_bytes}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
