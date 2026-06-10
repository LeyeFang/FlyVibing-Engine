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
import ctypes
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

    FBO 管线 + Stencil 轮廓高亮 + FBO 实体拾取。
    """

    # ════════════════════════════════════════════════════════════
    # 内联着色器 — 轮廓/拾取/Blit (编辑器内部, 不走 ResourceManager)
    # ════════════════════════════════════════════════════════════

    _OUTLINE_VS_SRC: str = """#version 330 core
layout(location=0) in vec3 aPos;
layout(location=1) in vec2 aTexCoord;
layout(location=2) in vec3 aNormal;
uniform mat4 model, view, projection;
uniform float uOutlineScale;
void main() {
    gl_Position = projection * view * model * vec4(aPos * uOutlineScale, 1.0);
}
"""

    _OUTLINE_FS_SRC: str = """#version 330 core
uniform vec3 uOutlineColor;
out vec4 fragColor;
void main() { fragColor = vec4(uOutlineColor, 1.0); }
"""

    # pick 顶点着色器: 与引擎实体 VAO 布局一致 (location 0/1/2)
    _PICK_VS_SRC: str = """#version 330 core
layout(location=0) in vec3 aPos;
layout(location=1) in vec2 aTexCoord;
layout(location=2) in vec3 aNormal;
uniform mat4 model, view, projection;
void main() {
    gl_Position = projection * view * model * vec4(aPos, 1.0);
}
"""

    _PICK_FS_SRC: str = """#version 330 core
uniform float uPickID;
out vec4 fragColor;
void main() { fragColor = vec4(uPickID / 255.0, 0.0, 0.0, 1.0); }
"""

    _BLIT_VS_SRC: str = """#version 330 core
in vec2 aPos;
out vec2 vUV;
void main() {
    gl_Position = vec4(aPos, 0.0, 1.0);
    vUV = aPos * 0.5 + 0.5;
}
"""

    _BLIT_FS_SRC: str = """#version 330 core
