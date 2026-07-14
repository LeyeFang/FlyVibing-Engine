"""
OpenGLEntities — PyOpenGL 实体渲染器 (组合到 OpenGLRenderer)。

职责:
  - 遍历可渲染实体并提交 GL 绘制命令
  - 支持 FBO 重定向 (_scene_fbo_override)
  - 支持 Stencil 注入 (_outline_selected_ids → 写 stencil=1)

设计:
  - 组合模式: 通过 _renderer 回引用访问资源注册表
  - 不再通过 MRO 继承 — 避免 classmethod/instancemethod 冲突
"""

from __future__ import annotations
import numpy as np
from OpenGL import GL as gl

from Application.Core.Renderer.OpenGL.OpenGLUtils import OpenGLUtils
from Application.Resource.ResourceManager import ResourceManager
from Application.Core.Scene.SceneManager import SceneManager


class OpenGLEntities:
    """PyOpenGL 实体渲染器 — 核心实体绘制管线。"""

    def __init__(self, renderer) -> None:
        self._renderer = renderer

    def render_entities(
        self,
        view: np.ndarray,
        proj: np.ndarray,
    ) -> None:
        """渲染所有实体 — 支持 FBO 重定向 + stencil 注入。"""
        r = self._renderer
        target_fbo = r._scene_fbo_override
        if target_fbo:
            gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, target_fbo)
            gl.glViewport(0, 0, r.viewport_width, r.viewport_height)

        has_outline = bool(r._outline_selected_ids)
        last_program: int = 0  # ★ 缓存最后使用的 shader program，避免冗余切换

        # ── 收集可渲染实体 ──
        visible_entities: list[tuple[int, object]] = []
        for entity_id in r._resources._visible_entities:
            entity = r.registered_entities.get(entity_id)
            if entity is None:
                r._resources._visible_entities.discard(entity_id)
                continue
            if not entity.render_visible:
                continue
            if entity.shader_id not in r.registered_shaders:
                continue
            if entity.mesh_id not in r.registered_meshes:
                continue
            visible_entities.append((entity_id, entity))

        # ★ 按 shader_id → material_id 排序，最大化 GPU 状态复用
        visible_entities.sort(key=lambda item: (item[1].shader_id, item[1].material_id))

        for entity_id, entity in visible_entities:

            if has_outline:
                if entity_id in r._outline_selected_ids:
                    gl.glStencilFunc(gl.GL_ALWAYS, 1, 0xFF)
                    gl.glStencilMask(0xFF)
                else:
                    gl.glStencilMask(0x00)

            # ★ 冗余消除: 只在 shader 变化时切换 program
            program = r.registered_shaders[entity.shader_id].program
            if program != last_program:
                gl.glUseProgram(program)
                last_program = program
                # ★ 冗余消除: view / proj 全帧不变，仅在 shader 切换后设置一次
                OpenGLUtils.set_uniform_mat4(
                    r.registered_shaders, entity.shader_id, 'view', view)
                OpenGLUtils.set_uniform_mat4(
                    r.registered_shaders, entity.shader_id, 'projection', proj)

            model = self._renderer.engine.scene.GetEntityModelMatrix(entity_id)
            OpenGLUtils.set_uniform_mat4(
                r.registered_shaders, entity.shader_id, 'model', model)
            if entity.texture_id and entity.texture_id > 0:
                tex_data = r.registered_textures.get(entity.texture_id)
                if tex_data and tex_data.gl_handle:
                    gl.glActiveTexture(gl.GL_TEXTURE0)
                    gl.glBindTexture(gl.GL_TEXTURE_2D, tex_data.gl_handle)
                    OpenGLUtils.set_uniform_int(
                        r.registered_shaders, entity.shader_id, 'uTexture', 0)
            try:
                material = ResourceManager.GetMaterial(entity.material_id)
            except Exception:
                material = None
            if material is not None:
                for u_name, u_value in material.uniforms_data.items():
                    if u_name in ('model', 'view', 'projection'):
                        continue
                    OpenGLUtils.set_uniform_value(
                        r.registered_shaders, entity.shader_id, u_name, u_value)
            gl.glBindVertexArray(entity.vao)
            mesh_data = r.registered_meshes[entity.mesh_id]
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
