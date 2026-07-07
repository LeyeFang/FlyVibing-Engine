"""
Test: 透明背景窗口 + 红色三角形覆盖渲染 + 选择性点击穿透
═══════════════════════════════════════════════════════════════

功能:
  ★ 创建透明背景的 GLFW 窗口（桌面内容穿透可见）
  ★ 在窗口中央渲染一个纯红色三角形
  ★ 点击透明背景区域 → 鼠标事件穿透到桌面下方窗口
  ★ 点击红色三角形区域 → 鼠标事件被本窗口捕获（不穿透）
  ★ 标题栏/边框/关闭按钮 始终正常工作（可拖拽、缩放、关闭）

实现原理:
  混合方案 — WS_EX_TRANSPARENT 负责真正的鼠标穿透，每帧光标轮询精细化控制：

    1. WS_EX_TRANSPARENT 是实现鼠标穿透的唯一方式（WM_NCHITTEST
       返回 HTTRANSPARENT 不会将事件路由到下方窗口）
    2. 每帧通过 glfw.get_cursor_pos()（内部调用 GetCursorPos）
       主动轮询光标位置 — 即使 WS_EX_TRANSPARENT 开启也正常工作
    3. ★ 关键顺序：先切换 WS_EX_TRANSPARENT，再 poll_events()，
       确保事件处理时窗口样式已正确
    4. 光标在非客户区（y<0 或 x<0 或超出 fb）→ 关闭穿透，
       保护标题栏、边框、关闭按钮
    5. 光标在客户区内命中三角形 → 关闭穿透，捕获点击 + 窗口置顶
    6. 光标在客户区内透明背景 → 开启穿透，事件传到后方窗口

与主线统一:
  - OpenGL 4.4 core profile
  - GLSL #version 440 core
  - GLFW 窗口管理

操作:
  点击红色三角形 → 终端输出 "Triangle clicked!"，窗口置顶
  点击窗口透明部分 → 点击穿透到后方窗口
  拖拽标题栏 / 边框缩放 / 点×关闭 → 正常工作
  ESC = 退出

运行: python Test/Application/Core/Window/test_transparent_triangle.py
"""

from __future__ import annotations
import sys, os
_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, '_path_setup.py')):
    _d = os.path.dirname(_d)
if _d: sys.path.insert(0, _d)
import _path_setup  # noqa: E402

import ctypes
from ctypes import wintypes
import numpy as np
import glfw
from OpenGL import GL as gl
from OpenGL.GL import shaders


# ═══════════════════════════════════════════════════════════════
# Win32 API — WS_EX_TRANSPARENT 切换
# ═══════════════════════════════════════════════════════════════

_user32 = ctypes.windll.user32

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020

SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_FRAMECHANGED = 0x0020
SWP_NOACTIVATE = 0x0010

_user32.GetWindowLongPtrW.restype = ctypes.c_longlong
_user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.SetWindowLongPtrW.restype = ctypes.c_longlong
_user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_longlong]
_user32.SetWindowPos.restype = wintypes.BOOL
_user32.SetWindowPos.argtypes = [
    wintypes.HWND, wintypes.HWND,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.UINT,
]


def _add_ws_transparent(hwnd: int) -> bool:
    """添加 WS_EX_TRANSPARENT → 鼠标穿透。返回 True 表示状态变更。"""
    style = _user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    if style & WS_EX_TRANSPARENT:
        return False  # 已经开启
    new_style = style | WS_EX_TRANSPARENT
    _user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, new_style)
    _user32.SetWindowPos(
        hwnd, 0, 0, 0, 0, 0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER |
        SWP_NOACTIVATE | SWP_FRAMECHANGED,
    )
    # 回读验证
    verify = _user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    if not (verify & WS_EX_TRANSPARENT):
        print(f"  ⚠ _add_ws_transparent 失败! style=0x{verify:08X}")
    return True


def _remove_ws_transparent(hwnd: int) -> bool:
    """移除 WS_EX_TRANSPARENT → 正常接收鼠标。返回 True 表示状态变更。"""
    style = _user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    if not (style & WS_EX_TRANSPARENT):
        return False  # 已经关闭
    new_style = style & ~WS_EX_TRANSPARENT
    _user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, new_style)
    _user32.SetWindowPos(
        hwnd, 0, 0, 0, 0, 0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER |
        SWP_NOACTIVATE | SWP_FRAMECHANGED,
    )
    # 回读验证
    verify = _user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    if verify & WS_EX_TRANSPARENT:
        print(f"  ⚠ _remove_ws_transparent 失败! style=0x{verify:08X}")
    return True


