"""
ViewGizmo — Cube Model Matrix for View Direction Gizmo
======================================================

Computes the NDC-space model matrix for the ViewGizmo cube overlay.

CONVENTION:
  Returns numpy ndarray (4×4, float32) in column-vector convention.
  This is a Type B matrix — upload with GL_TRUE.

FORMULA:
  model = T @ R_cube @ S

  where:
    T      = translation to screen corner (SCREEN_OFFSET_X, SCREEN_OFFSET_Y)
    R_cube = camera view rotation with Y/Z axes flipped
    S      = non-uniform scale [size/aspect, size, size, 1]

COORDINATE MAPPING:
  Editor X → GL X
  Editor Y → GL -Z
  Editor Z → GL Y
"""

from __future__ import annotations

import math
import numpy as np


# ── ViewGizmo layout constants ──────────────────────────────
CUBE_SIZE_NDC: float = 0.18
SCREEN_OFFSET_X: float = 0.82
SCREEN_OFFSET_Y: float = 0.78

# Sign conventions for mapping editor camera yaw/pitch to cube rotation
SIGN_PITCH: float = 1.0
SIGN_YAW: float = -1.0


def compute_cube_model(
    vp_w: int,
    vp_h: int,
    yaw: float,
    pitch: float
) -> np.ndarray:
    """Compute the ViewGizmo cube's NDC model matrix.

    The cube is rendered in NDC space (ignore_scene_matrices=True),
    positioned at the screen corner with rotation matching the editor camera.

    Args:
        vp_w: Viewport width in pixels.
        vp_h: Viewport height in pixels.
        yaw: Editor camera yaw angle (radians).
        pitch: Editor camera pitch angle (radians).

    Returns:
        numpy ndarray: 4×4 float32 model matrix in column-vector convention.
        Upload with glUniformMatrix4fv(..., GL_TRUE, ...) for NDC overlays.

    IMPORTANT:
        This is a Type B matrix (numpy ndarray, column-vector convention).
        The overlay visual pass correctly uses GL_TRUE.
        The overlay pick pass MUST ALSO use GL_TRUE (not GL_FALSE).
    """
    sp = math.sin(pitch) * SIGN_PITCH
    cp = math.cos(pitch)
    sy = math.sin(yaw) * SIGN_YAW
    cy = math.cos(yaw)
    # View rotation matrix R_view (3×3)
    R_view = np.array([
        [cy,        0.0,      sy],
        [sy * sp,  -cp,     -cy * sp],
        [-sy * cp, -sp,      cy * cp],
    ], dtype=np.float32)
    # 原版: 翻转 Y/Z 轴 (det=-1 反射, 但视觉上相当于绕 X 轴 180°)
    R_cube = R_view.copy()
    R_cube[1, :] *= -1.0
    R_cube[2, :] *= -1.0
    # Build 4×4 rotation matrix
    rot_mat = np.identity(4, dtype=np.float32)
    rot_mat[:3, :3] = R_cube
    # Uniform scale — cube stays a cube in 3D
    s = CUBE_SIZE_NDC
    scale_uniform = np.diag([s, s, s, 1.0]).astype(np.float32)
    # Aspect‑ratio compensation applied *after* rotation (like a
    # projection matrix), so the cube's 3D proportions are preserved
    # while the on‑screen XY projection appears square.
    aspect = vp_w / max(vp_h, 1)
    scale_aspect = np.diag([1.0 / aspect, 1.0, 1.0, 1.0]).astype(np.float32)
    # Translation to screen corner
    trans_mat = np.identity(4, dtype=np.float32)
    trans_mat[0, 3] = SCREEN_OFFSET_X
    trans_mat[1, 3] = SCREEN_OFFSET_Y
    # model = T @ R @ (uniform_cube)  — 不含 aspect，aspect 由投影矩阵处理
    return (trans_mat @ rot_mat @ scale_uniform).astype(np.float32)


def compute_ortho_proj(vp_w: int, vp_h: int) -> np.ndarray:
    """返回 ViewGizmo 的正交投影矩阵（仅 aspect 矫正）。"""
    aspect = vp_w / max(vp_h, 1)
    proj = np.diag([1.0 / aspect, 1.0, 1.0, 1.0]).astype(np.float32)
    return proj
