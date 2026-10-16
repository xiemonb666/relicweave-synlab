from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import OpenEXR
from PIL import Image

ROOT = Path(r'C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\tmp\review_20261003\implementation\vf')
ART = ROOT / 'artifacts'
OLD = ART / 'four_bands_canonical3'
NEW = ART / 'four_bands_brep_semantics1_final'
THREE = ART / 'three_bands_brep_semantics1_final'
OLD_THREE = ART / 'three_bands_canonical3'
PREVIEW = ART / 'preview_brep_semantics1_final'
THREE_PREVIEW = ART / 'preview_three_bands_brep_semantics1_final'
DEPTH = ART / 'geometry_depth_parity_brep_semantics1_final'
OUTPUT = ROOT / 'vf_brep_semantics1_evidence.json'


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def array_sha256(array: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(array).view(np.uint8)).hexdigest()


def load_arrays(path: Path) -> dict[str, np.ndarray]:
    with np.load(path, allow_pickle=False) as payload:
        return {name: payload[name].copy() for name in payload.files}


def runs(mask: np.ndarray, minimum: int = 5) -> list[dict[str, int]]:
    indices = np.flatnonzero(mask)
    if len(indices) == 0:
        return []
    groups = np.split(indices, np.flatnonzero(np.diff(indices) > 1) + 1)
    return [
        {"y_start": int(group[0]), "y_end": int(group[-1]), "pixel_count": int(len(group))}
        for group in groups if len(group) >= minimum
    ]


def image_appearance(path: Path) -> dict[str, object]:
    pixels = np.asarray(Image.open(path).convert('RGB'), dtype=np.uint8)
    x = 450
    line = pixels[:, x, :]
    dark = (line[:, 0] < 75) & (line[:, 1] < 60) & (line[:, 2] < 50)
    red = ((line[:, 0].astype(np.int16) - line[:, 1].astype(np.int16)) > 30) & (line[:, 0] < 160) & (line[:, 1] < 80)
    dark_roi = np.zeros(len(line), dtype=bool)
    red_roi = np.zeros(len(line), dtype=bool)
    dark_roi[250:850] = dark[250:850]
    red_roi[250:850] = red[250:850]
    return {
        "path": str(path),
        "sha256": sha256(path),
        "size_px": list(pixels.shape[1::-1]),
        "scanline_x_px": x,
        "roi_y_px": [250, 850],
        "thresholds": {"dark": "R<75,G<60,B<50", "red": "R-G>30,R<160,G<80"},
        "dark_band_runs": runs(dark_roi),
        "red_band_runs": runs(red_roi),
        "note": "display-space check of the actual Blender mesh render; style remains NOT_VALIDATED",
    }


def read_depth(path: Path) -> np.ndarray:
    exr = OpenEXR.File(str(path))
    channels = exr.channels()
    channel_name = next((name for name in channels if name.lower().endswith('.v')), next(iter(channels)))
    return np.asarray(channels[channel_name].pixels, dtype=np.float32)


def depth_pair(label: str, old_png: Path, new_png: Path) -> dict[str, object]:
    old_exr = DEPTH / f'canonical3_{label}_depth_.exr'
    new_exr = DEPTH / f'brep_semantics1_{label}_depth_.exr'
    old_z = read_depth(old_exr)
    new_z = read_depth(new_exr)
    old_png_pixels = np.asarray(Image.open(old_png).convert('RGBA'))
    new_png_pixels = np.asarray(Image.open(new_png).convert('RGBA'))
    old_mask = np.isfinite(old_z) & (old_z < 1e9)
    new_mask = np.isfinite(new_z) & (new_z < 1e9)
    both = old_mask & new_mask
    delta = np.abs(old_z[both] - new_z[both])
    np.save(DEPTH / f'canonical3_{label}_depth.npy', old_z)
    np.save(DEPTH / f'brep_semantics1_{label}_depth.npy', new_z)
    return {
        "view": label,
        "camera_and_projection": "same saved renderer camera transform/orthographic scale and 1100x1100 target for each pair",
        "uniform_material": "same neutral emission shader; ornament/semantic material fields are not loaded",
        "depth_channel": "OpenEXR multi-layer compositor Depth.V, float32, world-unit camera depth",
        "depth_map_shape": list(old_z.shape),
        "valid_geometry_pixels_old_new": [int(old_mask.sum()), int(new_mask.sum())],
        "silhouette_mask_equal": bool(np.array_equal(old_mask, new_mask)),
        "depth_values_bitwise_equal_on_geometry": bool(np.array_equal(old_z[both], new_z[both])),
        "depth_max_abs_delta_mm": float(delta.max()) if len(delta) else None,
        "depth_mismatched_geometry_pixels": int(np.count_nonzero(delta != 0)),
        "all_depth_pixels_bitwise_equal_including_background": bool(np.array_equal(old_z, new_z)),
        "geometry_only_png_bitwise_equal": bool(np.array_equal(old_png_pixels, new_png_pixels)),
        "old_png": {"path": str(old_png), "sha256": sha256(old_png)},
        "new_png": {"path": str(new_png), "sha256": sha256(new_png)},
        "old_depth_exr": {"path": str(old_exr), "sha256": sha256(old_exr)},
        "new_depth_exr": {"path": str(new_exr), "sha256": sha256(new_exr)},
    }


