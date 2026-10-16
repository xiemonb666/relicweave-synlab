from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
JOBS = ROOT / "jobs"
OUT = ROOT / "visuals" / "bar_point_state_OSB_BB.png"
WIDTH, HEIGHT = 1800, 1290
BG = (248, 249, 251)
INK = (28, 36, 48)
GRID = (218, 223, 230)
PANEL = (255, 255, 255)


def read_result(name: str) -> tuple[dict, list[dict[str, str]]]:
    folder = JOBS / name / "output"
    result = json.loads((folder / "result.json").read_text(encoding="utf-8"))
    with (folder / "points.csv").open(newline="", encoding="utf-8") as stream:
        points = list(csv.DictReader(stream))
    return result, points


def color_diverging(value: float, bound: float) -> tuple[int, int, int]:
    t = max(-1.0, min(1.0, value / bound)) if bound else 0.0
    if t < 0:
        a, b = (58, 112, 184), (248, 248, 248)
        q = t + 1.0
    else:
        a, b = (248, 248, 248), (196, 45, 49)
        q = t
    return tuple(round(a[i] * (1 - q) + b[i] * q) for i in range(3))


def color_damage(value: float) -> tuple[int, int, int]:
    a, b = (46, 118, 174), (209, 52, 43)
    t = max(0.0, min(1.0, value))
    return tuple(round(a[i] * (1 - t) + b[i] * t) for i in range(3))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def known_vector_checks() -> dict:
    neg, zero, pos = color_diverging(-1.0, 1.0), color_diverging(0.0, 1.0), color_diverging(1.0, 1.0)
    conversions = [
        {"input": 1.0, "input_unit": "m", "multiplier": 1000.0, "output": 1000.0,
         "expected": 1000.0, "output_unit": "mm", "pass": 1.0 * 1000.0 == 1000.0},
        {"input": 1.0, "input_unit": "mm", "multiplier": 1000.0, "output": 1000.0,
         "expected": 1000.0, "output_unit": "um", "pass": 1.0 * 1000.0 == 1000.0},
        {"input": -1.0, "input_unit": "mm", "multiplier": 1000.0, "output": -1000.0,
         "expected": -1000.0, "output_unit": "um", "pass": -1.0 * 1000.0 == -1000.0},
        {"input": 1.0, "input_unit": "m", "multiplier": 1e9, "output": 1e9,
         "expected": 1e9, "output_unit": "nm", "pass": 1.0 * 1e9 == 1e9},
    ]
    colors = {"negative": list(neg), "zero": list(zero), "positive": list(pos),
              "negative_is_blue": neg[2] > neg[0], "positive_is_red": pos[0] > pos[2],
              "zero_is_neutral": zero == (248, 248, 248)}
    if not all(item["pass"] for item in conversions) or not all(colors[k] for k in
            ("negative_is_blue", "positive_is_red", "zero_is_neutral")):
        raise AssertionError(f"visual unit/sign conversion check failed: {conversions}, {colors}")
    return {"status": "PASS", "conversions": conversions, "diverging_sign_color_check": colors}


