"""Bounded production-render counterfactual for material/pattern route wiring.

Uses two current-source generated mothers with identical V13 geometry and one fixed software
view. Outputs and this script live under tmp/review_20261002/realism; no store assets are written.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image

from synlab.cameras.api import camera_profiles
from synlab.cameras.viewframes import make_view_frames
from synlab.materials.api import (
    build_material_profile,
    default_material_params,
    material_at,
)
from synlab.mothers.api import create_mother, default_params
from synlab.observe import routes as rt
from synlab.observe.imaging import ImagingSpec, apply_imaging_chain
from synlab.observe.render import BACKEND_SOFTWARE, RenderSpec, build_scene, render_view
from synlab.patterns.api import build_pattern, evaluate
from synlab.seeds import make_rng


OUT = Path(__file__).resolve().parent
SEED = 20261002


def save_rgb(path: Path, image: np.ndarray) -> None:
    Image.fromarray(np.asarray(image, dtype=np.uint8), mode="RGB").save(path)


def main() -> None:
    params = default_params("V13")
    mother_a = create_mother(
        "V13", "M01", params, make_rng(SEED, "material-counterfactual", "mother"),
        mother_id="cf_V13_M01",
    )
    mother_b = create_mother(
        "V13", "M05", params, make_rng(SEED, "material-counterfactual", "mother"),
        mother_id="cf_V13_M05",
    )
    geometry_equal = bool(
        np.array_equal(mother_a.mesh.vertices, mother_b.mesh.vertices)
        and np.array_equal(mother_a.mesh.faces, mother_b.mesh.faces)
        and np.array_equal(mother_a.face_surface_tag, mother_b.face_surface_tag)
    )
    if not geometry_equal:
        raise RuntimeError("material variants did not preserve geometry; counterfactual invalid")

    points = np.asarray(mother_a.mesh.triangles_center, dtype=np.float64)
    tags = np.asarray(mother_a.face_surface_tag)
    material_profiles: dict[str, object] = {}
    material_samples: dict[str, object] = {}
    for material_id in ("M01", "M05", "M07"):
        profile = build_material_profile(
            material_id,
            default_material_params(material_id),
            make_rng(SEED, "material-counterfactual", material_id),
        )
        sample = material_at(profile, points, tags)
        material_profiles[material_id] = profile
        material_samples[material_id] = sample

    # The checked path is the same production helper called by routes.render_views and
    # routes.render_frame_bundles. The same explicit frame, zero-noise identity imaging,
    # geometry and seed are used for both supported MotherGeometry material variants.
    profile = camera_profiles()[0]
    target_a = rt.resolve_target(mother_a)
    target_b = rt.resolve_target(mother_b)
    frames = make_view_frames(
        profile, target_a.bbox, 1, make_rng(SEED, "material-counterfactual", "frames"),
        tiers=("GLOBAL",), orbit=True,
    )
    spec = rt.ObsSpec(
        view_count=1,
        delivered_size=(384, 288),
        max_render_pixels=384 * 288,
        tiers=("GLOBAL",),
        render_spec=RenderSpec(supersample=1),
        imaging=ImagingSpec(),
        master_seed=SEED,
        lineage_id="material-counterfactual",
    )

    captured_scenes: dict[str, list[dict[str, object]]] = {"M01": [], "M05": []}
    original_render_view = rt.render_view

    def render_spy(label: str):
        def call(scene, frame, **kwargs):
            captured_scenes[label].append({
                "albedo": np.asarray(scene.material.albedo).copy(),
                "roughness": np.asarray(scene.material.roughness).copy(),
                "source_kind": scene.material.source_kind,
            })
            return original_render_view(scene, frame, **kwargs)
        return call

    try:
        rt.render_view = render_spy("M01")
        bundle_a = rt.render_frame_bundles(
            target_a, frames, spec, make_rng(SEED, "material-counterfactual", "sensor"),
            backend=BACKEND_SOFTWARE,
        )[0]
        rt.render_view = render_spy("M05")
        bundle_b = rt.render_frame_bundles(
            target_b, frames, spec, make_rng(SEED, "material-counterfactual", "sensor"),
            backend=BACKEND_SOFTWARE,
        )[0]
    finally:
        rt.render_view = original_render_view

    image_a = np.asarray(bundle_a.imaging.image)
    image_b = np.asarray(bundle_b.imaging.image)
    linear_a = np.asarray(bundle_a.render.rgb_linear)
    linear_b = np.asarray(bundle_b.render.rgb_linear)
    save_rgb(OUT / "production_V13_M01.png", image_a)
    save_rgb(OUT / "production_V13_M05.png", image_b)

    # The pattern API produces different per-face appearance channels on the same mother.
    # Production render_frame_bundles has no appearance/profile/recipe argument; this preview
    # explicitly injects the resulting channels through build_scene to show renderer response.
    pattern_mother = create_mother(
        "V01", "M05", default_params("V01"), make_rng(SEED, "pattern-preview", "mother"),
        mother_id="preview_V01_M05",
    )
    pattern_target = rt.resolve_target(pattern_mother)
    pattern_frames = make_view_frames(
        camera_profiles()[0], pattern_target.bbox, 1,
        make_rng(SEED, "pattern-preview", "frames"), tiers=("GLOBAL",), orbit=True,
    )
    pattern_render_frame = rt._rescaled_frame(pattern_frames[0], (384, 288))
    pattern_channels: dict[str, object] = {}
    pattern_recipes: dict[str, object] = {}
    pattern_stats: dict[str, object] = {}
    pattern_points = np.asarray(pattern_mother.mesh.triangles_center, dtype=np.float64)
    pattern_tags = np.asarray(pattern_mother.face_surface_tag)
    for family in ("PAT01", "PAT03"):
        recipe = build_pattern(
            pattern_mother,
            {"family": family, "complexity": 2, "allow_aux_layers": False},
            make_rng(SEED, "pattern-preview", family),
        )
        channels = evaluate(recipe, pattern_mother, pattern_points, pattern_tags)
        pattern_recipes[family] = recipe
        pattern_channels[family] = channels
        pattern_stats[family] = {
            "recipe_hash": str(recipe.meta.get("recipe_hash", "")),
            "coverage_fraction": float(np.mean(channels.pattern_region > 0)),
            "albedo_mean": np.mean(channels.albedo, axis=0).tolist(),
            "albedo_std": np.std(channels.albedo, axis=0).tolist(),
            "height_abs_max_mm": float(np.max(np.abs(channels.height_mm), initial=0.0)),
        }
        if family == "PAT03":
            scene = build_scene(
                pattern_mother.mesh,
                surface_tag=pattern_tags,
                face_id=np.arange(pattern_mother.mesh.faces.shape[0], dtype=np.int32),
                albedo=channels.albedo,
                roughness=channels.roughness,
                name=f"{pattern_mother.mother_id}_{family}_channel_preview",
                albedo_source_kind="SYNTHETIC_PATTERN_CHANNEL_PREVIEW",
            )
            preview_render = render_view(
                scene,
                pattern_render_frame,
                light=spec.resolved_light(),
                spec=spec.render_spec,
                focus_distance_mm=pattern_render_frame.working_distance_mm,
                backend=BACKEND_SOFTWARE,
            )
            preview = apply_imaging_chain(
                preview_render.rgb_linear,
                K=pattern_render_frame.K,
                dist=pattern_render_frame.dist,
                uncertain_mask=preview_render.uncertain_mask,
                depth_z=preview_render.depth_z,
                focus_distance_mm=pattern_render_frame.working_distance_mm,
                rng=make_rng(SEED, "pattern-preview", "sensor"),
                spec=spec.imaging,
                camera_model=pattern_render_frame.camera_model or "PINHOLE",
            )
            save_rgb(OUT / "display_V01_M05_PAT03_explicit_channel_preview.png", preview.image)

    # A target may carry pattern provenance, but the production view helper does not inspect it.
    # Keep this as a separate explicit probe: the only documented render inputs remain mesh/tags/IDs.
    plain_target = rt.resolve_target(pattern_mother)
    pat03_target = rt.resolve_target(pattern_mother)
    plain_target.meta["pattern_recipe_hash"] = str(
        pattern_recipes["PAT01"].meta.get("recipe_hash", "")
    )
    pat03_target.meta["pattern_recipe_hash"] = str(
        pattern_recipes["PAT03"].meta.get("recipe_hash", "")
    )
    plain_bundle = rt.render_frame_bundles(
        plain_target, pattern_frames, spec,
        make_rng(SEED, "pattern-preview", "production-sensor"), backend=BACKEND_SOFTWARE,
    )[0]
    pat03_bundle = rt.render_frame_bundles(
        pat03_target, pattern_frames, spec,
        make_rng(SEED, "pattern-preview", "production-sensor"), backend=BACKEND_SOFTWARE,
    )[0]
    save_rgb(OUT / "production_V01_M05_target_metadata_PAT01.png", plain_bundle.imaging.image)
    save_rgb(OUT / "production_V01_M05_target_metadata_PAT03.png", pat03_bundle.imaging.image)

    report = {
        "status": "read_only_runtime_probe",
        "source_commit": "139a5d5",
        "renderer": BACKEND_SOFTWARE,
        "render_path": "synlab.observe.routes.render_frame_bundles -> build_scene -> render_view",
        "frame_count": 1,
        "delivered_size_wh": [384, 288],
        "imaging": "identity defaults (zero noise, zero defocus, linear response)",
        "material_counterfactual": {
            "same_geometry_vertices_faces_tags": geometry_equal,
            "variants": ["M01", "M05"],
            "face_count": int(mother_a.mesh.faces.shape[0]),
            "profile_samples_differ": bool(np.any(
                material_samples["M01"].albedo != material_samples["M05"].albedo
            )),
            "profile_channel_stats": {
                mid: {
                    "albedo_mean": np.mean(material_samples[mid].albedo, axis=0).tolist(),
                    "albedo_std": np.std(material_samples[mid].albedo, axis=0).tolist(),
                    "roughness_mean": float(np.mean(material_samples[mid].roughness)),
                    "ior_mean": float(np.mean(material_samples[mid].ior)),
                    "layer_ids": list(material_profiles[mid].get("layer_ids", [])),
                }
                for mid in ("M01", "M05", "M07")
            },
            "production_scene_captured": {
                mid: {
                    "albedo_mean": np.mean(item["albedo"], axis=0).tolist(),
                    "albedo_std": np.std(item["albedo"], axis=0).tolist(),
                    "roughness_unique": np.unique(item["roughness"]).tolist(),
                    "source_kind": item["source_kind"],
                }
                for mid, items in captured_scenes.items() for item in items
            },
            "production_rgb_exactly_equal": bool(np.array_equal(image_a, image_b)),
            "production_linear_exactly_equal": bool(np.array_equal(linear_a, linear_b)),
            "changed_uint8_pixels": int(np.sum(np.any(image_a != image_b, axis=2))),
            "max_abs_linear_difference": float(np.max(np.abs(linear_a - linear_b), initial=0.0)),
            "images": ["production_V13_M01.png", "production_V13_M05.png"],
        },
        "pattern_counterfactual": {
            "same_mother_geometry": True,
            "families": pattern_stats,
            "pattern_channels_differ": bool(np.any(
                pattern_channels["PAT01"].albedo != pattern_channels["PAT03"].albedo
            )),
            "same_production_geometry_and_pattern_metadata_rgb_equal": bool(np.array_equal(
                plain_bundle.render.rgb_linear, pat03_bundle.render.rgb_linear
            )),
            "production_metadata_variant_images": [
                "production_V01_M05_target_metadata_PAT01.png",
                "production_V01_M05_target_metadata_PAT03.png",
            ],
            "explicit_channel_preview_image": "display_V01_M05_PAT03_explicit_channel_preview.png",
            "boundary": "The explicit-channel preview manually supplies PatternChannels to build_scene; it is not the generated production observation. The production target metadata probe has no supported pattern binding argument.",
        },
        "source_notes": {
            "routes.py": "render_frame_bundles calls build_scene(mesh, surface_tag, face_id, name); no albedo/roughness/profile/recipe is passed.",
            "render.py": "build_scene defaults to deterministic procedural_albedo(face_count) and constant roughness 0.55.",
            "materials_api": "material_at yields per-point albedo/roughness/IOR, but MaterialSpec only carries per-face albedo/roughness/source_kind.",
            "patterns_api": "evaluate yields PatternChannels, but production render_frame_bundles has no channel argument.",
        },
    }
    (OUT / "production_counterfactual.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
