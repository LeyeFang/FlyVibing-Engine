"""
Camera — View & Projection Matrix Utilities
============================================

All camera-related matrix calculations in one place.

CONVENTION:
  All functions return numpy ndarray (4×4, float32) in column-vector convention.
  For OpenGL upload: these are Type B matrices → use GL_TRUE.

  Exception: calculate_view_matrix() and calculate_projection_matrix()
  internally use pyrr and return pyrr-style matrices for backward compatibility.
  For these, use GL_FALSE when uploading to OpenGL.

FUNCTIONS:
  For Scene Camera (free camera, uses Transform component):
    calculate_view_matrix(camera, transform, target=None) → np.ndarray
    calculate_projection_matrix(camera, aspect_ratio) → np.ndarray
    get_world_forward(camera, transform) → np.ndarray

  For Editor Camera (orbit camera, uses yaw/pitch/distance):
    compute_orbit_position(yaw, pitch, distance, target) → np.ndarray
    compute_orbit_view_matrix(yaw, pitch, distance, target) → np.ndarray
    compute_orbit_projection_matrix(fov, aspect, near, far) → np.ndarray

  Low-level (no ECS dependency):
    compute_perspective_matrix(fov, aspect, near, far) → np.ndarray
    compute_orthographic_matrix(left, right, bottom, top, near, far) → np.ndarray
"""

from __future__ import annotations

import math
import numpy as np
from pyrr import matrix44, Matrix44, vector4, vector3, Vector3

from Application.Core.Scene.BasicComponents import Camera, Transform, ProjectionType


# ═══════════════════════════════════════════════════════════════
# Scene Camera (free camera, uses ECS Transform)
# ═══════════════════════════════════════════════════════════════

def calculate_view_matrix(
    camera: Camera,
    transform: Transform,
    target: np.ndarray = None
) -> np.ndarray:
    """Calculate view matrix from Camera + Transform components.

    Two modes:
      - Orbit mode (target is not None):
        Uses target as the look-at point. Camera orbits around target.

      - Free camera mode (target is None):
        Uses rotation matrix + local_forward to compute look-at target.

    Args:
        camera: Camera component (up_vector, local_forward, etc.)
        transform: Transform component (position, rotation)
        target: Optional orbit target point (world space, shape (3,))

    Returns:
        numpy ndarray: 4×4 float32 view matrix (pyrr-style, row-vector).
        Upload with glUniformMatrix4fv(..., GL_FALSE, ...).
    """
    pos = Vector3([transform.position_x, transform.position_y, transform.position_z])
    up = Vector3(camera.up_vector)

    if target is not None:
        return matrix44.create_look_at(pos, Vector3(target), up)

    # Free camera: rotate local forward direction to world space
    rot_mat = matrix44.create_from_eulers([
        transform.rotation_x,   # pitch
        transform.rotation_y,   # yaw
        transform.rotation_z    # roll
    ])
    local_forward = Vector3(camera.local_forward)
    local_forward_h = vector4.create_from_vector3(local_forward)  # w=0 (direction)
    world_forward_vec4 = matrix44.apply_to_vector(rot_mat, local_forward_h)
    world_forward = vector3.create_from_vector4(world_forward_vec4)
    target_from_rot = pos + world_forward[0]
    return matrix44.create_look_at(pos, target_from_rot, up)


def calculate_projection_matrix(
    camera: Camera,
    aspect_ratio: float
) -> np.ndarray:
    """Calculate projection matrix from Camera component.

    Args:
        camera: Camera component (fov, near_plane, far_plane, projection_type)
        aspect_ratio: Viewport aspect ratio (width / height)

    Returns:
        numpy ndarray: 4×4 float32 projection matrix (pyrr-style, row-vector).
        Upload with glUniformMatrix4fv(..., GL_FALSE, ...).
    """
    near = camera.near_plane
    far = camera.far_plane
    fov = camera.fov

    if camera.projection_type == ProjectionType.PERSPECTIVE:
        return matrix44.create_perspective_projection(fov, aspect_ratio, near, far)
    else:
        half_h = camera.ortho_size
        half_w = half_h * aspect_ratio
        return matrix44.create_orthogonal_projection(
            -half_w, half_w, -half_h, half_h, near, far
        )


def get_world_forward(
    camera: Camera,
    transform: Transform
) -> np.ndarray:
    """Get the camera's forward direction in world space (unit vector).

    Args:
        camera: Camera component (local_forward)
        transform: Transform component (rotation)

    Returns:
        numpy ndarray: 3-element float32 unit vector in world space.
    """
    rot_mat = matrix44.create_from_eulers([
        transform.rotation_x,
        transform.rotation_y,
        transform.rotation_z
    ])
    local_forward = Vector3(camera.local_forward)
    local_forward_h = vector4.create_from_vector3(local_forward)
    world_forward_vec4 = matrix44.apply_to_vector(rot_mat, local_forward_h)
    world_forward = vector3.create_from_vector4(world_forward_vec4)[0]
    # Normalize to unit vector
    fwd_len = np.linalg.norm(world_forward)
    if fwd_len > 0:
        world_forward = world_forward / fwd_len
    return world_forward


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
