"""Render a captured native wall-interval pytest report as a small PNG review figure."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch, Rectangle


def _draw_section(ax: plt.Axes, outer: list[float], inner: list[float], color: str,
                  title: str, station_x: float, wall_direction: str) -> None:
    outer_x, outer_y = outer[0] / 2.0, outer[1] / 2.0
    inner_x, inner_y = inner[0] / 2.0, inner[1] / 2.0
    ax.add_patch(Rectangle((-outer_x, -outer_y), 2 * outer_x, 2 * outer_y,
                           facecolor=color, edgecolor="#203040", linewidth=1.6, alpha=0.72))
    ax.add_patch(Rectangle((-inner_x, -inner_y), 2 * inner_x, 2 * inner_y,
                           facecolor="white", edgecolor="#203040", linewidth=1.5))
    ax.plot([inner_x, outer_x], [0.0, 0.0], color="#a33a2b", linewidth=5.0,
            solid_capstyle="butt", zorder=5)
    ax.scatter([station_x], [0.0], color="#b42117", s=42, zorder=6)
    ax.annotate("", xy=(inner_x - 0.12, 0.0), xytext=(station_x + 0.72, 0.0),
                arrowprops={"arrowstyle": "-|>", "lw": 1.6, "color": "#b42117"}, zorder=6)
    ax.text(station_x - 0.2, 0.45, "fixed station", ha="right", va="bottom", fontsize=8,
            color="#7a1a14")
    ax.text((inner_x + outer_x) / 2.0, -0.42, f"{outer_x - inner_x:.1f} mm",
            ha="center", va="top", fontsize=8, color="#7a1a14", weight="bold")
    ax.set_title(title, fontsize=10, weight="bold", pad=7)
    ax.set_xlabel("x (mm)", fontsize=8)
    ax.set_ylabel("y (mm)", fontsize=8)
    ax.set_xlim(-5.9, 5.9)
    ax.set_ylim(-5.9, 5.9)
    ax.set_aspect("equal", adjustable="box")
    ax.grid(True, linewidth=0.35, alpha=0.35)
    ax.tick_params(labelsize=7)


def render(report_path: Path, output_path: Path) -> None:
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    report = payload["native_report"]
    row = report["station_results"][0]
    if row["source_interval_mm"] is None or row["result_interval_mm"] is None:
        raise ValueError("captured native report has no paired interval to render")

    source_outer = payload["source_mesh"]["outer_extents_mm"]
    source_inner = payload["source_mesh"]["inner_cavity_extents_mm"]
    result_outer = payload["result_mesh"]["outer_extents_mm"]
    result_inner = payload["result_mesh"]["inner_cavity_extents_mm"]
    station = payload["stations_mm"][0]
    direction = payload["outward_wall_directions"][0]
    source_interval = [float(v) for v in row["source_interval_mm"]]
    result_interval = [float(v) for v in row["result_interval_mm"]]
    origin_x = float(station[0]) + float(report["probe_offset_mm"]) * float(direction[0])

    source_inner_half_x = float(source_inner[0]) / 2.0
    result_inner_half_x = float(result_inner[0]) / 2.0
    source_outer_half_x = float(source_outer[0]) / 2.0
    result_outer_half_x = float(result_outer[0]) / 2.0
    source_far_cavity_t = origin_x + source_inner_half_x
    result_far_cavity_t = origin_x + result_inner_half_x
    source_far_outer_t = origin_x + source_outer_half_x
    result_far_outer_t = origin_x + result_outer_half_x

    fig = plt.figure(figsize=(15.4, 8.2), constrained_layout=True)
    grid = fig.add_gridspec(2, 3, height_ratios=[1.0, 0.9], width_ratios=[1.0, 1.0, 1.25])
    ax_source = fig.add_subplot(grid[0, 0])
    ax_result = fig.add_subplot(grid[0, 1])
    ax_intervals = fig.add_subplot(grid[:, 2])
    ax_notes = fig.add_subplot(grid[1, :2])

    _draw_section(ax_source, source_outer, source_inner, "#4b9ba5",
                  "Source mesh section at z = 0", float(station[0]), "inward")
    _draw_section(ax_result, result_outer, result_inner, "#e3a14f",
                  "Eroded result section at z = 0", float(station[0]), "inward")
    ax_source.legend(handles=[Patch(facecolor="#4b9ba5", alpha=0.72, label="source material"),
                              Patch(facecolor="white", edgecolor="#203040", label="air cavity")],
                     loc="lower left", fontsize=7, framealpha=0.95)
    ax_result.legend(handles=[Patch(facecolor="#e3a14f", alpha=0.72, label="result material"),
                              Patch(facecolor="white", edgecolor="#203040", label="air cavity")],
                     loc="lower left", fontsize=7, framealpha=0.95)

    ax_intervals.set_title("Native material intervals along inward ray", fontsize=11, weight="bold")
    ax_intervals.set_xlim(0.0, 10.5)
    ax_intervals.set_ylim(-0.7, 4.35)
    ax_intervals.set_xlabel("distance from outward-offset probe origin, t (mm)", fontsize=9)
    ax_intervals.set_yticks([3.5, 2.55, 1.05])
    ax_intervals.set_yticklabels(["source selected", "result selected", "other wall*"], fontsize=9)
    ax_intervals.grid(axis="x", linewidth=0.55, alpha=0.45)
    ax_intervals.tick_params(axis="x", labelsize=8)

    src_lo, src_hi = source_interval
    res_lo, res_hi = result_interval
    ax_intervals.barh(3.5, src_hi - src_lo, left=src_lo, height=0.48,
                      color="#267b88", edgecolor="#16434a", label="native source interval")
    ax_intervals.barh(2.55, res_hi - res_lo, left=res_lo, height=0.48,
                      color="#da8527", edgecolor="#774511", label="native result interval")
    ax_intervals.text(src_hi + 0.12, 3.5, f"{src_hi - src_lo:.6f} mm native",
                      va="center", fontsize=8, color="#16434a")
    ax_intervals.text(res_hi + 0.12, 2.55, f"{res_hi - res_lo:.6f} mm native",
                      va="center", fontsize=8, color="#774511")

    ax_intervals.axvspan(src_hi, source_far_cavity_t, color="#c9cdd1", alpha=0.42, zorder=0)
    ax_intervals.text((src_hi + source_far_cavity_t) / 2.0, 1.8,
                      "air cavity\nnot summed", ha="center", va="center", fontsize=8,
                      color="#4e5358")
    ax_intervals.barh(1.05, source_far_outer_t - source_far_cavity_t,
                      left=source_far_cavity_t, height=0.28, color="#8eb9c0",
                      edgecolor="#267b88", alpha=0.72)
    ax_intervals.barh(0.65, result_far_outer_t - result_far_cavity_t,
                      left=result_far_cavity_t, height=0.28, color="#e7bb86",
                      edgecolor="#da8527", alpha=0.82)
    ax_intervals.text(9.7, 0.25, "*opposite wall shown from analytic fixture geometry only; not returned or added",
                      ha="center", va="center", fontsize=7, color="#4e5358", wrap=True)
    ax_intervals.axvline(src_lo, color="#267b88", linestyle="--", linewidth=0.8, alpha=0.7)
    ax_intervals.axvline(src_hi, color="#267b88", linestyle="--", linewidth=0.8, alpha=0.7)
    ax_intervals.axvline(res_hi, color="#da8527", linestyle=":", linewidth=1.0, alpha=0.9)
    ax_intervals.legend(loc="upper right", fontsize=7, framealpha=0.95)

    ax_notes.axis("off")
    expected = payload["analytic_oracle"]
    actual_source = float(row["source_length_mm"])
    actual_result = float(row["remaining_length_mm"])
    ax_notes.text(0.01, 0.88, "NATIVE MEASURED FROM CAPTURED PYTEST REPORT",
                  transform=ax_notes.transAxes, fontsize=10, weight="bold", color="#193a42")
    ax_notes.text(0.01, 0.68,
                  f"source [{src_lo:.9f}, {src_hi:.9f}] mm  ->  {actual_source:.9f} mm",
                  transform=ax_notes.transAxes, fontsize=9, family="monospace")
    ax_notes.text(0.01, 0.50,
                  f"result [{res_lo:.9f}, {res_hi:.9f}] mm  ->  {actual_result:.9f} mm",
                  transform=ax_notes.transAxes, fontsize=9, family="monospace")
    ax_notes.text(0.01, 0.30,
                  f"ANALYTIC ORACLE OVERLAY: source {expected['source_wall_mm']:.3f} mm; "
                  f"result {expected['remaining_wall_mm']:.3f} mm",
                  transform=ax_notes.transAxes, fontsize=9, color="#7c4f14")
    ax_notes.text(0.01, 0.08,
                  "One fixed station. Sampled chord only; 1/1 coverage is not global coverage.",
                  transform=ax_notes.transAxes, fontsize=8, color="#40484d")

    fig.suptitle(
        f"Wall interval fixture — sampled={report['sampled_interval_status']} | "
        f"global={report['global_wall_status']} | physical={report['physical_qualification_status']} | mm",
        fontsize=13, weight="bold")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=180, facecolor="white")
    plt.close(fig)

    summary = {
        "figure": str(output_path.resolve()),
        "input_report": str(report_path.resolve()),
        "fixture_id": payload["fixture_id"],
        "native_status": report["sampled_interval_status"],
        "global_wall_status": report["global_wall_status"],
        "physical_qualification_status": report["physical_qualification_status"],
        "native_source_interval_mm": source_interval,
        "native_result_interval_mm": result_interval,
        "native_source_length_mm": actual_source,
        "native_result_length_mm": actual_result,
        "analytic_oracle_mm": expected,
        "opposite_wall_and_cavity": "analytic context only; not measured or summed",
    }
    output_path.with_suffix(".figure_receipt.json").write_text(
        json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")
    print(f"python_version={sys.version.split()[0]}")
    print(f"argv={sys.argv}")
    print(f"matplotlib_version={matplotlib.__version__}")
    print(f"input_report={report_path.resolve()}")
    print(f"output_png={output_path.resolve()}")
    print(f"native_intervals_mm=source:{source_interval};result:{result_interval}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: render_actual_report.py <captured-report.json> <output.png>")
    render(Path(sys.argv[1]), Path(sys.argv[2]))
