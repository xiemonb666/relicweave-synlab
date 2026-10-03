from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synlab.cameras.projection import look_at_T_WC, project, world_to_camera  # noqa: E402
from synlab.errors import ErrorCode, SynLabError  # noqa: E402


def _assert_proper_rotation(T_WC: np.ndarray) -> None:
    rotation = np.asarray(T_WC[:3, :3], dtype=np.float64)
    assert np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-12)
    assert np.linalg.det(rotation) == pytest.approx(1.0, abs=1e-12)


def test_world_up_projects_up_and_right_directions_to_correct_image_axes() -> None:
    eye = np.asarray([0.0, -10.0, 0.0])
    target = np.zeros(3)
    T_WC = look_at_T_WC(eye, target, up=np.asarray([0.0, 0.0, 1.0]))
    _assert_proper_rotation(T_WC)

    K = np.asarray([[100.0, 0.0, 50.0], [0.0, 100.0, 50.0], [0.0, 0.0, 1.0]])
    points = np.asarray([target, [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])
    uv, z = project(points, K, T_WC, model="PINHOLE")
    assert z[0] > 0.0, "the target must be in front of the camera"
    assert uv[1, 0] > uv[0, 0], "world +X is right for this view"
    assert uv[2, 1] < uv[0, 1], "world +Z is up (smaller image row)"
    assert np.allclose(world_to_camera(T_WC, target)[0], [0.0, 0.0, 10.0], atol=1e-12)


def test_default_up_is_repository_world_z_up() -> None:
    eye = np.asarray([0.0, -10.0, 0.0])
    T_WC = look_at_T_WC(eye, np.zeros(3))
    K = np.asarray([[100.0, 0.0, 50.0], [0.0, 100.0, 50.0], [0.0, 0.0, 1.0]])
    uv, _ = project(np.asarray([[0.0, 0.0, 0.0], [0.0, 0.0, 1.0]]), K, T_WC,
                    model="PINHOLE")
    assert uv[1, 1] < uv[0, 1]


def test_parallel_up_falls_back_to_a_deterministic_least_parallel_basis() -> None:
    eye = np.asarray([0.0, 0.0, -10.0])
    target = np.zeros(3)
    unit_up = look_at_T_WC(eye, target, up=np.asarray([0.0, 0.0, 1.0]))
    scaled_up = look_at_T_WC(eye, target, up=np.asarray([0.0, 0.0, 1000.0]))
    _assert_proper_rotation(unit_up)
    assert np.allclose(unit_up, scaled_up, atol=1e-12)
    assert np.allclose(world_to_camera(unit_up, target)[0], [0.0, 0.0, 10.0], atol=1e-12)


@pytest.mark.parametrize("kwargs", [
    {"eye": [np.nan, 0.0, 0.0]},
    {"target": [0.0, np.inf, 0.0]},
    {"up": [np.nan, 0.0, 1.0]},
    {"up": [0.0, 0.0, 0.0]},
])
def test_nonfinite_or_zero_camera_vectors_are_structured_schema_errors(
    kwargs: dict[str, list[float]],
) -> None:
    values = {"eye": np.asarray([0.0, -10.0, 0.0]), "target": np.zeros(3),
              "up": np.asarray([0.0, 0.0, 1.0])}
    for name, value in kwargs.items():
        values[name] = np.asarray(value, dtype=np.float64)
    with pytest.raises(SynLabError) as excinfo:
        look_at_T_WC(**values)
    assert excinfo.value.code == ErrorCode.SCHEMA_INVALID


def test_coincident_camera_and_target_are_rejected() -> None:
    with pytest.raises(SynLabError) as excinfo:
        look_at_T_WC(np.zeros(3), np.zeros(3), up=np.asarray([0.0, 0.0, 1.0]))
    assert excinfo.value.code == ErrorCode.SCHEMA_INVALID
