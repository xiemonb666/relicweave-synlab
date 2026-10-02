"""Scratch probe: why did SfM find no matches? (not a test; run manually).

Takes an existing photo_mvs work directory and re-runs extraction+matching twice on the
*same* images:

  ``with_mask``    as the route ran it (deployment-mask PNGs)
  ``without_mask`` the mask input removed

and reports, from the COLMAP database, how many features and how many matches each
configuration produced.  Also measures the image/mask statistics the run handed in.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402


def image_stats(workdir: Path) -> dict:
    images = sorted((workdir / "images").glob("*.png"))
    masks = sorted((workdir / "masks").glob("*.png"))
    rows = []
    for path in images[:3]:
        img = cv2.imread(str(path), cv2.IMREAD_COLOR)
        mask_path = workdir / "masks" / f"{path.name}.png"
        mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE) if mask_path.exists() else None
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        lap = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        rows.append({
            "image": path.name,
            "size": [int(img.shape[1]), int(img.shape[0])],
            "uint8_mean": float(gray.mean()),
            "uint8_std": float(gray.std()),
            "laplacian_var": lap,
            "unique_levels": int(len(np.unique(gray))),
            "mask_exists": bool(mask is not None),
            "mask_coverage": (float(np.mean(mask > 0)) if mask is not None else None),
            "mask_pixels": (int(np.count_nonzero(mask > 0)) if mask is not None else None),
        })
    return {"n_images": len(images), "n_masks": len(masks), "per_image": rows}


def run_colmap(images_dir: Path, masks_dir: Path | None, *, max_features: int = 8192,
               max_image_size: int = 1024) -> dict:
    import pycolmap

    work = Path(tempfile.mkdtemp(prefix="sfm_probe_"))
    db = work / "database.db"
    names = sorted(p.name for p in images_dir.glob("*.png"))
    reader = pycolmap.ImageReaderOptions()
    reader.camera_model = "SIMPLE_RADIAL"
    if masks_dir is not None:
        reader.mask_path = str(masks_dir)
    sift = pycolmap.SiftExtractionOptions()
    sift.max_image_size = int(max_image_size)
    sift.max_num_features = int(max_features)
    sift.num_threads = 2
    out: dict = {"mask_path": None if masks_dir is None else str(masks_dir)}
    try:
        pycolmap.extract_features(str(db), str(images_dir), names, pycolmap.CameraMode.AUTO,
                                  "SIMPLE_RADIAL", reader, sift)
        pycolmap.match_exhaustive(str(db), device=pycolmap.Device.cpu)
        out["status"] = "OK"
    except Exception as exc:  # noqa: BLE001
        out["status"] = f"RAISED {type(exc).__name__}: {exc}"
        return out
    import sqlite3

    with sqlite3.connect(str(db)) as conn:
        out["n_keypoints"] = int(conn.execute("SELECT COUNT(*) FROM keypoints").fetchone()[0])
        out["n_descriptors"] = int(conn.execute("SELECT COUNT(*) FROM descriptors")
                                   .fetchone()[0])
        out["n_matches"] = int(conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0])
        out["n_two_view"] = int(conn.execute(
            "SELECT COUNT(*) FROM two_view_geometries").fetchone()[0])
        rows = conn.execute("SELECT image_id, rows FROM keypoints").fetchall()
        out["keypoints_per_image"] = {int(i): int(r) for i, r in rows}
    try:
        maps = pycolmap.incremental_mapping(str(db), str(images_dir), str(work / "sparse"))
        out["n_models"] = len(maps)
        if maps:
            best = max(maps.values(), key=lambda m: m.num_reg_images())
            out["num_reg_images"] = int(best.num_reg_images())
            out["num_points3D"] = int(best.num_points3D())
            out["mean_reproj_error_px"] = float(best.compute_mean_reprojection_error())
    except Exception as exc:  # noqa: BLE001
        out["reconstruction_error"] = f"{type(exc).__name__}: {exc}"
    shutil.rmtree(work, ignore_errors=True)
    return out


def main() -> int:
    workdir = Path(sys.argv[1])
    report = {"workdir": str(workdir), "image_stats": image_stats(workdir)}
    report["with_mask"] = run_colmap(workdir / "images", workdir / "masks")
    report["without_mask"] = run_colmap(workdir / "images", None)
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
