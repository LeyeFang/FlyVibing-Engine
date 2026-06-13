"""
openGLRenderer — PyOpenGL 渲染器后端 (继承 OpenGLCore + OpenGLResourceManager)。

特性:
  - 使用 PyOpenGL (opengl) 直接管理 GL 对象
  - 相机矩阵缓存机制
  - 延迟 resize 处理
  - pre-overlay hook 系统 (实体渲染前介入点, 支持 FBO 重定向 + stencil 注入)

架构:
  openGLRenderer 继承:
    - OpenGLCore              : GL 状态 / 视口 / 清屏
    - OpenGLResourceManager   : Mesh / Shader / Texture / Entity 注册与管理
    - Renderer                : 生命周期接口 + overlay 回调 / 统一入口
    - RenderResourceManger    : 资源管理抽象接口 + overlay drawable 注册

对应关系:
  - modernGLRenderer  →  openGLRenderer (功能等价，不同后端)
  - ModernGLCore      →  OpenGLCore
  - ModernGLResourceManager → OpenGLResourceManager

所有方法均为 @classmethod，以单例模式运作。
"""

from __future__ import annotations
from typing import TYPE_CHECKING, Callable
if TYPE_CHECKING:
    from Application.Application import Application

from OpenGL import GL as gl

from Application.Core.Events.Event import Event
from Application.Core.Events.WindowEvent import *
from Application.Core.Events.SceneEvent import *
from Application.Core.Events.InputEvent import MouseMoveEvent
from Application.Resource.ResourceManager import ResourceManager
from Application.Core.Scene.SceneManager import SceneManager
from Application.Core.Scene.BasicComponents import *
from Application.Core.Renderer.Renderer import Renderer, RenderResourceManger
from Application.Core.Renderer.OpenGL.OpenGLCore import OpenGLCore
from Application.Core.Renderer.OpenGL.OpenGLResourceManager import OpenGLResourceManager
from Application.Core.Math.Transform import calculate_entity_model
from Application.Editor.EditorCamera import EditorCamera

import numpy as np


