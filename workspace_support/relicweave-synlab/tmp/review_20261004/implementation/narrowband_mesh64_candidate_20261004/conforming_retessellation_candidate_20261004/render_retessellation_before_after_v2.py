from __future__ import annotations
import hashlib, json
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon
import numpy as np

HERE = Path(__file__).resolve().parent
INPUTS = HERE / "frozen_retessellation_inputs.npz"
OUTPUTS = HERE / "retessellated_candidate_outputs.npz"
REPORT = HERE / "retessellated_candidate_report.json"
PNG = HERE / "retessellation_before_after_local_topology_v2.png"

def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()

def add_triangle(ax, vertices, ids, color, edge, alpha=0.32, linewidth=1.7, zorder=2):
    pts = np.asarray(vertices)[np.asarray(ids, dtype=np.int64)][:, [0, 2]]
    ax.add_patch(Polygon(pts, closed=True, facecolor=color, edgecolor=edge,
                         alpha=alpha, linewidth=linewidth, zorder=zorder))
    return pts

def add_triangle_xy(ax, vertices, ids, color, edge, alpha=0.32, linewidth=1.7, zorder=2):
    pts = np.asarray(vertices)[np.asarray(ids, dtype=np.int64)][:, [0, 1]]
    ax.add_patch(Polygon(pts, closed=True, facecolor=color, edgecolor=edge,
                         alpha=alpha, linewidth=linewidth, zorder=zorder))
    return pts
def setup_xz(ax, title):
    ax.set_title(title, fontsize=9, loc="left")
    ax.set_xlabel("X (mm)", fontsize=8)
    ax.set_ylabel("Z (mm)", fontsize=8)
    ax.set_xlim(-10.72, -8.83)
    ax.set_ylim(-1.72, -1.07)
    ax.set_aspect("equal", adjustable="box")
    ax.grid(True, color="#d9dee3", linewidth=0.55)
    ax.tick_params(labelsize=7)

