"""Render four full-form views and panel-normal details with continuous textures.

Use the VesselForge runtime (VTK is available there):
    ..\\third_party\\vesselforge-runtime\\venv\\Scripts\\python.exe \\
        experiments\\continuation_20261015\\reference_generation\\render_previews.py

The surface positions and triangle topology are loaded unchanged from the output NPZ. Outer
wall color comes from the 512x1024 chart-sampled material/pattern texture; inner, rim, foot,
and base colors use the saved per-face material/pattern samples.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
from pathlib import Path

import numpy as np
import vtk
from vtk.util.numpy_support import numpy_to_vtk, numpy_to_vtkIdTypeArray, vtk_to_numpy


HERE = Path(__file__).resolve().parent
DEFAULT_OUTPUT = HERE / "outputs_v3_pbr"
VIEW_DEFS = (
    ("Side · orthographic", (0.0, -1.0, 0.0), (0.0, 0.0, 1.0), True),
    ("Top · orthographic", (0.0, 0.0, 1.0), (0.0, 1.0, 0.0), True),
    ("Lit 3D · perspective", (1.0, -1.0, 0.55), (0.0, 0.0, 1.0), False),
    ("Underside · orthographic", (0.0, 0.0, -1.0), (0.0, 1.0, 0.0), True),
)
STUDIO_ENVIRONMENT = {
    "schema": "synlab.reference_preview_neutral_studio_environment.v1",
    "model": "procedural neutral linear-RGB equirectangular fill with broad softboxes",
    "base_fill_linear_rgb": [0.6, 0.6, 0.6],
    "softbox_linear_rgb": [1.05, 1.05, 1.05],
    "softboxes": [
        {"rows": [5, 13], "columns": [6, 23]},
        {"rows": [4, 12], "columns": [41, 58]},
    ],
    "dimensions_pixels": [64, 32],
    "color_space": "LINEAR_RGB_FLOAT",
    "image_based_lighting": True,
    "spherical_harmonics": False,
    "calibration_status": "UNCALIBRATED_PRESENTATION_LIGHTING",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _array_geometry_hash(vertices: np.ndarray, faces: np.ndarray) -> str:
    """Match the canonical source geometry hash used by the SynLab loader."""
    digest = hashlib.sha256()
    digest.update(b"synlab.reference_geometry_arrays.v1\0")
    v = np.ascontiguousarray(vertices, dtype="<f8")
    f = np.ascontiguousarray(faces, dtype="<i8")
    digest.update(json.dumps([list(v.shape), list(f.shape)], separators=(",", ":")).encode())
    digest.update(v.tobytes())
    digest.update(f.tobytes())
    return digest.hexdigest()


def _srgb8(linear: np.ndarray) -> np.ndarray:
    value = np.asarray(linear, dtype=np.float64)
    srgb = np.where(value <= 0.0031308, 12.92 * value,
                    1.055 * np.power(np.maximum(value, 0.0), 1.0 / 2.4) - 0.055)
    return np.clip(np.rint(srgb * 255.0), 0, 255).astype(np.uint8)


def _neutral_studio_environment() -> tuple[vtk.vtkTexture, dict[str, object]]:
    """Build a small, deterministic neutral linear-RGB equirectangular IBL map."""
    width, height = (int(value) for value in STUDIO_ENVIRONMENT["dimensions_pixels"])
    rgb = np.full((height, width, 3),
                  STUDIO_ENVIRONMENT["base_fill_linear_rgb"], dtype=np.float32)
    for softbox in STUDIO_ENVIRONMENT["softboxes"]:
        row0, row1 = softbox["rows"]
        column0, column1 = softbox["columns"]
        rgb[row0:row1, column0:column1] = STUDIO_ENVIRONMENT["softbox_linear_rgb"]
    image = vtk.vtkImageData()
    image.SetDimensions(width, height, 1)
    scalars = numpy_to_vtk(np.ascontiguousarray(rgb.reshape(-1, 3)), deep=True,
                            array_type=vtk.VTK_FLOAT)
    scalars.SetNumberOfComponents(3)
    image.GetPointData().SetScalars(scalars)
    texture = vtk.vtkTexture()
    texture.SetInputData(image)
    texture.SetColorModeToDirectScalars()
    texture.MipmapOn()
    texture.InterpolateOn()
    info = {
        **STUDIO_ENVIRONMENT,
        "sha256_float32_rgb": hashlib.sha256(
            np.ascontiguousarray(rgb, dtype="<f4").tobytes()).hexdigest(),
    }
    return texture, info


def _enable_studio_lighting(renderer: vtk.vtkRenderer,
                            environment: vtk.vtkTexture) -> None:
    renderer.AutomaticLightCreationOff()
    renderer.SetEnvironmentTexture(environment, False)
    renderer.UseImageBasedLightingOn()
    renderer.UseSphericalHarmonicsOff()


def _add_legacy_scene_lights(renderer: vtk.vtkRenderer, center: np.ndarray,
                             distance: float) -> None:
    for light_direction, intensity in (
            ([1.4, -1.7, 2.2], 1.10),
            ([-1.8, -0.2, 1.0], 0.55),
            ([0.2, 1.8, 0.8], 0.38),
            ([0.3, -0.2, -1.5], 0.42)):
        light = vtk.vtkLight()
        light.SetLightTypeToSceneLight()
        light.SetPosition(*(center + np.asarray(light_direction) * distance))
        light.SetFocalPoint(*center)
        light.SetIntensity(intensity)
        renderer.AddLight(light)


def _source_profile_point_normal(profile_rz_mm: np.ndarray, center_s_mm: float,
                                 theta_rad: float) -> dict[str, object]:
    """Evaluate the source finite polyline and its meridian-derived outward normal."""
    profile = np.asarray(profile_rz_mm, dtype=np.float64)
    if (profile.ndim != 2 or profile.shape[1] != 2 or len(profile) < 2
            or not np.isfinite(profile).all() or np.any(profile[:, 0] <= 0.0)):
        raise ValueError("saved outer profile must be a finite positive-radius (N,2) polyline")
    segment_vectors = np.diff(profile, axis=0)
    segment_lengths = np.linalg.norm(segment_vectors, axis=1)
    if not np.isfinite(segment_lengths).all() or np.any(segment_lengths <= 0.0):
        raise ValueError("saved outer profile contains a degenerate finite-polyline segment")
    s_profile = np.concatenate([[0.0], np.cumsum(segment_lengths)])
    s_total = float(s_profile[-1])
    if not math.isfinite(center_s_mm) or not 0.0 <= center_s_mm <= s_total:
        raise ValueError("panel center_s lies outside the saved source profile")
    segment_index = min(int(np.searchsorted(s_profile, center_s_mm, side="right") - 1),
                        len(segment_lengths) - 1)
    segment_index = max(0, segment_index)
    tangent_rz_per_s = segment_vectors[segment_index] / segment_lengths[segment_index]
    radius_mm = float(np.interp(center_s_mm, s_profile, profile[:, 0]))
    z_mm = float(np.interp(center_s_mm, s_profile, profile[:, 1]))
    radial = np.asarray([math.cos(theta_rad), math.sin(theta_rad), 0.0])
    vertical = np.asarray([0.0, 0.0, 1.0])
    meridian_tangent = tangent_rz_per_s[0] * radial + tangent_rz_per_s[1] * vertical
    outward = -tangent_rz_per_s[1] * radial + tangent_rz_per_s[0] * vertical
    outward /= np.linalg.norm(outward)
    return {
        "s_profile_mm": s_profile,
        "meridian_length_mm": s_total,
        "segment_index": segment_index,
        "radius_mm": radius_mm,
        "z_mm": z_mm,
        "point_mm": np.asarray([radius_mm * radial[0], radius_mm * radial[1], z_mm]),
        "tangent_rz_per_s": tangent_rz_per_s,
        "meridian_tangent": meridian_tangent,
        "outward_normal": outward,
    }


def _polydata(points: np.ndarray, triangles: np.ndarray, *,
              point_normals: np.ndarray, uv: np.ndarray | None = None,
              cell_rgb: np.ndarray | None = None) -> vtk.vtkPolyData:
    points = np.ascontiguousarray(points, dtype=np.float64)
    triangles = np.ascontiguousarray(triangles, dtype=np.int64)
    poly = vtk.vtkPolyData()
    vtk_points = vtk.vtkPoints()
    vtk_points.SetData(numpy_to_vtk(points, deep=True))
    poly.SetPoints(vtk_points)
    connectivity = np.empty((len(triangles), 4), dtype=np.int64)
    connectivity[:, 0] = 3
    connectivity[:, 1:] = triangles
    cells = vtk.vtkCellArray()
    cells.ImportLegacyFormat(numpy_to_vtkIdTypeArray(connectivity.reshape(-1), deep=True))
    poly.SetPolys(cells)
    normals = np.asarray(point_normals, dtype=np.float64)
    if normals.shape != points.shape or not np.isfinite(normals).all():
        raise ValueError("display point normals must match the display point array")
    vtk_normals = numpy_to_vtk(np.ascontiguousarray(normals, dtype=np.float32), deep=True)
    vtk_normals.SetNumberOfComponents(3)
    vtk_normals.SetName("SourceSharedVertexNormals")
    poly.GetPointData().SetNormals(vtk_normals)
    if uv is not None:
        coordinates = numpy_to_vtk(np.ascontiguousarray(uv, dtype=np.float32), deep=True)
        coordinates.SetNumberOfComponents(2)
        coordinates.SetName("OuterChartUV")
        poly.GetPointData().SetTCoords(coordinates)
    if cell_rgb is not None:
        colors = numpy_to_vtk(np.ascontiguousarray(cell_rgb, dtype=np.uint8),
                              deep=True, array_type=vtk.VTK_UNSIGNED_CHAR)
        colors.SetNumberOfComponents(3)
        colors.SetName("AppearanceSRGB")
        poly.GetCellData().SetScalars(colors)
    return poly


def _actor(poly: vtk.vtkPolyData, *, texture_path: Path | None = None,
           roughness: float, ior: float) -> vtk.vtkActor:
    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputData(poly)
    actor = vtk.vtkActor()
    actor.SetMapper(mapper)
    prop = actor.GetProperty()
    prop.SetInterpolationToPBR()
    prop.SetMetallic(0.0)
    prop.SetRoughness(float(np.clip(roughness, 0.02, 1.0)))
    prop.SetBaseIOR(float(np.clip(ior, 1.0, 3.0)))
    if texture_path is None:
        mapper.SetScalarModeToUseCellData()
        mapper.SetColorModeToDirectScalars()
        mapper.ScalarVisibilityOn()
    else:
        reader = vtk.vtkPNGReader()
        reader.SetFileName(str(texture_path))
        texture = vtk.vtkTexture()
        texture.SetInputConnection(reader.GetOutputPort())
        texture.InterpolateOn()
        texture.SetColorModeToDirectScalars()
        texture.UseSRGBColorSpaceOn()
        texture.RepeatOn()
        texture.EdgeClampOff()
        # PBR consumes a base-color texture from vtkProperty; vtkActor.SetTexture is the
        # legacy fixed-function texture slot and is ignored by the PBR shader.
        prop.SetBaseColorTexture(texture)
        actor.GetProperty().SetColor(1.0, 1.0, 1.0)
        mapper.ScalarVisibilityOff()
    return actor


def _source_corner_normals(vertices: np.ndarray, faces: np.ndarray,
                           smoothing_groups: np.ndarray) -> np.ndarray:
    """Area-weight source shared-vertex normals before any UV display duplication.

    A corner blends only with incident triangles in the same source CAD smoothing group.
    The loader joins two CAD faces only when their serialized section segments meet C1, so
    sharp source features remain explicit while UV seam copies receive identical normals.
    """
    triangle_vertices = np.asarray(vertices, dtype=np.float64)[faces]
    face_vectors = np.cross(triangle_vertices[:, 1] - triangle_vertices[:, 0],
                            triangle_vertices[:, 2] - triangle_vertices[:, 0])
    lengths = np.linalg.norm(face_vectors, axis=1)
    if np.any(lengths <= 0.0) or not np.isfinite(face_vectors).all():
        raise ValueError("source geometry has a degenerate face; display normals are undefined")
    vertex_ids = np.asarray(faces, dtype=np.int64).reshape(-1)
    group_ids = np.repeat(np.asarray(smoothing_groups, dtype=np.int64), 3)
    pairs = np.column_stack([vertex_ids, group_ids])
    _, inverse = np.unique(pairs, axis=0, return_inverse=True)
    accumulated = np.zeros((int(inverse.max()) + 1, 3), dtype=np.float64)
    np.add.at(accumulated, inverse, np.repeat(face_vectors, 3, axis=0))
    norms = np.linalg.norm(accumulated, axis=1)
    if np.any(norms <= 0.0):
        raise ValueError("source shared-vertex normal accumulation cancelled to zero")
    accumulated /= norms[:, None]
    return accumulated[inverse].reshape(-1, 3, 3)


def _capture_png(window: vtk.vtkRenderWindow, path: Path) -> np.ndarray:
    capture = vtk.vtkWindowToImageFilter()
    capture.SetInput(window)
    capture.SetInputBufferTypeToRGB()
    capture.ReadFrontBufferOff()
    capture.Update()
    pixels = vtk_to_numpy(capture.GetOutput().GetPointData().GetScalars())
    width, height, _ = capture.GetOutput().GetDimensions()
    pixels = np.ascontiguousarray(pixels.reshape(height, width, 3))
    writer = vtk.vtkPNGWriter()
    writer.SetFileName(str(path))
    writer.SetInputConnection(capture.GetOutputPort())
    writer.Write()
    if not path.is_file() or path.stat().st_size <= 0:
        raise RuntimeError(f"VTK did not write the preview image: {path}")
    return pixels


def _decorate(renderer: vtk.vtkRenderer, title: str, footer: str = "") -> None:
    label = vtk.vtkTextActor()
    label.SetInput(title)
    label.GetPositionCoordinate().SetCoordinateSystemToNormalizedViewport()
    label.SetPosition(0.03, 0.055)
    label.GetTextProperty().SetFontSize(17)
    label.GetTextProperty().SetColor(0.16, 0.14, 0.12)
    renderer.AddViewProp(label)
    if footer:
        note = vtk.vtkTextActor()
        note.SetInput(footer)
        note.GetPositionCoordinate().SetCoordinateSystemToNormalizedViewport()
        note.SetPosition(0.03, 0.012)
        note.GetTextProperty().SetFontSize(11)
        note.GetTextProperty().SetColor(0.20, 0.17, 0.14)
        renderer.AddViewProp(note)


def _orient_renderer(renderer: vtk.vtkRenderer, *, focal: np.ndarray,
                     direction: np.ndarray, view_up: np.ndarray,
                     parallel_scale: float, parallel: bool = True) -> None:
    camera = renderer.GetActiveCamera()
    camera.SetFocalPoint(*focal)
    direction = np.asarray(direction, dtype=np.float64)
    direction /= np.linalg.norm(direction)
    camera.SetPosition(*(focal + max(1.0, parallel_scale * 4.0) * direction))
    camera.SetViewUp(*view_up)
    if parallel:
        camera.ParallelProjectionOn()
        camera.SetParallelScale(float(parallel_scale))
    else:
        camera.ParallelProjectionOff()
    renderer.ResetCameraClippingRange()


def _render_texture_origin_probe(output_root: Path, revision: str,
                                 lighting_mode: str,
                                 environment: vtk.vtkTexture | None,
                                 environment_info: dict[str, object]
                                 ) -> dict[str, object]:
    """Display an asymmetric PNG marker through the same VTK PBR texture path.

    The left viewport maps chart v=s/L directly; the right applies the renderer-only
    t=1-v conversion. A screen-space sample proves which PNG row each mapping displays.
    """
    marker_path = output_root / f"texture_origin_marker_{revision}.png"
    probe_path = output_root / f"texture_origin_probe_{revision}.png"
    if marker_path.exists() or probe_path.exists():
        raise FileExistsError("refusing to overwrite the texture-origin marker or probe")
    from PIL import Image

    colors = {
        "png_top_left": [255, 0, 0],
        "png_top_right": [0, 255, 0],
        "png_bottom_left": [0, 0, 255],
        "png_bottom_right": [255, 255, 0],
    }
    tile = 48
    marker_rgb = np.empty((2 * tile, 2 * tile, 3), dtype=np.uint8)
    marker_rgb[:tile, :tile] = colors["png_top_left"]
    marker_rgb[:tile, tile:] = colors["png_top_right"]
    marker_rgb[tile:, :tile] = colors["png_bottom_left"]
    marker_rgb[tile:, tile:] = colors["png_bottom_right"]
    Image.fromarray(marker_rgb, mode="RGB").save(marker_path, format="PNG", optimize=False)

    points = np.asarray([[-1., -1., 0.], [1., -1., 0.],
                         [-1., 1., 0.], [1., 1., 0.]], dtype=np.float64)
    triangles = np.asarray([[0, 1, 2], [1, 3, 2]], dtype=np.int64)
    normals = np.tile(np.asarray([0., 0., 1.]), (4, 1))
    # The chart convention has s=0 at the rim (the top of this test surface) and
    # s/L=1 at the foot (the bottom).  This mirrors actual source geometry orientation.
    current_chart_uv = np.asarray([[0., 1.], [1., 1.], [0., 0.], [1., 0.]])
    corrected_uv = current_chart_uv.copy()
    corrected_uv[:, 1] = 1.0 - corrected_uv[:, 1]
    marker_actor = _actor(
        _polydata(points, triangles, point_normals=normals, uv=current_chart_uv),
        texture_path=marker_path, roughness=1.0, ior=1.5)
    corrected_actor = _actor(
        _polydata(points, triangles, point_normals=normals, uv=corrected_uv),
        texture_path=marker_path, roughness=1.0, ior=1.5)

    window = vtk.vtkRenderWindow()
    window.SetOffScreenRendering(1)
    window.SetSize(960, 520)
    window.SetMultiSamples(0)
    if lighting_mode == "studio_ibl" and hasattr(window, "UseSRGBColorSpaceOn"):
        window.UseSRGBColorSpaceOn()
    for index, (title, actor) in enumerate((
            ("Stored chart UV: v = s / L", marker_actor),
            ("PBR backend conversion: t = 1 - v", corrected_actor))):
        renderer = vtk.vtkRenderer()
        renderer.SetViewport(0.5 * index, 0.0, 0.5 * (index + 1), 1.0)
        renderer.SetBackground(0.22, 0.23, 0.24)
        if lighting_mode == "studio_ibl":
            assert environment is not None
            _enable_studio_lighting(renderer, environment)
        else:
            _add_legacy_scene_lights(renderer, np.zeros(3), 4.0)
        renderer.AddActor(actor)
        _orient_renderer(renderer, focal=np.zeros(3), direction=np.asarray([0., 0., 1.]),
                         view_up=np.asarray([0., 1., 0.]), parallel_scale=1.12)
        _decorate(renderer, title,
                  "PNG top row = red / green; bottom row = blue / yellow")
        window.AddRenderer(renderer)
    window.Render()
    pixels = _capture_png(window, probe_path)
    window_srgb_enabled = bool(
        window.GetUsingSRGBColorSpace()
        if hasattr(window, "GetUsingSRGBColorSpace") else False)
    window.Finalize()

    height, width, _ = pixels.shape
    # The in-memory framebuffer is lower-left-origin; the saved PNG writer flips rows for
    # the ordinary top-left image origin.  Sample screen-space y directly in the VTK array.
    def crop_median(viewport_index: int, side: str, vertical: str) -> list[int]:
        x0, x1 = int(viewport_index * width / 2), int((viewport_index + 1) * width / 2)
        viewport_width = x1 - x0
        screen_x = x0 + (viewport_width // 4 if side == "left"
                         else 3 * viewport_width // 4)
        screen_y = (3 * height // 4) if vertical == "top" else (height // 4)
        crop = pixels[screen_y - 5:screen_y + 6, screen_x - 5:screen_x + 6]
        return np.median(crop.astype(np.float64), axis=(0, 1)).round().astype(int).tolist()

    screen_corners: dict[str, dict[str, list[int]]] = {}
    for index, label in enumerate(("current_chart_uv", "renderer_converted_uv")):
        screen_corners[label] = {
            "top_left": crop_median(index, "left", "top"),
            "top_right": crop_median(index, "right", "top"),
            "bottom_left": crop_median(index, "left", "bottom"),
            "bottom_right": crop_median(index, "right", "bottom"),
        }
    corrected = screen_corners["renderer_converted_uv"]
    matches = (
        corrected["top_left"][0] > max(corrected["top_left"][1:])
        and corrected["top_right"][1] > max(corrected["top_right"][0],
                                             corrected["top_right"][2])
        and corrected["bottom_left"][2] > max(corrected["bottom_left"][:2])
        and min(corrected["bottom_right"][:2]) > corrected["bottom_right"][2]
    )
    return {
        "schema": "synlab.reference_preview_texture_origin_probe.v1",
        "marker_png": marker_path.name,
        "marker_png_sha256": _sha256(marker_path),
        "probe_png": probe_path.name,
        "probe_png_sha256": _sha256(probe_path),
        "source_png_corner_colors_srgb8": colors,
        "measured_screen_corner_medians_srgb8": screen_corners,
        "stored_chart_coordinate_semantics": "v=s/L; s=0 at rim/top and s=L at foot/bottom",
        "observed_png_texture_convention": "texture v=0 samples PNG bottom row; v=1 samples PNG top row",
        "renderer_boundary_conversion": "t=1-v for every outer-chart PNG base-color texture; saved chart UV stays v=s/L",
        "corrected_mapping_matches_marker_orientation": bool(matches),
        "lighting_mode": lighting_mode,
        "render_window_srgb_enabled": window_srgb_enabled,
        "environment": environment_info,
    }


def _render_panel_detail(bundle: Path, revision: str, *,
                         vertices: np.ndarray, faces: np.ndarray, outer: np.ndarray,
                         outer_actor: vtk.vtkActor, profile_rz_mm: np.ndarray,
                         material_albedo_linear: np.ndarray,
                         roughness: float, ior: float,
                         lighting_mode: str,
                         environment: vtk.vtkTexture | None,
                         environment_info: dict[str, object]) -> list[dict[str, object]]:
    """Render profile-normal panel views and a genuine PBR base-color swatch."""
    pattern = json.loads((bundle / "recipe.json").read_text(encoding="utf-8"))
    receipt = json.loads((bundle / "bluewhite_panel_receipt.json").read_text(encoding="utf-8"))
    controls = pattern.get("pattern", {}).get("mapping_and_spread_controls", {})
    panel = receipt.get("panel", {})
    numerical_receipt = {key: value for key, value in receipt.items()
                         if key != "preview_scene"}
    numeric_receipt_hash = hashlib.sha256(json.dumps(
        numerical_receipt, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8")).hexdigest()
    s_fraction = float(controls.get("center_s_fraction", 0.5))
    theta = float(controls.get("center_theta_rad", math.pi))
    profile_length = float(_source_profile_point_normal(
        profile_rz_mm, 0.0, theta)["meridian_length_mm"])
    center_s = s_fraction * profile_length
    if not math.isclose(center_s, float(panel.get("center_s_mm", math.nan)),
                        rel_tol=0.0, abs_tol=1e-8):
        raise ValueError("preview panel center disagrees with the saved source-field receipt")
    geometry = _source_profile_point_normal(profile_rz_mm, center_s, theta)
    point = np.asarray(geometry["point_mm"], dtype=np.float64)
    normal = np.asarray(geometry["outward_normal"], dtype=np.float64)
    meridian_tangent = np.asarray(geometry["meridian_tangent"], dtype=np.float64)
    rim_up = -meridian_tangent
    if not np.isclose(np.linalg.norm(normal), 1.0, atol=1e-12):
        raise ValueError("profile-derived panel normal is not a unit vector")

    triangle_points = vertices[faces[outer]]
    face_centers = triangle_points.mean(axis=1)
    face_vectors = np.cross(triangle_points[:, 1] - triangle_points[:, 0],
                            triangle_points[:, 2] - triangle_points[:, 0])
    face_lengths = np.linalg.norm(face_vectors, axis=1)
    if np.any(face_lengths <= 0.0):
        raise ValueError("source outer wall contains a degenerate triangle")
    face_normals = face_vectors / face_lengths[:, None]
    nearest = np.argsort(np.linalg.norm(face_centers - point[None, :], axis=1))[:12]
    nearest_dots = face_normals[nearest] @ normal
    if float(np.min(nearest_dots)) < 0.85:
        raise ValueError("profile-derived outward normal disagrees with nearby source face normals")
    orientation_check = {
        "source_outer_face_normals_checked": int(len(nearest)),
        "minimum_dot_with_profile_outward_normal": float(np.min(nearest_dots)),
        "median_dot_with_profile_outward_normal": float(np.median(nearest_dots)),
        "nearest_face_centroid_distance_mm": float(np.max(
            np.linalg.norm(face_centers[nearest] - point[None, :], axis=1))),
        "passed": True,
    }

    detail_path = bundle / f"preview_{revision}_panel_detail.png"
    swatch_path = bundle / f"preview_{revision}_material_swatch.png"
    if detail_path.exists() or swatch_path.exists():
        raise FileExistsError("refusing to overwrite a panel detail or material swatch preview")

    detail_window = vtk.vtkRenderWindow()
    detail_window.SetOffScreenRendering(1)
    detail_window.SetSize(1400, 820)
    detail_window.SetMultiSamples(0)
    if lighting_mode == "studio_ibl" and hasattr(detail_window, "UseSRGBColorSpaceOn"):
        detail_window.UseSRGBColorSpaceOn()
    full_view_scale = max(float(panel.get("height_mm", 26.0)) * 1.35,
                          float(panel.get("width_mm", 45.0)) / 1.7)
    for index, (title, scale) in enumerate((
            ("Panel normal · full finite motif", full_view_scale),
            ("Panel normal · closeup", float(panel.get("height_mm", 26.0)) * 0.48))):
        renderer = vtk.vtkRenderer()
        renderer.SetViewport(0.5 * index, 0.0, 0.5 * (index + 1), 1.0)
        renderer.SetBackground(0.946, 0.929, 0.89)
        if lighting_mode == "studio_ibl":
            assert environment is not None
            _enable_studio_lighting(renderer, environment)
        else:
            _add_legacy_scene_lights(renderer, point, scale * 4.0)
        renderer.AddActor(outer_actor)
        _orient_renderer(renderer, focal=point, direction=normal, view_up=rim_up,
                         parallel_scale=scale)
        _decorate(renderer, title,
                  "Profile-derived outward normal; center fixed to field receipt")
        detail_window.AddRenderer(renderer)
    detail_window.Render()
    detail_pixels = _capture_png(detail_window, detail_path)
    detail_window.Finalize()

    swatch_albedo = np.median(np.asarray(material_albedo_linear, dtype=np.float64), axis=0)
    swatch_albedo = np.clip(swatch_albedo, 0.0, 1.0)
    srgb_color = _srgb8(swatch_albedo.reshape(1, 1, 3))[0, 0]
    swatch_image = vtk.vtkImageData()
    swatch_image.SetDimensions(8, 8, 1)
    color_pixels = np.tile(srgb_color[None, :], (64, 1)).astype(np.uint8)
    color_scalars = numpy_to_vtk(color_pixels, deep=True,
                                 array_type=vtk.VTK_UNSIGNED_CHAR)
    color_scalars.SetNumberOfComponents(3)
    swatch_image.GetPointData().SetScalars(color_scalars)
    swatch_texture = vtk.vtkTexture()
    swatch_texture.SetInputData(swatch_image)
    swatch_texture.SetColorModeToDirectScalars()
    swatch_texture.UseSRGBColorSpaceOn()
    swatch_texture.InterpolateOn()

    sphere = vtk.vtkSphereSource()
    sphere.SetRadius(1.0)
    sphere.SetThetaResolution(96)
    sphere.SetPhiResolution(64)
    sphere.Update()
    swatch_mapper = vtk.vtkPolyDataMapper()
    swatch_mapper.SetInputConnection(sphere.GetOutputPort())
    swatch_actor = vtk.vtkActor()
    swatch_actor.SetMapper(swatch_mapper)
    swatch_prop = swatch_actor.GetProperty()
    swatch_prop.SetInterpolationToPBR()
    swatch_prop.SetMetallic(0.0)
    swatch_prop.SetRoughness(float(np.clip(roughness, 0.02, 1.0)))
    swatch_prop.SetBaseIOR(float(np.clip(ior, 1.0, 3.0)))
    swatch_prop.SetBaseColorTexture(swatch_texture)
    swatch_prop.SetColor(1.0, 1.0, 1.0)

    swatch_window = vtk.vtkRenderWindow()
    swatch_window.SetOffScreenRendering(1)
    swatch_window.SetSize(720, 720)
    swatch_window.SetMultiSamples(0)
    if lighting_mode == "studio_ibl" and hasattr(swatch_window, "UseSRGBColorSpaceOn"):
        swatch_window.UseSRGBColorSpaceOn()
    swatch_renderer = vtk.vtkRenderer()
    swatch_renderer.SetBackground(0.30, 0.31, 0.32)
    if lighting_mode == "studio_ibl":
        assert environment is not None
        _enable_studio_lighting(swatch_renderer, environment)
    else:
        _add_legacy_scene_lights(swatch_renderer, np.zeros(3), 4.72)
    swatch_renderer.AddActor(swatch_actor)
    _orient_renderer(swatch_renderer, focal=np.zeros(3), direction=np.asarray([0., 0., 1.]),
                     view_up=np.asarray([0., 1., 0.]), parallel_scale=1.18)
    _decorate(swatch_renderer, "PBR material swatch · neutral studio IBL",
              "Median source material albedo; actual textured PBR render")
    swatch_window.AddRenderer(swatch_renderer)
    swatch_window.Render()
    swatch_pixels = _capture_png(swatch_window, swatch_path)
    swatch_srgb_enabled = bool(
        swatch_window.GetUsingSRGBColorSpace()
        if hasattr(swatch_window, "GetUsingSRGBColorSpace") else False)
    swatch_window.Finalize()
    h, w, _ = swatch_pixels.shape
    center_crop = swatch_pixels[h // 2 - 18:h // 2 + 18,
                                w // 2 - 18:w // 2 + 18].astype(np.float64)
    rendered_crop_median = np.median(center_crop, axis=(0, 1)).round(2).tolist()
    return [
        {
            "bundle": bundle.name,
            "preview": detail_path.name,
            "sha256": _sha256(detail_path),
            "view_definitions": ["Panel normal · full finite motif", "Panel normal · closeup"],
            "camera": {
                "focal_point_world_mm": point.tolist(),
                "direction_profile_outward_normal": normal.tolist(),
                "view_up_toward_rim": rim_up.tolist(),
                "projection": "orthographic",
                "parallel_scales_mm": [full_view_scale,
                                        float(panel.get("height_mm", 26.0)) * 0.48],
                "center_s_mm": center_s,
                "center_theta_rad": theta,
                "profile_meridian_length_mm": float(geometry["meridian_length_mm"]),
            },
            "native_normal_orientation_check": orientation_check,
            "environment": environment_info,
            "lighting_mode": lighting_mode,
            "renderer": "VTK PBR appearance proxy with neutral linear-RGB studio IBL",
            "geometry_array_sha256": _array_geometry_hash(vertices, faces),
            "source_numeric_panel_receipt_sha256": numeric_receipt_hash,
            "panel_field_file_sha256": _sha256(bundle / "bluewhite_panel_fields.npz"),
        },
        {
            "bundle": bundle.name,
            "preview": swatch_path.name,
            "sha256": _sha256(swatch_path),
            "view_definitions": ["PBR material swatch · neutral studio IBL"],
            "input_material_albedo_linear_rgb": swatch_albedo.tolist(),
            "texture_srgb8": srgb_color.astype(int).tolist(),
            "roughness": float(roughness),
            "ior": float(ior),
            "metallic": 0.0,
            "rendered_center_crop_median_srgb8": rendered_crop_median,
            "rendered_center_crop_size_px": [int(center_crop.shape[1]),
                                             int(center_crop.shape[0])],
            "environment": environment_info,
            "lighting_mode": lighting_mode,
            "render_window_srgb_enabled": swatch_srgb_enabled,
            "renderer": "VTK PBR appearance proxy with neutral linear-RGB studio IBL",
        },
    ]


def render(bundle: Path, preview_revision: str = "v3",
           lighting_mode: str = "legacy") -> dict[str, object]:
    if lighting_mode not in {"legacy", "studio_ibl"}:
        raise ValueError("lighting_mode must be 'legacy' or 'studio_ibl'")
    png_path = bundle / f"preview_{preview_revision}_4view.png"
    if png_path.exists():
        raise FileExistsError(f"refusing to overwrite preview: {png_path}")
    with np.load(bundle / "geometry_and_fields.npz", allow_pickle=False) as arrays:
        vertices = np.asarray(arrays["vertices_mm"], dtype=np.float64)
        faces = np.asarray(arrays["faces"], dtype=np.int64)
        profile_rz_mm = np.asarray(arrays["outer_profile_rz_mm"], dtype=np.float64)
        outer = np.asarray(arrays["face_outer_texture_mask"], dtype=bool)
        uv_by_face = np.asarray(arrays["face_outer_texture_uv"], dtype=np.float64)
        face_tags = np.asarray(arrays["face_surface_tag"], dtype=np.int32)
        combined = np.asarray(arrays["face_combined_albedo_linear_rgb"], dtype=np.float64)
        material_albedo = np.asarray(arrays["face_material_albedo_linear_rgb"],
                                     dtype=np.float64)
        combined_roughness = np.asarray(arrays["face_combined_roughness"], dtype=np.float64)
        material_ior = np.asarray(arrays["face_material_ior"], dtype=np.float64)
        source_face_ids = np.asarray(arrays["face_source_brep_face_index"], dtype=np.int64)
        smoothing_groups = np.asarray(arrays["face_display_normal_group"], dtype=np.int64)
    provenance = json.loads((bundle / "provenance.json").read_text(encoding="utf-8"))
    recipe = json.loads((bundle / "recipe.json").read_text(encoding="utf-8"))
    is_bluewhite_panel = (
        recipe.get("pattern", {}).get("style_id") == "met_50899_partial_dragon_panel")
    view_defs = list(VIEW_DEFS)
    if is_bluewhite_panel:
        # theta=pi is the -X meridian under the registered [r*cos(theta),r*sin(theta)] chart.
        # Aim the lit view at that finite panel so the preview reviews the source mapping,
        # without widening or moving the recipe panel after its field receipt was made.
        view_defs[2] = ("Lit 3D · perspective · panel-facing", (-1.0, 0.0, 0.55),
                        (0.0, 0.0, 1.0), False)
    tag_names = {int(code): name for code, name in
                 provenance.get("surface_tag_map", {}).items()}
    if vertices.ndim != 2 or faces.ndim != 2 or not np.all(np.isfinite(vertices)):
        raise ValueError(f"malformed geometry arrays in {bundle}")
    if faces.shape != (len(outer), 3) or uv_by_face.shape != (len(faces), 3, 2):
        raise ValueError(f"malformed outer-wall texture coordinates in {bundle}")
    if (combined.shape != (len(faces), 3) or combined_roughness.shape != (len(faces),)
            or material_ior.shape != (len(faces),)
            or source_face_ids.shape != (len(faces),)
            or smoothing_groups.shape != (len(faces),)):
        raise ValueError(f"malformed appearance or source-face arrays in {bundle}")
    if not np.array_equal(outer, face_tags == 0):
        raise ValueError("saved texture mask does not match the outer_wall tag")
    geometry_hash = _array_geometry_hash(vertices, faces)
    bundle_manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    if geometry_hash != bundle_manifest.get("geometry_array_sha256"):
        raise ValueError("saved preview geometry hash differs from the composed source geometry")
    for filename, expected_hash in bundle_manifest.get("file_sha256", {}).items():
        path = bundle / filename
        if not path.is_file() or _sha256(path) != expected_hash:
            raise ValueError(f"bundle file hash mismatch before render: {filename}")
    panel_fields_path = bundle / "bluewhite_panel_fields.npz"
    panel_fields_sha256_before = (_sha256(panel_fields_path)
                                  if panel_fields_path.is_file() else None)
    if not np.isfinite(uv_by_face[outer]).all():
        raise ValueError("outer-wall texture coordinates contain a NaN or infinity")
    spans = np.ptp(uv_by_face[outer, :, 0], axis=1)
    if np.any(spans > 0.5 + 1e-6):
        raise ValueError("outer-wall face texture coordinates cross the periodic seam")

    corner_normals = _source_corner_normals(vertices, faces, smoothing_groups)

    def display_poly(face_mask: np.ndarray, *, with_uv: bool = False,
                     flip_v_at_renderer_boundary: bool = False) -> vtk.vtkPolyData:
        subset = faces[face_mask]
        points = vertices[subset].reshape(-1, 3)
        normals = corner_normals[face_mask].reshape(-1, 3)
        cells = np.arange(len(subset) * 3, dtype=np.int64).reshape(-1, 3)
        uv = uv_by_face[face_mask].copy() if with_uv else None
        if uv is not None and flip_v_at_renderer_boundary:
            # Saved UV v is semantic chart arclength s/L. VTK's PNG/OpenGL texture convention
            # maps v=0 to the PNG bottom row, so invert only the display-coordinate binding.
            uv[:, :, 1] = 1.0 - uv[:, :, 1]
        return _polydata(points, cells, point_normals=normals,
                         uv=uv.reshape(-1, 2) if uv is not None else None,
                         cell_rgb=None if with_uv else _srgb8(combined[face_mask]))

    outer_actor = _actor(
        display_poly(outer, with_uv=True,
                     flip_v_at_renderer_boundary=True),
        texture_path=bundle / "outer_texture_srgb.png",
        roughness=float(np.median(combined_roughness[outer])),
        ior=float(np.median(material_ior[outer])))
    region_actors: list[vtk.vtkActor] = []
    material_rendering: dict[str, dict[str, float]] = {}
    for tag in sorted(set(face_tags.tolist()) - {0}):
        mask = face_tags == tag
        if not np.any(mask):
            continue
        roughness = float(np.median(combined_roughness[mask]))
        ior = float(np.median(material_ior[mask]))
        actor = _actor(display_poly(mask), roughness=roughness, ior=ior)
        region_actors.append(actor)
        material_rendering[tag_names.get(int(tag), str(int(tag)))] = {
            "roughness_median_from_combined_face_field": roughness,
            "roughness_range": [float(np.min(combined_roughness[mask])),
                                float(np.max(combined_roughness[mask]))],
            "ior_median_from_material_face_field": ior,
            "ior_range": [float(np.min(material_ior[mask])),
                          float(np.max(material_ior[mask]))],
        }
    material_rendering["outer_wall"] = {
        "roughness_median_from_combined_face_field": float(
            np.median(combined_roughness[outer])),
        "roughness_range": [float(np.min(combined_roughness[outer])),
                            float(np.max(combined_roughness[outer]))],
        "ior_median_from_material_face_field": float(np.median(material_ior[outer])),
        "ior_range": [float(np.min(material_ior[outer])), float(np.max(material_ior[outer]))],
    }
    if lighting_mode == "studio_ibl":
        environment, environment_info = _neutral_studio_environment()
    else:
        environment = None
        environment_info = {
            "model": "existing four-scene-light preview setup",
            "image_based_lighting": False,
            "calibrated_optics": False,
            "scene_light_intensities": [1.10, 0.55, 0.38, 0.42],
        }

    bounds = np.asarray([vertices.min(axis=0), vertices.max(axis=0)])
    center = bounds.mean(axis=0)
    span = bounds[1] - bounds[0]
    camera_distance = float(np.max(span) * 2.8)
    window = vtk.vtkRenderWindow()
    window.SetOffScreenRendering(1)
    window.SetSize(1280, 980)
    window.SetMultiSamples(0)
    if lighting_mode == "studio_ibl" and hasattr(window, "UseSRGBColorSpaceOn"):
        window.UseSRGBColorSpaceOn()
    renderers: list[vtk.vtkRenderer] = []
    for index, (title, direction, view_up, orthographic) in enumerate(view_defs):
        row, col = divmod(index, 2)
        viewport = (0.5 * col, 0.5 * (1 - row), 0.5 * (col + 1), 0.5 * (2 - row))
        renderer = vtk.vtkRenderer()
        renderer.SetViewport(*viewport)
        renderer.SetBackground(0.946, 0.929, 0.89)
        if lighting_mode == "studio_ibl":
            assert environment is not None
            _enable_studio_lighting(renderer, environment)
        renderer.AddActor(outer_actor)
        for actor in region_actors:
            renderer.AddActor(actor)
        else:
            _add_legacy_scene_lights(renderer, center, camera_distance)
        cam = renderer.GetActiveCamera()
        cam.SetFocalPoint(*center)
        direction_vec = np.asarray(direction, dtype=np.float64)
        direction_vec /= np.linalg.norm(direction_vec)
        cam.SetPosition(*(center + camera_distance * direction_vec))
        cam.SetViewUp(*view_up)
        if orthographic:
            cam.ParallelProjectionOn()
            cam.SetParallelScale(float(max(span[0], span[1]) * 0.83))
        else:
            cam.ParallelProjectionOff()
            cam.SetViewAngle(31.0)
        renderer.ResetCameraClippingRange()
        _decorate(renderer, title,
                  "Glaze appearance: outer + inside floor/wall + rim | bare body: foot/underside")
        window.AddRenderer(renderer)
        renderers.append(renderer)

    window.Render()
    _capture_png(window, png_path)
    window_srgb_enabled = bool(
        window.GetUsingSRGBColorSpace()
        if hasattr(window, "GetUsingSRGBColorSpace") else False)
    window.Finalize()
    panel_previews: list[dict[str, object]] = []
    if is_bluewhite_panel:
        panel_receipt_path = bundle / "bluewhite_panel_receipt.json"
        panel_receipt = json.loads(panel_receipt_path.read_text(encoding="utf-8"))
        panel_controls = recipe["pattern"].get("mapping_and_spread_controls", {})
        panel_previews = _render_panel_detail(
            bundle, preview_revision, vertices=vertices, faces=faces, outer=outer,
            outer_actor=outer_actor, profile_rz_mm=profile_rz_mm,
            material_albedo_linear=material_albedo[outer],
            roughness=float(np.median(combined_roughness[outer])),
            ior=float(np.median(material_ior[outer])), lighting_mode=lighting_mode,
            environment=environment,
            environment_info=environment_info)
        geometry_hash_after_preview = _array_geometry_hash(vertices, faces)
        panel_fields_sha256_after = _sha256(panel_fields_path)
        if (geometry_hash_after_preview != geometry_hash
                or panel_fields_sha256_after != panel_fields_sha256_before):
            raise RuntimeError("preview rendering changed saved geometry or panel field evidence")
        panel_receipt["preview_scene"] = {
            "preview_revision": preview_revision,
            "environment": environment_info,
            "mapping_controls_sha256": hashlib.sha256(json.dumps(
                panel_controls, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            "source_numeric_panel_receipt_sha256": hashlib.sha256(json.dumps(
                {key: value for key, value in panel_receipt.items()
                 if key != "preview_scene"}, ensure_ascii=False, sort_keys=True,
                separators=(",", ":")).encode("utf-8")).hexdigest(),
            "source_field_npz_sha256_before": panel_fields_sha256_before,
            "source_field_npz_sha256_after": panel_fields_sha256_after,
            "source_geometry_array_sha256_before": geometry_hash,
            "source_geometry_array_sha256_after": geometry_hash_after_preview,
            "field_arrays_unchanged": panel_fields_sha256_after == panel_fields_sha256_before,
            "geometry_arrays_unchanged": geometry_hash_after_preview == geometry_hash,
            "details": panel_previews,
        }
        panel_receipt_path.write_text(json.dumps(panel_receipt, ensure_ascii=False,
                                                 sort_keys=True, indent=2) + "\n",
                                      encoding="utf-8")
    receipt_path = bundle / "sha256_receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["file_sha256"][png_path.name] = _sha256(png_path)
    for panel_preview in panel_previews:
        preview_path = bundle / str(panel_preview["preview"])
        receipt["file_sha256"][preview_path.name] = _sha256(preview_path)
    if panel_previews:
        receipt["file_sha256"]["bluewhite_panel_receipt.json"] = _sha256(
            bundle / "bluewhite_panel_receipt.json")
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False,
                                       sort_keys=True, indent=2) + "\n", encoding="utf-8")
    bundle_manifest["file_sha256"] = {
        name: value for name, value in receipt["file_sha256"].items()
    }
    bundle_manifest["file_sha256"][receipt_path.name] = _sha256(receipt_path)
    (bundle / "manifest.json").write_text(
        json.dumps(bundle_manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8")
    return {
        "bundle": bundle.name,
        "preview": png_path.name,
        "sha256": _sha256(png_path),
        "panel_details": panel_previews,
        "faces": int(len(faces)),
        "texture_grid": [512, 1024],
        "view_definitions": [title for title, _, _, _ in view_defs],
        "view_specs": [{"title": title, "camera_direction": list(direction),
                        "view_up": list(view_up), "orthographic": bool(orthographic)}
                       for title, direction, view_up, orthographic in view_defs],
        "renderer": "VTK PBR appearance proxy; outer chart texture and per-region face appearance",
        "display_normals": {
            "method": "area-weighted normals accumulated over original shared source mesh vertices before UV triangle-corner duplication",
            "smoothing_groups": "exact source CAD face ancestry; adjacent serialized segment faces blend only at C1 section joins (dot >= 0.9995)",
            "source_geometry_mutated": False,
            "source_face_id_array_sha256": hashlib.sha256(
                np.ascontiguousarray(source_face_ids).tobytes()).hexdigest(),
        },
        "pbr_material_parameters": material_rendering,
        "pbr_parameter_status": "per-region medians from source-conditioned design fields; uncalibrated appearance proxy",
        "lighting": {
            "mode": lighting_mode,
            "environment": environment_info,
            "direct_scene_lights": 0 if lighting_mode == "studio_ibl" else 4,
            "render_window_srgb_enabled": window_srgb_enabled,
            "purpose": "neutral studio presentation to inspect the rendered appearance",
            "calibrated_optics": False,
        },
        "legend": ("Glaze appearance on outer wall, inside wall/floor, and rim; bare body on foot and exterior underside"),
        "color_space": "linear RGB fields converted to sRGB8 texture/cell colors; VTK displays sRGB colors",
        "texture_coordinate_conversion": {
            "saved_uv_semantics": "u=wrapped theta/(2*pi); v=s/total_source_meridian_length",
            "renderer_v": "t=1-v for every PNG base-color texture; saved chart UV remains v=s/L",
        },
        "geometry_array_sha256": geometry_hash,
        "bundle_manifest_sha256": _sha256(bundle / "manifest.json"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help="completed experiment output directory")
    parser.add_argument("--preview-revision", default="v3",
                        help="unique lowercase slug used for new preview filenames/manifests")
    parser.add_argument("--lighting", choices=("legacy", "studio_ibl"), default="legacy",
                        help="lighting preset shared by every material in this experiment; legacy is the historical default")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", args.preview_revision):
        raise ValueError("--preview-revision must be a lowercase filename-safe slug")
    output_root = args.output.expanduser().resolve()
    manifest_path = output_root / "experiment_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"experiment manifest is missing: {manifest_path}")
    preview_manifest_path = output_root / f"preview_manifest_{args.preview_revision}.json"
    if preview_manifest_path.exists():
        raise FileExistsError(f"refusing to overwrite preview manifest: {preview_manifest_path}")
    experiment = json.loads(manifest_path.read_text(encoding="utf-8"))
    instance_rows = experiment.get("instances", [])
    if not 1 <= len(instance_rows) <= 8:
        raise ValueError(f"expected one to eight generated instances, found {len(instance_rows)}")
    rows = [render(output_root / item["bundle"], args.preview_revision,
                   lighting_mode=args.lighting)
            for item in instance_rows]
    texture_origin_probe = None
    if any(item.get("pattern_style") == "met_50899_partial_dragon_panel"
           for item in instance_rows):
        if args.lighting == "studio_ibl":
            probe_environment, probe_environment_info = _neutral_studio_environment()
        else:
            probe_environment = None
            probe_environment_info = {
                "model": "existing four-scene-light preview setup",
                "image_based_lighting": False,
                "calibrated_optics": False,
                "scene_light_intensities": [1.10, 0.55, 0.38, 0.42],
            }
        texture_origin_probe = _render_texture_origin_probe(
            output_root, args.preview_revision, args.lighting,
            probe_environment, probe_environment_info)
    manifest = {
        "schema": "synlab.reference_generation_preview_manifest.v5",
        "preview_revision": args.preview_revision,
        "lighting_mode": args.lighting,
        "renderer": "VTK PBR appearance proxy with continuous outer-wall texture and source-conditioned per-region appearance",
        "preview_views": rows[0]["view_definitions"],
        "view_specs": rows[0]["view_specs"],
        "panel_detail_artifacts": [
            artifact for row in rows for artifact in row.get("panel_details", [])],
        "lighting": rows[0]["lighting"],
        "texture_origin_probe": texture_origin_probe,
        "texture_color_conversion": "linear RGB appearance samples converted to sRGB8 texture/cell colors for display",
        "normal_policy": "source shared-vertex normals computed before UV duplication; only source CAD ancestry and C1 section joins are blended",
        "side_view_direction": [0.0, -1.0, 0.0],
        "surface_finish_legend": "outer wall / inside wall and floor / rim receive glaze appearance; foot / exterior underside remain bare body",
        "geometry_changed": False,
        "physical_rendering_claim": "NONE",
        "files": rows,
    }
    preview_manifest_path.write_text(json.dumps(manifest, ensure_ascii=False,
                                                sort_keys=True, indent=2) + "\n",
                    encoding="utf-8")
    experiment["previews"] = {
        "manifest": preview_manifest_path.name,
        "manifest_sha256": _sha256(preview_manifest_path),
        "files": rows,
        "texture_origin_probe": texture_origin_probe,
    }
    for item, preview in zip(experiment["instances"], rows):
        item["bundle_manifest_sha256"] = preview["bundle_manifest_sha256"]
        item["preview_sha256"] = preview["sha256"]
        bundle = output_root / item["bundle"]
        item["files"][preview["preview"]] = preview["sha256"]
        for detail in preview.get("panel_details", []):
            item["files"][detail["preview"]] = detail["sha256"]
        item["files"]["sha256_receipt.json"] = _sha256(bundle / "sha256_receipt.json")
        item["files"]["manifest.json"] = preview["bundle_manifest_sha256"]
    for _ in range(10):
        current_total = sum(path.stat().st_size for path in output_root.rglob("*")
                            if path.is_file() and path != manifest_path)
        payload = json.dumps(experiment, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        disk_payload = payload.replace("\n", os.linesep)
        output_bytes = current_total + len(disk_payload.encode("utf-8"))
        if experiment.get("output_bytes") == output_bytes:
            break
        experiment["output_bytes"] = output_bytes
    payload = json.dumps(experiment, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    manifest_path.write_bytes(payload.replace("\n", os.linesep).encode("utf-8"))
    actual_total = sum(path.stat().st_size for path in output_root.rglob("*")
                       if path.is_file())
    if actual_total != experiment.get("output_bytes"):
        raise RuntimeError("experiment output byte count did not converge to the exact total")
    if actual_total > 256 * 1024 * 1024:
        raise RuntimeError("rendered experiment exceeds the 256 MiB output limit")
    print(json.dumps({"previews": len(rows), "manifest": str(preview_manifest_path),
                      "manifest_sha256": _sha256(preview_manifest_path)},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
