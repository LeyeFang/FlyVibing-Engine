"""
Unified Test Harness — 引擎渲染测试的共享夹具。

职责:
  - GLFW 窗口创建 (统一 GL 版本 4.4 core)
  - 引擎子系统初始化 (ResourceManager, SceneManager)
  - 主线 openGLRenderer 创建
  - 标准主循环模板 (相机矩阵更新 + StartFrame/EndFrame)
  - 通用 Mock 类 (_MockWindow, _MockApp)

约定:
  - 所有测试统一使用 GL 4.4 core profile
  - 深灰背景 (0.11, 0.11, 0.11) — 与 Editor BG_NEAR_BLACK 一致
  - 测试文件需先 import _path_setup 设置好 sys.path，再 import 本模块

使用示例:

    from Test._test_harness import TestHarness, MockWindow, MockApp
    from Test._test_scene import create_three_cubes

    h = TestHarness("My Test", 1024, 768)
    h.create_window()
    h.init_engine()
    renderer = h.create_renderer()
    cam = h.create_default_camera()

    create_three_cubes(renderer)

    while h.running:
        h.poll()
        h.begin_frame(cam)
        h.end_frame()

    h.shutdown()
"""

from __future__ import annotations

import math
import numpy as np
import glfw

from Application.Core.Events.Event import BindPackCallback
from Application.Resource.ResourceManager import ResourceManager
from Application.Core.Scene.SceneManager import SceneManager
from Application.Core.Renderer.OpenGL.OpenGLRenderer import OpenGLRenderer
from Application.Core.Renderer.OpenGL.OpenGLCore import OpenGLCore
from Application.Editor.EditorCamera import EditorCamera
from Test.Helpers.TestEditorCamera import TestEditorCamera
from OpenGL import GL as gl


# ═══════════════════════════════════════════════════════════════
# 通用 Mock 类
# ═══════════════════════════════════════════════════════════════

class MockWindow:
    """包装 GLFW 窗口，匹配 EditorWindow 接口 (GetSize)。"""
    def __init__(self, glfw_window):
        self._glfw = glfw_window
        self.glfw_window = glfw_window

    def GetSize(self):
        return glfw.get_framebuffer_size(self._glfw)


class MockApp:
    """最小 Application mock，供引擎子系统 Init() 使用。"""
    editor_window = None
    renderer = None


class MockEditorCamera:
    """Mock EditorCamera — 注入到 EditorCamera 模块，供 ViewGizmo/OutlinerID 等使用。

    用法:
        cam = TestEditorCamera()
        MockEditorCamera.set_camera(cam)
        import Application.Editor.EditorCamera as _ec
        _ec.EditorCamera = MockEditorCamera
    """
    _cam = None

    @classmethod
    def set_camera(cls, cam) -> None:
        cls._cam = cam

    @classmethod
    def get_instance(cls):
        return cls._cam

    @classmethod
    def get_view_matrix(cls) -> np.ndarray:
        if cls._cam is None:
            return np.identity(4, dtype=np.float32)
        return cls._cam.get_view_matrix()

    @classmethod
    def get_projection_matrix(cls, aspect: float = 1.0) -> np.ndarray:
        if cls._cam is None:
            return np.identity(4, dtype=np.float32)
        return cls._cam.get_projection_matrix(aspect)


# ═══════════════════════════════════════════════════════════════
# TestHarness
# ═══════════════════════════════════════════════════════════════

