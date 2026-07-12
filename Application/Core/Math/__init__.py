"""
Core.Math — Unified Matrix & Transform Utilities
================================================

This module is the SINGLE SOURCE OF TRUTH for all matrix math in the engine.
All functions accept plain numeric values (float / tuple / np.ndarray) —
NO dependency on Scene/ECS types. Scene layer wraps Math functions for convenience.

════════════════════════════════════════════════════════════════
MATRIX CONVENTION — MUST READ
════════════════════════════════════════════════════════════════

Two types of matrices exist in this codebase:

  TYPE A: pyrr Matrix44
    - Uses ROW-VECTOR convention internally:  v' = v * M
    - When converted to numpy C-contiguous, the byte stream becomes
      column-vector order (transposed)
    - OpenGL upload: MUST USE glUniformMatrix4fv(..., GL_FALSE, ...)
    - Source: pyrr.matrix44.create_*, EditorCamera, OrbitCamera

  TYPE B: numpy ndarray (standard math convention)
    - Uses COLUMN-VECTOR convention:  v' = M @ v
    - Standard C-order memory layout: row by row
    - OpenGL upload: MUST USE glUniformMatrix4fv(..., GL_TRUE, ...)
    - Source: ViewGizmo compute_cube_model, compute_ortho_proj

  ┌──────────────────────────────┬──────────┬───────────────┐
  │ Source                       │ Type     │ GL upload flag │
  ├──────────────────────────────┼──────────┼───────────────┤
  │ Math.Transform (pyrr-backed) │ pyrr  A  │ GL_FALSE      │
  │ Math.Camera   (pyrr-backed)  │ pyrr  A  │ GL_FALSE      │
  │ EditorCamera (pyrr)          │ pyrr  A  │ GL_FALSE      │
  │ OrbitCamera  (pyrr)          │ pyrr  A  │ GL_FALSE      │
  │ ViewGizmo compute_cube_model │ numpy B  │ GL_TRUE       │
  │ ViewGizmo compute_ortho_proj │ numpy B  │ GL_TRUE       │
  └──────────────────────────────┴──────────┴───────────────┘

SUB-MODULES:
  - Transform       : TRS entity model matrix from (position, rotation, scale) tuples
  - Camera          : View / Projection / Orbit camera math (pure numeric params)
  - ViewGizmo       : ViewGizmo cube NDC model matrix
  - CoordinateSystem: Editor ↔ GL coordinate axis conversion
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
from Application.Core.Math.CoordinateSystem import (
    gl_to_editor_position,
    editor_to_gl_position,
    gl_to_editor_scale,
    editor_to_gl_scale,
    gl_to_editor_vec3,
    editor_to_gl_vec3,
    gl_to_editor_scale_vec3,
    editor_to_gl_scale_vec3,
)

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
    # CoordinateSystem
    "gl_to_editor_position",
    "editor_to_gl_position",
    "gl_to_editor_scale",
    "editor_to_gl_scale",
    "gl_to_editor_vec3",
    "editor_to_gl_vec3",
    "gl_to_editor_scale_vec3",
    "editor_to_gl_scale_vec3",
]
