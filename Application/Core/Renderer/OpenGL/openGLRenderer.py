"""
openGLRenderer — PyOpenGL 渲染器后端 (继承 OpenGLCore + OpenGLResourceManager)。

特性:
  - 使用 PyOpenGL (opengl) 直接管理 GL 对象
  - 相机矩阵缓存机制
  - 延迟 resize 处理
  - (new) FBO 管线: scene FBO (depth24+stencil8) + pick FBO (depth24)
  - (new) Stencil 轮廓高亮: 选中实体橙色边框 + X-Ray 模式
  - (new) FBO 实体拾取: PickAt(sx, sy) → entity_id

架构:
  openGLRenderer 继承:
    - OpenGLCore              : GL 状态 / 视口 / 清屏
    - OpenGLResourceManager   : Mesh / Shader / Texture / Entity 注册与管理
    - Renderer                : 生命周期接口
    - RenderResourceManger    : 资源管理抽象接口

FBO 管线 (当 _enable_fbo_pipeline = True):
  StartFrame:
    1. Scene Pass   → scene FBO: 绘制实体, 被选中者写 stencil=1
    2. Outline Pass → scene FBO: stencil NOTEQUAL → 橙色轮廓
    3. Overlay Callbacks → scene FBO
    4. Registered Overlays → scene FBO
  EndFrame:
    5. Blit         → scene FBO 颜色纹理 → 默认帧缓冲

编辑器桥梁 (对齐 overlay 模式):
  EditorLayer → SetOutlineConfig(selected_ids, color, scale, xray)
  渲染器根据配置在 StartFrame 中自动应用 stencil 轮廓。

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
    """PyOpenGL 渲染器 — 基于 opengl 的 GPU 渲染后端。

    轮廓/拾取功能已迁移到 Application.Editor.Rendering.Outliner,
    通过 register_outliner / unregister_outliner 管理。
    """

    # ════════════════════════════════════════════════════════════
    # 类级状态
    # ════════════════════════════════════════════════════════════

    _cached_view: np.ndarray = None
    _cached_proj: np.ndarray = None
    _pending_resize: tuple = None

    # ── Outliner 引用 (编辑器注册) ──
    _outliner: 'Outliner' = None

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

        return cls

    # ════════════════════════════════════════════════════════════
    # Outliner 管理 (编辑器在 OnAttach 时调用)
    # ════════════════════════════════════════════════════════════

    @classmethod
    def register_outliner(
        cls,
        outliner: 'Outliner'
    ) -> None:
        """注册 Outliner — 渲染器启用 FBO 管线。

        调用时机: EditorLayer.OnAttach (render thread, GL context 有效)。
        与 Grid.register_to(renderer) 对齐: 编辑器注册, 渲染器持有引用。

        Args:
            outliner: Outliner 实例 (已调用 outliner.init(renderer, w, h))
        """
        cls._outliner = outliner
        print("[openGLRenderer] Outliner registered — FBO pipeline enabled")

    @classmethod
    def unregister_outliner(cls) -> None:
        """取消注册 Outliner — 恢复到默认渲染管线。"""
        if cls._outliner is not None:
            cls._outliner.release()
            cls._outliner = None
            print("[openGLRenderer] Outliner unregistered")

    # ════════════════════════════════════════════════════════════
    # 帧渲染
    # ════════════════════════════════════════════════════════════

    @classmethod
    def StartFrame(cls) -> None:
        if cls._pending_resize is not None:
            w, h = cls._pending_resize
            OpenGLCore.update_viewport(w, h)
            if cls._outliner is not None:
                cls._outliner.resize(w, h)
            cls._pending_resize = None

        view = cls._cached_view
        proj = cls._cached_proj

        if cls._outliner is not None:
            # ── Outliner FBO 管线 ──
            cls._outliner.render_scene_pass(cls, view, proj)
            cls._outliner.render_outline_pass(cls, view, proj)
            cls._render_overlays(view, proj)
            cls._draw_registered_overlays(view, proj)
        else:
            # ── 默认管线 ──
            OpenGLCore.clear_frame()
            cls._RenderEntities(view, proj)
            cls._render_overlays(view, proj)
            cls._draw_registered_overlays(view, proj)

    @classmethod
    def EndFrame(cls) -> None:
        if cls._outliner is not None:
            cls._outliner.blit_to_screen()

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

    @classmethod
    def _camera_update_callback(
        cls,
        event: SceneCameraUpdateEvent
    ) -> None:
        cam = EditorCamera.get_instance()
        cls._cached_view = cam.get_view_matrix()
        cls._cached_proj = cam.get_projection_matrix(cls.aspect_ratio)

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

