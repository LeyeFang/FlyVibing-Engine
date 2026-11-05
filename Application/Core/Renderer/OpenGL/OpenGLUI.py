"""OpenGLUI — 运行时 UI pass（屏幕空间矩形/文本，永远画在场景与 overlay 之上）。

输入是 `Application/Core/UI/layout.UIQuad` 的元组（纯数据，渲染线程消费）：
  - `image is None` → 纯色矩形
  - `image` 为 (H, W, 4) uint8 → 纹理矩形（`color` 作乘色）

设计取舍（M0）：
  - 每个 quad 一次 draw call（对话框就 6~8 个 quad；批量/合批等真需要时再加）；
  - 纹理按 `key` 缓存，文本内容变了才重新上传；
  - 关深度、开 alpha 混合、关切面；不写深度（UI 不需要参与场景排序）。
"""

from __future__ import annotations

import ctypes

import numpy as np
from OpenGL import GL as gl

from Application.Core.Renderer.OpenGL.OpenGLUtils import OpenGLUtils

_VS = """#version 440 core
layout(location = 0) in vec2 aPos;   // 0..1 quad 空间
layout(location = 1) in vec2 aUV;
uniform vec2 uOffset;    // 屏幕像素（左上原点）
uniform vec2 uSize;      // 屏幕像素
uniform vec2 uViewport;  // 屏幕像素
uniform vec4 uColor;
out vec2 vUV;
out vec4 vColor;
void main() {
    vec2 px = uOffset + aPos * uSize;
    vec2 ndc = vec2(px.x / uViewport.x * 2.0 - 1.0,
                    1.0 - px.y / uViewport.y * 2.0);
    gl_Position = vec4(ndc, 0.0, 1.0);
    vUV = aUV;
    vColor = uColor;
}
"""

_FS = """#version 440 core
in vec2 vUV;
in vec4 vColor;
uniform sampler2D uTex;
uniform int uUseTex;
out vec4 FragColor;
void main() {
    vec4 c = uUseTex == 1 ? texture(uTex, vUV) : vec4(1.0);
    FragColor = c * vColor;
}
"""


