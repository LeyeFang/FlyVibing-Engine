"""
Test: 窗口模式 + 透明背景 交互测试
═══════════════════════════════════════════════════════════════

功能:
  ★ 启动时通过 input() 选择窗口模式 (Windowed / Borderless / Fullscreen)
  ★ 启动时通过 input() 选择是否透明背景
  ★ 使用主线 glfwWindow 基础设施 (WindowMode, _transparent, set_window_mode)
  ★ 窗口中央渲染红色三角形作为可见内容
  ★ 运行时按键切换窗口模式 (不改变透明设置):
      F1 — Windowed
      F2 — Borderless
      F3 — Fullscreen
  ★ ESC — 退出

运行: python Test/Application/Core/Window/test_window_modes.py
"""

from __future__ import annotations
import sys, os
_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, '_path_setup.py')):
    _d = os.path.dirname(_d)
if _d: sys.path.insert(0, _d)
import _path_setup  # noqa: E402

import ctypes
import numpy as np
import glfw
from OpenGL import GL as gl
from OpenGL.GL import shaders

from Application.Core.Window.glfwWindow import glfwWindow, WindowMode


# ═══════════════════════════════════════════════════════════════
# 测试用窗口子类 — 仅覆写 OpenGL 上下文提示
# ═══════════════════════════════════════════════════════════════

class _TestWindow(glfwWindow):
    """测试窗口 — 复用主线 InputPipeline + 点击穿透，覆写命中测试和按键钩子。"""

    @classmethod
    def _set_window_hints(cls) -> None:
        glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 4)
        glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 4)
        glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
        glfw.window_hint(glfw.OPENGL_FORWARD_COMPAT, glfw.TRUE)

    # ── 点击穿透: 光标命中三角形时捕获鼠标，透明背景穿透 ──

    @classmethod
    def _is_click_through_target(cls, ndc_x: float, ndc_y: float) -> bool:
        """命中三角形 → 捕获鼠标 (不穿透); 透明背景 → 穿透。"""
        return _point_in_triangle_ndc(ndc_x, ndc_y)

    # ── 按键钩子: 处理 F1/F2/F3/ESC, 其余键忽略 ──

    @classmethod
    def _make_key_hook(cls):
        _kls = cls
        def hook(key, scancode, action, mods):
            if action != glfw.PRESS:
                return
            if key == glfw.KEY_ESCAPE:
                glfw.set_window_should_close(_kls.glfw_window)
            elif key == glfw.KEY_F1:
                print("\n[KEY] F1 → Windowed")
                _kls.set_window_mode(WindowMode.WINDOWED)
            elif key == glfw.KEY_F2:
                print("\n[KEY] F2 → Borderless")
                _kls.set_window_mode(WindowMode.BORDERLESS)
            elif key == glfw.KEY_F3:
                print("\n[KEY] F3 → Fullscreen")
                _kls.set_window_mode(WindowMode.FULLSCREEN)
            # 其余键: 不 Pack 事件 (无 engine), 静默忽略
        return hook


# ═══════════════════════════════════════════════════════════════
# Shader 源码 — GLSL 440 core
# ═══════════════════════════════════════════════════════════════

_VERTEX_SHADER_SRC = """#version 440 core
layout(location = 0) in vec2 aPos;
void main() {
    gl_Position = vec4(aPos, 0.0, 1.0);
}
"""

_FRAGMENT_SHADER_SRC = """#version 440 core
out vec4 FragColor;
void main() {
    FragColor = vec4(1.0, 0.0, 0.0, 1.0);
}
"""

_TRIANGLE_NDC = np.array([
    [ 0.0,  0.6],
    [-0.6, -0.4],
    [ 0.6, -0.4],
], dtype=np.float32)
_TRIANGLE_VERTICES = _TRIANGLE_NDC.flatten()


def _point_in_triangle_ndc(px: float, py: float) -> bool:
    """重心坐标法: 判断 NDC 点是否在三角形内。"""
    a, b, c = _TRIANGLE_NDC[0], _TRIANGLE_NDC[1], _TRIANGLE_NDC[2]
    v0 = c - a
    v1 = b - a
    v2 = np.array([px, py], dtype=np.float32) - a
    dot00 = float(np.dot(v0, v0))
    dot01 = float(np.dot(v0, v1))
    dot02 = float(np.dot(v0, v2))
    dot11 = float(np.dot(v1, v1))
    dot12 = float(np.dot(v1, v2))
    denom = dot00 * dot11 - dot01 * dot01
    if abs(denom) < 1e-10:
        return False
    inv = 1.0 / denom
    u = (dot11 * dot02 - dot01 * dot12) * inv
    v = (dot00 * dot12 - dot01 * dot02) * inv
    return u >= 0.0 and v >= 0.0 and (u + v) <= 1.0


# ═══════════════════════════════════════════════════════════════
# 辅助
# ═══════════════════════════════════════════════════════════════

