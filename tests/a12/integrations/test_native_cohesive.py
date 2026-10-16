from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synlab.errors import SynLabError  # noqa: E402
from synlab.integrations.native_cohesive import (  # noqa: E402
    export_native_cohesive_dataset,
    load_native_cohesive_dataset,
    validate_native_cohesive_fragments,
)


RHO_KG_M3 = 2300.0
SIDE_M = 0.006


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _refresh_manifest_file(root: Path, relative: str) -> None:
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    path = root / relative
    manifest["files"][relative] = {"sha256": _sha(path), "bytes": path.stat().st_size}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def _outward_tet_faces(points: np.ndarray, tet: np.ndarray) -> list[list[int]]:
    center = points[tet].mean(axis=0)
    output = []
    for omitted in range(4):
        face = [int(value) for index, value in enumerate(tet) if index != omitted]
        tri = points[face]
        if np.dot(np.cross(tri[1] - tri[0], tri[2] - tri[0]), tri.mean(axis=0) - center) < 0:
            face[0], face[1] = face[1], face[0]
        output.append(face)
    return output


def _make_source_packet(root: Path, *, contact_penalty: float | None = None,
                        contact_traction: np.ndarray | None = None) -> Path:
    """Two hand-computable T4s split at one paired failed facet."""
    root.mkdir(parents=True)
    # Two 6 mm tetrahedra sit on opposite sides of x=0. The interface nodes are
    # duplicated in native state but map to the same three source nodes.
    rest = np.asarray([
        [0, 0, 0], [0, SIDE_M, 0], [0, 0, SIDE_M], [-SIDE_M, 0, 0],
        [0, 0, 0], [0, SIDE_M, 0], [0, 0, SIDE_M], [SIDE_M, 0, 0],
    ], dtype=np.float64)
    tets = np.asarray([[0, 2, 1, 3], [4, 5, 6, 7]], dtype=np.int32)
    volumes = np.einsum(
        "ij,ij->i",
        np.cross(rest[tets][:, 1] - rest[tets][:, 0],
                 rest[tets][:, 2] - rest[tets][:, 0]),
        rest[tets][:, 3] - rest[tets][:, 0],
    ) / 6.0
    assert np.all(volumes > 0)
    triangles: list[list[int]] = []
    face_component: list[int] = []
    face_kind: list[int] = []
    face_parent: list[int] = []
    face_regions: list[int] = []
    records: list[dict[str, object]] = []
    component_records: list[dict[str, object]] = []
    interface_indices: list[int] = []
    for component_index, tet in enumerate(tets):
        component_faces = _outward_tet_faces(rest, tet)
        comp_face_indices = []
        for triangle in component_faces:
            global_index = len(triangles)
            is_interface = all(abs(rest[node, 0]) < 1e-15 for node in triangle)
            kind = int(is_interface)
            triangles.append(triangle)
            face_component.append(component_index)
            face_kind.append(kind)
            face_parent.append(0 if is_interface else -1)
            face_regions.append(255 if is_interface else 1)
            comp_face_indices.append(global_index)
            if is_interface:
                interface_indices.append(global_index)
            records.append({
                "global_face_index": global_index,
                "component_index": component_index,
                "native_node_ids": triangle,
                "surface_kind": ("failed_cohesive_interface" if is_interface
                                 else "original_exterior"),
                "facet_row": (0 if is_interface else None),
                "parent_facet_id": (701 if is_interface else None),
                "source_exterior_ancestry_verified": True,
            })
        node_ids = [int(value) for value in tet]
        component_records.append({
            "component_index": component_index,
            "tet_rows": [component_index],
            "native_node_ids": node_ids,
            "face_indices": comp_face_indices,
            "oriented_native_triangles": [triangles[i] for i in comp_face_indices],
            "boundary_faces": [records[i] for i in comp_face_indices],
            "qualified_closed_mechanical_fragment": True,
            "rest_bulk_volume": float(volumes[component_index]),
            "current_bulk_volume": float(volumes[component_index]),
        })
    assert len(interface_indices) == 2
    side_a, side_b = interface_indices
    cohesive_row = triangles[side_a] + triangles[side_b]
    source_map = [0, 1, 2, 3, 0, 1, 2, 4]
    ancestry_pairs = [[node_a, next(node_b for node_b in cohesive_row[3:]
                                     if source_map[node_b] == source_map[node_a])]
                      for node_a in cohesive_row[:3]]
    pairs = [{
        "facet_row": 0,
        "parent_facet_id": 701,
        "side_a_boundary_face_index": side_a,
        "side_b_boundary_face_index": side_b,
        "side_a_component_index": 0,
        "side_b_component_index": 1,
        "side_a_native_node_ids": triangles[side_a],
        "side_b_native_node_ids": triangles[side_b],
    }]
    fragments = {
        "schema": "pgfrag.native_cohesive_fragment_topology.v1",
        "rest_nodes": rest.tolist(),
        "current_nodes": rest.tolist(),
        "native_tets": tets.tolist(),
        "native_node_to_source": [0, 1, 2, 3, 0, 1, 2, 4],
        "boundary_faces": records,
        "components": component_records,
        "complete_tet_volume_coverage": True,
        "all_components_qualified_closed_mechanical_fragments": True,
        "total_rest_bulk_volume": float(volumes.sum()),
        "total_current_bulk_volume": float(volumes.sum()),
        "failed_interface_face_pairs": pairs,
        "native_cohesive_facet_count": 1,
        "failed_facet_rows": [0],
        "failure_thresholds": {
            "damage_tolerance": 1e-10,
            "damage_threshold_inclusive": 1.0 - 1e-10,
            "traction_norm_tolerance_inclusive": 0.01,
            "facet_fails_only_if_all_qps_pass_both": True,
        },
        "facet_failure_evidence": [{
            "facet_row": 0, "parent_facet_id": 701, "failed": True,
            "side_a_native_node_ids": cohesive_row[:3],
            "side_b_native_node_ids": cohesive_row[3:],
            "paired_native_node_ids": ancestry_pairs,
            "damage_qp": [1.0, 1.0, 1.0],
            "traction_norm_qp": [0.0, 0.0, 0.0],
            "qp_damage_pass": [True, True, True],
            "qp_traction_pass": [True, True, True],
            "qp_joint_failure_pass": [True, True, True],
        }],
    }
    if contact_traction is not None:
        contact_values = np.asarray(contact_traction, dtype=np.float64)
        assert contact_values.shape == (1, 3, 3)
        combined_norms = np.linalg.norm(contact_values[0], axis=1)
        fragments["facet_failure_evidence"][0]["traction_norm_qp"] = combined_norms.tolist()
    palette = {
        "base": [0.2, 0.25, 0.3],
        "stripe": [0.9, 0.12, 0.08],
        "crack": [0.6, 0.6, 0.6],
    }
    forge = {
        "schema": "forge.asset.v1",
        "material": {"mechanics": {"rho_kg_m3": RHO_KG_M3},
                     "appearance": {"roughness": 0.78}},
        "ornament": {"recipe": {
            "coordinate_map": "world_xyz_rest_mm; band centers use global Z",
            "geometry_relief_mm": 0.0,
            "historical_style_validation": "NOT_VALIDATED",
            "pattern_id": "three_bands",
            "palette_linear_rgb": palette,
            "bands": [{"center_z_mm": 2.0, "width_mm": 1.0, "color": "stripe"}],
            "target_region_codes": [1],
        }},
    }
    files = {
        "rest_nodes_m": rest,
        "current_nodes_m": rest.copy(),
        "velocity_mps": np.zeros_like(rest),
        "tets": tets,
        "triangles_native": np.asarray(triangles, dtype=np.int32),
        "face_component": np.asarray(face_component, dtype=np.int32),
        "face_kind": np.asarray(face_kind, dtype=np.uint8),
        "face_parent_id": np.asarray(face_parent, dtype=np.int32),
        "native_to_source": np.asarray([0, 1, 2, 3, 0, 1, 2, 4], dtype=np.int64),
        "face_region_code": np.asarray(face_regions, dtype=np.uint8),
        "face_color_linear_rgb": np.asarray([
            palette["crack"] if region == 255 else palette["base"]
            for region in face_regions
        ], dtype=np.float64),
        "cohesive_native": np.asarray([cohesive_row], dtype=np.int32),
        "cohesive_damage_qp": np.ones((1, 3), dtype=np.float64),
        "cohesive_traction_Pa": np.zeros((1, 3, 3), dtype=np.float64),
        "cohesive_opening_m": np.zeros((1, 3, 3), dtype=np.float64),
    }
    if contact_traction is not None:
        files["cohesive_contact_traction_Pa"] = np.asarray(contact_traction, dtype=np.float64)
    np.savez_compressed(root / "state.npz", **files)
    (root / "fragments.json").write_text(json.dumps(fragments), encoding="utf-8")
    (root / "forge_manifest.json").write_text(json.dumps(forge), encoding="utf-8")
    case = {"case": "two-tet-seam-fixture"}
    if contact_penalty is not None:
        case["interface"] = {"penalty_Pa_m": contact_penalty}
    (root / "case.json").write_text(json.dumps(case), encoding="utf-8")
    (root / "receipt.json").write_text('{"run":"two-tet-seam-fixture"}', encoding="utf-8")
    manifest = {
        "schema": "pgfrag.native_cohesive_fragments.v1",
        "units": "SI",
        "files": {
            name: {"sha256": _sha(root / name), "bytes": (root / name).stat().st_size}
            for name in ("state.npz", "fragments.json", "forge_manifest.json",
                         "case.json", "receipt.json")
        },
        "source": {
            "run_receipt_sha256": _sha(root / "receipt.json"),
            "frozen_case_sha256": _sha(root / "case.json"),
            "forge_manifest_sha256": _sha(root / "forge_manifest.json"),
        },
        "qualification": {
            "status": "PREINSERTED_WEAK_SEAM_UNCALIBRATED",
            "preinserted_weak_seam": True,
            "material_calibration_status": "UNCALIBRATED",
            "physical_pass": False,
            "pretrain_eligible": False,
        },
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root


def test_closed_native_pair_exports_occluded_sensor_rgbd_with_truth_offline(tmp_path: Path) -> None:
    packet = _make_source_packet(tmp_path / "packet")
    report = validate_native_cohesive_fragments(packet)
    expected_volume = 2.0 * SIDE_M**3 / 6.0
    assert report["counts"]["nodes"] == 8
    assert report["counts"]["tets"] == 2
    assert report["counts"]["boundary_faces"] == 8
    assert report["counts"]["failed_cohesive_faces"] == 2
    assert report["counts"]["native_cohesive_facets"] == 1
    assert report["counts"]["recomputed_failed_facets"] == 1
    assert report["counts"]["qp_samples_with_both_failure_criteria"] == 3
    assert report["counts"]["qp_sample_count"] == 3
    assert report["counts"]["total_rest_bulk_volume_m3"] == pytest.approx(expected_volume)
    assert report["counts"]["total_rest_bulk_mass_kg"] == pytest.approx(
        expected_volume * RHO_KG_M3)
    assert report["counts"]["component_edge_audits"] == [
        {"edges": 6, "bad_incidence": 0, "bad_orientation": 0},
        {"edges": 6, "bad_incidence": 0, "bad_orientation": 0},
    ]

    output = tmp_path / "research_dataset"
    manifest = export_native_cohesive_dataset(packet, output, seed=20261015,
                                               views_per_component=1,
                                               image_size=(64, 64))
    loaded = load_native_cohesive_dataset(output)
    features, targets = loaded.research_features, loaded.offline_targets
    assert manifest["status"] == "RESEARCH_ONLY_UNCALIBRATED"
    assert manifest["qualification"]["physical_pass"] is False
    assert manifest["qualification"]["physical_control_status"] == "NOT_REVIEWED"
    assert manifest["qualification"]["pretrain_eligible"] is False
    assert manifest["qualification"]["deployment_eligible"] is False
    assert manifest["qualification"]["rig_obtainable"] is False
    assert manifest["source_group"]["split"] == "UNASSIGNED_RESEARCH"
    assert manifest["source_group"]["training_or_performance_pass"] == "NOT_RUN"
    assert set(features) == {"rgb_u8", "depth_m", "point_xyz_sensor_m",
                             "normal_sensor", "normal_valid", "view_point_offsets"}
    assert "native_to_source" not in features
    assert "rest_nodes_m" not in features
    assert "point_velocity_mps" not in features
    assert "view_rotation_native_to_sensor" not in features
    assert "face_kind" not in features
    assert targets["face_kind"].shape == (8,)
    assert targets["native_to_source"].tolist() == [0, 1, 2, 3, 0, 1, 2, 4]
    assert features["rgb_u8"].shape == (2, 64, 64, 3)
    assert np.isfinite(features["depth_m"]).any()
    assert np.all(features["depth_m"][np.isfinite(features["depth_m"])] > 0)

    # Each convex tetrahedron hides at least one of its four back-facing/occluded triangles.
    face_map = targets["view_face_id_map"]
    for view_index, component_index in enumerate(targets["view_component_index"]):
        start, end = targets["view_point_offsets"][view_index:view_index + 2]
        observed = set(targets["point_face_index"][start:end].tolist())
        component_faces = set(np.flatnonzero(targets["face_component"] == component_index).tolist())
        assert 2 <= len(observed) < 4
        assert observed <= component_faces
        assert set(np.unique(face_map[view_index][face_map[view_index] >= 0])) == observed
    assert not np.allclose(targets["view_rotation_native_to_sensor"][0],
                           targets["view_rotation_native_to_sensor"][1])
    first_view_pixels = targets["point_pixel_xy"][:targets["view_point_offsets"][1]]
    lexicographic_order = np.lexsort((first_view_pixels[:, 0], first_view_pixels[:, 1]))
    assert not np.array_equal(lexicographic_order, np.arange(first_view_pixels.shape[0]))

    # The feature package stays observable-only while labels/transform truth remain offline.
    feature_meta = manifest["research_features"]
    assert feature_meta["contains_native_identity"] is False
    assert feature_meta["contains_ancestry_or_labels"] is False
    assert feature_meta["sensor_model"].startswith("IDEAL_SOFTWARE_RGBD")


def test_explicit_control_review_is_bound_to_exact_source_case(tmp_path: Path) -> None:
    packet = _make_source_packet(tmp_path / "packet")
    source_manifest = json.loads((packet / "manifest.json").read_text(encoding="utf-8"))
    source_case_sha256 = source_manifest["source"]["frozen_case_sha256"]
    review = {
        "source_case_sha256": source_case_sha256,
        "physical_control_status": "FAILED_TRANSIENT_BONDED_COMPLIANCE",
        "evidence_source": "TEST_REVIEW",
        "loading_window_rms_relative_deviation": 0.0299,
        "loading_window_rms_relative_deviation_gate": 0.02,
    }
    output = tmp_path / "reviewed_dataset"
    manifest = export_native_cohesive_dataset(
        packet, output, seed=44, views_per_component=1, image_size=(48, 48),
        physical_control_review=review)
    assert manifest["qualification"]["physical_control_status"] == \
        "FAILED_TRANSIENT_BONDED_COMPLIANCE"
    loaded = load_native_cohesive_dataset(output)
    assert loaded.manifest["source_physics_review"]["source_case_sha256"] == source_case_sha256

    wrong_review = {**review, "source_case_sha256": "0" * 64}
    with pytest.raises(SynLabError, match="exact frozen source case"):
        export_native_cohesive_dataset(
            packet, tmp_path / "wrongly_bound_dataset", seed=45,
            views_per_component=1, image_size=(48, 48),
            physical_control_review=wrong_review)

    source_manifest["qualification"]["physical_control_status"] = "PACKET_REVIEW_STATUS"
    (packet / "manifest.json").write_text(json.dumps(source_manifest), encoding="utf-8")
    with pytest.raises(SynLabError, match="cannot override source-packet"):
        export_native_cohesive_dataset(
            packet, tmp_path / "overridden_dataset", seed=47,
            views_per_component=1, image_size=(48, 48),
            physical_control_review=review)


def test_positive_contact_penalty_requires_and_recomputes_raw_contact_traction(
    tmp_path: Path,
) -> None:
    missing = _make_source_packet(tmp_path / "missing", contact_penalty=10.0)
    with pytest.raises(SynLabError, match="requires raw cohesive contact traction"):
        validate_native_cohesive_fragments(missing)

    contact = np.tile(np.asarray([[[0.001, 0.0, 0.0]]]), (1, 3, 1))
    packet = _make_source_packet(tmp_path / "valid", contact_penalty=10.0,
                                 contact_traction=contact)
    report = validate_native_cohesive_fragments(packet)
    assert report["counts"]["contact_traction_present"] is True
    assert report["counts"]["interface_penalty_Pa_m"] == 10.0
    assert report["counts"]["recomputed_failed_facets"] == 1
    output = tmp_path / "contact_dataset"
    export_native_cohesive_dataset(packet, output, seed=46, views_per_component=1,
                                   image_size=(48, 48))
    loaded = load_native_cohesive_dataset(output)
    np.testing.assert_array_equal(loaded.offline_targets["cohesive_contact_traction_Pa"],
                                  contact)

    with np.load(packet / "state.npz", allow_pickle=False) as archive:
        state = {key: np.array(archive[key], copy=True) for key in archive.files}
    state["cohesive_contact_traction_Pa"][0, 0, 0] = 0.02
    np.savez_compressed(packet / "state.npz", **state)
    _refresh_manifest_file(packet, "state.npz")
    with pytest.raises(SynLabError, match="facet QP evidence disagrees"):
        validate_native_cohesive_fragments(packet)


def test_source_and_dataset_hash_corruption_are_rejected(tmp_path: Path) -> None:
    packet = _make_source_packet(tmp_path / "packet")
    with (packet / "state.npz").open("ab") as stream:
        stream.write(b"tamper")
    with pytest.raises(SynLabError):
        validate_native_cohesive_fragments(packet)

    valid_packet = _make_source_packet(tmp_path / "valid_packet")
    output = tmp_path / "research_dataset"
    export_native_cohesive_dataset(valid_packet, output, seed=19, views_per_component=1,
                                   image_size=(48, 48))
    with (output / "research_features.npz").open("ab") as stream:
        stream.write(b"tamper")
    with pytest.raises(SynLabError):
        load_native_cohesive_dataset(output)


def test_sensor_velocity_is_a_rotated_vector() -> None:
    from synlab.integrations.native_cohesive import _rotate_vectors_to_sensor

    rotation_90z = np.asarray([[0.0, -1.0, 0.0],
                               [1.0, 0.0, 0.0],
                               [0.0, 0.0, 1.0]])
    actual = _rotate_vectors_to_sensor(np.asarray([[1.0, 0.0, 0.0]]), rotation_90z)
    np.testing.assert_allclose(actual, [[0.0, 1.0, 0.0]], atol=0.0, rtol=0.0)


def test_rehashed_reversed_closed_surface_is_rejected_against_t4_boundary(tmp_path: Path) -> None:
    packet = _make_source_packet(tmp_path / "packet")
    with np.load(packet / "state.npz", allow_pickle=False) as archive:
        state = {key: np.array(archive[key], copy=True) for key in archive.files}
    fragments = json.loads((packet / "fragments.json").read_text(encoding="utf-8"))
    comp = fragments["components"][0]
    face_ids = comp["face_indices"]
    for face_index in face_ids:
        state["triangles_native"][face_index, :2] = state["triangles_native"][face_index, 1::-1]
        fragments["boundary_faces"][face_index]["native_node_ids"] = \
            state["triangles_native"][face_index].tolist()
    comp["oriented_native_triangles"] = state["triangles_native"][face_ids].tolist()
    for record in comp["boundary_faces"]:
        index = record["global_face_index"]
        record["native_node_ids"] = state["triangles_native"][index].tolist()
    for pair in fragments["failed_interface_face_pairs"]:
        for side in ("a", "b"):
            index = pair[f"side_{side}_boundary_face_index"]
            if pair[f"side_{side}_component_index"] == 0:
                pair[f"side_{side}_native_node_ids"] = state["triangles_native"][index].tolist()
    np.savez_compressed(packet / "state.npz", **state)
    (packet / "fragments.json").write_text(json.dumps(fragments), encoding="utf-8")
    _refresh_manifest_file(packet, "state.npz")
    _refresh_manifest_file(packet, "fragments.json")

    # Winding every face backwards preserves a closed two-manifold edge audit and all
    # packet hashes, but no longer matches the outward boundary implied by positive T4s.
    with pytest.raises(SynLabError, match="oriented T4-incidence boundary"):
        validate_native_cohesive_fragments(packet)


def test_rehashed_qp_traction_is_recomputed_from_native_vectors(tmp_path: Path) -> None:
    packet = _make_source_packet(tmp_path / "packet")
    with np.load(packet / "state.npz", allow_pickle=False) as archive:
        state = {key: np.array(archive[key], copy=True) for key in archive.files}
    state["cohesive_traction_Pa"][0, 0, 0] = 0.02
    np.savez_compressed(packet / "state.npz", **state)
    _refresh_manifest_file(packet, "state.npz")
    with pytest.raises(SynLabError, match="facet QP evidence disagrees"):
        validate_native_cohesive_fragments(packet)