in vec2 vUV;
out vec4 fragColor;
uniform sampler2D uScreenTex;
void main() { fragColor = texture(uScreenTex, vUV); }
"""

    # ════════════════════════════════════════════════════════════
    # 类级状态 — 相机 & 视口
    # ════════════════════════════════════════════════════════════

    _cached_view: np.ndarray = None
    _cached_proj: np.ndarray = None
    _pending_resize: tuple = None

    # ════════════════════════════════════════════════════════════
    # 类级状态 — FBO 管线 (编辑器轮廓/拾取)
    # ════════════════════════════════════════════════════════════

    _enable_fbo_pipeline: bool = False

    # FBO 资源句柄
    _fbo_scene: int = 0          # scene FBO
    _fbo_scene_color: int = 0    #  └─ 颜色纹理附件
    _fbo_scene_ds: int = 0       #  └─ depth24+stencil8 RBO
    _fbo_pick: int = 0           # pick FBO
    _fbo_pick_color: int = 0     #  └─ 颜色纹理附件
    _fbo_pick_depth: int = 0     #  └─ depth24 RBO

    # 轮廓/拾取/Blit 着色器程序 (编辑器内部, 不走 ResourceManager)
    _prog_outline: int = 0
    _prog_pick: int = 0
    _prog_blit: int = 0

    # Blit 全屏四边形 VAO
    _vao_blit: int = 0

    # 轮廓配置 (编辑器通过 SetOutlineConfig 设置)
    _outline_selected_ids: set = set()
    _outline_color: tuple = (0.976, 0.451, 0.024)     # 橙色
    _outline_scale: float = 1.05
    _outline_xray: bool = True

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

        # ── 编译编辑器内部着色器 (轮廓 / 拾取 / Blit) ──
        cls._prog_outline = cls._compile_internal_program(
            cls._OUTLINE_VS_SRC, cls._OUTLINE_FS_SRC
        )
        cls._prog_pick = cls._compile_internal_program(
            cls._PICK_VS_SRC, cls._PICK_FS_SRC
        )
        cls._prog_blit = cls._compile_internal_program(
            cls._BLIT_VS_SRC, cls._BLIT_FS_SRC
        )

        # ── 全屏四边形 VAO ──
        cls._vao_blit = cls._create_fullscreen_quad()

        return cls

    # ════════════════════════════════════════════════════════════
    # 帧渲染
    # ════════════════════════════════════════════════════════════

    @classmethod
    def StartFrame(cls) -> None:
        if cls._pending_resize is not None:
            w, h = cls._pending_resize
            OpenGLCore.update_viewport(w, h)
            if cls._enable_fbo_pipeline:
                cls._RebuildFBOs(w, h)
            cls._pending_resize = None

        view = cls._cached_view
        proj = cls._cached_proj

        if cls._enable_fbo_pipeline:
            cls._RenderFBOFrame(view, proj)
        else:
            OpenGLCore.clear_frame()
            cls._RenderEntities(view, proj)
            cls._render_overlays(view, proj)
            cls._draw_registered_overlays(view, proj)

    @classmethod
    def EndFrame(cls) -> None:
        if cls._enable_fbo_pipeline:
            cls._BlitSceneToScreen()

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
    # 编辑器轮廓接口 (EditorLayer → Renderer)
    # ════════════════════════════════════════════════════════════

    @classmethod
    def EnableFBOPipeline(
        cls
    ) -> None:
        """启用 FBO 管线 (编辑器 OnAttach 时调用)。

        启用后 StartFrame/EndFrame 使用 FBO + stencil 管线，
        支持轮廓高亮和实体拾取。

        与 Grid.register_to(renderer) 对齐: 编辑器通知渲染器启用功能。
        """
        cls._enable_fbo_pipeline = True
        print("[openGLRenderer] FBO pipeline enabled")

    @classmethod
    def SetOutlineConfig(
        cls,
        selected_ids: set = None,
        color: tuple = None,
        scale: float = None,
        xray: bool = None
    ) -> None:
        """编辑器设置轮廓配置 (纯数据 → 渲染器)。

        编辑器职责: 管理选择状态, 调用此方法传入数据。
        渲染器职责: 在 StartFrame 中读取配置, 执行 stencil 轮廓绘制。

        与 overlay 模式对齐:
          - Grid.register_to(renderer)   → 注册可绘制对象
          - renderer.SetOutlineConfig()  → 设置轮廓参数

        Args:
            selected_ids: 被选中实体 ID 集合
            color:        轮廓颜色 RGB tuple, 默认橙色 (0.976, 0.451, 0.024)
            scale:        轮廓放大系数, 默认 1.05
            xray:         True=穿透遮挡, False=仅可见边缘
        """
        if selected_ids is not None:
            cls._outline_selected_ids = selected_ids
        if color is not None:
            cls._outline_color = color
        if scale is not None:
            cls._outline_scale = scale
        if xray is not None:
            cls._outline_xray = xray

    # ════════════════════════════════════════════════════════════
    # FBO 实体拾取 (编辑器 → ScenePanel 点击 → 选中实体)
    # ════════════════════════════════════════════════════════════

    @classmethod
    def PickAt(
        cls,
        sx: float,
        sy: float
    ) -> int:
        """FBO 拾取: 返回屏幕坐标 (sx, sy) 处的实体 ID。

        每实体用其 ECS entity_id 作为 pick ID 渲染到 pick FBO,
        glReadPixels 读取对应像素, 解析为 entity_id。

        未命中返回 -1。

        Args:
            sx: 屏幕 X 坐标 (像素, 左上角原点)
            sy: 屏幕 Y 坐标 (像素, 左上角原点)

        Returns:
            entity_id 或 -1
        """
        if not cls._enable_fbo_pipeline:
            cls._InitFBOPipeline(cls.viewport_width, cls.viewport_height)

        entities = SceneManager.GetRenderableEntities()
        if not entities:
            return -1

        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, cls._fbo_pick)
        gl.glViewport(0, 0, cls.viewport_width, cls.viewport_height)
        gl.glClearColor(0, 0, 0, 1)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glDepthFunc(gl.GL_LEQUAL)
        gl.glDepthMask(gl.GL_TRUE)
        gl.glDisable(gl.GL_STENCIL_TEST)

        gl.glUseProgram(cls._prog_pick)
        cls.set_uniform_mat4(-2, 'view', cls._cached_view)
        cls.set_uniform_mat4(-2, 'projection', cls._cached_proj)

        for entity_id in entities:
            entity = cls.registered_entities.get(entity_id)
            if entity is None:
                continue
            model = calculate_entity_model(
                SceneManager.GetEntityTransform(entity_id)
            )
            # pick: 使用 entity_id 作为唯一颜色
            loc_model = gl.glGetUniformLocation(cls._prog_pick, 'model')
            if loc_model >= 0:
                gl.glUniformMatrix4fv(
                    loc_model, 1, gl.GL_FALSE,
                    np.ascontiguousarray(np.array(model, dtype=np.float32))
                )
            loc_id = gl.glGetUniformLocation(cls._prog_pick, 'uPickID')
            if loc_id >= 0:
                gl.glUniform1f(loc_id, float(entity_id))

            gl.glBindVertexArray(entity.vao)
            mesh_data = cls.registered_meshes[entity.mesh_id]
            gl.glDrawElements(
                gl.GL_TRIANGLES, mesh_data.elements_count,
                gl.GL_UNSIGNED_INT, None
            )
            gl.glBindVertexArray(0)

        gl.glFinish()
        px = max(0, min(int(round(sx)), cls.viewport_width - 1))
        py = max(0, min(int(round(sy)), cls.viewport_height - 1))
        pixel = (gl.GLfloat * 4)()
        gl.glReadPixels(
            px, cls.viewport_height - 1 - py,
            1, 1, gl.GL_RGBA, gl.GL_FLOAT, pixel
        )
        eid = int(pixel[0] * 255.0 + 0.5)
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, 0)
        return eid if eid >= 1 else -1

    # ════════════════════════════════════════════════════════════
    # FBO 管线 (内部)
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _RenderFBOFrame(
        cls,
        view: np.ndarray,
        proj: np.ndarray
    ) -> None:
        """FBO 管线完整帧渲染。

        1. Scene Pass   → scene FBO: 实体 + stencil 标记
        2. Outline Pass → scene FBO: stencil NOTEQUAL 轮廓
        3. Overlay Callbacks → scene FBO
        4. Registered Overlays → scene FBO
        """
        # ── 确保 FBO 已创建 ──
        if cls._fbo_scene == 0:
            cls._InitFBOPipeline(cls.viewport_width, cls.viewport_height)

        # ══════════════════════════════════════════════════
        # 1. Scene Pass → scene FBO
        # ══════════════════════════════════════════════════
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, cls._fbo_scene)
        gl.glViewport(0, 0, cls.viewport_width, cls.viewport_height)
        gl.glClearColor(0.2, 0.2, 0.2, 1.0)
        gl.glClear(
            gl.GL_COLOR_BUFFER_BIT
            | gl.GL_DEPTH_BUFFER_BIT
            | gl.GL_STENCIL_BUFFER_BIT
        )

        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glDepthFunc(gl.GL_LEQUAL)
        gl.glDepthMask(gl.GL_TRUE)

        # 开启 stencil: always pass, 通过 depth test 时 replace
        gl.glEnable(gl.GL_STENCIL_TEST)
        gl.glStencilOp(gl.GL_KEEP, gl.GL_KEEP, gl.GL_REPLACE)

        for entity_id in SceneManager.GetRenderableEntities():
            entity = cls.registered_entities.get(entity_id)
            if entity is None:
                continue
            program = cls.registered_shaders[entity.shader_id].program

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

            # ── Stencil: 被选中实体写入 stencil=1 ──
            is_selected = entity_id in cls._outline_selected_ids
            if is_selected:
                gl.glStencilFunc(gl.GL_ALWAYS, 1, 0xFF)
                gl.glStencilMask(0xFF)
            else:
                gl.glStencilMask(0x00)

            # ── 绘制 ──
            gl.glBindVertexArray(entity.vao)
            mesh_data = cls.registered_meshes[entity.mesh_id]
            gl.glDrawElements(
                gl.GL_TRIANGLES, mesh_data.elements_count,
                gl.GL_UNSIGNED_INT, None
            )
            gl.glBindVertexArray(0)

        # ══════════════════════════════════════════════════
        # 2. Outline Pass → scene FBO (stencil NOTEQUAL)
        # ══════════════════════════════════════════════════
        if cls._outline_selected_ids:
            gl.glUseProgram(cls._prog_outline)

            gl.glStencilFunc(gl.GL_NOTEQUAL, 1, 0xFF)
            gl.glStencilMask(0x00)
            gl.glStencilOp(gl.GL_KEEP, gl.GL_KEEP, gl.GL_KEEP)
            gl.glDepthMask(gl.GL_FALSE)

            if cls._outline_xray:
                gl.glDisable(gl.GL_DEPTH_TEST)
            else:
                gl.glEnable(gl.GL_DEPTH_TEST)
                gl.glDepthFunc(gl.GL_LEQUAL)

            cls.set_uniform_mat4(-1, 'view', view)
            cls.set_uniform_mat4(-1, 'projection', proj)
            loc_color = gl.glGetUniformLocation(
                cls._prog_outline, 'uOutlineColor'
            )
            if loc_color >= 0:
                gl.glUniform3f(loc_color, *cls._outline_color)

            for entity_id in SceneManager.GetRenderableEntities():
                if entity_id not in cls._outline_selected_ids:
                    continue
                entity = cls.registered_entities.get(entity_id)
                if entity is None:
                    continue
                model = calculate_entity_model(
                    SceneManager.GetEntityTransform(entity_id)
                )
                loc_model = gl.glGetUniformLocation(
                    cls._prog_outline, 'model'
                )
                if loc_model >= 0:
                    gl.glUniformMatrix4fv(
                        loc_model, 1, gl.GL_FALSE,
                        np.ascontiguousarray(
                            np.array(model, dtype=np.float32)
                        )
                    )
                loc_scale = gl.glGetUniformLocation(
                    cls._prog_outline, 'uOutlineScale'
                )
                if loc_scale >= 0:
                    gl.glUniform1f(loc_scale, cls._outline_scale)

                gl.glBindVertexArray(entity.vao)
                mesh_data = cls.registered_meshes[entity.mesh_id]
                gl.glDrawElements(
                    gl.GL_TRIANGLES, mesh_data.elements_count,
                    gl.GL_UNSIGNED_INT, None
                )
                gl.glBindVertexArray(0)

        # ── 恢复 stencil / depth 状态 ──
        gl.glStencilMask(0xFF)
        gl.glStencilFunc(gl.GL_ALWAYS, 0, 0xFF)
        gl.glDisable(gl.GL_STENCIL_TEST)
        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glDepthMask(gl.GL_TRUE)

        # ══════════════════════════════════════════════════
        # 3. Overlay Callbacks + Registered Overlays
        # ══════════════════════════════════════════════════
        cls._render_overlays(view, proj)
        cls._draw_registered_overlays(view, proj)

    @classmethod
    def _BlitSceneToScreen(cls) -> None:
        """Blit scene FBO 颜色纹理到默认帧缓冲。"""
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, 0)
        gl.glViewport(0, 0, cls.viewport_width, cls.viewport_height)
        gl.glClearColor(0, 0, 0, 1)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)
        gl.glDisable(gl.GL_DEPTH_TEST)

        gl.glUseProgram(cls._prog_blit)
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, cls._fbo_scene_color)
        loc_tex = gl.glGetUniformLocation(cls._prog_blit, 'uScreenTex')
        if loc_tex >= 0:
            gl.glUniform1i(loc_tex, 0)
        gl.glBindVertexArray(cls._vao_blit)
        gl.glDrawArrays(gl.GL_TRIANGLE_STRIP, 0, 4)
        gl.glBindVertexArray(0)

    @classmethod
    def _RenderEntities(
        cls,
        view: np.ndarray,
        proj: np.ndarray
    ) -> None:
        """默认管线: 直接渲染所有实体到当前绑定的帧缓冲 (无 FBO, 无 stencil)。"""
        for entity_id in SceneManager.GetRenderableEntities():
            entity = cls.registered_entities.get(entity_id)
            if entity is None:
                continue
            program = cls.registered_shaders[entity.shader_id].program

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

    # ════════════════════════════════════════════════════════════
    # FBO 管理 (内部)
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _InitFBOPipeline(
        cls,
        w: int,
        h: int
    ) -> None:
        """创建 FBO 资源 (scene FBO + pick FBO)。"""
        cls._DeleteFBOPipeline()

        # ── Scene FBO: depth24 + stencil8 ──
        cls._fbo_scene_color = gl.glGenTextures(1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, cls._fbo_scene_color)
        gl.glTexImage2D(
            gl.GL_TEXTURE_2D, 0, gl.GL_RGBA8, w, h, 0,
            gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, None
        )
        gl.glTexParameteri(
            gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_NEAREST
        )
        gl.glTexParameteri(
            gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST
        )

        cls._fbo_scene_ds = gl.glGenRenderbuffers(1)
        gl.glBindRenderbuffer(gl.GL_RENDERBUFFER, cls._fbo_scene_ds)
        gl.glRenderbufferStorage(
            gl.GL_RENDERBUFFER, gl.GL_DEPTH24_STENCIL8, w, h
        )

        cls._fbo_scene = gl.glGenFramebuffers(1)
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, cls._fbo_scene)
        gl.glFramebufferTexture2D(
            gl.GL_FRAMEBUFFER, gl.GL_COLOR_ATTACHMENT0,
            gl.GL_TEXTURE_2D, cls._fbo_scene_color, 0
        )
        gl.glFramebufferRenderbuffer(
            gl.GL_FRAMEBUFFER, gl.GL_DEPTH_STENCIL_ATTACHMENT,
            gl.GL_RENDERBUFFER, cls._fbo_scene_ds
        )
        if gl.glCheckFramebufferStatus(
            gl.GL_FRAMEBUFFER
        ) != gl.GL_FRAMEBUFFER_COMPLETE:
            raise RuntimeError("Scene FBO incomplete")

        # ── Pick FBO: depth24 ──
        cls._fbo_pick_color = gl.glGenTextures(1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, cls._fbo_pick_color)
        gl.glTexImage2D(
            gl.GL_TEXTURE_2D, 0, gl.GL_RGBA8, w, h, 0,
            gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, None
        )
        gl.glTexParameteri(
            gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_NEAREST
        )
        gl.glTexParameteri(
            gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST
        )

        cls._fbo_pick_depth = gl.glGenRenderbuffers(1)
        gl.glBindRenderbuffer(gl.GL_RENDERBUFFER, cls._fbo_pick_depth)
        gl.glRenderbufferStorage(
            gl.GL_RENDERBUFFER, gl.GL_DEPTH_COMPONENT24, w, h
        )

        cls._fbo_pick = gl.glGenFramebuffers(1)
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, cls._fbo_pick)
        gl.glFramebufferTexture2D(
            gl.GL_FRAMEBUFFER, gl.GL_COLOR_ATTACHMENT0,
            gl.GL_TEXTURE_2D, cls._fbo_pick_color, 0
        )
        gl.glFramebufferRenderbuffer(
            gl.GL_FRAMEBUFFER, gl.GL_DEPTH_ATTACHMENT,
            gl.GL_RENDERBUFFER, cls._fbo_pick_depth
        )
        if gl.glCheckFramebufferStatus(
            gl.GL_FRAMEBUFFER
        ) != gl.GL_FRAMEBUFFER_COMPLETE:
            raise RuntimeError("Pick FBO incomplete")

        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, 0)
        print(
            f"[openGLRenderer] FBO pipeline initialized "
            f"({w}×{h}) — scene(d24s8) + pick(d24)"
        )

    @classmethod
    def _RebuildFBOs(
        cls,
        w: int,
        h: int
    ) -> None:
        """重建 FBO (窗口 resize 时调用)。"""
        cls._DeleteFBOPipeline()
        cls._InitFBOPipeline(w, h)

    @classmethod
    def _DeleteFBOPipeline(cls) -> None:
        """释放 FBO 资源。"""
        if cls._fbo_scene:
            gl.glDeleteFramebuffers(1, [cls._fbo_scene])
            cls._fbo_scene = 0
        if cls._fbo_scene_color:
            gl.glDeleteTextures(1, [cls._fbo_scene_color])
            cls._fbo_scene_color = 0
        if cls._fbo_scene_ds:
            gl.glDeleteRenderbuffers(1, [cls._fbo_scene_ds])
            cls._fbo_scene_ds = 0
        if cls._fbo_pick:
            gl.glDeleteFramebuffers(1, [cls._fbo_pick])
            cls._fbo_pick = 0
        if cls._fbo_pick_color:
            gl.glDeleteTextures(1, [cls._fbo_pick_color])
            cls._fbo_pick_color = 0
        if cls._fbo_pick_depth:
            gl.glDeleteRenderbuffers(1, [cls._fbo_pick_depth])
            cls._fbo_pick_depth = 0

    # ════════════════════════════════════════════════════════════
    # 着色器编译辅助 (内部)
    # ════════════════════════════════════════════════════════════

    @staticmethod
    def _compile_internal_program(
        vs_src: str,
        fs_src: str
    ) -> int:
        """编译编辑器内部着色器程序 (不走 ResourceManager)。

        与 OpenGLResourceManager._compile_program 等价,
        但用于编辑器专属着色器 (轮廓 / 拾取 / Blit)。

        Args:
            vs_src: GLSL 顶点着色器源码
            fs_src: GLSL 片段着色器源码

        Returns:
            GLuint 着色器程序句柄
        """
        # ── 编译顶点着色器 ──
        vs = gl.glCreateShader(gl.GL_VERTEX_SHADER)
        gl.glShaderSource(vs, vs_src)
        gl.glCompileShader(vs)
        if not gl.glGetShaderiv(vs, gl.GL_COMPILE_STATUS):
            log = gl.glGetShaderInfoLog(vs).decode(errors='replace')
            gl.glDeleteShader(vs)
            raise RuntimeError(
                f"Internal vertex shader compilation failed:\n{log}"
            )

        # ── 编译片段着色器 ──
        fs = gl.glCreateShader(gl.GL_FRAGMENT_SHADER)
        gl.glShaderSource(fs, fs_src)
        gl.glCompileShader(fs)
        if not gl.glGetShaderiv(fs, gl.GL_COMPILE_STATUS):
            log = gl.glGetShaderInfoLog(fs).decode(errors='replace')
            gl.glDeleteShader(vs)
            gl.glDeleteShader(fs)
            raise RuntimeError(
                f"Internal fragment shader compilation failed:\n{log}"
            )

        # ── 链接程序 ──
        program = gl.glCreateProgram()
        gl.glAttachShader(program, vs)
        gl.glAttachShader(program, fs)
        gl.glLinkProgram(program)
        if not gl.glGetProgramiv(program, gl.GL_LINK_STATUS):
            log = gl.glGetProgramInfoLog(program).decode(errors='replace')
            gl.glDeleteShader(vs)
            gl.glDeleteShader(fs)
            gl.glDeleteProgram(program)
            raise RuntimeError(
                f"Internal shader program linking failed:\n{log}"
            )

        gl.glDeleteShader(vs)
        gl.glDeleteShader(fs)
        return program

    @staticmethod
    def _create_fullscreen_quad() -> int:
        """创建全屏四边形 VAO (用于 Blit)。

        顶点: [-1,-1] [1,-1] [-1,1] [1,1] → triangle strip
        """
        verts = np.array(
            [-1, -1, 1, -1, -1, 1, 1, 1], dtype=np.float32
        )
        vao = gl.glGenVertexArrays(1)
        vbo = gl.glGenBuffers(1)
        gl.glBindVertexArray(vao)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, vbo)
        gl.glBufferData(
            gl.GL_ARRAY_BUFFER, verts.nbytes,
            verts.tobytes(), gl.GL_STATIC_DRAW
        )
        gl.glEnableVertexAttribArray(0)
        gl.glVertexAttribPointer(
            0, 2, gl.GL_FLOAT, gl.GL_FALSE, 0, ctypes.c_void_p(0)
        )
        gl.glBindVertexArray(0)
        return vao

    # ════════════════════════════════════════════════════════════
    # Uniform 辅助 (轮廓 / 拾取 shader 用)
    # ════════════════════════════════════════════════════════════
    # 注: set_uniform_mat4 需要 shader_id 参数, 但内部着色器不走
    #     ResourceManager 注册表。使用 sentinel shader_id (-1=outline,
    #     -2=pick) 时直接操作 program handle。

    @classmethod
    def set_uniform_mat4(
        cls,
        shader_id: int,
        name: str,
        matrix: np.ndarray
    ) -> None:
        """设置 mat4 uniform (覆盖基类, 支持内部着色器)。"""
        # ── 内部着色器: 直接使用 program handle ──
        if shader_id == -1:
            prog = cls._prog_outline
        elif shader_id == -2:
            prog = cls._prog_pick
        else:
            # 走基类 (ResourceManager 注册的着色器)
            super().set_uniform_mat4(shader_id, name, matrix)
            return

        loc = gl.glGetUniformLocation(prog, name)
        if loc >= 0:
            data = np.ascontiguousarray(matrix.astype(np.float32))
            gl.glUniformMatrix4fv(loc, 1, gl.GL_FALSE, data)
