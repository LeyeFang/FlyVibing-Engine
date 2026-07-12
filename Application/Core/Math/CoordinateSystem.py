"""
CoordinateSystem — 编辑器 / GL 坐标系转换 (纯数学, 零依赖)
============================================================

引擎内部所有 Transform 数据统一以 **GL 坐标系** 存储和渲染。
编辑器 UI (ScenePanel, Node Editor 等) 以 **编辑器坐标系** 呈现给用户。

两套坐标系的轴映射:

  编辑器坐标系          GL 坐标系 (存储/渲染)
  ───────────          ─────────────────────
  +X = 右 (right)      +X = 右 (right)       ← 一致
  +Y = 前 (forward)    +Y = 上 (up)          ← 交换
  +Z = 上 (up)         +Z = 后 (backward)    ← 交换 + 翻转
                        -Z = 前 (forward)

转换公式:
  editor → GL:  (ex, ey, ez) → (ex, ez, -ey)
  GL → editor:  (gx, gy, gz) → (gx, -gz, gy)

设计原则:
  - 本模块是唯一权威的坐标系转换来源。
  - 所有需要坐标转换的代码 (SceneManager, Evaluators, Gizmos)
    统一 import 此模块, 禁止在各处内联转换公式。
  - 纯函数, 零依赖, 可在任何上下文中使用。
"""

from __future__ import annotations


# ═══════════════════════════════════════════════════════════════
# Position 转换
# ═══════════════════════════════════════════════════════════════

def gl_to_editor_position(gl_x: float, gl_y: float, gl_z: float) -> tuple[float, float, float]:
    """GL 坐标 → 编辑器坐标。

    GL (right, up, backward) → Editor (right, forward, up)
    """
    return (gl_x, -gl_z, gl_y)


def editor_to_gl_position(editor_x: float, editor_y: float, editor_z: float) -> tuple[float, float, float]:
    """编辑器坐标 → GL 坐标。

    Editor (right, forward, up) → GL (right, up, backward)
    """
    return (editor_x, editor_z, -editor_y)


# ═══════════════════════════════════════════════════════════════
# Scale 转换 (Y ↔ Z 轴交换, 无符号翻转 — scale 是大小量)
# ═══════════════════════════════════════════════════════════════

def gl_to_editor_scale(gl_sx: float, gl_sy: float, gl_sz: float) -> tuple[float, float, float]:
    """GL 轴缩放 → 编辑器轴缩放: Y ↔ Z 交换。"""
    return (gl_sx, gl_sz, gl_sy)


def editor_to_gl_scale(editor_sx: float, editor_sy: float, editor_sz: float) -> tuple[float, float, float]:
    """编辑器轴缩放 → GL 轴缩放: Y ↔ Z 交换。"""
    return (editor_sx, editor_sz, editor_sy)


# ═══════════════════════════════════════════════════════════════
# Vec3 批量转换
# ═══════════════════════════════════════════════════════════════

def gl_to_editor_vec3(gl_vec: tuple[float, float, float]) -> tuple[float, float, float]:
    """GL vec3 → 编辑器 vec3 (position)。"""
    return gl_to_editor_position(gl_vec[0], gl_vec[1], gl_vec[2])


def editor_to_gl_vec3(editor_vec: tuple[float, float, float]) -> tuple[float, float, float]:
    """编辑器 vec3 → GL vec3 (position)。"""
    return editor_to_gl_position(editor_vec[0], editor_vec[1], editor_vec[2])


def gl_to_editor_scale_vec3(gl_vec: tuple[float, float, float]) -> tuple[float, float, float]:
    """GL vec3 → 编辑器 vec3 (scale)。"""
    return gl_to_editor_scale(gl_vec[0], gl_vec[1], gl_vec[2])


def editor_to_gl_scale_vec3(editor_vec: tuple[float, float, float]) -> tuple[float, float, float]:
    """编辑器 vec3 → GL vec3 (scale)。"""
    return editor_to_gl_scale(editor_vec[0], editor_vec[1], editor_vec[2])
