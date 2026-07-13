"""
Camera — View & Projection Matrix Utilities
============================================

All camera-related matrix calculations in one place.

Design:
  Math 层不依赖任何 Scene/ECS 类型。所有函数接受纯数值参数
  (float, tuple, np.ndarray)。调用方从 ECS 组件中提取数值后传入。

CONVENTION:
  All functions are pure numpy — NO pyrr dependency.
  Matrices use row-vector convention (v' = v * M), translation in last row.
  Upload with GL_FALSE.

FUNCTIONS:
  For Scene Camera (free camera):
    calculate_view_matrix(position, rotation, local_forward, up, target=None) → np.ndarray
    calculate_projection_matrix(fov, aspect, near, far, is_ortho, ortho_size) → np.ndarray
    get_world_forward(rotation, local_forward) → np.ndarray

  For Editor Camera (orbit camera):
    compute_orbit_position(yaw, pitch, distance, target) → np.ndarray
    compute_orbit_view_matrix(yaw, pitch, distance, target, up) → np.ndarray
    compute_orbit_projection_matrix(fov, aspect, near, far) → np.ndarray

  Low-level (no ECS dependency):
    compute_perspective_matrix(fov, aspect, near, far) → np.ndarray
    compute_orthographic_matrix(left, right, bottom, top, near, far) → np.ndarray

  Internal helpers (also usable from outside):
    look_at(eye, target, up) → np.ndarray
    perspective_projection(fov, aspect, near, far) → np.ndarray
    orthogonal_projection(left, right, bottom, top, near, far) → np.ndarray
    euler_rotation(rx, ry, rz) → np.ndarray
"""

from __future__ import annotations

import math
import numpy as np


# ═══════════════════════════════════════════════════════════════
# Internal helpers — pure numpy, pyrr-compatible output
# ═══════════════════════════════════════════════════════════════

def look_at(
    eye: np.ndarray,
    target: np.ndarray,
    up: np.ndarray,
) -> np.ndarray:
    """Pure-numpy look-at view matrix (row-vector convention, pyrr-compatible).

    Convention: v_view = v_world @ V
    Basis vectors stored as COLUMNS (like pyrr), translation in last row.
    When uploaded with GL_FALSE, transposes to standard OpenGL lookAt.

    Args:
        eye:    3-element camera position.
        target: 3-element look-at target point.
        up:     3-element world up vector.

    Returns:
        float32 4×4 view matrix, row-vector convention (GL_FALSE upload).
    """
    eye = np.asarray(eye, dtype=np.float32)
    target = np.asarray(target, dtype=np.float32)
    up = np.asarray(up, dtype=np.float32)

    # f = normalize(eye - target): world-space forward (target → eye)
    f = eye - target
    f /= np.linalg.norm(f)

    # r = normalize(cross(up, f)): world-space right
    r = np.cross(up, f)
    r_norm = np.linalg.norm(r)
    r = r / r_norm if r_norm > 1e-8 else np.array([1.0, 0.0, 0.0], dtype=np.float32)

    # u = cross(f, r): world-space up (re-orthogonalized)
    u = np.cross(f, r)

    # Row-vector view matrix: basis vectors in COLUMNS (pyrr-compatible)
    # Row 0 = [r.x, u.x, f.x, 0]
    # Row 1 = [r.y, u.y, f.y, 0]
    # Row 2 = [r.z, u.z, f.z, 0]
    # Row 3 = [-dot(r,eye), -dot(u,eye), -dot(f,eye), 1]
    V = np.identity(4, dtype=np.float32)
    V[0, 0] = r[0]; V[0, 1] = u[0]; V[0, 2] = f[0]
    V[1, 0] = r[1]; V[1, 1] = u[1]; V[1, 2] = f[1]
    V[2, 0] = r[2]; V[2, 1] = u[2]; V[2, 2] = f[2]
    V[3, 0] = -np.dot(r, eye)
    V[3, 1] = -np.dot(u, eye)
    V[3, 2] = -np.dot(f, eye)
    return V


