from __future__ import annotations

import hashlib
import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[6]
sys.path.insert(0, str(REPO_ROOT / "vesselforge" / "src"))
sys.path.insert(0, str(REPO_ROOT / "vesselforge"))

import cadquery as cq
import numpy as np
import OCP
from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.BRepClass3d import BRepClass3d_SolidClassifier
from OCP.GeomAbs import GeomAbs_BSplineCurve
from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector
from OCP.Bnd import Bnd_Box
from OCP.gp import gp_Dir, gp_Lin, gp_Pnt

from experiments.brep_persistence_helper import (
    build_exact_profile_candidate,
    save_actual_brep_preview,
)
from experiments.smooth_cad_spike import (
    MESH_ANGULAR_RAD,
    _native_curve_inventory,
    _shape_bbox,
    measure_floor_thickness,
    sample_sidewall_normal_rays,
)
from vesselforge.geometry import (
    VesselSpec,
    mesh_shape,
    mesh_topology_metrics,
    sampled_mesh_to_cad_metrics,
)

ROOT = Path(__file__).resolve().parent
GEOMETRY = ROOT / "geometry"
REPORT_PATH = ROOT / "brep_candidate_report.json"
BODY_BREP = GEOMETRY / "smooth_body.brep"
ATTEMPT_MARKER = ROOT / "native_brep_write_attempted.marker"
DESIGN_ROOT = (
    REPO_ROOT
    / "relicweave-synlab"
    / "tmp"
    / "review_20261003"
    / "implementation"
    / "vf"
    / "smooth_cad"
    / "candidate2_native_2d_offset_wall4"
)
sys.path.insert(0, str(DESIGN_ROOT))
import candidate2_physical_profile as design  # noqa: E402

WALL_MM = 4.0
SPEC = VesselSpec(
    body_width_mm=41.0,
    body_height_mm=56.0,
    wall_mm=WALL_MM,
    tessellation_linear_mm=0.05,
    tessellation_angular_rad=MESH_ANGULAR_RAD,
)

REFERENCE_VOLUME_MM3 = 26998.301999424355
REFERENCE_BBOX_MM = {
    "xmin_mm": -20.5000001,
    "ymin_mm": -20.5000001,
    "zmin_mm": -1e-7,
    "xmax_mm": 20.5000001,
    "ymax_mm": 20.5000001,
    "zmax_mm": 56.0000001,
}
ROUNDTRIP_TOLERANCE_MM = 0.01
ROUNDTRIP_TOLERANCE_MM3 = 0.01


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_report(report: dict[str, Any]) -> None:
    REPORT_PATH.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False, default=json_default) + "\n",
        encoding="utf-8",
    )


def json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def shape_summary(shape: cq.Shape) -> dict[str, Any]:
    solids = shape.Solids()
    return {
        "valid": bool(shape.isValid()),
        "null": bool(shape.isNull()),
        "shape_type": str(shape.ShapeType()),
        "solid_count": len(solids),
        "shell_count": len(shape.Shells()),
        "volume_mm3": float(shape.Volume()),
        "bbox_mm": _shape_bbox(shape) if not shape.isNull() else None,
        "solid_validity": [bool(solid.isValid()) for solid in solids],
        "solid_volumes_mm3": [float(solid.Volume()) for solid in solids],
        "solid_shell_counts": [len(solid.Shells()) for solid in solids],
    }


def tolerance_inventory(shape: cq.Shape) -> dict[str, Any]:
    values: dict[str, list[float]] = {"vertex_mm": [], "edge_mm": [], "face_mm": []}
    for vertex in shape.Vertices():
        values["vertex_mm"].append(float(BRep_Tool.Tolerance_s(vertex.wrapped)))
    for edge in shape.Edges():
        values["edge_mm"].append(float(BRep_Tool.Tolerance_s(edge.wrapped)))
    for face in shape.Faces():
        values["face_mm"].append(float(BRep_Tool.Tolerance_s(face.wrapped)))
    return {
        "by_subshape_type": {
            kind: {
                "count": len(items),
                "minimum_mm": min(items) if items else None,
                "maximum_mm": max(items) if items else None,
            }
            for kind, items in values.items()
        },
        "maximum_mm": max((max(items) for items in values.values() if items), default=None),
    }


