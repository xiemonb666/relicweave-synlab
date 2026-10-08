"""A12 Blender render worker: JSON config in, scene-linear RGB + exact geometry passes out.

Entry point (a JSON file is the *only* input)::

    & $env:BLENDER_BIN --background --python-exit-code 3 \
        --python blender_scripts/render_worker.py -- <config.json>

Why a subprocess worker
-----------------------
``bpy`` cannot be imported into the project venv (no Windows/py3.12 wheel), so Blender is
driven as an external binary with a frozen JSON contract (``docs/a12/blender_backend.md``).
The worker never guesses: every channel it writes is labelled with the pass it came from,
its unit, its invalid value and its anti-aliasing behaviour.

Outputs written into ``config["output_dir"]``
---------------------------------------------
``rgb_linear.npy`` / ``rgb_linear.exr``
    Scene-linear RGB, float32, read back from a 32-bit float OpenEXR written with
    ``save_as_render=False`` (no view transform is baked in).  Never a PNG only.
``depth_z_mm.npy``
    Camera-frame z in **millimetres** (plan 4.3), float32, ``NaN`` where nothing was hit.
``id_face.npy``
    Per-face research label, int32, ``-1`` = background.  Integer by construction (the
    exact geometry pass uses one sample per pixel inside a 0.01 px filter), never
    interpolated; the fractional values of the anti-aliased pass are kept separately as
    evidence in ``geometry_passes_aa.exr``.
``surface_tag.npy``
    Per-face surface tag, int16, ``-1`` = background, taken from the Cycles **Material
    Index** pass (one material slot per tag).
``object_index.npy``
    Cycles **Object Index** pass value, int32, ``-1`` = background.
``visibility.npy`` / ``occlusion.npy``
    uint8.  ``visibility`` = the primary hit is the target object.  ``occlusion`` = the
    target is hit when only target objects are rendered but not in the full scene, i.e. a
    measured occluder, not a guess.
``uncertain_mask.npy``
    bool: the pixel cannot be assigned to a single surface.  Components (all measured)
    are written to ``channels.json``: anti-aliased geometry mixing, a depth edge inside
    the pixel, and defocus (circle of confusion above the threshold).
``geometry_passes_*.exr``
    Raw pass packs kept for audit; the compositor output packs four **unscaled** float
    channels into one image: ``R`` = Cycles Depth (camera z, mm), ``G`` = Object Index,
    ``B`` = Material Index, ``A`` = the per-face label AOV.  A float32 OpenEXR written
    through this compositor keeps values above 1.0 (measured; a 350 mm depth survives as
    350.0), and the independent ray-cast check fails loudly if that ever changes.
``channels.json`` / ``manifest.json``
    Per-channel semantics and the full run record (argv, samples, elapsed, version,
    device, output hashes, self-checks).

Self-checks (recorded, never silently passed)
---------------------------------------------
* imported face order against the label file's per-face centroids,
* Blender camera model against the project's OpenCV pinhole projection,
* exact-pass depth/face id against an independent ``Scene.ray_cast`` pinhole pass,
* anti-aliased vs exact pass behaviour (the AA evidence of plan 13.2 / R7),
* RGB scale linearity against two emitters of known ratio.

Run standalone::

    & $env:BLENDER_BIN --background --python blender_scripts/render_worker.py -- cfg.json
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import sys
import time
import traceback

import bpy
import numpy as np
from mathutils import Vector

CONFIG_SCHEMA = "rws.blender.render.config/1"
RESULT_PREFIX = "RWS_WORKER_RESULT "

#: The compositor pass pack keeps **raw** float values in the four EXR channels; measured
#: in ``blender_scripts/probe_blender_api5.py`` that a float EXR written through the
#: compositor does not clamp values above 1.0 (a 350 mm depth survives as 350.0), and the
#: independent ray-cast check fails loudly if that ever changes.
PACK = {
    "depth_mm": 1.0,
    "object_index": 1.0,
    "material_index": 1.0,
    "face_id": 1.0,
}

#: Pass names used from the Cycles render layer (Blender 5.2 names).
PASS_IMAGE = "Image"
PASS_DEPTH = "Depth"
PASS_OBJ = "Object Index"
PASS_MAT = "Material Index"
PASS_POSITION = "Position"
#: Shader AOVs carrying the per-face research label and the surface tag.  Measured in
#: ``blender_scripts/probe_blender_api9.py``: in Blender 5.2.2 the Cycles **Material Index**
#: pass returns a constant 0 even when every face has a non-zero material index, and the
#: **Z / Object Index / Position** passes are *not* filter-averaged at all (identical under
#: filter widths 0.01/1.5/4.0 and 1/16/64 samples), while a Shader AOV **is** averaged like
#: RGB.  So the per-face labels are published as Shader AOVs and the Material Index pass is
#: kept only as an audited channel.
AOV_FACE_ID = "rws_face_id"
AOV_TAG = "rws_surface_tag"

ATTR_FACE_ID = "rws_face_label"    # mesh attribute names; deliberately different from the
ATTR_TAG = "rws_tag_label"         # AOV names because Cycles resolves AOV and attribute
ATTR_ALBEDO = "rws_albedo"         # names in the same namespace
ATTR_ROUGH = "rws_roughness"

#: Compositor channel -> render-layer socket, per geometry render.  Only three channels are
#: used per pack: measured in ``_dbg_exr_channels.py`` the fourth (Alpha) channel of the
#: compositor output is the *film* alpha (a constant 1.0), so an AOV written into it is lost.
GEOMETRY_PACKS: dict[str, list[dict[str, str]]] = {
    "geometry_exact": [
        {"Red": PASS_DEPTH, "Green": PASS_OBJ, "Blue": AOV_FACE_ID},
        {"Red": AOV_TAG, "Green": PASS_MAT, "Blue": PASS_DEPTH},
    ],
    "geometry_aa": [
        {"Red": PASS_DEPTH, "Green": PASS_OBJ, "Blue": AOV_FACE_ID},
        {"Red": AOV_TAG, "Green": PASS_MAT, "Blue": PASS_DEPTH},
    ],
    "geometry_targetonly": [
        {"Red": PASS_DEPTH, "Green": PASS_OBJ, "Blue": PASS_MAT},
    ],
}


class WorkerError(RuntimeError):
    """Raised for every failure; the message is printed as a JSON error record."""

    def __init__(self, code: str, message: str, **extra) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.extra = extra


# --------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------
def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def as_mat4(value, name: str) -> np.ndarray:
    arr = np.asarray(value, dtype=np.float64)
    if arr.shape != (4, 4):
        raise WorkerError("SCHEMA_INVALID", f"{name} must be 4x4, got {arr.shape}")
    return arr


def as_mat3(value, name: str) -> np.ndarray:
    arr = np.asarray(value, dtype=np.float64)
    if arr.shape != (3, 3):
        raise WorkerError("SCHEMA_INVALID", f"{name} must be 3x3, got {arr.shape}")
    return arr


def scene_view_layer(scene):
    try:
        vl = bpy.context.view_layer
        if vl is not None and vl.id_data == scene:
            return vl
    except Exception:  # noqa: BLE001
        pass
    return scene.view_layers[0]


def unlink_input(tree, socket) -> None:
    for link in list(socket.links):
        tree.links.remove(link)


# --------------------------------------------------------------------------------------
# scene construction
# --------------------------------------------------------------------------------------
def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = "OPEN_EXR"
    scene.render.image_settings.color_depth = "32"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.image_settings.compression = 15
    try:  # keep the delivered numbers scene-linear
        scene.view_settings.view_transform = "Standard"
        scene.view_settings.look = "None"
    except Exception:  # noqa: BLE001
        pass
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 0.001      # 1 Blender unit == 1 mm
    scene.unit_settings.length_unit = "MILLIMETERS"
    return scene


def import_mesh(path: str, fmt: str, axis: dict, name: str):
    """Import a PLY/OBJ/NPZ mesh and return the new object."""
    fmt = (fmt or os.path.splitext(path)[1].lstrip(".")).lower()
    before = set(bpy.data.objects.keys())
    if fmt == "ply":
        props = bpy.ops.wm.ply_import.get_rna_type().properties.keys()
        kwargs = {"filepath": path}
        if "forward_axis" in props:
            kwargs["forward_axis"] = axis.get("forward", "NEGATIVE_Y")
        if "up_axis" in props:
            kwargs["up_axis"] = axis.get("up", "Z")
        if "global_scale" in props:
            kwargs["global_scale"] = float(axis.get("global_scale", 1.0))
        bpy.ops.wm.ply_import(**kwargs)
    elif fmt in ("obj",):
        props = bpy.ops.wm.obj_import.get_rna_type().properties.keys()
        kwargs = {"filepath": path}
        if "forward_axis" in props:
            kwargs["forward_axis"] = axis.get("forward", "NEGATIVE_Y")
        if "up_axis" in props:
            kwargs["up_axis"] = axis.get("up", "Z")
        if "global_scale" in props:
            kwargs["global_scale"] = float(axis.get("global_scale", 1.0))
        bpy.ops.wm.obj_import(**kwargs)
    elif fmt == "npz":
        data = np.load(path)
        verts = np.asarray(data["vertices"], dtype=np.float64)
        faces = np.asarray(data["faces"], dtype=np.int64)
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata([tuple(v) for v in verts], [], [tuple(int(i) for i in f) for f in faces])
        mesh.validate()
        mesh.update()
        obj = bpy.data.objects.new(name, mesh)
        bpy.context.scene.collection.objects.link(obj)
    else:
        raise WorkerError("SCHEMA_INVALID", f"unsupported mesh format {fmt!r}")
    new = [k for k in bpy.data.objects.keys() if k not in before]
    if len(new) != 1:
        raise WorkerError("MESH_IMPORT_FAILED",
                          f"importing {path} created {len(new)} objects ({new})")
    obj = bpy.data.objects[new[0]]
    obj.name = name
    return obj


def set_face_attributes(mesh, labels: dict, name: str) -> dict:
    """Per-face integer/float attributes; verified against the label file."""
    faces = np.asarray(labels["faces"], dtype=np.int64)
    n_blender = len(mesh.polygons)
    if n_blender != faces.shape[0]:
        raise WorkerError("FACE_COUNT_MISMATCH",
                          f"{name}: Blender imported {n_blender} faces, labels have "
                          f"{faces.shape[0]}")
    coords = np.empty(len(mesh.vertices) * 3, dtype=np.float64)
    mesh.vertices.foreach_get("co", coords)
    coords = coords.reshape(-1, 3)
    tri = np.empty(n_blender * 3, dtype=np.int64)
    mesh.polygons.foreach_get("vertices", tri)
    tri = tri.reshape(-1, 3)
    if tri.shape[1] != 3:
        raise WorkerError("SCHEMA_INVALID",
                          f"{name}: expected triangles, imported faces have "
                          f"{tri.shape[1]} vertices")
    centroids = coords[tri].mean(axis=1)
    expected = np.asarray(labels["face_centroid_mm"], dtype=np.float64)
    order_err = float(np.abs(centroids - expected).max()) if expected.shape == centroids.shape \
        else float("inf")
    if not np.isfinite(order_err):
        raise WorkerError("FACE_ORDER_MISMATCH", f"{name}: centroid shapes differ")
    tol = float(labels.get("face_order_tol_mm", 1e-2))
    if order_err > tol:
        raise WorkerError(
            "FACE_ORDER_MISMATCH",
            f"{name}: imported face order does not match the label file "
            f"(max centroid error {order_err:.6g} mm > {tol} mm); reface labelling refused",
            max_centroid_error_mm=order_err,
        )

    face_id = np.asarray(labels["face_id"], dtype=np.int32)
    surface_tag = np.asarray(labels["surface_tag"], dtype=np.int16)
    albedo = np.asarray(labels["albedo"], dtype=np.float32).reshape(-1, 3)
    roughness = np.asarray(labels["roughness"], dtype=np.float32).reshape(-1)

    # The per-face label is stored as a FLOAT attribute: Cycles samples float face
    # attributes reliably through the Attribute node and float32 represents every integer
    # exactly up to 2**24, so the label stays an exact integer.
    attr = mesh.attributes.new(name=ATTR_FACE_ID, type="FLOAT", domain="FACE")
    attr.data.foreach_set("value", face_id.astype(np.float32))
    attr = mesh.attributes.new(name=ATTR_TAG, type="FLOAT", domain="FACE")
    attr.data.foreach_set("value", surface_tag.astype(np.float32))
    rgba = np.concatenate([np.clip(albedo, 0.0, 1.0),
                           np.ones((albedo.shape[0], 1), dtype=np.float32)], axis=1)
    attr = mesh.attributes.new(name=ATTR_ALBEDO, type="FLOAT_COLOR", domain="FACE")
    attr.data.foreach_set("color", rgba.astype(np.float32).ravel())
    attr = mesh.attributes.new(name=ATTR_ROUGH, type="FLOAT", domain="FACE")
    attr.data.foreach_set("value", np.clip(roughness, 0.0, 1.0).astype(np.float32))
    mesh.update()

    for poly in mesh.polygons:
        poly.material_index = int(surface_tag[poly.index])
    return {"n_faces": int(n_blender), "max_centroid_error_mm": order_err,
            "face_id_unique": int(np.unique(face_id).size),
            "surface_tags": sorted(int(v) for v in np.unique(surface_tag))}


def assign_material_indices(mesh, surface_tag: np.ndarray) -> None:
    """Material slot = tag, assigned **after** the slots exist (Blender clamps otherwise)."""
    if surface_tag.size and int(np.max(surface_tag)) >= len(mesh.materials):
        raise WorkerError("SCHEMA_INVALID",
                          "material slots were not created before assigning material indices")
    for poly in mesh.polygons:
        poly.material_index = int(surface_tag[poly.index])


def make_tag_materials(mesh, n_tags: int) -> None:
    """One material slot per surface tag, plus the two per-face Shader AOVs.

    The slot index equals the tag, so the Cycles Material Index pass *would* carry the tag;
    it is kept for audit but the delivered tag comes from the AOV (see GEOMETRY_PACKS).
    """
    for tag in range(n_tags):
        mat = bpy.data.materials.new(f"rws_tag_{tag}")
        mat.use_nodes = True
        nt = mat.node_tree
        for node in list(nt.nodes):
            nt.nodes.remove(node)
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
        alb = nt.nodes.new("ShaderNodeAttribute")
        alb.attribute_type = "GEOMETRY"
        alb.attribute_name = ATTR_ALBEDO
        rgh = nt.nodes.new("ShaderNodeAttribute")
        rgh.attribute_type = "GEOMETRY"
        rgh.attribute_name = ATTR_ROUGH
        aov = nt.nodes.new("ShaderNodeOutputAOV")
        aov.aov_name = AOV_FACE_ID
        fid = nt.nodes.new("ShaderNodeAttribute")
        fid.attribute_type = "GEOMETRY"
        fid.attribute_name = ATTR_FACE_ID
        aov_tag = nt.nodes.new("ShaderNodeOutputAOV")
        aov_tag.aov_name = AOV_TAG
        tag_attr = nt.nodes.new("ShaderNodeAttribute")
        tag_attr.attribute_type = "GEOMETRY"
        tag_attr.attribute_name = ATTR_TAG
        nt.links.new(alb.outputs["Color"], bsdf.inputs["Base Color"])
        nt.links.new(rgh.outputs["Fac"], bsdf.inputs["Roughness"])
        nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
        nt.links.new(fid.outputs["Fac"], aov.inputs["Value"])
        nt.links.new(tag_attr.outputs["Fac"], aov_tag.inputs["Value"])
        try:
            bsdf.inputs["Specular IOR Level"].default_value = 0.2
        except Exception:  # noqa: BLE001 - name differs across versions
            pass
        mesh.materials.append(mat)


def make_plain_material(obj, albedo=(0.45, 0.45, 0.45), roughness=0.7,
                        face_label: float = -1.0, tag: float = -1.0) -> None:
    """Material for an object without a label file; both AOVs get declared constants."""
    mat = bpy.data.materials.new(f"rws_plain_{obj.name}")
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Base Color"].default_value = (*albedo, 1.0)
    bsdf.inputs["Roughness"].default_value = float(roughness)
    aov = nt.nodes.new("ShaderNodeOutputAOV")
    aov.aov_name = AOV_FACE_ID
    aov.inputs["Value"].default_value = float(face_label)
    aov_tag = nt.nodes.new("ShaderNodeOutputAOV")
    aov_tag.aov_name = AOV_TAG
    aov_tag.inputs["Value"].default_value = float(tag)
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    for poly in obj.data.polygons:
        poly.material_index = 0


def setup_camera(scene, cam_cfg: dict):
    """Blender camera from the project's OpenCV K/T_WC (both frames are Z-up, right-handed).

    Blender's own projection function is used to *calibrate* the two conventions that are
    easy to get silently wrong (which corner ``world_to_camera_view`` measures from, and
    the sign/scale of ``shift_x``/``shift_y``); the calibration is then verified against
    the project's pinhole formula on the real mesh vertices by :func:`camera_selfcheck`.
    """
    W, H = int(cam_cfg["image_size"][0]), int(cam_cfg["image_size"][1])
    K = as_mat3(cam_cfg["K"], "camera.K")
    T_WC = as_mat4(cam_cfg["T_WC"], "camera.T_WC")
    fx, fy = float(K[0, 0]), float(K[1, 1])
    cx, cy = float(K[0, 2]), float(K[1, 2])
    if abs(fx - fy) > 1e-9 * max(fx, 1.0):
        raise WorkerError("SCHEMA_INVALID",
                          f"Blender pinhole camera needs fx == fy, got {fx} vs {fy}")
    sensor = 36.0
    cam_data = bpy.data.cameras.new("rws_cam")
    cam_data.type = "PERSP"
    cam_data.sensor_fit = "HORIZONTAL"
    cam_data.sensor_width = sensor
    cam_data.lens = fx * sensor / float(W)
    cam_data.shift_x = 0.0
    cam_data.shift_y = 0.0
    cam_data.clip_start = max(float(cam_cfg.get("near_mm", 1.0)), 1e-3)
    cam_data.clip_end = min(max(float(cam_cfg.get("far_mm", 1.0e6)), 1.0), 1.0e7)
    cam = bpy.data.objects.new("rws_cam", cam_data)
    scene.collection.objects.link(cam)
    # T_CB = diag(1,-1,-1): OpenCV camera (right, down, fwd) -> Blender camera (right, up, back)
    T_CB = np.eye(4)
    T_CB[:3, :3] = np.diag([1.0, -1.0, -1.0])
    T_WB = T_WC @ T_CB
    cam.matrix_world = _to_blender_matrix(T_WB)
    scene.camera = cam
    report = {"fx": fx, "fy": fy, "cx": cx, "cy": cy, "image_size": [W, H],
              "T_WC": T_WC.tolist(), "lens_mm": cam_data.lens,
              "sensor_width_mm": sensor, "clip_mm": [cam_data.clip_start,
                                                     cam_data.clip_end]}
    report.update(calibrate_camera(scene, cam, cam_cfg))
    return cam, report


def _to_blender_matrix(T: np.ndarray):
    from mathutils import Matrix

    return Matrix([[float(T[i][j]) for j in range(4)] for i in range(4)])


def _corner_projection(scene, cam, points_mm: np.ndarray, cam_cfg: dict,
                       v_from_bottom: bool) -> np.ndarray:
    """Corner-coordinate projection (0,0 = top-left image corner) of world points.

    ``v_from_bottom`` is the *measured* convention of ``world_to_camera_view`` (its ``v``
    grows upwards); when true the row is flipped so row 0 is the top of the image.
    """
    from bpy_extras.object_utils import world_to_camera_view

    W, H = int(cam_cfg["image_size"][0]), int(cam_cfg["image_size"][1])
    pts = np.asarray(points_mm, dtype=np.float64).reshape(-1, 3)
    out = np.empty((pts.shape[0], 2), dtype=np.float64)
    for i, p in enumerate(pts):
        uv = world_to_camera_view(scene, cam, Vector((float(p[0]), float(p[1]), float(p[2]))))
        out[i, 0] = float(uv.x) * W
        v = float(uv.y) * H
        out[i, 1] = (H - v) if v_from_bottom else v
    return out


def calibrate_camera(scene, cam, cam_cfg: dict) -> dict:
    """Measure Blender's projection conventions and solve the principal-point shift."""
    K = as_mat3(cam_cfg["K"], "camera.K")
    T_WC = as_mat4(cam_cfg["T_WC"], "camera.T_WC")
    W, H = int(cam_cfg["image_size"][0]), int(cam_cfg["image_size"][1])
    R, C = T_WC[:3, :3], T_WC[:3, 3]
    depth = float(K[0, 0]) * 4.0
    p_axis = C + R[:, 2] * depth
    p_down = p_axis + R[:, 1] * (depth * 0.1)      # +y_cam = down in the image
    p_right = p_axis + R[:, 0] * (depth * 0.1)     # +x_cam = right in the image
    probe = np.stack([p_axis, p_down, p_right])
    raw = _corner_projection(scene, cam, probe, cam_cfg, v_from_bottom=False)
    v_from_bottom = bool(raw[1, 1] < raw[0, 1])
    right_up = bool(raw[2, 0] > raw[0, 0])

    def corner(points):
        q = _corner_projection(scene, cam, points, cam_cfg, v_from_bottom=v_from_bottom)
        if not right_up:                       # measured, not assumed
            q[:, 0] = W - q[:, 0]
        return q

    cam.data.shift_x = 0.0
    cam.data.shift_y = 0.0
    c0 = corner(probe)[0]
    step = 0.05
    cam.data.shift_x = step
    cam.data.shift_y = step
    c1 = corner(probe)[0]
    cam.data.shift_x = 0.0
    cam.data.shift_y = 0.0
    kx = (float(c1[0]) - float(c0[0])) / step
    ky = (float(c1[1]) - float(c0[1])) / step
    if abs(kx) < 1e-6 or abs(ky) < 1e-6:
        raise WorkerError("CAMERA_CHECK_FAILED",
                          f"principal-point shift has no effect (kx={kx}, ky={ky})")
    target = np.array([float(K[0, 2]) + 0.5, float(K[1, 2]) + 0.5])   # pixel centre -> corner
    cam.data.shift_x = float((target[0] - c0[0]) / kx)
    cam.data.shift_y = float((target[1] - c0[1]) / ky)
    after = corner(probe)[0]
    return {"v_axis_measured_from_bottom": bool(v_from_bottom),
            "u_increases_to_the_right": right_up,
            "shift_px_per_unit": [kx, ky], "shift_x": float(cam.data.shift_x),
            "shift_y": float(cam.data.shift_y),
            "principal_point_px": [target[0] - 0.5, target[1] - 0.5],
            "axis_point_corner_px": [float(after[0]), float(after[1])],
            "convention": "project pixel-centre index (i,j) == blender corner (i+0.5, j+0.5)"}