def perspective_projection(
    fov: float,
    aspect_ratio: float,
    near: float = 0.1,
    far: float = 1000.0,
) -> np.ndarray:
    """Pure-numpy perspective projection (row-vector, pyrr-compatible).

    Right-handed, NDC [-1,1]. Upload with GL_FALSE.

    Args:
        fov:          Vertical FOV in degrees.
        aspect_ratio: Viewport width / height.
        near:         Near clipping plane.
        far:          Far clipping plane.

    Returns:
        float32 4×4 projection matrix.
    """
    fov_rad = math.radians(fov)
    f = 1.0 / math.tan(fov_rad / 2.0)
    nf = 1.0 / (near - far)

    P = np.zeros((4, 4), dtype=np.float32)
    P[0, 0] = f / aspect_ratio
    P[1, 1] = f
    P[2, 2] = (far + near) * nf
    P[2, 3] = -1.0
    P[3, 2] = (2.0 * far * near) * nf
    return P


def orthogonal_projection(
    left: float, right: float,
    bottom: float, top: float,
    near: float, far: float,
) -> np.ndarray:
    """Pure-numpy orthographic projection (row-vector, pyrr-compatible).

    Right-handed, NDC [-1,1]. Upload with GL_FALSE.

    Returns:
        float32 4×4 projection matrix.
    """
    rl = 1.0 / (right - left)
    tb = 1.0 / (top - bottom)
    fn = 1.0 / (far - near)

    P = np.identity(4, dtype=np.float32)
    P[0, 0] = 2.0 * rl
    P[1, 1] = 2.0 * tb
    P[2, 2] = -2.0 * fn
    P[3, 0] = -(right + left) * rl
    P[3, 1] = -(top + bottom) * tb
    P[3, 2] = -(far + near) * fn
    return P


def euler_rotation(
    rx: float = 0.0,
    ry: float = 0.0,
    rz: float = 0.0,
) -> np.ndarray:
    """Pure-numpy Euler rotation matrix (pyrr-compatible Tait-Bryan convention).

    Matches pyrr's create_from_eulers([rx, ry, rz]) where:
      - rx = roll  (rotation around X / forward axis)
      - ry = pitch (rotation around Y / right axis)
      - rz = yaw   (rotation around Z / up axis)

    Internal formula (row-vector): R = yaw_matrix @ pitch_matrix @ roll_matrix
    Translation row is zero, bottom-right = 1.

    Returns:
        float32 4×4 rotation matrix.
    """
    cr, sr = math.cos(rx), math.sin(rx)  # roll
    cp, sp = math.cos(ry), math.sin(ry)  # pitch
    cy, sy = math.cos(rz), math.sin(rz)  # yaw

    R = np.identity(4, dtype=np.float32)
    # Row 0
    R[0, 0] = cy * cp
    R[0, 1] = -cy * sp * cr + sy * sr
    R[0, 2] = cy * sp * sr + sy * cr
    # Row 1
    R[1, 0] = sp
    R[1, 1] = cp * cr
    R[1, 2] = -cp * sr
    # Row 2
    R[2, 0] = -sy * cp
    R[2, 1] = sy * sp * cr + cy * sr
    R[2, 2] = -sy * sp * sr + cy * cr
    return R


def apply_rotation_to_vector(
    rot: np.ndarray,
    vec: np.ndarray,
) -> np.ndarray:
    """Apply row-vector 4×4 rotation to a direction vector (w=0).

    Equivalent to pyrr's apply_to_vector: v_world = (v_local, 0) @ rot

    Args:
        rot: 4×4 row-vector rotation matrix.
        vec: 3-element direction vector.

    Returns:
        3-element float32 direction vector in world space.
    """
    v4 = np.array([vec[0], vec[1], vec[2], 0.0], dtype=np.float32)
    result = v4 @ rot
    return result[:3]


