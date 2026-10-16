"""Run source-guided pattern samples against a real generated MotherGeometry.

From ``relicweave-synlab`` run:
    .venv\\Scripts\\python.exe experiments\\continuation_20261015\\reference_styles\\generate_reference_style_previews.py

The preview is an unwrapped chart visualization of the frozen fields. Acceptance samples,
seam/determinism audits and fracture-interface fallback checks query the actual mother.
"""

from __future__ import annotations

import hashlib
import json
import platform
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from synlab.mothers.api import create_mother, default_params
from synlab.patterns.api import audit_pattern, evaluate, pattern_field
from synlab.patterns.charts import resolve_frame, surface_samples
from synlab.patterns.fields import smoothstep
from synlab.patterns.reference_styles import build_reference_pattern
from synlab.seeds import make_rng


OUT = Path(__file__).resolve().parent
SEED = 20261015
VESSEL_ID = "V01"
MATERIAL_ID = "M01"
STYLE_IDS = ("daily_hasami_tokusa", "historical_met_jun_plain")


def _sha256(array: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest()


def _linear_to_srgb(rgb: np.ndarray) -> np.ndarray:
    values = np.clip(np.asarray(rgb, dtype=np.float64), 0.0, 1.0)
    encoded = np.where(values <= 0.0031308, 12.92 * values,
                       1.055 * np.power(values, 1.0 / 2.4) - 0.055)
    return np.asarray(np.rint(255.0 * encoded), dtype=np.uint8)


def _chart_preview(recipe, frame, *, width: int = 960, height: int = 220) -> Image.Image:
    x = np.linspace(0.0, float(frame.x_period_mm), width, endpoint=False)
    s = np.linspace(float(frame.s_min_mm), float(frame.s_max_mm), height)
    xx, ss = np.meshgrid(x, s)
    field = pattern_field(recipe, xx.ravel(), ss.ravel())
    region = recipe.meta["regions"][0]
    lo, hi = float(region["s_min_mm"]), float(region["s_max_mm"])
    feather = float(region.get("feather_mm", 0.0))
    if feather > 0.0:
        weight = smoothstep(lo - feather, lo, ss.ravel()) * \
            (1.0 - smoothstep(hi, hi + feather, ss.ravel()))
    else:
        weight = ((ss.ravel() >= lo) & (ss.ravel() <= hi)).astype(np.float64)
    coverage = np.clip(field.coverage * weight, 0.0, 1.0)
    palette = recipe.meta["palette"]
    body = np.asarray(palette["body"], dtype=np.float64)
    rgb = body[None, :] * (1.0 - coverage[:, None]) + field.paint * coverage[:, None]
    pixels = _linear_to_srgb(rgb).reshape(height, width, 3)
    return Image.fromarray(pixels, mode="RGB")


def _mesh_preview(mother, recipe, *, width: int = 350, height: int = 200,
                  max_edge_mm: float = 2.0) -> tuple[Image.Image, int]:
    """Rasterize a temporary subdivided display copy; source mother arrays stay untouched."""
    import trimesh

    vertices, faces, source_face = trimesh.remesh.subdivide_to_size(
        np.asarray(mother.mesh.vertices, dtype=np.float64),
        np.asarray(mother.mesh.faces, dtype=np.int64),
        max_edge=float(max_edge_mm), max_iter=8, return_index=True,
    )
    triangles = vertices[faces]
    points = triangles.mean(axis=1)
    tags = np.asarray(mother.face_surface_tag, dtype=np.int64)[source_face]
    channels = evaluate(recipe, mother, points, tags)
    colors = _linear_to_srgb(channels.albedo)
    edge_a = triangles[:, 1] - triangles[:, 0]
    edge_b = triangles[:, 2] - triangles[:, 0]
    normals = np.cross(edge_a, edge_b)
    norms = np.linalg.norm(normals, axis=1)
    normals /= np.maximum(norms[:, None], 1e-12)
    light = np.asarray([-0.35, -0.55, 0.76], dtype=np.float64)
    light /= np.linalg.norm(light)
    shade = 0.68 + 0.32 * np.abs(normals @ light)
    colors = np.asarray(np.clip(colors.astype(np.float64) * shade[:, None], 0, 255), dtype=np.uint8)

    center = vertices.mean(axis=0)
    toward_camera = np.asarray([1.8, -4.0, 1.7], dtype=np.float64)
    toward_camera /= np.linalg.norm(toward_camera)
    right = np.cross(np.asarray([0.0, 0.0, 1.0]), toward_camera)
    right /= np.linalg.norm(right)
    up = np.cross(toward_camera, right)
    relative = vertices - center[None, :]
    projected = np.column_stack([relative @ right, relative @ up])
    px, py = projected[:, 0], projected[:, 1]
    span_x = max(float(px.max() - px.min()), 1e-9)
    span_y = max(float(py.max() - py.min()), 1e-9)
    scale = min((width - 22) / span_x, (height - 18) / span_y)
    x_pixels = 0.5 * width + (px - 0.5 * (px.max() + px.min())) * scale
    y_pixels = 0.5 * height - (py - 0.5 * (py.max() + py.min())) * scale
    projected_faces = np.stack([x_pixels[faces], y_pixels[faces]], axis=-1)
    depth = (points - center[None, :]) @ toward_camera

    image = Image.new("RGB", (width, height), (246, 245, 241))
    draw = ImageDraw.Draw(image)
    for index in np.argsort(depth):
        polygon = [(float(x), float(y)) for x, y in projected_faces[index]]
        color = tuple(int(value) for value in colors[index])
        draw.polygon(polygon, fill=color)
    return image, int(faces.shape[0])


def _build_run():
    mother = create_mother(
        VESSEL_ID, MATERIAL_ID, default_params(VESSEL_ID),
        make_rng(SEED, "shape"), mother_id=f"reference-styles-{VESSEL_ID}-{SEED}",
    )
    vertices_before = _sha256(np.asarray(mother.mesh.vertices))
    faces_before = _sha256(np.asarray(mother.mesh.faces))
    tags_before = _sha256(np.asarray(mother.face_surface_tag))
    frame = resolve_frame(mother, "outer_wall")
    if frame.to_xyz is not None:
        inverse_mapping = "chart.meta.uv_to_xyz"
    else:
        inverse_mapping = "no chart inverse; preview samples the measured chart coordinates and evaluation samples the real tagged mesh"

    image = Image.new("RGB", (1120, 590), (250, 249, 246))
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    draw.text((32, 22), "Synthetic reference-guided pattern recipes", fill=(28, 35, 42), font=font)
    draw.text((32, 42),
              "Left: actual mother display copy | right: unwrapped outer-wall chart",
              fill=(72, 79, 85), font=font)
    draw.text((32, 59), "Colors are uncalibrated design proxies", fill=(72, 79, 85), font=font)

    face_centres = np.asarray(mother.mesh.triangles_center, dtype=np.float64)
    face_tags = np.asarray(mother.face_surface_tag, dtype=np.int64)
    report = {
        "schema": "synlab.reference_style_preview.v1",
        "generation_mode": "SYNTHETIC_REFERENCE_GUIDED",
        "master_seed": SEED,
        "mother": {
            "mother_id": mother.mother_id,
            "vessel_id": mother.vessel_id,
            "material_id": mother.material_id,
            "faces": int(len(mother.mesh.faces)),
            "vertices": int(len(mother.mesh.vertices)),
            "outer_chart": frame.as_dict(),
        "preview_mapping": inverse_mapping,
        "mesh_display_subdivision_max_edge_mm": 2.0,
        },
        "styles": {},
        "geometry_unchanged": None,
        "limitations": [
            "The PNG is an unwrapped chart preview, not a calibrated photograph or physically lit render.",
            "The preview samples the real mother's measured chart bounds; the acceptance receipt additionally evaluates area-weighted points on its actual outer_wall mesh.",
            "The Tokusa pattern engine does not model brush taper, underglaze pigment diffusion/bleed, glaze pooling or measured reflectance.",
            "The Jun style is a flat PAT01 blue-gray albedo proxy; glaze chemistry, thickness, pooling, opalescence, crazing and firing behavior are not simulated here.",
            "The catalogued Hacilar chevron candidate remains research-only because rim, body and projection charts are not source-aligned in the generic adapter.",
        ],
    }

    outer_tag = int(frame.tag)
    for row, style_id in enumerate(STYLE_IDS):
        recipe = build_reference_pattern(mother, style_id, SEED)
        points, sampled_faces = surface_samples(
            mother, 6000, make_rng(SEED, style_id, "outer-validation"), tag=outer_tag)
        channels = evaluate(recipe, mother, points, "outer_wall")
        audit = audit_pattern(recipe, mother, n_pairs=256, scale_samples=96,
                              geometry_probe=False)
        interface = evaluate(recipe, mother, points[:32], "interface")
        body = np.asarray(recipe.meta["palette"]["body"], dtype=np.float32)
        fracture_fallback = bool(
            interface.meta.get("unpatterned_reason") == "new_fracture_surface_exposes_body"
            and np.allclose(interface.albedo, body[None, :], atol=1e-6)
            and np.all(interface.pattern_region == 0)
            and np.all(interface.height_mm == 0.0)
        )
        if not audit.get("pass") or not fracture_fallback:
            raise RuntimeError(f"acceptance failed for {style_id}: audit={audit.get('failures')}, "
                               f"fracture_fallback={fracture_fallback}")

        texture = _chart_preview(recipe, frame, width=580, height=200)
        mesh_view, display_face_count = _mesh_preview(mother, recipe)
        panel_top = 96 + row * 235
        draw.text((32, panel_top), style_id, fill=(28, 35, 42), font=font)
        draw.text((32, panel_top + 20), recipe.family_id, fill=(72, 79, 85), font=font)
        draw.text((32, panel_top + 38), f"seed {SEED}", fill=(72, 79, 85), font=font)
        image.paste(mesh_view, (150, panel_top))
        image.paste(texture, (520, panel_top))
        draw.rectangle((149, panel_top - 1, 1110, panel_top + 200), outline=(210, 208, 202), width=1)
        style_receipt = {
            "recipe_hash": recipe.meta["recipe_hash"],
            "family_id": recipe.family_id,
            "palette_id": recipe.meta["palette_id"],
            "seed_ref": recipe.seed_ref,
            "region": recipe.meta["regions"][0],
            "source_status": recipe.meta["reference_style"]["evidence_status"],
            "sampled_outer_mesh_points": int(points.shape[0]),
            "sampled_outer_face_index_count": int(sampled_faces.shape[0]),
            "sampled_pattern_region_count": int(channels.pattern_region.sum()),
            "sampled_pattern_region_fraction": float(channels.pattern_region.mean()),
            "face_centroid_pattern_region_count": int(
                evaluate(recipe, mother, face_centres, face_tags).pattern_region.sum()),
            "display_subdivided_face_count": display_face_count,
            "display_subdivision_is_temporary_copy": True,
            "height_max_abs_mm": float(np.max(np.abs(channels.height_mm))) if len(points) else 0.0,
            "seam_pass": bool(audit["seam"]["chart_space"]["pass"]),
            "seam_max_abs_color_error": float(audit["seam"]["chart_space"]["max_abs_color_error"]),
            "determinism_pass": bool(audit["determinism"]["pass"]),
            "inheritance_pass": bool(audit["inheritance"]["pass"]),
            "audit_pass": bool(audit["pass"]),
            "fracture_interface_body_fallback_pass": fracture_fallback,
            "audit": audit,
        }
        report["styles"][style_id] = style_receipt

    report["geometry_unchanged"] = bool(
        vertices_before == _sha256(np.asarray(mother.mesh.vertices))
        and faces_before == _sha256(np.asarray(mother.mesh.faces))
        and tags_before == _sha256(np.asarray(mother.face_surface_tag))
    )
    if not report["geometry_unchanged"]:
        raise RuntimeError("pattern preview mutated the mother geometry or surface tags")
    report["runtime"] = {"python": platform.python_version(), "implementation": platform.python_implementation()}
    report["preview"] = {
        "file": "reference_style_preview.png",
        "width_px": image.width,
        "height_px": image.height,
        "format": "PNG",
        "display_encoding": "linear sRGB primaries encoded to sRGB for PNG display",
        "rendering": "PIL painter-order raster of a temporary subdivided mesh copy with simple visualization shading; not a calibrated renderer",
    }
    image.save(OUT / "reference_style_preview.png", format="PNG", optimize=True)
    (OUT / "evaluation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    result = _build_run()
    print(json.dumps({
        "mother_id": result["mother"]["mother_id"],
        "geometry_unchanged": result["geometry_unchanged"],
        "preview": str(OUT / "reference_style_preview.png"),
        "evaluation": str(OUT / "evaluation.json"),
        "styles": {key: {"family_id": val["family_id"],
                         "sampled_pattern_region_fraction": val["sampled_pattern_region_fraction"],
                         "audit_pass": val["audit_pass"],
                         "fracture_interface_body_fallback_pass": val["fracture_interface_body_fallback_pass"]}
                   for key, val in result["styles"].items()},
    }, ensure_ascii=False, indent=2))
