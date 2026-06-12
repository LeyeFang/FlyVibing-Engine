"""
Editor Outliner — 选中实体轮廓高亮 (stencil buffer 方案)。

设计原则 (对齐 Grid):
  - 轮廓资源 (参数/着色器/FBO管理/渲染回调) 独立于 Outliner 类, 置于模块顶部
  - Outliner 类仅为薄注册器: register_to() / unregister_from() / 选择同步
  - 不创建 overlay_drawable_struct — 复用实体 VAO, 通过 stencil 管线绘制轮廓
  - 线程安全: set_selected_entities() 主线程写入, _sync() 渲染线程消费

绘制原理 (stencil 方案):
  ┌────────────────────────────────────────────────────────────┐
  │ Pre-render 回调 (_on_pre_render):                          │
  │   1. 创建 Scene FBO (depth24+stencil8)                     │
  │   2. 清空颜色+深度+stencil                                  │
  │   3. 启用 stencil test (depth pass → replace=1)            │
  │   4. 注入 _scene_fbo_override → 实体渲染重定向到 Scene FBO  │
  │   5. 注入 _outline_selected_ids → 被选实体写 stencil=1      │
  │                                                            │
  │ _RenderEntities (渲染器):                                   │
  │   - 渲染到 Scene FBO                                       │
  │   - 被选实体 stencil=1, 其余 stencil=0                      │
  │                                                            │
  │ Post-render 回调 (_on_post_render):                        │
  │   1. Outline Pass: stencil NOTEQUAL → 放大绘制被选实体      │
  │   2. 恢复 GL 状态                                          │
  │   3. Blit Scene FBO 颜色纹理 → 默认帧缓冲                    │
  └────────────────────────────────────────────────────────────┘

与 Grid 的对应关系:
  ┌──────────────────────┬─────────────────────────────────────┐
  │ Grid                 │ Outliner                            │
  ├──────────────────────┼─────────────────────────────────────┤
  │ overlay_drawable     │ pre_overlay_callback +              │
  │ (data-driven)        │   overlay_callback (function-driven)│
  │ 顶点/索引预生成       │ 复用实体 VAO (不生成额外几何)         │
  │ uniforms_setup 回调   │ _on_pre_render / _on_post_render    │
  │ register_to()        │ register_to()                       │
  │ unregister_from()    │ unregister_from()                   │
  └──────────────────────┴─────────────────────────────────────┘

依赖:
  - openGLRenderer._scene_fbo_override    (FBO 重定向)
  - openGLRenderer._outline_selected_ids  (stencil 注入点)
  - openGLRenderer.register_pre_overlay_callback()
  - Renderer.register_overlay_callback()
"""

from __future__ import annotations

import numpy as np
from OpenGL import GL as gl

from Application.Core.Scene.SceneManager import SceneManager
from Application.Core.Math.RendererMath import calculate_entity_model


# ════════════════════════════════════════════════════════════════
# 轮廓资源: 参数常量
# ════════════════════════════════════════════════════════════════

OUTLINE_COLOR: tuple = (0.976, 0.451, 0.024)      # Blender 橙色 RGB
OUTLINE_SCALE: float = 1.05                         # 轮廓放大系数
OUTLINE_XRAY: bool = True                           # 默认穿透模式


# ════════════════════════════════════════════════════════════════
# 轮廓资源: 着色器
# ════════════════════════════════════════════════════════════════

_OUTLINE_VS: str = """#version 330 core
layout(location=0) in vec3 aPos;
uniform mat4 uModel, uView, uProj;
uniform float uOutlineScale;
void main() {
    // 纯顶点等比缩放: stencil NOTEQUAL 自动筛选轮廓边缘像素
    gl_Position = uProj * uView * uModel * vec4(aPos * uOutlineScale, 1.0);
}
"""

_OUTLINE_FS: str = """#version 330 core
uniform vec3 uOutlineColor;
out vec4 fragColor;
void main() {
    fragColor = vec4(uOutlineColor, 1.0);
}
"""

_BLIT_VS: str = """#version 330 core
in vec2 aPos;
out vec2 vUV;
void main() {
    gl_Position = vec4(aPos, 0.0, 1.0);
    vUV = aPos * 0.5 + 0.5;
}
"""

_BLIT_FS: str = """#version 330 core
in vec2 vUV;
out vec4 fragColor;
uniform sampler2D uScreenTex;
void main() {
    fragColor = texture(uScreenTex, vUV);
}
"""


