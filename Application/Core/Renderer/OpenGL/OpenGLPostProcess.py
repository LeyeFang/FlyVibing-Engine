"""
OpenGLPostProcess — PyOpenGL 屏幕空间后处理管线 (组合到 OpenGLRenderer)。

职责:
  - Highlight 效果: MRT FBO 管理 + 边缘检测 shader + 全屏四边形
  - 管理后处理专用的 GPU 资源 (不与 entity/overlay 共享)

设计:
  - 组合模式: 通过 _renderer 回引用访问资源注册表
  - 不再通过 MRO 继承
"""

from __future__ import annotations
import ctypes
import numpy as np
from OpenGL import GL as gl

from Application.Core.Renderer.PostProcess import PostProcess, HighlightEffectConfig


class OpenGLPostProcess(PostProcess):
    """PyOpenGL 后处理管线 — 当前支持 Highlight 效果。"""

    def __init__(self, renderer) -> None:
        super().__init__()
        self._renderer = renderer
        self._pp_fbo: int = 0
        self._pp_color_tex: int = 0
        self._pp_id_tex: int = 0
        self._pp_ds_rbo: int = 0
        self._pp_fbo_w: int = 0
        self._pp_fbo_h: int = 0
        self._pp_edge_tex: int = 0
        self._pp_edge_fbo: int = 0
        self._pp_mrt_prog: int = 0
        self._pp_edge_prog: int = 0
        self._pp_composite_prog: int = 0
        self._pp_quad_vao: int = 0

    # ════════════════════════════════════════════════════════
    # PostProcess 接口实现
    # ════════════════════════════════════════════════════════

    def _init_highlight(self, config: HighlightEffectConfig) -> None:
        """编译 shader → 创建全屏四边形 → 初始化 FBO。"""
        self._compile_shaders()
        self._create_quad()
        self._ensure_fbo(
            self._renderer.viewport_width, self._renderer.viewport_height)

    def _release_highlight(self) -> None:
        """释放所有 highlight GPU 资源。"""
        self._release_fbo()
        self._release_edge_fbo()
        for prog in (self._pp_mrt_prog, self._pp_edge_prog, self._pp_composite_prog):
            if prog:
                gl.glDeleteProgram(prog)
        self._pp_mrt_prog = self._pp_edge_prog = self._pp_composite_prog = 0
        if self._pp_quad_vao:
            gl.glDeleteVertexArrays(1, [self._pp_quad_vao])
            self._pp_quad_vao = 0

    def _render_highlight(self, view: np.ndarray, proj: np.ndarray) -> None:
        """Pass 1 MRT → Pass 2 Edge → Pass 3 Composite。"""
        r = self._renderer
        vp_w, vp_h = r.viewport_width, r.viewport_height
        if vp_w == 0 or vp_h == 0:
            return

        # ── 确保 FBO 尺寸匹配 (resize 时惰性重建) ──
        self._ensure_fbo(vp_w, vp_h)
        self._ensure_edge_fbo(vp_w, vp_h)

        # ══════════════════════════════════════════════════
        # Pass 1: MRT Scene — 渲染实体到 color + id
        # ══════════════════════════════════════════════════
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self._pp_fbo)
        gl.glViewport(0, 0, vp_w, vp_h)

        # attachment 0 (rgba8) + attachment 1 (r32ui) + depth
        # ★ 场景色缓冲清屏色 = 渲染器当前清屏色 (SetClearColorCommand / set_clear_color)。
        #   不再硬编码 — 否则 highlight 常驻时编辑器视口/PIE 都看不到工程背景色。
        _cc = getattr(self._renderer._core, "_clear_color", (0.2, 0.2, 0.2, 1.0))
        gl.glClearColor(*_cc)
        gl.glClearBufferuiv(gl.GL_COLOR, 1, (ctypes.c_uint * 4)(0, 0, 0, 0))
        gl.glClearBufferfv(gl.GL_COLOR, 0, (ctypes.c_float * 4)(*_cc))
        gl.glClear(gl.GL_DEPTH_BUFFER_BIT)
        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glDepthFunc(gl.GL_LESS)
        gl.glDepthMask(gl.GL_TRUE)
        gl.glDisable(gl.GL_BLEND)

        gl.glUseProgram(self._pp_mrt_prog)
        loc_model = gl.glGetUniformLocation(self._pp_mrt_prog, 'model')
        loc_view = gl.glGetUniformLocation(self._pp_mrt_prog, 'view')
        loc_proj = gl.glGetUniformLocation(self._pp_mrt_prog, 'projection')
        loc_tex = gl.glGetUniformLocation(self._pp_mrt_prog, 'uTexture')
        loc_oid = gl.glGetUniformLocation(self._pp_mrt_prog, 'uObjID')

        view_f32 = np.ascontiguousarray(view.astype('float32'))
        proj_f32 = np.ascontiguousarray(proj.astype('float32'))
        if loc_view >= 0:
            gl.glUniformMatrix4fv(loc_view, 1, gl.GL_FALSE, view_f32)
        if loc_proj >= 0:
            gl.glUniformMatrix4fv(loc_proj, 1, gl.GL_FALSE, proj_f32)
        if loc_tex >= 0:
            gl.glUniform1i(loc_tex, 0)

        active_ids = self._highlight_config.selected_ids if self._highlight_config else set()

        # ★ 使用 _visible_entities (Editor Eye 控制) — 眼睛关闭的实体既不渲染也不画轮廓
        for eid in list(self._renderer._resources._visible_entities):
            entity = r.registered_entities.get(eid)
            if entity is None:
                continue

            model = self._renderer.engine.scene.GetEntityModelMatrix(eid)
            model_f32 = np.ascontiguousarray(model.astype('float32'))
            if loc_model >= 0:
                gl.glUniformMatrix4fv(loc_model, 1, gl.GL_FALSE, model_f32)

            # 选中实体 ID=1, 未选中=0 (边界仅出现在选中↔背景)
            obj_id = 1 if eid in active_ids else 0
            if loc_oid >= 0:
                gl.glUniform1ui(loc_oid, obj_id)

            gl.glBindVertexArray(entity.vao)
            mesh_data = r.registered_meshes[entity.mesh_id]
            gl.glDrawElements(gl.GL_TRIANGLES, mesh_data.elements_count,
                              gl.GL_UNSIGNED_INT, None)
            gl.glBindVertexArray(0)

        # ══════════════════════════════════════════════════
        # Pass 2: Edge Detection
        #   读 id_tex → Roberts Cross 边缘检测 → edge_tex (R8)
        # ══════════════════════════════════════════════════
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self._pp_edge_fbo)
        gl.glViewport(0, 0, vp_w, vp_h)
        gl.glDisable(gl.GL_DEPTH_TEST)

        gl.glUseProgram(self._pp_edge_prog)
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self._pp_id_tex)

        loc_eid = gl.glGetUniformLocation(self._pp_edge_prog, 'uIDTex')
        if loc_eid >= 0:
            gl.glUniform1i(loc_eid, 0)
        loc_w = gl.glGetUniformLocation(self._pp_edge_prog, 'uWidth')
        if loc_w >= 0:
            w_val = self._highlight_config.width if self._highlight_config else 3
            gl.glUniform1i(loc_w, w_val)

        gl.glBindVertexArray(self._pp_quad_vao)
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

        gl.glUseProgram(self._pp_composite_prog)
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self._pp_edge_tex)

        loc_etex = gl.glGetUniformLocation(self._pp_composite_prog, 'uEdgeTex')
        if loc_etex >= 0:
            gl.glUniform1i(loc_etex, 0)
        loc_oc = gl.glGetUniformLocation(
            self._pp_composite_prog, 'uOutlineColor')
        if loc_oc >= 0:
            col = self._highlight_config.color if self._highlight_config else (
                0.878, 0.416, 0.153)
            gl.glUniform3f(loc_oc, *col)

        gl.glBindVertexArray(self._pp_quad_vao)
        gl.glDrawArrays(gl.GL_TRIANGLE_STRIP, 0, 4)
        gl.glBindVertexArray(0)
        gl.glDisable(gl.GL_BLEND)

        # 恢复深度测试 (后续 overlay 需要)
        gl.glEnable(gl.GL_DEPTH_TEST)

    def _update_highlight_params(self) -> None:
        """参数更新 — 颜色/宽度在每帧 _render_highlight 中动态读取，无需额外操作。"""
        pass

    # ════════════════════════════════════════════════════════
    # Shader 编译
    # ════════════════════════════════════════════════════════

    def _compile_shaders(self) -> None:
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
        self._pp_mrt_prog = gls.compileProgram(
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
        self._pp_edge_prog = gls.compileProgram(
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
        self._pp_composite_prog = gls.compileProgram(
            gls.compileShader(_COMP_VS, gl.GL_VERTEX_SHADER),
            gls.compileShader(_COMP_FS, gl.GL_FRAGMENT_SHADER),
        )

    # ════════════════════════════════════════════════════════
    # 全屏四边形
    # ════════════════════════════════════════════════════════

    def _create_quad(self) -> None:
        """创建全屏四边形 VAO (triangle strip)。"""
        from Application.Core.Renderer.VertexLayout import STD_LAYOUT
        verts = np.array([-1, -1, 1, -1, -1, 1, 1, 1], dtype='f4')
        self._pp_quad_vao = gl.glGenVertexArrays(1)
        vbo = gl.glGenBuffers(1)
        gl.glBindVertexArray(self._pp_quad_vao)
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

    def _ensure_fbo(self, w: int, h: int) -> None:
        """确保 MRT FBO 尺寸匹配 (resize 时重建)。"""
        if self._pp_fbo and self._pp_fbo_w == w and self._pp_fbo_h == h:
            return
        self._release_fbo()

        # Color (RGBA8)
        self._pp_color_tex = gl.glGenTextures(1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self._pp_color_tex)
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA8, w, h, 0,
                        gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, None)
        gl.glTexParameteri(gl.GL_TEXTURE_2D,
                           gl.GL_TEXTURE_MIN_FILTER, gl.GL_NEAREST)
        gl.glTexParameteri(gl.GL_TEXTURE_2D,
                           gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST)

        # Object ID (R32UI)
        self._pp_id_tex = gl.glGenTextures(1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self._pp_id_tex)
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_R32UI, w, h, 0,
                        gl.GL_RED_INTEGER, gl.GL_UNSIGNED_INT, None)
        gl.glTexParameteri(gl.GL_TEXTURE_2D,
                           gl.GL_TEXTURE_MIN_FILTER, gl.GL_NEAREST)
        gl.glTexParameteri(gl.GL_TEXTURE_2D,
                           gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST)

        # Depth (D24)
        self._pp_ds_rbo = gl.glGenRenderbuffers(1)
        gl.glBindRenderbuffer(gl.GL_RENDERBUFFER, self._pp_ds_rbo)
        gl.glRenderbufferStorage(
            gl.GL_RENDERBUFFER, gl.GL_DEPTH_COMPONENT24, w, h)

        # FBO
        self._pp_fbo = gl.glGenFramebuffers(1)
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self._pp_fbo)
        gl.glFramebufferTexture2D(gl.GL_FRAMEBUFFER,
                                  gl.GL_COLOR_ATTACHMENT0,
                                  gl.GL_TEXTURE_2D, self._pp_color_tex, 0)
        gl.glFramebufferTexture2D(gl.GL_FRAMEBUFFER,
                                  gl.GL_COLOR_ATTACHMENT1,
                                  gl.GL_TEXTURE_2D, self._pp_id_tex, 0)
        gl.glFramebufferRenderbuffer(gl.GL_FRAMEBUFFER,
                                     gl.GL_DEPTH_ATTACHMENT,
                                     gl.GL_RENDERBUFFER, self._pp_ds_rbo)
        gl.glDrawBuffers(2, [gl.GL_COLOR_ATTACHMENT0,
                         gl.GL_COLOR_ATTACHMENT1])

        if gl.glCheckFramebufferStatus(gl.GL_FRAMEBUFFER) != gl.GL_FRAMEBUFFER_COMPLETE:
            raise RuntimeError("OpenGLPostProcess: MRT FBO incomplete")

        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, 0)
        self._pp_fbo_w, self._pp_fbo_h = w, h

    def _release_fbo(self) -> None:
        """释放 MRT FBO 及其附件。"""
        if self._pp_fbo:
            gl.glDeleteFramebuffers(1, [self._pp_fbo])
            self._pp_fbo = 0
        if self._pp_color_tex:
            gl.glDeleteTextures(1, [self._pp_color_tex])
            self._pp_color_tex = 0
        if self._pp_id_tex:
            gl.glDeleteTextures(1, [self._pp_id_tex])
            self._pp_id_tex = 0
        if self._pp_ds_rbo:
            gl.glDeleteRenderbuffers(1, [self._pp_ds_rbo])
            self._pp_ds_rbo = 0
        self._pp_fbo_w = self._pp_fbo_h = 0

    # ════════════════════════════════════════════════════════
    # Edge FBO 管理 (持久化, 不再每帧创建/销毁)
    # ════════════════════════════════════════════════════════

    def _ensure_edge_fbo(self, w: int, h: int) -> None:
        """确保边缘检测 FBO 尺寸匹配。"""
        if self._pp_edge_fbo and self._pp_fbo_w == w and self._pp_fbo_h == h:
            return
        self._release_edge_fbo()

        self._pp_edge_tex = gl.glGenTextures(1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self._pp_edge_tex)
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_R8, w, h, 0,
                        gl.GL_RED, gl.GL_UNSIGNED_BYTE, None)
        gl.glTexParameteri(gl.GL_TEXTURE_2D,
                           gl.GL_TEXTURE_MIN_FILTER, gl.GL_NEAREST)
        gl.glTexParameteri(gl.GL_TEXTURE_2D,
                           gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST)

        self._pp_edge_fbo = gl.glGenFramebuffers(1)
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self._pp_edge_fbo)
        gl.glFramebufferTexture2D(gl.GL_FRAMEBUFFER,
                                  gl.GL_COLOR_ATTACHMENT0,
                                  gl.GL_TEXTURE_2D, self._pp_edge_tex, 0)
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, 0)

    def _release_edge_fbo(self) -> None:
        """释放边缘检测 FBO 及其纹理。"""
        if self._pp_edge_fbo:
            gl.glDeleteFramebuffers(1, [self._pp_edge_fbo])
            self._pp_edge_fbo = 0
        if self._pp_edge_tex:
            gl.glDeleteTextures(1, [self._pp_edge_tex])
            self._pp_edge_tex = 0