def source_bbox_comparison(shape: cq.Shape) -> dict[str, Any]:
    bbox = _shape_bbox(shape)
    deltas = {
        key: float(bbox[key] - expected)
        for key, expected in REFERENCE_BBOX_MM.items()
    }
    return {
        "reference_volume_mm3": REFERENCE_VOLUME_MM3,
        "source_volume_mm3": float(shape.Volume()),
        "source_volume_delta_mm3": float(shape.Volume() - REFERENCE_VOLUME_MM3),
        "reference_bbox_mm": REFERENCE_BBOX_MM,
        "source_bbox_mm": bbox,
        "bbox_bound_deltas_mm": deltas,
        "source_matches_previously_accepted_geometry": bool(
            abs(float(shape.Volume()) - REFERENCE_VOLUME_MM3) <= ROUNDTRIP_TOLERANCE_MM3
            and max(abs(value) for value in deltas.values()) <= ROUNDTRIP_TOLERANCE_MM
        ),
    }


def roundtrip_compare(source: cq.Shape, restored: cq.Shape) -> dict[str, Any]:
    source_bbox = _shape_bbox(source)
    restored_bbox = _shape_bbox(restored)
    bound_keys = (
        "xmin_mm",
        "ymin_mm",
        "zmin_mm",
        "xmax_mm",
        "ymax_mm",
        "zmax_mm",
    )
    deltas = {key: float(restored_bbox[key] - source_bbox[key]) for key in bound_keys}
    source_volume = float(source.Volume())
    restored_volume = float(restored.Volume())
    volume_delta = restored_volume - source_volume
    one_solid_shell = bool(
        source.isValid()
        and restored.isValid()
        and len(source.Solids()) == len(restored.Solids()) == 1
        and len(source.Shells()) == len(restored.Shells()) == 1
        and source.Solids()[0].isValid()
        and restored.Solids()[0].isValid()
        and len(source.Solids()[0].Shells()) == len(restored.Solids()[0].Shells()) == 1
    )
    return {
        "source": shape_summary(source),
        "restored": shape_summary(restored),
        "bbox_bound_deltas_mm": deltas,
        "max_abs_bbox_bound_delta_mm": max(abs(value) for value in deltas.values()),
        "source_volume_mm3": source_volume,
        "restored_volume_mm3": restored_volume,
        "volume_delta_mm3": volume_delta,
        "bbox_tolerance_mm": ROUNDTRIP_TOLERANCE_MM,
        "volume_tolerance_mm3": ROUNDTRIP_TOLERANCE_MM3,
        "one_valid_solid_shell_preserved": one_solid_shell,
        "volume_preserved": abs(volume_delta) <= ROUNDTRIP_TOLERANCE_MM3,
        "bbox_preserved": max(abs(value) for value in deltas.values()) <= ROUNDTRIP_TOLERANCE_MM,
    }


def solid_state(shape: cq.Shape, xyz: tuple[float, float, float]) -> str:
    solid = shape.Solids()[0] if len(shape.Solids()) == 1 else shape
    classifier = BRepClass3d_SolidClassifier()
    classifier.Load(solid.wrapped)
    classifier.Perform(gp_Pnt(*xyz), 1e-7)
    return str(classifier.State())


