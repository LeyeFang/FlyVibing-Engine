"""
RHI 变体 OpenGLRenderer — 继承 TestRenderer + 主线 OpenGLRenderer。

MRO (C3 linearization):
  OpenGLRenderer → TestRenderer → _BaseRenderer → ... → Renderer (mainline)

改动点:
  - OnEvent: 覆写为 enqueue(command) 版本 (替代主线直接处理)
  - StartFrame: 由 TestRenderer 提供两级架构 (execute_all → _do_start_frame)
  - _command_queue: 由 TestRenderer 提供
  - Create: 覆写为 EditorHost 版本 + 初始化命令队列

其他所有方法通过 MRO 完全继承。
"""

from __future__ import annotations

from Application.Core.Renderer.OpenGL.OpenGLRenderer import OpenGLRenderer as _BaseRenderer
from Application.Core.Renderer.OpenGL.OpenGLCore import OpenGLCore
from Application.Editor.EditorHost import EditorHost

from Application.Core.Events.Event import Event
from Application.Core.Events.WindowEvent import WindowResizeEvent
from Application.Core.Events.SceneEvent import (
    SceneCameraUpdateEvent,
    NewComponentEvent,
    ComponentModifiedEvent,
)
from Application.Core.Events.InputEvent import MouseMoveEvent
from Application.Core.Scene.BasicComponents import MeshRenderer

from Test.RHI.Engine.Renderer import Renderer as TestRenderer
from Test.RHI.Engine.CommandQueue import CommandQueue
from Test.RHI.Engine.RenderCommand import (
    ResizeCommand,
    CameraUpdateCommand,
    EntityRegistrationCommand,
    PickMouseMoveCommand,
)


class OpenGLRenderer(TestRenderer, _BaseRenderer):
    """RHI 变体 — TestRenderer 提供命令队列+两级帧渲染, _BaseRenderer 提供 GL 实现。

    MRO:
      TestRenderer.StartFrame → execute_all + _do_start_frame → super().StartFrame()
      → _BaseRenderer.StartFrame → clear + pick + entities + overlays

      OpenGLRenderer.OnEvent → enqueue(commands)  (覆写 _BaseRenderer 的版本)
    """

    # ════════════════════════════════════════════════════════════
    # 生命周期
    # ════════════════════════════════════════════════════════════

    @classmethod
    def Create(cls) -> "OpenGLRenderer":
        """初始化渲染器 + 命令队列。"""
        cls._command_queue = CommandQueue()
        # ── 父类 Create 逻辑 (用 EditorHost 获取窗口) ──
        window_size = EditorHost.editor_window.GetSize()
        OpenGLCore.init_core(window_size)
        cls.viewport_width = window_size[0]
        cls.viewport_height = window_size[1]
        cls.aspect_ratio = window_size[0] / window_size[1]
        if cls._active_camera is not None:
            cls._cached_view = cls._active_camera.get_view_matrix()
            cls._cached_proj = cls._active_camera.get_projection_matrix(cls.aspect_ratio)
        cls.init_pick(window_size[0], window_size[1])
        return cls

    @classmethod
    def _do_start_frame(cls) -> None:
        """子类实现: 实际的帧渲染逻辑。

        基类 StartFrame() 已在调用前消费完所有排队命令。
        这里直接调用主线 _BaseRenderer 的渲染流程。
        """
        # 调用主线 OpenGLRenderer 的 StartFrame (跳过 TestRenderer 的队列消费)
        _BaseRenderer.StartFrame.__func__(cls)

    # ════════════════════════════════════════════════════════════
    # OnEvent — 事件 → 命令转换 (替代直接处理)
    # ════════════════════════════════════════════════════════════

    @classmethod
    def OnEvent(cls, event: Event) -> None:
        """将事件转换为渲染命令并入队。

        替代主线 OpenGLRenderer.OnEvent 的直接处理模式。
        命令将在下一帧 StartFrame 时由渲染线程消费。
        """
        if isinstance(event, WindowResizeEvent):
            w, h = event.unpack()
            cls.enqueue(ResizeCommand(width=w, height=h))
        elif isinstance(event, SceneCameraUpdateEvent):
            if cls._active_camera is not None:
                view = cls._active_camera.get_view_matrix()
                proj = cls._active_camera.get_projection_matrix(cls.aspect_ratio)
                cls.enqueue(CameraUpdateCommand(view_matrix=view, proj_matrix=proj))
        elif isinstance(event, (NewComponentEvent, ComponentModifiedEvent)):
            comp = event.unpack()
            if isinstance(comp, MeshRenderer):
                cls.enqueue(EntityRegistrationCommand(
                    entity_id=event.entity_id,
                    mesh_id=comp.mesh_id,
                ))
        elif isinstance(event, MouseMoveEvent):
            cls.enqueue(PickMouseMoveCommand(pos_x=event.pos_x, pos_y=event.pos_y))


# ════════════════════════════════════════════════════════════════
# TODO: 以下内容需要从备份恢复
# ════════════════════════════════════════════════════════════════
# - 原始文件的完整实现可能包含额外的边界处理
# - 请从 git 历史或备份中恢复完整内容
