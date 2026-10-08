from pathlib import Path
p = Path("data/a12_reports/physical_layer/_fill_doc.py")
t = p.read_text(encoding="utf-8")
old = '''    lines = [f"（`mm/px = {fac['mm_per_px_measured']:.5f}`，交付长边 {fac['long_edge_px']} px，"
             f"折痕角 {fac['variants']['SMOOTH_CREASE']['crease_angle_deg']:g}°）", "",
             "| 着色法线 | 面片边界 DN 阶跃 | 面片内部 DN 阶跃 | 比值 | 面片中位面积 px | 全图 dN p95−p05 | 几何哈希 |",
             "|---|---|---|---|---|---|---|"]
    for key, v in fac["variants"].items():
        m = v["measured"]
        lines.append(f"| `{key}`（{v['label']}） | {m['facet']['facet_edge_dn_step']:.2f} | "
                     f"{m['facet']['interior_dn_step']:.3f} | "
                     f"{m['facet']['facet_contrast_ratio']:.1f} | "
                     f"{m['facet']['median_face_area_px']:.0f} | "
                     f"{m['dn']['dn_p95_minus_p05']:.1f} | "
                     f"{v['geometry_hash'][:22]}… |")
    sub["TABLE_FACETS"] = "\\n".join(lines)'''
new = '''    lines = [f"（`mm/px = {fac['mm_per_px_measured']:.5f}`，交付长边 {fac['long_edge_px']} px，"
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
    sub["TABLE_FACETS"] = "\\n".join(lines)'''
assert old in t, "facet fill pattern missing"
t = t.replace(old, new, 1)
p.write_text(t, encoding="utf-8")
print("ok")