def halfspace_profile_probe(shape: cq.Shape) -> dict[str, Any]:
    """Check cavity, floor material, and one actual sidewall band on the cut solid."""
    probes = {
        "floor_material_center": (0.0, 0.5, 2.0),
        "cavity_above_inner_floor": (0.0, 0.5, 4.5),
        "cavity_mid_height": (0.0, 0.5, 28.0),
    }
    states = {name: solid_state(shape, xyz) for name, xyz in probes.items()}

    ray = IntCurvesFace_ShapeIntersector()
    ray.Load(shape.wrapped, 1e-7)
    line = gp_Lin(gp_Pnt(0.0, 0.5, 28.0), gp_Dir(1.0, 0.0, 0.0))
    ray.Perform(line, 0.0, 45.0)
    hits = sorted(
        float(ray.WParameter(index))
        for index in range(1, ray.NbPnt() + 1)
        if float(ray.WParameter(index)) > 1e-5
    ) if ray.IsDone() else []
    wall_midpoint = None
    wall_midpoint_state = None
    if len(hits) >= 2:
        inner_radius, outer_radius = hits[0], hits[1]
        wall_midpoint = (inner_radius + outer_radius) / 2.0
        wall_midpoint_state = solid_state(shape, (wall_midpoint, 0.5, 28.0))
    else:
        inner_radius = None
        outer_radius = None

    inside_token = "TopAbs_State.TopAbs_IN"
    outside_token = "TopAbs_State.TopAbs_OUT"
    return {
        "method": "BRepClass3d solid classification and a positive-X line through the actual half-space-cut solid at z=28 mm",
        "probe_points_mm": {key: list(value) for key, value in probes.items()},
        "probe_states": states,
        "sidewall_ray_hit_radii_mm": [inner_radius, outer_radius] if len(hits) >= 2 else hits,
        "sidewall_wall_midpoint_radius_mm": wall_midpoint,
        "sidewall_wall_midpoint_state": wall_midpoint_state,
        "cavity_open_and_floor_material_present": bool(
            states["floor_material_center"] == inside_token
            and states["cavity_above_inner_floor"] == outside_token
            and states["cavity_mid_height"] == outside_token
            and wall_midpoint_state == inside_token
        ),
        "scope": "finite actual-solid probes; interpreted with the native planar section face and normal wall rays",
    }


def native_section_face_inventory(shape: cq.Shape) -> dict[str, Any]:
    cut_faces = []
    for index, face in enumerate(shape.Faces()):
        if face.geomType() != "PLANE" or abs(float(face.Center().y)) > 1e-5:
            continue
        normal = face.normalAt().toTuple()
        if abs(float(normal[1])) < 0.999:
            continue
        cut_faces.append(
            {
                "face_index_zero_based": index,
                "valid": bool(face.isValid()),
                "area_mm2": float(face.Area()),
                "wire_count": len(face.Wires()),
                "normal": [float(value) for value in normal],
            }
        )
    return {
        "method": "planar faces of the exact OCC half-space intersection whose centers lie on y=0",
        "section_face_count": len(cut_faces),
        "faces": cut_faces,
        "all_section_faces_valid_positive_area": bool(
            cut_faces and all(face["valid"] and face["area_mm2"] > 0.0 for face in cut_faces)
        ),
        "scope": "actual clipped BREP face topology, not a mesh-only visualization cut",
    }


def source_inventory() -> dict[str, str]:
    files = {
        "rejected_interpolated_candidate_report": REPO_ROOT / "relicweave-synlab/tmp/review_20261003/implementation/vf/smooth_cad/candidate_default_wall4/smooth_cad_spike_report.json",
        "accepted_exact_profile_script": DESIGN_ROOT / "candidate2_physical_profile.py",
        "accepted_exact_profile_report": DESIGN_ROOT / "candidate2_physical_profile_report.json",
        "previous_planar_offset_script": DESIGN_ROOT / "candidate2_planar_offset.py",
        "previous_planar_offset_report": DESIGN_ROOT / "candidate2_planar_offset_report.json",
        "failed_step_diagnostic_script": DESIGN_ROOT / "candidate2_step_roundtrip_diagnostics.py",
        "failed_step_diagnostic_report": DESIGN_ROOT / "candidate2_step_roundtrip_diagnostics.json",
        "failed_step_diagnostic_log": DESIGN_ROOT / "candidate2_step_roundtrip_diagnostics.log",
        "smooth_cad_experiment_helper": REPO_ROOT / "vesselforge/experiments/smooth_cad_spike.py",
        "brep_persistence_helper": REPO_ROOT / "vesselforge/experiments/brep_persistence_helper.py",
        "vesselforge_geometry_module": REPO_ROOT / "vesselforge/src/vesselforge/geometry.py",
        "candidate_builder": Path(__file__).resolve(),
    }
    return {
        key: sha256(path)
        for key, path in files.items()
        if path.exists() and path.is_file()
    }


