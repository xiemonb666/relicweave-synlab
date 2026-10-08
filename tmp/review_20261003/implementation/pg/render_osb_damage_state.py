from __future__ import annotations

import csv
import hashlib
import json
import math
import tomllib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "jobs" / "osb_fracture_branch_001" / "output"
TARGET = ROOT / "visuals" / "osb_fracture_point_state.png"
CANVAS = (1800, 1230)
BG, INK, GRID = (249, 250, 252), (30, 39, 50), (191, 199, 209)
PALETTE = [(40, 99, 166), (199, 59, 47), (54, 142, 95), (143, 88, 160),
           (222, 144, 38), (37, 154, 170), (160, 95, 65), (96, 109, 121)]


def read_data():
    result = json.loads((OUTPUT / "result.json").read_text(encoding="utf-8"))
    with (OUTPUT / "points.csv").open(newline="", encoding="utf-8") as stream:
        points = list(csv.DictReader(stream))
    with (OUTPUT / "bond_states.csv").open(newline="", encoding="utf-8") as stream:
        bonds = list(csv.DictReader(stream))
    summary = tomllib.loads((OUTPUT / "summary.toml").read_text(encoding="utf-8"))
    return result, points, bonds, summary


def scalar_color(value: float, lo: float, hi: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, (value - lo) / (hi - lo))) if hi > lo else 0.0
    stops = [(40, 78, 152), (54, 154, 177), (112, 184, 130), (242, 198, 81), (195, 45, 43)]
    p = t * (len(stops) - 1)
    i = min(len(stops) - 2, int(p))
    q = p - i
    return tuple(round(stops[i][k] * (1 - q) + stops[i + 1][k] * q) for k in range(3))


def diverging_color(value: float, bound: float) -> tuple[int, int, int]:
    t = max(-1.0, min(1.0, value / bound)) if bound else 0.0
    if t < 0:
        a, b = (58, 112, 184), (248, 248, 248)
        q = t + 1.0
    else:
        a, b = (248, 248, 248), (196, 45, 49)
        q = t
    return tuple(round(a[i] * (1 - q) + b[i] * q) for i in range(3))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def conversion_checks() -> dict:
    negative = diverging_color(-1.0, 1.0)
    center = diverging_color(0.0, 1.0)
    positive = diverging_color(1.0, 1.0)
    conversions = [
        {"input": 1.0, "input_unit": "m", "multiplier": 1000.0, "output": 1000.0,
         "expected": 1000.0, "output_unit": "mm", "pass": 1.0 * 1000.0 == 1000.0},
        {"input": 1.0, "input_unit": "mm", "multiplier": 1000.0, "output": 1000.0,
         "expected": 1000.0, "output_unit": "um", "pass": 1.0 * 1000.0 == 1000.0},
        {"input": -1.0, "input_unit": "mm", "multiplier": 1000.0, "output": -1000.0,
         "expected": -1000.0, "output_unit": "um", "pass": -1.0 * 1000.0 == -1000.0},
    ]
    colors = {"negative": list(negative), "zero": list(center), "positive": list(positive),
              "negative_is_blue": negative[2] > negative[0], "positive_is_red": positive[0] > positive[2],
              "zero_is_neutral": center == (248, 248, 248)}
    if not all(item["pass"] for item in conversions) or not all(colors[k] for k in
            ("negative_is_blue", "positive_is_red", "zero_is_neutral")):
        raise AssertionError(f"visual unit/sign conversion check failed: {conversions}, {colors}")
    return {"status": "PASS", "conversions": conversions, "diverging_sign_color_check": colors}


def isometric(x: float, y: float, z: float, cx: float, cy: float, scale: float) -> tuple[float, float]:
    return cx + (x - y) * math.cos(math.pi / 6) * scale, cy + (x + y) * 0.5 * scale - z * scale


