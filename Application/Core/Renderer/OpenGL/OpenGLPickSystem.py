"""
OpenGLPickSystem — PyOpenGL 拾取系统 (Mixin, 通过 MRO 访问资源注册表)。

职责:
  - 持久拾取 FBO 的创建/重建/销毁
  - Entity pick pass: 每帧将实体 ID 渲染到 pick FBO
  - Overlay pick pass: 每帧将 overlay 类型/ID 渲染到 pick FBO
  - 像素读回 + 缓存 (render thread 写入, main thread 零 GL 读取)
  - 公共拾取 API: update_pick_mouse / get_pick / pick_at

设计:
  - Mixin 模式: 通过 cls.registered_entities / cls._overlay_gpu_resources 访问资源
  - 须置于 OpenGLResourceManager 之后的 MRO 位置
  - 着色器源码内嵌 (编译时无外部文件依赖)

MRO 约定:
  openGLRenderer(..., OpenGLResourceManager, OpenGLPickSystem, ...)
  → cls.registered_entities 由 OpenGLResourceManager 提供
  → cls._overlay_gpu_resources 由 OpenGLResourceManager 提供
"""

from __future__ import annotations
import numpy as np
from OpenGL import GL as gl

from Application.Core.Renderer.OpenGL.OpenGLUtils import OpenGLUtils
from Application.Core.Scene.SceneManager import SceneManager


