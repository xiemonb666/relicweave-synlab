"""Render the frozen fixture NPZ with the Vesselforge runtime Matplotlib."""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
import numpy as np
from mpl_toolkits.mplot3d.art3d import Line3DCollection


ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
NPZ = OUT / "g01_conditioned_total_rms_fixture.npz"


def main() -> None:
    with np.load(NPZ, allow_pickle=False) as archive:
        points = archive["points_before_mm"].copy()
        suffixes = ("005", "050")
        after = {suffix: archive[f"points_after_{suffix}_mm"].copy() for suffix in suffixes}
        signed = {
            suffix: archive[f"signed_normal_displacement_{suffix}_mm"].copy()
            for suffix in suffixes
        }

    xspan = float(np.ptp(points[:, 0]))
    yspan = float(np.ptp(points[:, 1]))
    all_abs = np.concatenate([np.abs(signed[key]) for key in suffixes])
    color_limit = float(np.max(all_abs))
    color_norm = Normalize(vmin=-color_limit, vmax=color_limit)

    fig = plt.figure(figsize=(14.5, 7.5), constrained_layout=True)
    axes = [fig.add_subplot(1, 2, i + 1, projection="3d") for i in range(2)]
    titles = {"005": "Target RMS 0.05 mm", "050": "Target RMS 0.5 mm"}
    for ax, suffix in zip(axes, suffixes):
        current = after[suffix]
        values = signed[suffix]
        ax.scatter(
            points[:, 0], points[:, 1], points[:, 2],
            s=5, c="#7a7a7a", alpha=0.30, depthshade=False,
            label="Input (400 points)",
        )
        segments = np.stack((points, current), axis=1)
        connectors = Line3DCollection(
            segments, cmap="coolwarm", norm=color_norm, linewidths=0.55, alpha=0.78
        )
        connectors.set_array(values)
        ax.add_collection3d(connectors)
        dots = ax.scatter(
            current[:, 0], current[:, 1], current[:, 2],
            s=8, c=values, cmap="coolwarm", norm=color_norm,
            alpha=0.98, depthshade=False, label="Output (all 400 points)",
        )
        ax.set_title(titles[suffix])
        ax.set_xlabel("x (mm)")
        ax.set_ylabel("y (mm)")
        ax.set_xlim(float(points[:, 0].min()), float(points[:, 0].max()))
        ax.set_ylim(float(points[:, 1].min()), float(points[:, 1].max()))
        zlimit = float(np.max(np.abs(current[:, 2])))
        zlimit = max(zlimit * 1.12, 1e-6)
        zspan = 2.0 * zlimit
        ax.set_zlim(-zlimit, zlimit)
        # At 0.05 mm the equal-scale z axis is physically very short relative to
        # the 19 mm x/y span. Keep one zero tick and state the exact +/- limits
        # in the panel annotation instead of overlapping endpoint tick labels.
        ax.set_zticks((0.0,))
        ax.set_zticklabels(("0",))
        ax.tick_params(axis="z", labelsize=8, pad=1)
        ax.zaxis.set_rotate_label(False)
        ax.set_zlabel("z (mm)", rotation=90, labelpad=12)
        # Box dimensions are proportional to data ranges, so equal world distances
        # use equal displayed axis lengths; vertical motion is not magnified.
        ax.set_box_aspect((xspan, yspan, zspan))
        ax.view_init(elev=24, azim=135)
        ax.text2D(
            0.02, 0.04, f"z limits: ±{zlimit:.4g} mm",
            transform=ax.transAxes, fontsize=8,
            bbox={"facecolor": "white", "alpha": 0.72, "edgecolor": "none"},
        )
        ax.legend(loc="upper left", fontsize=8, markerscale=0.8)
    fig.suptitle(
        "G01 conditioned_total_rms: input plane and delivered point coordinates\n"
        "Equal world-unit axes; all points shown; geometry is not magnified",
        fontsize=13,
    )
    fig.colorbar(dots, ax=axes, shrink=0.72, pad=0.08,
                 label="Signed normal displacement (mm)")
    fig.savefig(OUT / "g01_conditioned_total_rms_3d.png", dpi=170)
    plt.close(fig)

    fig, axes = plt.subplots(2, 2, figsize=(13, 8.5), constrained_layout=True)
    targets = {"005": 0.05, "050": 0.5}
    for col, suffix in enumerate(suffixes):
        values = signed[suffix]
        axes[0, col].scatter(
            points[:, 0], values, s=15, alpha=0.78, color="#315f91",
            edgecolors="none",
        )
        axes[0, col].axhline(0.0, color="#333333", linewidth=0.8)
        axes[0, col].set_title(f"{titles[suffix]} — signed point error")
        axes[0, col].set_xlabel("Input x (mm)")
        axes[0, col].set_ylabel("Signed normal displacement (mm)")
        axes[0, col].grid(alpha=0.2)

        # Each panel spans its own full observed range so the 0.05 mm fixture's
        # distribution is legible; no point is clipped from the histogram.
        hist_limit = float(np.max(np.abs(values))) * 1.04
        bins = np.linspace(-hist_limit, hist_limit, 51)
        axes[1, col].hist(values, bins=bins, color="#b56b36", alpha=0.88,
                          edgecolor="white", linewidth=0.35)
        axes[1, col].axvline(0.0, color="#333333", linewidth=0.8)
        axes[1, col].set_title(
            f"All 400 signed errors; target {targets[suffix]:g} mm"
        )
        axes[1, col].set_xlabel("Signed normal displacement (mm; full panel range)")
        axes[1, col].set_ylabel("Point count")
        axes[1, col].grid(axis="y", alpha=0.2)
    fig.suptitle(
        "G01 delivered errors — every fixture point is plotted and counted; no interpolation",
        fontsize=13,
    )
    fig.savefig(OUT / "g01_conditioned_total_rms_displacements.png", dpi=170)
    plt.close(fig)

    print(f"npz_read_only={NPZ}")
    print(f"png_3d={OUT / 'g01_conditioned_total_rms_3d.png'}")
    print(f"png_displacements={OUT / 'g01_conditioned_total_rms_displacements.png'}")
    print(f"point_count={len(points)}")
    print(f"levels={','.join(suffixes)}")
    print(f"matplotlib={matplotlib.__version__}")


if __name__ == "__main__":
    main()
