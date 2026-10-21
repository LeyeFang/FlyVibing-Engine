"""
GL 像素探针 — 渲染器验证体系的最小实测环境（夹具, 非测试文件 — 供 test_*.py 复用）。

职责:
  - 隐藏 GLFW 窗口 (GL 4.4 core) + 真实 OpenGLRenderer + 内置资源 (ResourceManager)
  - 最小场景搭建: 实体 (mesh / material 颜色 / 纹理) + 正交相机
  - 像素断言原语: read_pixel / expect_color（顶左坐标系 ⇒ GL 底左自动换算）

使用约定:
  - 一个测试文件进程内用 **一个** GlProbe（SceneManager 状态按类名共享）;
  - 结束时 close()（释放 GL 资源 + 销毁窗口）;
  - 世界坐标→像素映射的"金标准"由 test_gl_pixels.py 用例锁定 —
    改相机/矩阵约定前先看那批用例与 rendering_protocol.md。

线程模型: 探针全程在调用线程 (测试主线程) 内持有 GL 上下文 — 与引擎
"GL 只许渲染线程" 的纪律一致（此线程即扮演渲染线程）。
"""

from __future__ import annotations

import numpy as np


class _FakeWindow:
    """OpenGLRenderer.Create 只需要 GetSize()。"""

    def __init__(self, size: tuple[int, int]) -> None:
        self._size = size

    def GetSize(self) -> tuple[int, int]:
        return self._size


class GlProbeEngine:
    """最小引擎替身（类对象 — 与 SceneManager/ResourceManager 的 engine 语义一致）。"""
    renderer = None
    scene = None


