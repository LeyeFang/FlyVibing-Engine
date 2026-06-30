"""
Editor Outliner (ID Buffer) — Blender 风格的实体 ID + 屏幕空间边缘检测轮廓高亮。

设计理念:
  不使用 stencil buffer。改用 MRT (Multiple Render Target) 渲染两个 attachment:
    Attachment 0: 颜色 (RGBA8)
    Attachment 1: 实体 ID (R32UINT)
  然后通过 screen-space edge detection (Roberts cross) 检测 ID 不连续像素作为轮廓。

绘制管线:
  ┌──────────────────────────────────────────────────────────────┐
  │ Pass 1 — Scene MRT                                         │
  │   遍历所有实体, 着色器同时输出:                               │
  │     layout(location=0) out vec4  outColor;                  │
  │     layout(location=1) out uint  outObjID;                  │
  │   写入 FBO (color + obj_id + depth)                         │
  ├──────────────────────────────────────────────────────────────┤
  │ Pass 2 — Edge Detection (全屏四边形)                         │
  │   读取 id_img, Roberts cross 检测边缘 → outline_mask         │
  │   fragment shader 输出到 outline_img (R8)                   │
  ├──────────────────────────────────────────────────────────────┤
  │ Pass 3 — Composite (全屏四边形)                              │
  │   outline_img 与 color_img 混合 → 输出到屏幕                  │
  └──────────────────────────────────────────────────────────────┘

对比 Stencil 方案:
  ┌────────────────┬───────────────────┬──────────────────┐
  │                │ Stencil Outliner  │ ID Outliner      │
  ├────────────────┼───────────────────┼──────────────────┤
  │ depth+stencil  │ 必须              │ 不需要           │
  │ 逐实体状态切换  │ 必须              │ 不需要           │
  │ 深度 blit      │ 必须              │ 不需要           │
  │ 后处理 pass    │ 无                │ 一个 edge pass   │
  │ ZenGL 纯血     │ ❌ 不行           │ ✅ 可以          │
  │ 轮廓宽度调节   │ 几何缩放 (有锯齿)  │ 采样半径 (平滑)   │
  │ 实现复杂度     │ 中                │ 中上             │
  └────────────────┴───────────────────┴──────────────────┘

使用方式:
  OutlinerID.register_to(renderer)     # 自动检测 OpenGL / ZenGL 后端
  OutlinerID.unregister_from(renderer)
  OutlinerID.set_selected_entities(selected_set)
  OutlinerID.configure(xray=True, outline_width=2, outline_color=(1,0.6,0.2))

线程安全:
  通过 _pending_ids / _active_ids 隔离, 同原版 Outliner。
"""

from __future__ import annotations
import numpy as np


# ════════════════════════════════════════════════════════════════
# 参数常量
# ════════════════════════════════════════════════════════════════

OUTLINE_COLOR: tuple = (0.878, 0.416, 0.153)      # Blender 橙色
OUTLINE_WIDTH: int = 3                               # 边缘检测半径 (像素)
OUTLINE_XRAY: bool = True                             # 默认穿透模式
ENTITY_ID_OFFSET: int = 1                             # entity_id → outID (0=空)


# ════════════════════════════════════════════════════════════════
# 后端渲染器检测与类型
# ════════════════════════════════════════════════════════════════

BACKEND_OPENGL = 1
BACKEND_ZENGL = 2


# ════════════════════════════════════════════════════════════════
# OutlinerID — Blender 风格 ID Buffer 轮廓
# ════════════════════════════════════════════════════════════════

