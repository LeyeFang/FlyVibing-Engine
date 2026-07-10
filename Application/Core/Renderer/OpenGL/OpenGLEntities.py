"""
OpenGLEntities — PyOpenGL 实体渲染器 (Mixin, 通过 MRO 访问资源注册表)。

职责:
  - 遍历可渲染实体并提交 GL 绘制命令
  - 支持 FBO 重定向 (self._scene_fbo_override)
  - 支持 Stencil 注入 (self._outline_selected_ids → 写 stencil=1)

设计:
  - Mixin 模式: 通过 self.registered_entities/shaders/meshes/textures 访问资源
  - 须置于 OpenGLResourceManager 之后的 MRO 位置
  - self._scene_fbo_override / self._outline_selected_ids 由 OpenGLRenderer 提供
"""

from __future__ import annotations
import numpy as np
from OpenGL import GL as gl

from Application.Core.Renderer.OpenGL.OpenGLUtils import OpenGLUtils
from Application.Resource.ResourceManager import ResourceManager
from Application.Core.Scene.SceneManager import SceneManager


class OpenGLEntities:
    """PyOpenGL 实体渲染器 — 核心实体绘制管线。"""

    def _RenderEntities(
        self,
        view: np.ndarray,
        proj: np.ndarray,
    ) -> None:
        """渲染所有实体 — 支持 FBO 重定向 + stencil 注入 (通过 MRO 访问 cls 状态)。"""
        # ── FBO 重定向 (由 pre-overlay 控制) ──
        target_fbo = self._scene_fbo_override
        if target_fbo:
            gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, target_fbo)
            gl.glViewport(0, 0, self.viewport_width, self.viewport_height)

        has_outline = bool(self._outline_selected_ids)

        for entity_id in SceneManager.GetRenderableEntities():
            entity = self.registered_entities.get(entity_id)
            if entity is None:
                continue

            # ★ 资源保护: 跳过已失效的实体（shader/mesh 被删除后残留的缓存）
            if entity.shader_id not in self.registered_shaders:
                continue
            if entity.mesh_id not in self.registered_meshes:
                continue

            # ── Stencil 写入: 被选实体写 stencil=1 (由 OutlineOverlay 注入) ──
            if has_outline:
                if entity_id in self._outline_selected_ids:
                    gl.glStencilFunc(gl.GL_ALWAYS, 1, 0xFF)
                    gl.glStencilMask(0xFF)
                else:
                    gl.glStencilMask(0x00)

            program = self.registered_shaders[entity.shader_id].program
            # ── 激活 shader ──
            gl.glUseProgram(program)
            # ── MVP 矩阵 ──
            model = SceneManager.GetEntityModelMatrix(entity_id)
            OpenGLUtils.set_uniform_mat4(
                self.registered_shaders, entity.shader_id, 'model', model)
            OpenGLUtils.set_uniform_mat4(
                self.registered_shaders, entity.shader_id, 'view', view)
            OpenGLUtils.set_uniform_mat4(
                self.registered_shaders, entity.shader_id, 'projection', proj)
            # ── 纹理 ──
            if entity.texture_id and entity.texture_id > 0:
                tex_data = self.registered_textures.get(entity.texture_id)
                if tex_data and tex_data.gl_handle:
                    gl.glActiveTexture(gl.GL_TEXTURE0)
                    gl.glBindTexture(gl.GL_TEXTURE_2D, tex_data.gl_handle)
                    OpenGLUtils.set_uniform_int(
                        self.registered_shaders, entity.shader_id, 'uTexture', 0)
            # ── 材质 uniform ──
            try:
                material = ResourceManager.GetMaterial(entity.material_id)
            except Exception:
                material = None
            if material is not None:
                for u_name, u_value in material.uniforms_data.items():
                    if u_name in ('model', 'view', 'projection'):
                        continue
                    OpenGLUtils.set_uniform_value(
                        self.registered_shaders, entity.shader_id, u_name, u_value)
            # ── 绘制 ──
            gl.glBindVertexArray(entity.vao)
            mesh_data = self.registered_meshes[entity.mesh_id]
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
