"""Pinhole projection, unprojection and pixel-frame transforms (plan 4.3, 30.3).

Frame definitions
-----------------
``T_WC`` maps **camera coordinates to world coordinates** (``X_W = T_WC @ X_C``), so the
camera centre is ``T_WC[:3, 3]`` and ``R_WC = T_WC[:3, :3]``.  Camera coordinates are
OpenCV style: ``+x`` right, ``+y`` down, ``+z`` along the viewing direction (forward).
The depth returned by :func:`project` is the camera-frame ``z`` (not the ray length):
under a unit ray ``d``, ``z = r * d_z`` (plan 4.3).

Pixel frame
-----------
Internal pixel coordinates are OpenCV centred: the centre of the top-left pixel is
``(0, 0)``.  COLMAP uses the same physical convention but documents the top-left pixel
*corner* offset as ``(0.5, 0.5)``; :func:`colmap_convention` adds the 0.5 px and
:func:`colmap_unconvention` removes it (plan 30.3).
"""

from __future__ import annotations

import numpy as np

from ..errors import ErrorCode, SynLabError

#: Supported OpenCV camera models and their distortion coefficient names.
CAMERA_MODELS: dict[str, tuple[str, ...]] = {
    "PINHOLE": (),
    "SIMPLE_RADIAL": ("k1",),
    "RADIAL": ("k1", "k2"),
    "OPENCV": ("k1", "k2", "p1", "p2", "k3"),
    "OPENCV_FISHEYE": ("k1", "k2", "k3", "k4"),
}


def _as_points(points_mm: np.ndarray) -> np.ndarray:
    pts = np.asarray(points_mm, dtype=np.float64)
    if pts.ndim == 1:
        pts = pts.reshape(1, 3)
    if pts.ndim != 2 or pts.shape[1] != 3:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"points must be (N,3) mm, got {pts.shape}",
                          stage="cameras.projection")
    return pts


def _as_T(T_WC: np.ndarray) -> np.ndarray:
    T = np.asarray(T_WC, dtype=np.float64)
    if T.shape == (3, 4):
        T = np.vstack([T, np.array([0.0, 0.0, 0.0, 1.0])])
    if T.shape != (4, 4):
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"T_WC must be (4,4) or (3,4), got {T.shape}",
                          stage="cameras.projection")
    return T


def world_to_camera(T_WC: np.ndarray, points_mm: np.ndarray) -> np.ndarray:
    """``X_C = R_WC^T (X_W - C)``."""
    T = _as_T(T_WC)
    pts = _as_points(points_mm)
    R = T[:3, :3]
    C = T[:3, 3]
    return (pts - C[None, :]) @ R


def camera_to_world(T_WC: np.ndarray, points_cam: np.ndarray) -> np.ndarray:
    T = _as_T(T_WC)
    pts = _as_points(points_cam)
    return pts @ T[:3, :3].T + T[:3, 3][None, :]


def distort_normalized(x: np.ndarray, y: np.ndarray, dist: np.ndarray | None,
                       model: str = "OPENCV") -> tuple[np.ndarray, np.ndarray]:
    """Apply the OpenCV distortion model to normalised image coordinates."""
    if dist is None:
        return x, y
    d = np.asarray(dist, dtype=np.float64).ravel()
    if d.size == 0:
        return x, y
    names = CAMERA_MODELS.get(model.upper())
    if names is None:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, f"unsupported camera model {model!r}",
                          stage="cameras.distort")
    if d.size != len(names):
        raise SynLabError(
            ErrorCode.SCHEMA_INVALID,
            f"model {model} expects {len(names)} distortion coefficients {names}, got {d.size}",
            stage="cameras.distort",
        )
    coeff = dict(zip(names, d.tolist()))
    if model.upper() == "OPENCV_FISHEYE":
        r = np.sqrt(x * x + y * y)
        theta = np.arctan(r)
        theta_d = theta * (1.0 + coeff["k1"] * theta ** 2 + coeff["k2"] * theta ** 4
                           + coeff["k3"] * theta ** 6 + coeff["k4"] * theta ** 8)
        scale = np.where(r > 1e-12, theta_d / np.maximum(r, 1e-12), 1.0)
        return x * scale, y * scale
    r2 = x * x + y * y
    k1 = coeff.get("k1", 0.0)
    k2 = coeff.get("k2", 0.0)
    k3 = coeff.get("k3", 0.0)
    p1 = coeff.get("p1", 0.0)
    p2 = coeff.get("p2", 0.0)
    radial = 1.0 + k1 * r2 + k2 * r2 * r2 + k3 * r2 * r2 * r2
    xd = x * radial + 2.0 * p1 * x * y + p2 * (r2 + 2.0 * x * x)
    yd = y * radial + p1 * (r2 + 2.0 * y * y) + 2.0 * p2 * x * y
    return xd, yd


