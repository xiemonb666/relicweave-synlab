from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import numpy as np


ROOT = Path(__file__).resolve().parents[3]
VF_SRC = ROOT / "vesselforge" / "src"
if str(VF_SRC) not in sys.path:
    sys.path.insert(0, str(VF_SRC))

from vesselforge.reference_mesh import (  # noqa: E402
    DeformationControls,
    SourceProvenance,
    deform_reference_mesh,
)


SOURCE_DIR = ROOT / "third_party" / "reference-assets" / "apsida-shm17946-0047"
SOURCE_OBJ = SOURCE_DIR / "Footed_Bowl_SHM_17946_0047.obj"
RAW_NPZ = ROOT / "vesselforge" / "experiments" / "continuation_20261015" / "scanned_anchor_audit" / "raw_geometry.npz"
AUDIT_JSON = RAW_NPZ.parent / "mesh_audit.json"
OUT = Path(__file__).resolve().parent / "run01"

SOURCE_URL = "https://apsida.cut.ac.cy/items/show/49281"
LICENSE_URL = "https://creativecommons.org/licenses/by-sa/4.0/"
SOURCE_SCALE_MM_PER_UNIT = 1000.0
CENTER_SOURCE = np.array(
    [0.05191771229236255, -0.007930005189105168, 0.077194], dtype=np.float64
)
AXIS_SOURCE = np.array([0.0, 0.0, 1.0], dtype=np.float64)

