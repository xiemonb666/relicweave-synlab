"""Before/after measurement of the three silent export defects (D1 tokens, D2 view_pos, D3 frame_id).

Usage:
  python _measure_export_defects.py <package_dir> [<store_root>]

``<package_dir>`` is measured as it is on disk (before *and* after a re-export are measured by the
same code); ``<store_root>`` -- when given -- adds the ground truth the fixes are checked against
(``T_WC`` for ``view_pos``, ``K``/``T_WC``/``depth_z`` for ``frame_id``).
"""
from __future__ import annotations

import json
import sqlite3
import sys
import tarfile
import io
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from synlab.storage.export import TOKEN_DIM, TOKEN_BLOCK  # noqa: E402


def token_metrics(tokens: np.ndarray) -> dict:
    """Effective rank of the token block, and whether it is a broadcast of one scalar."""
    matrix = np.asarray(tokens, dtype=np.float64)
    n, columns = matrix.shape
    out = {"shape": [int(n), int(columns)]}
    if n == 0:
        return out
    singular = np.linalg.svd(matrix, compute_uv=False)
    tolerance = singular[0] * max(n, columns) * np.finfo(np.float64).eps
    out["sv0"] = float(singular[0])
    out["sv1"] = float(singular[1]) if singular.size > 1 else 0.0
    out["sv1_over_sv0"] = float(singular[1] / singular[0]) if singular.size > 1 and singular[0] else 0.0
    out["numerical_rank"] = int((singular > tolerance).sum())
    out["effective_rank_1e-6"] = int((singular > singular[0] * 1e-6).sum())
    # the old writer's exact fingerprint: every column k is column 0 * (1 - 1e-6 k)
    first = matrix[:, 0]
    scale = (1.0 - 1e-6 * np.arange(columns))
    predicted = first[:, None] * scale[None, :]
    out["max_abs_error_vs_scaled_broadcast"] = float(np.abs(matrix - predicted).max())
    out["columns_equal_to_scaled_column0"] = int(np.count_nonzero(
        np.abs(matrix - predicted).max(axis=0) <= 1e-6))
    out["nonzero_fraction"] = float(np.count_nonzero(matrix) / matrix.size)
    out["column_std_median"] = float(np.median(matrix.std(axis=0)))
    return out


def observation_metrics(tar_path: Path, member_prefix: str) -> dict:
    with tarfile.open(tar_path, "r") as tar:
        names = {m.name for m in tar.getmembers()}
        out = {"members": sorted(names)}
        path = f"{member_prefix}/view_pos.npy"
        if path in names:
            data = np.load(io.BytesIO(tar.extractfile(path).read()), allow_pickle=False)
            out["view_pos"] = {
                "shape": list(np.shape(data)),
                "nonzero": int(np.count_nonzero(data)),
                "finite": int(np.count_nonzero(np.isfinite(data))),
                "unique_finite": int(np.unique(data[np.isfinite(data)]).size),
                "min": float(np.nanmin(data)) if np.size(data) else None,
                "max": float(np.nanmax(data)) if np.size(data) else None,
            }
    return out


def geometry_metrics(npz_path: Path, prefix: str, views: int) -> dict:
    with np.load(npz_path, allow_pickle=False) as data:
        frame_id = np.asarray(data[f"{prefix}__frame_id"])
        points = np.asarray(data[f"{prefix}__points"])
    n = int(frame_id.size)
    out = {"n_points": n, "views": int(views)}
    if n == 0:
        return out
    row_counter = (np.arange(n, dtype=np.int64) % max(int(views), 1)).astype(frame_id.dtype)
    out["equals_row_counter"] = bool(np.array_equal(frame_id, row_counter))
    out["unique_values"] = int(np.unique(frame_id).size)
    out["unmatched"] = int((frame_id < 0).sum())
    out["matched_fraction"] = float((frame_id >= 0).sum() / n)
    out["histogram"] = {int(k): int(v) for k, v in zip(*np.unique(frame_id, return_counts=True))}
    # can the row index predict the frame id?  a row counter is a perfect predictor.
    out["row_index_predicts_frame_id"] = bool(np.array_equal(
        frame_id, (np.arange(n, dtype=np.float64) % max(int(views), 1)).astype(frame_id.dtype)))
    out["points_bbox_mm"] = [[float(v) for v in points.min(axis=0)],
                             [float(v) for v in points.max(axis=0)]]
    return out


def store_truth(store: Path) -> dict:
    """Real pose/depth ground truth per fragment, for the error columns of the fixes."""
    truth = {}
    con = sqlite3.connect(str(store / "metadata.sqlite"))
    con.row_factory = sqlite3.Row
    for row in con.execute("select * from assets where role='obs_result' order by asset_id"):
        row = dict(row)
        meta = json.loads(row["meta_json"])
        fragment = str(meta.get("fragment_id") or "")
        arrays_path = store / json.loads(row["files_json"])["arrays"]
        if not fragment or not arrays_path.exists():
            continue
        with np.load(arrays_path, allow_pickle=False) as z:
            poses = [np.asarray(z[f"v{i:03d}.T_WC"], dtype=np.float64)
                     for i in range(len(meta.get("views") or [])) if f"v{i:03d}.T_WC" in z.files]
        truth[fragment] = {"meta_u_position_mm": [v.get("u_position_mm")
                                                  for v in (meta.get("views") or [])],
                           "T_WC_x": [float(p[0, 3]) for p in poses],
                           "camera_centers": [[float(x) for x in p[:3, 3]] for p in poses]}
    return truth


