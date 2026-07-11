"""
OpenGLRenderer — PyOpenGL 渲染器 (MRO 编排层)。

特性:
  - 使用 PyOpenGL (opengl) 直接管理 GL 对象
  - 相机矩阵缓存机制 (继承自 Renderer 基类)
  - 延迟 resize 处理
  - pre-overlay hook 系统 (实体渲染前介入点, 支持 FBO 重定向 + stencil 注入)

架构 (Mixin 继承链, 按 MRO 顺序):
  OpenGLRenderer 继承:
    - OpenGLCore              : GL 状态 / 视口 / 清屏
    - OpenGLResourceManager   : 资源注册表
    - OpenGLPickSystem        : Pick FBO + Pass + Cache + API
    - OpenGLEntities          : 实体渲染 (_RenderEntities)
    - OpenGLOverlays          : overlay drawable 渲染 (_render_overlay_drawables)
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

from Application.Core.Renderer.Renderer import Renderer, RenderResourceManger
from Application.Core.Renderer.CommandQueue import CommandQueue
from Application.Core.Renderer.OpenGL.OpenGLCore import OpenGLCore
from Application.Core.Renderer.OpenGL.OpenGLResourceManager import OpenGLResourceManager
from Application.Core.Renderer.OpenGL.OpenGLPickSystem import OpenGLPickSystem
from Application.Core.Renderer.OpenGL.OpenGLOverlays import OpenGLOverlays
from Application.Core.Renderer.OpenGL.OpenGLEntities import OpenGLEntities
from Application.Core.Renderer.OpenGL.OpenGLPostProcess import OpenGLPostProcess


class OpenGLRenderer(Renderer, RenderResourceManger):
    """PyOpenGL 渲染器 — 纯抽象基类继承 + 组合组件。

    MRO: OpenGLRenderer → Renderer → RenderResourceManger

    组合组件:
      - self._core      : OpenGLCore         (GL 状态/视口/清屏)
      - self._resources : OpenGLResourceManager (资源注册表)
      - self._pick      : OpenGLPickSystem    (拾取)
      - self._entity    : OpenGLEntities      (实体渲染)
      - self._overlay   : OpenGLOverlays      (叠加层)
      - self._post      : OpenGLPostProcess   (后处理)
      - self._pp        : PostProcess         (后处理逻辑)
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

    # ── 类级默认值: Mixin classmethod (OpenGLEntities._RenderEntities) 通过 cls. 访问 ──
    _scene_fbo_override: int = 0
    _outline_selected_ids: set = set()

    def __init__(self, engine=None) -> None:
        super().__init__(engine=engine)
        # ★ 组合组件 (替代 MRO 继承)
        self._core = OpenGLCore()
        self._resources = OpenGLResourceManager(self)
        self._pick = OpenGLPickSystem(self)
        self._entity = OpenGLEntities(self)
        self._overlay = OpenGLOverlays(self)
        self._post = OpenGLPostProcess(self)
        # ── 本层状态 ──
        self._pre_overlay_callbacks: list[Callable] = []
        self._scene_fbo_override: int = 0
        self._outline_selected_ids: set[int] = set()

    def register_pre_overlay_callback(self, callback: Callable) -> None:
        """注册实体渲染前回调。

        典型用法: OutlineOverlay 注册 _on_pre_render, 在其中创建 Scene FBO、
        设置 stencil 状态、并通过 _scene_fbo_override 重定向实体渲染。

        Args:
            callback: fn(view, proj, vp_w, vp_h) → None
        """
        if callback not in self._pre_overlay_callbacks:
            self._pre_overlay_callbacks.append(callback)

    def unregister_pre_overlay_callback(self, callback: Callable) -> None:
        """取消注册 pre-overlay 回调。"""
        if callback in self._pre_overlay_callbacks:
            self._pre_overlay_callbacks.remove(callback)

    # ════════════════════════════════════════════════════════════
    # 生命周期
    # ════════════════════════════════════════════════════════════

    @classmethod
    def Create(
        cls,
        window: 'Window' = None,
        engine=None,
    ) -> "OpenGLRenderer":
        """初始化 OpenGL 渲染器。"""
        from Application.Core.Renderer.CommandQueue import CommandQueue
        instance = cls(engine=engine)
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
        instance._core.init_core(window_size)
        instance.viewport_width = window_size[0]
        instance.viewport_height = window_size[1]
        instance.aspect_ratio = window_size[0] / window_size[1]
        # ── 相机矩阵由逻辑线程通过 SetViewProjectionCommand 推送 ──
        # ── 初始化拾取系统 ──
        instance._pick.init_pick(window_size[0], window_size[1])
        # ── 初始化命令队列 ──
        instance._command_queue = CommandQueue()
        return instance

    # ════════════════════════════════════════════════════════════
    # 帧渲染
    # ════════════════════════════════════════════════════════════

    def _do_start_frame(self) -> None:
        if self._pending_resize is not None:
            w, h = self._pending_resize
            self._core.update_viewport(w, h)
            self.rebuild_pick_fbo(w, h)
            self._pending_resize = None
        # ── 恢复: pick FBO 被外部销毁后自动重建 (如 PIE 停止后编辑器恢复) ──
        if not self._pick._pick_fbo and self.viewport_width > 0 and self.viewport_height > 0:
            self.rebuild_pick_fbo(self.viewport_width, self.viewport_height)
        view = self._cached_view
        proj = self._cached_proj
        # ── 兜底: 无相机时使用单位矩阵 (PIE 首帧 / 未注入相机) ──
        if view is None:
            view = np.identity(4, dtype=np.float32)
        if proj is None:
            proj = np.identity(4, dtype=np.float32)
        vp_w, vp_h = self.viewport_width, self.viewport_height
        # ── 1. 清屏 ──
        self._core.clear_frame()
        # ── 2. Entity pick + overlay pick ──
        self._pick._render_entities_pick_pass(view, proj)
        self._pick._render_overlays_pick_pass(view, proj, vp_w, vp_h)
        # ── 3. Pre-overlay callbacks (FBO 创建 / stencil 预设) ──
        for cb in self._pre_overlay_callbacks:
            cb(view, proj, vp_w, vp_h)
        # ── 4. 实体渲染 (可能重定向到 Scene FBO) ──
        self._entity.render_entities(view, proj)
        # ── 5. 后处理管线 ──
        self._post._render_post_process(view, proj)
        # ── 6. 统一 overlay 入口 ──
        self._render_all_overlays(view, proj)

    def EndFrame(self) -> None:
        pass

    def Shutdown(self) -> None:
        """释放所有 OpenGL GPU 资源 — 渲染线程、GL 上下文有效时调用。

        清理顺序 (逆 MRO):
          1. 拾取系统: FBO + shader + pick key 映射
          2. 实体资源: VAO/VBO/EBO/Shader/Texture (级联降引用)
          3. Overlay 资源: VAO/VBO/EBO/Program/Texture
          4. 后处理资源: FBO + shader + quad VAO
          5. 基类: 命令队列 + overlay 回调 + 相机缓存
        """
        self._pick._destroy_pick()
        self._resources._unregister_all_entities()
        self._resources._unregister_all_overlays()
        self._post.unregister_highlight_effect()
        self._pre_overlay_callbacks.clear()
        self._outline_selected_ids.clear()
        self._scene_fbo_override = 0
        super().Shutdown()



    # ════════════════════════════════════════════════════════════
    # 桥接: OpenGLCore
    # ════════════════════════════════════════════════════════════

    def clear_frame(self) -> None:
        self._core.clear_frame()

    def update_viewport(self, w: int, h: int) -> None:
        self._core.update_viewport(w, h)

    def _clear_depth_for_overlays(self) -> None:
        self._core._clear_depth_for_overlays()

    # ════════════════════════════════════════════════════════════
    # 桥接: OpenGLResourceManager
    # ════════════════════════════════════════════════════════════

    def register_entity(self, entity_id: int) -> None:
        self._resources.register_entity(entity_id)

    def unregister_entity(self, entity_id: int) -> None:
        self._resources.unregister_entity(entity_id)

    def register_mesh(self, mesh, mesh_id: int) -> None:
        self._resources.register_mesh(mesh, mesh_id)

    def register_shader(self, shader, shader_id: int) -> None:
        self._resources.register_shader(shader, shader_id)

    def register_texture(self, texture, texture_id: int) -> None:
        self._resources.register_texture(texture, texture_id)

    def unregister_mesh(self, mesh_id: int) -> None:
        self._resources.unregister_mesh(mesh_id)

    def unregister_shader(self, shader_id: int) -> None:
        self._resources.unregister_shader(shader_id)

    def unregister_texture(self, texture_id: int) -> None:
        self._resources.unregister_texture(texture_id)

    @property
    def registered_entities(self):
        return self._resources.registered_entities

    @property
    def registered_meshes(self):
        return self._resources.registered_meshes

    @property
    def registered_shaders(self):
        return self._resources.registered_shaders

    @property
    def registered_textures(self):
        return self._resources.registered_textures

    @property
    def _overlay_gpu_resources(self):
        return self._resources._overlay_gpu_resources

    # ════════════════════════════════════════════════════════════
    # 桥接: PostProcess + OpenGLPostProcess (统一用 self._post)
    # ════════════════════════════════════════════════════════════

    def register_highlight_effect(self, config) -> None:
        self._post.register_highlight_effect(config)

    def unregister_highlight_effect(self) -> None:
        self._post.unregister_highlight_effect()

    def update_highlight_selection(self, selected_ids: set) -> None:
        self._post.update_highlight_selection(selected_ids)

    def _init_highlight(self, config) -> None:
        self._post._init_highlight(config)

    def _release_highlight(self) -> None:
        self._post._release_highlight()

    def _render_highlight(self, view, proj) -> None:
        self._post._render_highlight(view, proj)

    def _update_highlight_params(self) -> None:
        self._post._update_highlight_params()

    # ════════════════════════════════════════════════════════════
    # 桥接: PickSystem
    # ════════════════════════════════════════════════════════════

    def rebuild_pick_fbo(self, w: int, h: int) -> None:
        self._pick.rebuild_pick_fbo(w, h)

    def pick_at(self, x: float, y: float) -> tuple:
        return self._pick.pick_at(x, y)

    def update_pick_mouse(self, x: float, y: float) -> None:
        self._pick.update_pick_mouse(x, y)

    # ════════════════════════════════════════════════════════════
    # 桥接: Overlays + Overlay drawable 注册
    # ════════════════════════════════════════════════════════════

    def _render_overlay_drawables(self, view, proj, layer=-1) -> None:
        self._overlay._render_overlay_drawables(view, proj, layer)

    def register_overlay_drawable(self, overlay) -> None:
        self._resources.register_overlay_drawable(overlay)
        if overlay.pick_type > 0:
            self._pick.register_pick_key(overlay.pick_type, overlay.pick_id, overlay.key)

    def unregister_overlay_drawable(self, key: str) -> None:
        self._pick.unregister_pick_key(key)
        self._resources.unregister_overlay_drawable(key)

