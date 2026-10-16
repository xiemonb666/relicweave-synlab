from pathlib import Path
p = Path("docs/a12/fracture_appearance.md")
t = p.read_text(encoding="utf-8")
bad = "| 参考：V10/M11（plane 线）面片中位面积 | 18 px ≈ 0 |"
good = ("| 参考：V10/M11（plane 线）断口的面片中位面积（另一具碎片实测） | "
        "5388 px → 等效棱长 ≈ 111 px ≈ **8.1 mm** |")
assert bad in t, "row missing"
t = t.replace(bad, good, 1)
t = t.replace("`median_face_area_px = 5388`", "`median_face_area_px = 5388 px`（≈ 8.1 mm 棱长）")
p.write_text(t, encoding="utf-8")
print("fixed")