def render():
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    raw = np.load(INPUTS, allow_pickle=False)
    candidate = np.load(OUTPUTS, allow_pickle=False)
    fig, axes = plt.subplots(5, 2, figsize=(14.5, 15.7), constrained_layout=True)
    fig.suptitle(
        "Saved-array conforming retessellation candidate — local topology only\n"
        "X–Z projection at Y = 9 mm for four cases; final row is positive-area-hole negative control. "
        "Not physical fracture evidence; material ancestry UNKNOWN.",
        fontsize=12, fontweight="bold")

    for row, item in enumerate(report["results"][:4]):
        case = item["case_id"]
        loop = item["loops"][0]
        V = raw[f"{case}_raw_vertices_f64"]
        F = raw[f"{case}_raw_faces_i64"]
        CV = candidate[f"{case}_candidate_vertices_f64"]
        CF = candidate[f"{case}_candidate_faces_i64"]
        deg_id = int(loop["degenerate_face_id"])
        long_id = int(loop["split_target_face_id"])
        short_ids = [int(loop["span_neighbors"][name]["face_id"])
                     for name in ("short_a_mid", "short_mid_b")]
        middle = int(loop["middle_vertex_id"])
        xloc = float(V[middle, 0])
        zloc = float(V[middle, 2])
        parent_lineage = next(x for x in item["face_lineage"]
                              if x["kind"] == "split_long_edge_face" and int(x["parent_face_id"]) == long_id)
        children = parent_lineage["children"]

        ax = axes[row, 0]
        for face_id in short_ids:
            add_triangle(ax, V, F[face_id], "#bdc3c7", "#59636e", alpha=0.24, linewidth=1.25)
        add_triangle(ax, V, F[long_id], "#5dade2", "#1f618d", alpha=0.36, linewidth=2.0)
        deg = F[deg_id]
        pts = V[deg][:, [0, 2]]
        pts_closed = np.vstack([pts, pts[0]])
        ax.plot(pts_closed[:, 0], pts_closed[:, 1], color="#c0392b", linewidth=3.0,
                linestyle="--", marker="o", markersize=4.0, zorder=6)
        ax.scatter([xloc], [zloc], color="#f39c12", edgecolor="black", s=36, zorder=8)
        setup_xz(ax, f"{case}: raw saved Boolean arrays — local example 1/7")
        ax.text(0.02, 0.03, f"zero-area row {deg_id} overlays long edge\nmidpoint at X={xloc:.2f}, Z={zloc:.2f} mm",
                transform=ax.transAxes, fontsize=7, va="bottom",
                bbox={"boxstyle":"round,pad=0.25", "facecolor":"white", "alpha":0.88, "edgecolor":"#cbd2d9"})

        ax = axes[row, 1]
        for face_id in short_ids:
            add_triangle(ax, CV, F[face_id], "#bdc3c7", "#59636e", alpha=0.24, linewidth=1.25)
        child_points = []
        for ch in children:
            pts = add_triangle(ax, CV, ch["vertex_ids"], "#48c9b0", "#117864", alpha=0.42, linewidth=2.0)
            child_points.append(pts)
        ax.scatter([xloc], [zloc], color="#f39c12", edgecolor="black", s=42, zorder=8)
        setup_xz(ax, f"{case}: saved candidate — 7 exact loops retessellated")
        ax.text(0.02, 0.03,
                f"parent row {long_id} → 2 children; zero-area row {deg_id} removed\n"
                f"same existing midpoint; vertex bytes unchanged",
                transform=ax.transAxes, fontsize=7, va="bottom",
                bbox={"boxstyle":"round,pad=0.25", "facecolor":"white", "alpha":0.88, "edgecolor":"#cbd2d9"})

    neg = report["results"][4]
    full_case = "P02_mesh64"
    Vfull = raw[f"{full_case}_raw_vertices_f64"]
    Ffull = raw[f"{full_case}_raw_faces_i64"]
    Vneg = raw["P02_mesh64_hole_negative_vertices_f64"]
    Fneg = raw["P02_mesh64_hole_negative_faces_i64"]
    hole_face_id = int(neg["negative_control_removed_face_id"])
    hole_face = Ffull[hole_face_id]
    hole_set = set(int(x) for x in hole_face)
    neighbors = [(i, tri) for i, tri in enumerate(Ffull)
                 if i != hole_face_id and len(hole_set.intersection(int(x) for x in tri)) >= 2]
    boundary = neg["input_metrics"]["boundary_edge_ids"]
    area = float(neg["negative_control_removed_face_area_mm2"])

    ax = axes[4, 0]
    for _, tri in neighbors:
        add_triangle_xy(ax, Vfull, tri, "#bdc3c7", "#59636e", alpha=0.26, linewidth=1.2)
    hpts = add_triangle_xy(ax, Vfull, hole_face, "#58d68d", "#196f3d", alpha=0.48, linewidth=2.2, zorder=5)
    ax.text(float(hpts[:, 0].mean()), float(hpts[:, 1].mean()), f"row {hole_face_id}\n{area:.6f} mm²",
            fontsize=7, ha="center", va="center", zorder=9)
    ax.set_title("Negative control reference: complete saved P02 Mesh64 input", fontsize=9, loc="left")
    ax.set_xlabel("X (mm)", fontsize=8); ax.set_ylabel("Y (mm)", fontsize=8)
    ax.set_aspect("equal", adjustable="box"); ax.grid(True, color="#d9dee3", linewidth=0.55); ax.tick_params(labelsize=7)
    ax.set_xlim(8.0, 11.6); ax.set_ylim(7.5, 9.6)
    ax.text(0.02, 0.03, "reference face is positive-area; plane Z = -1.6 mm",
            transform=ax.transAxes, fontsize=7, va="bottom",
            bbox={"boxstyle":"round,pad=0.25", "facecolor":"white", "alpha":0.88, "edgecolor":"#cbd2d9"})

    ax = axes[4, 1]
    for _, tri in neighbors:
        add_triangle_xy(ax, Vneg, tri, "#bdc3c7", "#59636e", alpha=0.26, linewidth=1.2)
    for edge in boundary:
        ids = np.asarray(edge, dtype=np.int64)
        pts = Vneg[ids][:, [0, 1]]
        ax.plot(pts[:, 0], pts[:, 1], color="#c0392b", linewidth=3.0, zorder=7)
    hxy = Vneg[hole_face][:, [0, 1]]
    hclosed = np.vstack([hxy, hxy[0]])
    ax.plot(hclosed[:, 0], hclosed[:, 1], color="#8e44ad", linewidth=2.2,
            linestyle="--", marker="o", markersize=3.5, zorder=8)
    ax.set_title("Negative control input: 3-edge positive-area opening; rejected unchanged", fontsize=9, loc="left")
    ax.set_xlabel("X (mm)", fontsize=8); ax.set_ylabel("Y (mm)", fontsize=8)
    ax.set_aspect("equal", adjustable="box"); ax.grid(True, color="#d9dee3", linewidth=0.55); ax.tick_params(labelsize=7)
    ax.set_xlim(8.0, 11.6); ax.set_ylim(7.5, 9.6)
    ax.text(0.02, 0.03,
            f"omitted row {hole_face_id}: {area:.6f} mm²\n"
            "red = existing boundary; dashed purple = omitted face outline\n"
            "candidate status: rejected_without_modification",
            transform=ax.transAxes, fontsize=7, va="bottom",
            bbox={"boxstyle":"round,pad=0.25", "facecolor":"white", "alpha":0.9, "edgecolor":"#cbd2d9"})

    fig.savefig(PNG, dpi=170, facecolor="white")
    plt.close(fig)
    print(json.dumps({"png": str(PNG), "png_sha256": sha(PNG), "bytes": PNG.stat().st_size,
                      "report_sha256": sha(REPORT), "raw_inputs_sha256": sha(INPUTS),
                      "candidate_outputs_sha256": sha(OUTPUTS), "cases_rendered": 4,
                      "negative_control_rendered": neg["status"], "conversion_rerun": False}, indent=2))

if __name__ == "__main__":
    render()

