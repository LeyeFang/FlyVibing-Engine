"""
Test: Overlay Pick 验证 — 两个三角形 overlay 的独立拾取
═══════════════════════════════════════════════════════════════

验证 openGLRenderer_v6 的 overlay 拾取管线:
  register_overlay_drawable → _render_overlays_pick_pass → pick_at

编码格式:
  - 实体:  R>0,  RGB24 = entity_id
  - Overlay: R=0,  G=pick_type,  B=pick_id
  - 查表:   _overlay_pick_key_map[(pick_type, pick_id)] → key

两个 NDC 三角形 (忽略场景矩阵):
  ┌────────────┬──────────┬───────────┬─────────┬──────────────┐
  │ Key         │ 颜色     │ 屏幕位置   │ pick_type │ pick_id    │
  ├────────────┼──────────┼───────────┼─────────┼──────────────┤
  │ tri_red     │ 红色     │ 左上方     │    1      │   101       │
  │ tri_green   │ 绿色     │ 右下方     │    2      │   202       │
  └────────────┴──────────┴───────────┴─────────┴──────────────┘

操作:
  左键点击  = 拾取 overlay (打印 key) / entity (打印 id) / nothing
  ESC       = 退出

运行: python Test/test_overlay_pick.py
"""

from __future__ import annotations
import sys, os
_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, '_path_setup.py')):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)
import _path_setup  # noqa: E402
import numpy as np
import glfw
from pyrr import matrix44, Vector3

from Application.Core.Events.Event import BindPackCallback
from Application.Resource.ResourceManager import ResourceManager
from Application.Core.Scene.SceneManager import SceneManager
from Application.Core.Renderer.OpenGL.OpenGLCore import OpenGLCore

from Test.Application.Core.Renderer.v6.openGLRenderer_v6 import openGLRenderer_v6


# ═══════════════════════════════════════════════════════════════
# 简单着色器 (NDC 直通)
# ═══════════════════════════════════════════════════════════════

_VISUAL_VS: str = """#version 440 core
layout (location = 0) in vec3 aPos;
uniform mat4 uModel;
void main() {
    gl_Position = uModel * vec4(aPos, 1.0);
}
"""

_VISUAL_FS: str = """#version 440 core
uniform vec4 uColor;
out vec4 fragColor;
void main() {
    fragColor = uColor;
}
"""


# ═══════════════════════════════════════════════════════════════
# 两个三角形的几何数据 (NDC)
# ═══════════════════════════════════════════════════════════════

# 红色三角形 — 左上区域
_TRI_RED_VERTS = np.array([
    -0.8,  0.8, 0.0,   # 左上
     0.0,  0.8, 0.0,   # 上
    -0.4,  0.2, 0.0,   # 左下
], dtype=np.float32)

_TRI_RED_INDICES = np.array([0, 1, 2], dtype=np.uint32)

# 绿色三角形 — 右下区域
_TRI_GREEN_VERTS = np.array([
     0.8, -0.8, 0.0,   # 右下
     0.0, -0.8, 0.0,   # 下
     0.4, -0.2, 0.0,   # 右上
], dtype=np.float32)

_TRI_GREEN_INDICES = np.array([0, 1, 2], dtype=np.uint32)


# ═══════════════════════════════════════════════════════════════
# uniform 回调 — 仅用于可视化着色器
# ═══════════════════════════════════════════════════════════════

def _set_red_color(program: int) -> None:
    from OpenGL import GL as gl
    loc = gl.glGetUniformLocation(program, 'uColor')
    if loc >= 0:
        gl.glUniform4f(loc, 1.0, 0.2, 0.2, 1.0)


def _set_green_color(program: int) -> None:
    from OpenGL import GL as gl
    loc = gl.glGetUniformLocation(program, 'uColor')
    if loc >= 0:
        gl.glUniform4f(loc, 0.2, 1.0, 0.2, 1.0)


# ═══════════════════════════════════════════════════════════════
# Mock
# ═══════════════════════════════════════════════════════════════

class _MockWindow:
    def __init__(self, glfw_window):
        self._glfw = glfw_window

    def GetSize(self):
        return glfw.get_framebuffer_size(self._glfw)


