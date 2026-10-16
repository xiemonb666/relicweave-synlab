"""Fill the markdown placeholders of docs/a12/fracture_appearance.md from the real run JSON."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DOC = ROOT / "docs/a12/fracture_appearance.md"
RUN = ROOT / "data/a12_reports/physical_layer/fracture_appearance_run.json"
d = json.loads(RUN.read_text(encoding="utf-8"))
stages = d.get("stages", {})
sub: dict[str, str] = {}


def fmt(value, digits=3):
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


# ------------------------------------------------------------------ dDN table
s = stages.get("sweep")
if s:
    lines = ["| mm/px | 交付长边 L px | ss | `relief_off` 的 dN p95−p05 | 面片边界 DN | 面片内部 DN | "
             "`Ra` 实测 mm | **dDN rms** | dDN p95 | 改变 ≥1 码值 | 改变 ≥2 码值 | 预测 dDN |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for row in s["rows"]:
        if row.get("status") != "OK":
            lines.append(f"| {row.get('mm_per_px_target')} | {row.get('long_edge_px')} | — | "
                         f"UNREACHABLE | | | | | | | | |")
            continue
        off = row["relief_off"]
        for a in row["amplitudes"]:
            df = a["difference"]
            ch = a["changed_code_values"]
            lines.append(
                f"| {row['mm_per_px_measured']:.4f} | {row['long_edge_px']} | {row['supersample']} | "
                f"{off['dn']['dn_p95_minus_p05']:.1f} | {off['facet']['facet_edge_dn_step']:.2f} | "
                f"{off['facet']['interior_dn_step']:.3f} | {a['ra_realized_mm']:.4f} | "
                f"**{df['dDN_rms']:.2f}** | {df['dDN_p95_abs']:.2f} | "
                f"{ch['fraction_above_1_dn'] * 100:.1f} % | "
                f"{ch['fraction_above_2_dn'] * 100:.1f} % | "
                f"{a['prediction']['dDN_from_measured_slope']:.2f} |")
    sub["TABLE_DDN"] = "\n".join(lines)

# ------------------------------------------------------------------ facets
fac = stages.get("facets")
if fac:
    lines = [f"（`mm/px = {fac['mm_per_px_measured']:.5f}`，交付长边 {fac['long_edge_px']} px，"
             f"折痕角 {fac['variants']['SMOOTH_CREASE']['crease_angle_deg']:g}°，"
             f"面片中位面积 {fac['variants']['FLAT']['per_face_palette']['facet']['median_face_area_px']:.0f} px）", "",
             "| 着色法线 | 反照率 | 面片边界 DN 阶跃 | 面片内部 DN 阶跃 | 比值 | 全图 dN p95−p05 | 几何哈希 |",
             "|---|---|---|---|---|---|---|"]
    for key, v in fac["variants"].items():
        for src, label in (("per_face_palette", "逐面调色板（交付默认）"),
                           ("constant_material_albedo", "常数材料反照率")):
            m = v[src]
            lines.append(f"| `{key}`（{v['label']}） | {label} | "
                         f"{m['facet']['facet_edge_dn_step']:.2f} | "
                         f"{m['facet']['interior_dn_step']:.3f} | "
                         f"{m['facet']['facet_contrast_ratio']:.1f} | "
                         f"{m['dn']['dn_p95_minus_p05']:.1f} | "
                         f"{v['geometry_hash'][:22]}… |")
    sub["TABLE_FACETS"] = "\n".join(lines)

    md = fac.get("mesh_density")
    if md:
        inv = md["inverse_solve"]
        lines = [f"（试样 `{d['roi_frame']['roi_id']}` 的断口补片实测：{md['patch_edges']['n_faces']} 面、"
                 f"{md['patch_edges']['area_mm2']:.1f} mm²、棱长中位 "
                 f"{md['patch_edges']['edge_median_mm']:.3f} mm）", "",
                 "| 量 | 值 |", "|---|---|",
                 f"| `λ_min`（M01 审计带集） | {inv['lambda_min_mm']:.3f} mm |",
                 f"| 要求棱长 `L = λ_min/ratio`（ratio={inv['ratio']:g}） | **{inv['required_edge_mm']:.4f} mm** |",
                 f"| 该棱长下的三角面数（1 mm² 断口） | **{inv['required_triangles']:.0f} 面/mm²** |",
                 f"| 折算四叉树单元 | {inv['required_cells_equivalent']:.0f} 单元/mm² |",
                 f"| 当前棱长（实测中位） | {inv['current_edge_mm']:.3f} mm |",
                 f"| 密度倍数 | **~{inv['density_factor']:.0e}×** |",
                 f"| 要求棱长在 0.073 mm/px 下 | {md['required_edge_in_px']['edge_px']:.3f} px（面片不可见） |",
                 f"| 当前棱长在 0.073 mm/px 下 | {md['current_edge_in_px']['edge_px']:.1f} px（面片可见） |"]
        sub["TABLE_DENSITY"] = "\n".join(lines)

# ------------------------------------------------------------------ materials
mat = stages.get("materials")
if mat:
    lines = [f"（同一断口几何，`mm/px = {mat['mm_per_px_measured']:.5f}`）", "",
             "| 材料 | grain mm | 孔隙率 | `σ_r0` mm | `λ_min` mm | 纤维周期 mm | 透射 | 釉层 mm | "
             "实测 `Ra` mm | dN p95−p05 | **dDN rms** | 方向性(结构张量) | 颗粒中位 px | 面片边界 DN |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for mid, row in mat["materials"].items():
        p = row["parameters"]
        on = row["relief_on"]
        blob = on["grain"].get("median_blob_px")
        lines.append(
            f"| **{mid}** {p['material_name']} | {p['grain_scale_mm']:.2f} | {p['porosity']:.4f} | "
            f"{p['sigma_r0_mm']:.4f} | {p['lambda_min_mm']:.3f} | {p['fiber_period_mm']:.2f} | "
            f"{p['transmission']:.2f} | {p['glaze_thickness_mm']:.2f} | "
            f"{row['relief_field']['realized_ra_mm']:.4f} | {on['dn']['dn_p95_minus_p05']:.1f} | "
            f"**{row['difference_relief_on_minus_off']['dDN_rms']:.2f}** | "
            f"{on['direction']['anisotropy']:.3f} | "
            f"{(f'{blob:.0f}' if blob == blob else 'n/a')} | "
            f"{on['facet']['facet_edge_dn_step']:.2f} |")
    sub["TABLE_MATERIALS"] = "\n".join(lines)

# ------------------------------------------------------------------ glaze
gl = stages.get("glaze")
if gl:
    a = gl["asset_channels"]
    sub["GLAZE_ASSETS"] = (
        f"* 资产数组键（实测）：`{a['keys']}`\n"
        f"* 是否存在层/釉通道：**{a['has_layer_channel']}**\n"
        f"* 检查的 store：{', '.join(a['runs'])}\n"
        f"* 判定：{a['verdict']}")
    m = gl.get("measured_layer_shell")
    if m:
        sub["GLAZE_SHELL"] = (
            f"* 组合 `{m['combo']}` → 层 `{m['thickness_mm']}`，材料 `{m['material']}`，"
            f"模式 `{m['kind']}`\n"
            f"* **p05 / median / max = {m['thickness_mm'].get('p05_mm', float('nan')):.3f} / "
            f"{m['thickness_mm'].get('median_mm', float('nan')):.3f} / "
            f"{m['thickness_mm'].get('max_mm', float('nan')):.3f} mm**，体积 {m['volume_mm3']:.0f} mm³\n"
            f"* 仪器：`{m['instrument']}`")
    elif gl.get("measured_layer_shell_error"):
        sub["GLAZE_SHELL"] = f"（本次实测失败：`{gl['measured_layer_shell_error'][:200]}`）"
    st = gl.get("relief_damping_strip")
    if st:
        sub["GLAZE_STRIP"] = (
            f"* 材料 `{st['material']}`（釉层 {st['glaze_thickness_mm']:.2f} mm，kind `{st['glaze_kind']}`）；"
            f"阻尼带宽 **{st['strip_width_mm']:.3f} mm = {st['strip_width_px']:.1f} px**"
            f"（@ {gl['mm_per_px_measured']:.5f} mm/px），ratio {st['ratio']:.2f}\n"
            f"* `strip ON` vs `OFF` 的实测差：**dDN rms {st['difference']['dDN_rms']:.2f}**，"
            f"受影响像素占比 **{st['changed_pixel_fraction'] * 100:.1f} %**"
            f"（即断口前缘那一圈）")

# ------------------------------------------------------------------ images
im = stages.get("images")
if im:
    lines = []
    for v in im["views"]:
        name = Path(v["path"]).name
        lines.append(
            f"* `data/a12_reports/physical_layer/{name}` — 交付长边 **{v['long_edge_px']} px**、"
            f"`mm/px = {v['mm_per_px_measured']:.5f}`、`Ra = {v['ra_mm']} mm`、"
            f"`supersample = {v['supersample']}`；"
            f"`dDN` rms **{v['dDN']['dDN_rms']:.2f}** / p95 {v['dDN']['dDN_p95_abs']:.2f}；"
            f"面片边界 DN off/on/smooth = {v['facet_edge_step_relief_off']:.2f} / "
            f"{v['facet_edge_step_relief_on']:.2f} / {v['facet_edge_step_smooth']:.2f}")
    lines.append("* `data/a12_reports/physical_layer/fracture_appearance_materials_1024.png` — "
                 "三材料断口特写并排（同一几何）")
    sub["IMAGES"] = "\n".join(lines)

text = DOC.read_text(encoding="utf-8")
missing = [k for k in sub if f"<!--{k}-->" not in text]
for key, value in sub.items():
    text = text.replace(f"<!--{key}-->", value)
DOC.write_text(text, encoding="utf-8")
print("filled:", sorted(sub))
print("placeholders left:", [k for k in ("TABLE_DDN", "TABLE_FACETS", "TABLE_DENSITY",
                                          "TABLE_MATERIALS", "GLAZE_ASSETS", "GLAZE_SHELL",
                                          "GLAZE_STRIP", "IMAGES") if f"<!--{k}-->" in text])
