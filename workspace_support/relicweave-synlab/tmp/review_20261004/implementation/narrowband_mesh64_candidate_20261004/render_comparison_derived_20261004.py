from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection

OUT = Path(__file__).resolve().parent
RESULTS = {
    (axis, path): OUT / f"result_{axis}_{path}.json"
    for axis in ("P02", "P03") for path in ("mesh32", "mesh64")
}
OUTPUT = OUT / "mesh32_mesh64_topology_projections.png"


def unique_edges(faces: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    faces = np.asarray(faces, dtype=np.int64)
    if not len(faces):
        return np.empty((0, 2), dtype=np.int64), np.empty((0, 2), dtype=np.int64)
    pairs = np.concatenate((faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]))
    ordered = np.sort(pairs, axis=1)
    unique, inverse, counts = np.unique(ordered, axis=0, return_inverse=True,
                                        return_counts=True)
    return unique, unique[counts == 1]


def project(vertices: np.ndarray, pairs: np.ndarray, axes: tuple[int, int]) -> np.ndarray:
    if not len(pairs):
        return np.empty((0, 2, 2), dtype=np.float64)
    return np.asarray(vertices, dtype=np.float64)[pairs][:, :, axes]


def panel(ax, vertices, faces, stage, title, xy_axes):
    edges, boundary = unique_edges(faces)
    lines = project(vertices, edges, xy_axes)
    if len(lines):
        ax.add_collection(LineCollection(lines, colors="#aab3bf", linewidths=0.28,
                                         alpha=0.28, zorder=1))
    boundary_lines = project(vertices, boundary, xy_axes)
    if len(boundary_lines):
        ax.add_collection(LineCollection(boundary_lines, colors="#d62728", linewidths=1.6,
                                         alpha=0.95, zorder=4))
        endpoints = boundary_lines.reshape(-1, 2)
        ax.scatter(endpoints[:, 0], endpoints[:, 1], s=6, c="#d62728", zorder=5)
    if len(vertices):
        pts = np.asarray(vertices, dtype=np.float64)[:, list(xy_axes)]
        lo = np.min(pts, axis=0)
        hi = np.max(pts, axis=0)
        pad = np.maximum((hi - lo) * 0.035, 0.05)
        ax.set_xlim(lo[0] - pad[0], hi[0] + pad[0])
        ax.set_ylim(lo[1] - pad[1], hi[1] + pad[1])
    ax.set_aspect("equal", adjustable="box")
    x_label = ("X", "Y", "Z")[xy_axes[0]]
    y_label = ("X", "Y", "Z")[xy_axes[1]]
    ax.set_xlabel(f"{x_label} (mm)")
    ax.set_ylabel(f"{y_label} (mm)")
    metric = stage or {}
    ax.set_title(
        f"{title}\nboundary={metric.get('boundary_edges', '?')}, "
        f"degenerate={metric.get('degenerate_faces_height_1e-12', '?')}, "
        f"signed V={metric.get('signed_volume_mm3', '?')} mm³",
        fontsize=8)
    ax.grid(True, linewidth=0.3, alpha=0.35)


def main() -> None:
    loaded = {}
    for key, path in RESULTS.items():
        if path.is_file():
            loaded[key] = json.loads(path.read_text(encoding="utf-8"))
        else:
            loaded[key] = None
    fig, axs = plt.subplots(4, 4, figsize=(18, 15), constrained_layout=True)
    cols = [
        ("raw_vertices", "raw_faces", "native output", (0, 1)),
        ("clean_vertices", "clean_faces", "clean_mesh output", (0, 1)),
        ("raw_vertices", "raw_faces", "native output", (0, 2)),
        ("clean_vertices", "clean_faces", "clean_mesh output", (0, 2)),
    ]
    row_index = 0
    for axis in ("P02", "P03"):
        for path in ("mesh32", "mesh64"):
            record = loaded[(axis, path)]
            for column, (v_key, f_key, stage_name, projection) in enumerate(cols):
                ax = axs[row_index, column]
                if not record or record.get("status") != "completed":
                    ax.text(0.5, 0.5, "candidate result missing or failed\n"
                                      "see result JSON / receipt", ha="center", va="center",
                            transform=ax.transAxes, fontsize=10)
                    ax.set_axis_off()
                    continue
                output_path = Path(record["output_npz"])
                with np.load(output_path, allow_pickle=False) as arrays:
                    vertices = arrays[v_key]
                    faces = arrays[f_key]
                stage_label = ("native_boolean_output" if stage_name == "native output"
                               else "clean_mesh.actual_function_output")
                stage = next((x for x in record.get("stages", [])
                              if x.get("stage") == stage_label), None)
                panel(ax, vertices, faces, stage,
                      f"{axis} / {path} / {stage_name} / "
                      f"{'XY' if projection == (0, 1) else 'XZ'}", projection)
            row_index += 1
    fig.suptitle(
        "P02/P03 frozen rough-probe Boolean topology comparison (mm)\n"
        "Gray = actual projected mesh edges; red = open boundary edges after each stage. "
        "This is a geometry diagnostic, not physical crack evidence.", fontsize=14)
    fig.savefig(OUTPUT, dpi=180)
    plt.close(fig)
    print(json.dumps({"output": str(OUTPUT), "bytes": OUTPUT.stat().st_size}, ensure_ascii=False))


if __name__ == "__main__":
    main()
