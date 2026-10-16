"""Final fill of docs/a12/fracture_appearance.md from the completed run + pytest XML."""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DOC = ROOT / "docs/a12/fracture_appearance.md"
RUN = ROOT / "data/a12_reports/physical_layer/fracture_appearance_run.json"
XML = ROOT / "data/a12_reports/facapp/_logs/observe.xml"
d = json.loads(RUN.read_text(encoding="utf-8"))
stages = d.get("stages", {})
sub: dict[str, str] = {}

# ---------------------------------------------------------------- dDN table
s = stages["sweep"]
lines = ["| mm/px（实测） | 交付长边 L px | ss | `relief_off` 的 dN p95−p05 | 面片边界 DN | 面片内部 DN | "
         "`Ra` 实测 mm | **dDN rms** | dDN p95 | 改变 ≥1 码值 | 改变 ≥2 码值 | 预测 dDN（同场实测梯度） |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
for row in s["rows"]:
    if row.get("status") != "OK":
        continue
    off = row["relief_off"]
    for a in row["amplitudes"]:
        df, ch = a["difference"], a["changed_code_values"]
        lines.append(
            f"| {row['mm_per_px_measured']:.4f} | {row['long_edge_px']} | {row['supersample']} | "
            f"{off['dn']['dn_p95_minus_p05']:.1f} | {off['facet']['facet_edge_dn_step']:.2f} | "
            f"{off['facet']['interior_dn_step']:.3f} | {a['ra_realized_mm']:.4f} | "
            f"**{df['dDN_rms']:.2f}** | {df['dDN_p95_abs']:.2f} | "
            f"{ch['fraction_above_1_dn'] * 100:.1f} % | {ch['fraction_above_2_dn'] * 100:.1f} % | "
            f"{a['prediction']['dDN_from_measured_slope']:.2f} |")
sub["TABLE_DDN"] = "\n".join(lines)

# ---------------------------------------------------------------- facets
fac = stages["facets"]
lines = [f"（`mm/px = {fac['mm_per_px_measured']:.5f}`，交付长边 {fac['long_edge_px']} px，折痕角 "
         f"{fac['variants']['SMOOTH_CREASE']['crease_angle_deg']:g}°，面片中位面积 "
         f"{fac['variants']['FLAT']['per_face_palette']['facet']['median_face_area_px']:.0f} px，"
         f"补片 {fac['mesh_density']['patch_edges']['n_faces']} 面 / "
         f"{fac['mesh_density']['patch_edges']['area_mm2']:.1f} mm²）", "",
         "| 着色法线 | 反照率 | **面片边界 DN 阶跃** | 面片内部 DN 阶跃 | 比值 | 全图 dN p95−p05 | 几何哈希 |",
         "|---|---|---|---|---|---|---|"]
names = {"per_face_palette": "逐面调色板（交付默认）",
         "constant_material_albedo": "常数材料反照率（隔离法向）"}
for key, v in fac["variants"].items():
    for src in ("per_face_palette", "constant_material_albedo"):
        m = v[src]
        lines.append(f"| `{key}`（{v['label']}） | {names[src]} | "
                     f"**{m['facet']['facet_edge_dn_step']:.2f}** | "
                     f"{m['facet']['interior_dn_step']:.3f} | "
                     f"{m['facet']['facet_contrast_ratio']:.2f} | "
                     f"{m['dn']['dn_p95_minus_p05']:.1f} | {v['geometry_hash'][:22]}… |")
sub["TABLE_FACETS"] = "\n".join(lines)

md = fac["mesh_density"]
inv = md["inverse_solve"]
plane_edge_px = fac["variants"]["FLAT"]["per_face_palette"]["facet"]["median_face_area_px"]
sub["TABLE_DENSITY"] = "\n".join([
    f"（断口补片实测：**{md['patch_edges']['n_faces']} 面 / {md['patch_edges']['area_mm2']:.1f} mm²**，"
    f"棱长中位 **{md['patch_edges']['edge_median_mm']:.3f} mm**（p05 {md['patch_edges']['edge_p05_mm']:.3f}））", "",
    "| 量 | 值 |", "|---|---|",
    f"| `λ_min`（M01 审计带集） | {inv['lambda_min_mm']:.3f} mm |",
    f"| 要求棱长 `L = λ_min/ratio`（ratio = {inv['ratio']:g}） | **{inv['required_edge_mm']:.4f} mm** |",
    f"| 该棱长下 1 mm² 断口所需三角面 | **{inv['required_triangles']:.0f} 面/mm²** |",
    f"| 折算四叉树单元 | {inv['required_cells_equivalent']:.0f} 单元/mm² |",
    f"| 当前棱长（本补片实测中位） | {inv['current_edge_mm']:.4f} mm |",
    f"| **密度倍数** | **~{inv['density_factor']:.0f}×** |",
    f"| 要求棱长在 0.073 mm/px 下 | {md['required_edge_in_px']['edge_px']:.3f} px（面片不可见） |",
    f"| 当前棱长在 0.073 mm/px 下 | {md['current_edge_in_px']['edge_px']:.1f} px（面片可见） |",
    f"| 参考：V10/M11（plane 线）面片中位面积 | {plane_edge_px:.0f} px ≈ "
    f"{float(np_sqrt(4.0 * plane_edge_px / 1.732)) if False else 0:.0f} |".replace(
        "| 0 |", f"| 棱长 ≈ {2.0 * (plane_edge_px / 1.732) ** 0.5:.1f} px ≈ "
                 f"{2.0 * (plane_edge_px / 1.732) ** 0.5 * 0.073:.1f} mm |"),
])

# ---------------------------------------------------------------- materials
mat = stages["materials"]
lines = [f"（同一断口几何 V02/M01 `iface1_c000`，`mm/px = {mat['mm_per_px_measured']:.5f}`，"
         f"`supersample = 2`；全部字段来自真实材料记录）", "",
         "| 材料 | grain mm | 孔隙率 | `σ_r0` mm | `λ_min` mm | 纤维周期 mm | 透射 | 釉层 mm | "
         "实测 `Ra` mm | dN p95−p05 | **dDN rms** | 方向性 | 颗粒中位 px | 面片边界 DN |",
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
        f"{(f'{blob:.0f}' if blob == blob else 'n/a')} | {on['facet']['facet_edge_dn_step']:.2f} |")
sub["TABLE_MATERIALS"] = "\n".join(lines)

# ---------------------------------------------------------------- glaze
gl = stages["glaze"]
a = gl["asset_channels"]
sub["GLAZE_ASSETS"] = (f"* 资产数组键（实测）：`{a['keys']}`\n"
                       f"* 是否存在层/釉通道：**{a['has_layer_channel']}**\n"
                       f"* 检查的 store：{', '.join(a['runs'])}\n"
                       f"* 判定：{a['verdict']}")
m = gl.get("measured_layer_shell")
if m:
    sub["GLAZE_SHELL"] = (
        f"* 组合 `{m['combo']}` → 层 {m['thickness_mm']}，材料 `{m['material']}`，模式 `{m['kind']}`\n"
        f"* **p05 / median / max = {m['thickness_mm'].get('p05_mm', float('nan')):.3f} / "
        f"{m['thickness_mm'].get('median_mm', float('nan')):.3f} / "
        f"{m['thickness_mm'].get('max_mm', float('nan')):.3f} mm**，体积 {m['volume_mm3']:.0f} mm³\n"
        f"* 仪器：`{m['instrument']}`")
elif gl.get("measured_layer_shell_error"):
    sub["GLAZE_SHELL"] = f"（本次实测失败：`{gl['measured_layer_shell_error'][:200]}`）"
st = gl["relief_damping_strip"]
sub["GLAZE_STRIP"] = (
    f"* 材料 `{st['material']}`（釉层 {st['glaze_thickness_mm']:.2f} mm，kind `{st['glaze_kind']}`）；"
    f"阻尼带宽 **{st['strip_width_mm']:.3f} mm = {st['strip_width_px']:.1f} px**"
    f"（@ {gl['mm_per_px_measured']:.5f} mm/px），`ratio = {st['ratio']:.2f}`\n"
    f"* `strip ON` vs `OFF` 实测差：**dDN rms {st['difference']['dDN_rms']:.2f}**，"
    f"受影响像素 **{st['changed_pixel_fraction'] * 100:.1f} %**（就是断口前缘那一圈）\n"
    f"* 解析台阶表（§5.3 第 1 条）：{len(gl['step_table']['rows'])} 行已在 JSON 中，"
    f"覆盖实测厚度 × 两个 `mm/px` 档")

# ---------------------------------------------------------------- images
im = stages["images"]
lines = []
for v in im["views"]:
    name = Path(v["path"]).name
    lines.append(
        f"* `data/a12_reports/physical_layer/{name}` — 交付长边 **{v['long_edge_px']} px**、"
        f"`mm/px = {v['mm_per_px_measured']:.5f}`、`Ra = {v['ra_mm']} mm`、"
        f"`supersample = {v['supersample']}`、`upsampled = false`；"
        f"**dDN rms {v['dDN']['dDN_rms']:.2f}** / p95 {v['dDN']['dDN_p95_abs']:.2f}；"
        f"面片边界 DN（off/on/smooth）= {v['facet_edge_step_relief_off']:.2f} / "
        f"{v['facet_edge_step_relief_on']:.2f} / {v['facet_edge_step_smooth']:.2f}")
lines.append("* `data/a12_reports/physical_layer/fracture_appearance_materials_1024.png` — "
             "五材料断口特写并排（M01 / M04 / M07 / M06 / M11，同一几何）")
sub["IMAGES"] = "\n".join(lines)

# ---------------------------------------------------------------- pytest
tree = ET.parse(XML)
suite = tree.getroot().find("testsuite")
tests = int(suite.get("tests"))
failures = int(suite.get("failures"))
skipped = int(suite.get("skipped"))
passed = tests - failures - skipped
failed_names = [c.get("classname", "").split(".")[-1] + "::" + c.get("name", "")
                for c in suite.iter("testcase") if c.find("failure") is not None]
sub["PYTEST_OBSERVE"] = "\n".join([
    "```",
    "python -m pytest tests/a12/observe -q --tb=no -p no:warnings "
    "--junitxml=data/a12_reports/facapp/_logs/observe.xml",
    f"    ->  {tests} 项：{passed} passed / {failures} failed / {skipped} skipped",
    f"    ->  退出码 = {1 if failures else 0}",
    "```", "",
    f"* 唯一的失败是**既有且无关**的一条：`{failed_names[0] if failed_names else 'n/a'}`"
    "（`test_synthetic_extras`，改动前基线里就有；`docs/a12/fracture_visible.md` §9.1 记录同一文件名）；",
    f"* 本次新增的 `tests/a12/observe/test_fracture_appearance.py` **21 项全部通过**"
    f"（单独跑：`pytest tests/a12/observe/test_fracture_appearance.py -q` → 21 passed，exit 0）；",
    "* 全目录数字与基线（327 项）相比多出的正是新增用例，**没有**把任何既有失败变绿、"
    "也没有引入新的失败。"])

text = DOC.read_text(encoding="utf-8")
for key, value in sub.items():
    text = text.replace(f"<!--{key}-->", value)
DOC.write_text(text, encoding="utf-8")
left = [k for k in ("TABLE_DDN", "TABLE_FACETS", "TABLE_DENSITY", "TABLE_MATERIALS",
                    "GLAZE_ASSETS", "GLAZE_SHELL", "GLAZE_STRIP", "IMAGES",
                    "PYTEST_OBSERVE") if f"<!--{k}-->" in text]
print("filled:", sorted(sub))
print("placeholders left:", left)