# ═══════════════════════════════════════════════════════════════
# Shader 源码 — GLSL 440 core (与主线统一)
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
    FragColor = vec4(1.0, 0.0, 0.0, 1.0);  // 纯红色，完全不透明
}
"""


# ═══════════════════════════════════════════════════════════════
# 三角形顶点数据 — NDC 坐标 (覆盖屏幕中央区域)
# ═══════════════════════════════════════════════════════════════

_TRIANGLE_NDC = np.array([
    [ 0.0,  0.6],   # 顶部
    [-0.6, -0.4],   # 左下
    [ 0.6, -0.4],   # 右下
], dtype=np.float32)

_TRIANGLE_VERTICES = _TRIANGLE_NDC.flatten()


# ═══════════════════════════════════════════════════════════════
# 点-三角形 碰撞检测 (重心坐标法)
# ═══════════════════════════════════════════════════════════════

def _point_in_triangle_ndc(px: float, py: float) -> bool:
    """判断 NDC 坐标 (px, py) 是否落入三角形内部。"""
    a = _TRIANGLE_NDC[0]
    b = _TRIANGLE_NDC[1]
    c = _TRIANGLE_NDC[2]

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

    inv_denom = 1.0 / denom
    u = (dot11 * dot02 - dot01 * dot12) * inv_denom
    v = (dot00 * dot12 - dot01 * dot02) * inv_denom

    return u >= 0.0 and v >= 0.0 and (u + v) <= 1.0


def _cursor_to_ndc(cursor_x: float, cursor_y: float, fbw: int, fbh: int):
    """GLFW 光标坐标 (左上原点, Y↓) → NDC (中心原点, Y↑)。"""
    ndc_x = (cursor_x / fbw) * 2.0 - 1.0
    ndc_y = 1.0 - (cursor_y / fbh) * 2.0
    return ndc_x, ndc_y


# ═══════════════════════════════════════════════════════════════
# 辅助函数
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
# main
# ═══════════════════════════════════════════════════════════════

def main() -> None:
    # ── 1. 初始化 GLFW ──────────────────────────────────────────
    if not glfw.init():
        raise RuntimeError("glfw.init() 失败")

    # ── 2. 窗口 hints（与主线统一的 OpenGL 4.4 core + 透明帧缓冲） ──
    glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 4)
    glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 4)
    glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
    glfw.window_hint(glfw.OPENGL_FORWARD_COMPAT, glfw.TRUE)
    glfw.window_hint(glfw.TRANSPARENT_FRAMEBUFFER, glfw.TRUE)  # ★ 透明背景
    glfw.window_hint(glfw.DECORATED, glfw.TRUE)
    glfw.window_hint(glfw.RESIZABLE, glfw.TRUE)

    width, height = 800, 600
    window = glfw.create_window(
        width, height, "Transparent + Selective Click-Through — Red Triangle", None, None
    )
    if not window:
        glfw.terminate()
        raise RuntimeError("glfw.create_window() 失败")

    glfw.make_context_current(window)
    glfw.swap_interval(1)

    # ── 3. 获取 HWND + 强制启用 WS_EX_LAYERED ───────────────────
    # GLFW 的 TRANSPARENT_FRAMEBUFFER 使用 DWM blur behind 实现视觉透明，
    # 但不会设置 WS_EX_LAYERED。而 WS_EX_TRANSPARENT 需要 WS_EX_LAYERED
    # 配合才能在 DWM 合成窗口上正确穿透鼠标事件。
    hwnd = glfw.get_win32_window(window)
    WS_EX_LAYERED = 0x00080000

    style = _user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    print(f"[Init] 原始 EX_STYLE = 0x{style:08X}, LAYERED={'✓' if style & WS_EX_LAYERED else '✗'}")
    if not (style & WS_EX_LAYERED):
        _user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED)
        _user32.SetWindowPos(
            hwnd, 0, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER |
            SWP_NOACTIVATE | SWP_FRAMECHANGED,
        )
        style = _user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        print(f"[Init] 添加 LAYERED 后 EX_STYLE = 0x{style:08X}, LAYERED={'✓' if style & WS_EX_LAYERED else '✗'}")

    _remove_ws_transparent(hwnd)  # 初始状态：不穿透，标题栏可操作

    # ── 3b. 置顶窗口（与背后窗口交互时不会被挤到后面） ──────────
    HWND_TOPMOST = -1
    _user32.SetWindowPos(
        hwnd, HWND_TOPMOST, 0, 0, 0, 0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
    )
    print("[Init] 窗口已置顶 (TOPMOST)")

    # ── 4. 光标状态（轮询 GetCursorPos，不受 WS_EX_TRANSPARENT 影响） ──
    cursor = {"x": 0.0, "y": 0.0, "clicked_triangle": False}

    def on_mouse_button(win, button, action, mods):
        if button == glfw.MOUSE_BUTTON_LEFT and action == glfw.PRESS:
            cursor["clicked_triangle"] = True

    glfw.set_mouse_button_callback(window, on_mouse_button)

    # ── 5. ESC 关闭 ─────────────────────────────────────────────
    def on_key(win, key, scancode, action, mods):
        if key == glfw.KEY_ESCAPE and action == glfw.PRESS:
            glfw.set_window_should_close(win, True)
        elif key == glfw.KEY_F1 and action == glfw.PRESS:
            # F1: 打印完整的窗口样式
            style = _user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
            print(f"[F1] EX_STYLE=0x{style:08X} | "
                  f"LAYERED={'✓' if style & 0x00080000 else '✗'} "
                  f"TRANSPARENT={'✓' if style & WS_EX_TRANSPARENT else '✗'}")
            _add_ws_transparent(hwnd)
            style = _user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
            print(f"[F1] 强制穿透后 EX_STYLE=0x{style:08X} | "
                  f"TRANSPARENT={'✓' if style & WS_EX_TRANSPARENT else '✗'}")
            print(f"[F1] ★ 请现在点击透明背景区域，测试是否穿透 ★")
    glfw.set_key_callback(window, on_key)

    # ── 6. 编译 shader + VAO ────────────────────────────────────
    prog = _compile_shader_program()
    vao = _setup_vao(prog)

    print("[Diagnostic] OpenGL 4.4 core — 调试模式")
    print("  点击透明背景 → 应穿透到后方窗口")
    print("  点击三角形 → 终端输出 'Triangle clicked!'")
    print("  F1 → 打印当前 EX_STYLE 并强制开启穿透")
    print("  ESC → 退出")
    print()

    # ── 7. 主循环 ──────────────────────────────────────────────
    frame = 0
    last_ws_state: bool | None = None  # 跟踪上一次的 WS_EX_TRANSPARENT 状态

    while not glfw.window_should_close(window):
        frame += 1

        # ── 7a. 获取帧状态 ──────────────────────────────────────
        fbw, fbh = glfw.get_framebuffer_size(window)

        # ★ poll 光标（GetCursorPos）
        cx, cy = glfw.get_cursor_pos(window)
        cursor["x"] = cx
        cursor["y"] = cy

        # ── 7b. 判定 + 切换穿透 ─────────────────────────────────
        in_client = (0.0 <= cx < fbw) and (0.0 <= cy < fbh)
        ndc_x, ndc_y = _cursor_to_ndc(cx, cy, fbw, fbh) if in_client else (0.0, 0.0)
        on_triangle = _point_in_triangle_ndc(ndc_x, ndc_y) if in_client else False

        if not in_client:
            changed = _remove_ws_transparent(hwnd)
            decision = "NONCLIENT"
        elif on_triangle:
            changed = _remove_ws_transparent(hwnd)
            decision = "TRIANGLE"
        else:
            changed = _add_ws_transparent(hwnd)
            decision = "TRANSPARENT"

        # ── 7c. 诊断日志（状态变化时打印） ───────────────────────
        current_ws = bool(_user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE) & WS_EX_TRANSPARENT)
        if changed or current_ws != last_ws_state or (frame <= 5):
            state_str = "穿透ON" if current_ws else "穿透OFF"
            print(f"  [F{frame:04d}] {decision:12s} | cursor=({cx:6.1f},{cy:6.1f}) fb=({fbw},{fbh}) "
                  f"NDC=({ndc_x:+.3f},{ndc_y:+.3f}) | {state_str}")
        last_ws_state = current_ws

        # ── 7d. 处理事件 ────────────────────────────────────────
        glfw.poll_events()

        # ── 7e. 处理点击 ────────────────────────────────────────
        if cursor["clicked_triangle"]:
            cursor["clicked_triangle"] = False
            ndc_x2, ndc_y2 = _cursor_to_ndc(cursor["x"], cursor["y"], fbw, fbh)
            print(f"  [F{frame:04d}] ⬆ CLICK at NDC=({ndc_x2:+.3f},{ndc_y2:+.3f}) "
                  f"| WS_EX_TRANSPARENT={'ON' if current_ws else 'OFF'}")

        # ── 渲染 ──────────────────────────────────────────────
        gl.glViewport(0, 0, fbw, fbh)
        gl.glClearColor(0.0, 0.0, 0.0, 0.0)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)

        gl.glUseProgram(prog)
        gl.glBindVertexArray(vao)
        gl.glDrawArrays(gl.GL_TRIANGLES, 0, 3)

        glfw.swap_buffers(window)

    # ── 8. 清理 ────────────────────────────────────────────────
    _remove_ws_transparent(hwnd)  # 恢复，避免残留
    gl.glDeleteVertexArrays(1, [vao])
    gl.glDeleteProgram(prog)
    glfw.destroy_window(window)
    glfw.terminate()
    print("[Selective Click-Through] 已退出")


if __name__ == "__main__":
    main()
