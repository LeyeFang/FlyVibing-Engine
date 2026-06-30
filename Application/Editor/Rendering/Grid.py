"""
Editor Grid — 摄像机跟随参考网格 (圆形淡化边缘)。

设计原则:
  - 网格资源 (参数/着色器/顶点/回调) 独立于 Grid 类, 置于模块顶部
  - 网格中心跟随 EditorCamera 的注视点 (orbit_target)
  - 网格半径 = 摄像机到注视点的距离 (orbit_distance), 记为 r
  - 0.8r ~ 1r 范围边缘逐渐虚化到透明
  - ★ 零图形后端依赖 — 不 import OpenGL / ZenGL / Vulkan

坐标约定:
  - 编辑器 X 轴 = GL  X 轴  (+X 方向)
  - 编辑器 Y 轴 = GL -Z 轴  (-Z 方向, 即 GL 的 Z 负半轴 → 编辑器 Y 正半轴)
  - 编辑器 Z 轴 = GL  Y 轴  (+Y 方向, 即 GL 的 Y 正半轴 → 编辑器 Z 正半轴)
  - 网格在注视点所在水平面上 (GL Y = orbit_target.y, 对应编辑器 Z = orbit_target.y)

绘制分层:
  1. grid_lines  : 白色网格线, 深度测试开启, 线宽 1, 边缘淡化
  2. grid_x_axis : 红色 X 正半轴, 深度测试关闭, 线宽 3
  3. grid_y_axis : 绿色 Y 正半轴, 深度测试关闭, 线宽 3
"""

from __future__ import annotations

import numpy as np

from Application.Core.Renderer.Renderer import RenderResourceManger

# ════════════════════════════════════════════════════════════════
# 网格资源: 参数常量
# ════════════════════════════════════════════════════════════════

GRID_HALF_EXTENT: int = 100
GRID_SPACING: int = 1

GRID_COLOR: tuple = (0.45, 0.45, 0.45, 1.0)   # 白色偏灰
X_AXIS_COLOR: tuple = (1.0, 0.0, 0.0, 1.0)    # 红色
Y_AXIS_COLOR: tuple = (0.0, 1.0, 0.0, 1.0)    # 绿色

GRID_LINE_WIDTH: float = 1.0
AXIS_LINE_WIDTH: float = 1.0

KEY_GRID_LINES: str = "editor_grid_lines"
KEY_X_AXIS: str = "editor_grid_x_axis"
KEY_Y_AXIS: str = "editor_grid_y_axis"

# ════════════════════════════════════════════════════════════════
# 网格资源: 着色器
# ════════════════════════════════════════════════════════════════

_OVERLAY_VS: str = """#version 440 core
layout (location = 0) in vec3 aPos;
uniform mat4 uView;
uniform mat4 uProj;
out vec3 vWorldPos;
void main() {
    vWorldPos = aPos;
    gl_Position = uProj * uView * vec4(aPos, 1.0);
}
"""

_OVERLAY_FADE_FS: str = """#version 440 core
in vec3 vWorldPos;
out vec4 FragColor;
uniform vec4 uColor;
uniform vec3 uFadeCenter;
uniform float uFadeRadius;
void main() {
    float dist = length(vWorldPos.xz - uFadeCenter.xz);
    float fade_start = uFadeRadius * 0.8;
    float alpha = 1.0 - smoothstep(fade_start, uFadeRadius, dist);
    FragColor = vec4(uColor.rgb, uColor.a * alpha);
}
"""

# ════════════════════════════════════════════════════════════════
# 网格资源: 顶点 / 索引生成
# ════════════════════════════════════════════════════════════════

def _build_grid_line_vertices(
    half_extent: int = GRID_HALF_EXTENT,
    spacing: int = GRID_SPACING,
) -> tuple[np.ndarray, np.ndarray]:
    """生成网格线的顶点和索引。

    网格线在 XZ 平面 (Y=0) 上, 覆盖 [-half_extent, +half_extent]。
    网格固定世界原点, 淡化圆心由 uFadeCenter 控制。
    """
    n = half_extent
    verts = []
    idx = []
    vi = 0

    for z in range(-n, n + 1, spacing):
        verts.append([-float(n), 0.0, float(z)])
        verts.append([ float(n), 0.0, float(z)])
        idx.extend([vi, vi + 1])
        vi += 2

    for x in range(-n, n + 1, spacing):
        verts.append([float(x), 0.0, -float(n)])
        verts.append([float(x), 0.0,  float(n)])
        idx.extend([vi, vi + 1])
        vi += 2

    return (
        np.array(verts, dtype=np.float32),
        np.array(idx, dtype=np.uint32),
    )


