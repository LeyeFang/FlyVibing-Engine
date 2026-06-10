"""
Editor Grid — 摄像机跟随参考网格 (圆形淡化边缘)。

设计原则:
  - **不 import 任何图形 API** (OpenGL / ModernGL / Vulkan 等)
  - 仅生成纯 numpy 顶点/索引数据和着色器源码字符串
  - 网格中心跟随 EditorCamera 的注视点 (orbit_target)
  - 网格半径 = 摄像机到注视点的距离 (orbit_distance), 记为 r
  - 0.8r ~ 1r 范围边缘逐渐虚化到透明

坐标约定:
  - 编辑器 X 轴 = GL X 轴 (+X 方向)
  - 编辑器 Y 轴 = GL -Z 轴 (-Z 方向)
  - 网格在注视点所在水平面上 (Y = orbit_target.y)

绘制分层:
  1. grid_lines  : 白色网格线, 深度测试开启, 线宽 1, 边缘淡化
  2. grid_x_axis : 红色 X 正半轴, 深度测试关闭, 线宽 3
  3. grid_y_axis : 绿色 Y 正半轴, 深度测试关闭, 线宽 3
"""

from __future__ import annotations
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from Application.Core.Renderer.Renderer import RenderResourceManger

# ════════════════════════════════════════════════════════════════
# 内联着色器 (无外部依赖)
# ════════════════════════════════════════════════════════════════

# ── 网格线顶点着色器: 顶点固定在世界空间 ──
_GRID_VS: str = """#version 330 core
layout (location = 0) in vec3 aPos;
uniform mat4 uView;
uniform mat4 uProj;
out vec3 vWorldPos;
void main() {
    vWorldPos = aPos;
    gl_Position = uProj * uView * vec4(aPos, 1.0);
}
"""

# ── 网格线片段着色器: 以注视点为中心的圆形淡化边缘 ──
_GRID_FS: str = """#version 330 core
in vec3 vWorldPos;
out vec4 FragColor;
uniform vec4 uColor;
uniform vec3 uFadeCenter;     // 摄像机注视点, 淡化圆心
uniform float uFadeRadius;    // 摄像机距离, 淡化半径
void main() {
    float dist = length(vWorldPos.xz - uFadeCenter.xz);
    float fade_start = uFadeRadius * 0.8;
    float alpha = 1.0 - smoothstep(fade_start, uFadeRadius, dist);
    FragColor = vec4(uColor.rgb, uColor.a * alpha);
}
"""

# ── 轴顶点着色器: 固定世界原点, 传递世界坐标给 FS ──
_AXIS_VS: str = """#version 330 core
layout (location = 0) in vec3 aPos;
uniform mat4 uView;
uniform mat4 uProj;
out vec3 vWorldPos;
void main() {
    vWorldPos = aPos;
    gl_Position = uProj * uView * vec4(aPos, 1.0);
}
"""

