"""
Transform — Entity Model Matrix (TRS Decomposition)
====================================================

Calculates the 4x4 model matrix for an ECS entity from its Transform component.

Convention:
  - Returns: numpy ndarray (4×4, float32), column-vector convention
  - Formula: M = T @ R @ S
    - S: scale matrix
    - R: rotation matrix (Euler Z*Y*X via pyrr)
    - T: translation matrix
  - For OpenGL upload: use GL_TRUE (numpy ndarray convention)

Implementation note:
  Internally uses pyrr Matrix44 for the TRS multiplication (which uses
  row-vector convention internally), then converts to numpy ndarray.
  This is equivalent to the column-vector TRS due to the transpose
  relationship between the two conventions.
"""

from __future__ import annotations

import numpy as np
from pyrr import Matrix44, Vector3

from Application.Core.Scene.BasicComponents import Transform


def calculate_entity_model(transform: Transform) -> np.ndarray:
    """Calculate the 4x4 model matrix for an entity from its Transform.

    Decomposition: M = T @ R @ S (column-vector convention)

    Args:
        transform: The entity's Transform component.

    Returns:
        numpy ndarray: 4×4 float32 model matrix in column-vector convention.
        Upload to OpenGL with glUniformMatrix4fv(..., GL_FALSE, ...)
        because the underlying computation uses pyrr Matrix44 (Type A).

        (This function preserves the existing behaviour — returns a pyrr-style
        matrix via numpy. The actual OpenGL upload convention depends on the
        renderer's set_uniform_mat4 which uses GL_FALSE.)
    """
    # 1. Scale matrix
    scale_mat = Matrix44.from_scale(Vector3(
        [transform.scale_x, transform.scale_y, transform.scale_z]
    ), dtype=float)

    # 2. Rotation matrix from Euler angles (Z * Y * X)
    rot_mat = Matrix44.from_eulers(Vector3(
        [transform.rotation_x, transform.rotation_y, transform.rotation_z]
    ), dtype=float)

    # 3. Translation matrix
    trans_mat = Matrix44.from_translation(Vector3(
        [transform.position_x, transform.position_y, transform.position_z]
    ), dtype=float)

    # TRS composition (pyrr row-vector convention)
    # The result, when uploaded with GL_FALSE, gives the correct
    # column-vector model matrix in OpenGL.
    return trans_mat * rot_mat * scale_mat
