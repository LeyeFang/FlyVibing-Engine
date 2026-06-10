"""
Editor Grid — X-Y 平面参考网格。

设计原则:
  - **不 import 任何图形 API** (OpenGL / ModernGL / Vulkan 等)
  - 仅生成纯 numpy 顶点/索引数据和着色器源码字符串
  - 通过 Application 获取 renderer 实例，调用其
    register_overlay_drawable() 注册渲染资源
  - 渲染器不知道 Grid 的存在，只看到带 key 的可绘制对象

坐标约定:
  - 编辑器 X 轴 = GL X 轴 (+X 方向)
  - 编辑器 Y 轴 = GL -Z 轴 (-Z 方向)
  - 网格在 GL 的 XZ 平面 (Y=0) 上绘制

绘制分层 (确保轴在网格线之上):
  1. grid_lines  : 白色网格线, 深度测试开启, 线宽 1
  2. grid_x_axis : 红色 X 正半轴,  深度测试关闭, 线宽 3
  3. grid_y_axis : 绿色 Y 正半轴,  深度测试关闭, 线宽 3
"""

from __future__ import annotations
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from Application.Core.Renderer.Renderer import RenderResourceManger

# ════════════════════════════════════════════════════════════════
# 内联着色器 (无外部依赖)
# ════════════════════════════════════════════════════════════════

_VERTEX_SHADER: str = """#version 330 core
layout (location = 0) in vec3 aPos;
uniform mat4 uView;
uniform mat4 uProj;
void main() {
    gl_Position = uProj * uView * vec4(aPos, 1.0);
}
"""

_FRAGMENT_SHADER: str = """#version 330 core
out vec4 FragColor;
uniform vec4 uColor;
void main() {
    FragColor = uColor;
}
"""


