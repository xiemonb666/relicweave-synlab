"""Render plain orthographic side projections from run_examples.py mesh arrays.

Run with the VesselForge runtime because it provides matplotlib:
    third_party/vesselforge-runtime/venv/Scripts/python.exe \
      relicweave-synlab/experiments/continuation_20261015/design_space/render_previews.py
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import PolyCollection


HERE = Path(__file__).resolve().parent
MESH_DIR = HERE / "outputs" / "mesh_arrays"
PREVIEW_DIR = HERE / "outputs" / "previews"
CASES = {
    "V01": ("default", "deeper_profile", "rim_flare"),
    "V04": ("default", "thicker_handle", "without_handle"),
    "V06": ("default", "higher_shoulder", "wider_mouth"),
    "V09": ("default", "longer_spout", "steeper_spout"),
}


def main() -> None:
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    for vessel_id, case_names in CASES.items():
        fig, axes = plt.subplots(1, len(case_names), figsize=(10.5, 4.0),
                                 constrained_layout=True)
        for ax, case_name in zip(axes, case_names):
            with np.load(MESH_DIR / f"{vessel_id}_{case_name}.npz") as data:
                vertices = np.asarray(data["vertices"], dtype=np.float64)
                faces = np.asarray(data["faces"], dtype=np.int64)
            triangles = vertices[faces]
            normals = np.cross(triangles[:, 1] - triangles[:, 0],
                               triangles[:, 2] - triangles[:, 0])
            norm = np.linalg.norm(normals, axis=1)
            normals = normals / np.maximum(norm[:, None], 1e-12)
            # Looking from negative Y: retain the near surface and near-silhouette faces.
            keep = normals[:, 1] <= 0.08
            projected = triangles[keep][:, :, (0, 2)]
            depth = triangles[keep, :, 1].mean(axis=1)
            order = np.argsort(depth)[::-1]  # draw far projected faces before near faces
            collection = PolyCollection(
                projected[order],
                facecolors="#dedbd2",
                edgecolors="#5f5c56",
                linewidths=0.08,
                antialiased=True,
            )
            ax.add_collection(collection)
            ax.set_xlim(float(vertices[:, 0].min()) - 8,
                        float(vertices[:, 0].max()) + 8)
            ax.set_ylim(float(vertices[:, 2].min()) - 8,
                        float(vertices[:, 2].max()) + 8)
            ax.set_aspect("equal", adjustable="box")
            ax.set_title(case_name.replace("_", "\n"), fontsize=9)
            ax.set_xlabel("X (mm)")
            if ax is axes[0]:
                ax.set_ylabel("Z (mm)")
            ax.grid(color="#c7c4bd", linewidth=0.35, alpha=0.65)
        fig.suptitle(f"{vessel_id}: synthetic-control side projections", fontsize=11)
        fig.savefig(PREVIEW_DIR / f"{vessel_id}_side.png", dpi=150)
        plt.close(fig)
    print(f"wrote 4 side previews to {PREVIEW_DIR}")


if __name__ == "__main__":
    main()