def camera_selfcheck(scene, cam, points_mm: np.ndarray, cam_cfg: dict, tol_px: float) -> dict:
    """Compare Blender's projection of known world points with the project's pinhole."""
    K = as_mat3(cam_cfg["K"], "camera.K")
    T_WC = as_mat4(cam_cfg["T_WC"], "camera.T_WC")
    W, H = int(cam_cfg["image_size"][0]), int(cam_cfg["image_size"][1])
    R = T_WC[:3, :3]
    C = T_WC[:3, 3]
    pts = np.asarray(points_mm, dtype=np.float64)
    cam_pts = (pts - C[None, :]) @ R                      # OpenCV camera coords
    z = cam_pts[:, 2]
    front = z > 1e-6
    if not front.any():
        raise WorkerError("CAMERA_CHECK_FAILED", "no sample point is in front of the camera")
    u_ref = K[0, 0] * cam_pts[front, 0] / z[front] + K[0, 2] + 0.5    # corner coordinates
    v_ref = K[1, 1] * cam_pts[front, 1] / z[front] + K[1, 2] + 0.5
    # flip_v is the measured convention from setup_camera; re-measure it here so the check
    # does not depend on state carried between the two functions
    axis = C + R[:, 2] * 1000.0
    probe_pts = np.stack([axis, axis + R[:, 1] * 100.0])
    raw = _corner_projection(scene, cam, probe_pts, cam_cfg, v_from_bottom=False)
    v_from_bottom = bool(raw[1, 1] < raw[0, 1])
    got = _corner_projection(scene, cam, pts[front], cam_cfg, v_from_bottom=v_from_bottom)
    du = got[:, 0] - u_ref
    dv = got[:, 1] - v_ref
    err = float(max(np.abs(du).max(), np.abs(dv).max()))
    info = {"n_points": int(front.sum()), "max_uv_error_px": err, "tolerance_px": tol_px,
            "du_px": float(np.abs(du).max()), "dv_px": float(np.abs(dv).max()),
            "convention": "project pixel-centre index (i,j) == blender corner (i+0.5, j+0.5)",
            "v_axis_measured_from_bottom": bool(v_from_bottom)}
    if err > tol_px:
        raise WorkerError(
            "CAMERA_CHECK_FAILED",
            f"Blender camera projection disagrees with the project pinhole by {err:.4f} px "
            f"(tolerance {tol_px} px)", camera_check=info)
    return info


