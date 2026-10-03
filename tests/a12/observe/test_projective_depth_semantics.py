"""Small analytic regressions for A12's projective depth paths."""

from __future__ import annotations

import numpy as np
import pytest
from types import SimpleNamespace

from synlab.observe import render as renderer
from synlab.observe.render import LightSpec, MaterialSpec, RenderSpec, Scene
from synlab.observe.api import _apply_compiled
from synlab.observe.mvs_subset import MvsConfig
from synlab.observe.routes import ObsSpec
from synlab.schemas.runtime import ViewFrame


W, H = 64, 48
K = np.array([[82.0, 0.0, (W - 1) / 2],
              [0.0, 82.0, (H - 1) / 2],
              [0.0, 0.0, 1.0]], dtype=np.float64)
LIGHT = LightSpec(direction=np.array([0.0, 0.0, -1.0]),
                  color=np.ones(3), ambient=np.full(3, 0.1))


def frame(model: str = "PINHOLE", dist: np.ndarray | None = None) -> ViewFrame:
    return ViewFrame(view_id="depth-contract", K=K.copy(), T_WC=np.eye(4),
                     image_size=(W, H), profile_id="test", tier="GLOBAL",
                     u_position_mm=0.0, working_distance_mm=500.0,
                     focus_setting="FIXED", source_kind="SENSOR_SIM",
                     camera_model=model, dist=dist)


def sloped_plane(*, extent_x: float = 240.0, extent_y: float = 180.0,
                 base_z: float = 500.0, slope_x: float = 0.28,
                 slope_y: float = -0.16) -> Scene:
    def p(x: float, y: float) -> tuple[float, float, float]:
        return (x, y, base_z + slope_x * x + slope_y * y)

    vertices = np.asarray([p(-extent_x, -extent_y), p(extent_x, -extent_y),
                           p(extent_x, extent_y), p(-extent_x, extent_y)], dtype=np.float64)
    # Both triangles have camera-facing normals (N dot X < 0).
    faces = np.asarray([[0, 2, 1], [0, 3, 2]], dtype=np.int32)
    return Scene("tilted-plane", vertices, faces, np.asarray([11, 22], np.int16),
                 MaterialSpec(np.asarray([[0.5, 0.3, 0.2], [0.2, 0.4, 0.6]], np.float32),
                              np.asarray([0.4, 0.4], np.float32)),
                 face_id=np.asarray([4101, 4202], np.int32))


def exact_plane_depth(ray_x: np.ndarray, ray_y: np.ndarray, *, base_z: float = 500.0,
                      slope_x: float = 0.28, slope_y: float = -0.16) -> np.ndarray:
    denom = 1.0 - slope_x * ray_x - slope_y * ray_y
    return base_z / denom


@pytest.mark.parametrize("factor", [1, 2])
@pytest.mark.parametrize("model,dist", [
    ("PINHOLE", None),
    ("OPENCV", np.asarray([0.16, -0.035, 0.0012, -0.0008, 0.0])),
    ("OPENCV", np.asarray([-0.14, 0.025, -0.0010, 0.0007, 0.0])),
])
def test_plane_depth_matches_independent_ray_plane_solution(model: str,
                                                            dist: np.ndarray | None,
                                                            factor: int):
    f = renderer._scaled_frame(frame(model, dist), factor)
    sw, sh = W * factor, H * factor
    scene = sloped_plane()
    buffers = renderer._rasterise_buffers(scene, f, sw, sh, LIGHT,
                                          RenderSpec(supersample=factor,
                                                     near_mm=1.0, far_mm=2000.0))
    ray_x, ray_y = renderer._camera_sample_rays(f, sw, sh)
    expected = exact_plane_depth(ray_x, ray_y)
    actual = buffers["depth"]
    assert np.isfinite(actual).all(), "the oversized plane must cover this test frustum"
    assert float(np.max(np.abs(actual - expected))) <= 1e-6
    assert set(np.unique(buffers["id"]).tolist()) <= {4101, 4202}
    tag_by_id = {4101: 11, 4202: 22}
    for face_id, tag in tag_by_id.items():
        mask = buffers["id"] == face_id
        assert mask.any()
        assert np.all(buffers["tag"][mask] == tag)


