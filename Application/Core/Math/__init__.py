"""
Core.Math — Unified Matrix & Transform Utilities
================================================

This module is the SINGLE SOURCE OF TRUTH for all matrix math in the engine.
All functions return numpy ndarray (dtype float32) in STANDARD MATH CONVENTION:
column vectors: v' = M @ v.

════════════════════════════════════════════════════════════════
MATRIX CONVENTION — MUST READ
════════════════════════════════════════════════════════════════

Two types of matrices exist in this codebase:

  TYPE A: pyrr Matrix44
    - Uses ROW-VECTOR convention internally:  v' = v * M
    - Example: pyrr's translation(3,5,7) stores [3,5,7] in the BOTTOM row
    - When converted to numpy C-contiguous, the byte stream becomes
      column-vector order (transposed)
    - OpenGL upload: MUST USE glUniformMatrix4fv(..., GL_FALSE, ...)
    - Source: pyrr.matrix44.create_*, Matrix44.from_*, EditorCamera

  TYPE B: numpy ndarray (standard math convention)
    - Uses COLUMN-VECTOR convention:  v' = M @ v
    - Example: translation(3,5,7) stores 3 in row 0 col 3 (right column)
    - Standard C-order memory layout: row by row
    - OpenGL upload: MUST USE glUniformMatrix4fv(..., GL_TRUE, ...)
    - Source: ALL functions in this module, ViewGizmo model_cb

  ┌──────────────────────┬──────────┬───────────────┐
  │ Source               │ Type     │ GL upload flag │
  ├──────────────────────┼──────────┼───────────────┤
  │ Core.Math functions  │ numpy B  │ GL_TRUE       │
  │ pyrr create_look_at  │ pyrr  A  │ GL_FALSE      │
  │ pyrr create_persp... │ pyrr  A  │ GL_FALSE      │
  │ pyrr Matrix44 (TRS)  │ pyrr  A  │ GL_FALSE      │
  │ EditorCamera (pyrr)  │ pyrr  A  │ GL_FALSE      │
  │ ViewGizmo model_cb   │ numpy B  │ GL_TRUE       │
  │ overlay model_cb     │ numpy B  │ GL_TRUE       │
  └──────────────────────┴──────────┴───────────────┘

GOLDEN RULE:
  When uploading a matrix to OpenGL, check its SOURCE:
    - If from pyrr (Matrix44, create_look_at, etc.) → GL_FALSE
    - If from numpy ndarray (np.array, np.identity, @ operator) → GL_TRUE

  When in doubt, use the helper::

      from Application.Core.Math import upload_mat4_to_gl
      upload_mat4_to_gl(program, 'uModel', matrix)

  This auto-detects the matrix type and uses the correct GL flag.

SUB-MODULES:
  - Transform  : TRS entity model matrix calculation
  - Camera     : View / Projection / Orbit camera math
  - ViewGizmo  : ViewGizmo cube NDC model matrix
"""

from __future__ import annotations

# ── Re-export all public symbols ────────────────────────────
from Application.Core.Math.Transform import calculate_entity_model
from Application.Core.Math.Camera import (
    calculate_view_matrix,
    calculate_projection_matrix,
    compute_orbit_position,
    compute_orbit_view_matrix,
    compute_orbit_projection_matrix,
    compute_perspective_matrix,
    compute_orthographic_matrix,
    get_world_forward,
)
from Application.Core.Math.ViewGizmo import compute_cube_model

__all__ = [
    # Transform
    "calculate_entity_model",
    # Camera
    "calculate_view_matrix",
    "calculate_projection_matrix",
    "compute_orbit_position",
    "compute_orbit_view_matrix",
    "compute_orbit_projection_matrix",
    "compute_perspective_matrix",
    "compute_orthographic_matrix",
    "get_world_forward",
    # ViewGizmo
    "compute_cube_model",
]
