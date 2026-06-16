"""
modernGLRenderer — ModernGL 渲染器后端 (继承 ModernGLCore + ModernGLResourceManager)。

特性:
  - 使用 moderngl 直接管理 GL 对象
  - 相机矩阵缓存机制
  - 延迟 resize 处理

架构:
  modernGLRenderer 继承:
    - ModernGLCore            : GL Context / 视口 / 清屏
    - ModernGLResourceManager : Mesh / Shader / Texture / Entity 注册与管理
    - Renderer                : 生命周期接口
    - RenderResourceManger    : 资源管理抽象接口

所有方法均为 @classmethod，以单例模式运作。
"""

from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from Application.Application import Application

from Application.Core.Events.Event import Event
from Application.Core.Events.WindowEvent import *
from Application.Core.Events.SceneEvent import *
from Application.Resource.ResourceManager import ResourceManager
from Application.Core.Scene.SceneManager import SceneManager
from Application.Core.Scene.BasicComponents import *
from Application.Core.Renderer.Renderer import Renderer, RenderResourceManger
from Application.Core.Renderer.ModernGL.ModernGLCore import ModernGLCore
from Application.Core.Renderer.ModernGL.ModernGLResourceManager import ModernGLResourceManager
from Application.Core.Math.Transform import calculate_entity_model

import numpy as np
import moderngl as mgl


class modernGLRenderer(ModernGLCore, ModernGLResourceManager, Renderer, RenderResourceManger):
    """ModernGL 渲染器 — 基于 moderngl 的 GPU 渲染后端。"""

    @classmethod
    def Create(
        cls
    ) -> "modernGLRenderer":
        from Application.Application import Application
        window_size = Application.editor_window.GetSize()
        ModernGLCore.init_core(window_size)
        cls.viewport_width = window_size[0]
        cls.viewport_height = window_size[1]
        cls.aspect_ratio = window_size[0] / window_size[1]
        # ── 缓存初始相机矩阵 (由 set_active_camera 在 OnAttach 中设置) ──
        if cls._active_camera is not None:
            cls._cached_view = cls._active_camera.get_view_matrix()
            cls._cached_proj = cls._active_camera.get_projection_matrix(cls.aspect_ratio)

        return cls

    @classmethod
    def StartFrame(cls) -> None:
        if cls._pending_resize is not None:
            w, h = cls._pending_resize
            ModernGLCore.update_viewport(w, h)
            cls._pending_resize = None
        ModernGLCore.clear_frame()
        view = cls._cached_view
        proj = cls._cached_proj
        for entity_id in SceneManager.GetRenderableEntities():
            entity = cls.registered_entities[entity_id]
            program = cls.registered_shaders[entity.shader_id].program
            # MVP 矩阵
            model = calculate_entity_model(SceneManager.GetEntityTransform(entity_id))
            program['model'].write(np.ascontiguousarray(model.astype('float32')).tobytes())
            program['view'].write(np.ascontiguousarray(view.astype('float32')).tobytes())
            program['projection'].write(np.ascontiguousarray(proj.astype('float32')).tobytes())
            # 纹理
            if entity.texture_id and entity.texture_id > 0:
                tex_data = cls.registered_textures.get(entity.texture_id)
                if tex_data and tex_data.gl_handle is not None:
                    tex_data.gl_handle.use(location=0)
                    try:
                        program['uTexture'] = 0
                    except KeyError:
                        pass
            # 材质 uniform
            material = ResourceManager.GetMaterial(entity.material_id)
            for u_name, u_value in material.uniforms_data.items():
                if u_name in ('model', 'view', 'projection'):
                    continue
                try:
                    if isinstance(u_value, np.ndarray) and u_value.ndim == 2:
                        program[u_name].write(
                            np.ascontiguousarray(u_value.astype('float32')).tobytes()
                        )
                    else:
                        program[u_name] = u_value
                except KeyError:
                    pass
            entity.vao.render(mgl.TRIANGLES)
        # ── Overlay 回调 (编辑器网格/Gizmo/轮廓, 由 Layer 注册) ──
        cls._render_overlays(view, proj)

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
            cls._on_window_resize(width, height)
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
            cls._on_camera_update()