def setup_lighting(scene, light_cfg: dict, background_linear):
    """Sun + decoupled environment/background (camera rays see the background only)."""
    direction = np.asarray(light_cfg["direction"], dtype=np.float64).reshape(3)
    n = float(np.linalg.norm(direction))
    if n < 1e-12:
        raise WorkerError("SCHEMA_INVALID", "light.direction is degenerate")
    direction = direction / n
    color = np.asarray(light_cfg["color"], dtype=np.float64).reshape(3)
    ambient = np.asarray(light_cfg["ambient"], dtype=np.float64).reshape(3)

    # Sun travelling along `direction` points its -Z axis that way.
    light_data = bpy.data.lights.new("rws_sun", type="SUN")
    peak = float(np.max(color)) if float(np.max(color)) > 0 else 1.0
    light_data.color = tuple((color / peak).tolist())
    # Cycles sun strength is irradiance (W/m^2); a Lambertian surface returns rho*E*cos/pi,
    # which matches the software model's albedo*(ambient + color*cos) up to the 1/pi factor.
    light_data.energy = float(peak) * math.pi
    light_data.angle = 0.0
    sun = bpy.data.objects.new("rws_sun", light_data)
    scene.collection.objects.link(sun)
    # -Z of the light must equal `direction`: build a basis with -Z along direction.
    z_axis = -direction
    up = np.array([0.0, 0.0, 1.0])
    if abs(float(np.dot(z_axis, up))) > 0.999:
        up = np.array([0.0, 1.0, 0.0])
    x_axis = np.cross(up, z_axis)
    x_axis /= np.linalg.norm(x_axis)
    y_axis = np.cross(z_axis, x_axis)
    T = np.eye(4)
    T[:3, 0], T[:3, 1], T[:3, 2] = x_axis, y_axis, z_axis
    T[:3, 3] = -direction * 1.0e4        # far away; only the direction matters for a sun
    sun.matrix_world = _to_blender_matrix(T)

    world = bpy.data.worlds.new("rws_world")
    scene.world = world
    world.use_nodes = True
    nt = world.node_tree
    for node in list(nt.nodes):
        nt.nodes.remove(node)
    out = nt.nodes.new("ShaderNodeOutputWorld")
    mix = nt.nodes.new("ShaderNodeMixShader")
    bg_env = nt.nodes.new("ShaderNodeBackground")
    bg_cam = nt.nodes.new("ShaderNodeBackground")
    lp = nt.nodes.new("ShaderNodeLightPath")
    bg_env.inputs[0].default_value = (*[float(v) for v in ambient], 1.0)
    bg_cam.inputs[0].default_value = (*[float(v) for v in background_linear], 1.0)
    nt.links.new(lp.outputs["Is Camera Ray"], mix.inputs[0])
    nt.links.new(bg_env.outputs["Background"], mix.inputs[1])
    nt.links.new(bg_cam.outputs["Background"], mix.inputs[2])
    nt.links.new(mix.outputs["Shader"], out.inputs["Surface"])
    return {"sun_energy_irradiance": light_data.energy,
            "sun_color_normalised": list(light_data.color),
            "direction_travel": direction.tolist(),
            "ambient_linear": ambient.tolist(),
            "background_linear": [float(v) for v in background_linear],
            "world_model": "LIGHT_PATH_MIX(camera=background, other=ambient)"}


