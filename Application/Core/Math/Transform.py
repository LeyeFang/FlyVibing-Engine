"""
Transform — Entity Model Matrix (TRS Decomposition)
====================================================

Calculates the 4x4 model matrix from raw position/rotation/scale parameters.

Convention:
  - Input:  plain numeric tuples (no ECS / Scene dependency — pure math)
  - Returns: numpy ndarray (4×4, float64, row-vector convention, C-contiguous)
  - Formula: M = T @ R @ S  (row-vector: v' = v * M)
    - S: scale matrix
    - R: rotation matrix (Euler Z*Y*X, pure numpy)
    - T: translation matrix
  - For OpenGL/ZenGL upload: GL_FALSE (C-contiguous bytes → column-vector in shader)

Design:
  Math 层不依赖任何 Scene/ECS 类型。调用方从 ECS 组件中提取数值
  后传入纯数值参数。SceneManager 提供 GetEntityModelMatrix() 便捷封装。

Note: 原使用 pyrr 实现，但 pyrr 的 Matrix44.from_translation 存在跨调用
内部状态污染 bug（不同 entity 的平移矩阵会相互覆盖）。已改为纯 numpy 实现。
"""

from __future__ import annotations

import numpy as np


def calculate_entity_model(
    position: tuple[float, float, float] = (0.0, 0.0, 0.0),
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0),
) -> np.ndarray:
    """Calculate the 4x4 TRS model matrix from raw position/rotation/scale.

    Pure numpy — no pyrr dependency. Direct matrix construction avoids
    intermediate array allocations and matmuls for performance.

    Convention: row-vector (v' = v * M), translation in last row.
    Returns: float64 ndarray 4×4, C-contiguous.
    """
    import math
    px, py, pz = float(position[0]), float(position[1]), float(position[2])
    rx, ry, rz = float(rotation[0]), float(rotation[1]), float(rotation[2])
    sx, sy, sz = float(scale[0]), float(scale[1]), float(scale[2])

    # ── Fast path: no rotation, no non-uniform scale ──
    if rx == 0.0 and ry == 0.0 and rz == 0.0:
        M = np.array([
            [sx, 0,  0,  0],
            [0,  sy, 0,  0],
            [0,  0,  sz, 0],
            [px, py, pz, 1],
        ], dtype=np.float64)
        return M

    # ── Rotation matrix 3×3: R = Rz @ Ry @ Rx (Z*Y*X Euler) ──
    cx, sx_v = math.cos(rx), math.sin(rx)
    cy, sy_v = math.cos(ry), math.sin(ry)
    cz, sz_v = math.cos(rz), math.sin(rz)

    # Build R directly: R = Rz @ Ry @ Rx
    # Rx = [[1,0,0],[0,cx,-sx],[0,sx,cx]]
    # Ry = [[cy,0,sy],[0,1,0],[-sy,0,cy]]
    # Rz = [[cz,-sz,0],[sz,cz,0],[0,0,1]]
    # Precompute intermediates to avoid 3x3 matmul allocations
    # Ry @ Rx:
    r00 = cy
    r01 = sy_v * sx_v
    r02 = sy_v * cx
    r10 = 0.0
    r11 = cx
    r12 = -sx_v
    r20 = -sy_v
    r21 = cy * sx_v
    r22 = cy * cx
    # Rz @ (Ry @ Rx):
    R00 = cz * r00 + (-sz_v) * r10  # = cz*cy
    R01 = cz * r01 + (-sz_v) * r11  # = cz*sy*sx - sz*cx
    R02 = cz * r02 + (-sz_v) * r12  # = cz*sy*cx + sz*sx
    R10 = sz_v * r00 + cz * r10     # = sz*cy
    R11 = sz_v * r01 + cz * r11     # = sz*sy*sx + cz*cx
    R12 = sz_v * r02 + cz * r12     # = sz*sy*cx - cz*sx
    R20 = r20                        # = -sy
    R21 = r21                        # = cy*sx
    R22 = r22                        # = cy*cx

    # ── Build final 4×4 matrix: M = T @ R @ S ──
    # Upper-left 3×3 = R scaled by columns: M[i,j] = R[i,j] * S[j,j]
    # Bottom row: M[3,j] = S[j,j] * dot([px,py,pz], R_col_j)
    # Right column: M[i,3] = 0 (i<3), M[3,3] = 1
    M = np.array([
        [R00 * sx,  R01 * sy,  R02 * sz,  0.0],
        [R10 * sx,  R11 * sy,  R12 * sz,  0.0],
        [R20 * sx,  R21 * sy,  R22 * sz,  0.0],
        [sx * (px * R00 + py * R10 + pz * R20),
         sy * (px * R01 + py * R11 + pz * R21),
         sz * (px * R02 + py * R12 + pz * R22),
         1.0],
    ], dtype=np.float64)
    return M


