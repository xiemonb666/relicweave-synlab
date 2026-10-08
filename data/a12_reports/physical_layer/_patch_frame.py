"""Patch: apply the relief perturbation in the WORLD frame (the shading is world-frame)."""
from pathlib import Path

p = Path("synlab/observe/fracture_appearance.py")
t = p.read_text(encoding="utf-8")

pairs = [
    ("""    world_normals = face_n / np.maximum(np.linalg.norm(face_n, axis=1, keepdims=True), 1e-30)
""",
     """    # `face_n` is a CAMERA-space normal (the vertices above are camera-space; the frozen
    # rasteriser calls the cross product "world_normals" only by history).  The frozen shading
    # composes to ``-(n_world . l)`` with a world-frame light, and the relief tangents live in the
    # world frame, so the perturbation is applied to the **world** normal and converted back.
    R_WC = np.asarray(T_CW, dtype=np.float64)[:3, :3]
    cam_normals = face_n / np.maximum(np.linalg.norm(face_n, axis=1, keepdims=True), 1e-30)
    world_normals = cam_normals @ R_WC
"""),
    ("""        if appearance.normal_mode == "FLAT" and not relief_on:
            shaded = lambert_ambient_linear(normals_world=world_normals[f][None, :], T_WC=T_CW,
                                            albedo=albedo_px[f][None, :], light=light)[0]
""",
     """        if appearance.normal_mode == "FLAT" and not relief_on:
            shaded = shade_world_normals(normals_world=world_normals[f][None, :],
                                         albedo=albedo_px[f][None, :], light=light)[0]
"""),
    ("""        shaded = lambert_ambient_linear(
            normals_world=n_px, T_WC=T_CW,
            albedo=np.repeat(albedo_px[f][None, :], pts.shape[0], axis=0), light=light)
""",
     """        shaded = shade_world_normals(
            normals_world=n_px,
            albedo=np.repeat(albedo_px[f][None, :], pts.shape[0], axis=0), light=light)
"""),
    # prediction: the light is already the world-frame light, no extra rotation
    ("""        l_eff = np.asarray(T_WC, dtype=np.float64)[:3, :3] @ np.asarray(light.direction,
                                                                       dtype=np.float64)
""",
     """        l_eff = np.asarray(light.direction, dtype=np.float64).reshape(3)
"""),
]
for old, new in pairs:
    if old not in t:
        raise SystemExit("PATTERN NOT FOUND:\n" + old[:200])
    t = t.replace(old, new)
p.write_text(t, encoding="utf-8")
print("patched", len(pairs))