class OpenGLPickSystem:
    """PyOpenGL 拾取系统 — 零延迟 GPU 拾取。"""

    # ════════════════════════════════════════════════════════════
    # 拾取着色器源码
    # ════════════════════════════════════════════════════════════

    # ── Entity 拾取: ID → RGB24 ──
    _PICK_VS: str = """#version 440 core
layout (location = 0) in vec3 aPos;
uniform mat4 uModel;
uniform mat4 uView;
uniform mat4 uProj;
void main() {
    gl_Position = uProj * uView * uModel * vec4(aPos, 1.0);
}
"""

    _PICK_FS: str = """#version 440 core
uniform float uPickID;
out vec4 fragColor;
void main() {
    float id = uPickID;
    float r = mod(id, 256.0) / 255.0;
    float g = mod(floor(id / 256.0), 256.0) / 255.0;
    float b = floor(id / 65536.0) / 255.0;
    fragColor = vec4(r, g, b, 1.0);
}
"""

    # ── Overlay 拾取: R=0(标记), G=type, B=id ──
    _OVERLAY_PICK_VS: str = """#version 440 core
layout (location = 0) in vec3 aPos;
layout (location = 0) uniform int uIsNDC;
layout (location = 1) uniform mat4 uModel;
layout (location = 5) uniform mat4 uViewProj;
layout (location = 9) uniform mat4 uProj;
void main() {
    if (uIsNDC == 1)
        gl_Position = uProj * uModel * vec4(aPos, 1.0);
    else
        gl_Position = uViewProj * uModel * vec4(aPos, 1.0);
}
"""

    _OVERLAY_PICK_FS: str = """#version 440 core
layout (location = 10) uniform float uPickType;
layout (location = 11) uniform float uPickID;
out vec4 fragColor;
void main() {
    fragColor = vec4(0.0, uPickType / 255.0, uPickID / 255.0, 1.0);
}
"""

    # ════════════════════════════════════════════════════════════
    # 类级状态
    # ════════════════════════════════════════════════════════════

    # ── 持久拾取 FBO (每帧更新, 点击时即时读回) ──
    _pick_fbo: int = 0
    _pick_color: int = 0
    _pick_depth: int = 0
    _pick_prog: int = 0
    _pick_fbo_w: int = 0
    _pick_fbo_h: int = 0

    # ── Overlay pick 资源 ──
    _overlay_pick_prog: int = 0
    _overlay_pick_key_map: dict[tuple[int, int], str] = {}

    # ── 零延迟拾取缓存: render thread 每帧预读, main thread 即时获取 ──
    _pick_mouse: tuple = (0, 0)  # 鼠标位置, main thread 每帧更新
    _pick_cache: int = -1         # entity_id, render thread 每帧刷新
    _pick_overlay_key: str | None = None  # 当前鼠标下 overlay 的 key

    # ════════════════════════════════════════════════════════════
    # 初始化
    # ════════════════════════════════════════════════════════════

    @classmethod
    def init_pick(cls, window_w: int, window_h: int) -> None:
        """编译拾取着色器 + 创建拾取 FBO。

        调用时机: openGLRenderer.Create()，渲染线程，GL 上下文已绑定。

        Args:
            window_w, window_h: 初始窗口尺寸
        """
        cls._pick_prog = OpenGLUtils.compile_program(cls._PICK_VS, cls._PICK_FS)
        cls._overlay_pick_prog = OpenGLUtils.compile_program(
            cls._OVERLAY_PICK_VS, cls._OVERLAY_PICK_FS)
        cls._rebuild_pick_fbo(window_w, window_h)

    # ════════════════════════════════════════════════════════════
    # FBO 管理
    # ════════════════════════════════════════════════════════════

    @classmethod
    def rebuild_pick_fbo(cls, w: int, h: int) -> None:
        """重建拾取 FBO (resize 时调用)。"""
        cls._rebuild_pick_fbo(w, h)

    @classmethod
    def _rebuild_pick_fbo(cls, w: int, h: int) -> None:
        """重建拾取 FBO (内部实现)。"""
        if cls._pick_fbo:
            gl.glDeleteFramebuffers(1, [cls._pick_fbo])
        if cls._pick_color:
            gl.glDeleteTextures(1, [cls._pick_color])
        if cls._pick_depth:
            gl.glDeleteRenderbuffers(1, [cls._pick_depth])
        cls._pick_fbo = gl.glGenFramebuffers(1)
        cls._pick_color = gl.glGenTextures(1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, cls._pick_color)
        gl.glTexImage2D(
            gl.GL_TEXTURE_2D,
            0,
            gl.GL_RGBA8,
            w, h,
            0,
            gl.GL_RGBA,
            gl.GL_UNSIGNED_BYTE,
            None
        )
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_NEAREST)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST)
        cls._pick_depth = gl.glGenRenderbuffers(1)
        gl.glBindRenderbuffer(gl.GL_RENDERBUFFER, cls._pick_depth)
        gl.glRenderbufferStorage(gl.GL_RENDERBUFFER, gl.GL_DEPTH_COMPONENT24, w, h)
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, cls._pick_fbo)
        gl.glFramebufferTexture2D(
            gl.GL_FRAMEBUFFER,
            gl.GL_COLOR_ATTACHMENT0,
            gl.GL_TEXTURE_2D,
            cls._pick_color,
            0)
        gl.glFramebufferRenderbuffer(
            gl.GL_FRAMEBUFFER,
            gl.GL_DEPTH_ATTACHMENT,
            gl.GL_RENDERBUFFER,
            cls._pick_depth)
        if gl.glCheckFramebufferStatus(gl.GL_FRAMEBUFFER) != gl.GL_FRAMEBUFFER_COMPLETE:
            raise RuntimeError("Pick FBO incomplete")
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, 0)
        cls._pick_fbo_w, cls._pick_fbo_h = w, h

    @classmethod
    def _destroy_pick(cls) -> None:
        """销毁拾取系统的 GPU 资源 — 渲染线程、GL 上下文有效时调用。"""
        if cls._pick_fbo:
            gl.glDeleteFramebuffers(1, [cls._pick_fbo])
            cls._pick_fbo = 0
        if cls._pick_color:
            gl.glDeleteTextures(1, [cls._pick_color])
            cls._pick_color = 0
        if cls._pick_depth:
            gl.glDeleteRenderbuffers(1, [cls._pick_depth])
            cls._pick_depth = 0
        if cls._pick_prog:
            gl.glDeleteProgram(cls._pick_prog)
            cls._pick_prog = 0
        if cls._overlay_pick_prog:
            gl.glDeleteProgram(cls._overlay_pick_prog)
            cls._overlay_pick_prog = 0
        cls._overlay_pick_key_map.clear()
        cls._pick_cache = -1
        cls._pick_overlay_key = None

    # ════════════════════════════════════════════════════════════
    # Entity Pick Pass
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _render_entities_pick_pass(
        cls,
        view: np.ndarray,
        proj: np.ndarray,
    ) -> None:
        """每帧将实体 ID 渲染到拾取 FBO — 通过 MRO 访问 cls.registered_entities。"""
        entities = SceneManager.GetRenderableEntities()
        if not entities:
            # Only print when verbose debugging is needed
            # print("[PICK-DBG] NO renderable entities, skipping pick pass")
            cls._finalize_pick_read()
            return
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, cls._pick_fbo)
        gl.glViewport(0, 0, cls._pick_fbo_w, cls._pick_fbo_h)
        gl.glClearColor(0.0, 0.0, 0.0, 1.0)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glDepthFunc(gl.GL_LESS)
        gl.glDepthMask(gl.GL_TRUE)
        gl.glDisable(gl.GL_BLEND)
        gl.glUseProgram(cls._pick_prog)
        loc_model = gl.glGetUniformLocation(cls._pick_prog, 'uModel')
        loc_view = gl.glGetUniformLocation(cls._pick_prog, 'uView')
        loc_proj = gl.glGetUniformLocation(cls._pick_prog, 'uProj')
        loc_id = gl.glGetUniformLocation(cls._pick_prog, 'uPickID')
        view_f32 = np.ascontiguousarray(view.astype('float32'))
        proj_f32 = np.ascontiguousarray(proj.astype('float32'))
        for entity_id in entities:
            gpu = cls.registered_entities.get(entity_id)
            if gpu is None:
                continue
            model = SceneManager.GetEntityModelMatrix(entity_id)
            model_f32 = np.ascontiguousarray(model.astype('float32'))
            if loc_model >= 0:
                gl.glUniformMatrix4fv(loc_model, 1, gl.GL_FALSE, model_f32)
            if loc_view >= 0:
                gl.glUniformMatrix4fv(loc_view, 1, gl.GL_FALSE, view_f32)
            if loc_proj >= 0:
                gl.glUniformMatrix4fv(loc_proj, 1, gl.GL_FALSE, proj_f32)
            if loc_id >= 0:
                gl.glUniform1f(loc_id, float(entity_id))
            gl.glBindVertexArray(gpu.vao)
            mesh_data = cls.registered_meshes[gpu.mesh_id]
            gl.glDrawElements(
                gl.GL_TRIANGLES,
                mesh_data.elements_count,
                gl.GL_UNSIGNED_INT,
                None
            )
        gl.glBindVertexArray(0)
        # FBO 保持绑定 → _render_overlays_pick_pass 续用

    # ════════════════════════════════════════════════════════════
    # Overlay Pick Pass
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _render_overlays_pick_pass(
        cls,
        view: np.ndarray,
        proj: np.ndarray,
        vp_w: int,
        vp_h: int,
    ) -> None:
        """渲染可拾取 overlay → pick FBO — 通过 MRO 访问 cls._overlay_gpu_resources。"""
        pickable = [(k, g) for k, g in cls._overlay_gpu_resources.items() if g.pick_type > 0]
        if not pickable:
            cls._finalize_pick_read()
            return
        vp_mat = np.ascontiguousarray((proj @ view).astype('float32'))
        gl.glUseProgram(cls._overlay_pick_prog)
        loc_model = gl.glGetUniformLocation(cls._overlay_pick_prog, 'uModel')
        loc_ndc  = gl.glGetUniformLocation(cls._overlay_pick_prog, 'uIsNDC')
        loc_vp   = gl.glGetUniformLocation(cls._overlay_pick_prog, 'uViewProj')
        loc_type = gl.glGetUniformLocation(cls._overlay_pick_prog, 'uPickType')
        loc_id   = gl.glGetUniformLocation(cls._overlay_pick_prog, 'uPickID')
        for _key, gpu in cls._overlay_gpu_resources.items():
            if gpu.pick_type <= 0:
                continue
            if loc_type >= 0:
                gl.glUniform1f(loc_type, float(gpu.pick_type))
            if loc_id >= 0:
                gl.glUniform1f(loc_id, float(gpu.pick_id))
            if gpu.ignore_scene_matrices and gpu.model_matrix_cb:
                if loc_ndc >= 0:
                    gl.glUniform1i(loc_ndc, 1)
                model = gpu.model_matrix_cb(vp_w, vp_h)
                if loc_model >= 0:
                    gl.glUniformMatrix4fv(loc_model, 1, gl.GL_TRUE,
                        np.ascontiguousarray(model.astype('float32')))
                # uProj: 若 model 已是完整 MVP (NDC), 则用 identity, 否则用正交投影
                loc_proj = gl.glGetUniformLocation(cls._overlay_pick_prog, 'uProj')
                if loc_proj >= 0:
                    if getattr(gpu, 'model_is_ndc', False):
                        gl.glUniformMatrix4fv(loc_proj, 1, gl.GL_TRUE,
                            np.identity(4, dtype='float32'))
                    else:
                        from Application.Core.Math.ViewGizmo import compute_ortho_proj
                        op = compute_ortho_proj(vp_w, vp_h)
                        gl.glUniformMatrix4fv(loc_proj, 1, gl.GL_TRUE,
                            np.ascontiguousarray(op.astype('float32')))
            else:
                if loc_ndc >= 0:
                    gl.glUniform1i(loc_ndc, 0)
                if loc_vp >= 0:
                    gl.glUniformMatrix4fv(loc_vp, 1, gl.GL_FALSE, vp_mat)
                if loc_model >= 0:
                    gl.glUniformMatrix4fv(loc_model, 1, gl.GL_FALSE,
                        np.identity(4, dtype='float32'))
            # ── 面剔除: 与 visual pass 保持一致 ──
            if gpu.cull_face:
                gl.glEnable(gl.GL_CULL_FACE)
                gl.glCullFace(gl.GL_BACK)
                gl.glFrontFace(gl.GL_CCW)
            else:
                gl.glDisable(gl.GL_CULL_FACE)
            gl.glDepthFunc(gl.GL_LEQUAL)
            gl.glBindVertexArray(gpu.vao)
            gl.glDrawElements(gpu.draw_mode, gpu.elements_count,
                              gl.GL_UNSIGNED_INT, None)
        gl.glBindVertexArray(0)
        gl.glDisable(gl.GL_CULL_FACE)
        gl.glDepthFunc(gl.GL_LESS)
        # ── 每帧预读 → _pick_cache + _pick_overlay_key ──
        cls._finalize_pick_read()

    @classmethod
    def _finalize_pick_read(cls) -> None:
        """解绑 pick FBO 并预读鼠标位置像素 → 缓存。

        render thread 专用, 包含 glFinish + glReadPixels。
        main thread 通过 get_pick() / pick_at() 零 GL 读取。
        """
        sx, sy = cls._pick_mouse
        px = max(0, min(int(round(sx)), cls._pick_fbo_w - 1))
        py = max(0, min(int(round(sy)), cls._pick_fbo_h - 1))
        gl_y = cls._pick_fbo_h - 1 - py
        gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER, cls._pick_fbo)
        gl.glReadBuffer(gl.GL_COLOR_ATTACHMENT0)
        gl.glFinish()
        pixel = (gl.GLubyte * 4)()
        gl.glReadPixels(px, gl_y, 1, 1, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, pixel)
        gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER, 0)
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, 0)
        r, g, b = int(pixel[0]), int(pixel[1]), int(pixel[2])
        if r > 0:
            cls._pick_cache = r | (g << 8) | (b << 16)
            cls._pick_overlay_key = None
        elif g > 0:
            cls._pick_cache = -1
            cls._pick_overlay_key = cls._overlay_pick_key_map.get((g, b))
        else:
            cls._pick_cache = -1
            cls._pick_overlay_key = None

    # ════════════════════════════════════════════════════════════
    # 公共拾取 API — main thread 安全, 零 GL 调用
    # ════════════════════════════════════════════════════════════

    @classmethod
    def update_pick_mouse(cls, x: float, y: float) -> None:
        """更新鼠标位置 (main thread 每帧调用)。

        Args:
            x, y: 屏幕像素坐标
        """
        cls._pick_mouse = (x, y)

    @classmethod
    def get_pick(cls) -> int:
        """获取当前鼠标下的 entity_id (main thread, 即时返回, 零阻塞)。

        render thread 每帧预读 _pick_mouse 位置的像素到 _pick_cache,
        因此返回值最多落后 1 帧 (~3ms), 人眼完全不可感知。
        """
        return cls._pick_cache

    @classmethod
    def pick_at(cls, sx: float, sy: float) -> tuple:
        """统一拾取 → (type, value) — 返回渲染线程预读的缓存结果。

        注意: 当前实现返回的是 _pick_mouse 位置的缓存,
        不区分 sx,sy (适用于鼠标点击场景, 点击前鼠标已就位)。

        Returns:
            ('entity', entity_id) | ('overlay', key) | (None, None)
        """
        if cls._pick_cache >= 0:
            return ('entity', cls._pick_cache)
        if cls._pick_overlay_key is not None:
            return ('overlay', cls._pick_overlay_key)
        return (None, None)

    # ════════════════════════════════════════════════════════════
    # Overlay pick key 映射 (由 openGLRenderer.register_overlay_drawable 调用)
    # ════════════════════════════════════════════════════════════

    @classmethod
    def register_pick_key(cls, pick_type: int, pick_id: int, key: str) -> None:
        """注册 overlay pick key → (type, id) 映射。

        调用时机: openGLRenderer.register_overlay_drawable() 中, pick_type > 0 时。
        """
        cls._overlay_pick_key_map[(pick_type, pick_id)] = key

    @classmethod
    def unregister_pick_key(cls, key: str) -> None:
        """取消注册 overlay pick key 映射。"""
        to_remove = [k for k, v in cls._overlay_pick_key_map.items() if v == key]
        for k in to_remove:
            del cls._overlay_pick_key_map[k]
