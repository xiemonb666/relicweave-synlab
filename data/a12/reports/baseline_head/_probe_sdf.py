"""Scratch probe 2: open3d raycasting + manifold booleans + trimesh paths without rtree."""
import time
import numpy as np
import trimesh
import open3d as o3d

mesh = trimesh.creation.box(extents=(30.0, 20.0, 8.0)).subdivide().subdivide()
print("faces", len(mesh.faces), "watertight", mesh.is_watertight, "vol", round(mesh.volume, 3))

legacy = o3d.geometry.TriangleMesh(o3d.utility.Vector3dVector(np.asarray(mesh.vertices)),
                                   o3d.utility.Vector3iVector(np.asarray(mesh.faces)))
scene = o3d.t.geometry.RaycastingScene()
scene.add_triangles(o3d.t.geometry.TriangleMesh.from_legacy(legacy))

nx = ny = nz = 48
spacing = 0.5
origin = np.asarray(mesh.bounds[0]) - 1.0
xs = origin[0] + spacing * np.arange(nx)
ys = origin[1] + spacing * np.arange(ny)
zs = origin[2] + spacing * np.arange(nz)
nodes = np.stack(np.meshgrid(xs, ys, zs, indexing="ij"), axis=-1).reshape(-1, 3)
print("nodes", nodes.shape)

t1 = time.time()
q = o3d.core.Tensor(nodes.astype(np.float32))
sd = scene.compute_signed_distance(q).numpy()
print("o3d sd", time.time() - t1, "min", sd.min(), "max", sd.max(), "neg frac", float((sd < 0).mean()))

t1 = time.time()
occ = scene.compute_occupancy(q).numpy().astype(bool)
print("o3d occ", time.time() - t1, "inside frac", occ.mean(), "agree", float((occ == (sd < 0)).mean()))

# voxel grid inside fraction vs true volume
vol_vox = occ.sum() * spacing ** 3
print("voxel volume", vol_vox, "true", mesh.volume)

# marching cubes on the SDF
from skimage import measure

field = sd.reshape(nx, ny, nz).astype(np.float32)
t1 = time.time()
verts, faces, normals, values = measure.marching_cubes(field, level=0.0, spacing=(spacing,) * 3)
print("mc", len(verts), len(faces), time.time() - t1)
world = verts + origin
m2 = trimesh.Trimesh(vertices=world, faces=faces, process=True)
print("mc mesh watertight", m2.is_watertight, "vol", round(abs(m2.volume), 3), "true", round(mesh.volume, 3))

# boolean
cut = trimesh.creation.box(extents=(15.0, 20.0, 8.0), transform=trimesh.transformations.translation_matrix([-5, 0, 0]))
t1 = time.time()
res = trimesh.boolean.intersection([mesh, cut], engine="manifold")
print("intersection", len(res.faces), round(res.volume, 3), res.is_watertight, time.time() - t1)
t1 = time.time()
dif = trimesh.boolean.difference([mesh, cut], engine="manifold")
print("difference", len(dif.faces), round(dif.volume, 3), dif.is_watertight, time.time() - t1)

# surface sampling
t1 = time.time()
pts, fid = trimesh.sample.sample_surface(mesh, 4000)
print("sample_surface", pts.shape, time.time() - t1)
try:
    t1 = time.time()
    ev, _ = trimesh.sample.sample_surface_even(mesh, 4000)
    print("sample_surface_even", ev.shape, time.time() - t1)
except Exception as exc:
    print("sample_surface_even failed", type(exc).__name__, exc)

# open3d raycasting for thickness
t1 = time.time()
rays = np.concatenate([pts + np.asarray(mesh.face_normals[fid]) * 1e-3,
                       -np.asarray(mesh.face_normals[fid])], axis=1).astype(np.float32)
res = scene.cast_rays(o3d.core.Tensor(rays))
t_hit = res["t_hit"].numpy()
print("cast_rays", time.time() - t1, np.nanpercentile(t_hit, [5, 50]), "finite", np.isfinite(t_hit).mean())

# open3d occupancy for "point inside"
pts_rand = np.random.default_rng(0).uniform(-20, 20, size=(2000, 3))
occ2 = scene.compute_occupancy(o3d.core.Tensor(pts_rand.astype(np.float32))).numpy().astype(bool)
print("contains via occ", occ2.mean())

# QEM
t1 = time.time()
dec = legacy.simplify_quadric_decimation(target_number_of_triangles=48)
print("qem", len(np.asarray(dec.triangles)), time.time() - t1)

# open3d hausdorff-ish: nearest distance both ways
t1 = time.time()
a = o3d.core.Tensor(pts.astype(np.float32))
d1 = scene.compute_distance(o3d.core.Tensor(ev.astype(np.float32))).numpy() if 'ev' in dir() else None
print("o3d compute_distance", time.time() - t1, None if d1 is None else (d1.max(), d1.mean()))

# split components
multi = trimesh.util.concatenate([mesh, trimesh.creation.box(extents=(2, 2, 2), transform=trimesh.transformations.translation_matrix([50, 0, 0]))])
parts = multi.split(only_watertight=False)
print("split", len(parts), [round(abs(p.volume), 2) for p in parts])