class TestHarness:
    """引擎渲染测试的统一夹具。

    创建 GLFW 窗口 → 初始化引擎子系统 → 创建渲染器 → 运行主循环。

    属性:
        window       : GLFW 窗口句柄
        mock_window  : MockWindow 实例
        mock_app     : MockApp 实例
        renderer     : openGLRenderer 实例
        running      : bool, 窗口是否未请求关闭
    """

    DEFAULT_CLEAR_COLOR = (0.11, 0.11, 0.11, 1.0)   # 深灰 (BG_NEAR_BLACK)

    def __init__(
        self,
        title: str = "Engine Test",
        width: int = 1024,
        height: int = 768,
        clear_color: tuple = None,
    ):
        self._title = title
        self._width = width
        self._height = height
        self._clear_color = clear_color or self.DEFAULT_CLEAR_COLOR

        self.window = None
        self.mock_window = None
        self.mock_app = None
        self.renderer = None

    # ── 1. 窗口 ─────────────────────────────────────────────────

    def create_window(self) -> None:
        """创建 GLFW 4.4 core 窗口并绑定上下文。"""
        if not glfw.init():
            raise RuntimeError("glfw.init() 失败")

        glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 4)
        glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 4)
        glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)

        self.window = glfw.create_window(
            self._width, self._height, self._title, None, None
        )
        if not self.window:
            glfw.terminate()
            raise RuntimeError("glfw.create_window() 失败")

        glfw.make_context_current(self.window)
        glfw.swap_interval(1)

        self.mock_window = MockWindow(self.window)
        self.mock_app = MockApp()
        self.mock_app.editor_window = self.mock_window

    def set_window(self, glfw_window) -> None:
        """注入手动创建的 GLFW 窗口（用于需要定制 GLFW hints 的测试，如 ZenGL）。

        调用方负责 glfw.init()、窗口创建和 make_context_current。
        本方法仅将窗口注册到 harness 并创建对应的 mock。
        """
        self.window = glfw_window
        self.mock_window = MockWindow(glfw_window)
        self.mock_app = MockApp()
        self.mock_app.editor_window = self.mock_window

    # ── 2. 引擎子系统 ───────────────────────────────────────────

    def init_engine(self) -> None:
        """初始化 ResourceManager 和 SceneManager。"""
        BindPackCallback(lambda e: None)                    # 静默事件
        ResourceManager.Init(self.mock_app)
        SceneManager.Init(self.mock_app)
        SceneManager.set_thread_active("MockApp")           # 测试线程绑定

    # ── 3. 渲染器 ──────────────────────────────────────────────

    def create_renderer(self) -> "OpenGLRenderer":
        """创建主线 OpenGLRenderer，覆写清屏颜色为深灰。"""
        import Application.Editor.EditorHost as _eh
        _eh.EditorHost.editor_window = self.mock_window

        renderer = OpenGLRenderer.Create()
        renderer.viewport_width = self._width
        renderer.viewport_height = self._height

        # 覆写 OpenGLCore 的默认清屏颜色为深灰
        gl.glClearColor(*self._clear_color)

        self.renderer = renderer
        self.mock_app.renderer = renderer
        return renderer

    # ── 4. 摄像机 ──────────────────────────────────────────────

    def create_default_camera(self) -> EditorCamera:
        """创建 EditorCamera 单例并设为标准测试视角。"""
        cam = EditorCamera.get_instance()
        cam.yaw = math.pi * 0.7
        cam.pitch = 0.3
        cam.orbit_target = np.array([0.0, 0.0, 0.0], dtype=np.float32)
        cam.orbit_distance = 10.0
        cam._update_position()
        return cam

    def create_test_camera(
        self,
        yaw: float = math.pi * 0.6,
        pitch: float = 0.25,
        distance: float = 8.0,
    ) -> TestEditorCamera:
        """创建 TestEditorCamera 实例（非单例，可注入为 MockEditorCamera）。

        Args:
            yaw: 水平环绕角 (弧度)
            pitch: 垂直俯仰角 (弧度)
            distance: 摄像机距离
        """
        cam = TestEditorCamera()
        cam.yaw = yaw
        cam.pitch = pitch
        cam.distance = distance
        cam.target = np.array([0.0, 0.0, 0.0], dtype=np.float32)
        return cam

    def inject_mock_camera(self, cam: TestEditorCamera) -> None:
        """将 TestEditorCamera 注入为 EditorCamera 模块的替身。

        ViewGizmo / OutlinerID / TransformGizmo 通过 EditorCamera.get_instance()
        获取相机引用。调用此方法后，它们将使用传入的 cam。
        """
        MockEditorCamera.set_camera(cam)
        import Application.Editor.EditorCamera as _ec
        _ec.EditorCamera = MockEditorCamera

    # ── 5. Shader 工具 ─────────────────────────────────────────

    @staticmethod
    def patch_default_shader_440() -> None:
        """将默认 shader (ID '1') patch 为 GLSL 440 core 兼容版本。

        所有使用主线 openGLRenderer 的测试，如果要在 GL 4.4 上下文中渲染
        引擎默认立方体，必须先调用此方法。
        """
        vs = """#version 440 core
layout(location=0) in vec3 aPos; layout(location=1) in vec2 aTexCoord;
uniform mat4 model,view,projection; out vec2 TexCoord;
void main(){gl_Position=projection*view*model*vec4(aPos,1.0);TexCoord=aTexCoord;}"""
        fs = """#version 440 core
in vec2 TexCoord; out vec4 FragColor;
layout(binding=0) uniform sampler2D uTexture;
void main(){FragColor=texture(uTexture,TexCoord);}"""
        s = ResourceManager.loaded_shader['1']['data']
        s.vs_src = vs
        s.fs_src = fs
        s.uniforms_name_type = {
            'model': 'mat4', 'view': 'mat4',
            'projection': 'mat4', 'uTexture': 'sampler2D',
        }

    # ── 6. 渲染器替换 ──────────────────────────────────────────

    def set_renderer(self, renderer) -> None:
        """手动设置渲染器（用于非主线渲染器如 ZenGL）。

        create_renderer() 自动创建 openGLRenderer。对于 ZenGL 等替代后端，
        测试需自行创建渲染器后调用此方法注入。
        """
        self.renderer = renderer
        self.mock_app.renderer = renderer
        renderer.viewport_width = self._width
        renderer.viewport_height = self._height

    # ── 7. 主循环助手 ──────────────────────────────────────────

    @property
    def running(self) -> bool:
        """窗口是否未请求关闭。"""
        return self.window is not None and not glfw.window_should_close(self.window)

    def poll(self) -> None:
        """poll_events 的别名。"""
        glfw.poll_events()

    def run_loop(
        self,
        camera=None,
        skip_cmd_queue: bool = False,
    ) -> None:
        """运行标准主循环 — poll → begin_frame → end_frame。

        等价于:
            while h.running:
                h.poll()
                h.begin_frame(cam, skip_cmd_queue)
                h.end_frame()

        Args:
            camera: 摄像机实例。为 None 则使用 _cached_view/_cached_proj。
            skip_cmd_queue: True 时直接 _do_start_frame() (ZenGL 等)。
        """
        while self.running:
            self.poll()
            self.begin_frame(camera, skip_cmd_queue=skip_cmd_queue)
            self.end_frame()

    def begin_frame(self, camera=None, skip_cmd_queue: bool = False) -> None:
        """更新相机矩阵 + 视口，调用渲染器帧开始。

        Args:
            camera: 有 get_view_matrix() / get_projection_matrix(aspect) 的实例。
                    为 None 则使用已缓存的矩阵。
            skip_cmd_queue: True 时直接调用 _do_start_frame()（跳过命令队列消费），
                            用于 ZenGL 等非主线渲染器。
        """
        fbw, fbh = glfw.get_framebuffer_size(self.window)
        asp = fbw / fbh if fbh else 1.0

        if camera:
            self.renderer._cached_view = camera.get_view_matrix()
            self.renderer._cached_proj = camera.get_projection_matrix(asp)

        # ZenGL: 处理 resize
        if skip_cmd_queue:
            if (fbw != self.renderer.viewport_width or
                fbh != self.renderer.viewport_height):
                self.renderer.viewport_width = fbw
                self.renderer.viewport_height = fbh
                self.renderer.aspect_ratio = asp

        self.renderer.viewport_width = fbw
        self.renderer.viewport_height = fbh
        self.renderer.aspect_ratio = asp

        if skip_cmd_queue:
            # ★ 即使跳过标准 StartFrame，也必须消费命令队列
            #    (EntityRegistrationCommand / OverlayRegistrationCommand 等)
            if (hasattr(self.renderer, '_command_queue')
                    and self.renderer._command_queue is not None):
                self.renderer._command_queue.execute_all(self.renderer)
            self.renderer._do_start_frame()
        else:
            self.renderer.StartFrame()

    def end_frame(self) -> None:
        """调用 renderer.EndFrame() + swap_buffers（主线渲染器）。"""
        if hasattr(self.renderer, 'EndFrame'):
            self.renderer.EndFrame()
        glfw.swap_buffers(self.window)

    # ── 8. 输入管线 ────────────────────────────────────────────

    def create_input_pipeline(self, input_state=None):
        """创建并返回一个 InputPipeline 实例 (test 专用)。

        InputPipeline 自动接管 GLFW 回调注册 + InputState 管理 +
        拖拽/移动分流。test 通过覆写其钩子 (on_key / on_mouse_button /
        on_drag / on_move / on_scroll) 实现自定义交互逻辑，
        无需手写 GLFW 回调。

        Args:
            input_state: 外部 InputState 实例。为 None 则自动创建。

        Returns:
            InputPipeline 实例

        Usage:
            pipeline = h.create_input_pipeline()

            def on_drag(button, dx, dy, x, y):
                if button == glfw.MOUSE_BUTTON_LEFT:
                    cam.orbit(dx, dy)

            pipeline.on_drag = on_drag

            # 主循环不变
            h.run_loop(cam)
        """
        from Application.Core.Input.InputPipeline import InputPipeline
        return InputPipeline(self.window, input_state=input_state)

    # ── 9. 清理 ────────────────────────────────────────────────

    def shutdown(self) -> None:
        """终止 GLFW。"""
        if self.window:
            glfw.destroy_window(self.window)
        glfw.terminate()