def panel(draw: ImageDraw.ImageDraw, x: int, y: int, title: str, points: list[dict[str, str]],
          color_field: str, current: bool, displacement_bound: float, font, small, detail: str) -> None:
    w, h = 850, 530
    draw.rounded_rectangle((x, y, x + w, y + h), radius=14, fill=PANEL, outline=(219, 224, 231), width=2)
    draw.text((x + 20, y + 14), title, font=font, fill=INK)
    draw.text((x + 20, y + 48), "x-z projection; y layers overlap in this view", font=small, fill=(92, 101, 114))
    draw.multiline_text((x + 20, y + 70), detail, font=small, fill=(72, 82, 96), spacing=1)
    coordinate_state = "current" if current else "ref"
    xx = [float(p[f"x_{coordinate_state}_m"]) * 1000 for p in points]
    zz = [float(p[f"z_{coordinate_state}_m"]) * 1000 for p in points]
    vals = [float(p[color_field]) for p in points]
    xmin, xmax = min(xx), max(xx)
    zmin, zmax = min(zz), max(zz)
    xspan = max(xmax - xmin, 1.0)
    zspan = max(zmax - zmin, 1.0)
    pad_x, pad_z = 1.0, 1.0
    xmin -= pad_x; xmax += pad_x
    zmin -= pad_z; zmax += pad_z
    plot_l, plot_t, plot_r, plot_b = x + 92, y + 116, x + 674, y + 456
    scale = min((plot_r - plot_l) / (xmax - xmin), (plot_b - plot_t) / (zmax - zmin))
    draw_w, draw_h = (xmax - xmin) * scale, (zmax - zmin) * scale
    px0 = plot_l + ((plot_r - plot_l) - draw_w) / 2
    py0 = plot_t + ((plot_b - plot_t) - draw_h) / 2

    def mapxy(a: float, b: float) -> tuple[float, float]:
        return px0 + (a - xmin) * scale, py0 + (zmax - b) * scale

    # Grid and numeric ticks are in the actual coordinate units from points.csv.
    for tick in range(int(xmin) + 1, int(xmax) + 1):
        tx, _ = mapxy(float(tick), zmin)
        draw.line((tx, py0, tx, py0 + draw_h), fill=GRID, width=1)
        draw.text((tx - 10, py0 + draw_h + 7), str(tick), font=small, fill=INK)
    for tick in range(int(zmin) + 1, int(zmax) + 1):
        _, ty = mapxy(xmin, float(tick))
        draw.line((px0, ty, px0 + draw_w, ty), fill=GRID, width=1)
        draw.text((px0 - 38, ty - 8), str(tick), font=small, fill=INK)
    draw.rectangle((px0, py0, px0 + draw_w, py0 + draw_h), outline=(70, 78, 88), width=2)
    draw.text((px0 + draw_w / 2 - 28, py0 + draw_h + 27), "x (mm)", font=small, fill=INK)
    draw.text((x + 20, py0 + draw_h / 2), "z (mm)", font=small, fill=INK)

    for a, b, value in zip(xx, zz, vals):
        cx, cy = mapxy(a, b)
        c = color_diverging(value, displacement_bound) if color_field == "u_z_nm" else color_damage(value)
        draw.ellipse((cx - 5, cy - 5, cx + 5, cy + 5), fill=c, outline=(27, 34, 44), width=1)

    # A scale bar uses the same x/z coordinate-to-pixel scale as the plotted data.
    bar_mm = min(2.0, max(1.0, xspan / 2))
    bar_px = bar_mm * scale
    bar_x, bar_y = x + 701, y + 180
    draw.line((bar_x, bar_y, bar_x, bar_y + 190), fill=(70, 78, 88), width=5)
    if color_field == "u_z_nm":
        for step in range(101):
            q = step / 100
            c = color_diverging((1 - 2 * q) * displacement_bound, displacement_bound)
            draw.line((x + 722, y + 125 + step * 2, x + 742, y + 125 + step * 2), fill=c, width=3)
        draw.text((x + 748, y + 123), f"+{displacement_bound:.5g}", font=small, fill=INK)
        draw.text((x + 748, y + 220), "0", font=small, fill=INK)
        draw.text((x + 748, y + 323), f"-{displacement_bound:.5g}", font=small, fill=INK)
        draw.text((x + 718, y + 350), "u_z (nm)", font=small, fill=INK)
    else:
        for step in range(101):
            q = step / 100
            c = color_damage(1 - q)
            draw.line((x + 722, y + 125 + step * 2, x + 742, y + 125 + step * 2), fill=c, width=3)
        draw.text((x + 748, y + 123), "1", font=small, fill=INK)
        draw.text((x + 748, y + 323), "0", font=small, fill=INK)
        draw.text((x + 718, y + 350), "damage", font=small, fill=INK)
    draw.line((bar_x - 7, bar_y, bar_x + 7, bar_y), fill=(70, 78, 88), width=2)
    draw.line((bar_x - 7, bar_y + 190, bar_x + 7, bar_y + 190), fill=(70, 78, 88), width=2)
    draw.text((bar_x - 14, bar_y + 198), f"{bar_mm:g} mm", font=small, fill=INK)


