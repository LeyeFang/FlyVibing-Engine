"""
OpenGLPostProcess — PyOpenGL 屏幕空间后处理管线 (Mixin)。

职责:
  - Highlight 效果: MRT FBO 管理 + 边缘检测 shader + 全屏四边形
  - 管理后处理专用的 GPU 资源 (不与 entity/overlay 共享)

管线 (每帧 _render_highlight):
  Pass 1 — Scene MRT:  遍历实体 → MRT FBO (color + entity_id + depth)
  Pass 2 — Edge Detect: 读 id_tex → Roberts Cross 边缘检测 → edge_tex (R8)
  Pass 3 — Composite:   读 edge_tex → alpha blend 叠加到默认帧缓冲

MRO 位置:
  openGLRenderer → ... → OpenGLOverlayRenderer → OpenGLPostProcess → Renderer → ...
  (需要 MRO 已提供 cls.registered_entities / cls.registered_meshes / cls.registered_textures)
"""

from __future__ import annotations
import ctypes
import numpy as np
from OpenGL import GL as gl

from Application.Core.Renderer.PostProcess import PostProcess, HighlightEffectConfig


class OpenGLPostProcess(PostProcess):
    """PyOpenGL 后处理管线 — 当前支持 Highlight 效果。"""

    # ════════════════════════════════════════════════════════════
    # Highlight GPU 资源
    # ════════════════════════════════════════════════════════════

    # ── MRT FBO ──
    _pp_fbo: int = 0
    _pp_color_tex: int = 0       # GL_RGBA8  — attachment 0
    _pp_id_tex: int = 0          # GL_R32UI  — attachment 1
    _pp_ds_rbo: int = 0          # GL_DEPTH_COMPONENT24
    _pp_fbo_w: int = 0
    _pp_fbo_h: int = 0

    # ── Edge FBO (持久化, resize 时重建) ──
    _pp_edge_tex: int = 0        # GL_R8
    _pp_edge_fbo: int = 0

    # ── Shader Programs ──
    _pp_mrt_prog: int = 0        # MRT 场景着色器
    _pp_edge_prog: int = 0       # 边缘检测着色器
    _pp_composite_prog: int = 0  # 合成着色器

    # ── 全屏四边形 ──
    _pp_quad_vao: int = 0

    # ════════════════════════════════════════════════════════
    # PostProcess 接口实现
    # ════════════════════════════════════════════════════════

    @classmethod
    def _init_highlight(cls, config: HighlightEffectConfig) -> None:
        """编译 shader → 创建全屏四边形 → 初始化 FBO。"""
        cls._compile_shaders()
        cls._create_quad()
        cls._ensure_fbo(
            cls.viewport_width, cls.viewport_height)

    @classmethod
    def _release_highlight(cls) -> None:
        """释放所有 highlight GPU 资源。"""
        cls._release_fbo()
        cls._release_edge_fbo()
        for prog in (cls._pp_mrt_prog, cls._pp_edge_prog, cls._pp_composite_prog):
            if prog:
                gl.glDeleteProgram(prog)
        cls._pp_mrt_prog = cls._pp_edge_prog = cls._pp_composite_prog = 0
        if cls._pp_quad_vao:
            gl.glDeleteVertexArrays(1, [cls._pp_quad_vao])
            cls._pp_quad_vao = 0

    @classmethod
    def _render_highlight(cls, view: np.ndarray, proj: np.ndarray) -> None:
        """Pass 1 MRT → Pass 2 Edge → Pass 3 Composite。"""
        vp_w, vp_h = cls.viewport_width, cls.viewport_height
        if vp_w == 0 or vp_h == 0:
            return

        # ── 确保 FBO 尺寸匹配 (resize 时惰性重建) ──
        cls._ensure_fbo(vp_w, vp_h)
        cls._ensure_edge_fbo(vp_w, vp_h)

        # ══════════════════════════════════════════════════
        # Pass 1: MRT Scene — 渲染实体到 color + id
        # ══════════════════════════════════════════════════
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, cls._pp_fbo)
        gl.glViewport(0, 0, vp_w, vp_h)

        # attachment 0 (rgba8) + attachment 1 (r32ui) + depth
        gl.glClearColor(0.2, 0.2, 0.2, 1.0)
        gl.glClearBufferuiv(gl.GL_COLOR, 1, (ctypes.c_uint * 4)(0, 0, 0, 0))
        gl.glClearBufferfv(gl.GL_COLOR, 0,
                           (ctypes.c_float * 4)(0.2, 0.2, 0.2, 1.0))
        gl.glClear(gl.GL_DEPTH_BUFFER_BIT)
        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glDepthFunc(gl.GL_LESS)
        gl.glDepthMask(gl.GL_TRUE)
        gl.glDisable(gl.GL_BLEND)

        gl.glUseProgram(cls._pp_mrt_prog)
        loc_model = gl.glGetUniformLocation(cls._pp_mrt_prog, 'model')
        loc_view = gl.glGetUniformLocation(cls._pp_mrt_prog, 'view')
        loc_proj = gl.glGetUniformLocation(cls._pp_mrt_prog, 'projection')
        loc_tex = gl.glGetUniformLocation(cls._pp_mrt_prog, 'uTexture')
        loc_oid = gl.glGetUniformLocation(cls._pp_mrt_prog, 'uObjID')

        view_f32 = np.ascontiguousarray(view.astype('float32'))
        proj_f32 = np.ascontiguousarray(proj.astype('float32'))
        if loc_view >= 0:
            gl.glUniformMatrix4fv(loc_view, 1, gl.GL_FALSE, view_f32)
        if loc_proj >= 0:
            gl.glUniformMatrix4fv(loc_proj, 1, gl.GL_FALSE, proj_f32)
        if loc_tex >= 0:
            gl.glUniform1i(loc_tex, 0)

        from Application.Core.Scene.SceneManager import SceneManager

        active_ids = cls._highlight_config.selected_ids if cls._highlight_config else set()

        for eid in SceneManager.GetRenderableEntities():
            entity = cls.registered_entities.get(eid)
            if entity is None:
                continue

            model = SceneManager.GetEntityModelMatrix(eid)
            model_f32 = np.ascontiguousarray(model.astype('float32'))
            if loc_model >= 0:
                gl.glUniformMatrix4fv(loc_model, 1, gl.GL_FALSE, model_f32)

            # 选中实体 ID=1, 未选中=0 (边界仅出现在选中↔背景)
            obj_id = 1 if eid in active_ids else 0
            if loc_oid >= 0:
                gl.glUniform1ui(loc_oid, obj_id)

            gl.glBindVertexArray(entity.vao)
            mesh_data = cls.registered_meshes[entity.mesh_id]
            gl.glDrawElements(gl.GL_TRIANGLES, mesh_data.elements_count,
                              gl.GL_UNSIGNED_INT, None)
            gl.glBindVertexArray(0)

        # ══════════════════════════════════════════════════
        # Pass 2: Edge Detection
        #   读 id_tex → Roberts Cross 边缘检测 → edge_tex (R8)
        # ══════════════════════════════════════════════════
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, cls._pp_edge_fbo)
        gl.glViewport(0, 0, vp_w, vp_h)
        gl.glDisable(gl.GL_DEPTH_TEST)

        gl.glUseProgram(cls._pp_edge_prog)
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, cls._pp_id_tex)

        loc_eid = gl.glGetUniformLocation(cls._pp_edge_prog, 'uIDTex')
        if loc_eid >= 0:
            gl.glUniform1i(loc_eid, 0)
        loc_w = gl.glGetUniformLocation(cls._pp_edge_prog, 'uWidth')
        if loc_w >= 0:
            w_val = cls._highlight_config.width if cls._highlight_config else 3
            gl.glUniform1i(loc_w, w_val)

        gl.glBindVertexArray(cls._pp_quad_vao)
        gl.glDrawArrays(gl.GL_TRIANGLE_STRIP, 0, 4)
        gl.glBindVertexArray(0)

        # ══════════════════════════════════════════════════
        # Pass 3: Composite (alpha-blended)
        #   读 edge_tex → 仅输出轮廓到默认帧缓冲
        # ══════════════════════════════════════════════════
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, 0)
        gl.glViewport(0, 0, vp_w, vp_h)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
        gl.glEnable(gl.GL_BLEND)

        gl.glUseProgram(cls._pp_composite_prog)
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, cls._pp_edge_tex)

        loc_etex = gl.glGetUniformLocation(cls._pp_composite_prog, 'uEdgeTex')
        if loc_etex >= 0:
            gl.glUniform1i(loc_etex, 0)
        loc_oc = gl.glGetUniformLocation(
            cls._pp_composite_prog, 'uOutlineColor')
        if loc_oc >= 0:
            col = cls._highlight_config.color if cls._highlight_config else (
                0.878, 0.416, 0.153)
            gl.glUniform3f(loc_oc, *col)

        gl.glBindVertexArray(cls._pp_quad_vao)
        gl.glDrawArrays(gl.GL_TRIANGLE_STRIP, 0, 4)
        gl.glBindVertexArray(0)
        gl.glDisable(gl.GL_BLEND)

        # 恢复深度测试 (后续 overlay 需要)
        gl.glEnable(gl.GL_DEPTH_TEST)

    @classmethod
    def _update_highlight_params(cls) -> None:
        """参数更新 — 颜色/宽度在每帧 _render_highlight 中动态读取，无需额外操作。"""
        pass

    # ════════════════════════════════════════════════════════
    # Shader 编译
    # ════════════════════════════════════════════════════════

    @classmethod
    def _compile_shaders(cls) -> None:
        """编译 MRT 场景着色器、边缘检测着色器、composite 着色器。"""
        from OpenGL.GL import shaders as gls

        # ── MRT 场景 Vertex ──
        _MRT_VS = '''#version 440 core
layout(location=0) in vec3 aPos;
layout(location=1) in vec2 aTexCoord;
uniform mat4 model, view, projection;
out vec2 TexCoord;
void main() {
    gl_Position = projection * view * model * vec4(aPos, 1.0);
    TexCoord = aTexCoord;
}'''
        # ── MRT 场景 Fragment (输出 color + objID) ──
        _MRT_FS = '''#version 440 core
in vec2 TexCoord;
uniform sampler2D uTexture;
uniform uint uObjID;
layout(location=0) out vec4 outColor;
layout(location=1) out uint outObjID;
void main() {
    outColor = texture(uTexture, TexCoord);
    outObjID = uObjID;
}'''
        cls._pp_mrt_prog = gls.compileProgram(
            gls.compileShader(_MRT_VS, gl.GL_VERTEX_SHADER),
            gls.compileShader(_MRT_FS, gl.GL_FRAGMENT_SHADER),
        )

        # ── 边缘检测 (Roberts cross, 支持可变宽度) ──
        _EDGE_VS = '''#version 440 core
in vec2 aPos;
out vec2 vUV;
void main() {
    gl_Position = vec4(aPos, 0.0, 1.0);
    vUV = aPos * 0.5 + 0.5;
}'''
        _EDGE_FS = '''#version 440 core
in vec2 vUV;
uniform usampler2D uIDTex;
uniform int uWidth;
out float outEdge;
void main() {
    ivec2 tx = ivec2(gl_FragCoord.xy);
    int w = uWidth;
    uint c = texelFetch(uIDTex, tx, 0).r;
    float edge = 0.0;
    for (int dx = -w; dx <= w; dx++) {
        for (int dy = -w; dy <= w; dy++) {
            uint n = texelFetch(uIDTex, tx + ivec2(dx, dy), 0).r;
            if (n != c) { edge = 1.0; }
        }
    }
    outEdge = edge;
}'''
        cls._pp_edge_prog = gls.compileProgram(
            gls.compileShader(_EDGE_VS, gl.GL_VERTEX_SHADER),
            gls.compileShader(_EDGE_FS, gl.GL_FRAGMENT_SHADER),
        )

        # ── Composite ──
        _COMP_VS = '''#version 440 core
in vec2 aPos;
out vec2 vUV;
void main() {
    gl_Position = vec4(aPos, 0.0, 1.0);
    vUV = aPos * 0.5 + 0.5;
}'''
        _COMP_FS = '''#version 440 core
in vec2 vUV;
uniform sampler2D uEdgeTex;
uniform vec3 uOutlineColor;
out vec4 outColor;
void main() {
    float edge = texture(uEdgeTex, vUV).r;
    outColor = vec4(uOutlineColor, edge);
}'''
        cls._pp_composite_prog = gls.compileProgram(
            gls.compileShader(_COMP_VS, gl.GL_VERTEX_SHADER),
            gls.compileShader(_COMP_FS, gl.GL_FRAGMENT_SHADER),
        )

    # ════════════════════════════════════════════════════════
    # 全屏四边形
    # ════════════════════════════════════════════════════════

    @classmethod
    def _create_quad(cls) -> None:
        """创建全屏四边形 VAO (triangle strip)。"""
        from Application.Core.Renderer.VertexLayout import STD_LAYOUT
        verts = np.array([-1, -1, 1, -1, -1, 1, 1, 1], dtype='f4')
        cls._pp_quad_vao = gl.glGenVertexArrays(1)
        vbo = gl.glGenBuffers(1)
        gl.glBindVertexArray(cls._pp_quad_vao)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, vbo)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, verts.nbytes, verts,
                        gl.GL_STATIC_DRAW)
        gl.glEnableVertexAttribArray(0)
        # ★ 使用标准布局
        ql = STD_LAYOUT.SCREEN_QUAD
        loc, size, stride, offset = ql.to_gl_attribs()[0]
        gl.glVertexAttribPointer(loc, size, gl.GL_FLOAT, gl.GL_FALSE, stride,
                                 ctypes.c_void_p(offset))
        gl.glBindVertexArray(0)

    # ════════════════════════════════════════════════════════
    # MRT FBO 管理
    # ════════════════════════════════════════════════════════

    @classmethod
    def _ensure_fbo(cls, w: int, h: int) -> None:
        """确保 MRT FBO 尺寸匹配 (resize 时重建)。"""
        if cls._pp_fbo and cls._pp_fbo_w == w and cls._pp_fbo_h == h:
            return
        cls._release_fbo()

        # Color (RGBA8)
        cls._pp_color_tex = gl.glGenTextures(1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, cls._pp_color_tex)
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA8, w, h, 0,
                        gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, None)
        gl.glTexParameteri(gl.GL_TEXTURE_2D,
                           gl.GL_TEXTURE_MIN_FILTER, gl.GL_NEAREST)
        gl.glTexParameteri(gl.GL_TEXTURE_2D,
                           gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST)

        # Object ID (R32UI)
        cls._pp_id_tex = gl.glGenTextures(1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, cls._pp_id_tex)
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_R32UI, w, h, 0,
                        gl.GL_RED_INTEGER, gl.GL_UNSIGNED_INT, None)
        gl.glTexParameteri(gl.GL_TEXTURE_2D,
                           gl.GL_TEXTURE_MIN_FILTER, gl.GL_NEAREST)
        gl.glTexParameteri(gl.GL_TEXTURE_2D,
                           gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST)

        # Depth (D24)
        cls._pp_ds_rbo = gl.glGenRenderbuffers(1)
        gl.glBindRenderbuffer(gl.GL_RENDERBUFFER, cls._pp_ds_rbo)
        gl.glRenderbufferStorage(
            gl.GL_RENDERBUFFER, gl.GL_DEPTH_COMPONENT24, w, h)

        # FBO
        cls._pp_fbo = gl.glGenFramebuffers(1)
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, cls._pp_fbo)
        gl.glFramebufferTexture2D(gl.GL_FRAMEBUFFER,
                                  gl.GL_COLOR_ATTACHMENT0,
                                  gl.GL_TEXTURE_2D, cls._pp_color_tex, 0)
        gl.glFramebufferTexture2D(gl.GL_FRAMEBUFFER,
                                  gl.GL_COLOR_ATTACHMENT1,
                                  gl.GL_TEXTURE_2D, cls._pp_id_tex, 0)
        gl.glFramebufferRenderbuffer(gl.GL_FRAMEBUFFER,
                                     gl.GL_DEPTH_ATTACHMENT,
                                     gl.GL_RENDERBUFFER, cls._pp_ds_rbo)
        gl.glDrawBuffers(2, [gl.GL_COLOR_ATTACHMENT0,
                         gl.GL_COLOR_ATTACHMENT1])

        if gl.glCheckFramebufferStatus(gl.GL_FRAMEBUFFER) != gl.GL_FRAMEBUFFER_COMPLETE:
            raise RuntimeError("OpenGLPostProcess: MRT FBO incomplete")

        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, 0)
        cls._pp_fbo_w, cls._pp_fbo_h = w, h

    @classmethod
    def _release_fbo(cls) -> None:
        """释放 MRT FBO 及其附件。"""
        if cls._pp_fbo:
            gl.glDeleteFramebuffers(1, [cls._pp_fbo])
            cls._pp_fbo = 0
        if cls._pp_color_tex:
            gl.glDeleteTextures(1, [cls._pp_color_tex])
            cls._pp_color_tex = 0
        if cls._pp_id_tex:
            gl.glDeleteTextures(1, [cls._pp_id_tex])
            cls._pp_id_tex = 0
        if cls._pp_ds_rbo:
            gl.glDeleteRenderbuffers(1, [cls._pp_ds_rbo])
            cls._pp_ds_rbo = 0
        cls._pp_fbo_w = cls._pp_fbo_h = 0

    # ════════════════════════════════════════════════════════
    # Edge FBO 管理 (持久化, 不再每帧创建/销毁)
    # ════════════════════════════════════════════════════════

    @classmethod
    def _ensure_edge_fbo(cls, w: int, h: int) -> None:
        """确保边缘检测 FBO 尺寸匹配。"""
        if cls._pp_edge_fbo and cls._pp_fbo_w == w and cls._pp_fbo_h == h:
            return
        cls._release_edge_fbo()

        cls._pp_edge_tex = gl.glGenTextures(1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, cls._pp_edge_tex)
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_R8, w, h, 0,
                        gl.GL_RED, gl.GL_UNSIGNED_BYTE, None)
        gl.glTexParameteri(gl.GL_TEXTURE_2D,
                           gl.GL_TEXTURE_MIN_FILTER, gl.GL_NEAREST)
        gl.glTexParameteri(gl.GL_TEXTURE_2D,
                           gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST)

        cls._pp_edge_fbo = gl.glGenFramebuffers(1)
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, cls._pp_edge_fbo)
        gl.glFramebufferTexture2D(gl.GL_FRAMEBUFFER,
                                  gl.GL_COLOR_ATTACHMENT0,
                                  gl.GL_TEXTURE_2D, cls._pp_edge_tex, 0)
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, 0)

    @classmethod
    def _release_edge_fbo(cls) -> None:
        """释放边缘检测 FBO 及其纹理。"""
        if cls._pp_edge_fbo:
            gl.glDeleteFramebuffers(1, [cls._pp_edge_fbo])
            cls._pp_edge_fbo = 0
        if cls._pp_edge_tex:
            gl.glDeleteTextures(1, [cls._pp_edge_tex])
            cls._pp_edge_tex = 0
