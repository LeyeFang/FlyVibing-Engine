"""
openGLRenderer — PyOpenGL 渲染器 (MRO 编排层)。

特性:
  - 使用 PyOpenGL (opengl) 直接管理 GL 对象
  - 相机矩阵缓存机制 (继承自 Renderer 基类)
  - 延迟 resize 处理
  - pre-overlay hook 系统 (实体渲染前介入点, 支持 FBO 重定向 + stencil 注入)

架构 (Mixin 继承链, 按 MRO 顺序):
  openGLRenderer 继承:
    - OpenGLCore              : GL 状态 / 视口 / 清屏
    - OpenGLResourceManager   : 资源注册表
    - OpenGLPickSystem        : Pick FBO + Pass + Cache + API
    - OpenGLEntityRenderer    : 实体渲染 (_RenderEntities)
    - OpenGLOverlayRenderer   : overlay drawable 渲染 (_render_overlay_drawables)
    - OpenGLPostProcess       : 后处理管线 (MRT + 边缘检测 + 合成)
    - Renderer                : 生命周期接口 + overlay 回调
    - RenderResourceManger    : 资源管理抽象接口

所有方法均为 @classmethod，以单例模式运作。
"""

from __future__ import annotations
from typing import TYPE_CHECKING, Callable
if TYPE_CHECKING:
    from Application.Core.Engine import Engine
    from Application.Core.Window.Window import Window

import numpy as np

from Application.Core.Events.Event import Event
from Application.Core.Events.SceneEvent import SceneCameraUpdateEvent
from Application.Core.Events.InputEvent import MouseMoveEvent
from Application.Core.Renderer.Renderer import Renderer, RenderResourceManger
from Application.Core.Renderer.RenderCommand import (
    CameraUpdateCommand,
    PickMouseMoveCommand,
)
from Application.Core.Renderer.CommandQueue import CommandQueue
from Application.Core.Renderer.OpenGL.OpenGLCore import OpenGLCore
from Application.Core.Renderer.OpenGL.OpenGLResourceManager import OpenGLResourceManager
from Application.Core.Renderer.OpenGL.OpenGLPickSystem import OpenGLPickSystem
from Application.Core.Renderer.OpenGL.OpenGLOverlayRenderer import OpenGLOverlayRenderer
from Application.Core.Renderer.OpenGL.OpenGLEntityRenderer import OpenGLEntityRenderer
from Application.Core.Renderer.OpenGL.OpenGLPostProcess import OpenGLPostProcess