# ════════════════════════════════════════════════════════════════
# 轮廓资源: Scene FBO 管理 (depth24 + stencil8)
# ════════════════════════════════════════════════════════════════

_fbo: int = 0
_color_tex: int = 0
_ds_rbo: int = 0               # depth24+stencil8 renderbuffer
_fbo_w: int = 0
_fbo_h: int = 0


def _ensure_fbo(w: int, h: int) -> None:
    """确保 Scene FBO 尺寸匹配视口 (resize 时重建)。"""
    global _fbo, _color_tex, _ds_rbo, _fbo_w, _fbo_h
    if _fbo and _fbo_w == w and _fbo_h == h:
        return
    _release_fbo()

    # ── 颜色纹理 ──
    _color_tex = gl.glGenTextures(1)
    gl.glBindTexture(gl.GL_TEXTURE_2D, _color_tex)
    gl.glTexImage2D(
        gl.GL_TEXTURE_2D, 0, gl.GL_RGBA8,
        w, h, 0, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, None)
    gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_NEAREST)
    gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST)

    # ── Depth24 + Stencil8 Renderbuffer ──
    _ds_rbo = gl.glGenRenderbuffers(1)
    gl.glBindRenderbuffer(gl.GL_RENDERBUFFER, _ds_rbo)
    gl.glRenderbufferStorage(gl.GL_RENDERBUFFER, gl.GL_DEPTH24_STENCIL8, w, h)

    # ── FBO ──
    _fbo = gl.glGenFramebuffers(1)
    gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, _fbo)
    gl.glFramebufferTexture2D(
        gl.GL_FRAMEBUFFER, gl.GL_COLOR_ATTACHMENT0,
        gl.GL_TEXTURE_2D, _color_tex, 0)
    gl.glFramebufferRenderbuffer(
        gl.GL_FRAMEBUFFER, gl.GL_DEPTH_STENCIL_ATTACHMENT,
        gl.GL_RENDERBUFFER, _ds_rbo)

    if gl.glCheckFramebufferStatus(gl.GL_FRAMEBUFFER) != gl.GL_FRAMEBUFFER_COMPLETE:
        raise RuntimeError("Outliner: Scene FBO incomplete")

    gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, 0)
    _fbo_w, _fbo_h = w, h


def _release_fbo() -> None:
    """释放 Scene FBO 及其附件。"""
    global _fbo, _color_tex, _ds_rbo, _fbo_w, _fbo_h
    if _fbo:
        gl.glDeleteFramebuffers(1, [_fbo])
        _fbo = 0
    if _color_tex:
        gl.glDeleteTextures(1, [_color_tex])
        _color_tex = 0
    if _ds_rbo:
        gl.glDeleteRenderbuffers(1, [_ds_rbo])
        _ds_rbo = 0
    _fbo_w = _fbo_h = 0


# ════════════════════════════════════════════════════════════════
# 轮廓资源: 着色器程序 + 全屏四边形 (GPU 资源)
# ════════════════════════════════════════════════════════════════

_prog_outline: int = 0
_prog_blit: int = 0
_vao_blit: int = 0


def _compile_shaders() -> None:
    """编译轮廓着色器和 blit 着色器。"""
    global _prog_outline, _prog_blit
    from OpenGL.GL import shaders as gls

    try:
        vs_o = gls.compileShader(_OUTLINE_VS, gl.GL_VERTEX_SHADER)
        fs_o = gls.compileShader(_OUTLINE_FS, gl.GL_FRAGMENT_SHADER)
        _prog_outline = gls.compileProgram(vs_o, fs_o)
        gl.glDeleteShader(vs_o)
        gl.glDeleteShader(fs_o)
    except RuntimeError as e:
        raise RuntimeError(f"Outliner: outline shader failed:\n{e}")

    try:
        vs_b = gls.compileShader(_BLIT_VS, gl.GL_VERTEX_SHADER)
        fs_b = gls.compileShader(_BLIT_FS, gl.GL_FRAGMENT_SHADER)
        _prog_blit = gls.compileProgram(vs_b, fs_b)
        gl.glDeleteShader(vs_b)
        gl.glDeleteShader(fs_b)
    except RuntimeError as e:
        raise RuntimeError(f"Outliner: blit shader failed:\n{e}")