def enable_passes(scene):
    """Enable the render passes and register both Shader AOVs (before materials exist)."""
    vl = scene_view_layer(scene)
    for flag in ("use_pass_combined", "use_pass_z", "use_pass_position",
                 "use_pass_object_index", "use_pass_material_index",
                 "use_pass_ambient_occlusion"):
        if hasattr(vl, flag):
            setattr(vl, flag, True)
    for name in (AOV_FACE_ID, AOV_TAG):
        if not any(existing.name == name for existing in vl.aovs):
            aov = vl.aovs.add()
            aov.name = name
            aov.type = "VALUE"
    return vl


def build_compositor(scene):
    """Render-layer node + pack/inspect nodes inside a compositor node group.

    Blender 5.2 has no ``CompositorNodeComposite``; the node group's interface output is
    the compositor result (measured in ``blender_scripts/probe_blender_api7.py``).
    """
    tree = bpy.data.node_groups.new(name="rws_compositor", type="CompositorNodeTree")
    out_socket = tree.interface.new_socket("Image", in_out="OUTPUT",
                                           socket_type="NodeSocketColor")
    group_out = tree.nodes.new("NodeGroupOutput")
    rl = tree.nodes.new("CompositorNodeRLayers")
    packs = []
    for _ in range(2):
        pack = tree.nodes.new("CompositorNodeCombineColor")
        pack.mode = "RGB"
        packs.append(pack)
    missing = [name for name in (PASS_DEPTH, PASS_OBJ, PASS_MAT, PASS_IMAGE,
                                 AOV_FACE_ID, AOV_TAG)
               if name not in rl.outputs]
    if missing:
        raise WorkerError("PASS_UNAVAILABLE",
                          f"render layer does not expose {missing} in this Blender build")
    scene.compositing_node_group = tree
    return {"tree": tree, "rl": rl, "packs": packs, "group_out": group_out,
            "out_socket": out_socket, "missing": missing}


def wire_image(comp) -> None:
    tree, rl, out = comp["tree"], comp["rl"], comp["group_out"]
    unlink_input(tree, out.inputs["Image"])
    tree.links.new(rl.outputs[PASS_IMAGE], out.inputs["Image"])


def wire_geometry(comp, mapping: dict[str, str], pack_index: int = 0) -> None:
    """Pack three raw geometry channels of one render into RGB.

    The channels are written **unscaled** (depth in mm, object index, face label, tag); a
    float32 OpenEXR written through this compositor keeps values above 1.0 (measured), and
    the independent ray-cast check in the manifest fails loudly if that ever stops being
    true.  The Alpha channel is deliberately unused: it is the film alpha, not the pack.
    """
    tree, rl, out = comp["tree"], comp["rl"], comp["group_out"]
    pack = comp["packs"][pack_index]
    for dst_name, src_name in mapping.items():
        dst = pack.inputs[dst_name]
        unlink_input(tree, dst)
        tree.links.new(rl.outputs[src_name], dst)
    unlink_input(tree, out.inputs["Image"])
    tree.links.new(pack.outputs["Image"], out.inputs["Image"])


def render_to(scene, filepath_stem: str) -> str:
    scene.render.filepath = filepath_stem
    bpy.ops.render.render(write_still=True)
    path = filepath_stem + ".exr"
    if not os.path.exists(path):
        raise WorkerError("RENDER_OUTPUT_MISSING", f"expected render output {path}")
    return path


def load_exr(path: str, non_color: bool = True, keep: bool = False):
    img = bpy.data.images.load(path, check_existing=False)
    try:
        if non_color:
            img.colorspace_settings.name = "Non-Color"
        n = len(img.pixels)
        if n == 0:
            raise WorkerError("EXR_READBACK_FAILED",
                              f"Blender could not decode {path} (empty image buffer)")
        buf = np.empty(n, dtype=np.float32)
        img.pixels.foreach_get(buf)
        ch = int(img.channels)
        arr = buf.reshape(img.size[1], img.size[0], ch)
        arr = np.flipud(arr)              # Blender image buffers are bottom-up
        info = {"size": [int(img.size[0]), int(img.size[1])], "channels": ch,
                "colorspace": img.colorspace_settings.name, "dtype": "float32",
                "row_order": "flipped_from_blender_bottom_up"}
    finally:
        if not keep:
            bpy.data.images.remove(img)
    return arr, info


def write_npy(path: str, arr: np.ndarray) -> None:
    np.save(path, arr)


def write_preview_png(path: str, rgb: np.ndarray, alpha: np.ndarray | None = None) -> None:
    """8-bit sRGB preview; clearly not a data channel."""
    data = np.clip(np.asarray(rgb, dtype=np.float32), 0.0, 1.0)
    enc = np.where(data <= 0.0031308, data * 12.92,
                   1.055 * np.power(np.maximum(data, 0.0), 1.0 / 2.4) - 0.055)
    enc = np.clip(enc, 0.0, 1.0)
    if alpha is None:
        a = np.ones((*enc.shape[:2], 1), dtype=np.float32)
    else:
        a = np.asarray(alpha, dtype=np.float32).reshape(*enc.shape[:2], 1)
    rgba = np.concatenate([enc, a], axis=2)
    img = bpy.data.images.new("rws_preview", width=enc.shape[1], height=enc.shape[0],
                              alpha=False, float_buffer=False)
    img.pixels.foreach_set(np.flipud(rgba).ravel())     # back to bottom-up
    img.filepath_raw = path
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)


def write_scalar_png(path: str, values: np.ndarray, valid: np.ndarray | None = None,
                     mask_alpha: np.ndarray | None = None) -> None:
    """Greyscale preview of a scalar channel, normalised on its valid values.

    ``mask_alpha`` marks overlay pixels (e.g. the uncertain mask) in red.
    """
    v = np.asarray(values, dtype=np.float32)
    m = np.isfinite(v) if valid is None else np.asarray(valid, dtype=bool)
    out = np.zeros((*v.shape, 3), dtype=np.float32)
    if m.any():
        lo = float(np.percentile(v[m], 1.0))
        hi = float(np.percentile(v[m], 99.0))
        rng = max(hi - lo, 1e-9)
        norm = np.clip((np.nan_to_num(v, nan=lo) - lo) / rng, 0.0, 1.0)
        out[..., 0] = norm
        out[..., 1] = norm
        out[..., 2] = norm
    if mask_alpha is not None:
        ov = np.asarray(mask_alpha, dtype=bool)
        out[ov] = np.array([1.0, 0.15, 0.15], dtype=np.float32)
    write_preview_png(path, out)


# --------------------------------------------------------------------------------------
# assembly
# --------------------------------------------------------------------------------------
def circle_of_confusion_px(depth_mm: np.ndarray, focus_distance_mm: float, f_number: float,
                           f_px: float) -> np.ndarray:
    z = np.asarray(depth_mm, dtype=np.float64)
    if f_px <= 0 or f_number <= 0:
        return np.zeros_like(z)
    denom = np.maximum(z, 1e-6)
    coc = np.abs(f_px ** 2 / (f_number * denom)
                 * (z - focus_distance_mm) / max(focus_distance_mm, 1e-6))
    return np.nan_to_num(coc, nan=0.0, posinf=1e6, neginf=0.0)


def dilate(mask: np.ndarray, radius: int) -> np.ndarray:
    out = np.asarray(mask, dtype=bool).copy()
    for _ in range(max(int(radius), 0)):
        grown = out.copy()
        grown[1:, :] |= out[:-1, :]
        grown[:-1, :] |= out[1:, :]
        grown[:, 1:] |= out[:, :-1]
        grown[:, :-1] |= out[:, 1:]
        out = grown
    return out