def undistort_normalized(xd: np.ndarray, yd: np.ndarray, dist: np.ndarray | None,
                         model: str = "OPENCV", iterations: int = 20,
                         tol: float = 1e-14) -> tuple[np.ndarray, np.ndarray]:
    """Iterative inverse of :func:`distort_normalized` (fixed-point, frozen order)."""
    if dist is None:
        return xd, yd
    d = np.asarray(dist, dtype=np.float64).ravel()
    if d.size == 0:
        return xd, yd
    x, y = xd.copy(), yd.copy()
    for _ in range(int(iterations)):
        xd_hat, yd_hat = distort_normalized(x, y, d, model)
        dx, dy = xd_hat - xd, yd_hat - yd
        x = x - dx
        y = y - dy
        if np.max(np.abs(dx)) < tol and np.max(np.abs(dy)) < tol:
            break
    return x, y


def project(points_mm: np.ndarray, K: np.ndarray, T_WC: np.ndarray,
            dist: np.ndarray | None = None, *, model: str = "OPENCV"
            ) -> tuple[np.ndarray, np.ndarray]:
    """Project world points (N,3) mm to pixels.

    Returns ``(uv, z)`` where ``uv`` is (N,2) ``float64`` in the OpenCV pixel centre
    convention and ``z`` is (N,) camera-frame depth in mm.  Points with ``z <= 0`` are
    behind the camera: their ``uv`` is returned as NaN so callers cannot silently use a
    mirrored point, and ``z`` keeps its true (non-positive) value.
    """
    T = _as_T(T_WC)
    K = np.asarray(K, dtype=np.float64)
    if K.shape != (3, 3):
        raise SynLabError(ErrorCode.SCHEMA_INVALID, f"K must be (3,3), got {K.shape}",
                          stage="cameras.project")
    cam = world_to_camera(T, points_mm)
    z = cam[:, 2]
    safe = np.where(np.abs(z) > 1e-12, z, np.nan)
    x = cam[:, 0] / safe
    y = cam[:, 1] / safe
    xd, yd = distort_normalized(x, y, dist, model)
    u = K[0, 0] * xd + K[0, 1] * yd + K[0, 2]
    v = K[1, 0] * xd + K[1, 1] * yd + K[1, 2]
    uv = np.stack([u, v], axis=1)
    invalid = ~(z > 0)
    uv[invalid] = np.nan
    return uv, z


def unproject(uv: np.ndarray, z: np.ndarray, K: np.ndarray, T_WC: np.ndarray,
              dist: np.ndarray | None = None, *, model: str = "OPENCV") -> np.ndarray:
    """Back-project pixels (N,2) at camera depth ``z`` (N,) mm to world points (N,3)."""
    T = _as_T(T_WC)
    K = np.asarray(K, dtype=np.float64)
    uv = np.asarray(uv, dtype=np.float64)
    if uv.ndim == 1:
        uv = uv.reshape(1, 2)
    z = np.asarray(z, dtype=np.float64).reshape(-1)
    if uv.shape[0] != z.shape[0]:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"uv ({uv.shape[0]}) and z ({z.shape[0]}) length mismatch",
                          stage="cameras.unproject")
    xd = (uv[:, 0] - K[0, 2]) / K[0, 0]
    yd = (uv[:, 1] - K[1, 2]) / K[1, 1]
    x, y = undistort_normalized(xd, yd, dist, model)
    cam = np.stack([x * z, y * z, z], axis=1)
    return camera_to_world(T, cam)