def main(package_dir: str, store_dir: str | None = None) -> int:
    package = Path(package_dir)
    manifest = json.loads((package / "export_manifest.json").read_text(encoding="utf-8"))
    obs_index = json.loads((package / "deploy/obs/index.json").read_text(encoding="utf-8"))
    geometry_index = json.loads((package / "deploy/geometry/index.json").read_text(encoding="utf-8"))
    token_index = json.loads((package / "deploy/tokens/index.json").read_text(encoding="utf-8"))
    report: dict = {
        "package": str(package),
        "package_id": manifest.get("package_id"),
        "release_id": manifest.get("release_id"),
        "token_index_declared": {k: v for k, v in token_index.items() if k != "rows"},
        "obs_index_view_pos_block": obs_index.get("view_pos"),
        "geometry_index_frame_id_block": geometry_index.get("frame_id"),
        "defect_1_tokens": {},
        "defect_2_view_pos": {},
        "defect_3_frame_id": {},
    }
    truth = store_truth(Path(store_dir)) if store_dir else {}

    # ---- D1 tokens ---------------------------------------------------------------------
    for fragment_id, entry in sorted(token_index["rows"].items()):
        npz_path = package / "deploy" / entry["shard"]
        with np.load(npz_path, allow_pickle=False) as data:
            tokens = np.asarray(data[f"{entry['opaque']}__tokens"])
            token_input = np.asarray(data[f"{entry['opaque']}__token_input"])
            token_view = np.asarray(data[f"{entry['opaque']}__token_view"])
        metrics = token_metrics(tokens)
        metrics["tokens_per_view"] = int(TOKEN_BLOCK * TOKEN_BLOCK * 3)
        metrics["views"] = int(np.unique(token_view).size) if token_view.size else 0
        metrics["token_input_equals_column0"] = bool(
            tokens.shape[1] and np.allclose(tokens[:, 0], token_input))
        report["defect_1_tokens"][fragment_id] = metrics

    # ---- D2 view_pos -------------------------------------------------------------------
    for fragment_id, entry in sorted(obs_index["rows"].items()):
        metrics = observation_metrics(package / "deploy" / entry["shard"], entry["opaque"])
        metrics["view_pos_source"] = entry.get("view_pos_source")
        real = truth.get(fragment_id) or {}
        real_x = real.get("T_WC_x") or []
        exported = metrics.get("view_pos") or {}
        if real_x and exported:
            n = min(len(real_x), exported["shape"][0])
            with tarfile.open(package / "deploy" / entry["shard"], "r") as tar:
                values = np.load(io.BytesIO(
                    tar.extractfile(f"{entry['opaque']}/view_pos.npy").read()), allow_pickle=False)
            error = np.abs(np.asarray(values[:n], dtype=np.float64) - np.asarray(real_x[:n]))
            metrics["error_vs_real_T_WC_x_mm"] = {
                "max": float(np.nanmax(error)) if error.size else None,
                "mean": float(np.nanmean(error)) if error.size else None,
                "per_view": [float(v) for v in error],
            }
            metrics["real_T_WC_x_mm"] = [float(v) for v in real_x]
            metrics["real_camera_centers_mm"] = real.get("camera_centers")
            metrics["source_meta_u_position_mm"] = real.get("meta_u_position_mm")
        report["defect_2_view_pos"][fragment_id] = metrics

    # ---- D3 frame_id -------------------------------------------------------------------
    for fragment_id, entry in sorted(geometry_index["rows"].items()):
        views = int(obs_index["rows"].get(fragment_id, {}).get("views", 1) or 1)
        metrics = geometry_metrics(package / "deploy" / entry["shard"], entry["opaque"], views)
        metrics["index_frames"] = entry.get("frames")
        metrics["index_frame_id_source"] = entry.get("frame_id_source")
        metrics["index_frame_id_match_fraction"] = entry.get("frame_id_match_fraction")
        report["defect_3_frame_id"][fragment_id] = metrics

    out_path = Path(__file__).with_name(
        f"_measure_{package.parent.name}_{package.name}.json")
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str),
                        encoding="utf-8")

    def summarise(name: str, rows: dict) -> None:
        print(f"\n== {name} ({len(rows)} fragments)")
        for fragment_id, metrics in rows.items():
            print("  ", fragment_id, json.dumps(metrics, ensure_ascii=False, default=str)[:400])

    print("package:", package)
    print("package_id:", report["package_id"], "release_id:", report["release_id"])
    print("tokens/index.json declared:", json.dumps(report["token_index_declared"],
                                                    ensure_ascii=False)[:300])
    print("obs/index.json view_pos block:", json.dumps(report["obs_index_view_pos_block"],
                                                       ensure_ascii=False)[:400])
    print("geometry/index.json frame_id block:",
          json.dumps(report["geometry_index_frame_id_block"], ensure_ascii=False)[:400])
    summarise("D1 tokens", report["defect_1_tokens"])
    summarise("D2 view_pos", report["defect_2_view_pos"])
    summarise("D3 frame_id", report["defect_3_frame_id"])
    print("\nwrote", out_path)
    return 0


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "data/a12_exports/closed_loop/training_package"
    store = sys.argv[2] if len(sys.argv) > 2 else None
    raise SystemExit(main(target, store))