def add_panel(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], title: str, points,
              field: str, values: list[float], color_mode: str, font, small, extra: str = "") -> None:
    x0, y0, x1, y1 = box
    draw.rounded_rectangle(box, radius=14, fill=(255, 255, 255), outline=(215, 221, 229), width=2)
    draw.text((x0 + 18, y0 + 13), title, font=font, fill=INK)
    if extra:
        for line_index, line in enumerate(extra.splitlines()):
            draw.text((x0 + 18, y0 + 43 + line_index * 18), line, font=small, fill=(91, 101, 114))

    coords = []
    for p in points:
        coordinate_prefix = "ref" if field == "u_z_mm" else "current"
        xx = float(p[f"x_{coordinate_prefix}_m"]) * 1000
        yy = float(p[f"y_{coordinate_prefix}_m"]) * 1000
        zz = float(p[f"z_{coordinate_prefix}_m"]) * 1000
        coords.append((xx, yy, zz))
    xmin, xmax = min(c[0] for c in coords), max(c[0] for c in coords)
    ymin, ymax = min(c[1] for c in coords), max(c[1] for c in coords)
    zmin, zmax = min(c[2] for c in coords), max(c[2] for c in coords)
    # Isometric orthographic projection with the same px/mm scale on x, y and z.
    total_w_mm = (xmax - xmin + ymax - ymin) * math.cos(math.pi / 6) + 1.5
    total_h_mm = (zmax - zmin) + 0.5 * (xmax - xmin + ymax - ymin) + 1.5
    scale = min(500 / total_w_mm, 345 / total_h_mm)
    cx, cy = x0 + 380, y0 + 313

    # Context is only the axis-aligned bounds of solver points, not a reconstructed surface.
    corners = [(a, b, c) for a in (xmin, xmax) for b in (ymin, ymax) for c in (zmin, zmax)]
    edges = []
    for i, a in enumerate(corners):
        for j in range(i + 1, len(corners)):
            b = corners[j]
            if sum(a[k] != b[k] for k in range(3)) == 1:
                edges.append((a, b))
    for a, b in edges:
        pa = isometric(*a, cx, cy, scale)
        pb = isometric(*b, cx, cy, scale)
        draw.line((pa[0], pa[1], pb[0], pb[1]), fill=GRID, width=1)

    order = sorted(range(len(points)), key=lambda i: sum(coords[i]))
    if color_mode == "category":
        categories = sorted({int(float(v)) for v in values})
        cat_color = {cat: PALETTE[index % len(PALETTE)] for index, cat in enumerate(categories)}
        for i in order:
            px, py = isometric(*coords[i], cx, cy, scale)
            c = cat_color[int(float(values[i]))]
            draw.ellipse((px - 3.2, py - 3.2, px + 3.2, py + 3.2), fill=c, outline=(25, 30, 36), width=1)
        for idx, cat in enumerate(categories):
            cy0 = y0 + 112 + idx * 24
            draw.rectangle((x0 + 675, cy0, x0 + 691, cy0 + 14), fill=cat_color[cat])
            count_cat = sum(int(float(v)) == cat for v in values)
            draw.text((x0 + 701, cy0 - 2), f"component {cat}: {count_cat} points", font=small, fill=INK)
    else:
        actual_lo, actual_hi = min(values), max(values)
        if field == "u_z_mm":
            bound = max(abs(actual_lo), abs(actual_hi))
            if bound == 0:
                bound = 1e-15
            lo, hi = -bound, bound
            color_fn = lambda value: diverging_color(value, bound)
            legend = [f"+{bound:.6g}", "0", f"-{bound:.6g}"]
        elif field == "damage":
            lo, hi = 0.0, 1.0
            color_fn = lambda value: scalar_color(value, lo, hi)
            legend = ["1.0", "0.5", "0.0"]
        else:
            lo, hi = actual_lo, actual_hi
            if hi <= lo:
                hi = lo + 1.0
            color_fn = lambda value: scalar_color(value, lo, hi)
            legend = [f"max {actual_hi:g}", f"min {actual_lo:g}"]
        for i in order:
            px, py = isometric(*coords[i], cx, cy, scale)
            draw.ellipse((px - 3.2, py - 3.2, px + 3.2, py + 3.2),
                         fill=color_fn(values[i]), outline=(25, 30, 36), width=1)
        bar_x = x0 + 668
        for step in range(101):
            t = step / 100
            val = hi - (hi - lo) * t
            c = color_fn(val)
            yy = y0 + 119 + step * 2
            draw.line((bar_x, yy, bar_x + 20, yy), fill=c, width=3)
        draw.text((bar_x + 27, y0 + 114), legend[0], font=small, fill=INK)
        draw.text((bar_x + 27, y0 + 313), legend[-1], font=small, fill=INK)
        if len(legend) == 3:
            draw.text((bar_x + 27, y0 + 213), legend[1], font=small, fill=INK)
        if field == "u_z_mm":
            draw.text((bar_x, y0 + 337), "u_z (mm)", font=small, fill=INK)
        else:
            draw.text((bar_x, y0 + 337), field, font=small, fill=INK)

    # 2 mm axis triad, all axes use the same projection scale.
    ox, oy = x0 + 95, y1 - 63
    length = 2.0 * scale
    axes = [("x", (length, 0)), ("y", (-math.cos(math.pi/6)*length, 0.5*length)), ("z", (0, -length))]
    draw.ellipse((ox - 3, oy - 3, ox + 3, oy + 3), fill=INK)
    for label, (dx, dy) in axes:
        draw.line((ox, oy, ox + dx, oy + dy), fill=INK, width=3)
        draw.text((ox + dx + 5, oy + dy - 7), f"{label}+", font=small, fill=INK)
    draw.text((x0 + 18, y1 - 31), "isometric axes share mm scale; point glyph size is symbolic", font=small, fill=(88, 97, 108))