class OpenGLUI:
    """UI 叠加层渲染器（组合进 OpenGLRenderer）。"""

    def __init__(self) -> None:
        self._prog: int = 0
        self._vao: int = 0
        self._vbo: int = 0
        self._textures: dict[str, tuple[int, int, int]] = {}   # key → (tex, w, h)
        self._quad_count: int = 0
        self._last_viewport: tuple[int, int] = (0, 0)

    # ── 生命周期 ────────────────────────────────────────────

    def _ensure_program(self) -> None:
        if self._prog:
            return
        self._prog = OpenGLUtils.compile_program(_VS, _FS)
        # 单位 quad：位置 (0..1) + uv (0..1)，TRIANGLE_STRIP
        verts = np.array([
            0.0, 0.0, 0.0, 0.0,
            1.0, 0.0, 1.0, 0.0,
            0.0, 1.0, 0.0, 1.0,
            1.0, 1.0, 1.0, 1.0,
        ], dtype=np.float32)
        self._vao = gl.glGenVertexArrays(1)
        self._vbo = gl.glGenBuffers(1)
        gl.glBindVertexArray(self._vao)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._vbo)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, verts.nbytes, verts, gl.GL_STATIC_DRAW)
        stride = 4 * 4
        gl.glEnableVertexAttribArray(0)
        gl.glVertexAttribPointer(0, 2, gl.GL_FLOAT, gl.GL_FALSE, stride, ctypes.c_void_p(0))
        gl.glEnableVertexAttribArray(1)
        gl.glVertexAttribPointer(1, 2, gl.GL_FLOAT, gl.GL_FALSE, stride,
                                 ctypes.c_void_p(2 * 4))
        gl.glBindVertexArray(0)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, 0)

    def destroy(self) -> None:
        for tex, _w, _h in self._textures.values():
            gl.glDeleteTextures([tex])
        self._textures.clear()
        if self._vbo:
            gl.glDeleteBuffers(1, [self._vbo])
            self._vbo = 0
        if self._vao:
            gl.glDeleteVertexArrays(1, [self._vao])
            self._vao = 0
        if self._prog:
            gl.glDeleteProgram(self._prog)
            self._prog = 0

    # ── 纹理缓存 ────────────────────────────────────────────

    def _texture_for(self, quad) -> int:
        key = str(getattr(quad, "key", "") or "")
        entry = self._textures.get(key)
        if entry is not None:
            return entry[0]
        image = getattr(quad, "image", None)
        if image is None or not key:
            return 0
        arr = np.asarray(image)
        if arr.ndim != 3 or arr.shape[2] != 4:
            return 0
        h, w = int(arr.shape[0]), int(arr.shape[1])
        tex = int(gl.glGenTextures(1))
        gl.glBindTexture(gl.GL_TEXTURE_2D, tex)
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA8, w, h, 0,
                        gl.GL_RGBA, gl.GL_UNSIGNED_BYTE,
                        np.ascontiguousarray(arr, dtype=np.uint8).tobytes())
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_CLAMP_TO_EDGE)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, gl.GL_CLAMP_TO_EDGE)
        gl.glBindTexture(gl.GL_TEXTURE_2D, 0)
        self._textures[key] = (tex, w, h)
        return tex

    # ── 绘制 ────────────────────────────────────────────────

    def render(self, quads, viewport_w: int, viewport_h: int) -> None:
        """渲染一帧 UI（`quads` 为空时立即返回）。"""
        self._quad_count = 0
        if not quads or viewport_w <= 0 or viewport_h <= 0:
            return
        self._ensure_program()
        self._last_viewport = (int(viewport_w), int(viewport_h))

        prog = self._prog
        gl.glUseProgram(prog)
        loc_offset = gl.glGetUniformLocation(prog, "uOffset")
        loc_size = gl.glGetUniformLocation(prog, "uSize")
        loc_vp = gl.glGetUniformLocation(prog, "uViewport")
        loc_color = gl.glGetUniformLocation(prog, "uColor")
        loc_use_tex = gl.glGetUniformLocation(prog, "uUseTex")
        loc_tex = gl.glGetUniformLocation(prog, "uTex")

        gl.glUniform2f(loc_vp, float(viewport_w), float(viewport_h))
        gl.glDisable(gl.GL_DEPTH_TEST)
        gl.glDisable(gl.GL_CULL_FACE)
        gl.glEnable(gl.GL_BLEND)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
        gl.glBindVertexArray(self._vao)

        for quad in quads:
            w, h = float(getattr(quad, "w", 0.0)), float(getattr(quad, "h", 0.0))
            if w <= 0.0 or h <= 0.0:
                continue
            tex = self._texture_for(quad)
            gl.glUniform2f(loc_offset, float(getattr(quad, "x", 0.0)),
                           float(getattr(quad, "y", 0.0)))
            gl.glUniform2f(loc_size, w, h)
            color = getattr(quad, "color", (1.0, 1.0, 1.0, 1.0))
            gl.glUniform4f(loc_color, float(color[0]), float(color[1]),
                           float(color[2]), float(color[3]))
            if tex:
                gl.glActiveTexture(gl.GL_TEXTURE0)
                gl.glBindTexture(gl.GL_TEXTURE_2D, tex)
                gl.glUniform1i(loc_tex, 0)
                gl.glUniform1i(loc_use_tex, 1)
            else:
                gl.glUniform1i(loc_use_tex, 0)
            gl.glDrawArrays(gl.GL_TRIANGLE_STRIP, 0, 4)
            self._quad_count += 1

        gl.glBindVertexArray(0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, 0)
        gl.glUseProgram(0)
        gl.glDisable(gl.GL_BLEND)

    # ── 诊断 ────────────────────────────────────────────────

    def snapshot(self) -> dict:
        return {
            "available": bool(self._prog),
            "quads_drawn": int(self._quad_count),
            "textures": len(self._textures),
            "viewport": list(self._last_viewport),
        }