class openGLRenderer(
    OpenGLCore,
    OpenGLResourceManager,
    Renderer,
    RenderResourceManger
):
    """PyOpenGL 渲染器 — 基于 opengl 的 GPU 渲染后端。"""

    # ════════════════════════════════════════════════════════════
    # 类级状态
    # ════════════════════════════════════════════════════════════

    _cached_view: np.ndarray = None
    _cached_proj: np.ndarray = None
    _pending_resize: tuple = None

    # ── 持久拾取 FBO (每帧更新, 点击时即时读回) ──
    _pick_fbo: int = 0
    _pick_color: int = 0
    _pick_depth: int = 0
    _pick_prog: int = 0
    _pick_fbo_w: int = 0
    _pick_fbo_h: int = 0

    # ── 零延迟拾取: render thread 每帧预读, main thread 即时获取 ──
    _pick_mouse: tuple = (0, 0)  # 鼠标位置, main thread 每帧更新
    _pick_cache: int = -1         # entity_id, render thread 每帧刷新

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

    # ── 拾取着色器: ID → RGB24 ──
    _PICK_VS: str = """#version 330 core
layout (location = 0) in vec3 aPos;
uniform mat4 uModel;
uniform mat4 uView;
uniform mat4 uProj;
void main() {
    gl_Position = uProj * uView * uModel * vec4(aPos, 1.0);
}
"""

    _PICK_FS: str = """#version 330 core
uniform float uPickID;
out vec4 fragColor;
void main() {
    float id = uPickID;
    float r = mod(id, 256.0) / 255.0;
    float g = mod(floor(id / 256.0), 256.0) / 255.0;
    float b = floor(id / 65536.0) / 255.0;
    fragColor = vec4(r, g, b, 1.0);
}
"""

    # ── Overlay 拾取着色器: R=0(标记), G=type, B=id ──
    _OVERLAY_PICK_VS: str = """#version 440 core
layout (location = 0) in vec3 aPos;
layout (location = 0) uniform int uIsNDC;
layout (location = 1) uniform mat4 uModel;
layout (location = 5) uniform mat4 uViewProj;
void main() {
    if (uIsNDC == 1)
        gl_Position = uModel * vec4(aPos, 1.0);
    else
        gl_Position = uViewProj * uModel * vec4(aPos, 1.0);
}
"""

    _OVERLAY_PICK_FS: str = """#version 440 core
layout (location = 10) uniform float uPickType;
layout (location = 11) uniform float uPickID;
out vec4 fragColor;
void main() {
    fragColor = vec4(0.0, uPickType / 255.0, uPickID / 255.0, 1.0);
}
"""

    # ── Overlay pick 资源 ──
    _overlay_pick_prog: int = 0
    _overlay_pick_key_map: dict[tuple[int, int], str] = {}
    _pick_overlay_key: str | None = None

    # ════════════════════════════════════════════════════════════
    # 生命周期
    # ════════════════════════════════════════════════════════════

    @classmethod
    def Create(
        cls
    ) -> "openGLRenderer":
        from Application.Application import Application
        window_size = Application.editor_window.GetSize()
        OpenGLCore.init_core(window_size)
        cls.viewport_width = window_size[0]
        cls.viewport_height = window_size[1]
        cls.aspect_ratio = window_size[0] / window_size[1]
        cam = EditorCamera.get_instance()
        cls._cached_view = cam.get_view_matrix()
        cls._cached_proj = cam.get_projection_matrix(cls.aspect_ratio)
        # ── 编译拾取着色器 + 创建拾取 FBO ──
        cls._pick_prog = cls._compile_program(cls._PICK_VS, cls._PICK_FS)
        cls._overlay_pick_prog = cls._compile_program(
            cls._OVERLAY_PICK_VS, cls._OVERLAY_PICK_FS)
        cls._rebuild_pick_fbo(window_size[0], window_size[1])
        return cls

    # ════════════════════════════════════════════════════════════
    # 帧渲染
    # ════════════════════════════════════════════════════════════

    @classmethod
    def StartFrame(cls) -> None:
        if cls._pending_resize is not None:
            w, h = cls._pending_resize
            OpenGLCore.update_viewport(w, h)
            cls._rebuild_pick_fbo(w, h)
            cls._pending_resize = None
        view = cls._cached_view
        proj = cls._cached_proj
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
        # ── 5. 统一 overlay 入口: 先回调, 后 drawable ──
        cls._render_all_overlays(view, proj)

    @classmethod
    def EndFrame(cls) -> None:
        pass

    @classmethod
    def OnEvent(
        cls,
        event: Event
    ) -> None:
        if event is WindowResizeEvent:
            width, height = event.UnPack()
            cls._pending_resize = (width, height)
            cls.aspect_ratio = width / height
            cam = EditorCamera.get_instance()
            cls._cached_proj = cam.get_projection_matrix(cls.aspect_ratio)
        if any([
            event is NewComponentEvent,
            event is ComponentModifiedEvent
        ]):
            entity_id, comp = event.UnPack()
            if isinstance(comp, MeshRenderer):
                if comp.visible:
                    cls.register_entity(entity_id)
                else:
                    cls.unregister_entity(entity_id)
        if event is SceneCameraUpdateEvent:
            cls._camera_update_callback(event)
        if event is MouseMoveEvent:
            cls._pick_mouse = (MouseMoveEvent.pos_x, MouseMoveEvent.pos_y)

    @classmethod
    def _camera_update_callback(
        cls,
        event: SceneCameraUpdateEvent
    ) -> None:
        cam = EditorCamera.get_instance()
        cls._cached_view = cam.get_view_matrix()
        cls._cached_proj = cam.get_projection_matrix(cls.aspect_ratio)

    # ════════════════════════════════════════════════════════════
    # 持久拾取 FBO — 每帧渲染, 点击即时读回
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _rebuild_pick_fbo(cls, w: int, h: int) -> None:
        """重建拾取 FBO (resize 时调用)。"""
        if cls._pick_fbo:
            gl.glDeleteFramebuffers(1, [cls._pick_fbo])
        if cls._pick_color:
            gl.glDeleteTextures(1, [cls._pick_color])
        if cls._pick_depth:
            gl.glDeleteRenderbuffers(1, [cls._pick_depth])
        cls._pick_fbo = gl.glGenFramebuffers(1)
        cls._pick_color = gl.glGenTextures(1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, cls._pick_color)
        gl.glTexImage2D(
            gl.GL_TEXTURE_2D,
            0,
            gl.GL_RGBA8,
            w, h,
            0,
            gl.GL_RGBA,
            gl.GL_UNSIGNED_BYTE,
            None
        )
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_NEAREST)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST)
        cls._pick_depth = gl.glGenRenderbuffers(1)
        gl.glBindRenderbuffer(gl.GL_RENDERBUFFER, cls._pick_depth)
        gl.glRenderbufferStorage(gl.GL_RENDERBUFFER, gl.GL_DEPTH_COMPONENT24, w, h)
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, cls._pick_fbo)
        gl.glFramebufferTexture2D(
            gl.GL_FRAMEBUFFER,
            gl.GL_COLOR_ATTACHMENT0,
            gl.GL_TEXTURE_2D,
            cls._pick_color,
            0)
        gl.glFramebufferRenderbuffer(
            gl.GL_FRAMEBUFFER,
            gl.GL_DEPTH_ATTACHMENT,
            gl.GL_RENDERBUFFER,
            cls._pick_depth)
        if gl.glCheckFramebufferStatus(gl.GL_FRAMEBUFFER) != gl.GL_FRAMEBUFFER_COMPLETE:
            raise RuntimeError("Pick FBO incomplete")
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, 0)
        cls._pick_fbo_w, cls._pick_fbo_h = w, h

    @classmethod
    def _render_entities_pick_pass(
        cls,
        view: np.ndarray,
        proj: np.ndarray
    ) -> None:
        """每帧将实体 ID 渲染到拾取 FBO — 无 glFinish, 零等待。"""
        entities = SceneManager.GetRenderableEntities()
        if not entities:
            return
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, cls._pick_fbo)
        gl.glViewport(0, 0, cls._pick_fbo_w, cls._pick_fbo_h)
        gl.glClearColor(0.0, 0.0, 0.0, 1.0)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glDepthFunc(gl.GL_LESS)
        gl.glDepthMask(gl.GL_TRUE)
        gl.glDisable(gl.GL_BLEND)
        gl.glUseProgram(cls._pick_prog)
        loc_model = gl.glGetUniformLocation(cls._pick_prog, 'uModel')
        loc_view = gl.glGetUniformLocation(cls._pick_prog, 'uView')
        loc_proj = gl.glGetUniformLocation(cls._pick_prog, 'uProj')
        loc_id = gl.glGetUniformLocation(cls._pick_prog, 'uPickID')
        view_f32 = np.ascontiguousarray(view.astype('float32'))
        proj_f32 = np.ascontiguousarray(proj.astype('float32'))
        for entity_id in entities:
            gpu = cls.registered_entities.get(entity_id)
            if gpu is None:
                continue
            model = calculate_entity_model(SceneManager.GetEntityTransform(entity_id))
            model_f32 = np.ascontiguousarray(model.astype('float32'))
            if loc_model >= 0:
                gl.glUniformMatrix4fv(loc_model, 1, gl.GL_FALSE, model_f32)
            if loc_view >= 0:
                gl.glUniformMatrix4fv(loc_view, 1, gl.GL_FALSE, view_f32)
            if loc_proj >= 0:
                gl.glUniformMatrix4fv(loc_proj, 1, gl.GL_FALSE, proj_f32)
            if loc_id >= 0:
                gl.glUniform1f(loc_id, float(entity_id))
            gl.glBindVertexArray(gpu.vao)
            mesh_data = cls.registered_meshes[gpu.mesh_id]
            gl.glDrawElements(
                gl.GL_TRIANGLES,
                mesh_data.elements_count,
                gl.GL_UNSIGNED_INT,
                None
            )
        gl.glBindVertexArray(0)
        # FBO 保持绑定 → _render_overlays_pick_pass 续用

    @classmethod
    def update_pick_mouse(cls, x: float, y: float) -> None:
        """更新鼠标位置 (main thread 每帧调用)。"""
        cls._pick_mouse = (x, y)

    @classmethod
    def get_pick(cls) -> int:
        """获取当前鼠标下的 entity_id (main thread, 即时返回, 零阻塞)。

        render thread 每帧预读 _pick_mouse 位置的像素到 _pick_cache,
        因此返回值最多落后 1 帧 (~3ms), 人眼完全不可感知。
        """
        return cls._pick_cache

    # ════════════════════════════════════════════════════════════
    # 统一拾取缓存 — render thread 每帧写入, main thread 零 GL 读取
    # ════════════════════════════════════════════════════════════

    _pick_overlay_key: str | None = None  # 当前鼠标下 overlay 的 key

    # ════════════════════════════════════════════════════════════
    # Overlay Pick Pass (R=0, G=type, B=id, 延续 entity pass FBO)
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _render_overlays_pick_pass(
        cls, view: np.ndarray, proj: np.ndarray, vp_w: int, vp_h: int
    ) -> None:
        """渲染可拾取 overlay → pick FBO, R=0 标记 overlay。"""
        pickable = [(k, g) for k, g in cls._overlay_gpu_resources.items() if g.pick_type > 0]
        if not pickable:
            cls._finalize_pick_read()
            return
        vp_mat = np.ascontiguousarray((proj @ view).astype('float32'))
        gl.glUseProgram(cls._overlay_pick_prog)
        loc_model = gl.glGetUniformLocation(cls._overlay_pick_prog, 'uModel')
        loc_ndc  = gl.glGetUniformLocation(cls._overlay_pick_prog, 'uIsNDC')
        loc_vp   = gl.glGetUniformLocation(cls._overlay_pick_prog, 'uViewProj')
        loc_type = gl.glGetUniformLocation(cls._overlay_pick_prog, 'uPickType')
        loc_id   = gl.glGetUniformLocation(cls._overlay_pick_prog, 'uPickID')
        for _key, gpu in cls._overlay_gpu_resources.items():
            if gpu.pick_type <= 0:
                continue
            if loc_type >= 0:
                gl.glUniform1f(loc_type, float(gpu.pick_type))
            if loc_id >= 0:
                gl.glUniform1f(loc_id, float(gpu.pick_id))
            if gpu.ignore_scene_matrices and gpu.model_matrix_cb:
                if loc_ndc >= 0:
                    gl.glUniform1i(loc_ndc, 1)
                model = gpu.model_matrix_cb(vp_w, vp_h)
                if loc_model >= 0:
                    gl.glUniformMatrix4fv(loc_model, 1, gl.GL_TRUE,
                        np.ascontiguousarray(model.astype('float32')))
            else:
                if loc_ndc >= 0:
                    gl.glUniform1i(loc_ndc, 0)
                if loc_vp >= 0:
                    gl.glUniformMatrix4fv(loc_vp, 1, gl.GL_FALSE, vp_mat)
                if loc_model >= 0:
                    gl.glUniformMatrix4fv(loc_model, 1, gl.GL_FALSE,
                        np.identity(4, dtype='float32'))
            # ── 面剔除: 与 visual pass 保持一致 ──
            if gpu.cull_face:
                gl.glEnable(gl.GL_CULL_FACE)
                gl.glCullFace(gl.GL_BACK)
                gl.glFrontFace(gl.GL_CCW)
            else:
                gl.glDisable(gl.GL_CULL_FACE)
            gl.glDepthFunc(gl.GL_LEQUAL)
            gl.glBindVertexArray(gpu.vao)
            gl.glDrawElements(gpu.draw_mode, gpu.elements_count,
                              gl.GL_UNSIGNED_INT, None)
        gl.glBindVertexArray(0)
        gl.glDisable(gl.GL_CULL_FACE)
        gl.glDepthFunc(gl.GL_LESS)
        # ── 每帧预读 → _pick_cache + _pick_overlay_key ──
        cls._finalize_pick_read()

    @classmethod
    def _finalize_pick_read(cls) -> None:
        """解绑 pick FBO 并预读鼠标位置像素 → 缓存。

        render thread 专用, 包含 glFinish + glReadPixels。
        main thread 通过 get_pick() / pick_at() 零 GL 读取。
        """
        sx, sy = cls._pick_mouse
        px = max(0, min(int(round(sx)), cls._pick_fbo_w - 1))
        py = max(0, min(int(round(sy)), cls._pick_fbo_h - 1))
        gl_y = cls._pick_fbo_h - 1 - py
        gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER, cls._pick_fbo)
        gl.glReadBuffer(gl.GL_COLOR_ATTACHMENT0)
        gl.glFinish()
        pixel = (gl.GLubyte * 4)()
        gl.glReadPixels(px, gl_y, 1, 1, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, pixel)
        gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER, 0)
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, 0)
        r, g, b = int(pixel[0]), int(pixel[1]), int(pixel[2])
        if r > 0:
            cls._pick_cache = r | (g << 8) | (b << 16)
            cls._pick_overlay_key = None
        elif g > 0:
            cls._pick_cache = -1
            cls._pick_overlay_key = cls._overlay_pick_key_map.get((g, b))
        else:
            cls._pick_cache = -1
            cls._pick_overlay_key = None

    # ════════════════════════════════════════════════════════════
    # 统一拾取 API — main thread 安全, 零 GL 调用
    # ════════════════════════════════════════════════════════════

    @classmethod
    def pick_at(cls, sx: float, sy: float) -> tuple:
        """统一拾取 → (type, value) — 返回渲染线程预读的缓存结果。

        注意: 当前实现返回的是 _pick_mouse 位置的缓存,
        不区分 sx,sy (适用于鼠标点击场景, 点击前鼠标已就位)。
        """
        if cls._pick_cache >= 0:
            return ('entity', cls._pick_cache)
        if cls._pick_overlay_key is not None:
            return ('overlay', cls._pick_overlay_key)
        return (None, None)

    # ════════════════════════════════════════════════════════════
    # Overlay drawable 注册扩展 — 维护 pick_key 查找表
    # ════════════════════════════════════════════════════════════

    @classmethod
    def register_overlay_drawable(
        cls, overlay: 'RenderResourceManger.overlay_drawable_struct'
    ) -> None:
        super().register_overlay_drawable(overlay)
        if overlay.pick_type > 0:
            cls._overlay_pick_key_map[(overlay.pick_type, overlay.pick_id)] = overlay.key

    @classmethod
    def unregister_overlay_drawable(cls, key: str) -> None:
        to_remove = [k for k, v in cls._overlay_pick_key_map.items() if v == key]
        for k in to_remove:
            del cls._overlay_pick_key_map[k]
        super().unregister_overlay_drawable(key)

    # ════════════════════════════════════════════════════════════
    # 实体渲染 (支持 FBO 重定向 + stencil 注入)
    # ════════════════════════════════════════════════════════════
    #
    # 当没有 pre-overlay 设置 _scene_fbo_override 时, 行为与原版完全一致。
    # 有 pre-overlay 时: 渲染重定向到 Scene FBO, 被选实体写 stencil=1。

    @classmethod
    def _RenderEntities(
        cls,
        view: np.ndarray,
        proj: np.ndarray
    ) -> None:
        """渲染所有实体 — 支持 FBO 重定向 + stencil 注入。"""
        # ── FBO 重定向 (由 pre-overlay 控制) ──
        target_fbo = cls._scene_fbo_override
        if target_fbo:
            gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, target_fbo)
            gl.glViewport(0, 0, cls.viewport_width, cls.viewport_height)

        has_outline = bool(cls._outline_selected_ids)

        for entity_id in SceneManager.GetRenderableEntities():
            entity = cls.registered_entities.get(entity_id)
            if entity is None:
                continue

            # ── Stencil 写入: 被选实体写 stencil=1 (由 OutlineOverlay 注入) ──
            if has_outline:
                if entity_id in cls._outline_selected_ids:
                    gl.glStencilFunc(gl.GL_ALWAYS, 1, 0xFF)
                    gl.glStencilMask(0xFF)
                else:
                    gl.glStencilMask(0x00)

            program = cls.registered_shaders[entity.shader_id].program
            # ── 激活 shader ──
            gl.glUseProgram(program)
            # ── MVP 矩阵 ──
            model = calculate_entity_model(
                SceneManager.GetEntityTransform(entity_id)
            )
            cls.set_uniform_mat4(entity.shader_id, 'model', model)
            cls.set_uniform_mat4(entity.shader_id, 'view', view)
            cls.set_uniform_mat4(entity.shader_id, 'projection', proj)
            # ── 纹理 ──
            if entity.texture_id and entity.texture_id > 0:
                tex_data = cls.registered_textures.get(entity.texture_id)
                if tex_data and tex_data.gl_handle:
                    gl.glActiveTexture(gl.GL_TEXTURE0)
                    gl.glBindTexture(gl.GL_TEXTURE_2D, tex_data.gl_handle)
                    cls.set_uniform_int(entity.shader_id, 'uTexture', 0)
            # ── 材质 uniform ──
            material = ResourceManager.GetMaterial(entity.material_id)
            for u_name, u_value in material.uniforms_data.items():
                if u_name in ('model', 'view', 'projection'):
                    continue
                cls.set_uniform_value(entity.shader_id, u_name, u_value)
            # ── 绘制 ──
            gl.glBindVertexArray(entity.vao)
            mesh_data = cls.registered_meshes[entity.mesh_id]
            gl.glDrawElements(
                gl.GL_TRIANGLES,
                mesh_data.elements_count,
                gl.GL_UNSIGNED_INT,
                None
            )
            gl.glBindVertexArray(0)

        # ── 恢复 stencil mask ──
        if has_outline:
            gl.glStencilMask(0xFF)

        # ── 解绑 FBO (回到默认帧缓冲) ──
        if target_fbo:
            gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, 0)