def main() -> None:
    result, points, bonds, summary = read_data()
    uz = [(float(p["z_current_m"]) - float(p["z_ref_m"])) * 1000 for p in points]
    damage = [float(p["damage"]) for p in points]
    component = [int(p["intact_bond_component_id"]) for p in points]
    degree = [int(p["n_active_bonds"]) for p in points]
    image = Image.new("RGB", CANVAS, BG)
    draw = ImageDraw.Draw(image)
    title_font, font, small = ImageFont.load_default(size=30), ImageFont.load_default(size=21), ImageFont.load_default(size=15)
    draw.text((28, 22), "OSB high-load native bond-state branch | pointwise solver fields", font=title_font, fill=INK)
    state, solver = result["state"], result["solver"]
    draw.text((30, 62),
              f"{result['job_id']} | {state['point_count']} points | {state['canonical_initial_bond_pairs']} initial bond pairs | {state['broken_bond_pairs_at_endpoint']} broken pairs | {state['intact_bond_graph_component_count']} endpoint components | {solver['steps']} steps",
              font=font, fill=(40, 78, 117))
    draw.text((30, 93),
              f"native dt bound/accepted: {solver['native_stability_bound_dt_s']:.6g} s | calibration: UNVALIDATED_PROTOTYPE | geometry surface reconstruction: absent",
              font=small, fill=(82, 91, 104))

    uz_min, uz_max = min(uz), max(uz)
    uz_bound = max(abs(uz_min), abs(uz_max)) or 1e-15
    damage_min, damage_max = min(damage), max(damage)
    degree_min, degree_max = min(degree), max(degree)
    panels = [
        ((20, 128, 880, 648), "Reference points; signed axial displacement u_z (mm)", "u_z_mm", uz, "scalar",
         f"formula: (z_current_m - z_ref_m)*1000 | source: z_current_m, z_ref_m\nactual min/max=[{uz_min:.9g}, {uz_max:.9g}] mm | symmetric color=[-{uz_bound:.9g}, +{uz_bound:.9g}] mm"),
        ((920, 128, 1780, 648), "Current points; upstream damage (fixed color domain [0,1])", "damage", damage, "scalar",
         f"source column: damage | fixed color domain [0,1]\nactual min/max=[{damage_min:.6g}, {damage_max:.6g}]"),
        ((20, 675, 880, 1195), "Current points; endpoint intact-bond component IDs", "component_id", component, "category",
         "CSV source: intact_bond_component_id | categorical IDs; these are graph components, not verified rigid fragments"),
        ((920, 675, 1780, 1195), "Current points; active native bond degree", "n_active_bonds", degree, "scalar",
         f"CSV source: n_active_bonds | actual range [{degree_min}, {degree_max}]"),
    ]
    for box, label, field, values, mode, extra in panels:
        add_panel(draw, box, label, points, field, values, mode, font, small, extra)

    check = result["validation"]["checks"]
    source_points = OUTPUT / "points.csv"
    source_result = OUTPUT / "result.json"
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    image.save(TARGET)
    source_hashes = {"points.csv": sha256_file(source_points), "result.json": sha256_file(source_result)}
    bond_summary = json.dumps({
        "schema": "pgfrag.point_state_visual_audit.v2",
        "result_path": str((OUTPUT / "result.json").resolve()),
        "result_sha256": source_hashes["result.json"],
        "image_path": str(TARGET.resolve()),
        "image_sha256": sha256_file(TARGET),
        "source_sha256": source_hashes,
        "panels": [
            {"variable": "axial displacement u_z", "formula": "(z_current_m - z_ref_m) * 1000", "source_columns": ["z_current_m", "z_ref_m"],
             "source_unit": "m", "output_unit": "mm", "multiplier": 1000.0,
             "actual_minmax": {"min": uz_min, "max": uz_max},
             "colorscale": {"type": "diverging", "min": -uz_bound, "center": 0.0, "max": uz_bound},
             "source_sha256": source_hashes["points.csv"]},
            {"variable": "damage", "formula": "damage", "source_columns": ["damage"], "source_unit": "1", "output_unit": "1", "multiplier": 1.0,
             "actual_minmax": {"min": damage_min, "max": damage_max}, "colorscale": {"type": "sequential", "min": 0.0, "max": 1.0},
             "source_sha256": source_hashes["points.csv"]},
            {"variable": "intact-bond graph component ID", "formula": "intact_bond_component_id", "source_columns": ["intact_bond_component_id"],
             "source_unit": "1", "output_unit": "categorical ID", "multiplier": 1.0,
             "actual_minmax": {"min": min(component), "max": max(component)}, "colorscale": {"type": "categorical", "categories": sorted(set(component))},
             "source_sha256": source_hashes["points.csv"]},
            {"variable": "active bond degree", "formula": "n_active_bonds", "source_columns": ["n_active_bonds"], "source_unit": "1", "output_unit": "count", "multiplier": 1.0,
             "actual_minmax": {"min": degree_min, "max": degree_max}, "colorscale": {"type": "sequential_actual_range", "min": degree_min, "max": degree_max},
             "source_sha256": source_hashes["points.csv"]},
        ],
        "known_vector_checks": conversion_checks(),
        "job_id": result["job_id"], "status": result["status"],
        "point_count": state["point_count"], "initial_bond_pairs": state["canonical_initial_bond_pairs"],
        "broken_bond_pairs": state["broken_bond_pairs_at_endpoint"],
        "initial_graph_component_count": summary["initial_graph_component_count"],
        "endpoint_components": state["intact_bond_graph_component_count"],
        "damage_min": min(damage), "damage_max": max(damage),
        "component_point_counts": {str(c): component.count(c) for c in sorted(set(component))},
        "active_bond_degree_min": min(degree), "active_bond_degree_max": max(degree),
        "total_endpoint_mass_kg": result["material"]["rho_kg_m3"] * result["initial_condition"]["point_volume_sum_mm3"] * 1e-9,
        "strain_energy_j": solver["strain_energy_j"], "kinetic_energy_j": solver["kinetic_energy_j"],
        "csv_sha256": {record["path"]: record["sha256"] for record in result["outputs"]},
        "integrity_checks": check,
        "scope": "actual solver point/bond CSV visualization only; no crack surface or ceramic realism claim",
        "projection": "isometric orthographic; x/y/z coordinate axes share the same mm-per-pixel scale",
    }, indent=2)
    (ROOT / "visuals" / "osb_fracture_point_state_audit.json").write_text(bond_summary + "\n", encoding="utf-8")
    print(TARGET.resolve())


if __name__ == "__main__":
    main()