def project_cam_from_world(T_CW: np.ndarray, points_mm: np.ndarray, K: np.ndarray,
                           dist: np.ndarray | None = None, *, model: str = "OPENCV"
                           ) -> tuple[np.ndarray, np.ndarray]:
    """Same as :func:`project` but taking the world-to-camera matrix ``T_CW``."""
    return project(points_mm, K, np.linalg.inv(_as_T(T_CW)), dist, model=model)


def unproject_cam_from_world(T_CW: np.ndarray, uv: np.ndarray, z: np.ndarray,
                             K: np.ndarray, dist: np.ndarray | None = None,
                             *, model: str = "OPENCV") -> np.ndarray:
    return unproject(uv, z, K, np.linalg.inv(_as_T(T_CW)), dist, model=model)


# --------------------------------------------------------------------------------------
# Pixel-frame transforms (plan 30.3)
# --------------------------------------------------------------------------------------
def crop_resize_matrix(x0: float, y0: float, sx: float, sy: float) -> np.ndarray:
    """Affine ``A`` for ``u' = sx (u - x0 + 0.5) - 0.5`` (OpenCV ``resize`` sampling)."""
    A = np.array([[sx, 0.0, sx * (0.5 - x0) - 0.5],
                  [0.0, sy, sy * (0.5 - y0) - 0.5],
                  [0.0, 0.0, 1.0]], dtype=np.float64)
    return A


