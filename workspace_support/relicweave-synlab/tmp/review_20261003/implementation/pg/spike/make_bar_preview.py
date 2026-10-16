"""Render a small point-state audit sheet without fabricating a crack surface."""
from __future__ import annotations

import csv
import os
import tomllib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(os.environ.get("PG_SPIKE_OUT_ROOT", Path(__file__).parent / "series_v3"))
OUT = ROOT / "bar_point_state_preview.png"
DETAIL = ROOT / "bar_high_load_50_detail.png"
CASES = [
    ("zero_h1", "zero-load | h=1 mm | 50 steps"),
    ("low_load_h1", "0.1 m/s | h=1 mm | 50 steps"),
    ("high_load_h1/steps_5", "0.5 m/s | h=1 mm | 5 steps"),
    ("high_load_h1/steps_20", "0.5 m/s | h=1 mm | 20 steps"),
    ("high_load_h1/steps_35", "0.5 m/s | h=1 mm | 35 steps"),
    ("high_load_h1/steps_50", "0.5 m/s | h=1 mm | 50 steps"),
    ("high_load_h1_dt_half", "0.5 m/s | h=1 mm | dt/2, 100 steps"),
    ("high_load_h1p5_same_time", "0.5 m/s | h=1.5 mm | same delta/time"),
]

FONT = ImageFont.load_default()
COMP_COLORS = [
    (54, 95, 145), (220, 90, 55), (70, 145, 90), (151, 90, 165),
    (219, 174, 49), (52, 155, 165), (189, 76, 119), (119, 119, 119),
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def damage_color(value: float) -> tuple[int, int, int]:
    value = max(0.0, min(1.0, value))
    return (int(35 + 215 * value), int(72 + 80 * (1 - value)), int(190 - 170 * value))


def diverging_color(value: float, span: float) -> tuple[int, int, int]:
    q = 0.0 if span == 0 else max(-1.0, min(1.0, value / span))
    neutral = (248, 248, 248)
    target = (49, 83, 164) if q < 0 else (180, 4, 38)
    w = abs(q)
    return tuple(round(neutral[i] * (1 - w) + target[i] * w) for i in range(3))


def draw_panel(draw: ImageDraw.ImageDraw, x0: int, y0: int, w: int, h: int,
               rows: list[dict[str, str]], component_by_point: dict[int, int],
               field: str, title: str, bigger: bool = False) -> None:
    left, top, right, bottom = x0 + 34, y0 + 29, x0 + w - 12, y0 + h - 29
    draw.text((x0 + 8, y0 + 5), title, fill=(25, 25, 25), font=FONT)
    ys = sorted({float(row["y_ref_m"]) for row in rows})
    ymid = (ys[0] + ys[-1]) / 2
    yslice = min(ys, key=lambda y: abs(y - ymid))
    slice_rows = [row for row in rows if abs(float(row["y_ref_m"]) - yslice) < 1e-12]
    xs = [float(row["x_current_m"]) for row in slice_rows]
    zs = [float(row["z_current_m"]) for row in slice_rows]
    xmin, xmax = min(xs), max(xs)
    zmin, zmax = min(zs), max(zs)
    xspan = max(xmax - xmin, 1e-12)
    zspan = max(zmax - zmin, 1e-12)
    draw.line((left, top, left, bottom), fill=(65, 65, 65), width=1)
    draw.line((left, bottom, right, bottom), fill=(65, 65, 65), width=1)
    draw.text((left, bottom + 5), "x (mm)", fill=(50, 50, 50), font=FONT)
    draw.text((x0 + 2, top), "z", fill=(50, 50, 50), font=FONT)
    span_disp = max(abs(float(row["z_current_m"]) - float(row["z_ref_m"])) for row in slice_rows) * 1000
    radius = 4 if bigger else 3
    for row in slice_rows:
        px = left + round((float(row["x_current_m"]) - xmin) / xspan * (right - left))
        py = bottom - round((float(row["z_current_m"]) - zmin) / zspan * (bottom - top))
        point_id = int(row["point_id"])
        if field == "damage":
            color = damage_color(float(row["damage"]))
        elif field == "component":
            component = component_by_point[point_id]
            color = COMP_COLORS[(component - 1) % len(COMP_COLORS)]
        else:
            uz_mm = (float(row["z_current_m"]) - float(row["z_ref_m"])) * 1000
            color = diverging_color(uz_mm, span_disp)
        draw.ellipse((px-radius, py-radius, px+radius, py+radius), fill=color,
                     outline=(30, 30, 30))
    draw.text((left, y0 + h - 18), f"material y={yslice*1000:.2f} mm: {len(slice_rows)} pts", fill=(70, 70, 70), font=FONT)


def make_sheet() -> None:
    tile_w, tile_h = 300, 220
    columns = 3
    sheet = Image.new("RGB", (columns * tile_w, 38 + len(CASES) * tile_h), "white")
    d = ImageDraw.Draw(sheet)
    d.text((8, 8), "Bond-based PD bar: point state only; no reconstructed crack surface or roughness", fill=(20, 20, 20), font=FONT)
    for idx, (rel, label) in enumerate(CASES):
        run = ROOT / rel
        rows = read_csv(run / "points.csv")
        comp_rows = read_csv(run / "components.csv")
        comp_map = {int(row["point_id"]): int(row["component_id"]) for row in comp_rows}
        summary = tomllib.loads((run / "summary.toml").read_text(encoding="utf-8"))
        row_y = 38 + idx * tile_h
        d.text((8, row_y + 1), f"{label}; damage={summary['max_damage']:.3f}, components={summary['intact_bond_connected_component_count']}", fill=(20, 20, 20), font=FONT)
        panel_y = row_y + 16
        draw_panel(d, 0, panel_y, tile_w, tile_h - 16, rows, comp_map, "damage", "damage 0..1")
        draw_panel(d, tile_w, panel_y, tile_w, tile_h - 16, rows, comp_map, "component", "intact-bond component")
        draw_panel(d, 2 * tile_w, panel_y, tile_w, tile_h - 16, rows, comp_map, "uz", "vertical displacement +/-")
    sheet.save(OUT)


def make_detail() -> None:
    run = ROOT / "high_load_h1" / "steps_50"
    rows = read_csv(run / "points.csv")
    comp_rows = read_csv(run / "components.csv")
    comp_map = {int(row["point_id"]): int(row["component_id"]) for row in comp_rows}
    image = Image.new("RGB", (1260, 400), "white")
    d = ImageDraw.Draw(image)
    s = tomllib.loads((run / "summary.toml").read_text(encoding="utf-8"))
    d.text((12, 8), f"0.5 m/s, 50 steps, t={s['time_s']:.6g} s; {s['broken_undirected_bond_count']} broken pairs; component sizes={s['component_sizes_points']}", fill=(20, 20, 20), font=FONT)
    for idx, (field, label) in enumerate((("damage", "damage 0..1"), ("component", "intact-bond component"), ("uz", "vertical displacement +/-"))):
        draw_panel(d, idx * 420, 26, 420, 370, rows, comp_map, field, label, bigger=True)
    image.save(DETAIL)


if __name__ == "__main__":
    make_sheet()
    make_detail()
    print(OUT.resolve())
    print(DETAIL.resolve())