class openGLRenderer(
    OpenGLCore,
    OpenGLResourceManager,
    OpenGLPickSystem,
    OpenGLEntityRenderer,
    OpenGLOverlayRenderer,
    OpenGLPostProcess,
    Renderer,
    RenderResourceManger
):
    """PyOpenGL 渲染器 — MRO 编排层。

    MRO (C3 linearization):
      openGLRenderer → OpenGLOverlayRenderer → OpenGLEntityRenderer
        → OpenGLPickSystem → OpenGLResourceManager → OpenGLCore
        → Renderer → RenderResourceManger

    每个 Mixin 通过 cls.xxx 访问下层提供的资源注册表。
    """

    # ════════════════════════════════════════════════════════════
    # Pre-Overlay Hook 系统 (实体渲染前介入点)
    # ════════════════════════════════════════════════════════════
    #
    # 管线: clear → pick_pass → **pre_overlays** → _RenderEntities → _render_all_overlays
    #
    #   pre_overlay_callbacks  在实体渲染前运行, 可:
    #     - 创建 Scene FBO (depth24+stencil8)
    #     - 设置 stencil 状态
    #     - 通过 _scene_fbo_override 重定向 _RenderEntities
    #
    #   _render_all_overlays (来自 Renderer 基类) 在实体渲染后运行, 按序执行:
    #     1) 回调式 overlay (轮廓 pass + blit)
    #     2) 声明式 drawable (Grid/Gizmo)

    _pre_overlay_callbacks: list[Callable] = []
    """实体渲染前回调列表: fn(view, proj, vp_w, vp_h) → None"""

    _scene_fbo_override: int = 0
    """非零时 _RenderEntities 绑定此 FBO 而非默认帧缓冲 (由 pre-overlay 设置)"""

    _outline_selected_ids: set[int] = set()
    """被选实体 ID 集合 (由 OutlineOverlay 注入, _RenderEntities 据此写 stencil=1)"""

    @classmethod
    def register_pre_overlay_callback(cls, callback: Callable) -> None:
        """注册实体渲染前回调。

        典型用法: OutlineOverlay 注册 _on_pre_render, 在其中创建 Scene FBO、
        设置 stencil 状态、并通过 _scene_fbo_override 重定向实体渲染。

        Args:
            callback: fn(view, proj, vp_w, vp_h) → None
        """
        if callback not in cls._pre_overlay_callbacks:
            cls._pre_overlay_callbacks.append(callback)

    @classmethod
    def unregister_pre_overlay_callback(cls, callback: Callable) -> None:
        """取消注册 pre-overlay 回调。"""
        if callback in cls._pre_overlay_callbacks:
            cls._pre_overlay_callbacks.remove(callback)

    # ════════════════════════════════════════════════════════════
    # 生命周期
    # ════════════════════════════════════════════════════════════

    @classmethod
    def Create(
        cls,
        window: 'Window' = None,
    ) -> "openGLRenderer":
        """初始化 OpenGL 渲染器。

        Args:
            window: Engine 传入的 Window 实例。通过 window.GetSize() 获取初始尺寸。
                    调用方已在 Create 前调用 window.MakeContextCurrent()。
        """
        if window is not None:
            window_size = window.GetSize()
        else:
            # 回退: 从当前 GLFW 上下文获取 (兼容旧测试路径)
            import glfw as _glfw
            _glfw_win = _glfw.get_current_context()
            if _glfw_win is not None:
                window_size = _glfw.get_framebuffer_size(_glfw_win)
            else:
                window_size = (800, 600)
        OpenGLCore.init_core(window_size)
        cls.viewport_width = window_size[0]
        cls.viewport_height = window_size[1]
        cls.aspect_ratio = window_size[0] / window_size[1]
        # ── 缓存初始相机矩阵 (由 set_active_camera 在 OnAttach 中设置) ──
        if cls._active_camera is not None:
            cls._cached_view = cls._active_camera.get_view_matrix()
            cls._cached_proj = cls._active_camera.get_projection_matrix(cls.aspect_ratio)
        # ── 初始化拾取系统 ──
        cls.init_pick(window_size[0], window_size[1])
        # ── 初始化命令队列 ──
        cls._command_queue = CommandQueue()
        return cls

    # ════════════════════════════════════════════════════════════
    # 帧渲染
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _do_start_frame(cls) -> None:
        if cls._pending_resize is not None:
            w, h = cls._pending_resize
            OpenGLCore.update_viewport(w, h)
            cls.rebuild_pick_fbo(w, h)
            cls._pending_resize = None
        view = cls._cached_view
        proj = cls._cached_proj
        # ── 兜底: 无相机时使用单位矩阵 (PIE 首帧 / 未注入相机) ──
        if view is None:
            view = np.identity(4, dtype=np.float32)
        if proj is None:
            proj = np.identity(4, dtype=np.float32)
        vp_w, vp_h = cls.viewport_width, cls.viewport_height
        # ── 1. 清屏 ──
        OpenGLCore.clear_frame()
        # ── 2. Entity pick → pick FBO (FBO 不解绑) ──
        cls._render_entities_pick_pass(view, proj)
        # ── 2b. Overlay pick → pick FBO (最后解绑 + 预读缓存) ──
        cls._render_overlays_pick_pass(view, proj, vp_w, vp_h)
        # ── 3. Pre-overlay callbacks (FBO 创建 / stencil 预设) ──
        for cb in cls._pre_overlay_callbacks:
            cb(view, proj, vp_w, vp_h)
        # ── 4. 实体渲染 (可能重定向到 Scene FBO) ──
        cls._RenderEntities(view, proj)
        # ── 5. 后处理管线 (MRT → 边缘检测 → 合成) ──
        cls._render_post_process(view, proj)
        # ── 6. 统一 overlay 入口: 先回调, 后 drawable ──
        cls._render_all_overlays(view, proj)

    @classmethod
    def EndFrame(cls) -> None:
        pass

    @classmethod
    def Shutdown(cls) -> None:
        """释放所有 OpenGL GPU 资源 — 渲染线程、GL 上下文有效时调用。

        清理顺序 (逆 MRO):
          1. 拾取系统: FBO + shader + pick key 映射
          2. 实体资源: VAO/VBO/EBO/Shader/Texture (级联降引用)
          3. Overlay 资源: VAO/VBO/EBO/Program/Texture
          4. 后处理资源: FBO + shader + quad VAO
          5. 基类: 命令队列 + overlay 回调 + 相机缓存
        """
        cls._destroy_pick()
        cls._unregister_all_entities()
        cls._unregister_all_overlays()
        cls.unregister_highlight_effect()
        cls._pre_overlay_callbacks.clear()
        cls._outline_selected_ids.clear()
        cls._scene_fbo_override = 0
        super().Shutdown()

    @classmethod
    def OnEvent(cls, event: Event) -> None:
        """事件处理 — enqueue 命令到队列，由 StartFrame 消费。

        注意:
          - 窗口 resize 已改为直接 Command (glfwWindow 回调中提交)。
          - 实体注册/解注册使用 renderer.enqueue(EntityRegistrationCommand(...))。
        """
        if isinstance(event, SceneCameraUpdateEvent):
            cls.enqueue(CameraUpdateCommand())
        if isinstance(event, MouseMoveEvent):
            cls.enqueue(
                PickMouseMoveCommand(event.pos_x, event.pos_y))

    # ════════════════════════════════════════════════════════════
    # Overlay drawable 注册扩展 — 维护 pick_key 查找表
    # ════════════════════════════════════════════════════════════

    @classmethod
    def register_overlay_drawable(
        cls, overlay: 'RenderResourceManger.overlay_drawable_struct'
    ) -> None:
        super().register_overlay_drawable(overlay)
        if overlay.pick_type > 0:
            cls.register_pick_key(
                overlay.pick_type, overlay.pick_id, overlay.key)

    @classmethod
    def unregister_overlay_drawable(cls, key: str) -> None:
        cls.unregister_pick_key(key)
        super().unregister_overlay_drawable(key)

