"""
Camera — View & Projection Matrix Utilities
============================================

All camera-related matrix calculations in one place.

Design:
  Math 层不依赖任何 Scene/ECS 类型。所有函数接受纯数值参数
  (float, tuple, np.ndarray)。调用方从 ECS 组件中提取数值后传入。

CONVENTION:
  Most functions use pyrr internally and return pyrr-style matrices
  (row-vector convention). Upload with GL_FALSE.

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
"""

from __future__ import annotations

import math
import numpy as np
from pyrr import matrix44, Matrix44, vector4, vector3, Vector3


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
        numpy ndarray: 4×4 float32 view matrix (pyrr-style, row-vector).
        Upload with glUniformMatrix4fv(..., GL_FALSE, ...).
    """
    pos = Vector3(list(position))
    up = Vector3(list(up_vector))

    if target is not None:
        return matrix44.create_look_at(pos, Vector3(target), up).astype(np.float32)

    # Free camera: rotate local forward direction to world space
    rot_mat = matrix44.create_from_eulers(list(rotation))
    local_fwd = Vector3(list(local_forward))
    local_fwd_h = vector4.create_from_vector3(local_fwd)  # w=0 (direction)
    world_fwd_vec4 = matrix44.apply_to_vector(rot_mat, local_fwd_h)
    world_fwd = vector3.create_from_vector4(world_fwd_vec4)
    target_from_rot = pos + world_fwd[0]
    return matrix44.create_look_at(pos, target_from_rot, up).astype(np.float32)


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
        numpy ndarray: 4×4 float32 projection matrix (pyrr-style, row-vector).
        Upload with glUniformMatrix4fv(..., GL_FALSE, ...).
    """
    if is_ortho:
        half_h = ortho_size
        half_w = half_h * aspect_ratio
        return matrix44.create_orthogonal_projection(
            -half_w, half_w, -half_h, half_h, near, far
        ).astype(np.float32)
    else:
        return matrix44.create_perspective_projection(
            fov, aspect_ratio, near, far
        ).astype(np.float32)


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
    rot_mat = matrix44.create_from_eulers(list(rotation))
    local_fwd = Vector3(list(local_forward))
    local_fwd_h = vector4.create_from_vector3(local_fwd)
    world_fwd_vec4 = matrix44.apply_to_vector(rot_mat, local_fwd_h)
    world_fwd = vector3.create_from_vector4(world_fwd_vec4)[0]
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

    Uses pyrr.create_look_at internally — the returned matrix is pyrr-style
    (row-vector convention). Upload with GL_FALSE.

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

    return matrix44.create_look_at(
        Vector3(position.tolist()),
        Vector3(target.tolist()),
        Vector3(list(up))
    ).astype(np.float32)


def compute_orbit_projection_matrix(
    fov: float,
    aspect_ratio: float,
    near: float = 0.1,
    far: float = 1000.0
) -> np.ndarray:
    """Compute perspective projection matrix for an orbit camera.

    Uses pyrr.create_perspective_projection internally — returned matrix
    is pyrr-style (row-vector convention). Upload with GL_FALSE.

    Args:
        fov: Vertical field of view in degrees.
        aspect_ratio: Viewport width / height.
        near: Near clipping plane.
        far: Far clipping plane.

    Returns:
        numpy ndarray: 4×4 float32 projection matrix.
    """
    return matrix44.create_perspective_projection(
        fov, aspect_ratio, near, far
    ).astype(np.float32)


# ═══════════════════════════════════════════════════════════════
# Low-level matrix constructors (pyrr-backed)
# ═══════════════════════════════════════════════════════════════

def compute_perspective_matrix(
    fov: float,
    aspect_ratio: float,
    near: float = 0.1,
    far: float = 1000.0
) -> np.ndarray:
    """Low-level perspective projection matrix (pyrr-style, GL_FALSE upload).

    Args:
        fov: Vertical field of view in degrees.
        aspect_ratio: Viewport width / height.
        near: Near clipping plane.
        far: Far clipping plane.

    Returns:
        numpy ndarray: 4×4 float32 projection matrix.
    """
    return matrix44.create_perspective_projection(
        fov, aspect_ratio, near, far
    ).astype(np.float32)


def compute_orthographic_matrix(
    left: float, right: float,
    bottom: float, top: float,
    near: float, far: float
) -> np.ndarray:
    """Low-level orthographic projection matrix (pyrr-style, GL_FALSE upload).

    Returns:
        numpy ndarray: 4×4 float32 projection matrix.
    """
    return matrix44.create_orthogonal_projection(
        left, right, bottom, top, near, far
    ).astype(np.float32)