def _create_blit_quad() -> None:
    """创建全屏四边形 VAO (用于 blit Scene FBO → 默认帧缓冲)。"""
    global _vao_blit
    verts = np.array([-1, -1, 1, -1, -1, 1, 1, 1], dtype='f4')
    _vao_blit = gl.glGenVertexArrays(1)
    vbo = gl.glGenBuffers(1)
    gl.glBindVertexArray(_vao_blit)
    gl.glBindBuffer(gl.GL_ARRAY_BUFFER, vbo)
    gl.glBufferData(gl.GL_ARRAY_BUFFER, verts.nbytes, verts, gl.GL_STATIC_DRAW)
    gl.glEnableVertexAttribArray(0)
    gl.glVertexAttribPointer(0, 2, gl.GL_FLOAT, gl.GL_FALSE, 0, None)
    gl.glBindVertexArray(0)


def _release_shaders() -> None:
    """释放轮廓着色器和 blit 资源。"""
    global _prog_outline, _prog_blit, _vao_blit
    if _prog_outline:
        gl.glDeleteProgram(_prog_outline)
        _prog_outline = 0
    if _prog_blit:
        gl.glDeleteProgram(_prog_blit)
        _prog_blit = 0
    if _vao_blit:
        gl.glDeleteVertexArrays(1, [_vao_blit])
        _vao_blit = 0


# ════════════════════════════════════════════════════════════════
# 轮廓资源: Pre / Post 渲染回调
# ════════════════════════════════════════════════════════════════
#
# 这些是模块级函数, 通过 renderer.register_pre_overlay_callback()
# 和 renderer.register_overlay_callback() 注册, 每帧由渲染器调用。
# 它们通过模块级变量访问 FBO / 着色器 / Outliner 配置。

_renderer: type = None
"""渲染器类引用 (register_to 时设置)。"""


def _on_pre_render(
    view: np.ndarray,
    proj: np.ndarray,
    vp_w: int,
    vp_h: int,
) -> None:
    """Pre-render 回调: Scene FBO 准备 + stencil 预设。

    由渲染器在 _RenderEntities 之前调用。
    """
    renderer = _renderer
    if renderer is None:
        return

    # ── 确保 FBO 尺寸 ──
    _ensure_fbo(vp_w, vp_h)

    # ── 绑定 Scene FBO, 清空 ──
    gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, _fbo)
    gl.glViewport(0, 0, vp_w, vp_h)
    gl.glClearColor(0.2, 0.2, 0.2, 1.0)
    gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT | gl.GL_STENCIL_BUFFER_BIT)

    # ── 深度测试 ──
    gl.glEnable(gl.GL_DEPTH_TEST)
    gl.glDepthFunc(gl.GL_LEQUAL)
    gl.glDepthMask(gl.GL_TRUE)

    # ── Stencil 预设: always pass, depth pass → replace=1 ──
    gl.glEnable(gl.GL_STENCIL_TEST)
    gl.glStencilOp(gl.GL_KEEP, gl.GL_KEEP, gl.GL_REPLACE)

    # ── 注入渲染器: 重定向实体渲染 + 被选实体 ID ──
    renderer._scene_fbo_override = _fbo
    renderer._outline_selected_ids = Outliner._active_ids