def pixel_transform_crop_resize(x0: float, y0: float, sx: float, sy: float,
                                K: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Crop (integer origin) + resize (arbitrary scale) applied to pixels and ``K``.

    Returns ``(A, K_new)`` with ``K_new = A @ K``.  ``K`` is unchanged by this function.
    """
    K = np.asarray(K, dtype=np.float64)
    A = crop_resize_matrix(x0, y0, sx, sy)
    return A, A @ K


def letterbox_transform(K: np.ndarray, pad_x: float, pad_y: float) -> tuple[np.ndarray, np.ndarray]:
    """Extra pure translation for a letterboxed image: ``u'' = u' + pad_x``."""
    K = np.asarray(K, dtype=np.float64)
    A = np.array([[1.0, 0.0, pad_x], [0.0, 1.0, pad_y], [0.0, 0.0, 1.0]], dtype=np.float64)
    return A, A @ K


#: EXIF orientation tag -> (applied to the pixel array, mirrored).
#: 1 = identity, 2 = mirror horizontal, 3 = rotate 180, 4 = mirror vertical,
#: 5 = mirror horizontal + rotate 270 CW, 6 = rotate 90 CW, 7 = mirror horizontal +
#: rotate 90 CW, 8 = rotate 270 CW.
EXIF_ROTATE_CW: dict[int, int] = {1: 0, 2: 0, 3: 180, 4: 0, 5: 270, 6: 90, 7: 90, 8: 270}
EXIF_MIRROR: dict[int, str | None] = {
    1: None, 2: "horizontal", 3: None, 4: "vertical",
    5: "horizontal", 6: None, 7: "horizontal", 8: None,
}


def exif_transform(K: np.ndarray, orientation: int, image_size: tuple[int, int]
                   ) -> tuple[np.ndarray, np.ndarray, tuple[int, int]]:
    """Real EXIF orientation applied to pixels, with the matching ``A`` and ``K_new``.

    ``image_size`` is the *stored* ``(W, H)`` before rotation.  Returns
    ``(A, K_new, (W', H'))``.  The relationship is ``K_new = A @ K`` for the affine
    that maps original pixel coordinates onto the rotated pixel array; the caller must
    apply the same numpy operation to every pixel channel (never metadata only).
    """
    K = np.asarray(K, dtype=np.float64)
    if orientation not in EXIF_ROTATE_CW:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, f"bad EXIF orientation {orientation}",
                          stage="cameras.exif_transform")
    width, height = int(image_size[0]), int(image_size[1])
    rot = EXIF_ROTATE_CW[orientation]
    mirror = EXIF_MIRROR[orientation]
    if rot in (90, 270):
        new_size = (height, width)
    else:
        new_size = (width, height)
    A = np.eye(3, dtype=np.float64)
    if mirror == "horizontal":
        A = np.array([[-1.0, 0.0, width - 1.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]) @ A
    elif mirror == "vertical":
        A = np.array([[1.0, 0.0, 0.0], [0.0, -1.0, height - 1.0], [0.0, 0.0, 1.0]]) @ A
    if rot == 90:
        # clockwise: (u, v) -> (H - 1 - v, u) in the *mirrored* frame
        R = np.array([[0.0, -1.0, height - 1.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])
        A = R @ A
    elif rot == 180:
        R = np.array([[-1.0, 0.0, width - 1.0], [0.0, -1.0, height - 1.0], [0.0, 0.0, 1.0]])
        A = R @ A
    elif rot == 270:
        R = np.array([[0.0, 1.0, 0.0], [-1.0, 0.0, width - 1.0], [0.0, 0.0, 1.0]])
        A = R @ A
    return A, A @ K, new_size


def apply_exif_to_image(image: np.ndarray, orientation: int) -> np.ndarray:
    """Apply an EXIF orientation to a pixel array with numpy (matches :func:`exif_transform`)."""
    if orientation not in EXIF_ROTATE_CW:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, f"bad EXIF orientation {orientation}",
                          stage="cameras.apply_exif_to_image")
    out = image
    mirror = EXIF_MIRROR[orientation]
    if mirror == "horizontal":
        out = out[:, ::-1, ...]
    elif mirror == "vertical":
        out = out[::-1, :, ...]
    rot = EXIF_ROTATE_CW[orientation]
    if rot == 90:
        out = np.rot90(out, k=-1, axes=(0, 1))
    elif rot == 180:
        out = np.rot90(out, k=2, axes=(0, 1))
    elif rot == 270:
        out = np.rot90(out, k=1, axes=(0, 1))
    return np.ascontiguousarray(out)


# --------------------------------------------------------------------------------------
# COLMAP pixel-centre convention (plan 30.3)
# --------------------------------------------------------------------------------------
def colmap_convention(K: np.ndarray) -> np.ndarray:
    """OpenCV pixel centre ``(0,0)`` -> COLMAP ``cx+0.5, cy+0.5`` (top-left corner)."""
    K = np.asarray(K, dtype=np.float64).copy()
    if K.shape != (3, 3):
        raise SynLabError(ErrorCode.SCHEMA_INVALID, f"K must be (3,3), got {K.shape}",
                          stage="cameras.colmap_convention")
    K[0, 2] += 0.5
    K[1, 2] += 0.5
    return K


def colmap_unconvention(K: np.ndarray) -> np.ndarray:
    """COLMAP ``(0.5, 0.5)`` origin -> OpenCV pixel centre ``(0, 0)``."""
    K = np.asarray(K, dtype=np.float64).copy()
    if K.shape != (3, 3):
        raise SynLabError(ErrorCode.SCHEMA_INVALID, f"K must be (3,3), got {K.shape}",
                          stage="cameras.colmap_unconvention")
    K[0, 2] -= 0.5
    K[1, 2] -= 0.5
    return K


def to_colmap_pixels(uv: np.ndarray) -> np.ndarray:
    """Pixel coordinates for COLMAP: OpenCV centre -> COLMAP corner convention."""
    uv = np.asarray(uv, dtype=np.float64).reshape(-1, 2)
    return uv + 0.5


def from_colmap_pixels(uv: np.ndarray) -> np.ndarray:
    uv = np.asarray(uv, dtype=np.float64).reshape(-1, 2)
    return uv - 0.5


def to_colmap_pose(T_WC: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """COLMAP ``(qvec, tvec)`` with ``X_C = R X_W + t`` (world-to-camera)."""
    T = _as_T(T_WC)
    R = T[:3, :3]
    C = T[:3, 3]
    R_cw = R.T
    t_cw = -R_cw @ C
    q = _rotation_to_quaternion(R_cw)
    return q, t_cw


def from_colmap_pose(qvec: np.ndarray, tvec: np.ndarray) -> np.ndarray:
    """Inverse of :func:`to_colmap_pose`: returns ``T_WC``."""
    R_cw = _quaternion_to_rotation(np.asarray(qvec, dtype=np.float64).ravel())
    t_cw = np.asarray(tvec, dtype=np.float64).ravel()
    R_wc = R_cw.T
    C = -R_wc @ t_cw
    T = np.eye(4, dtype=np.float64)
    T[:3, :3] = R_wc
    T[:3, 3] = C
    return T


def _rotation_to_quaternion(R: np.ndarray) -> np.ndarray:
    """Shepperd's method; COLMAP order is ``(w, x, y, z)``."""
    R = np.asarray(R, dtype=np.float64)
    tr = float(np.trace(R))
    if tr > 0.0:
        s = np.sqrt(tr + 1.0) * 2.0
        w = 0.25 * s
        x = (R[2, 1] - R[1, 2]) / s
        y = (R[0, 2] - R[2, 0]) / s
        z = (R[1, 0] - R[0, 1]) / s
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        s = np.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2]) * 2.0
        w = (R[2, 1] - R[1, 2]) / s
        x = 0.25 * s
        y = (R[0, 1] + R[1, 0]) / s
        z = (R[0, 2] + R[2, 0]) / s
    elif R[1, 1] > R[2, 2]:
        s = np.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2]) * 2.0
        w = (R[0, 2] - R[2, 0]) / s
        x = (R[0, 1] + R[1, 0]) / s
        y = 0.25 * s
        z = (R[1, 2] + R[2, 1]) / s
    else:
        s = np.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1]) * 2.0
        w = (R[1, 0] - R[0, 1]) / s
        x = (R[0, 2] + R[2, 0]) / s
        y = (R[1, 2] + R[2, 1]) / s
        z = 0.25 * s
    q = np.array([w, x, y, z], dtype=np.float64)
    return q / np.linalg.norm(q)


