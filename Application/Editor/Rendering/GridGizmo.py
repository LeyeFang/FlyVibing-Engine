"""
GridGizmo — 编辑器 X-Y 平面参考网格。

坐标映射:
  - 用户 X 轴 → GL +X 轴 → 红色粗线
  - 用户 Y 轴 → GL -Z 轴 → 绿色粗线

网格位于 GL 坐标系的 X-Z 平面 (Y=0):
  - 单位刻度: 1
  - 范围: ±50
  - 细灰线: 每 1 单位
  - 主轴: 窄矩形 (三角形) 模拟粗线效果

使用方式:
  # 初始化 (渲染器 Create 时调用一次)
  GridGizmo.init(ModernGLCore.ctx)

  # 每帧绘制 (场景实体之后, ImGui 之前)
  GridGizmo.render(view_matrix, proj_matrix)
"""

from __future__ import annotations
import numpy as np
import moderngl as mgl


class GridGizmo:
    """编辑器 X-Y 平面参考网格。

    所有方法为 @classmethod — 全局单例网格。
    """

    # ════════════════════════════════════════════════════════════
    # 着色器源码 (内联, 不依赖 ResourceManager)
    # ════════════════════════════════════════════════════════════

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

    # ════════════════════════════════════════════════════════════
    # 常量
    # ════════════════════════════════════════════════════════════

    GRID_EXTENT: int = 50          # 网格范围 ±50 单位
    AXIS_HALF_WIDTH: float = 0.03  # 主轴半宽 (三角形矩形)
    Y_OFFSET: float = 0.001        # 微抬避免与 Y=0 物体 z-fighting

    # 颜色
    COLOR_GRID: tuple = (0.30, 0.30, 0.30, 1.0)   # 网格线 — 深灰
    COLOR_X_AXIS: tuple = (0.85, 0.15, 0.15, 1.0) # X 轴 (用户 X) — 红色
    COLOR_Y_AXIS: tuple = (0.15, 0.80, 0.15, 1.0) # Y 轴 (用户 Y) — 绿色

    # ════════════════════════════════════════════════════════════
    # 内部状态
    # ════════════════════════════════════════════════════════════

    _program: mgl.Program | None = None
    _grid_vao: mgl.VertexArray | None = None     # 细网格线
    _axis_vao: mgl.VertexArray | None = None     # 主轴 (矩形)
    _grid_vertex_count: int = 0                   # 网格线顶点数
    _initialized: bool = False

    # ════════════════════════════════════════════════════════════
    # 初始化
    # ════════════════════════════════════════════════════════════

    @classmethod
    def init(
        cls,
        ctx: mgl.Context
    ) -> None:
        """初始化 GPU 资源 — 编译着色器 + 上传网格/主轴几何体。

        调用时机: 渲染器 Create() 之后, GL Context 已就绪。
        """
        if cls._initialized:
            return

        # ── 编译着色器 ──
        cls._program = ctx.program(
            vertex_shader=cls._VERTEX_SHADER,
            fragment_shader=cls._FRAGMENT_SHADER,
        )

        # ── 网格线 VBO → VAO ──
        grid_verts = cls._build_grid_vertices()
        grid_vbo = ctx.buffer(grid_verts.tobytes())
        cls._grid_vao = ctx.vertex_array(
            cls._program,
            [(grid_vbo, '3f', 'aPos')],
        )
        cls._grid_vertex_count = len(grid_verts) // 3

        # ── 主轴 VBO → VAO ──
        axis_verts = cls._build_axis_vertices()
        axis_vbo = ctx.buffer(axis_verts.tobytes())
        cls._axis_vao = ctx.vertex_array(
            cls._program,
            [(axis_vbo, '3f', 'aPos')],
        )

        cls._initialized = True
        print(
            f"[GridGizmo] Initialized — "
            f"grid lines ±{cls.GRID_EXTENT}, "
            f"axis width={cls.AXIS_HALF_WIDTH * 2:.3f}"
        )

    # ════════════════════════════════════════════════════════════
    # 几何体生成
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _build_grid_vertices(cls) -> np.ndarray:
        """生成网格线顶点 (GL_LINES 图元)。

        在 GL 的 X-Z 平面 (Y=0) 上:
          - 平行于 X 轴: 从 (-e, 0, z) 到 (+e, 0, z)
          - 平行于 Z 轴: 从 (x, 0, -e) 到 (x, 0, +e)

        Returns:
            float32 ndarray, shape (N, 3)
        """
        e = cls.GRID_EXTENT
        yo = cls.Y_OFFSET
        lines: list[tuple[float, float, float]] = []

        for i in range(-e, e + 1):
            # 平行于 X 轴 (固定 z=i)
            lines.append((-e, yo, float(i)))
            lines.append((+e, yo, float(i)))
            # 平行于 Z 轴 (固定 x=i)
            lines.append((float(i), yo, -e))
            lines.append((float(i), yo, +e))

        return np.array(lines, dtype='f4')

    @classmethod
    def _build_axis_vertices(cls) -> np.ndarray:
        """生成主轴窄矩形顶点 (GL_TRIANGLES 图元)。

        用两个三角形组成的窄矩形模拟粗线:
          - X 轴矩形: 沿 X 方向, 宽 2*AXIS_HALF_WIDTH, 位于 Z=0
          - Z 轴矩形: 沿 Z 方向, 宽 2*AXIS_HALF_WIDTH, 位于 X=0

        顶点布局: [X轴矩形 6顶点] + [Z轴矩形 6顶点]

        Returns:
            float32 ndarray, shape (12, 3)
        """
        e = float(cls.GRID_EXTENT)
        hw = cls.AXIS_HALF_WIDTH
        yo = cls.Y_OFFSET

        # ── X 轴矩形 (Z=0, 沿 X 延伸) ──
        #   (-e, yo, -hw) ──── (+e, yo, -hw)
        #        │  ╲                 │
        #   (-e, yo, +hw) ──── (+e, yo, +hw)
        x_axis = np.array([
            [-e, yo, -hw], [+e, yo, -hw], [+e, yo, +hw],   # 三角形 1
            [-e, yo, -hw], [+e, yo, +hw], [-e, yo, +hw],   # 三角形 2
        ], dtype='f4')

        # ── Z 轴矩形 (X=0, 沿 Z 延伸) — 用户 Y 轴 ──
        #   (-hw, yo, -e) ──── (+hw, yo, -e)
        #        │  ╲                 │
        #   (-hw, yo, +e) ──── (+hw, yo, +e)
        z_axis = np.array([
            [-hw, yo, -e], [+hw, yo, -e], [+hw, yo, +e],   # 三角形 1
            [-hw, yo, -e], [+hw, yo, +e], [-hw, yo, +e],   # 三角形 2
        ], dtype='f4')

        return np.vstack([x_axis, z_axis])

    # ════════════════════════════════════════════════════════════
    # 渲染
    # ════════════════════════════════════════════════════════════

    @classmethod
    def render(cls, view: np.ndarray, proj: np.ndarray) -> None:
        """绘制网格和主轴。

        调用时机: StartFrame() 场景实体绘制完毕后。

        Args:
            view: 4x4 视图矩阵 (pyrr, 列主序, float32)
            proj: 4x4 投影矩阵 (pyrr, 列主序, float32)
        """
        if not cls._initialized:
            return

        # 分开传入 view/proj, 与场景实体 shader 保持一致,
        # 避免 NumPy 中 pyrr 列主序矩阵相乘后布局错乱
        cls._program['uView'].write(
            np.ascontiguousarray(view.astype('f4')).tobytes()
        )
        cls._program['uProj'].write(
            np.ascontiguousarray(proj.astype('f4')).tobytes()
        )

        # ── 1. 绘制灰色网格线 ──
        cls._program['uColor'] = cls.COLOR_GRID
        cls._grid_vao.render(mgl.LINES)

        # ── 2. 绘制 X 轴 (红色) ──
        cls._program['uColor'] = cls.COLOR_X_AXIS
        cls._axis_vao.render(mgl.TRIANGLES, vertices=6)

        # ── 3. 绘制 Z 轴 (绿色, 用户 Y) ──
        cls._program['uColor'] = cls.COLOR_Y_AXIS
        cls._axis_vao.render(mgl.TRIANGLES, vertices=6, first=6)

    # ════════════════════════════════════════════════════════════
    # 清理
    # ════════════════════════════════════════════════════════════

    @classmethod
    def destroy(cls) -> None:
        """释放 GPU 资源。"""
        if cls._grid_vao is not None:
            cls._grid_vao.release()
        if cls._axis_vao is not None:
            cls._axis_vao.release()
        if cls._program is not None:
            cls._program.release()
        cls._initialized = False
        cls._grid_vao = None
        cls._axis_vao = None
        cls._program = None