def _on_post_render(view: np.ndarray, proj: np.ndarray) -> None:
    """Post-render 回调: Outline pass (stencil) + Blit → 屏幕。

    由渲染器在 _RenderEntities 之后、_render_overlay_drawables 之前调用。
    """
    renderer = _renderer
    if renderer is None:
        return

    vp_w = renderer.viewport_width
    vp_h = renderer.viewport_height
    selected = Outliner._active_ids

    if selected:
        # ── 重新绑定 Scene FBO ──
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, _fbo)
        gl.glViewport(0, 0, vp_w, vp_h)

        # ══════════════════════════════════════════════════
        # Outline Pass: stencil NOTEQUAL → 轮廓像素
        # ══════════════════════════════════════════════════
        gl.glStencilFunc(gl.GL_NOTEQUAL, 1, 0xFF)
        gl.glStencilMask(0x00)
        gl.glStencilOp(gl.GL_KEEP, gl.GL_KEEP, gl.GL_KEEP)
        gl.glDepthMask(gl.GL_FALSE)

        if Outliner._xray:
            gl.glDisable(gl.GL_DEPTH_TEST)
        else:
            gl.glEnable(gl.GL_DEPTH_TEST)
            gl.glDepthFunc(gl.GL_LEQUAL)

        # ── 轮廓着色器 ──
        gl.glUseProgram(_prog_outline)
        loc_view = gl.glGetUniformLocation(_prog_outline, 'uView')
        loc_proj = gl.glGetUniformLocation(_prog_outline, 'uProj')
        loc_color = gl.glGetUniformLocation(_prog_outline, 'uOutlineColor')
        loc_scale = gl.glGetUniformLocation(_prog_outline, 'uOutlineScale')
        loc_model = gl.glGetUniformLocation(_prog_outline, 'uModel')

        view_f32 = np.ascontiguousarray(view.astype('float32'))
        proj_f32 = np.ascontiguousarray(proj.astype('float32'))

        if loc_view >= 0:
            gl.glUniformMatrix4fv(loc_view, 1, gl.GL_FALSE, view_f32)
        if loc_proj >= 0:
            gl.glUniformMatrix4fv(loc_proj, 1, gl.GL_FALSE, proj_f32)
        if loc_color >= 0:
            gl.glUniform3f(loc_color, *Outliner._color)
        if loc_scale >= 0:
            gl.glUniform1f(loc_scale, Outliner._scale)

        # ── 遍历被选实体, 复用其 VAO 绘制放大轮廓 ──
        for eid in selected:
            entity = renderer.registered_entities.get(eid)
            if entity is None:
                continue
            model = calculate_entity_model(
                SceneManager.GetEntityTransform(eid))
            model_f32 = np.ascontiguousarray(model.astype('float32'))
            if loc_model >= 0:
                gl.glUniformMatrix4fv(loc_model, 1, gl.GL_FALSE, model_f32)

            gl.glBindVertexArray(entity.vao)
            mesh_data = renderer.registered_meshes[entity.mesh_id]
            gl.glDrawElements(
                gl.GL_TRIANGLES, mesh_data.elements_count,
                gl.GL_UNSIGNED_INT, None)
        gl.glBindVertexArray(0)

    # ── 恢复 GL 状态 ──
    gl.glStencilMask(0xFF)
    gl.glStencilFunc(gl.GL_ALWAYS, 0, 0xFF)
    gl.glDisable(gl.GL_STENCIL_TEST)
    gl.glEnable(gl.GL_DEPTH_TEST)
    gl.glDepthFunc(gl.GL_LESS)
    gl.glDepthMask(gl.GL_TRUE)
    gl.glDisable(gl.GL_BLEND)

    # ══════════════════════════════════════════════════════
    # Blit Scene FBO → 默认帧缓冲
    # ══════════════════════════════════════════════════════
    gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, 0)
    gl.glViewport(0, 0, vp_w, vp_h)
    gl.glDisable(gl.GL_DEPTH_TEST)

    gl.glUseProgram(_prog_blit)
    gl.glActiveTexture(gl.GL_TEXTURE0)
    gl.glBindTexture(gl.GL_TEXTURE_2D, _color_tex)
    loc_tex = gl.glGetUniformLocation(_prog_blit, 'uScreenTex')
    if loc_tex >= 0:
        gl.glUniform1i(loc_tex, 0)
    gl.glBindVertexArray(_vao_blit)
    gl.glDrawArrays(gl.GL_TRIANGLE_STRIP, 0, 4)
    gl.glBindVertexArray(0)

    # ── 复制深度缓冲: Scene FBO → 默认帧缓冲 ──
    #   fullscreen quad 只搬了颜色, 深度必须单独 blit,
    #   否则后续 overlay (Grid) 的深度测试会因默认FB深度为空而全部通过
    gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER, _fbo)
    gl.glBindFramebuffer(gl.GL_DRAW_FRAMEBUFFER, 0)
    gl.glBlitFramebuffer(0, 0, vp_w, vp_h, 0, 0, vp_w, vp_h,
                          gl.GL_DEPTH_BUFFER_BIT, gl.GL_NEAREST)
    gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, 0)

    # ── 恢复深度测试 (后续 overlay drawable 如 Grid 需要) ──
    gl.glEnable(gl.GL_DEPTH_TEST)
    gl.glDepthFunc(gl.GL_LESS)

    # ── 清除 FBO override (下帧由 _on_pre_render 重新设置) ──
    renderer._scene_fbo_override = 0


# ════════════════════════════════════════════════════════════════
# Outliner — 薄注册器, 仅负责注册/注销 + 线程安全选择同步
# ════════════════════════════════════════════════════════════════

