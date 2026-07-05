"""
Transform — Entity Model Matrix (TRS Decomposition)
====================================================

Calculates the 4x4 model matrix from raw position/rotation/scale parameters.

Convention:
  - Input:  plain numeric tuples (no ECS / Scene dependency — pure math)
  - Returns: pyrr-style numpy ndarray (4×4, float32, row-vector convention)
  - Formula: M = T @ R @ S (pyrr internally: trans_mat * rot_mat * scale_mat)
    - S: scale matrix
    - R: rotation matrix (Euler Z*Y*X via pyrr)
    - T: translation matrix
  - For OpenGL upload: use GL_FALSE (pyrr Matrix44 → numpy C-contiguous)

Design:
  Math 层不依赖任何 Scene/ECS 类型。调用方从 ECS 组件中提取数值
  后传入纯数值参数。SceneManager 提供 GetEntityModelMatrix() 便捷封装。
"""

from __future__ import annotations

import numpy as np
from pyrr import Matrix44, Vector3


def calculate_entity_model(
    position: tuple[float, float, float] = (0.0, 0.0, 0.0),
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0),
) -> np.ndarray:
    """Calculate the 4x4 TRS model matrix from raw position/rotation/scale.

    Decomposition: M = T @ R @ S (column-vector convention)

    Args:
        position: (px, py, pz) — translation in world units.
        rotation: (rx, ry, rz) — Euler angles in radians (Z*Y*X order).
        scale:    (sx, sy, sz) — non-uniform scale factors.

    Returns:
        numpy ndarray: 4×4 float32 model matrix (pyrr-style, row-vector).
        Upload with glUniformMatrix4fv(..., GL_FALSE, ...).

    Convenience:
        SceneManager.GetEntityModelMatrix(entity_id) wraps this for ECS entities.
    """
    px, py, pz = position
    rx, ry, rz = rotation
    sx, sy, sz = scale

    # 1. Scale matrix
    scale_mat = Matrix44.from_scale(Vector3([sx, sy, sz]), dtype=float)

    # 2. Rotation matrix from Euler angles (Z * Y * X)
    rot_mat = Matrix44.from_eulers(Vector3([rx, ry, rz]), dtype=float)

    # 3. Translation matrix
    trans_mat = Matrix44.from_translation(Vector3([px, py, pz]), dtype=float)

    # TRS composition (pyrr row-vector convention)
    # The result, when uploaded with GL_FALSE, gives the correct
    # column-vector model matrix in OpenGL.
    return trans_mat * rot_mat * scale_mat