class _MockApp:
    editor_window = None


class _MockEditorCamera:
    """提供 view/proj 矩阵 — overlay 使用 ignore_scene_matrices=True 时仅需非 None 即可。"""
    @classmethod
    def get_instance(cls):
        return cls

    @classmethod
    def get_view_matrix(cls) -> np.ndarray:
        return matrix44.create_look_at(
            Vector3([3, 2, 5]),
            Vector3([0, 0, 0]),
            Vector3([0, 1, 0]))

    @classmethod
    def get_projection_matrix(cls, aspect_ratio: float) -> np.ndarray:
        return matrix44.create_perspective_projection(45.0, aspect_ratio, 0.1, 100.0)


# ═══════════════════════════════════════════════════════════════
# main
# ═══════════════════════════════════════════════════════════════

def main():
    # ── GLFW 初始化 ──
    if not glfw.init():
        print("glfw.init() failed")
        return
    glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 4)
    glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 4)
    glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
    glfw.window_hint(glfw.OPENGL_FORWARD_COMPAT, glfw.TRUE)

    window = glfw.create_window(
        1024, 768,
        "Overlay Pick Test — Click red/green triangle",
        None, None)
    if not window:
        glfw.terminate()
        return
    glfw.make_context_current(window)
    glfw.swap_interval(1)

    fbw, fbh = glfw.get_framebuffer_size(window)

    # ── 事件 pack 回调 (避免 BindPackCallback 报错) ──
    BindPackCallback(lambda event_cls: print(f"[EVENT] {event_cls.__name__}"))

    # ── 引擎子系统 ──
    mock_app = _MockApp()
    mock_app.editor_window = _MockWindow(window)
    ResourceManager.Init(mock_app)
    SceneManager.Init(mock_app)

    # ── 注入 Mock EditorCamera ──
    import Application.Editor.EditorCamera as _ec_mod
    _ec_mod.EditorCamera = _MockEditorCamera

    # ══════════════════════════════════════════════════════════
    # v6 渲染器初始化
    # ══════════════════════════════════════════════════════════

    renderer = openGLRenderer_v6
    renderer.viewport_width = fbw
    renderer.viewport_height = fbh
    renderer.aspect_ratio = fbw / fbh if fbh else 1.0

    OpenGLCore.init_core((fbw, fbh))

    # 设置缓存的 view/proj
    cam = _MockEditorCamera.get_instance()
    renderer._cached_view = cam.get_view_matrix()
    renderer._cached_proj = cam.get_projection_matrix(renderer.aspect_ratio)

    # 编译拾取着色器 & 重建 FBO
    renderer._pick_prog = renderer._compile_program(
        renderer._PICK_VS, renderer._PICK_FS)
    renderer._rebuild_pick_fbo(fbw, fbh)
    renderer._overlay_pick_prog = renderer._compile_program(
        renderer._OVERLAY_PICK_VS, renderer._OVERLAY_PICK_FS)

    print(f"[TEST] Pick FBO: {renderer._pick_fbo_w}x{renderer._pick_fbo_h}")
    print(f"[TEST] Pick prog: {renderer._pick_prog}")
    print(f"[TEST] Overlay pick prog: {renderer._overlay_pick_prog}")

    # ══════════════════════════════════════════════════════════
    # 注册两个三角形 overlay
    # ══════════════════════════════════════════════════════════

    from Application.Core.Renderer.Renderer import RenderResourceManger as RRM

    # ── 红色三角形 (pick_type=1, pick_id=101) ──
    overlay_red = RRM.overlay_drawable_struct(
        key="tri_red",
        vertices=_TRI_RED_VERTS,
        indices=_TRI_RED_INDICES,
        vs_src=_VISUAL_VS,
        fs_src=_VISUAL_FS,
        draw_mode='triangles',
        depth_test=False,
        blend=True,
        cull_face=False,
        ignore_scene_matrices=True,
        model_matrix_cb=lambda w, h: np.identity(4, dtype=np.float32),
        uniforms_setup=_set_red_color,
        vertex_stride=12,            # 3 floats × 4 bytes
        vertex_attrs=[(0, 3, 0)],    # location=0, 3 floats, offset=0
        pick_type=1,
        pick_id=101,
    )
    renderer.register_overlay_drawable(overlay_red)

    # ── 绿色三角形 (pick_type=2, pick_id=202) ──
    overlay_green = RRM.overlay_drawable_struct(
        key="tri_green",
        vertices=_TRI_GREEN_VERTS,
        indices=_TRI_GREEN_INDICES,
        vs_src=_VISUAL_VS,
        fs_src=_VISUAL_FS,
        draw_mode='triangles',
        depth_test=False,
        blend=True,
        cull_face=False,
        ignore_scene_matrices=True,
        model_matrix_cb=lambda w, h: np.identity(4, dtype=np.float32),
        uniforms_setup=_set_green_color,
        vertex_stride=12,
        vertex_attrs=[(0, 3, 0)],
        pick_type=2,
        pick_id=202,
    )
    renderer.register_overlay_drawable(overlay_green)

    # ── 验证注册表 ──
    print(f"[TEST] _overlay_gpu_resources keys: {list(renderer._overlay_gpu_resources.keys())}")
    print(f"[TEST] _overlay_pick_key_map: {renderer._overlay_pick_key_map}")
    for k, gpu in renderer._overlay_gpu_resources.items():
        print(f"  {k}: vao={gpu.vao} pick_type={gpu.pick_type} pick_id={gpu.pick_id} "
              f"elements={gpu.elements_count} draw_mode={gpu.draw_mode}")

    # ══════════════════════════════════════════════════════════
    # 交互
    # ══════════════════════════════════════════════════════════

    print("\n[TEST] === Ready. Click red/green triangle to pick. ESC to exit. ===\n")

    def on_key(win, key, scancode, action, mods):
        if action == glfw.PRESS and key == glfw.KEY_ESCAPE:
            glfw.set_window_should_close(win, True)

    def on_mouse_button(win, button, action, mods):
        if button != glfw.MOUSE_BUTTON_LEFT or action != glfw.PRESS:
            return
        cx, cy = glfw.get_cursor_pos(win)
        pick_type, pick_value = renderer.pick_at(cx, cy)
        if pick_type == 'entity':
            print(f"[PICK] screen=({cx:.0f},{cy:.0f}) → ENTITY id={pick_value}")
        elif pick_type == 'overlay':
            print(f"[PICK] screen=({cx:.0f},{cy:.0f}) → OVERLAY key='{pick_value}'")
        else:
            print(f"[PICK] screen=({cx:.0f},{cy:.0f}) → nothing (R=G=B=0)")

    glfw.set_key_callback(window, on_key)
    glfw.set_mouse_button_callback(window, on_mouse_button)

    # ══════════════════════════════════════════════════════════
    # 主循环
    # ══════════════════════════════════════════════════════════

    while not glfw.window_should_close(window):
        glfw.poll_events()

        fbw, fbh = glfw.get_framebuffer_size(window)
        asp = fbw / fbh if fbh else 1.0

        if fbw != renderer.viewport_width or fbh != renderer.viewport_height:
            renderer.viewport_width = fbw
            renderer.viewport_height = fbh
            renderer.aspect_ratio = asp
            OpenGLCore.update_viewport(fbw, fbh)
            renderer._rebuild_pick_fbo(fbw, fbh)

        cam = _MockEditorCamera.get_instance()
        renderer._cached_view = cam.get_view_matrix()
        renderer._cached_proj = cam.get_projection_matrix(asp)

        # ★ 帧渲染
        renderer.StartFrame()

        glfw.swap_buffers(window)

    # ── 清理 ──
    renderer.unregister_overlay_drawable("tri_red")
    renderer.unregister_overlay_drawable("tri_green")
    import OpenGL.GL as gl
    if renderer._pick_fbo:
        gl.glDeleteFramebuffers(1, [renderer._pick_fbo])
    if renderer._pick_color:
        gl.glDeleteTextures(1, [renderer._pick_color])
    if renderer._pick_depth:
        gl.glDeleteRenderbuffers(1, [renderer._pick_depth])
    glfw.terminate()
    print("[TEST] Done")


if __name__ == "__main__":
    main()