@pytest.mark.parametrize("dist", [
    np.asarray([0.18, -0.04, 0.002, -0.001, 0.0]),
    np.asarray([-0.18, 0.04, -0.002, 0.001, 0.0]),
])
def test_distorted_inverse_ray_round_trip_is_independently_bounded(dist: np.ndarray):
    f = renderer._scaled_frame(frame("OPENCV", dist), 2)
    ray_x, ray_y = renderer._camera_sample_rays(f, W * 2, H * 2)
    # Check forward distortion against the sensor coordinates independently of plane hits.
    import cv2

    u = np.arange(W * 2, dtype=np.float64)[None, :] + 0.5
    v = np.arange(H * 2, dtype=np.float64)[:, None] + 0.5
    xd = (u - f.K[0, 2]) / f.K[0, 0]
    yd = (v - f.K[1, 2]) / f.K[1, 1]
    projected, _ = cv2.projectPoints(
        np.column_stack([ray_x.ravel(), ray_y.ravel(), np.ones(ray_x.size)]).reshape(-1, 1, 3),
        np.zeros(3), np.zeros(3), f.K, np.asarray(dist, dtype=np.float64))
    projected = projected.reshape(H * 2, W * 2, 2)
    assert np.max(np.abs((projected[..., 0] - f.K[0, 2]) / f.K[0, 0] - xd)) < 1e-8
    assert np.max(np.abs((projected[..., 1] - f.K[1, 2]) / f.K[1, 1] - yd)) < 1e-8


def test_zero_coefficient_fisheye_uses_analytic_tan_inverse_and_ray_backend():
    f = renderer._scaled_frame(frame("OPENCV_FISHEYE", np.zeros(4)), 1)
    ray_x, ray_y = renderer._camera_sample_rays(f, W, H)
    u = np.arange(W, dtype=np.float64)[None, :] + 0.5
    v = np.arange(H, dtype=np.float64)[:, None] + 0.5
    xd = (u - f.K[0, 2]) / f.K[0, 0]
    yd = (v - f.K[1, 2]) / f.K[1, 1]
    theta = np.sqrt(xd * xd + yd * yd)
    radius = np.tan(theta)
    scale = np.divide(radius, theta, out=np.ones_like(radius), where=theta > 1e-14)
    assert np.max(np.abs(ray_x - xd * scale)) < 1e-10
    assert np.max(np.abs(ray_y - yd * scale)) < 1e-10
    extent_x, extent_y = 240.0, 180.0
    buffers = renderer._rasterise_buffers(sloped_plane(extent_x=extent_x,
                                                       extent_y=extent_y), f, W, H, LIGHT,
                                          RenderSpec(supersample=1))
    expected_depth = exact_plane_depth(ray_x, ray_y)
    expected_x, expected_y = expected_depth * ray_x, expected_depth * ray_y
    expected_support = ((np.abs(expected_x) <= extent_x)
                        & (np.abs(expected_y) <= extent_y))
    assert np.array_equal(np.isfinite(buffers["depth"]), expected_support)
    assert float(np.max(np.abs(buffers["depth"][expected_support]
                               - expected_depth[expected_support]))) < 1e-6


def test_distorted_background_and_source_face_mapping_survive_open3d_candidates():
    scene = sloped_plane(extent_x=55.0, extent_y=42.0)
    dist = np.asarray([0.20, -0.03, 0.001, -0.001, 0.0])
    f = renderer._scaled_frame(frame("OPENCV", dist), 1)
    buffers = renderer._rasterise_buffers(scene, f, W, H, LIGHT,
                                          RenderSpec(supersample=1))
    assert np.any(buffers["id"] == -1), "the candidate path must tolerate background rays"
    for face_id, tag in ((4101, 11), (4202, 22)):
        mask = buffers["id"] == face_id
        assert mask.any()
        assert np.all(buffers["tag"][mask] == tag)


def test_perspective_front_face_culling_uses_camera_ray_not_normal_z():
    # The visible plane is far off axis. Its normal has positive camera-z, but points
    # toward the camera at the plane location; normals[:,2] would wrongly cull it.
    center = np.asarray([-300.0, 0.0, 1000.0])
    e1 = np.asarray([-100.0, 0.0, 1000.0])
    e2 = np.asarray([0.0, 120.0, 0.0])
    vertices = np.asarray([center, center + e2, center + e1])
    faces = np.asarray([[0, 1, 2]], np.int32)
    normal = np.cross(vertices[1] - vertices[0], vertices[2] - vertices[0])
    assert normal[2] > 0 and np.dot(normal, vertices[0]) < 0
    scene = Scene("eccentric-front", vertices, faces, np.asarray([7], np.int16),
                  MaterialSpec(np.asarray([[0.4, 0.5, 0.6]], np.float32),
                               np.asarray([0.4], np.float32)),
                  face_id=np.asarray([777], np.int32))
    buf = renderer._rasterise_buffers(scene, renderer._scaled_frame(frame(), 1), W, H,
                                      LIGHT, RenderSpec(supersample=1))
    assert np.any(buf["id"] == 777)


