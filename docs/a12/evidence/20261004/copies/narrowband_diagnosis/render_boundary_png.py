from pathlib import Path
import json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
import numpy as np

out = Path(__file__).resolve().parent
report = json.loads((out / "diagnosis.json").read_text(encoding="utf-8"))
cases = {case["axis_id"]: case for case in report["p02_p03_cases"]}

fig, axes = plt.subplots(2, 2, figsize=(13, 9), constrained_layout=True)
for row, axis_id in enumerate(("P02", "P03")):
    case = cases[axis_id]
    b = case["final_component"]["bounds_mm"]
    x0, y0, z0 = b[0]
    x1, y1, z1 = b[1]
    edges = case["final_boundary"]["edges"]
    for col, (u, v, title, lims) in enumerate((
        (0, 1, "XY projection", ((x0 - 0.4, x1 + 0.4), (y0 - 0.4, y1 + 0.4))),
        (0, 2, "XZ projection", ((x0 - 0.4, x1 + 0.4), (z0 - 0.25, z1 + 0.25))),
    )):
        ax = axes[row, col]
        if col == 0:
            # This is explicitly only the actual mesh's projected bounding box; edges below are
            # the actual coordinates from final component topology, not synthetic section geometry.
            ax.plot([x0, x1, x1, x0, x0], [y0, y0, y1, y1, y0],
                    color="#9aa3ad", linewidth=1.5, linestyle="--",
                    label="actual mesh bounding box")
        else:
            ax.plot([x0, x1, x1, x0, x0], [z0, z0, z1, z1, z0],
                    color="#9aa3ad", linewidth=1.5, linestyle="--",
                    label="actual mesh bounding box")
        segments = []
        centers = []
        for edge in edges:
            p0 = edge["p0_mm"]
            p1 = edge["p1_mm"]
            segments.append(([p0[u], p0[v]], [p1[u], p1[v]]))
            centers.append([(p0[u] + p1[u]) * 0.5, (p0[v] + p1[v]) * 0.5])
        if segments:
            ax.add_collection(LineCollection(
                segments, colors="#d7191c", linewidths=2.4,
                label=f"open boundary edges ({len(segments)})", zorder=4))
            endpoints = np.asarray([[p for p in seg] for edge in edges
                                    for seg in (edge["p0_mm"], edge["p1_mm"])], dtype=float)
            ax.scatter(endpoints[:, u], endpoints[:, v], s=10, c="#d7191c",
                       edgecolors="white", linewidths=0.35, zorder=5,
                       label="boundary endpoints")
        ax.set_xlim(*lims[0])
        ax.set_ylim(*lims[1])
        ax.set_aspect("equal", adjustable="box")
        ax.set_xlabel(("X" if u == 0 else "Y") + " (mm)")
        ax.set_ylabel(("Y" if v == 1 else "Z") + " (mm)")
        ax.set_title(f"{axis_id}: {title}")
        ax.grid(True, alpha=0.28)
        ax.text(
            0.02, 0.98,
            f"boundary edges = {len(edges)}; watertight = "
            f"{case['final_component']['watertight']}",
            transform=ax.transAxes, va="top", ha="left", fontsize=9,
            bbox={"facecolor": "white", "alpha": 0.9, "edgecolor": "#777"},
        )
        if row == 0 and col == 0:
            ax.legend(loc="lower left", fontsize=8)
fig.suptitle(
    "Actual P02/P03 output mesh boundary coordinates (probe fixture, mm)\n"
    "Red marks show open topology after cleanup; these are not physical cracks or cut surfaces",
    fontsize=13,
)
fig.savefig(out / "actual_mesh_boundary_projections.png", dpi=180)
print(json.dumps({
    "python_executable": __import__("sys").executable,
    "output_png": str(out / "actual_mesh_boundary_projections.png"),
    "edges": {axis: len(case["final_boundary"]["edges"]) for axis, case in cases.items()},
}, indent=2))