def _compile_shader_program() -> int:
    vs = shaders.compileShader(_VERTEX_SHADER_SRC, gl.GL_VERTEX_SHADER)
    fs = shaders.compileShader(_FRAGMENT_SHADER_SRC, gl.GL_FRAGMENT_SHADER)
    prog = shaders.compileProgram(vs, fs)
    gl.glDeleteShader(vs)
    gl.glDeleteShader(fs)
    return prog


def _setup_vao(prog: int) -> int:
    vao = gl.glGenVertexArrays(1)
    vbo = gl.glGenBuffers(1)
    gl.glBindVertexArray(vao)
    gl.glBindBuffer(gl.GL_ARRAY_BUFFER, vbo)
    gl.glBufferData(
        gl.GL_ARRAY_BUFFER, _TRIANGLE_VERTICES.nbytes,
        _TRIANGLE_VERTICES, gl.GL_STATIC_DRAW,
    )
    pos_loc = gl.glGetAttribLocation(prog, "aPos")
    gl.glVertexAttribPointer(pos_loc, 2, gl.GL_FLOAT, gl.GL_FALSE, 2 * 4, ctypes.c_void_p(0))
    gl.glEnableVertexAttribArray(pos_loc)
    gl.glBindVertexArray(0)
    return vao


# ═══════════════════════════════════════════════════════════════
# 用户输入 — 启动前选择
# ═══════════════════════════════════════════════════════════════

def _ask_mode() -> WindowMode:
    print()
    print("=" * 50)
    print("  Window Mode Selection")
    print("=" * 50)
    print("  [1] Windowed    — normal window with borders")
    print("  [2] Borderless  — fullscreen window, no borders")
    print("  [3] Fullscreen  — exclusive fullscreen")
    print("-" * 50)
    while True:
        try:
            choice = input("  Choose [1/2/3] (default=1): ").strip() or "1"
            return {1: WindowMode.WINDOWED, 2: WindowMode.BORDERLESS, 3: WindowMode.FULLSCREEN}[int(choice)]
        except (ValueError, KeyError):
            print("  Invalid — enter 1, 2, or 3")


def _ask_transparent() -> bool:
    print()
    print("-" * 50)
    while True:
        ans = input("  Transparent background? [y/N]: ").strip().lower()
        if ans in ("y", "yes", "n", "no", ""):
            return ans in ("y", "yes")
        print("  Invalid — enter y or n")


# ═══════════════════════════════════════════════════════════════
# main
# ═══════════════════════════════════════════════════════════════

def main() -> None:
    # ── 0. 设置全局事件回调为 no-op (无 Engine 时安全吞掉所有事件) ──
    from Application.Core.Events.Event import BindPackCallback
    BindPackCallback(lambda instance: None)

    # ── 1. 用户选择 ──
    mode = _ask_mode()
    transparent = _ask_transparent()

    # ── 2. 设置窗口标志 ──
    _TestWindow._window_mode = mode
    _TestWindow._transparent = transparent
    _TestWindow._click_through = transparent  # 透明 → 启用穿透
    _TestWindow._topmost = transparent        # 透明 → 窗口置顶
    _TestWindow._window_title = "Window Mode Test — Red Triangle"

    # ── 3. 创建窗口 (使用主线 Create, 包含完整 InputPipeline) ──
    _TestWindow.Create()
    glfw.make_context_current(_TestWindow.glfw_window)
    glfw.swap_interval(1)

    # ── 4. 编译 shader + VAO ──
    prog = _compile_shader_program()
    vao = _setup_vao(prog)

    # ── 5. 打印操作说明 ──
    print()
    print("=" * 50)
    print(f"  Initial mode: {mode.value}")
    print(f"  Transparent:  {'YES' if transparent else 'NO'}")
    print(f"  Click-through: {'YES (triangle=capture, bg=pass-through)' if transparent else 'NO'}")
    print("=" * 50)
    print("  F1 — Windowed")
    print("  F2 — Borderless")
    print("  F3 — Fullscreen")
    print("  ESC — Exit")
    print("=" * 50)
    print()

    # ── 6. 主循环 (使用主线 Update, 包含点击穿透) ──
    frame = 0
    while not glfw.window_should_close(_TestWindow.glfw_window):
        frame += 1
        _TestWindow.Update()

        # 渲染
        fbw, fbh = glfw.get_framebuffer_size(_TestWindow.glfw_window)
        gl.glViewport(0, 0, fbw, fbh)
        gl.glClearColor(0.0, 0.0, 0.0, 0.0)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)

        gl.glUseProgram(prog)
        gl.glBindVertexArray(vao)
        gl.glDrawArrays(gl.GL_TRIANGLES, 0, 3)

        glfw.swap_buffers(_TestWindow.glfw_window)

        # 每 300 帧打印状态
        if frame % 300 == 1 and frame > 1:
            m = _TestWindow.get_window_mode()
            print(f"  [F{frame:04d}] mode={m.value}")

    # ── 7. 清理 ──
    gl.glDeleteVertexArrays(1, [vao])
    gl.glDeleteProgram(prog)
    _TestWindow.Therminate()
    glfw.terminate()
    print("\n[Test] Exited")


if __name__ == "__main__":
    main()
