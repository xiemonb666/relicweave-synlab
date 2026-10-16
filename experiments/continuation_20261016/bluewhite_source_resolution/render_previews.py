"""Render this experiment through the shared VTK PBR path and report real texture sizes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import runpy
from pathlib import Path

import numpy as np


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
SHARED_RENDERER = (REPO / "experiments" / "continuation_20261015"
                   / "reference_generation" / "render_previews.py")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--preview-revision", default="source_resolved_v1")
    parser.add_argument("--lighting", choices=("legacy", "studio_ibl"), default="studio_ibl")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", args.preview_revision):
        raise ValueError("--preview-revision must be a lowercase filename-safe slug")
    output_root = args.output.expanduser().resolve()
    manifest_path = output_root / "experiment_manifest.json"
    preview_manifest_path = output_root / f"preview_manifest_{args.preview_revision}.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"experiment manifest is missing: {manifest_path}")
    if preview_manifest_path.exists():
        raise FileExistsError(f"refusing to overwrite preview manifest: {preview_manifest_path}")

    renderer = runpy.run_path(str(SHARED_RENDERER), run_name="synlab_shared_preview_renderer")
    experiment = json.loads(manifest_path.read_text(encoding="utf-8"))
    instance_rows = experiment.get("instances", [])
    if not 1 <= len(instance_rows) <= 8:
        raise ValueError(f"expected one to eight generated instances, found {len(instance_rows)}")
    rows = []
    for item in instance_rows:
        bundle = output_root / item["bundle"]
        rendered = renderer["render"](bundle, args.preview_revision,
                                      lighting_mode=args.lighting)
        with np.load(bundle / "appearance_texture.npz", allow_pickle=False) as texture:
            stored_shape = list(texture["outer_texture_linear_rgb"].shape[:2])
        rendered["texture_grid"] = stored_shape
        rows.append(rendered)

    if args.lighting == "studio_ibl":
        environment, environment_info = renderer["_neutral_studio_environment"]()
    else:
        environment = None
        environment_info = {
            "model": "existing four-scene-light preview setup",
            "image_based_lighting": False,
            "calibrated_optics": False,
            "scene_light_intensities": [1.10, 0.55, 0.38, 0.42],
        }
    texture_origin_probe = renderer["_render_texture_origin_probe"](
        output_root, args.preview_revision, args.lighting, environment, environment_info)
    preview_manifest = {
        "schema": "synlab.reference_generation_preview_manifest.v5",
        "preview_revision": args.preview_revision,
        "lighting_mode": args.lighting,
        "renderer": "shared VTK PBR appearance path with continuous outer-wall texture",
        "preview_views": rows[0]["view_definitions"],
        "view_specs": rows[0]["view_specs"],
        "panel_detail_artifacts": [detail for row in rows
                                    for detail in row.get("panel_details", [])],
        "lighting": rows[0]["lighting"],
        "texture_origin_probe": texture_origin_probe,
        "texture_grids_s_theta": [row["texture_grid"] for row in rows],
        "normal_policy": "source shared-vertex normals computed before UV duplication",
        "geometry_changed": False,
        "physical_rendering_claim": "NONE",
        "files": rows,
    }
    preview_manifest_path.write_text(json.dumps(
        preview_manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8")
    experiment["previews"] = {
        "manifest": preview_manifest_path.name,
        "manifest_sha256": _sha256(preview_manifest_path),
        "files": rows,
        "texture_origin_probe": texture_origin_probe,
    }
    for item, preview in zip(experiment["instances"], rows):
        item["bundle_manifest_sha256"] = preview["bundle_manifest_sha256"]
        item["preview_sha256"] = preview["sha256"]
        bundle = output_root / item["bundle"]
        item["files"][preview["preview"]] = preview["sha256"]
        for detail in preview.get("panel_details", []):
            item["files"][detail["preview"]] = detail["sha256"]
        item["files"]["sha256_receipt.json"] = _sha256(bundle / "sha256_receipt.json")
        item["files"]["manifest.json"] = preview["bundle_manifest_sha256"]
    for _ in range(10):
        current_total = sum(path.stat().st_size for path in output_root.rglob("*")
                            if path.is_file() and path != manifest_path)
        payload = json.dumps(experiment, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        disk_payload = payload.replace("\n", os.linesep)
        output_bytes = current_total + len(disk_payload.encode("utf-8"))
        if experiment.get("output_bytes") == output_bytes:
            break
        experiment["output_bytes"] = output_bytes
    payload = json.dumps(experiment, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    manifest_path.write_bytes(payload.replace("\n", os.linesep).encode("utf-8"))
    actual_total = sum(path.stat().st_size for path in output_root.rglob("*")
                       if path.is_file())
    if actual_total != experiment.get("output_bytes"):
        raise RuntimeError("experiment output byte count did not converge to exact total")
    if actual_total > 256 * 1024 * 1024:
        raise RuntimeError("rendered experiment exceeds the 256 MiB output limit")
    print(json.dumps({"previews": len(rows), "texture_grids_s_theta": [
        row["texture_grid"] for row in rows], "manifest": str(preview_manifest_path),
        "manifest_sha256": _sha256(preview_manifest_path)}, indent=2))


if __name__ == "__main__":
    main()