def raycast_check(scene, cam_cfg: dict, depth_z: np.ndarray, face_id: np.ndarray,
                  object_index: np.ndarray, target_pass_index: int, n_samples: int,
                  depth_tol_mm: float, seed: int,
                  label_arrays: dict[str, np.ndarray] | None = None) -> dict:
    """Independent pinhole ray pass (plan 13.2) against the exact Cycles geometry pass.

    The research label is a *global* face id while ``Scene.ray_cast`` returns the face index
    inside the hit object, so ``label_arrays`` (object name -> per-face label array) is used
    to map the hit before comparing.
    """
    K = as_mat3(cam_cfg["K"], "camera.K")
    T_WC = as_mat4(cam_cfg["T_WC"], "camera.T_WC")
    R, C = T_WC[:3, :3], T_WC[:3, 3]
    H, W = depth_z.shape
    rng = np.random.Generator(np.random.PCG64(np.uint64(seed)))
    n = int(min(n_samples, W * H))
    ys = rng.integers(0, H, size=n)
    xs = rng.integers(0, W, size=n)
    dg = bpy.context.evaluated_depsgraph_get()
    dl_interior, dl_boundary, di_interior, di_boundary, do_mismatch = [], [], [], [], 0
    hit = 0
    nan_depth = 0
    boundary_samples = 0
    for x, y in zip(xs.tolist(), ys.tolist()):
        u, v = float(x) + 0.5, float(y) + 0.5
        d_cam = np.array([(u - K[0, 2]) / K[0, 0], (v - K[1, 2]) / K[1, 1], 1.0])
        d_world = R @ d_cam
        d_world = d_world / np.linalg.norm(d_world)
        res, loc, _nrm, fidx, obj, _mat = scene.ray_cast(
            dg, Vector(tuple(C.tolist())), Vector(tuple(d_world.tolist())))
        if not res:
            continue
        hit += 1
        p = np.array(loc, dtype=np.float64)
        z = float((p - C) @ R[:, 2])
        # a sample whose 3x3 neighbourhood is not one single (object, face label) pair lies on
        # a geometric boundary; a pixel-centre ray and a filtered render may legitimately
        # disagree there (this includes label boundaries between coplanar faces of one object)
        y0, y1 = max(y - 1, 0), min(y + 2, H)
        x0, x1 = max(x - 1, 0), min(x + 2, W)
        patch_obj = object_index[y0:y1, x0:x1]
        patch_face = face_id[y0:y1, x0:x1]
        is_boundary = bool(patch_obj.min() != patch_obj.max()
                           or patch_face.min() != patch_face.max())
        if is_boundary:
            boundary_samples += 1
        rendered_depth = float(depth_z[y, x])
        if np.isfinite(rendered_depth):
            (dl_boundary if is_boundary else dl_interior).append(abs(z - rendered_depth))
        else:
            nan_depth += 1
        expected_label = None
        if label_arrays is not None and obj is not None and obj.name in label_arrays:
            labels = label_arrays[obj.name]
            if 0 <= int(fidx) < labels.shape[0]:
                expected_label = int(labels[int(fidx)])
        mismatch = int(getattr(obj, "pass_index", -1)) != int(object_index[y, x])
        do_mismatch += int(mismatch)
        if expected_label is not None and mismatch == 0:
            (di_boundary if is_boundary else di_interior).append(
                expected_label != int(face_id[y, x]))
    if hit == 0:
        return {"n_rays": n, "hits": 0, "status": "NO_HIT"}
    di = np.asarray(di_interior, dtype=bool)
    dli = np.asarray(dl_interior) if dl_interior else np.zeros(0)
    dlb = np.asarray(dl_boundary) if dl_boundary else np.zeros(0)
    ok = bool(dli.size and float(dli.max()) <= depth_tol_mm and not di.any())
    return {"n_rays": n, "hits": int(hit),
            "boundary_samples": int(boundary_samples),
            "interior_samples": int(hit - boundary_samples),
            "depth_compared_interior_px": int(dli.size),
            "depth_compared_boundary_px": int(dlb.size),
            "depth_unavailable_px": int(nan_depth),
            "max_depth_error_interior_mm": float(dli.max()) if dli.size else None,
            "max_depth_error_boundary_mm": float(dlb.max()) if dlb.size else None,
            "mean_depth_error_interior_mm": float(dli.mean()) if dli.size else None,
            "depth_tolerance_mm": float(depth_tol_mm),
            "face_id_mismatch_interior": int(np.count_nonzero(di)),
            "face_id_compared_interior": int(di.size),
            "face_id_mismatch_boundary": int(np.count_nonzero(di_boundary)),
            "object_index_mismatch": int(do_mismatch),
            "target_pass_index": int(target_pass_index),
            "label_mapping": "ray-cast face index -> per-object research label array",
            "note": ("interior = the 3x3 neighbourhood of the rendered object index is a "
                     "single object; boundary samples may legitimately disagree between a "
                     "pixel-centre ray and a filtered render"),
            "status": "OK" if ok else
                      ("DEPTH_MISMATCH" if dli.size and float(dli.max()) > depth_tol_mm
                       else "FACE_LABEL_MISMATCH")}