class OutlinerID:
    """选中实体轮廓高亮 (ID buffer + screen-space edge detection)。

    架构:
      - 模块顶层: MRT FBO 管理、边缘检测着色器、全屏四边形
      - OutlinerID 类: 注册/注销 + 选择同步 + 后端适配

    与 Renderer 接口:
      - register_overlay_callback   (post-render: edge + composite)
      - 不依赖 _scene_fbo_override / _outline_selected_ids
    """

    _pending_ids: set[int] | None = None
    _active_ids: set[int] = set()

    _color: tuple = OUTLINE_COLOR
    _width: int = OUTLINE_WIDTH
    _xray: bool = OUTLINE_XRAY

    # ── FBO / 着色器 / VAO 资源 (硬编码, 无外部文件依赖) ──
    _backend = 0  # BACKEND_OPENGL 或 BACKEND_ZENGL

    # ════════════════════════════════════════════════════════
    # OpenGL 后端资源
    # ════════════════════════════════════════════════════════
    _gl_fbo = 0
    _gl_color_tex = 0       # rgba8unorm
    _gl_id_tex = 0          # r32ui
    _gl_ds_rbo = 0          # depth24
    _gl_fbo_w = 0
    _gl_fbo_h = 0
    _gl_edge_prog = 0       # 边缘检测 shader
    _gl_composite_prog = 0  # composite shader
    _gl_vao_quad = 0        # 全屏四边形

    # ════════════════════════════════════════════════════════
    # ZenGL 后端资源 (在 register 时按需创建)
    # ════════════════════════════════════════════════════════
    _zg_ctx = None
    _zg_color_img = None
    _zg_id_img = None
    _zg_depth_img = None
    _zg_edge_pipeline = None
    _zg_composite_pipeline = None
    _zg_entity_pipelines: dict[int, any] = {}

    # ════════════════════════════════════════════════════════
    # 注册 / 注销
    # ════════════════════════════════════════════════════════

    @classmethod
    def detect_backend(cls, renderer) -> int:
        """自动检测渲染器后端。renderer 是类本身 (class-level API)。"""
        cls_name = getattr(renderer, '__name__', '') or renderer.__class__.__name__
        mod_name = getattr(renderer, '__module__', '')
        if 'ZenGL' in cls_name or 'ZenGL' in mod_name:
            return BACKEND_ZENGL
        return BACKEND_OPENGL

    @classmethod
    def register_to(cls, renderer) -> None:
        """注册 outliner — 自动适配后端。"""
        cls._backend = cls.detect_backend(renderer)
        cls._renderer = renderer

        if cls._backend == BACKEND_ZENGL:
            from Application.Core.Renderer.ZenGL.ZenGLCore import ZenGLCore
            cls._zg_ctx = ZenGLCore.ctx
            cls._zg_create_fbo(
                renderer.viewport_width, renderer.viewport_height)
            cls._zg_compile_entity_shaders()

        else:
            cls._gl_compile_shaders()
            cls._gl_create_quad()
            cls._gl_ensure_fbo(
                renderer.viewport_width, renderer.viewport_height)

        # 注册后渲染回调 (在实体渲染 + overlay 回调之后)
        renderer.register_overlay_callback(cls._on_post_render)
        print(f"[OutlinerID] registered (backend={'ZenGL' if cls._backend==BACKEND_ZENGL else 'OpenGL'})")

    @classmethod
    def unregister_from(cls, renderer) -> None:
        """注销 outliner — 释放 GPU 资源。"""
        renderer.unregister_overlay_callback(cls._on_post_render)
        if cls._backend == BACKEND_ZENGL:
            cls._zg_release()
        else:
            cls._gl_release()
        cls._renderer = None
        print("[OutlinerID] unregistered")

    # ════════════════════════════════════════════════════════
    # 主线程 API (零 GL 调用)
    # ════════════════════════════════════════════════════════

    @classmethod
    def set_selected_entities(cls, entity_ids: set[int]) -> None:
        cls._pending_ids = set(entity_ids) if entity_ids else set()

    @classmethod
    def clear(cls) -> None:
        cls._pending_ids = set()

    @classmethod
    def configure(
        cls,
        color: tuple[float, float, float] = None,
        outline_width: int = None,
        xray: bool = None,
    ) -> None:
        if color is not None:
            cls._color = tuple(color)
        if outline_width is not None:
            cls._width = max(1, int(outline_width))
        if xray is not None:
            cls._xray = bool(xray)

    # ════════════════════════════════════════════════════════
    # 线程安全同步 (渲染线程调用)
    # ════════════════════════════════════════════════════════

    @classmethod
    def _sync(cls) -> None:
        if cls._pending_ids is not None:
            cls._active_ids = cls._pending_ids
            cls._pending_ids = None

    # ════════════════════════════════════════════════════════
    # 核心回调 — _on_post_render
    # ════════════════════════════════════════════════════════
    #
    # 由 renderer._render_overlays(...) 在实体渲染后、overlay 绘制前调用。
    # 执行: Pass 1 (Scene MRT) + Pass 2 (Edge) + Pass 3 (Composite)
    #
    # 注意: 此函数是模块级函数, 但为了代码组织放在类方法中。

    @classmethod
    def _on_post_render(cls, view: np.ndarray, proj: np.ndarray) -> None:
        """Post-render 回调: 场景 MRT → 边缘检测 → 混合到屏幕。"""
        cls._sync()

        if cls._backend == BACKEND_ZENGL:
            cls._zg_on_post_render(view, proj)
        else:
            cls._gl_on_post_render(view, proj)

    # ═══════════════════════════════════════════════════════════════
    # 以下为实现细节 — 按后端隔离
    # ═══════════════════════════════════════════════════════════════
    # ========== OpenGL 后端 ==========
    # ═══════════════════════════════════════════════════════════════

    @classmethod
    def _gl_compile_shaders(cls) -> None:
        """编译 MRT 场景着色器、边缘检测着色器、composite 着色器。"""
        from OpenGL import GL as gl
        from OpenGL.GL import shaders as gls

        # ── MRT 场景 Vertex ──
        _SCENE_VS = '''#version 440 core
layout(location=0) in vec3 aPos;
layout(location=1) in vec2 aTexCoord;
layout(location=2) in vec3 aNormal;
uniform mat4 model, view, projection;
out vec2 TexCoord;
void main() {
    gl_Position = projection * view * model * vec4(aPos, 1.0);
    TexCoord = aTexCoord;
}'''
        # ── MRT 场景 Fragment (输出 color + objID) ──
        _SCENE_MRT_FS = '''#version 440 core
in vec2 TexCoord;
uniform sampler2D uTexture;
uniform uint uObjID;
layout(location=0) out vec4 outColor;
layout(location=1) out uint outObjID;
void main() {
    outColor = texture(uTexture, TexCoord);
    outObjID = uObjID;
}'''
        cls._gl_mrt_prog = gls.compileProgram(
            gls.compileShader(_SCENE_VS, gl.GL_VERTEX_SHADER),
            gls.compileShader(_SCENE_MRT_FS, gl.GL_FRAGMENT_SHADER),
        )

        # ── 边缘检测 (Roberts cross) ──
        _EDGE_VS = '''#version 440 core
in vec2 aPos;
out vec2 vUV;
void main() {
    gl_Position = vec4(aPos, 0.0, 1.0);
    vUV = aPos * 0.5 + 0.5;
}'''
        _EDGE_FS = f'''#version 440 core
in vec2 vUV;
uniform usampler2D uIDTex;
uniform int uWidth;
out float outEdge;
void main() {{
    ivec2 tx = ivec2(gl_FragCoord.xy);
    int w = uWidth;
    uint c = texelFetch(uIDTex, tx, 0).r;
    // 检查 uWidth 半径内是否有不同 ID → 粗轮廓
    float edge = 0.0;
    for (int dx = -w; dx <= w; dx++) {{
        for (int dy = -w; dy <= w; dy++) {{
            uint n = texelFetch(uIDTex, tx + ivec2(dx, dy), 0).r;
            if (n != c) {{ edge = 1.0; }}
        }}
    }}
    outEdge = edge;
}}'''
        cls._gl_edge_prog = gls.compileProgram(
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
        _COMP_FS = f'''#version 440 core
in vec2 vUV;
uniform sampler2D uEdgeTex;
uniform vec3 uOutlineColor;
out vec4 outColor;
void main() {{
    float edge = texture(uEdgeTex, vUV).r;
    outColor = vec4(uOutlineColor, edge);
}}'''
        cls._gl_composite_prog = gls.compileProgram(
            gls.compileShader(_COMP_VS, gl.GL_VERTEX_SHADER),
            gls.compileShader(_COMP_FS, gl.GL_FRAGMENT_SHADER),
        )

    @classmethod
    def _gl_create_quad(cls) -> None:
        """创建全屏四边形 VAO。"""
        from OpenGL import GL as gl
        verts = np.array([-1, -1, 1, -1, -1, 1, 1, 1], dtype='f4')
        cls._gl_vao_quad = gl.glGenVertexArrays(1)
        vbo = gl.glGenBuffers(1)
        gl.glBindVertexArray(cls._gl_vao_quad)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, vbo)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, verts.nbytes, verts, gl.GL_STATIC_DRAW)
        gl.glEnableVertexAttribArray(0)
        gl.glVertexAttribPointer(0, 2, gl.GL_FLOAT, gl.GL_FALSE, 0, None)
        gl.glBindVertexArray(0)

    @classmethod
    def _gl_ensure_fbo(cls, w: int, h: int) -> None:
        """确保 MRT FBO 尺寸匹配 (resize 时重建)。"""
        from OpenGL import GL as gl
        if cls._gl_fbo and cls._gl_fbo_w == w and cls._gl_fbo_h == h:
            return
        cls._gl_release_fbo()
        # Color
        cls._gl_color_tex = gl.glGenTextures(1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, cls._gl_color_tex)
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA8, w, h, 0,
                        gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, None)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_NEAREST)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST)
        # Object ID (R32UI)
        cls._gl_id_tex = gl.glGenTextures(1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, cls._gl_id_tex)
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_R32UI, w, h, 0,
                        gl.GL_RED_INTEGER, gl.GL_UNSIGNED_INT, None)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_NEAREST)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST)
        # Depth
        cls._gl_ds_rbo = gl.glGenRenderbuffers(1)
        gl.glBindRenderbuffer(gl.GL_RENDERBUFFER, cls._gl_ds_rbo)
        gl.glRenderbufferStorage(gl.GL_RENDERBUFFER, gl.GL_DEPTH_COMPONENT24, w, h)
        # FBO
        cls._gl_fbo = gl.glGenFramebuffers(1)
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, cls._gl_fbo)
        gl.glFramebufferTexture2D(gl.GL_FRAMEBUFFER, gl.GL_COLOR_ATTACHMENT0,
                                  gl.GL_TEXTURE_2D, cls._gl_color_tex, 0)
        gl.glFramebufferTexture2D(gl.GL_FRAMEBUFFER, gl.GL_COLOR_ATTACHMENT1,
                                  gl.GL_TEXTURE_2D, cls._gl_id_tex, 0)
        gl.glFramebufferRenderbuffer(gl.GL_FRAMEBUFFER, gl.GL_DEPTH_ATTACHMENT,
                                     gl.GL_RENDERBUFFER, cls._gl_ds_rbo)
        gl.glDrawBuffers(2, [gl.GL_COLOR_ATTACHMENT0, gl.GL_COLOR_ATTACHMENT1])
        if gl.glCheckFramebufferStatus(gl.GL_FRAMEBUFFER) != gl.GL_FRAMEBUFFER_COMPLETE:
            raise RuntimeError("OutlinerID: MRT FBO incomplete")
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, 0)
        cls._gl_fbo_w, cls._gl_fbo_h = w, h

    @classmethod
    def _gl_release_fbo(cls) -> None:
        from OpenGL import GL as gl
        if cls._gl_fbo: gl.glDeleteFramebuffers(1, [cls._gl_fbo]); cls._gl_fbo = 0
        if cls._gl_color_tex: gl.glDeleteTextures(1, [cls._gl_color_tex]); cls._gl_color_tex = 0
        if cls._gl_id_tex: gl.glDeleteTextures(1, [cls._gl_id_tex]); cls._gl_id_tex = 0
        if cls._gl_ds_rbo: gl.glDeleteRenderbuffers(1, [cls._gl_ds_rbo]); cls._gl_ds_rbo = 0

    @classmethod
    def _gl_on_post_render(cls, view: np.ndarray, proj: np.ndarray) -> None:
        """OpenGL 后端: Pass 1 MRT → Pass 2 Edge → Pass 3 Composite。"""
        from OpenGL import GL as gl
        r = cls._renderer
        if r is None:
            return
        vp_w, vp_h = r.viewport_width, r.viewport_height
        cls._gl_ensure_fbo(vp_w, vp_h)

        # ══════════════════════════════════════════════════
        # Pass 1: MRT Scene — 渲染实体到 color + id
        # ══════════════════════════════════════════════════
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, cls._gl_fbo)
        gl.glViewport(0, 0, vp_w, vp_h)
        # attachment 0 (rgba8): glClearColor 生效
        gl.glClearColor(0.2, 0.2, 0.2, 1.0)
        # attachment 1 (r32ui): 必须用 glClearBufferuiv 清零, glClearColor 对它无效
        import ctypes
        gl.glClearBufferuiv(gl.GL_COLOR, 1, (ctypes.c_uint * 4)(0, 0, 0, 0))
        gl.glClearBufferfv(gl.GL_COLOR, 0, (ctypes.c_float * 4)(0.2, 0.2, 0.2, 1.0))
        gl.glClear(gl.GL_DEPTH_BUFFER_BIT)
        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glDepthFunc(gl.GL_LESS)
        gl.glDepthMask(gl.GL_TRUE)
        gl.glDisable(gl.GL_BLEND)

        gl.glUseProgram(cls._gl_mrt_prog)
        loc_model = gl.glGetUniformLocation(cls._gl_mrt_prog, 'model')
        loc_view = gl.glGetUniformLocation(cls._gl_mrt_prog, 'view')
        loc_proj = gl.glGetUniformLocation(cls._gl_mrt_prog, 'projection')
        loc_tex = gl.glGetUniformLocation(cls._gl_mrt_prog, 'uTexture')
        loc_oid = gl.glGetUniformLocation(cls._gl_mrt_prog, 'uObjID')

        view_f32 = np.ascontiguousarray(view.astype('float32'))
        proj_f32 = np.ascontiguousarray(proj.astype('float32'))
        if loc_view >= 0: gl.glUniformMatrix4fv(loc_view, 1, gl.GL_FALSE, view_f32)
        if loc_proj >= 0: gl.glUniformMatrix4fv(loc_proj, 1, gl.GL_FALSE, proj_f32)
        if loc_tex >= 0: gl.glUniform1i(loc_tex, 0)

        from Application.Core.Scene.SceneManager import SceneManager
        from Application.Core.Math.Transform import calculate_entity_model
        for eid in SceneManager.GetRenderableEntities():
            entity = r.registered_entities.get(eid)
            if entity is None:
                continue
            model = calculate_entity_model(SceneManager.GetEntityTransform(eid))
            model_f32 = np.ascontiguousarray(model.astype('float32'))
            if loc_model >= 0:
                gl.glUniformMatrix4fv(loc_model, 1, gl.GL_FALSE, model_f32)
            # ★ 所有选中实体共用 ID=1, 未选中=0 (边界仅出现在选中↔背景)
            obj_id = 1 if eid in cls._active_ids else 0
            if loc_oid >= 0:
                gl.glUniform1ui(loc_oid, obj_id)
            gl.glBindVertexArray(entity.vao)
            mesh_data = r.registered_meshes[entity.mesh_id]
            gl.glDrawElements(gl.GL_TRIANGLES, mesh_data.elements_count,
                              gl.GL_UNSIGNED_INT, None)
            gl.glBindVertexArray(0)

        # ══════════════════════════════════════════════════
        # Pass 2: Edge Detection
        #  读 id_tex, 输出边缘到 outline_img (R8)
        # ══════════════════════════════════════════════════
        # 创建临时 R8 纹理用于 outline 结果
        out_edge_tex = gl.glGenTextures(1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, out_edge_tex)
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_R8, vp_w, vp_h, 0,
                        gl.GL_RED, gl.GL_UNSIGNED_BYTE, None)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_NEAREST)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST)
        edge_fbo = gl.glGenFramebuffers(1)
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, edge_fbo)
        gl.glFramebufferTexture2D(gl.GL_FRAMEBUFFER, gl.GL_COLOR_ATTACHMENT0,
                                  gl.GL_TEXTURE_2D, out_edge_tex, 0)

        gl.glViewport(0, 0, vp_w, vp_h)
        gl.glDisable(gl.GL_DEPTH_TEST)
        gl.glUseProgram(cls._gl_edge_prog)
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, cls._gl_id_tex)
        loc_eid = gl.glGetUniformLocation(cls._gl_edge_prog, 'uIDTex')
        if loc_eid >= 0: gl.glUniform1i(loc_eid, 0)
        loc_w = gl.glGetUniformLocation(cls._gl_edge_prog, 'uWidth')
        if loc_w >= 0: gl.glUniform1i(loc_w, cls._width)
        gl.glBindVertexArray(cls._gl_vao_quad)
        gl.glDrawArrays(gl.GL_TRIANGLE_STRIP, 0, 4)
        gl.glBindVertexArray(0)
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, 0)

        # ══════════════════════════════════════════════════
        # Pass 3: Composite (alpha-blended overlay)
        #  读 edge_tex → 仅输出轮廓到默认帧缓冲, 保留 Grid 等底层内容
        # ══════════════════════════════════════════════════
        gl.glViewport(0, 0, vp_w, vp_h)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
        gl.glEnable(gl.GL_BLEND)
        gl.glUseProgram(cls._gl_composite_prog)
        # edge → texture unit 0
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, out_edge_tex)
        loc_etex = gl.glGetUniformLocation(cls._gl_composite_prog, 'uEdgeTex')
        if loc_etex >= 0: gl.glUniform1i(loc_etex, 0)
        # color
        loc_oc = gl.glGetUniformLocation(cls._gl_composite_prog, 'uOutlineColor')
        if loc_oc >= 0:
            gl.glUniform3f(loc_oc, *cls._color)

        gl.glBindVertexArray(cls._gl_vao_quad)
        gl.glDrawArrays(gl.GL_TRIANGLE_STRIP, 0, 4)
        gl.glBindVertexArray(0)
        gl.glDisable(gl.GL_BLEND)

        # 清理临时纹理
        gl.glDeleteFramebuffers(1, [edge_fbo])
        gl.glDeleteTextures(1, [out_edge_tex])

        # 恢复深度测试 (后续 overlay 需要)
        gl.glEnable(gl.GL_DEPTH_TEST)

    @classmethod
    def _gl_release(cls) -> None:
        from OpenGL import GL as gl
        for prog in (cls._gl_mrt_prog, cls._gl_edge_prog, cls._gl_composite_prog):
            if prog: gl.glDeleteProgram(prog)
        cls._gl_mrt_prog = cls._gl_edge_prog = cls._gl_composite_prog = 0
        if cls._gl_vao_quad:
            gl.glDeleteVertexArrays(1, [cls._gl_vao_quad])
            cls._gl_vao_quad = 0
        cls._gl_release_fbo()

    # ═══════════════════════════════════════════════════════════════
    # ========== ZenGL 后端 ==========
    # ═══════════════════════════════════════════════════════════════

    @classmethod
    def _zg_compile_shaders(cls) -> None:
        """编译 ZenGL 的边缘检测 + composite 着色器。"""
        ctx = cls._zg_ctx

        # ── 边缘检测 (Roberts cross, 读 r32uint) ──
        cls._zg_edge_pipeline = ctx.pipeline(
            vertex_shader='''
                #version 330 core
                vec2 vertices[3] = vec2[](vec2(-1,-1), vec2(3,-1), vec2(-1,3));
                out vec2 vUV;
                void main() {
                    gl_Position = vec4(vertices[gl_VertexID], 0.0, 1.0);
                    vUV = gl_Position.xy * 0.5 + 0.5;
                }
            ''',
            fragment_shader=f'''#version 420 core
in vec2 vUV;
layout(binding=0) uniform usampler2D uIDTex;
layout(location=0) out float outEdge;
void main() {{
    ivec2 tx = ivec2(gl_FragCoord.xy);
    uint c = texelFetch(uIDTex, tx, 0).r;
    uint r1 = texelFetch(uIDTex, tx + ivec2(1, 0), 0).r;
    uint u1 = texelFetch(uIDTex, tx + ivec2(0, 1), 0).r;
    outEdge = float((c != r1) || (c != u1));
}}''',
            layout=[{'name': 'uIDTex', 'binding': 0}],
            resources=[{'type': 'sampler', 'binding': 0, 'image': None}],  # 运行时设置
            framebuffer=[None],  # 运行时设置
            topology='triangles',
            vertex_count=3,
        )

        # ── Composite ──
        out_col_fs = f'''#version 420 core
in vec2 vUV;
layout(binding=0) uniform sampler2D uColorTex;
layout(binding=1) uniform sampler2D uEdgeTex;
layout(location=0) out vec4 outColor;
uniform vec3 uOutlineColor;
void main() {{
    vec4 scene = texture(uColorTex, vUV);
    float edge = texture(uEdgeTex, vUV).r;
    {'' if cls._xray else 'if (edge < 0.5) discard;'}
    outColor = vec4(mix(scene.rgb, uOutlineColor, edge), 1.0);
}}'''
        cls._zg_composite_pipeline = ctx.pipeline(
            vertex_shader='''
                #version 330 core
                vec2 vertices[3] = vec2[](vec2(-1,-1), vec2(3,-1), vec2(-1,3));
                out vec2 vUV;
                void main() {
                    gl_Position = vec4(vertices[gl_VertexID], 0.0, 1.0);
                    vUV = gl_Position.xy * 0.5 + 0.5;
                }
            ''',
            fragment_shader=out_col_fs,
            layout=[
                {'name': 'uColorTex', 'binding': 0},
                {'name': 'uEdgeTex', 'binding': 1},
            ],
            resources=[
                {'type': 'sampler', 'binding': 0, 'image': None},
                {'type': 'sampler', 'binding': 1, 'image': None},
            ],
            uniforms={'uOutlineColor': list(cls._color)},
            topology='triangles',
            vertex_count=3,
            blend={'enable': True, 'src_color': 'src_alpha', 'dst_color': 'one_minus_src_alpha'},
        )

    @classmethod
    def _zg_compile_entity_shaders(cls) -> None:
        """编译 MRT 实体着色器模板 (ZenGL 缓存 shader)。"""
        ctx = cls._zg_ctx
        # 仅编译源码，让 pipeline 在 register_entity 时缓存
        cls._zg_mrt_vs = '''#version 440 core
layout(location=0) in vec3 aPos;
layout(location=1) in vec2 aTexCoord;
layout(location=2) in vec3 aNormal;
uniform mat4 model, view, projection;
out vec2 TexCoord;
void main() {
    gl_Position = projection * view * model * vec4(aPos, 1.0);
    TexCoord = aTexCoord;
}'''
        cls._zg_mrt_fs = '''#version 440 core
in vec2 TexCoord;
layout(binding=0) uniform sampler2D uTexture;
uniform uint uSelectedFlag;
uniform uint uEntityID;
layout(location=0) out vec4 outColor;
layout(location=1) out uint outSelected;
layout(location=2) out uint outEntityID;
void main() {
    outColor = texture(uTexture, TexCoord);
    outSelected = uSelectedFlag;
    outEntityID = uEntityID;
}'''

    _zg_pick_img = None  # 实体 ID 图像 (用于拾取)

    @classmethod
    def _zg_create_fbo(cls, w: int, h: int) -> None:
        """创建 ZenGL MRT 图像。"""
        ctx = cls._zg_ctx
        cls._zg_color_img = ctx.image((w, h), 'rgba8unorm')
        cls._zg_id_img = ctx.image((w, h), 'r32uint')    # 选中标记 (0/1) 用于边缘检测
        cls._zg_pick_img = ctx.image((w, h), 'r32uint')   # 实体 ID 用于拾取
        cls._zg_depth_img = ctx.image((w, h), 'depth24plus')
        cls._zg_color_img.clear_value = (0.2, 0.2, 0.2, 1.0)

    @classmethod
    def _zg_on_post_render(cls, view: np.ndarray, proj: np.ndarray) -> None:
        """ZenGL 后端: Pass 1 MRT → Pass 2 Edge → Pass 3 Composite。"""
        ctx = cls._zg_ctx
        if ctx is None:
            return
        r = cls._renderer
        if r is None:
            return
        vp_w, vp_h = r.viewport_width, r.viewport_height
        cls._zg_ensure_fbo(vp_w, vp_h)

        # ══════════════════════════════════════════════════
        # Pass 1: Entity MRT (每个实体一个 ZenGL pipeline)
        # ══════════════════════════════════════════════════
        cls._zg_depth_img.clear()
        try:
            cls._zg_id_img.clear()
        except Exception:
            pass
        try:
            cls._zg_pick_img.clear()
        except Exception:
            pass

        from Application.Core.Scene.SceneManager import SceneManager
        from Application.Core.Math.Transform import calculate_entity_model
        for eid in SceneManager.GetRenderableEntities():
            entity = r.registered_entities.get(eid)
            if entity is None:
                continue
            if eid not in cls._zg_entity_pipelines:
                cls._zg_build_entity_pipeline(r, eid)
            p = cls._zg_entity_pipelines.get(eid)
            if p is None:
                continue
            try:
                model = calculate_entity_model(
                    SceneManager.GetEntityTransform(eid))
                p.uniforms['model'][:] = model.astype('float32').tobytes()
                p.uniforms['view'][:] = view.astype('float32').tobytes()
                p.uniforms['projection'][:] = proj.astype('float32').tobytes()
                p.uniforms['uSelectedFlag'][:] = int(
                    1 if eid in cls._active_ids else 0
                ).to_bytes(4, 'little')
                p.uniforms['uEntityID'][:] = int(eid).to_bytes(4, 'little')
            except Exception:
                pass
            p.render()

        # ══════════════════════════════════════════════════
        # Pass 2: 边缘检测 → outline_img (R8)
        # ══════════════════════════════════════════════════
        out_edge_img = ctx.image((vp_w, vp_h), 'r8unorm')
        edge_pipe = ctx.pipeline(
            vertex_shader='''
                #version 330 core
                vec2 vertices[3] = vec2[](vec2(-1,-1), vec2(3,-1), vec2(-1,3));
                out vec2 vUV;
                void main() {
                    gl_Position = vec4(vertices[gl_VertexID], 0.0, 1.0);
                    vUV = gl_Position.xy * 0.5 + 0.5;
                }
            ''',
            fragment_shader='''#version 420 core
in vec2 vUV;
layout(binding=0) uniform usampler2D uIDTex;
layout(location=0) out float outEdge;
void main() {
    ivec2 tx = ivec2(gl_FragCoord.xy);
    uint c = texelFetch(uIDTex, tx, 0).r;
    float edge = 0.0;
    int w = ''' + str(cls._width) + ''';
    for (int dx = -w; dx <= w; dx++) {
        for (int dy = -w; dy <= w; dy++) {
            uint n = texelFetch(uIDTex, tx + ivec2(dx, dy), 0).r;
            if (n != c) { edge = 1.0; }
        }
    }
    outEdge = edge;
}''',
            layout=[{'name': 'uIDTex', 'binding': 0}],
            resources=[{'type': 'sampler', 'binding': 0, 'image': cls._zg_id_img}],
            framebuffer=[out_edge_img],
            topology='triangles',
            vertex_count=3,
        )
        out_edge_img.clear()
        edge_pipe.render()

        # ══════════════════════════════════════════════════
        # Pass 3: Composite (alpha-blended overlay)
        # ══════════════════════════════════════════════════
        from Application.Core.Renderer.ZenGL.ZenGLCore import ZenGLCore
        comp = ctx.pipeline(
            vertex_shader='''
                #version 330 core
                vec2 vertices[3] = vec2[](vec2(-1,-1), vec2(3,-1), vec2(-1,3));
                out vec2 vUV;
                void main() {
                    gl_Position = vec4(vertices[gl_VertexID], 0.0, 1.0);
                    vUV = gl_Position.xy * 0.5 + 0.5;
                }
            ''',
            fragment_shader='''#version 420 core
in vec2 vUV;
layout(binding=0) uniform sampler2D uEdgeTex;
uniform vec3 uOutlineColor;
layout(location=0) out vec4 outColor;
void main() {
    float edge = texture(uEdgeTex, vUV).r;
    outColor = vec4(uOutlineColor, edge);
}''',
            layout=[
                {'name': 'uEdgeTex', 'binding': 0},
            ],
            resources=[
                {'type': 'sampler', 'binding': 0, 'image': out_edge_img},
            ],
            uniforms={'uOutlineColor': list(cls._color)},
            framebuffer=[ZenGLCore._color_image, ZenGLCore._depth_image],
            blend={'enable': True, 'src_color': 'src_alpha', 'dst_color': 'one_minus_src_alpha'},
            topology='triangles',
            vertex_count=3,
        )
        comp.render()

    @classmethod
    def _zg_ensure_fbo(cls, w: int, h: int) -> None:
        """确保 MRT 图像尺寸匹配。"""
        if cls._zg_color_img is not None and cls._zg_color_img.size == (w, h):
            return
        cls._zg_release_fbo()
        cls._zg_create_fbo(w, h)

    @classmethod
    def _zg_build_entity_pipeline(cls, renderer, eid: int) -> None:
        """为实体创建 MRT 场景 pipeline。"""
        from Application.Core.Renderer.ZenGL.ZenGLCore import ZenGLCore
        ctx = ZenGLCore.ctx
        entity = renderer.registered_entities.get(eid)
        if entity is None:
            return
        mesh_data = renderer.registered_meshes.get(entity.mesh_id)
        if mesh_data is None:
            return

        # 获取该实体的实际纹理
        from Application.Core.Renderer.ZenGL.ZenGLResourceManager import ZenGLResourceManager as ZRM
        tex_id = entity.texture_id
        tex_resources = []
        tex_layout = []
        if tex_id and tex_id in ZRM.registered_textures:
            td = ZRM.registered_textures[tex_id]
            tex_layout.append({'name': 'uTexture', 'binding': 0})
            tex_resources.append({
                'type': 'sampler', 'binding': 0, 'image': td.image,
                'min_filter': 'linear', 'mag_filter': 'linear',
            })

        pipeline = ctx.pipeline(
            vertex_shader=cls._zg_mrt_vs,
            fragment_shader=cls._zg_mrt_fs,
            layout=tex_layout,
            resources=tex_resources,
            uniforms={
                'model': np.identity(4, dtype='f4').flatten().tolist(),
                'view': np.identity(4, dtype='f4').flatten().tolist(),
                'projection': np.identity(4, dtype='f4').flatten().tolist(),
                'uSelectedFlag': 0,
                'uEntityID': 0,
            },
            framebuffer=[cls._zg_color_img, cls._zg_id_img, cls._zg_pick_img, cls._zg_depth_img],
            topology='triangles',
            cull_face='none',
            depth={'func': 'less', 'write': True},
            vertex_buffers=__import__('zengl').bind(
                mesh_data.vbo, '3f 2f 3f', 0, 1, -1
            ),
            index_buffer=mesh_data.ebo,
            vertex_count=mesh_data.elements_count,
        )
        cls._zg_entity_pipelines[eid] = pipeline

    @classmethod
    def _zg_release_fbo(cls) -> None:
        cls._zg_color_img = None
        cls._zg_id_img = None
        cls._zg_pick_img = None
        cls._zg_depth_img = None

    @classmethod
    def _zg_release(cls) -> None:
        cls._zg_entity_pipelines.clear()
        cls._zg_release_fbo()