def fail(report: dict[str, Any], status: str, reason: str, exit_code: int = 2) -> int:
    report["status"] = status
    report.setdefault("failures", []).append(reason)
    report["finished_utc"] = datetime.now(timezone.utc).isoformat()
    write_report(report)
    print(json.dumps({"status": status, "reason": reason, "report": str(REPORT_PATH)}, ensure_ascii=False))
    return exit_code


def main() -> int:
    if ATTEMPT_MARKER.exists() or BODY_BREP.exists():
        print(
            json.dumps(
                {
                    "status": "REFUSED_REPEAT_BREP_SERIALIZATION",
                    "reason": "the one permitted body BREP write was already attempted or an artifact exists",
                    "attempt_marker": ATTEMPT_MARKER.exists(),
                    "body_brep_exists": BODY_BREP.exists(),
                },
                ensure_ascii=False,
            )
        )
        return 2

    report: dict[str, Any] = {
        "experiment_id": "vf.native-brep-persistence-candidate/1.0.0",
        "status": "RUNNING",
        "stage": "same-solid-native-brep-persistence-only",
        "candidate_state": "BREP_CANDIDATE_PENDING",
        "candidate_decision": "NOT_PROMOTED; native BREP experiment only; parent review required",
        "canonical_contract": "forge.asset.v1 remains strict canonical STEP; this experiment does not create solid.step or alter production APIs/schema",
        "production_generator_changed": False,
        "production_asset_contract_changed": False,
        "production_semantics_changed": False,
        "serialization_policy": {
            "only_operation": "source_solid.exportBrep once, followed by cq.Shape.importBrep once",
            "permitted_native_body_write_attempts": 1,
            "secondary_or_retry_serializations": 0,
            "step_write_or_read": False,
            "halfspace_result_serialized": False,
            "refuse_rerun_after_attempt_marker": True,
        },
        "construction": {
            "reuse": "the exact accepted two degree-5 Bezier-to-B-spline profile, the existing +4 mm native planar offset, and the same closed meridian/revolve",
            "profile_source": str(DESIGN_ROOT / "candidate2_physical_profile.py"),
            "body_dimensions_mm": {"height": 56.0, "width": 41.0, "wall": WALL_MM},
            "cadquery_version": cq.__version__,
            "ocp_version": OCP.__version__,
            "python_executable": sys.executable,
            "linear_units": "mm",
        },
        "previous_failure_evidence": {
            "legacy_interpolated_profile": {
                "report": "../review_20261003/implementation/vf/smooth_cad/candidate_default_wall4/smooth_cad_spike_report.json",
                "status": "FAIL_NATIVE_HALFSECTION_BOOLEAN",
                "rejected_sampled_curvature_minimum_mm": 0.0725,
                "decision": "not reused; no geometry repair or interpolation retry",
            },
            "accepted_exact_profile_step": {
                "report": "../review_20261003/implementation/vf/smooth_cad/candidate2_native_2d_offset_wall4/candidate2_physical_profile_report.json",
                "status": "FAIL_CANONICAL_STEP",
                "source_solid_count": 1,
                "source_shell_count": 1,
                "source_volume_mm3": REFERENCE_VOLUME_MM3,
                "step_import_shell_count": 2,
                "step_import_solid_count": 0,
                "step_import_volume_mm3": 8671.44834232436,
            },
            "direct_solid_step_probe": {
                "report": "../review_20261003/implementation/vf/smooth_cad/candidate2_native_2d_offset_wall4/candidate2_step_roundtrip_diagnostics.json",
                "status": "FAIL_STEP_SOLID_ROUNDTRIP",
            },
        },
        "source_sha256": source_inventory(),
        "argv": [sys.executable, str(Path(__file__).resolve())],
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "failures": [],
    }
    write_report(report)

    try:
        source_solid, construction_details = build_exact_profile_candidate(design, WALL_MM)
        report["construction_details"] = construction_details
        report["source_solid"] = shape_summary(source_solid)
        report["source_tolerances"] = tolerance_inventory(source_solid)
        report["previous_geometry_identity"] = source_bbox_comparison(source_solid)
        source_ready = bool(
            source_solid.isValid()
            and len(source_solid.Solids()) == 1
            and len(source_solid.Shells()) == 1
            and source_solid.Solids()[0].isValid()
            and len(source_solid.Solids()[0].Shells()) == 1
            and report["previous_geometry_identity"]["source_matches_previously_accepted_geometry"]
        )
        report["preflight_source_valid_and_same_geometry"] = source_ready
        if not source_ready:
            return fail(report, "FAIL_SOURCE_PREFLIGHT", "source is not the same one-valid-solid/shell geometry as the accepted profile report")

        GEOMETRY.mkdir(parents=True, exist_ok=True)
        try:
            with ATTEMPT_MARKER.open("x", encoding="utf-8") as marker:
                marker.write("One body exportBrep/importBrep sequence authorized; do not repeat.\n")
        except FileExistsError:
            return fail(report, "REFUSED_REPEAT_BREP_SERIALIZATION", "native BREP write marker already exists")

        report["serialization_policy"]["body_write_attempted"] = True
        report["serialization_policy"]["body_write_attempt_count"] = 1
        write_report(report)
        try:
            write_return = bool(source_solid.exportBrep(str(BODY_BREP)))
        except Exception as exc:
            report["native_BREP_persistence"] = {
                "writer": "CadQuery Shape.exportBrep -> OCP BRepTools native BREP writer",
                "write_attempt_count": 1,
                "writer_exception": {"type": type(exc).__name__, "message": str(exc)},
            }
            return fail(report, "FAIL_BREP_WRITE", "the single permitted native body BREP write raised an exception")

        report["native_BREP_persistence"] = {
            "writer": "CadQuery Shape.exportBrep -> OCP BRepTools native BREP writer",
            "reader": "CadQuery Shape.importBrep -> OCP BRepTools native BREP reader",
            "write_attempt_count": 1,
            "writer_returned_true": write_return,
            "file_exists": BODY_BREP.is_file(),
            "file_bytes": BODY_BREP.stat().st_size if BODY_BREP.is_file() else None,
            "file_header": BODY_BREP.read_bytes()[:256].decode("ascii", errors="replace") if BODY_BREP.is_file() else None,
            "sha256": sha256(BODY_BREP) if BODY_BREP.is_file() else None,
            "kernel_versions": {"cadquery": cq.__version__, "ocp": OCP.__version__},
        }
        if not write_return or not BODY_BREP.is_file():
            return fail(report, "FAIL_BREP_WRITE", "the single permitted native BREP write did not produce an artifact")

        try:
            restored = cq.Shape.importBrep(str(BODY_BREP))
        except Exception as exc:
            report["native_BREP_persistence"]["reader_exception"] = {
                "type": type(exc).__name__,
                "message": str(exc),
            }
            return fail(report, "FAIL_BREP_READ", "the single written native BREP could not be reimported")

        comparison = roundtrip_compare(source_solid, restored)
        report["native_BREP_roundtrip"] = comparison
        report["restored_tolerances"] = tolerance_inventory(restored)
        roundtrip_ok = bool(
            comparison["one_valid_solid_shell_preserved"]
            and comparison["volume_preserved"]
            and comparison["bbox_preserved"]
        )
        if not roundtrip_ok:
            return fail(report, "FAIL_BREP_ROUNDTRIP", "native BREP did not retain one valid solid/shell, volume, and bbox")
        report["candidate_state"] = "BREP_PERSISTENCE_PRESERVED_QA_PENDING"
        write_report(report)

        source_curves = _native_curve_inventory(source_solid)
        restored_curves = _native_curve_inventory(restored)
        def curve_signature(items: list[dict[str, Any]]) -> list[tuple[int, str, bool]]:
            return sorted(
                (
                    int(item["degree"]),
                    str(item["global_continuity"]),
                    bool(item["is_C2_at_all_internal_knots"]),
                )
                for item in items
            )
        report["native_curve_persistence"] = {
            "source_bspline_edge_inventory": source_curves,
            "restored_bspline_edge_inventory": restored_curves,
            "signature_preserved": curve_signature(source_curves) == curve_signature(restored_curves),
            "restored_native_bspline_edge_count": len(restored_curves),
            "method": "BRepAdaptor_Curve inventory before and after native BREP roundtrip; source meridian C2 is checked separately",
        }

        vertices, faces, lineage = mesh_shape(restored, SPEC)
        topology = mesh_topology_metrics(vertices, faces)
        mesh_cad = sampled_mesh_to_cad_metrics(restored, vertices, faces, lineage)
        mesh_cad["canonical_reference_kind"] = "native BREP reimport; no STEP used"
        body_mesh_path = GEOMETRY / "surface.npz"
        body_lineage_path = GEOMETRY / "mesh_lineage.npz"
        np.savez_compressed(body_mesh_path, vertices_mm=vertices.astype(np.float64), faces=faces.astype(np.int32))
        np.savez_compressed(body_lineage_path, face_source_brep_index=lineage.astype(np.int32))

        wall = sample_sidewall_normal_rays(restored, reference_kind="canonical BREP")
        floor = measure_floor_thickness(restored, reference_kind="canonical BREP")
        bbox = _shape_bbox(restored)
        report["canonical_native_BREP"] = {
            "shape": shape_summary(restored),
            "bbox_mm": bbox,
            "actual_height_mm": bbox["zlen_mm"],
            "actual_width_mm": max(bbox["xlen_mm"], bbox["ylen_mm"]),
            "nominal_height_mm": SPEC.body_height_mm,
            "nominal_width_mm": SPEC.body_width_mm,
            "radial_overshoot_mm": max(bbox["xlen_mm"], bbox["ylen_mm"]) / 2.0 - SPEC.body_width_mm / 2.0,
            "native_bspline_inventory": restored_curves,
        }
        report["wall"] = {
            "declared_mm": WALL_MM,
            "sidewall_normal_rays": wall,
            "floor_thickness": floor,
        }
        report["mesh"] = {
            "absolute_chord_target_mm": SPEC.tessellation_linear_mm,
            "angular_tolerance_rad": SPEC.tessellation_angular_rad,
            "topology": topology,
            "mesh_to_native_BREP": mesh_cad,
            "sampling_acceptance_max_mm": 0.10,
            "artifacts": {
                "body_mesh": body_mesh_path.relative_to(ROOT).as_posix(),
                "body_mesh_lineage": body_lineage_path.relative_to(ROOT).as_posix(),
            },
        }

        box = cq.Solid.makeBox(120.0, 70.0, 100.0, cq.Vector(-40.0, 0.0, -20.0))
        half_section = restored.intersect(box)
        cut_solids = half_section.Solids()
        cut_volume = float(sum(solid.Volume() for solid in cut_solids))
        ratio = cut_volume / max(float(restored.Volume()), 1e-12)
        halfsection_valid = bool(
            not half_section.isNull()
            and half_section.isValid()
            and cut_solids
            and all(solid.isValid() and solid.Volume() > 0.0 for solid in cut_solids)
            and abs(ratio - 0.5) <= 0.01
        )
        section_faces = native_section_face_inventory(half_section)
        profile_probe = halfspace_profile_probe(half_section) if len(cut_solids) == 1 else {
            "cavity_open_and_floor_material_present": False,
            "reason": "classification probes require exactly one cut solid",
        }
        cut_summary = {
            "method": "restored native BREP intersected with the actual y>=0 half-space box; no clean/heal/refine or serialization applied",
            "shape": shape_summary(half_section),
            "solid_count": len(cut_solids),
            "solid_validity": [bool(solid.isValid()) for solid in cut_solids],
            "solid_volumes_mm3": [float(solid.Volume()) for solid in cut_solids],
            "retained_volume_mm3": cut_volume,
            "full_volume_mm3": float(restored.Volume()),
            "retained_volume_fraction": ratio,
            "acceptance": halfsection_valid,
            "native_section_faces": section_faces,
            "cavity_and_bottom_probe": profile_probe,
            "persisted_or_retried": False,
        }
        report["native_half_section"] = cut_summary

        section_mesh_path = GEOMETRY / "axial_section.npz"
        section_lineage_path = GEOMETRY / "axial_section_lineage.npz"
        preview_path = ROOT / "renders" / "native_brep_and_half_section.png"
        preview_summary: dict[str, Any] | None = None
        if halfsection_valid:
            section_vertices, section_mesh_faces, section_lineage = mesh_shape(half_section, SPEC)
            section_topology = mesh_topology_metrics(section_vertices, section_mesh_faces)
            section_mesh_cad = sampled_mesh_to_cad_metrics(
                half_section, section_vertices, section_mesh_faces, section_lineage
            )
            section_mesh_cad["canonical_reference_kind"] = "native BREP half-section intersection"
            np.savez_compressed(
                section_mesh_path,
                vertices_mm=section_vertices.astype(np.float64),
                faces=section_mesh_faces.astype(np.int32),
            )
            np.savez_compressed(section_lineage_path, face_source_brep_index=section_lineage.astype(np.int32))
            cut_summary["mesh_topology"] = section_topology
            cut_summary["mesh_to_native_BREP_section"] = section_mesh_cad
            cut_summary["artifacts"] = {
                "section_mesh": section_mesh_path.relative_to(ROOT).as_posix(),
                "section_mesh_lineage": section_lineage_path.relative_to(ROOT).as_posix(),
            }
            preview_summary = save_actual_brep_preview(
                preview_path,
                vertices,
                faces,
                section_vertices,
                section_mesh_faces,
            )
        report["actual_png"] = preview_summary

        check_values = {
            "source_profile_native_degree5_C2": bool(
                all(edge["degree"] == 5 and edge["is_C2"] for edge in construction_details["source_meridian"]["native_edges"])
                and construction_details["source_meridian"]["internal_join"]["C2_join"]
            ),
            "source_profile_sampled_curvature_radius_at_least_5mm": bool(
                construction_details["source_meridian"]["sampled_curvature"]["minimum_sampled_radius_mm"] >= 5.0
                and construction_details["source_meridian"]["sampled_curvature"]["samples_below_threshold"] == 0
            ),
            "body_native_BREP_one_valid_solid_shell_preserved": comparison["one_valid_solid_shell_preserved"],
            "body_native_BREP_volume_bbox_preserved": comparison["volume_preserved"] and comparison["bbox_preserved"],
            "body_native_BREP_bspline_inventory_preserved": report["native_curve_persistence"]["signature_preserved"],
            "body_actual_height_within_0_10mm": abs(bbox["zlen_mm"] - SPEC.body_height_mm) <= 0.10,
            "body_actual_width_within_0_10mm": abs(max(bbox["xlen_mm"], bbox["ylen_mm"]) - SPEC.body_width_mm) <= 0.10,
            "body_mesh_watertight_positive": bool(topology["watertight"] and topology["signed_volume_mm3"] > 0),
            "body_mesh_to_cad_under_0_10mm": bool(
                mesh_cad["unknown_sample_count"] == 0
                and mesh_cad["max_sampled_deviation_mm"] is not None
                and mesh_cad["max_sampled_deviation_mm"] <= 0.10
            ),
            "wall_ray_sampling_no_unknowns": bool(wall["candidate_outer_side_samples"] > 0 and wall["unknown_count"] == 0),
            "sampled_wall_within_0_10mm_of_4mm": bool(
                wall["sampled_wall_min_mm"] is not None
                and wall["sampled_wall_max_mm"] is not None
                and abs(wall["sampled_wall_min_mm"] - WALL_MM) <= 0.10
                and abs(wall["sampled_wall_max_mm"] - WALL_MM) <= 0.10
            ),
            "floor_thickness_within_0_05mm": bool(
                floor.get("status") == "MEASURED_FROM_CANONICAL_BREP_PLANAR_FACES"
                and floor.get("distance_mm") is not None
                and abs(floor["distance_mm"] - WALL_MM) <= 0.05
            ),
            "native_half_section_valid_and_volume_preserving": halfsection_valid,
            "native_section_faces_valid_positive": section_faces["all_section_faces_valid_positive_area"],
            "native_half_section_confirms_cavity_and_bottom": bool(profile_probe.get("cavity_open_and_floor_material_present")),
            "actual_png_generated": bool(preview_path.is_file()),
        }
        if halfsection_valid:
            check_values["section_mesh_watertight_positive"] = bool(
                report["native_half_section"]["mesh_topology"]["watertight"]
                and report["native_half_section"]["mesh_topology"]["signed_volume_mm3"] > 0
            )
        report["checks"] = check_values
        report["artifacts"] = {
            "body_brep": BODY_BREP.relative_to(ROOT).as_posix(),
            "body_brep_sha256": sha256(BODY_BREP),
            "body_mesh": body_mesh_path.relative_to(ROOT).as_posix(),
            "body_mesh_sha256": sha256(body_mesh_path),
            "body_mesh_lineage": body_lineage_path.relative_to(ROOT).as_posix(),
            "body_mesh_lineage_sha256": sha256(body_lineage_path),
            "half_section_mesh": section_mesh_path.relative_to(ROOT).as_posix() if section_mesh_path.exists() else None,
            "half_section_mesh_sha256": sha256(section_mesh_path) if section_mesh_path.exists() else None,
            "half_section_mesh_lineage": section_lineage_path.relative_to(ROOT).as_posix() if section_lineage_path.exists() else None,
            "half_section_mesh_lineage_sha256": sha256(section_lineage_path) if section_lineage_path.exists() else None,
            "actual_png": preview_path.relative_to(ROOT).as_posix() if preview_path.exists() else None,
            "actual_png_sha256": sha256(preview_path) if preview_path.exists() else None,
        }
        report["status"] = "BREP_CANDIDATE" if all(check_values.values()) else "FAIL_OR_UNKNOWN_BREP_CANDIDATE"
        report["candidate_state"] = report["status"]
        report["candidate_decision"] = "NOT_PROMOTED; native BREP candidate only; parent review required; forge.asset.v1 remains canonical STEP"
        report["finished_utc"] = datetime.now(timezone.utc).isoformat()
        write_report(report)
        print(json.dumps({"status": report["status"], "checks": check_values, "report": str(REPORT_PATH)}, ensure_ascii=False))
        return 0 if report["status"] == "BREP_CANDIDATE" else 2
    except Exception as exc:
        report["exception"] = {"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()}
        return fail(report, "FAIL_EXCEPTION", f"candidate review stopped at an exception: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