class Outliner:
    """选中实体轮廓高亮 — stencil 管线注入。

    职责分离 (对齐 Grid):
      模块顶层    — 着色器 / FBO 管理 / pre-post 回调 (纯渲染逻辑)
      Outliner 类 — 注册/注销 + 选择状态同步 (编辑器桥梁)

    线程安全:
      主线程 (OnEvent):
        - set_selected_entities(ids) → 仅存储 _pending_ids
        - configure(...)             → 更新视觉参数

      渲染线程 (OnRender → _sync):
        - _sync() → _pending_ids → _active_ids
        - pre/post 回调自动读取 _active_ids / _color / _scale / _xray
    """

    _pending_ids: set[int] | None = None   # 主线程写入
    _active_ids: set[int] = set()          # 渲染线程读取 (pre/post 回调使用)

    _color: tuple = OUTLINE_COLOR           # 渲染线程读取
    _scale: float = OUTLINE_SCALE           # 渲染线程读取
    _xray: bool = OUTLINE_XRAY              # 渲染线程读取

    # ════════════════════════════════════════════════════════
    # 注册 / 注销
    # ════════════════════════════════════════════════════════

    @classmethod
    def register_to(cls, renderer: type) -> None:
        """向渲染器注册 pre/post 回调, 编译着色器, 创建 GPU 资源。

        调用时机: EditorLayer.OnAttach() (渲染线程, GL 上下文有效)。

        Args:
            renderer: openGLRenderer 类 (非实例)
        """
        global _renderer
        _renderer = renderer

        # 注册 pre-render 回调 (Scene FBO 创建 + stencil 预设)
        renderer.register_pre_overlay_callback(_on_pre_render)

        # 注册 post-render 回调 (outline pass + blit)
        renderer.register_overlay_callback(_on_post_render)

        # 编译着色器 + 创建全屏四边形
        _compile_shaders()
        _create_blit_quad()

    @classmethod
    def unregister_from(cls, renderer: type) -> None:
        """取消注册回调并释放 GPU 资源。

        调用时机: EditorLayer.OnDetach() (渲染线程)。
        """
        global _renderer
        renderer.unregister_pre_overlay_callback(_on_pre_render)
        renderer.unregister_overlay_callback(_on_post_render)
        _release_shaders()
        _release_fbo()
        _renderer = None
        cls._pending_ids = None
        cls._active_ids.clear()

    # ════════════════════════════════════════════════════════
    # 主线程 API (零 GL 调用)
    # ════════════════════════════════════════════════════════

    @classmethod
    def set_selected_entities(cls, entity_ids: set[int]) -> None:
        """请求选中实体 (主线程, 零 GL 调用)。

        Args:
            entity_ids: 被选中实体的 ID 集合 (空集 = 无轮廓)
        """
        cls._pending_ids = set(entity_ids) if entity_ids else set()

    @classmethod
    def clear(cls) -> None:
        """请求清除所有轮廓 (主线程, 零 GL)。"""
        cls._pending_ids = set()

    @classmethod
    def configure(
        cls,
        color: tuple[float, float, float] = None,
        scale: float = None,
        xray: bool = None,
    ) -> None:
        """更新轮廓视觉参数 (主线程安全)。

        Args:
            color: RGB 轮廓颜色 (0~1)
            scale: 轮廓放大系数 (1.05 = 5% 放大)
            xray: 穿透模式 (True = 轮廓始终可见)
        """
        if color is not None:
            cls._color = tuple(color)
        if scale is not None:
            cls._scale = float(scale)
        if xray is not None:
            cls._xray = bool(xray)

    # ════════════════════════════════════════════════════════
    # 渲染线程 API
    # ════════════════════════════════════════════════════════

    @classmethod
    def _sync(cls, renderer: type = None) -> None:
        """处理待处理的选择请求 (渲染线程)。

        由 EditorLayer.OnRender() 每帧调用。
        仅同步 _pending_ids → _active_ids, 零 GL 调用。
        实际的轮廓渲染由 pre/post 回调自动完成。
        """
        if cls._pending_ids is None:
            return
        cls._active_ids = cls._pending_ids
        cls._pending_ids = None

    @classmethod
    def _release(cls, renderer: type = None) -> None:
        """释放状态 (渲染线程, OnDetach 时调用)。"""
        cls._pending_ids = None
        cls._active_ids.clear()