VARIANTS = {
    "base_anchor": DeformationControls(),
    "fuller_belly": DeformationControls(belly_fullness=0.055),
    "broader_upper_and_rim": DeformationControls(
        upperbody_width=0.035, mouth_width=0.045
    ),
    "broader_foot": DeformationControls(foot_width=0.055),
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_obj_vertex_rgb(path: Path, expected_count: int) -> tuple[np.ndarray, dict[str, int]]:
    colors: list[tuple[float, float, float]] = []
    counts = {"vt": 0, "vn": 0, "faces": 0}
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for line in stream:
            row = line.strip()
            if not row or row.startswith("#"):
                continue
            tag, *fields = row.split()
            if tag == "v":
                if len(fields) < 6:
                    raise ValueError("source OBJ vertex row lacks its RGB payload")
                colors.append(tuple(float(value) for value in fields[3:6]))
            elif tag == "vt":
                counts["vt"] += 1
            elif tag == "vn":
                counts["vn"] += 1
            elif tag == "f":
                counts["faces"] += 1
    if len(colors) != expected_count:
        raise ValueError(
            f"source OBJ has {len(colors)} colored vertices; expected {expected_count}"
        )
    return np.asarray(colors, dtype=np.float64), counts


def _vtk_polydata(vertices: np.ndarray, faces: np.ndarray, colors: np.ndarray):
    import vtk
    from vtk.util.numpy_support import numpy_to_vtk, numpy_to_vtkIdTypeArray

    points = vtk.vtkPoints()
    points.SetData(numpy_to_vtk(np.ascontiguousarray(vertices), deep=True))
    connectivity = np.empty((len(faces), 4), dtype=np.int64)
    connectivity[:, 0] = 3
    connectivity[:, 1:] = faces
    cells = vtk.vtkCellArray()
    offsets = np.arange(len(faces) + 1, dtype=np.int64) * 3
    cells.SetData(
        numpy_to_vtkIdTypeArray(np.ascontiguousarray(offsets), deep=True),
        numpy_to_vtkIdTypeArray(np.ascontiguousarray(faces).reshape(-1), deep=True),
    )
    polydata = vtk.vtkPolyData()
    polydata.SetPoints(points)
    polydata.SetPolys(cells)
    vtk_colors = numpy_to_vtk(np.ascontiguousarray(colors, dtype=np.float32), deep=True)
    vtk_colors.SetName("source vertex RGB")
    polydata.GetPointData().SetScalars(vtk_colors)

    # Recomputed normals are temporary display data; source geometry and
    # vertex-color attributes are preserved in the output NPZ.
    normals = vtk.vtkPolyDataNormals()
    normals.SetInputData(polydata)
    normals.SplittingOff()
    normals.ConsistencyOff()
    normals.AutoOrientNormalsOff()
    normals.ComputeCellNormalsOff()
    normals.ComputePointNormalsOn()
    normals.Update()
    return normals.GetOutput()


def render_four_views(
    vertices: np.ndarray,
    faces: np.ndarray,
    colors: np.ndarray,
    output_png: Path,
    parallel_scale: float,
    *,
    use_source_rgb: bool,
) -> None:
    import vtk

    directions = [
        ("SIDE", (0.0, -1.0, 0.0), (0.0, 0.0, 1.0)),
        ("FRONT", (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
        ("TOP", (0.0, 0.0, 1.0), (0.0, 1.0, 0.0)),
        ("OBLIQUE", (2.6, -3.4, 1.4), (0.0, 0.0, 1.0)),
    ]
    mesh = _vtk_polydata(vertices, faces, colors)
    window = vtk.vtkRenderWindow()
    window.SetOffScreenRendering(1)
    window.SetSize(1600, 1200)
    window.SetMultiSamples(0)
    center = (0.0, 0.0, 0.0)
    camera_distance = max(float(np.linalg.norm(vertices, axis=1).max()) * 5.0, 100.0)

    for index, (label, direction, view_up) in enumerate(directions):
        column, row = index % 2, index // 2
        viewport = (
            column * 0.5,
            0.5 if row == 0 else 0.0,
            (column + 1) * 0.5,
            1.0 if row == 0 else 0.5,
        )
        renderer = vtk.vtkRenderer()
        renderer.SetViewport(*viewport)
        renderer.SetBackground(0.94, 0.94, 0.93)
        actor = vtk.vtkActor()
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputData(mesh)
        mapper.SetScalarModeToUsePointData()
        mapper.SetColorModeToDirectScalars()
        mapper.SetScalarVisibility(bool(use_source_rgb))
        actor.SetMapper(mapper)
        if not use_source_rgb:
            actor.GetProperty().SetColor(0.72, 0.65, 0.54)
        actor.GetProperty().SetInterpolationToPhong()
        actor.GetProperty().SetAmbient(0.24)
        actor.GetProperty().SetDiffuse(0.78)
        actor.GetProperty().SetSpecular(0.06)
        actor.GetProperty().SetSpecularPower(20.0)
        renderer.AddActor(actor)

        camera = vtk.vtkCamera()
        direction_vector = np.asarray(direction, dtype=np.float64)
        direction_vector /= np.linalg.norm(direction_vector)
        camera.SetFocalPoint(*center)
        camera.SetPosition(*(direction_vector * camera_distance))
        camera.SetViewUp(*view_up)
        camera.SetParallelProjection(True)
        camera.SetParallelScale(parallel_scale)
        renderer.SetActiveCamera(camera)
        renderer.ResetCameraClippingRange()

        label_actor = vtk.vtkTextActor()
        label_actor.SetInput(label)
        label_actor.GetTextProperty().SetFontSize(22)
        label_actor.GetTextProperty().SetColor(0.12, 0.12, 0.12)
        label_actor.GetTextProperty().SetBold(True)
        label_actor.SetDisplayPosition(column * 800 + 18, 1160 if row == 0 else 560)
        renderer.AddViewProp(label_actor)
        window.AddRenderer(renderer)

    window.Render()
    image = vtk.vtkWindowToImageFilter()
    image.SetInput(window)
    image.SetInputBufferTypeToRGB()
    image.ReadFrontBufferOff()
    image.Update()
    writer = vtk.vtkPNGWriter()
    writer.SetFileName(str(output_png))
    writer.SetInputConnection(image.GetOutputPort())
    writer.Write()
    window.Finalize()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with np.load(RAW_NPZ, allow_pickle=False) as archive:
        vertices = np.asarray(archive["vertices_source_units"], dtype=np.float64)
        faces = np.asarray(archive["faces"], dtype=np.int64)
    colors, source_obj_attribute_counts = parse_obj_vertex_rgb(SOURCE_OBJ, len(vertices))
    audit = json.loads(AUDIT_JSON.read_text(encoding="utf-8"))
    provenance = SourceProvenance(
        source_name="Footed bowl, SHM 17946:0047",
        source_url=SOURCE_URL,
        license_id="CC BY-SA 4.0",
        attribution=(
            "Medelhavsmuseet, SHM 17946:0047; via Apsida / Digital Heritage Research Lab"
        ),
        raw_source_sha256=sha256_file(SOURCE_OBJ),
        scale_evidence=(
            "The OBJ declares no units. Explicit candidate calibration is 1 raw unit = 1 m "
            "(1000 mm/raw unit), inferred from reported catalog height 119 mm versus raw Z "
            "span 0.119432; this is not a calibrated unit declaration, and reported rim/base "
            "diameters do not match this candidate exactly."
        ),
        source_component_count=int(audit["edge_graph_component_count"]),
    )

    raw_bounds = np.ptp(vertices, axis=0)
    # All views use the same physical parallel-camera scale, fixed from the
    # calibrated source anchor and shared by every control variant.
    base_extent_mm = raw_bounds * SOURCE_SCALE_MM_PER_UNIT
    parallel_scale = max(float(base_extent_mm.max()) * 0.68, 80.0)
    color_hash = hashlib.sha256(
        b"float64-rgb\0"
        + np.asarray(colors.shape, dtype="<i8").tobytes()
        + np.ascontiguousarray(colors, dtype="<f8").tobytes()
    ).hexdigest()

    index: dict[str, object] = {
        "schema": "vesselforge.reference_mesh_variation_experiment.v1",
        "source": {
            **provenance.__dict__,
            "raw_geometry_npz_sha256": sha256_file(RAW_NPZ),
            "source_obj_attribute_counts": source_obj_attribute_counts,
            "source_vertex_rgb_sha256": color_hash,
            "license_url": LICENSE_URL,
            "catalog_reported_dimensions_mm": {
                "height": 119.0,
                "base_diameter": 70.0,
                "rim_diameter": 160.0,
            },
        },
        "frame": {
            "center_source_coordinates": CENTER_SOURCE.tolist(),
            "axis_unit_vector": AXIS_SOURCE.tolist(),
            "interpretation": "candidate upright Z axis; not a source-declared frame",
        },
        "inherited_source_audit": {
            "edge_connected_components": audit["edge_graph_component_count"],
            "largest_component_face_count": audit["largest_component"]["face_count"],
            "largest_component_fraction_of_faces": audit["largest_component_face_fraction"],
            "largest_component_fraction_of_area": audit["largest_component_surface_area_fraction"],
            "degenerate_triangle_count": audit["degenerate_triangle_count_area_lt_1e-12_raw_units2"],
            "exact_duplicate_xyz_vertex_count": audit["exact_duplicate_xyz_vertex_count"],
            "boundary_edge_count": audit["boundary_edge_count"],
            "nonmanifold_edge_count": audit["nonmanifold_edge_count_incidence_gt2"],
            "source_surface_only": audit["surface_only_input"],
            "note": "All original face indices and vertices are retained. Component diagnostics inherit directly from the source audit; no component is discarded or repaired.",
        },
        "view_contract": {
            "camera_projection": "parallel",
            "parallel_scale_mm": parallel_scale,
            "same_camera_and_physical_scale_for_all_variants": True,
            "views": ["side", "front", "top", "oblique"],
        },
        "variants": {},
    }

    for name, controls in VARIANTS.items():
        result = deform_reference_mesh(
            vertices,
            faces,
            center=CENTER_SOURCE,
            axis=AXIS_SOURCE,
            source_unit_scale_to_mm=SOURCE_SCALE_MM_PER_UNIT,
            controls=controls,
            provenance=provenance,
            vertex_attributes=colors,
        )
        variant_dir = OUT / name
        variant_dir.mkdir(parents=True, exist_ok=True)
        mesh_file = variant_dir / "mesh.npz"
        np.savez_compressed(
            mesh_file,
            vertices_mm=result.vertices_mm,
            faces=result.faces,
            source_vertex_rgb=result.vertex_attributes,
        )
        mesh_file_sha256 = sha256_file(mesh_file)
        mesh_receipt = result.receipt
        mesh_receipt["mesh"]["derived_mesh_npz_sha256"] = mesh_file_sha256
        mesh_receipt["source_audit_inheritance"] = {
            "source_connected_components": audit["edge_graph_component_count"],
            "derived_connected_components_expected_unchanged": audit["edge_graph_component_count"],
            "source_degenerate_triangles": audit["degenerate_triangle_count_area_lt_1e-12_raw_units2"],
            "source_face_array_sha256": hashlib.sha256(
                np.ascontiguousarray(faces, dtype="<i8").tobytes()
            ).hexdigest(),
            "face_array_exactly_preserved": bool(np.array_equal(result.faces, faces)),
            "vertex_rgb_exactly_preserved": bool(
                np.array_equal(result.vertex_attributes, colors)
            ),
            "source_obj_attribute_inventory": source_obj_attribute_counts,
            "source_vertex_rgb_sha256": color_hash,
            "raw_geometry_npz_sha256": sha256_file(RAW_NPZ),
            "auxiliary_obj_uv_and_normal_data": (
                "Retained unchanged in the hash-identified source OBJ; derived NPZ carries the original RGB values and indexed triangle geometry."
            ),
        }
        (variant_dir / "receipt.json").write_text(
            json.dumps(mesh_receipt, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        render_four_views(
            result.vertices_mm,
            result.faces,
            colors,
            variant_dir / "views.png",
            parallel_scale,
            use_source_rgb=False,
        )
        render_four_views(
            result.vertices_mm,
            result.faces,
            colors,
            variant_dir / "source_color_views.png",
            parallel_scale,
            use_source_rgb=True,
        )
        index["variants"][name] = {
            "controls": mesh_receipt["controls"],
            "target_height_mm": mesh_receipt["transform"]["target_height_mm"],
            "derived_geometry_sha256": mesh_receipt["mesh"]["derived_geometry_sha256"],
            "derived_mesh_npz_sha256": mesh_file_sha256,
            "bounds_mm": {
                "min": result.vertices_mm.min(axis=0).tolist(),
                "max": result.vertices_mm.max(axis=0).tolist(),
                "extent": np.ptp(result.vertices_mm, axis=0).tolist(),
            },
            "sampled_jacobian_metrics": mesh_receipt["sampled_jacobian_metrics"],
            "mesh_file": str(mesh_file.relative_to(OUT)),
            "receipt_file": str((variant_dir / "receipt.json").relative_to(OUT)),
            "views_file": str((variant_dir / "views.png").relative_to(OUT)),
            "source_color_views_file": str(
                (variant_dir / "source_color_views.png").relative_to(OUT)
            ),
        }

    (OUT / "experiment.json").write_text(
        json.dumps(index, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
