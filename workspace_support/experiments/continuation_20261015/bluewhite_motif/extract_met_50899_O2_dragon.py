"""Extract a bounded, fired-photo cobalt projection from Met object 50899.

The mask is a chroma-derived view of the photographed fired surface. It does
not recover the original underglaze brush deposit or pre-firing pigment flow.
No blur, diffusion, inpainting, or morphological cleanup is applied.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[3]
RESOURCE = ROOT / "relicweave-synlab/synlab/patterns/resources/bluewhite_20261015"
SOURCE = RESOURCE / "source/met_50899_O2_original.jpg"
DERIVED = RESOURCE / "derived"
REPORT = Path(__file__).resolve().parent / "extraction_report.json"

# Source image pixel coordinates, left/top/right/bottom. This cropped view
# centers the named dragon on the bulbous shoulder/body while retaining the
# visible wrap at both sides. The crop is exactly 2,000 px wide.
CROP_BOX = (300, 2000, 2300, 3160)
CHROMA_ZERO = 6.0
CHROMA_FULL = 72.0
STRONG_CHROMA_SUPPORT = 55.0


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    DERIVED.mkdir(parents=True, exist_ok=True)
    with Image.open(SOURCE) as source:
        source_size = source.size
        crop = source.convert("RGB").crop(CROP_BOX)

    crop_path = DERIVED / "met_50899_O2_dragon_projection_crop.png"
    mask_path = DERIVED / "met_50899_O2_dragon_cobalt_fired_photo_mask.png"
    support_path = DERIVED / "met_50899_O2_dragon_strong_cobalt_support_proxy.png"
    crop.save(crop_path, format="PNG", optimize=True)

    rgb = np.asarray(crop, dtype=np.float32)
    red, green, blue = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    # Positive blue-channel excess over both warm channels acts as a simple,
    # inspectable cobalt-color selector. Values below the floor map to zero;
    # stronger blue excess maps linearly to white. This retains captured
    # photo softness and glaze variation without adding a blur.
    blue_excess = blue - np.maximum(red, green)
    density = np.clip(
        (blue_excess - CHROMA_ZERO) / (CHROMA_FULL - CHROMA_ZERO), 0.0, 1.0
    )
    mask = np.rint(density * 255.0).astype(np.uint8)
    Image.fromarray(mask, mode="L").save(mask_path, format="PNG", optimize=True)
    support = np.where(blue_excess >= STRONG_CHROMA_SUPPORT, 255, 0).astype(np.uint8)
    Image.fromarray(support, mode="L").save(support_path, format="PNG", optimize=True)

    nonzero = mask[mask > 0]
    report = {
        "source_path": str(SOURCE.relative_to(ROOT)).replace("\\", "/"),
        "source_sha256": sha256(SOURCE),
        "source_dimensions_px": {"width": source_size[0], "height": source_size[1]},
        "crop_box_source_px_ltrb": list(CROP_BOX),
        "crop_dimensions_px": {"width": crop.width, "height": crop.height},
        "mask_path": str(mask_path.relative_to(ROOT)).replace("\\", "/"),
        "mask_dimensions_px": {"width": crop.width, "height": crop.height},
        "mask_value_semantics": "0=no detected cobalt chroma; 255=strong cobalt chroma",
        "blue_excess_thresholds_rgb_units": {
            "zero_at_or_below": CHROMA_ZERO,
            "full_at_or_above": CHROMA_FULL,
            "formula": "clamp((B - max(R, G) - zero) / (full - zero), 0, 1)",
        },
        "mask_nonzero_pixel_fraction": float(np.count_nonzero(mask) / mask.size),
        "nonzero_mask_quantiles": (
            [int(v) for v in np.quantile(nonzero, [0.1, 0.5, 0.9]).round()]
            if nonzero.size
            else []
        ),
        "strong_support_path": str(support_path.relative_to(ROOT)).replace("\\", "/"),
        "strong_support_threshold_rgb_units": STRONG_CHROMA_SUPPORT,
        "strong_support_pixel_fraction": float(np.count_nonzero(support) / support.size),
        "strong_support_semantics": (
            "binary cut of stronger observed cobalt chroma; optional sharper simulation seed, "
            "not recovered pre-firing brush placement"
        ),
        "output_files": {
            path.name: {
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
            for path in (crop_path, mask_path, support_path)
        },
        "processing": [
            "crop the Met O2 photograph to CROP_BOX",
            "save the cropped photograph losslessly as PNG",
            "derive grayscale cobalt density from blue-channel excess",
            "derive optional binary high-chroma support cut for a sharper simulation seed",
            "apply no blur, diffusion, inpainting, morphology, or semantic redraw",
        ],
        "interpretation_limit": (
            "Fired-photo projection only: camera color, glaze, illumination,"
            " compression/photographic softness, and vessel curvature remain."
            " This is not the recovered pre-firing brush deposit."
        ),
    }
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