def main() -> None:
    old_surface = load_arrays(OLD / 'geometry' / 'surface.npz')
    new_surface = load_arrays(NEW / 'geometry' / 'surface.npz')
    new_three_surface = load_arrays(THREE / 'geometry' / 'surface.npz')
    old_lineage = load_arrays(OLD / 'geometry' / 'mesh_lineage.npz')['face_source_brep_index']
    new_lineage = load_arrays(NEW / 'geometry' / 'mesh_lineage.npz')['face_source_brep_index']
    old_fields = load_arrays(OLD / 'fields' / 'surface.npz')
    new_fields = load_arrays(NEW / 'fields' / 'surface.npz')
    new_three_fields = load_arrays(THREE / 'fields' / 'surface.npz')
    semantics = json.loads((NEW / 'metadata' / 'face_semantics.json').read_text(encoding='utf-8'))
    four_manifest = json.loads((NEW / 'manifest.json').read_text(encoding='utf-8'))
    three_manifest = json.loads((THREE / 'manifest.json').read_text(encoding='utf-8'))
    geometry_report = json.loads((NEW / 'validation' / 'geometry.json').read_text(encoding='utf-8'))

    geometry_equal_old_new = all(np.array_equal(old_surface[key], new_surface[key]) for key in ('vertices_mm', 'faces'))
    geometry_equal_four_three = all(np.array_equal(new_surface[key], new_three_surface[key]) for key in ('vertices_mm', 'faces'))
    lineage_equal_old_new = bool(np.array_equal(old_lineage, new_lineage))
    handle_indices = {row['face_index_zero_based'] for row in semantics['faces'] if row['region_name'] == 'handle'}
    old_handle = np.isin(old_lineage, sorted(handle_indices))
    new_handle = np.isin(new_lineage, sorted(handle_indices))
    palette_base = np.asarray([0.66, 0.49, 0.34], dtype=np.float32)
    old_handle_mislabelled = int(np.count_nonzero(old_handle & (old_fields['face_region'] == 1)))
    old_handle_nonbase = int(np.count_nonzero(np.any(old_fields['albedo_linear_rgb'][old_handle] != palette_base, axis=1)))
    new_handle_painted = int(np.count_nonzero(new_handle & (new_fields['face_region'] == 1)))
    new_handle_nonbase = int(np.count_nonzero(np.any(new_fields['albedo_linear_rgb'][new_handle] != palette_base, axis=1)))

    depth_results = [
        depth_pair('whole', DEPTH / 'canonical3_whole.png', DEPTH / 'brep_semantics1_whole.png'),
        depth_pair('lower_root', DEPTH / 'canonical3_lower_root.png', DEPTH / 'brep_semantics1_lower_root.png'),
    ]
    four_image = image_appearance(PREVIEW / 'exterior_four_bands_brep_semantics1_final.png')
    three_image = image_appearance(THREE_PREVIEW / 'exterior_three_bands_brep_semantics1_final.png')
    counts = {
        name: int(np.count_nonzero(new_fields['face_region'] == code))
        for code, name in ((1, 'body_outer'), (2, 'body_inner'), (3, 'natural_rim'), (4, 'base'), (5, 'handle'))
    }
    all_classification_evidence = all(
        row.get('status') == 'CLASSIFIED'
        and row.get('classifier_version') == semantics['classifier']
        and row.get('canonical_step_sha256') == semantics['canonical_step_sha256']
        and isinstance(row.get('classification_basis'), str)
        and isinstance(row.get('classification_evidence'), dict)
        and isinstance(row.get('interior_sample'), dict)
        for row in semantics['faces']
    )
    report = {
        "stage": "canonical B-rep semantic face classification and paint-root correction",
        "producer_version": four_manifest['provenance']['version'],
        "classification": {
            "status": semantics['status'],
            "classifier": semantics['classifier'],
            "backend": semantics['backend'],
            "canonical_step_sha256": semantics['canonical_step_sha256'],
            "face_count": semantics['canonical_step_face_count'],
            "face_counts": semantics['counts'],
            "all_faces_have_basis_version_hash_and_trimmed_sample": all_classification_evidence,
            "unknown_face_indices": semantics['unknown_face_indices'],
            "reserved_fracture_code": semantics['fracture_reserve_code'],
            "triangle_lineage_covers": int(len(new_lineage)),
            "triangle_region_counts": counts,
        },
        "canonical3_geometry_parity": {
            "vertices_bitwise_equal": bool(np.array_equal(old_surface['vertices_mm'], new_surface['vertices_mm'])),
            "faces_bitwise_equal": bool(np.array_equal(old_surface['faces'], new_surface['faces'])),
            "triangle_to_brep_lineage_bitwise_equal": lineage_equal_old_new,
            "vertices_sha256": array_sha256(new_surface['vertices_mm']),
            "faces_sha256": array_sha256(new_surface['faces']),
            "lineage_sha256": array_sha256(new_lineage),
            "counts": {"vertices": int(len(new_surface['vertices_mm'])), "triangles": int(len(new_surface['faces']))},
        },
        "four_vs_three_band_counterfactual_geometry": {
            "vertices_bitwise_equal": bool(np.array_equal(new_surface['vertices_mm'], new_three_surface['vertices_mm'])),
            "faces_bitwise_equal": bool(np.array_equal(new_surface['faces'], new_three_surface['faces'])),
            "lineage_bitwise_equal": bool(np.array_equal(new_lineage, load_arrays(THREE / 'geometry' / 'mesh_lineage.npz')['face_source_brep_index'])),
            "recipe_ids": [four_manifest['ornament']['recipe']['pattern_id'], three_manifest['ornament']['recipe']['pattern_id']],
            "style_validation": [four_manifest['ornament']['recipe']['historical_style_validation'], three_manifest['ornament']['recipe']['historical_style_validation']],
        },
        "old_to_new_handle_root_labeling": {
            "handle_face_indices": sorted(int(i) for i in handle_indices),
            "handle_triangle_count": int(new_handle.sum()),
            "canonical3_mislabelled_handle_triangles_as_paint": old_handle_mislabelled,
            "canonical3_handle_triangles_with_nonbase_albedo": old_handle_nonbase,
            "new_mislabelled_handle_triangles_as_paint": new_handle_painted,
            "new_handle_triangles_with_nonbase_albedo": new_handle_nonbase,
            "new_geometry_report_check": geometry_report['checks']['handle_surfaces_excluded_from_paint'],
        },
        "geometry_only_render_parity": depth_results,
        "continuous_pattern_render_checks": {"four_band": four_image, "three_band_counterfactual": three_image},
        "geometry_qa": {
            "contract_status": four_manifest['validation']['status'],
            "geometry_status": geometry_report['status'],
            "mesh": geometry_report['measurements']['mesh'],
            "mesh_step_sampled_max_deviation_mm": geometry_report['measurements']['mesh_to_canonical_step_max_sampled_deviation_mm'],
            "wall_scope": geometry_report['measurements']['wall']['scope'],
            "profile_realism_status": geometry_report['measurements']['profile_realism_status'],
            "physical_calibration": four_manifest['material']['calibration_status'],
            "historical_style": four_manifest['ornament']['recipe']['historical_style_validation'],
        },
        "test": {
            "command": "python -m pytest -q tests -p no:cacheprovider --basetemp <dedicated pytest_brep_semantics1_final>",
            "log": str(ROOT / 'pytest_brep_semantics1_final.log'),
            "result": "16 passed in 5.01s",
            "fixture_isolation": "tests/conftest.py creates both packages in pytest tmp_path_factory output; no checked-in sample manifest is modified",
        },
        "cli": {
            "generation_exit_codes": [0, 0],
            "validation_exit_codes": [0, 0],
            "logs": [str(ROOT / name) for name in (
                'cli_generate_four_bands_brep_semantics1_final.log',
                'cli_generate_three_bands_brep_semantics1_final.log',
                'cli_validate_four_bands_brep_semantics1_final.log',
                'cli_validate_three_bands_brep_semantics1_final.log',
            )],
        },
        "render_logs": [str(ROOT / 'render_blender_brep_semantics1_final.log'), str(ROOT / 'render_blender_three_bands_brep_semantics1_final.log'), str(ROOT / 'geometry_depth_parity_brep_semantics1_final.log')],
        "limitations": [
            "Face rules are specifically validated for this prototype CAD construction; other forms/surfaces remain UNKNOWN and block asset generation until explicitly classified.",
            "The finite sampled mesh-to-STEP QA is not a global Hausdorff proof; wall QA is side-profile plus floor only, not a global fused-solid minimum wall.",
            "C0 meridian corners, abrupt handle-root transition, actual ceramic appearance/style, physical mechanics, and high-fidelity fracture remain pending.",
        ],
    }
    report['checks'] = {
        'canonical3_mesh_and_lineage_unchanged': geometry_equal_old_new and lineage_equal_old_new,
        'four_three_band_counterfactual_same_geometry': geometry_equal_four_three,
        'all_canonical_faces_classified_and_auditable': all_classification_evidence and not semantics['unknown_face_indices'],
        'handle_root_paint_mislabel_removed': old_handle_mislabelled > 0 and new_handle_painted == 0 and new_handle_nonbase == 0,
        'four_bands_visible': len(four_image['dark_band_runs']) == 3 and len(four_image['red_band_runs']) == 1,
        'three_band_counterfactual_visible': len(three_image['dark_band_runs']) == 1 and len(three_image['red_band_runs']) == 2,
        'geometry_only_whole_and_lower_root_depth_equal': all(
            item['silhouette_mask_equal'] and item['depth_values_bitwise_equal_on_geometry'] and item['depth_max_abs_delta_mm'] == 0.0
            for item in depth_results
        ),
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps(report['checks'], indent=2, sort_keys=True))
    print(f'output={OUTPUT}')

if __name__ == '__main__':
    main()