def _build_R_T(rx: float, ry: float, rz: float) -> 'np.ndarray':
    """构建 R^T (旋转逆矩阵), 用于 world pos → pre-rotation pos 转换。

    pre_pos = world_pos @ R_T

    Args:
        rx, ry, rz: 欧拉角 (弧度), 与 calculate_entity_model 约定一致。
    Returns:
        (3, 3) float64 ndarray
    """
    import math
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    # R^T from calculate_entity_model's R = Rz @ Ry @ Rx
    return np.array([
        [cz * cy,                      sz * cy,                      -sy],
        [cz * sy * sx - sz * cx,       sz * sy * sx + cz * cx,       cy * sx],
        [cz * sy * cx + sz * sx,       sz * sy * cx - cz * sx,       cy * cx],
    ], dtype=np.float64)


# ═══════════════════════════════════════════════════════════════
# Local ↔ World 转换 (纯数学, 零 Scene/ECS 依赖)
# ═══════════════════════════════════════════════════════════════

def local_to_world_position(
    local_pos: tuple[float, float, float],
    parent_world_pos: tuple[float, float, float],
) -> tuple[float, float, float]:
    """Local 位置 → World 位置 (Euler 简化: 不考虑父旋转对子位置的影响)。

    world = local + parent_world
    """
    return (local_pos[0] + parent_world_pos[0],
            local_pos[1] + parent_world_pos[1],
            local_pos[2] + parent_world_pos[2])


def world_to_local_position(
    world_pos: tuple[float, float, float],
    parent_world_pos: tuple[float, float, float],
) -> tuple[float, float, float]:
    """World 位置 → Local 位置。

    local = world - parent_world
    """
    return (world_pos[0] - parent_world_pos[0],
            world_pos[1] - parent_world_pos[1],
            world_pos[2] - parent_world_pos[2])


def local_to_world_rotation(
    local_rot: tuple[float, float, float],
    parent_world_rot: tuple[float, float, float],
) -> tuple[float, float, float]:
    """Local 旋转 → World 旋转 (Euler 分量累加)。

    world = local + parent_world
    """
    return (local_rot[0] + parent_world_rot[0],
            local_rot[1] + parent_world_rot[1],
            local_rot[2] + parent_world_rot[2])


def world_to_local_rotation(
    world_rot: tuple[float, float, float],
    parent_world_rot: tuple[float, float, float],
) -> tuple[float, float, float]:
    """World 旋转 → Local 旋转 (Euler 分量相减)。

    local = world - parent_world
    """
    return (world_rot[0] - parent_world_rot[0],
            world_rot[1] - parent_world_rot[1],
            world_rot[2] - parent_world_rot[2])


def local_to_world_scale(
    local_scl: tuple[float, float, float],
    parent_world_scl: tuple[float, float, float],
) -> tuple[float, float, float]:
    """Local 缩放 → World 缩放 (component-wise 乘法)。

    world = local * parent_world
    """
    return (local_scl[0] * parent_world_scl[0],
            local_scl[1] * parent_world_scl[1],
            local_scl[2] * parent_world_scl[2])


def world_to_local_scale(
    world_scl: tuple[float, float, float],
    parent_world_scl: tuple[float, float, float],
) -> tuple[float, float, float]:
    """World 缩放 → Local 缩放 (component-wise 除法)。

    local = world / parent_world
    """
    psx, psy, psz = parent_world_scl
    return (world_scl[0] / psx if psx != 0 else world_scl[0],
            world_scl[1] / psy if psy != 0 else world_scl[1],
            world_scl[2] / psz if psz != 0 else world_scl[2])
