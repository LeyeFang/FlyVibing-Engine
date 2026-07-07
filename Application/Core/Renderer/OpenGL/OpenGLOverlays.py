"""
OpenGLOverlays — PyOpenGL 叠加层渲染器 (Mixin, 通过 MRO 访问资源)。

职责:
  - 遍历已注册的 overlay drawable 并提交 GL 绘制命令
  - 管理 overlay 渲染时的 GL 状态 (深度/混合/面剔除/线宽)

设计:
  - Mixin 模式: 覆写 Renderer._render_overlay_drawables() 的 no-op
  - 通过 cls._overlay_gpu_resources 访问资源 (由 OpenGLResourceManager 提供)
  - 须置于 OpenGLResourceManager 之后、Renderer 之前的 MRO 位置
"""

from __future__ import annotations
import numpy as np
from OpenGL import GL as gl


class OpenGLOverlays:
    """PyOpenGL 叠加层渲染器 — 编辑器的 Grid/Gizmo 等 overlay 绘制。"""

    @classmethod
    def _render_overlay_drawables(
        cls,
        view: np.ndarray,
        proj: np.ndarray,
        layer: int = -1,
    ) -> None:
        """遍历指定层级的 overlay drawable 并提交 GL 绘制命令。

        Args:
            view: 4×4 视图矩阵
            proj: 4×4 投影矩阵
            layer: -1=全绘制, 0=scene (Grid), 1=screen (Gizmo)
        """
        vp = gl.glGetIntegerv(gl.GL_VIEWPORT)
        vp_w, vp_h = vp[2], vp[3]
        # Layer 1 的 depth 清理在 _render_all_overlays 中由 _clear_depth_for_overlays 完成
        for _key, gpu in cls._overlay_gpu_resources.items():
            if layer >= 0 and getattr(gpu, 'render_layer', 0) != layer:
                if layer >= 0:
                    pass  # filtered
                continue
            gl.glUseProgram(gpu.program)
            if gpu.ignore_scene_matrices:
                # NDC rendering: custom model matrix from callback
                # model_matrix_cb returns numpy ndarray (Type B) -> GL_TRUE
                if gpu.model_matrix_cb:
                    model = gpu.model_matrix_cb(vp_w, vp_h)
                    loc = gl.glGetUniformLocation(gpu.program, 'uModel')
                    if loc >= 0:
                        gl.glUniformMatrix4fv(
                            loc,
                            1,
                            gl.GL_TRUE,  # numpy ndarray -> GL_TRUE
                            np.ascontiguousarray(model.astype('float32')))
                    # 设置 uProj (aspect 矫正，新版本 model 不含 aspect)
                    from Application.Core.Math.ViewGizmo import compute_ortho_proj
                    op = compute_ortho_proj(vp_w, vp_h)
                    loc_proj = gl.glGetUniformLocation(gpu.program, 'uProj')
                    if loc_proj >= 0:
                        gl.glUniformMatrix4fv(
                            loc_proj,
                            1,
                            gl.GL_TRUE,
                            np.ascontiguousarray(op.astype('float32')))
            else:
                # Scene rendering: use engine view/proj matrices
                # view/proj come from pyrr (Type A) -> GL_FALSE
                loc_view = gl.glGetUniformLocation(gpu.program, 'uView')
                loc_proj = gl.glGetUniformLocation(gpu.program, 'uProj')
                if loc_view >= 0:
                    gl.glUniformMatrix4fv(
                        loc_view,
                        1,
                        gl.GL_FALSE,  # pyrr matrix -> GL_FALSE
                        np.ascontiguousarray(view.astype('float32')))
                if loc_proj >= 0:
                    gl.glUniformMatrix4fv(
                        loc_proj,
                        1,
                        gl.GL_FALSE,  # pyrr matrix -> GL_FALSE
                        np.ascontiguousarray(proj.astype('float32')))
            # ── 纹理 ──
            if gpu.texture:
                gl.glActiveTexture(gl.GL_TEXTURE0)
                gl.glBindTexture(gl.GL_TEXTURE_2D, gpu.texture)
                loc_tex = gl.glGetUniformLocation(gpu.program, gpu.texture_uniform or 'uLetterTex')
                if loc_tex >= 0:
                    gl.glUniform1i(loc_tex, 0)
            # ── 声明式 uniform 解析 (替代 uniforms_setup 回调) ──
            #    overlay.uniforms = {'uColor': np.array(...), 'uFadeCenter': 'camera.fade_center', ...}
            #    渲染器基类 _resolve_overlay_uniforms 将动态源解析为当前帧值
            if gpu.uniforms:
                resolved = cls._resolve_overlay_uniforms(gpu.uniforms)
                for uname, uval in resolved.items():
                    loc = gl.glGetUniformLocation(gpu.program, uname)
                    if loc < 0:
                        continue
                    if uval.size == 16:       # mat4
                        gl.glUniformMatrix4fv(loc, 1, gl.GL_FALSE,
                            np.ascontiguousarray(uval.astype('float32')))
                    elif uval.size == 4:      # vec4
                        gl.glUniform4fv(loc, 1, uval.astype('float32'))
                    elif uval.size == 3:      # vec3
                        gl.glUniform3fv(loc, 1, uval.astype('float32'))
                    elif uval.size == 2:      # vec2
                        gl.glUniform2fv(loc, 1, uval.astype('float32'))
                    elif uval.size == 1:      # float / int
                        gl.glUniform1fv(loc, 1, uval.astype('float32'))
            # uniforms_setup 保留兼容 (旧 overlay 仍可用)
            if gpu.uniforms_setup:
                gpu.uniforms_setup(gpu.program)
            # ── 深度测试 ──
            if gpu.depth_test:
                gl.glEnable(gl.GL_DEPTH_TEST)
                gl.glDepthFunc(gl.GL_LESS)
            else:
                gl.glDisable(gl.GL_DEPTH_TEST)
            # ── 面剔除 ──
            if gpu.cull_face:
                gl.glEnable(gl.GL_CULL_FACE)
                gl.glCullFace(gl.GL_BACK)
                gl.glFrontFace(gl.GL_CCW)
            else:
                gl.glDisable(gl.GL_CULL_FACE)
            # ── 混合 ──
            if gpu.blend:
                gl.glEnable(gl.GL_BLEND)
                gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
            else:
                gl.glDisable(gl.GL_BLEND)
            # ── 线宽 ──
            if gpu.draw_mode == gl.GL_LINES:
                gl.glLineWidth(min(gpu.line_width, 1.0))
            # ── 绘制 ──
            gl.glBindVertexArray(gpu.vao)
            gl.glDrawElements(
                gpu.draw_mode,
                gpu.elements_count,
                gl.GL_UNSIGNED_INT,
                None)
            gl.glBindVertexArray(0)
            if gpu.draw_mode == gl.GL_LINES:
                gl.glLineWidth(1.0)
        # ── 恢复状态 ──
        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glDepthFunc(gl.GL_LESS)
        gl.glDisable(gl.GL_BLEND)
        gl.glDisable(gl.GL_CULL_FACE)