# ═══════════════════════════════════════════════════════════════
# Scene Camera (free camera — pure numeric parameters)
# ═══════════════════════════════════════════════════════════════

def calculate_view_matrix(
    position: tuple[float, float, float],
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
    local_forward: tuple[float, float, float] = (0.0, 0.0, -1.0),
    up_vector: tuple[float, float, float] = (0.0, 1.0, 0.0),
    target: np.ndarray = None,
) -> np.ndarray:
    """Calculate view matrix from raw camera parameters.

    Two modes:
      - Orbit mode (target is not None):
        Uses target as the look-at point. Camera orbits around target.

      - Free camera mode (target is None):
        Uses rotation matrix + local_forward to compute look-at target.

    Args:
        position:      World-space camera position (px, py, pz).
        rotation:      Euler angles in radians (rx=pitch, ry=yaw, rz=roll).
        local_forward: Forward direction in camera local space (default: -Z).
        up_vector:     World up vector (default: +Y).
        target:        Optional orbit target point (world space, shape (3,)).

    Returns:
        numpy ndarray: 4×4 float32 view matrix (row-vector).
        Upload with glUniformMatrix4fv(..., GL_FALSE, ...).
    """
    pos = np.array(list(position), dtype=np.float32)
    up = np.array(list(up_vector), dtype=np.float32)

    if target is not None:
        return look_at(pos, np.asarray(target, dtype=np.float32), up)

    # Free camera: rotate local forward direction to world space
    rot_mat = euler_rotation(*rotation)
    local_fwd = np.array(list(local_forward), dtype=np.float32)
    world_fwd = apply_rotation_to_vector(rot_mat, local_fwd)
    target_from_rot = pos + world_fwd
    return look_at(pos, target_from_rot, up)


def calculate_projection_matrix(
    fov: float = 45.0,
    aspect_ratio: float = 16.0 / 9.0,
    near: float = 0.1,
    far: float = 1000.0,
    is_ortho: bool = False,
    ortho_size: float = 5.0,
) -> np.ndarray:
    """Calculate projection matrix from raw parameters.

    Args:
        fov:          Vertical field of view in degrees (perspective only).
        aspect_ratio: Viewport aspect ratio (width / height).
        near:         Near clipping plane.
        far:          Far clipping plane.
        is_ortho:     If True, use orthographic projection.
        ortho_size:   Ortho half-height in world units (ortho only).

    Returns:
        numpy ndarray: 4×4 float32 projection matrix (row-vector).
        Upload with glUniformMatrix4fv(..., GL_FALSE, ...).
    """
    if is_ortho:
        half_h = ortho_size
        half_w = half_h * aspect_ratio
        return orthogonal_projection(-half_w, half_w, -half_h, half_h, near, far)
    else:
        return perspective_projection(fov, aspect_ratio, near, far)


def get_world_forward(
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
    local_forward: tuple[float, float, float] = (0.0, 0.0, -1.0),
) -> np.ndarray:
    """Get the camera's forward direction in world space (unit vector).

    Args:
        rotation:      Euler angles in radians (rx, ry, rz).
        local_forward: Forward direction in camera local space (default: -Z).

    Returns:
        numpy ndarray: 3-element float32 unit vector in world space.
    """
    rot_mat = euler_rotation(*rotation)
    local_fwd = np.array(list(local_forward), dtype=np.float32)
    world_fwd = apply_rotation_to_vector(rot_mat, local_fwd)
    # Normalize to unit vector
    fwd_len = np.linalg.norm(world_fwd)
    if fwd_len > 0:
        world_fwd = world_fwd / fwd_len
    return world_fwd


# ═══════════════════════════════════════════════════════════════
# Editor Camera (orbit camera)
# ═══════════════════════════════════════════════════════════════

