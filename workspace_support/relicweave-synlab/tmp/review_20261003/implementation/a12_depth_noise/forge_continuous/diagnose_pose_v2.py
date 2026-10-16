from pathlib import Path
import runpy
import numpy as np

ns = runpy.run_path("tests/a12/integrations/test_forge_asset.py")
asset = ns["load_forge_asset"](ns["_write_package"](
    Path("tmp/review_20261003/implementation/a12_depth_noise/forge_continuous/diag-fixture4/pkg"),
    continuous_recipe=True, sloped_region_1=True))
for angle_deg in (-24.0, -30.0, -18.0):
    angle = np.deg2rad(angle_deg)
    pose = np.asarray([[1, 0, 0, 0], [0, np.cos(angle), -np.sin(angle), 0],
                       [0, np.sin(angle), np.cos(angle), 0], [0, 0, 0, 1]], dtype=np.float64)
    for focal in (80.0, 120.0, 160.0, 240.0):
        frame = ns["_frame"]()
        frame.K[0, 0] = frame.K[1, 1] = focal
        output = ns["render_forge_asset_preview"](
            asset, frame, light=ns["_light"](),
            spec=ns["RenderSpec"](supersample=1, near_mm=1, far_mm=100, max_pixels=4096),
            allow_prototype_preview=True, object_pose=pose)
        tri = asset.vertices_mm[asset.faces[0]] @ pose[:3, :3].T + pose[:3, 3]
        z_values = []
        for row, col in zip(*np.nonzero(output.id_map == 0)):
            origin = frame.T_WC[:3, 3]
            ray = frame.T_WC[:3, :3] @ np.linalg.solve(
                frame.K, np.asarray([col, row, 1.0], dtype=np.float64))
            hit = ns["_ray_barycentric_world"](origin, ray, tri)
            if hit is not None:
                z_values.append(float(np.dot(hit[1], asset.vertices_material_xyz_mm[asset.faces[0], 2])))
        z = np.asarray(z_values)
        painted = np.count_nonzero(np.abs(z) <= 0.25)
        print(f"angle={angle_deg} focal={focal:g} face0={len(z)} painted={painted} "
              f"zmin={z.min() if z.size else None} zmax={z.max() if z.size else None}")