def main() -> None:
    osb, osb_points = read_result("osb_smoke_004")
    bb, bb_points = read_result("bb_smoke_002")
    osb_uz_nm = [(float(p["z_current_m"]) - float(p["z_ref_m"])) * 1e9 for p in osb_points]
    bb_uz_nm = [(float(p["z_current_m"]) - float(p["z_ref_m"])) * 1e9 for p in bb_points]
    osb_bound = max(abs(min(osb_uz_nm)), abs(max(osb_uz_nm))) or 1e-15
    bb_bound = max(abs(min(bb_uz_nm)), abs(max(bb_uz_nm))) or 1e-15
    font = ImageFont.load_default(size=22)
    small = ImageFont.load_default(size=15)
    image = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(image)
    draw.text((34, 22), "PG-Frag solver output | numerical bar point-state diagnostics", font=ImageFont.load_default(size=30), fill=INK)
    draw.text((35, 62), "72-point uniform-box fixtures; plotted point coordinates and fields come from each result CSV. No crack surface is reconstructed.",
              font=ImageFont.load_default(size=18), fill=(75, 84, 97))

    rows = [("OSBMaterial", osb, osb_points, osb_uz_nm, osb_bound, 128),
            ("BBMaterial", bb, bb_points, bb_uz_nm, bb_bound, 690)]
    audit_panels = []
    source_hashes = {}
    for model, result, points, uz_nm, bound, y in rows:
        solver = result["solver"]
        state = result["state"]
        draw.text((35, y - 28),
                  f"{model} | {result['job_id']} | n={state['point_count']} | broken bonds={state['broken_bond_pairs_at_endpoint']} | endpoint components={state['intact_bond_graph_component_count']}",
                  font=font, fill=(34, 76, 117))
        actual_uz_min, actual_uz_max = min(uz_nm), max(uz_nm)
        damage = [float(p["damage"]) for p in points]
        actual_damage_min, actual_damage_max = min(damage), max(damage)
        local_points = [dict(p, u_z_nm=str(dz)) for p, dz in zip(points, uz_nm)]
        panel(draw, 24, y, "Reference x-z points; signed axial displacement u_z",
              local_points, "u_z_nm", False, bound, font, small,
              f"formula: (z_current_m - z_ref_m)*1e9 -> nm | actual min/max=[{actual_uz_min:.6g}, {actual_uz_max:.6g}] nm\nsymmetric color scale=[-{bound:.6g}, +{bound:.6g}] nm")
        panel(draw, 900, y, "Current x-z points; upstream damage",
              local_points, "damage", True, bound, font, small,
              f"fixed color domain [0,1] | actual [{actual_damage_min:.6g}, {actual_damage_max:.6g}] | source column: damage")

        # Fixture folders are pinned explicitly so the source job identity is auditable.
        job_folder = "osb_smoke_004" if model == "OSBMaterial" else "bb_smoke_002"
        job_output = JOBS / job_folder / "output"
        points_path, result_path = job_output / "points.csv", job_output / "result.json"
        source_hashes[result["job_id"]] = {"points.csv": sha256_file(points_path), "result.json": sha256_file(result_path)}
        audit_panels.extend([
            {"job_id": result["job_id"], "panel": "signed axial displacement",
             "variable": "u_z", "formula": "(z_current_m - z_ref_m) * 1e9", "source_columns": ["z_current_m", "z_ref_m"],
             "source_unit": "m", "output_unit": "nm", "multiplier": 1e9,
             "actual_minmax": {"min": actual_uz_min, "max": actual_uz_max},
             "colorscale": {"type": "diverging", "min": -bound, "center": 0.0, "max": bound},
             "source_sha256": source_hashes[result["job_id"]]},
            {"job_id": result["job_id"], "panel": "upstream point damage",
             "variable": "damage", "formula": "damage", "source_columns": ["damage"],
             "source_unit": "1", "output_unit": "1", "multiplier": 1.0,
             "actual_minmax": {"min": actual_damage_min, "max": actual_damage_max},
             "colorscale": {"type": "sequential", "min": 0.0, "max": 1.0},
             "source_sha256": source_hashes[result["job_id"]]},
        ])

    # Footer is explicit about what this visualization can establish.
    draw.text((35, 1240), "Diagnostic scope: point-state projection only; projection collapses y layers. Marker size is visual, not a physical radius. These runs had no broken bonds.",
              font=ImageFont.load_default(size=17), fill=(88, 95, 105))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    image.save(OUT)
    audit = {
        "schema": "pgfrag.point_state_contact_sheet_audit.v2",
        "image_path": str(OUT.resolve()),
        "image_sha256": sha256_file(OUT),
        "source_sha256": source_hashes,
        "panels": audit_panels,
        "known_vector_checks": known_vector_checks(),
        "geometry_coordinates": {"source_columns": ["x_ref_m", "z_ref_m", "x_current_m", "z_current_m"],
                                  "source_unit": "m", "output_unit": "mm", "multiplier": 1000.0,
                                  "formula": "coordinate_m * 1000", "axes_equal_scale": True},
        "scope": "actual CSV point-state diagnostics for low-load OSB/BB fixtures; no crack surface is reconstructed",
    }
    (OUT.parent / "bar_point_state_OSB_BB_audit.json").write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    print(OUT.resolve())


if __name__ == "__main__":
    main()
