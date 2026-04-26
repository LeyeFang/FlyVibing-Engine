from Application.Layers.Layer import Layer
from Application.Events.Event import Event
from Application.Events.WindowEvent import WindowCloseEvent
from Application.Events.StatsEvent import PerformanceStatsEvent
from Application.Window.Window import Window
from Application.Window.glfwWindow import glfwWindow
from Application.Renderer.Renderer import Renderer
from Application.Renderer.openglRenderer import openglRenderer
from Application.Resource.ResourceManager import ResourceManager
from Application.Scene.SceneManager import SceneManager


class Application:

    window: Window = None
    renderer: Renderer = None
    layer_stack: list[Layer] = []
    event: Event = None
    event_stack: list[Event] = []
    run_time: float

    @classmethod
    def Create(cls):
        ResourceManager.Init(cls)
        SceneManager.Init(cls)
        cls.window = glfwWindow.Create(cls)
        cls.renderer = openglRenderer.Create(cls)
        return cls

    @classmethod
    def Run(cls):
        cls.run_state = True
        while cls.run_state:
            # Update Application
            cls.renderer.StartFrame()
            for layer in cls.layer_stack:
                layer.OnUpdate()
            cls.renderer.EndFrame()
            cls.window.Update()
            # Pass Events
            if cls.event is not None:
                for layer in cls.layer_stack:
                    layer.OnEvent(cls.event)
                cls.renderer.OnEvent(cls.event)
                cls.window.OnEvent(cls.event)
                cls.OnEvent(cls.event)
                cls.event = None

    @classmethod
    def GetApplication(
        cls
    ) -> 'Application':
        return cls

    @classmethod
    def PushLayer(
        cls,
        layer: Layer
    ):
        cls.layer_stack.append(layer)
        layer.OnAttach(cls)

    @classmethod
    def PopLayer(
        cls,
        layer: Layer
    ):
        cls.layer_stack.pop(-1)
        layer.OnDetach()

    @classmethod
    def SetEvent(
        cls,
        event: Event
    ) -> None:
        cls.event = event

    @classmethod
    def PushEvent(
        cls,
        event: Event
    ) -> None:
        cls.event_stack.append(event)

    @classmethod
    def OnEvent(
        cls,
        event: Event
    ) -> None:
        if event is WindowCloseEvent:
            cls.run_state = False

    @classmethod
    def _single_loop(
        cls
    ) -> None:
        pass


#
#
# ===================== 帧率统计装饰器（放在文件最下方） =====================
import time
from functools import wraps


def frame_rate_monitor(original_run):
    """
    装饰器：为 Application.Run 添加每秒平均帧率统计
    用法：Application.Run = frame_rate_monitor(Application.Run)
    """
    @classmethod
    @wraps(original_run)
    def monitored_run(cls):
        # 原 Run 方法中的所有逻辑完全保留，仅增加帧率统计代码
        cls.run_state = True
        # ----- 统计相关变量 -----
        last_report_time = time.perf_counter()   # 上一次报告的时间点
        frame_count = 0                          # 从上一次报告至今的帧数
        # 主循环（原样复制，只添加帧计数 + 周期报告）
        while cls.run_state:
            # 原 Run 的每一帧开始（无改动）
            cls.renderer.StartFrame()
            for layer in cls.layer_stack:
                layer.OnUpdate()
            cls.renderer.EndFrame()
            cls.window.Update()
            # 事件处理（无改动）
            if cls.event is not None:
                for layer in cls.layer_stack:
                    layer.OnEvent(cls.event)
                cls.renderer.OnEvent(cls.event)
                cls.window.OnEvent(cls.event)
                cls.OnEvent(cls.event)
                cls.event = None
            # ========== 新增统计：帧数累加 ==========
            frame_count += 1
            # ========== 新增统计：每秒报告一次平均帧率 ==========
            now = time.perf_counter()
            elapsed = now - last_report_time
            if elapsed >= 1.0:                     # 够1秒了
                avg_fps = frame_count / elapsed    # 过去这一秒的平均帧率
                # print(f"[FPS] Average FPS over last second: {avg_fps:.2f}")
                PerformanceStatsEvent.Pack(avg_fps)
                Application.SetEvent(PerformanceStatsEvent)
                # 重置统计变量
                last_report_time = now
                frame_count = 0
        # 原 Run 方法结尾（无改动）
        # （原方法没有 return，这里也不返回）
    return monitored_run


# 直接替换 Application 的 Run 方法
Application.Run = frame_rate_monitor(Application.Run)