# --------------------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------------------
def run(cfg: dict) -> dict:
    t_start = time.time()
    if cfg.get("schema") != CONFIG_SCHEMA:
        raise WorkerError("SCHEMA_INVALID",
                          f"config schema {cfg.get('schema')!r} != {CONFIG_SCHEMA!r}")
    out_dir = os.path.abspath(cfg["output_dir"])
    os.makedirs(out_dir, exist_ok=True)
    scene = reset_scene()
    W, H = int(cfg["resolution"][0]), int(cfg["resolution"][1])
    scene.render.resolution_x, scene.render.resolution_y = W, H

    rcfg = dict(cfg.get("render", {}))
    samples = int(rcfg.get("samples", 64))
    filter_width = float(rcfg.get("filter_width", 1.5))
    geom_samples = int(rcfg.get("geometry_samples", 1))
    geom_filter = float(rcfg.get("geometry_filter_width", 0.01))
    aa_geom_samples = int(rcfg.get("aa_geometry_samples", samples))
    max_bounces = int(rcfg.get("max_bounces", 4))
    denoise = bool(rcfg.get("denoise", False))
    denoiser = str(rcfg.get("denoiser", "OPENIMAGEDENOISE"))
    seed = int(rcfg.get("seed", 0))
    device = str(rcfg.get("device", "CPU")).upper()
    geom_bounces = int(rcfg.get("geometry_max_bounces", 0))

    scene.cycles.device = device if device in ("CPU", "GPU") else "CPU"
    scene.cycles.seed = seed
    scene.cycles.use_animated_seed = False
    scene.cycles.use_adaptive_sampling = bool(rcfg.get("adaptive_sampling", True))
    if hasattr(scene.cycles, "use_light_tree"):
        scene.cycles.use_light_tree = bool(rcfg.get("light_tree", True))

    # Render layers, passes and the Shader AOV must exist *before* the materials are built:
    # a ShaderNodeOutputAOV whose AOV is not registered yet silently keeps its default value
    # (measured: the face-label pass read a constant 1.0).
    vl = enable_passes(scene)
    comp = build_compositor(scene)

    # ------------------------------------------------------------------ objects
    obj_specs = list(cfg["objects"])
    if not obj_specs:
        raise WorkerError("SCHEMA_INVALID", "config has no objects")
    target_pass_index = None
    objs = []
    object_report = []
    for spec in obj_specs:
        name = str(spec["name"])
        obj = import_mesh(str(spec["mesh"]), str(spec.get("mesh_format", "")),
                          dict(spec.get("axis", {})), name)
        labels = dict(np.load(str(spec["labels"]), allow_pickle=False)) \
            if spec.get("labels") else None
        if labels is not None:
            labels["face_order_tol_mm"] = float(cfg.get("checks", {})
                                                .get("face_order_tol_mm", 1e-2))
            rep = set_face_attributes(obj.data, labels, name)
            n_tags = int(max(rep["surface_tags"]) + 1) if rep["surface_tags"] else 1
            make_tag_materials(obj.data, n_tags)
            assign_material_indices(obj.data,
                                    np.asarray(labels["surface_tag"], dtype=np.int16))
            rep["material_slots"] = n_tags
            # kept in memory only (popped before the manifest is serialised) so that the
            # ray-cast check can map an object-local face index to the research label
            rep["_face_id_labels"] = np.asarray(labels["face_id"], dtype=np.int64)
        else:
            make_plain_material(obj)
            rep = {"n_faces": int(len(obj.data.polygons)), "material_slots": 1,
                   "surface_tags": [0]}
            rep["_face_id_labels"] = np.full(len(obj.data.polygons), -1, dtype=np.int64)
        pose = spec.get("object_pose_T_WO")
        if pose is not None:
            obj.matrix_world = _to_blender_matrix(as_mat4(pose, f"{name}.object_pose_T_WO"))
        obj.pass_index = int(spec.get("pass_index", 1))
        obj.hide_render = False
        rep.update({"name": name, "pass_index": int(obj.pass_index),
                    "is_target": bool(spec.get("is_target", False)),
                    "mesh": os.path.abspath(str(spec["mesh"])),
                    "mesh_sha256": sha256_file(str(spec["mesh"]))})
        if rep["is_target"]:
            if target_pass_index is not None:
                raise WorkerError("SCHEMA_INVALID", "more than one target object")
            target_pass_index = int(obj.pass_index)
        object_report.append(rep)
        objs.append(obj)
    if target_pass_index is None:
        raise WorkerError("SCHEMA_INVALID", "no object is marked is_target")
    # ------------------------------------------------------------------ camera / light
    cam_cfg = dict(cfg["camera"])
    cam, cam_report = setup_camera(scene, cam_cfg)
    checks_cfg = dict(cfg.get("checks", {}))
    # camera self-check on the target's vertices (subsampled)
    tv = np.empty(len(objs[0].data.vertices) * 3, dtype=np.float64)
    objs[0].data.vertices.foreach_get("co", tv)
    tv = tv.reshape(-1, 3)[:: max(len(objs[0].data.vertices) // 64, 1)]
    cam_report["selfcheck"] = camera_selfcheck(
        scene, cam, tv, cam_cfg, float(checks_cfg.get("camera_uv_tol_px", 0.1)))
    light_report = setup_lighting(scene, dict(cfg["light"]),
                                  cfg.get("background_linear", [0.02, 0.02, 0.025]))

    # ------------------------------------------------------------------ render state
    depth_pack_range_mm = float(cfg.get("depth_pack_range_mm", 0.0)) or \
        float(checks_cfg.get("depth_pack_range_mm", 0.0)) or 100000.0
    pack_report = {"scaling": "NONE (raw pass values)",
                   "packs": {tag: packs for tag, packs in GEOMETRY_PACKS.items()},
                   "alpha_channel": "unused: the compositor output alpha is the film alpha "
                                    "(a constant 1.0), so each 3-channel pack is a separate "
                                    "render",
                   "depth_range_reference_mm": depth_pack_range_mm,
                   "note": "every geometry channel is written unscaled into a float32 "
                           "OpenEXR; the ray-cast cross-check fails if a value were clamped"}

    renders = []

    def do_render(tag: str, *, samples_: int, filter_: float, denoise_: bool,
                  bounces: int, kind: str, pack_index: int = 0) -> str:
        scene.cycles.samples = int(samples_)
        scene.cycles.filter_width = float(filter_)
        scene.cycles.max_bounces = int(bounces)
        scene.cycles.use_denoising = bool(denoise_)
        if denoise_:
            try:
                scene.cycles.denoiser = denoiser
            except Exception:  # noqa: BLE001
                pass
        if kind == "image":
            wire_image(comp)
        else:
            wire_geometry(comp, GEOMETRY_PACKS[tag][pack_index], pack_index)
        t0 = time.time()
        stem = f"pass_{tag}" if kind == "image" else f"pass_{tag}_{'ab'[pack_index]}"
        path = render_to(scene, os.path.join(out_dir, stem))
        dt = time.time() - t0
        renders.append({"tag": tag, "pack_index": int(pack_index), "kind": kind,
                        "samples_requested": int(samples_),
                        "samples_used": int(scene.cycles.samples),
                        "filter_width": float(scene.cycles.filter_width),
                        "denoise": bool(denoise_), "max_bounces": int(bounces),
                        "seconds": dt, "path": path, "bytes": os.path.getsize(path),
                        "channels": dict(GEOMETRY_PACKS.get(tag, [{}])[pack_index])})
        return path

    def do_geometry(tag: str, *, samples_: int, filter_: float) -> list[str]:
        return [do_render(tag, samples_=samples_, filter_=filter_, denoise_=False,
                          bounces=geom_bounces, kind="geometry", pack_index=i)
                for i in range(len(GEOMETRY_PACKS[tag]))]

    rgb_exr = do_render("rgb", samples_=samples, filter_=filter_width, denoise_=denoise,
                        bounces=max_bounces, kind="image")
    exact_exrs = do_geometry("geometry_exact", samples_=geom_samples, filter_=geom_filter)
    aa_exrs = do_geometry("geometry_aa", samples_=aa_geom_samples, filter_=filter_width)
    for obj in objs:
        if obj.pass_index != target_pass_index:
            obj.hide_render = True
    bpy.context.view_layer.update()
    target_exrs = do_geometry("geometry_targetonly", samples_=geom_samples,
                              filter_=geom_filter)
    for obj in objs:
        obj.hide_render = False
    bpy.context.view_layer.update()

    rgb, rgb_info = load_exr(rgb_exr, non_color=False)
    ex_a, ex_a_info = load_exr(exact_exrs[0])
    ex_b, ex_b_info = load_exr(exact_exrs[1])
    aa_a, aa_a_info = load_exr(aa_exrs[0])
    aa_b, aa_b_info = load_exr(aa_exrs[1])
    tg_a, tg_a_info = load_exr(target_exrs[0])

    # channel order follows GEOMETRY_PACKS:
    #   pack a = (depth, object index, face-label AOV)
    #   pack b = (tag AOV, material index, depth)   <- the repeated depth is a free check
    #   target-only = (depth, object index, material index)
    x_depth = ex_a[:, :, 0].astype(np.float64)
    x_obj = ex_a[:, :, 1].astype(np.float64)
    x_face = ex_a[:, :, 2].astype(np.float64)
    x_tag = ex_b[:, :, 0].astype(np.float64)
    x_mat = ex_b[:, :, 1].astype(np.float64)
    x_depth_b = ex_b[:, :, 2].astype(np.float64)
    a_depth = aa_a[:, :, 0].astype(np.float64)
    a_obj = aa_a[:, :, 1].astype(np.float64)
    a_face = aa_a[:, :, 2].astype(np.float64)
    a_tag = aa_b[:, :, 0].astype(np.float64)
    a_mat = aa_b[:, :, 1].astype(np.float64)
    t_depth = tg_a[:, :, 0].astype(np.float64)
    t_obj = tg_a[:, :, 1].astype(np.float64)
    t_mat = tg_a[:, :, 2].astype(np.float64)
    depth_pack_agreement = float(np.nanmax(np.abs(x_depth - x_depth_b)))

    def integral(values: np.ndarray, tol: float = 1e-3):
        r = np.rint(values)
        return r.astype(np.int64), np.abs(values - r) <= tol

    i_obj, ok_obj = integral(x_obj)
    i_mat, ok_mat = integral(x_mat)
    i_face, ok_face = integral(x_face)
    i_tag, ok_tag = integral(x_tag)
    bg = ~(x_obj > 0.5)                       # object index 0 == no object hit
    i_obj[bg] = -1
    i_mat[bg] = -1
    i_face[bg] = -1
    i_tag[bg] = -1
    object_index = i_obj.astype(np.int32)
    material_index = i_mat.astype(np.int32)
    id_face = i_face.astype(np.int32)
    depth_hit = x_obj > 0.5
    depth_z = np.where(depth_hit, x_depth, np.nan).astype(np.float32)

    # ------------------------------------------------------------------ uncertain mask
    ucfg = dict(cfg.get("uncertain", {}))
    coc_thr = float(ucfg.get("coc_px_threshold", 0.75))
    f_number = float(ucfg.get("f_number", 4.0))
    focus_mm = float(ucfg.get("focus_distance_mm", cam_cfg.get("focus_distance_mm", 0.0))
                     or 0.0)
    motion_px = float(ucfg.get("motion_amplitude_px", 0.0))
    f_px = 0.5 * (float(as_mat3(cam_cfg["K"], "camera.K")[0, 0])
                  + float(as_mat3(cam_cfg["K"], "camera.K")[1, 1]))
    depth_edge_tol = float(ucfg.get("depth_edge_tol_mm", 0.25))
    # A pixel is "mixed" when the filter-averaged pass disagrees with the exact pass: either a
    # fractional value (a weighted mixture of two labels), a different rounded label (two
    # labels whose average lands on an integer), or a disagreement about whether an object is
    # hit at all.  Background pixels are excluded from the label comparison because both
    # passes legitimately report "no hit" there (object index 0, AOV 0).
    frac_face = np.abs(a_face - np.rint(a_face)) > 1e-3
    frac_tag = np.abs(a_tag - np.rint(a_tag)) > 1e-3
    frac_obj = np.abs(a_obj - np.rint(a_obj)) > 1e-3
    exact_hit = x_obj > 0.5
    aa_hit = a_obj > 0.5
    label_mix = (np.rint(a_face).astype(np.int64) != i_face) & exact_hit & aa_hit
    tag_mix = (np.rint(a_tag).astype(np.int64) != i_tag) & exact_hit & aa_hit
    hit_mix = exact_hit != aa_hit
    mixed_face = frac_face | label_mix | hit_mix
    mixed_tag = frac_tag | tag_mix | hit_mix
    mixed_pass = (mixed_face | mixed_tag | frac_obj) & (exact_hit | aa_hit)
    depth_edge = np.zeros_like(mixed_pass)
    valid_both = depth_hit & np.isfinite(a_depth)
    depth_edge[valid_both] = np.abs(a_depth[valid_both] - x_depth[valid_both]) > depth_edge_tol
    with np.errstate(invalid="ignore"):
        coc = circle_of_confusion_px(depth_z.astype(np.float64), focus_mm, f_number, f_px)
    defocus = (coc > coc_thr) & depth_hit
    uncertain = (mixed_pass | depth_edge | defocus) & depth_hit
    if motion_px > 0:
        uncertain = uncertain | dilate(mixed_pass, int(math.ceil(motion_px)))
    uncertain = uncertain & depth_hit

    # ------------------------------------------------------------------ visibility
    # visibility keeps the software rasteriser's meaning (any scene geometry, not mixed);
    # target_visibility is the Blender-only channel that separates target from occluder.
    visible_any = depth_hit & (~mixed_pass)
    target_hit_full = (object_index == target_pass_index) & depth_hit
    target_visible = target_hit_full & (~mixed_pass)
    target_only_hit = (np.rint(t_obj).astype(np.int64) == target_pass_index) & (t_obj > 0.5)
    # occlusion is a pure geometry statement: the target is hit with the non-target objects
    # hidden and not hit in the full scene.  It deliberately ignores the mixing test.
    occlusion = (target_only_hit & (~target_hit_full)).astype(np.uint8)
    visibility = visible_any.astype(np.uint8)
    surface_tag = np.where(depth_hit, i_tag, -1).astype(np.int16)

    # measured anti-aliasing behaviour of each pass in this Blender build: the Z pass and the
    # Object Index pass are unfiltered (bit-identical between the exact and the AA render),
    # the Shader AOV passes are averaged exactly like RGB.
    z_pass_filtered = bool(np.any(np.abs(a_depth[valid_both] - x_depth[valid_both]) > 1e-6)) \
        if valid_both.any() else False
    aov_pass_filtered = bool(np.count_nonzero(mixed_face | mixed_tag) > 0)

    # ------------------------------------------------------------------ self checks
    label_arrays = {r["name"]: r.pop("_face_id_labels") for r in object_report}
    ray_report = raycast_check(
        scene, cam_cfg, depth_z, id_face, object_index, target_pass_index,
        int(checks_cfg.get("raycast_samples", 2000)),
        float(checks_cfg.get("raycast_depth_tol_mm", 0.5)), seed, label_arrays)
    linearity = linearity_check(rgb, cfg)
    background_linearity = background_linearity_check(
        rgb, cfg.get("background_linear", [0.0, 0.0, 0.0]),
        x_obj > 0.5)

    # ------------------------------------------------------------------ write outputs
    files: dict[str, str] = {}
    files["rgb_linear.npy"] = os.path.join(out_dir, "rgb_linear.npy")
    np.save(files["rgb_linear.npy"], np.ascontiguousarray(rgb[:, :, :3], dtype=np.float32))
    files["rgb_linear.exr"] = rgb_exr
    np.save(os.path.join(out_dir, "depth_z_mm.npy"), np.ascontiguousarray(depth_z))
    np.save(os.path.join(out_dir, "depth_z_aa_mm.npy"),
            np.ascontiguousarray(np.where(depth_hit, a_depth, np.nan).astype(np.float32)))
    np.save(os.path.join(out_dir, "id_face.npy"), np.ascontiguousarray(id_face))
    np.save(os.path.join(out_dir, "surface_tag.npy"), np.ascontiguousarray(surface_tag))
    np.save(os.path.join(out_dir, "object_index.npy"), np.ascontiguousarray(object_index))
    np.save(os.path.join(out_dir, "visibility.npy"), np.ascontiguousarray(visibility))
    np.save(os.path.join(out_dir, "target_visibility.npy"),
            np.ascontiguousarray(target_visible.astype(np.uint8)))
    np.save(os.path.join(out_dir, "occlusion.npy"), np.ascontiguousarray(occlusion))
    np.save(os.path.join(out_dir, "uncertain_mask.npy"), np.ascontiguousarray(uncertain))
    np.save(os.path.join(out_dir, "aa_object_index_raw.npy"),
            np.ascontiguousarray(a_obj.astype(np.float32)))
    np.save(os.path.join(out_dir, "aa_face_id_raw.npy"),
            np.ascontiguousarray(a_face.astype(np.float32)))
    np.save(os.path.join(out_dir, "aa_surface_tag_raw.npy"),
            np.ascontiguousarray(a_tag.astype(np.float32)))
    for i, path in enumerate(exact_exrs):
        files[f"geometry_passes_exact_{'ab'[i]}.exr"] = path
    for i, path in enumerate(aa_exrs):
        files[f"geometry_passes_aa_{'ab'[i]}.exr"] = path
    for i, path in enumerate(target_exrs):
        files[f"geometry_passes_targetonly_{'ab'[i]}.exr"] = path

    previews = {}
    if bool(cfg.get("write", {}).get("previews", True)):
        p = os.path.join(out_dir, "rgb_preview.png")
        write_preview_png(p, rgb[:, :, :3])
        previews["rgb_preview.png"] = p
        p = os.path.join(out_dir, "depth_preview.png")
        write_scalar_png(p, depth_z, depth_hit)
        previews["depth_preview.png"] = p
        p = os.path.join(out_dir, "id_preview.png")
        write_scalar_png(p, id_face.astype(np.float32), visible_any,
                         mask_alpha=(~visible_any) & target_visible)
        previews["id_preview.png"] = p

    # ------------------------------------------------------------------ channels.json
    n_classes = int(np.unique(id_face[visible_any]).size) if visible_any.any() else 0
    channels = {
        "rgb_linear": {"file": "rgb_linear.npy", "dtype": "float32", "shape": [H, W, 3],
                       "units": "scene-linear radiance", "color_space": "linear_rec709_scene",
                       "view_transform": "Standard", "save_as_render": False,
                       "source_pass": "Cycles Combined (Image)", "denoised": bool(denoise),
                       "note": "raw float values; the .exr holds the identical numbers"},
        "depth_z": {"file": "depth_z_mm.npy", "dtype": "float32", "shape": [H, W],
                    "units": "mm, camera-frame z (not ray length)", "invalid": "NaN",
                    "source_pass": "Cycles Depth (Z), exact geometry pass",
                    "aa_behaviour": "exact pass = one sample per pixel in a 0.01 px filter",
                    "also": {"depth_z_aa_mm.npy": "same pass with the RGB filter/samples"}},
        "id_face": {"file": "id_face.npy", "dtype": "int32", "shape": [H, W],
                    "units": "integer face index", "invalid": -1,
                    "source_pass": (f"Shader AOV {AOV_FACE_ID} fed by the face-domain FLOAT "
                                    f"attribute {ATTR_FACE_ID}"),
                    "interpolation": "forbidden; the exact pass is integral by construction",
                    "n_classes_visible": n_classes},
        "surface_tag": {"file": "surface_tag.npy", "dtype": "int16", "shape": [H, W],
                        "units": "integer surface tag", "invalid": -1,
                        "source_pass": (f"Shader AOV {AOV_TAG} fed by the face-domain FLOAT "
                                        f"attribute {ATTR_TAG}; the Cycles Material Index "
                                        f"pass returns a constant 0 in 5.2.2 and is kept "
                                        f"only as the target-only audit channel")},
        "object_index": {"file": "object_index.npy", "dtype": "int32", "shape": [H, W],
                         "units": "Blender Object Index (pass_index)", "invalid": -1,
                         "source_pass": "Cycles Object Index"},
        "visibility": {"file": "visibility.npy", "dtype": "uint8", "shape": [H, W],
                       "units": "1 primary hit is scene geometry and the pixel is not mixed, "
                                "else 0 (same meaning as the software rasteriser)",
                       "source_pass": "Cycles Object Index + anti-aliased mixing test"},
        "target_visibility": {"file": "target_visibility.npy", "dtype": "uint8",
                              "shape": [H, W],
                              "units": "1 primary hit is the *target* object and the pixel is "
                                       "not mixed, else 0 (Blender-only channel)",
                              "source_pass": "Cycles Object Index + anti-aliased mixing test"},
        "occlusion": {"file": "occlusion.npy", "dtype": "uint8", "shape": [H, W],
                      "units": "1 target hidden by a non-target object",
                      "source_pass": "Object Index with/without non-target objects"},
        "uncertain_mask": {"file": "uncertain_mask.npy", "dtype": "bool", "shape": [H, W],
                           "units": "1 = pixel cannot be assigned to a single surface",
                           "components": {
                               "mixed_pass": int(np.count_nonzero(mixed_pass)),
                               "depth_edge": int(np.count_nonzero(depth_edge)),
                               "defocus_coc_gt_threshold": int(np.count_nonzero(defocus)),
                               "motion_dilation_px": int(math.ceil(motion_px)) if motion_px else 0},
                           "coc_threshold_px": coc_thr, "f_number": f_number,
                           "focus_distance_mm": focus_mm,
                           "depth_edge_tol_mm": depth_edge_tol},
    }
    channels_path = os.path.join(out_dir, "channels.json")
    with open(channels_path, "w", encoding="utf-8") as fh:
        json.dump(channels, fh, indent=2, sort_keys=True)

    out_files = {k: v for k, v in files.items()}
    out_files.update(previews)
    out_files["channels.json"] = channels_path
    hashes = {}
    for name, path in sorted(out_files.items()):
        if os.path.exists(path):
            hashes[name] = {"sha256": sha256_file(path), "bytes": os.path.getsize(path)}
    npy_names = [f for f in os.listdir(out_dir) if f.endswith(".npy")]
    for name in sorted(npy_names):
        path = os.path.join(out_dir, name)
        hashes.setdefault(name, {"sha256": sha256_file(path), "bytes": os.path.getsize(path)})

    elapsed = time.time() - t_start
    manifest = {
        "schema": "rws.blender.render.manifest/1",
        "config_schema": CONFIG_SCHEMA,
        "view_id": cfg.get("view_id"),
        "argv": list(sys.argv),
        "blender": {
            "version": bpy.app.version_string,
            "version_tuple": list(bpy.app.version),
            "build_hash": bpy.app.build_hash.decode() if isinstance(bpy.app.build_hash, bytes)
            else str(bpy.app.build_hash),
            "build_commit_date": str(bpy.app.build_commit_date),
            "python": sys.version.split()[0],
            "binary": bpy.app.binary_path,
            "cycles_device_setting": scene.cycles.device,
            "gpu_devices": _gpu_devices(),
        },
        "render": {
            "resolution": [W, H],
            "samples_requested": samples,
            "samples_used": int(next(r["samples_used"] for r in renders
                                     if r["tag"] == "rgb")),
            "filter_width": filter_width,
            "denoise": bool(denoise),
            "denoiser": scene.cycles.denoiser if denoise else None,
            "denoise_applies_to": "RGB only (Image pass); geometry channels are separate "
                                  "renders with use_denoising = False",
            "max_bounces": max_bounces,
            "seed": seed,
            "adaptive_sampling": bool(scene.cycles.use_adaptive_sampling),
            "engine": scene.render.engine,
            "pixel_filter_type": str(getattr(scene.cycles, "pixel_filter_type", "n/a")),
            "unit_scale_length_m": scene.unit_settings.scale_length,
            "unit_note": "1 Blender unit == 1 mm; Depth pass values are millimetres",
        },
        "renders": renders,
        "pass_pack": pack_report,
        "exr_readback": {"rgb": rgb_info, "exact_a": ex_a_info, "exact_b": ex_b_info,
                         "aa_a": aa_a_info, "aa_b": aa_b_info, "targetonly_a": tg_a_info},
        "objects": object_report,
        "camera": cam_report,
        "light": light_report,
        "target_pass_index": int(target_pass_index),
        "checks": {
            "face_order": [{"name": r["name"], "n_faces": r["n_faces"],
                            "max_centroid_error_mm": r.get("max_centroid_error_mm")}
                           for r in object_report],
            "camera_model": cam_report["selfcheck"],
            "raycast_vs_exact_pass": ray_report,
            "exact_pass_integrality": {
                "object_index_non_integral": int(np.count_nonzero(~ok_obj)),
                "material_index_non_integral": int(np.count_nonzero(~ok_mat)),
                "face_id_non_integral": int(np.count_nonzero(~ok_face)),
                "surface_tag_non_integral": int(np.count_nonzero(~ok_tag)),
                "tolerance": 1e-3,
                "note": "exact geometry pass must be integral; the anti-aliased pass is "
                        "measured separately",
            },
            "aa_pass_fractional": {
                "object_index_fractional_px": int(np.count_nonzero(frac_obj)),
                "face_id_fractional_px": int(np.count_nonzero(frac_face)),
                "surface_tag_fractional_px": int(np.count_nonzero(frac_tag)),
                "mixed_label_px": int(np.count_nonzero(mixed_face | mixed_tag)),
                "depth_edge_px": int(np.count_nonzero(depth_edge)),
                "aa_samples": aa_geom_samples, "aa_filter_width": filter_width,
                "exact_samples": geom_samples, "exact_filter_width": geom_filter,
            },
            "pass_aa_behaviour": {
                "z_pass_filtered": z_pass_filtered,
                "object_index_pass_filtered": bool(np.count_nonzero(frac_obj) > 0),
                "shader_aov_pass_filtered": aov_pass_filtered,
                "rgb_pass_filtered": True,
                "material_index_pass_usable": bool(np.unique(x_mat).size > 1),
                "material_index_pass_values": sorted(float(v) for v in np.unique(x_mat))[:8],
                "master_material_index_count": 3,
                "conclusion": (
                    "measured: the Shader AOV passes behave like RGB (filter-averaged, "
                    "fractional labels on mixed borders), while the Z / Object Index passes "
                    "of Cycles 5.2.2 return identical values under 0.01 px vs 1.5 px filters "
                    "and 1 vs N samples, i.e. they are NOT anti-aliased the way RGB is; the "
                    "Material Index pass returns a constant in this build and the delivered "
                    "surface tag therefore comes from a per-face Shader AOV"),
            },
            "rgb_linearity": linearity,
            "rgb_background_linearity": background_linearity,
            "pass_channel_ranges": {
                "depth_mm": [float(np.nanmin(x_depth)), float(np.nanmax(x_depth))],
                "object_index": [float(x_obj.min()), float(x_obj.max())],
                "material_index_audit": [float(x_mat.min()), float(x_mat.max())],
                "face_label_aov": [float(x_face.min()), float(x_face.max())],
                "surface_tag_aov": [float(x_tag.min()), float(x_tag.max())],
                "depth_pack_a_vs_pack_b_max_diff_mm": depth_pack_agreement,
                "clamping_suspected": bool(np.nanmax(x_depth) <= 1.0 + 1e-6
                                           and float(cam_cfg.get("far_mm", 1e6)) > 1.0),
                "note": "measured ranges of the packed geometry channels; a scene with "
                        "geometry farther than 1 mm must show depth > 1.0 or the pack is "
                        "being clamped",
            },
        },
        "statistics": {
            "visible_fraction": float(np.mean(visibility)),
            "target_visible_fraction": float(np.mean(target_visible)),
            "occluded_fraction": float(np.mean(occlusion)),
            "uncertain_fraction": float(np.mean(uncertain)),
            "depth_valid_fraction": float(np.mean(depth_hit)),
            "id_classes_visible": n_classes,
            "unique_object_indices": sorted(int(v) for v in np.unique(object_index)),
        },
        "elapsed_seconds": elapsed,
        "outputs": hashes,
        "output_dir": out_dir,
        "status": "OK",
    }
    manifest_path = os.path.join(out_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
    manifest["outputs"]["manifest.json"] = {
        "sha256": sha256_file(manifest_path), "bytes": os.path.getsize(manifest_path)}
    manifest["manifest_path"] = manifest_path
    return manifest


def _gpu_devices() -> list:
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
        prefs.get_devices()
        return [f"{d.type}:{d.name}" for d in prefs.devices]
    except Exception:  # noqa: BLE001
        return []


def linearity_check(rgb: np.ndarray, cfg: dict) -> dict:
    """Scale linearity of the delivered numbers against the declared emitter ratio."""
    probes = list(cfg.get("linearity_probes", []))
    if not probes:
        return {"status": "NOT_REQUESTED"}
    out = {"status": "OK", "probes": []}
    for probe in probes:
        x, y = int(probe["pixel"][0]), int(probe["pixel"][1])
        expected = float(probe["expected_linear"])
        measured = float(np.mean(rgb[max(y - 1, 0):y + 2, max(x - 1, 0):x + 2, 0]))
        out["probes"].append({"pixel": [x, y], "expected_linear": expected,
                              "measured_linear": measured,
                              "rel_error": abs(measured - expected) / max(expected, 1e-9)})
    if len(out["probes"]) >= 2:
        # two emitters with a declared ratio must land on the same ratio in the file
        (a, b) = out["probes"][0], out["probes"][1]
        out["declared_ratio"] = b["expected_linear"] / max(a["expected_linear"], 1e-12)
        out["measured_ratio"] = b["measured_linear"] / max(a["measured_linear"], 1e-12)
        out["ratio_rel_error"] = abs(out["measured_ratio"] - out["declared_ratio"]) / \
            max(out["declared_ratio"], 1e-12)
        if out["ratio_rel_error"] > 0.02:
            out["status"] = "NONLINEAR"
    return out


def background_linearity_check(rgb: np.ndarray, background_linear, depth_hit: np.ndarray) -> dict:
    """The declared constant world radiance must come back unchanged in the float RGB.

    This is an analytic linearity probe that runs on every render: if a view transform or a
    gamma had been baked into the delivered numbers, the background would not be the declared
    scene-linear value (the sRGB-encoded alternative is reported next to it for contrast).
    """
    bg = ~np.asarray(depth_hit, dtype=bool)
    if not bg.any():
        return {"status": "NO_BACKGROUND_PIXELS",
                "note": "the fixture covers the whole frame; the check needs visible background"}
    expected = np.asarray(background_linear, dtype=np.float64).reshape(3)
    got = np.median(np.asarray(rgb, dtype=np.float64)[bg][:, :3], axis=0)
    err = float(np.abs(got - expected).max())
    srgb = np.where(expected <= 0.0031308, expected * 12.92,
                    1.055 * np.power(np.maximum(expected, 0.0), 1.0 / 2.4) - 0.055)
    return {"status": "OK" if err <= 1e-4 else "NONLINEAR",
            "measured_median": [float(v) for v in got],
            "expected_linear": [float(v) for v in expected],
            "max_abs_error": err,
            "srgb_encoded_alternative": [float(v) for v in srgb],
            "distance_to_srgb_alternative": float(np.abs(got - srgb).max()),
            "n_background_px": int(np.count_nonzero(bg)),
            "note": "a declared constant world radiance returned unchanged proves the float "
                    "EXR carries scene-linear numbers (no view transform baked in)"}


def main() -> int:
    argv = sys.argv
    if "--" not in argv or len(argv) < argv.index("--") + 2:
        raise WorkerError("USAGE", "usage: -- <config.json>")
    cfg_path = argv[argv.index("--") + 1]
    with open(cfg_path, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    cfg.setdefault("_config_path", os.path.abspath(cfg_path))
    manifest = run(cfg)
    print(RESULT_PREFIX + json.dumps({
        "status": "OK", "manifest": manifest["manifest_path"],
        "output_dir": manifest["output_dir"], "elapsed_seconds":
            manifest["elapsed_seconds"],
        "samples_used": manifest["render"]["samples_used"],
        "blender_version": manifest["blender"]["version"],
        "blender_binary": manifest["blender"]["binary"],
    }))
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except WorkerError as exc:
        print("RWS_WORKER_ERROR " + json.dumps(
            {"status": "ERROR", "error_code": exc.code, "message": exc.message,
             "extra": exc.extra}), file=sys.stderr)
        traceback.print_exc()
        raise SystemExit(3) from exc
    except Exception as exc:  # noqa: BLE001
        print("RWS_WORKER_ERROR " + json.dumps(
            {"status": "ERROR", "error_code": "WORKER_EXCEPTION",
             "message": f"{type(exc).__name__}: {exc}"}), file=sys.stderr)
        traceback.print_exc()
        raise SystemExit(3) from exc
    raise SystemExit(code)