def compute_orbit_position(
    yaw: float,
    pitch: float,
    distance: float,
    target: np.ndarray | tuple | list = None
) -> np.ndarray:
    """Compute camera world position from spherical coordinates.

    Spherical convention:
      direction = (sin(yaw)*cos(pitch), sin(pitch), -cos(yaw)*cos(pitch))
      position  = target + distance * direction

    Args:
        yaw: Horizontal orbit angle (radians). 0 = facing -Z.
        pitch: Vertical orbit angle (radians). 0 = horizon, +/-pi/2 = top/bottom.
        distance: Distance from orbit target.
        target: Orbit target point (world space, shape (3,)). Default: origin.

    Returns:
        numpy ndarray: 3-element float32 position in world space.
    """
    if target is None:
        target = np.zeros(3, dtype=np.float32)
    elif not isinstance(target, np.ndarray):
        target = np.array(target, dtype=np.float32)

    dx = math.sin(yaw) * math.cos(pitch)
    dy = math.sin(pitch)
    dz = -math.cos(yaw) * math.cos(pitch)

    position = np.empty(3, dtype=np.float32)
    position[0] = target[0] + dx * distance
    position[1] = target[1] + dy * distance
    position[2] = target[2] + dz * distance
    return position


def compute_orbit_view_matrix(
    yaw: float,
    pitch: float,
    distance: float,
    target: np.ndarray | tuple | list = None,
    up: tuple = (0.0, 1.0, 0.0)
) -> np.ndarray:
    """Compute view matrix for an orbit camera.

    Pure numpy — returns row-vector view matrix. Upload with GL_FALSE.

    Args:
        yaw: Horizontal orbit angle (radians).
        pitch: Vertical orbit angle (radians).
        distance: Distance from orbit target.
        target: Orbit target point (shape (3,)). Default: origin.
        up: World up vector. Default: (0, 1, 0).

    Returns:
        numpy ndarray: 4×4 float32 view matrix.
    """
    position = compute_orbit_position(yaw, pitch, distance, target)
    if target is None:
        target = np.zeros(3, dtype=np.float32)
    elif not isinstance(target, np.ndarray):
        target = np.array(target, dtype=np.float32)

    return look_at(position, target, np.array(list(up), dtype=np.float32))


def compute_orbit_projection_matrix(
    fov: float,
    aspect_ratio: float,
    near: float = 0.1,
    far: float = 1000.0
) -> np.ndarray:
    """Compute perspective projection matrix for an orbit camera.

    Pure numpy — returned matrix is row-vector convention. Upload with GL_FALSE.

    Args:
        fov: Vertical field of view in degrees.
        aspect_ratio: Viewport width / height.
        near: Near clipping plane.
        far: Far clipping plane.

    Returns:
        numpy ndarray: 4×4 float32 projection matrix.
    """
    return perspective_projection(fov, aspect_ratio, near, far)


# ═══════════════════════════════════════════════════════════════
# Low-level matrix constructors (pure numpy)
# ═══════════════════════════════════════════════════════════════

def compute_perspective_matrix(
    fov: float,
    aspect_ratio: float,
    near: float = 0.1,
    far: float = 1000.0
) -> np.ndarray:
    """Low-level perspective projection matrix (row-vector, GL_FALSE upload).

    Args:
        fov: Vertical field of view in degrees.
        aspect_ratio: Viewport width / height.
        near: Near clipping plane.
        far: Far clipping plane.

    Returns:
        numpy ndarray: 4×4 float32 projection matrix.
    """
    return perspective_projection(fov, aspect_ratio, near, far)


def compute_orthographic_matrix(
    left: float, right: float,
    bottom: float, top: float,
    near: float, far: float
) -> np.ndarray:
    """Low-level orthographic projection matrix (row-vector, GL_FALSE upload).

    Returns:
        numpy ndarray: 4×4 float32 projection matrix.
    """
    return orthogonal_projection(left, right, bottom, top, near, far)