class Grid:
    """X-Y 平面参考网格 — 仅数据，不知渲染。

    用法:
        Grid.register_to(renderer)   # 在 EditorLayer.OnAttach() 中调用
        Grid.unregister_from(renderer)
    """

    # ── 网格参数 ──
    GRID_HALF_EXTENT: int = 10       # 网格从 -10 到 +10
    GRID_COLOR: tuple = (0.45, 0.45, 0.45, 1.0)   # 白色偏灰
    X_AXIS_COLOR: tuple = (1.0, 0.0, 0.0, 1.0)    # 红色
    Y_AXIS_COLOR: tuple = (0.0, 1.0, 0.0, 1.0)    # 绿色
    AXIS_LINE_WIDTH: float = 3.0
    GRID_LINE_WIDTH: float = 1.0

    # overlay key 常量
    KEY_GRID_LINES: str = "editor_grid_lines"
    KEY_X_AXIS: str = "editor_grid_x_axis"
    KEY_Y_AXIS: str = "editor_grid_y_axis"

    # ════════════════════════════════════════════════════════════
    # 网格顶点生成
    # ════════════════════════════════════════════════════════════

    @staticmethod
    def _build_grid_line_vertices(half_extent: int) -> tuple[np.ndarray, np.ndarray]:
        """生成网格线的顶点和索引。

        网格线在 GL 的 XZ 平面 (Y=0) 上:
          - 平行于 X 轴的线: z 固定, x 从 -half_extent 到 +half_extent
          - 平行于 Z 轴的线: x 固定, z 从 -half_extent 到 +half_extent

        Returns:
            (vertices, indices): vertices 为 (N, 3) float32, indices 为 (M,) uint32
        """
        n = half_extent
        verts = []
        idx = []
        vi = 0  # vertex index

        # ── 平行于 X 轴的线 (z 固定) ──
        for z in range(-n, n + 1):
            # 每根线 2 个顶点: (-n, 0, z) → (+n, 0, z)
            verts.append([-float(n), 0.0, float(z)])
            verts.append([ float(n), 0.0, float(z)])
            idx.extend([vi, vi + 1])
            vi += 2

        # ── 平行于 Z 轴的线 (x 固定) ──
        for x in range(-n, n + 1):
            verts.append([float(x), 0.0, -float(n)])
            verts.append([float(x), 0.0,  float(n)])
            idx.extend([vi, vi + 1])
            vi += 2

        return (
            np.array(verts, dtype=np.float32),
            np.array(idx, dtype=np.uint32),
        )

    @staticmethod
    def _build_axis_vertices(half_extent: int) -> tuple[np.ndarray, np.ndarray]:
        """生成 X 轴和 Y 轴的顶点和索引。

        X 轴正半轴: (0,0,0) → (+half_extent, 0, 0)  — GL +X 方向
        Y 轴正半轴: (0,0,0) → (0, 0, -half_extent)   — GL -Z 方向

        Returns:
            (vertices, indices): vertices 为 (4, 3) float32, indices 为 (4,) uint32
        """
        n = float(half_extent)
        # 顶点: X轴起点, X轴终点, Y轴起点, Y轴终点
        verts = np.array([
            [0.0, 0.0,  0.0],   # 0: 原点 (X 轴起点)
            [  n, 0.0,  0.0],   # 1: X 轴正半轴终点
            [0.0, 0.0,  0.0],   # 2: 原点 (Y 轴起点)
            [0.0, 0.0,  -n],    # 3: Y 轴正半轴终点 (GL -Z)
        ], dtype=np.float32)
        # 索引: X轴线段, Y轴线段
        indices = np.array([0, 1, 2, 3], dtype=np.uint32)
        return verts, indices

    # ════════════════════════════════════════════════════════════
    # 公共 API
    # ════════════════════════════════════════════════════════════

    @classmethod
    def register_to(cls, renderer: 'RenderResourceManger') -> None:
        """向渲染器注册网格的所有可绘制对象。

        调用时机: EditorLayer.OnAttach() (渲染线程, GL 上下文有效)

        Args:
            renderer: 渲染器实例 (需实现 RenderResourceManger 接口)
        """
        from Application.Core.Renderer.Renderer import RenderResourceManger

        # ── 1. 网格线 ──
        grid_v, grid_i = cls._build_grid_line_vertices(cls.GRID_HALF_EXTENT)
        renderer.register_overlay_drawable(
            RenderResourceManger.overlay_drawable_struct(
                key=cls.KEY_GRID_LINES,
                vertices=grid_v,
                indices=grid_i,
                vs_src=_VERTEX_SHADER,
                fs_src=_FRAGMENT_SHADER,
                uniforms_setup=Grid._grid_uniform_setup,
                draw_mode='lines',
                depth_test=True,
                line_width=cls.GRID_LINE_WIDTH,
            )
        )

        # ── 2. X 轴 (红色正半轴) ──
        axis_v, axis_i = cls._build_axis_vertices(cls.GRID_HALF_EXTENT)
        # X 轴: 使用顶点 0,1
        renderer.register_overlay_drawable(
            RenderResourceManger.overlay_drawable_struct(
                key=cls.KEY_X_AXIS,
                vertices=axis_v,
                indices=np.array([0, 1], dtype=np.uint32),
                vs_src=_VERTEX_SHADER,
                fs_src=_FRAGMENT_SHADER,
                uniforms_setup=Grid._x_axis_uniform_setup,
                draw_mode='lines',
                depth_test=False,        # 总是绘制在网格线之上
                line_width=cls.AXIS_LINE_WIDTH,
            )
        )

        # ── 3. Y 轴 (绿色正半轴, GL -Z) ──
        renderer.register_overlay_drawable(
            RenderResourceManger.overlay_drawable_struct(
                key=cls.KEY_Y_AXIS,
                vertices=axis_v,
                indices=np.array([2, 3], dtype=np.uint32),
                vs_src=_VERTEX_SHADER,
                fs_src=_FRAGMENT_SHADER,
                uniforms_setup=Grid._y_axis_uniform_setup,
                draw_mode='lines',
                depth_test=False,
                line_width=cls.AXIS_LINE_WIDTH,
            )
        )

    @classmethod
    def unregister_from(cls, renderer: 'RenderResourceManger') -> None:
        """从渲染器取消注册网格的所有可绘制对象。"""
        for key in (cls.KEY_GRID_LINES, cls.KEY_X_AXIS, cls.KEY_Y_AXIS):
            renderer.unregister_overlay_drawable(key)

    # ════════════════════════════════════════════════════════════
    # Uniform 设置回调 — 通过 glGetUniformLocation + glUniform4fv
    # ════════════════════════════════════════════════════════════
    #
    # 这些回调在渲染线程的 _draw_registered_overlays() 中被调用，
    # 此时 GL 上下文有效，但我们用 ctypes 直接操作 GL 函数指针，
    # 避免 import OpenGL.GL。
    #
    # 实际上: 由于渲染器的 _draw_registered_overlays 已经 import 了
    # OpenGL.GL，这些回调可以通过渲染器的 set_uniform 辅助方法来设置。
    # 这里我们使用更简洁的方式: 直接在这里 import OpenGL.GL，
    # 因为这个回调只在渲染线程执行，且调用者已经持有 GL 上下文。
    #
    # 注: Grid 类不 import OpenGL 到模块级别，只在回调闭包内部 import，
    # 这样 Grid 本身仍然不依赖图形 API 即可被 import 和实例化。

    @staticmethod
    def _grid_uniform_setup(program: int) -> None:
        """设置白色网格线 uniform。"""
        from OpenGL import GL as gl
        loc = gl.glGetUniformLocation(program, 'uColor')
        if loc >= 0:
            gl.glUniform4f(loc, *Grid.GRID_COLOR)

    @staticmethod
    def _x_axis_uniform_setup(program: int) -> None:
        """设置红色 X 轴 uniform。"""
        from OpenGL import GL as gl
        loc = gl.glGetUniformLocation(program, 'uColor')
        if loc >= 0:
            gl.glUniform4f(loc, *Grid.X_AXIS_COLOR)

    @staticmethod
    def _y_axis_uniform_setup(program: int) -> None:
        """设置绿色 Y 轴 uniform。"""
        from OpenGL import GL as gl
        loc = gl.glGetUniformLocation(program, 'uColor')
        if loc >= 0:
            gl.glUniform4f(loc, *Grid.Y_AXIS_COLOR)