# ── 轴片段着色器: 圆形淡化边缘 (同网格线) ──
_AXIS_FS: str = """#version 330 core
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


class Grid:
    """摄像机跟随参考网格 — 仅数据，不知渲染。

    网格中心 = EditorCamera.orbit_target
    网格半径 = EditorCamera.orbit_distance
    边缘 0.8r ~ 1r 圆形淡化到透明
    """

    # ── 网格参数 ──
    GRID_HALF_EXTENT: int = 100      # 网格覆盖 ±100 单位
    GRID_SPACING: int = 1            # 网格线间距 1 单位
    GRID_COLOR: tuple = (0.45, 0.45, 0.45, 1.0)   # 白色偏灰
    X_AXIS_COLOR: tuple = (1.0, 0.0, 0.0, 1.0)    # 红色
    Y_AXIS_COLOR: tuple = (0.0, 1.0, 0.0, 1.0)    # 绿色
    AXIS_LINE_WIDTH: float = 1.0    # OpenGL 3.3 core 仅支持线宽 1.0
    GRID_LINE_WIDTH: float = 1.0

    # overlay key 常量
    KEY_GRID_LINES: str = "editor_grid_lines"
    KEY_X_AXIS: str = "editor_grid_x_axis"
    KEY_Y_AXIS: str = "editor_grid_y_axis"

    # ════════════════════════════════════════════════════════════
    # 网格顶点生成
    # ════════════════════════════════════════════════════════════

    @staticmethod
    def _build_grid_line_vertices(
        half_extent: int,
        spacing: int,
    ) -> tuple[np.ndarray, np.ndarray]:
        """生成网格线的顶点和索引。

        网格线在 XZ 平面 (Y=0) 上, 覆盖 [-half_extent, +half_extent]。
        网格固定世界原点, 淡化圆心由 uFadeCenter 控制。

        Returns:
            (vertices, indices): vertices (N,3) float32, indices (M,) uint32
        """
        n = half_extent
        verts = []
        idx = []
        vi = 0

        # ── 平行于 X 轴的线 (z 固定) ──
        for z in range(-n, n + 1, spacing):
            verts.append([-float(n), 0.0, float(z)])
            verts.append([ float(n), 0.0, float(z)])
            idx.extend([vi, vi + 1])
            vi += 2

        # ── 平行于 Z 轴的线 (x 固定) ──
        for x in range(-n, n + 1, spacing):
            verts.append([float(x), 0.0, -float(n)])
            verts.append([float(x), 0.0,  float(n)])
            idx.extend([vi, vi + 1])
            vi += 2

        return (
            np.array(verts, dtype=np.float32),
            np.array(idx, dtype=np.uint32),
        )

    @staticmethod
    def _build_axis_vertices(
        half_extent: int,
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

    # ════════════════════════════════════════════════════════════
    # 公共 API
    # ════════════════════════════════════════════════════════════

    @classmethod
    def register_to(
        cls,
        renderer: 'RenderResourceManger',
    ) -> None:
        """向渲染器注册网格的所有可绘制对象。

        Args:
            renderer: 渲染器实例 (需实现 RenderResourceManger 接口)
        """
        from Application.Core.Renderer.Renderer import RenderResourceManger

        # ── 1. 网格线 ──
        grid_v, grid_i = cls._build_grid_line_vertices(
            cls.GRID_HALF_EXTENT, cls.GRID_SPACING,
        )
        renderer.register_overlay_drawable(
            RenderResourceManger.overlay_drawable_struct(
                key=cls.KEY_GRID_LINES,
                vertices=grid_v,
                indices=grid_i,
                vs_src=_GRID_VS,
                fs_src=_GRID_FS,
                uniforms_setup=Grid._grid_uniform_setup,
                draw_mode='lines',
                depth_test=True,
                line_width=cls.GRID_LINE_WIDTH,
                blend=True,  # 圆形淡化边缘需要 alpha 混合
            )
        )

        # ── 2. X 轴 (红色, GL +X 方向) ──
        axis_v, axis_i = cls._build_axis_vertices(
            cls.GRID_HALF_EXTENT,
        )
        renderer.register_overlay_drawable(
            RenderResourceManger.overlay_drawable_struct(
                key=cls.KEY_X_AXIS,
                vertices=axis_v,
                indices=np.array([0, 1], dtype=np.uint32),
                vs_src=_AXIS_VS,
                fs_src=_AXIS_FS,
                uniforms_setup=Grid._x_axis_uniform_setup,
                draw_mode='lines',
                depth_test=False,
                line_width=cls.AXIS_LINE_WIDTH,
                blend=True,  # 淡化边缘需要 alpha 混合
            )
        )

        # ── 3. Y 轴 (绿色, GL -Z 方向) ──
        renderer.register_overlay_drawable(
            RenderResourceManger.overlay_drawable_struct(
                key=cls.KEY_Y_AXIS,
                vertices=axis_v,
                indices=np.array([2, 3], dtype=np.uint32),
                vs_src=_AXIS_VS,
                fs_src=_AXIS_FS,
                uniforms_setup=Grid._y_axis_uniform_setup,
                draw_mode='lines',
                depth_test=False,
                line_width=cls.AXIS_LINE_WIDTH,
                blend=True,
            )
        )

    @classmethod
    def unregister_from(
        cls,
        renderer: 'RenderResourceManger',
    ) -> None:
        """从渲染器取消注册网格的所有可绘制对象。"""
        for key in (
            cls.KEY_GRID_LINES, cls.KEY_X_AXIS, cls.KEY_Y_AXIS
        ):
            renderer.unregister_overlay_drawable(key)

    # ════════════════════════════════════════════════════════════
    # Uniform 设置回调
    # ════════════════════════════════════════════════════════════
    #
    # 这些回调在渲染线程的 _draw_registered_overlays() 中调用。
    # Grid 类不在模块级别 import OpenGL 或 EditorCamera,
    # 只在回调闭包内部 lazy-import, 保持 Grid 本身不依赖图形 API。

    @staticmethod
    def _get_grid_params() -> tuple:
        """从 EditorCamera 获取当前注视点和距离。

        Returns:
            (center_x, center_y, center_z, distance)
        """
        from Application.Editor.EditorCamera import EditorCamera
        cam = EditorCamera.get_instance()
        cx, cy, cz = cam.orbit_target
        return float(cx), float(cy), float(cz), float(cam.orbit_distance)

    @staticmethod
    def _grid_uniform_setup(program: int) -> None:
        """设置网格线 uniform: uColor + uFadeCenter + uFadeRadius。

        网格线固定在世界空间 (不跟随注视点),
        淡化圆心 = 摄像机注视点, 淡化半径 = 摄像机距离。
        """
        from OpenGL import GL as gl
        cx, cy, cz, r = Grid._get_grid_params()

        loc = gl.glGetUniformLocation(program, 'uColor')
        if loc >= 0:
            gl.glUniform4f(loc, *Grid.GRID_COLOR)

        loc = gl.glGetUniformLocation(program, 'uFadeCenter')
        if loc >= 0:
            gl.glUniform3f(loc, cx, cy, cz)

        loc = gl.glGetUniformLocation(program, 'uFadeRadius')
        if loc >= 0:
            gl.glUniform1f(loc, r)

    @staticmethod
    def _x_axis_uniform_setup(program: int) -> None:
        """设置 X 轴 uniform: uColor + uFadeCenter + uFadeRadius。

        轴固定世界原点, 淡化跟随注视点 (同网格线)。
        """
        from OpenGL import GL as gl
        cx, cy, cz, r = Grid._get_grid_params()

        loc = gl.glGetUniformLocation(program, 'uColor')
        if loc >= 0:
            gl.glUniform4f(loc, *Grid.X_AXIS_COLOR)

        loc = gl.glGetUniformLocation(program, 'uFadeCenter')
        if loc >= 0:
            gl.glUniform3f(loc, cx, cy, cz)

        loc = gl.glGetUniformLocation(program, 'uFadeRadius')
        if loc >= 0:
            gl.glUniform1f(loc, r)

    @staticmethod
    def _y_axis_uniform_setup(program: int) -> None:
        """设置 Y 轴 uniform: uColor + uFadeCenter + uFadeRadius。

        轴固定世界原点, 淡化跟随注视点 (同网格线)。
        """
        from OpenGL import GL as gl
        cx, cy, cz, r = Grid._get_grid_params()

        loc = gl.glGetUniformLocation(program, 'uColor')
        if loc >= 0:
            gl.glUniform4f(loc, *Grid.Y_AXIS_COLOR)

        loc = gl.glGetUniformLocation(program, 'uFadeCenter')
        if loc >= 0:
            gl.glUniform3f(loc, cx, cy, cz)

        loc = gl.glGetUniformLocation(program, 'uFadeRadius')
        if loc >= 0:
            gl.glUniform1f(loc, r)