def _quaternion_to_rotation(q: np.ndarray) -> np.ndarray:
    w, x, y, z = q
    n = np.sqrt(w * w + x * x + y * y + z * z)
    if n < 1e-15:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "zero quaternion",
                          stage="cameras.quaternion")
    w, x, y, z = w / n, x / n, y / n, z / n
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ], dtype=np.float64)


def look_at_T_WC(eye: np.ndarray, target: np.ndarray, up: np.ndarray | None = None) -> np.ndarray:
    """Build an OpenCV camera frame from an eye, target, and world-up vector.

    The camera basis is ``(+x right, +y down, +z forward)``.  ``up`` is a world-space
    up direction (default +Z for this repository's Z-up assets), not a desired camera +Y
    direction.  A parallel world-up uses the least-parallel world basis axis deterministically.
    """
    stage = "cameras.look_at"

    def vector3(name: str, value: np.ndarray) -> np.ndarray:
        try:
            result = np.asarray(value, dtype=np.float64)
        except (TypeError, ValueError) as exc:
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              f"{name} must be a finite 3-vector", stage=stage) from exc
        if result.shape != (3,) or not np.isfinite(result).all():
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              f"{name} must be a finite 3-vector", stage=stage,
                              measurements={"shape": result.shape})
        return result

    eye = vector3("eye", eye)
    target = vector3("target", target)
    world_up = vector3("up", np.array([0.0, 0.0, 1.0]) if up is None else up)
    up_norm = float(np.linalg.norm(world_up))
    if not np.isfinite(up_norm) or up_norm <= 1e-12:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "up direction must be non-zero",
                          stage=stage)
    forward = target - eye
    forward_norm = float(np.linalg.norm(forward))
    if not np.isfinite(forward_norm) or forward_norm <= 1e-12:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "camera centre coincides with target",
                          stage=stage)
    z_c = forward / forward_norm
    up_normed = world_up / up_norm

    # With +Z forward, x = forward x world-up points right and y = forward x x points down.
    # Cross products preserve a right-handed rotation matrix (determinant +1).
    x_c = np.cross(z_c, up_normed)
    x_norm = float(np.linalg.norm(x_c))
    if x_norm <= 1e-12:
        # Choose the world axis least parallel to the viewing direction.  This is stable even
        # when the supplied up vector has a very different magnitude from a unit vector.
        fallback_up = np.eye(3, dtype=np.float64)[int(np.argmin(np.abs(z_c)))]
        x_c = np.cross(z_c, fallback_up)
        x_norm = float(np.linalg.norm(x_c))
    x_c /= x_norm
    y_c = np.cross(z_c, x_c)
    T = np.eye(4, dtype=np.float64)
    T[:3, 0] = x_c
    T[:3, 1] = y_c
    T[:3, 2] = z_c
    T[:3, 3] = eye
    return T