class GlProbe:
    """隐藏窗口 GL 探针。"""

    def __init__(self, width: int = 320, height: int = 240) -> None:
        import glfw

        from Application.Core.Events.Event import BindPackCallback
        from Application.Resource.ResourceManager import ResourceManager
        from Application.Core.Scene.SceneManager import SceneManager

        self.width = int(width)
        self.height = int(height)

        # ── 1. 资源/场景引导（与 test_pie_bare / ui_scene 同套路） ──
        BindPackCallback(lambda e: None)
        ResourceManager.Init(GlProbeEngine)
        SceneManager.Init(GlProbeEngine)
        GlProbeEngine.scene = SceneManager._state_for(GlProbeEngine.__name__)
        self.st = GlProbeEngine.scene

        # ── 2. 隐藏 GL 窗口（GL 4.4 core — 与 EditorWindow 同规格） ──
        if not glfw.init():
            raise RuntimeError("glfw.init() failed")
        glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 4)
        glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 4)
        glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
        glfw.window_hint(glfw.VISIBLE, glfw.FALSE)
        self._glfw = glfw
        self.window = glfw.create_window(self.width, self.height, "GL-PROBE", None, None)
        if not self.window:
            glfw.terminate()
            raise RuntimeError("glfw.create_window failed")
        glfw.make_context_current(self.window)
        glfw.swap_interval(0)

        # ── 3. 真实渲染器 ──
        from Application.Core.Renderer.OpenGL.OpenGLRenderer import OpenGLRenderer
        self.renderer = OpenGLRenderer.Create(
            window=_FakeWindow((self.width, self.height)), engine=GlProbeEngine)
        GlProbeEngine.renderer = self.renderer

        # 清屏色设为可区分的深色（背景断言用）
        self.set_clear_color(0.05, 0.05, 0.08, 1.0)

    # ════════════════════════════════════════════════════════════
    # 场景搭建
    # ════════════════════════════════════════════════════════════

    def make_entity(self, name: str = "probe", *, mesh: str = "Square",
                    color: tuple | None = None, texture_name: str | None = None,
                    position: tuple = (0.0, 0.0, 0.0),
                    scale: float | tuple = 1.0) -> int:
        """建实体（Transform + MeshRenderer + 默认材质）；color/texture 触发独享材质。

        position 为 **GL 坐标**（探针位于渲染层，不做编辑器坐标转换）。
        注册走引擎标准命令路径（EntityManager.add 自动入队 register 命令，
        下一次 render() 时执行）——不要手动重复注册。
        """
        from Application.Core.Scene.BasicComponents import MeshRenderer, Transform
        from Application.Resource.ResourceManager import ResourceManager

        mr = MeshRenderer()
        mr.mesh_id = ResourceManager.GetDefaultMesh(mesh)
        eid = self.st.AddEntity(name, Transform(), mr)

        st = self.st
        s3 = (scale, scale, scale) if isinstance(scale, (int, float)) else tuple(scale)
        st.SetEntityTransform(eid, position_xyz=tuple(position), scale_xyz=s3)

        if color is not None or texture_name is not None:
            from Application.Core.Scene.SceneManager import SceneManager
            SceneManager._ensure_unique_material(st, eid, mr)
            if color is not None:
                r, g, b = (list(color) + [1.0])[:3] if len(color) == 3 else color[:3]
                a = color[3] if len(color) > 3 else 1.0
                ResourceManager.SetMaterialColor(mr.material_id, float(r), float(g),
                                                 float(b), float(a))
            if texture_name is not None:
                mat = ResourceManager.GetMaterial(mr.material_id)
                tid = ResourceManager.GetDefaultTexture(texture_name)
                if mat.texture_id_list:
                    mat.texture_id_list[0] = tid
                else:
                    mat.texture_id_list = [tid]
                mat.mark_modified()
        return eid

    def unregister(self, eid: int) -> None:
        if eid in self.renderer.registered_entities:
            self.renderer.unregister_entity(eid)
        try:
            self.st.DeleteEntity(eid)
        except Exception:  # noqa: BLE001
            pass

    # ════════════════════════════════════════════════════════════
    # 相机 / 帧 / 像素
    # ════════════════════════════════════════════════════════════

    def set_topdown(self, half_h: float = 10.0, height: float = 10.0,
                    near: float = 0.1, far: float = 100.0) -> None:
        """俯视相机 — 精确复刻 DefaultCamera2D 配方（GL 位姿 (0,height,0) + Rx=+90°）。

        网格 (Square 等 2D 网格) 平铺在 GL X-Z 平面 (Y=0); 该相机从 +Y 俯视。
        view = inv(calculate_entity_model(...)) — 与 RuntimeNodeLayer._sync_camera_to_renderer 同路径。
        """
        from Application.Core.Math.Camera import orthogonal_projection
        from Application.Core.Math.Transform import calculate_entity_model
        from Application.Core.Renderer.RenderCommand import SetViewProjectionCommand

        aspect = self.width / self.height
        hw = half_h * aspect
        proj = orthogonal_projection(-hw, hw, -half_h, half_h, near, far)
        cam_model = calculate_entity_model(
            position=(0.0, float(height), 0.0),
            rotation=(1.5707963267948966, 0.0, 0.0),   # DefaultCamera2D 同款: Rx=+90°
            scale=(1.0, 1.0, 1.0),
        )
        view = np.linalg.inv(cam_model)
        self.renderer.enqueue(SetViewProjectionCommand(
            view=view.astype(np.float32), proj=proj.astype(np.float32),
            is_orthographic=True, ortho_size=half_h))

    def set_clear_color(self, r: float, g: float, b: float, a: float = 1.0) -> None:
        from Application.Core.Renderer.RenderCommand import SetClearColorCommand
        self.renderer.enqueue(SetClearColorCommand(r, g, b, a))

    def enqueue(self, cmd) -> None:
        self.renderer.enqueue(cmd)

    def render(self) -> None:
        """出一帧（消费命令队列 → 完整 _do_start_frame 管线）。"""
        self.renderer.StartFrame()

    def read_pixel(self, x: int, y: int) -> tuple[int, int, int, int]:
        """读像素（x,y 为顶左坐标系; 内部换算 GL 底左）。

        必须在 render() 之后、未交换缓冲时调用（读后缓冲）。
        """
        from OpenGL import GL as gl
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, 0)
        gl.glReadBuffer(gl.GL_BACK)
        buf = np.empty((1, 1, 4), dtype=np.uint8)
        gl.glReadPixels(int(x), self.height - 1 - int(y), 1, 1,
                        gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, buf)
        return tuple(int(v) for v in buf[0, 0])

    def color_near(self, px: tuple, expected: tuple, tol: int = 6) -> bool:
        """像素 ≈ 期望色（8bit 容差，默认 ±6 —— 浮点往返 + 无 MSAA 精确采样）。"""
        return all(abs(int(px[i]) - int(expected[i])) <= tol for i in range(3))

    # ════════════════════════════════════════════════════════════
    # 收尾
    # ════════════════════════════════════════════════════════════

    def close(self) -> None:
        try:
            self.renderer.Shutdown()
        except Exception:  # noqa: BLE001
            pass
        try:
            self._glfw.destroy_window(self.window)
            self._glfw.terminate()
        except Exception:  # noqa: BLE001
            pass
