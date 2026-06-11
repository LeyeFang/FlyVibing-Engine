"""
openGLRenderer — PyOpenGL 渲染器后端 (继承 OpenGLCore + OpenGLResourceManager)。

特性:
  - 使用 PyOpenGL (opengl) 直接管理 GL 对象
  - 相机矩阵缓存机制
  - 延迟 resize 处理

架构:
  openGLRenderer 继承:
    - OpenGLCore              : GL 状态 / 视口 / 清屏
    - OpenGLResourceManager   : Mesh / Shader / Texture / Entity 注册与管理
    - Renderer                : 生命周期接口
    - RenderResourceManger    : 资源管理抽象接口

对应关系:
  - modernGLRenderer  →  openGLRenderer (功能等价，不同后端)
  - ModernGLCore      →  OpenGLCore
  - ModernGLResourceManager → OpenGLResourceManager

所有方法均为 @classmethod，以单例模式运作。
"""

from __future__ import annotations
from typing import TYPE_CHECKING
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
from Application.Core.Math.RendererMath import calculate_entity_model
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
        # ── 场景渲染 ──
        OpenGLCore.clear_frame()
        cls._render_entities_pick_pass(view, proj)
        cls._RenderEntities(view, proj)
        cls._draw_registered_overlays(view, proj)

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
            None)
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
    def _render_entities_pick_pass(cls, view: np.ndarray, proj: np.ndarray) -> None:
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
                gl.GL_TRIANGLES, mesh_data.elements_count,
                gl.GL_UNSIGNED_INT, None)
        gl.glBindVertexArray(0)
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, 0)

        # ── 每帧预读鼠标位置像素 → _pick_cache (零延迟) ──
        sx, sy = cls._pick_mouse
        px = max(0, min(int(round(sx)), cls._pick_fbo_w - 1))
        py = max(0, min(int(round(sy)), cls._pick_fbo_h - 1))
        gl_y = cls._pick_fbo_h - 1 - py
        gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER, cls._pick_fbo)
        gl.glReadBuffer(gl.GL_COLOR_ATTACHMENT0)
        pixel = (gl.GLubyte * 4)()
        gl.glReadPixels(px, gl_y, 1, 1, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, pixel)
        gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER, 0)
        eid = int(pixel[0]) | (int(pixel[1]) << 8) | (int(pixel[2]) << 16)
        cls._pick_cache = eid if eid > 0 else -1

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
    # 默认实体渲染 (无 FBO / 无 stencil)
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _RenderEntities(
        cls,
        view: np.ndarray,
        proj: np.ndarray
    ) -> None:
        """默认管线: 直接渲染所有实体到当前绑定的帧缓冲。"""
        for entity_id in SceneManager.GetRenderableEntities():
            entity = cls.registered_entities.get(entity_id)
            if entity is None:
                continue
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
                gl.GL_TRIANGLES, mesh_data.elements_count,
                gl.GL_UNSIGNED_INT, None
            )
            gl.glBindVertexArray(0)