def test_backface_in_front_does_not_hide_valid_front_face():
    near = np.asarray([[-30.0, -30.0, 300.0], [30.0, -30.0, 300.0],
                       [30.0, 30.0, 300.0], [-30.0, 30.0, 300.0]])
    far = near * (500.0 / 300.0)
    vertices = np.vstack([near, far])
    # Near winding is back-facing; far winding is front-facing. Their projections coincide.
    faces = np.asarray([[0, 1, 2], [0, 2, 3], [4, 6, 5], [4, 7, 6]], np.int32)
    scene = Scene("backface-occlusion", vertices, faces, np.asarray([3, 3, 8, 8], np.int16),
                  MaterialSpec(np.full((4, 3), 0.5, np.float32),
                               np.full(4, 0.4, np.float32)),
                  face_id=np.asarray([101, 101, 202, 202], np.int32))
    for model, coeff in (("PINHOLE", None),
                         ("OPENCV", np.asarray([0.10, -0.02, 0.001, 0.0, 0.0]))):
        buf = renderer._rasterise_buffers(scene, renderer._scaled_frame(frame(model, coeff), 1),
                                          W, H, LIGHT, RenderSpec(supersample=1))
        assert buf["id"][H // 2, W // 2] == 202
        assert buf["depth"][H // 2, W // 2] == pytest.approx(500.0, abs=1e-6)


def test_pinhole_triangle_crossing_near_plane_keeps_the_visible_polygon():
    vertices = np.asarray([[-2.0, -2.0, 0.5], [2.0, -2.0, 5.0], [0.0, 2.0, 5.0]])
    scene = Scene("near-crossing", vertices, np.asarray([[0, 2, 1]], np.int32),
                  np.asarray([4], np.int16),
                  MaterialSpec(np.asarray([[0.3, 0.4, 0.5]], np.float32),
                               np.asarray([0.4], np.float32)),
                  face_id=np.asarray([909], np.int32))
    buf = renderer._rasterise_buffers(scene, renderer._scaled_frame(frame(), 1), W, H,
                                      LIGHT, RenderSpec(supersample=1, near_mm=1.0))
    hits = buf["id"] == 909
    assert hits.sum() > 0
    assert np.all(buf["depth"][hits] > 1.0)


def test_distorted_near_clipped_first_hit_falls_through_to_next_valid_surface():
    near_vertices = np.asarray([[-20.0, -100.0, 0.2], [100.0, -100.0, 2.0],
                                [100.0, 100.0, 2.0], [-20.0, 100.0, 0.2]])
    far_vertices = np.asarray([[-100.0, -100.0, 5.0], [100.0, -100.0, 5.0],
                               [100.0, 100.0, 5.0], [-100.0, 100.0, 5.0]])
    vertices = np.vstack([near_vertices, far_vertices])
    faces = np.asarray([[0, 2, 1], [0, 3, 2], [4, 6, 5], [4, 7, 6]], np.int32)
    scene = Scene("near-fallback", vertices, faces, np.asarray([2, 2, 9, 9], np.int16),
                  MaterialSpec(np.full((4, 3), 0.5, np.float32),
                               np.full(4, 0.4, np.float32)),
                  face_id=np.asarray([111, 111, 999, 999], np.int32))
    dist = np.asarray([0.08, -0.01, 0.0, 0.0, 0.0])
    buf = renderer._rasterise_buffers(scene, renderer._scaled_frame(frame("OPENCV", dist), 1),
                                      W, H, LIGHT,
                                      RenderSpec(supersample=1, near_mm=1.0, far_mm=20.0))
    assert buf["id"][H // 2, W // 2] == 999
    assert buf["depth"][H // 2, W // 2] == pytest.approx(5.0, abs=1e-6)


def test_declared_sensor_consumers_enable_noise_but_explicit_off_wins():
    recipe = {"nodes": [SimpleNamespace(stage="SENSOR",
                                        parameters={"effective_gain": 2000.0,
                                                    "read_noise_sigma": 0.01})]}
    spec = ObsSpec()
    _apply_compiled(recipe, spec, "proxy_scan")
    assert spec.imaging.sensor_noise_enabled is True

    explicit_off = ObsSpec()
    explicit_off.imaging.sensor_noise_enabled = False
    _apply_compiled(recipe, explicit_off, "proxy_scan")
    assert explicit_off.imaging.sensor_noise_enabled is False

    recipe_off = {"nodes": [SimpleNamespace(stage="SENSOR",
                                             parameters={"effective_gain": 2000.0,
                                                         "sensor_noise_enabled": False})]}
    explicit_node_off = ObsSpec()
    _apply_compiled(recipe_off, explicit_node_off, "proxy_scan")
    assert explicit_node_off.imaging.sensor_noise_enabled is False
    assert MvsConfig().sensor_noise_enabled is True