def _build_axis_vertices(
    half_extent: int = GRID_HALF_EXTENT,
) -> tuple[np.ndarray, np.ndarray]:
    """生成 X 轴和 Y 轴的顶点和索引 (双方向)。

    X 轴: (-half_extent, 0, 0) → (+half_extent, 0, 0)   — GL ±X 方向
    Y 轴: (0, 0, +half_extent) → (0, 0, -half_extent)   — GL ±Z 方向
    """
    n = float(half_extent)
    verts = np.array([
        [ -n, 0.0,  0.0],   # 0: X 轴负端
        [  n, 0.0,  0.0],   # 1: X 轴正端
        [0.0, 0.0,   n],    # 2: Y 轴正端 (GL +Z)
        [0.0, 0.0,  -n],    # 3: Y 轴负端 (GL -Z = 编辑器 Y+)
    ], dtype=np.float32)
    indices = np.array([0, 1, 2, 3], dtype=np.uint32)
    return verts, indices


# ════════════════════════════════════════════════════════════════
# 网格资源: Uniform 设置回调
# ════════════════════════════════════════════════════════════════

class Grid:
    """摄像机跟随参考网格 — 仅负责向渲染器注册可绘制对象。"""

    @classmethod
    def register_to(cls, renderer: RenderResourceManger) -> None:
        """向渲染器注册网格的所有可绘制对象。"""

        # ── 1. 白色网格线 ──
        # ★ 声明式 uniform: 静态值 (uColor) + 动态源 (uFadeCenter/uFadeRadius)
        #    渲染器负责解析动态源并上传到 GPU，Grid 不感知后端类型
        grid_v, grid_i = _build_grid_line_vertices()
        renderer.register_overlay_drawable(
            RenderResourceManger.overlay_drawable_struct(
                key=KEY_GRID_LINES,
                vertices=grid_v,
                indices=grid_i,
                vs_src=_OVERLAY_VS,
                fs_src=_OVERLAY_FADE_FS,
                uniforms={
                    'uColor':       np.array(GRID_COLOR, 'f4'),
                    'uFadeCenter':  'camera.fade_center',
                    'uFadeRadius':  'camera.fade_radius',
                },
                draw_mode='lines',
                depth_test=True,
                line_width=GRID_LINE_WIDTH,
                blend=True,
                pick_type=0
            )
        )

        # ── 2. X 轴 (红色) ──
        axis_v, axis_i = _build_axis_vertices()
        renderer.register_overlay_drawable(
            RenderResourceManger.overlay_drawable_struct(
                key=KEY_X_AXIS,
                vertices=axis_v,
                indices=np.array([0, 1], dtype=np.uint32),
                vs_src=_OVERLAY_VS,
                fs_src=_OVERLAY_FADE_FS,
                uniforms={
                    'uColor':       np.array(X_AXIS_COLOR, 'f4'),
                    'uFadeCenter':  'camera.fade_center',
                    'uFadeRadius':  'camera.fade_radius',
                },
                draw_mode='lines',
                depth_test=False,
                line_width=AXIS_LINE_WIDTH,
                blend=True,
                pick_type=0
            )
        )

        # ── 3. Y 轴 (绿色) ──
        renderer.register_overlay_drawable(
            RenderResourceManger.overlay_drawable_struct(
                key=KEY_Y_AXIS,
                vertices=axis_v,
                indices=np.array([2, 3], dtype=np.uint32),
                vs_src=_OVERLAY_VS,
                fs_src=_OVERLAY_FADE_FS,
                uniforms={
                    'uColor':       np.array(Y_AXIS_COLOR, 'f4'),
                    'uFadeCenter':  'camera.fade_center',
                    'uFadeRadius':  'camera.fade_radius',
                },
                draw_mode='lines',
                depth_test=False,
                line_width=AXIS_LINE_WIDTH,
                blend=True,
                pick_type=0
            )
        )

    @classmethod
    def unregister_from(cls, renderer: RenderResourceManger) -> None:
        """从渲染器取消注册网格的所有可绘制对象。"""
        for key in (KEY_GRID_LINES, KEY_X_AXIS, KEY_Y_AXIS):
            renderer.unregister_overlay_drawable(key)