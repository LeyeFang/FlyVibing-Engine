"""
RHI 改进版 Renderer 基类 — 主线 Renderer.py 的 RHI 升级版。

与主线 Renderer 的差异:
  1. 新增 _command_queue + enqueue() — 主线程安全提交命令
  2. StartFrame 改为两级: execute_all(commands) → _do_start_frame()
  3. OnEvent 不再是抽象方法（事件→命令转换移到 EditorHost）

继承层次 (测试):
  TestRenderer (本文件)
    └── test openGLRenderer → 同时继承 mainline openGLRenderer (MRO 共享)

推回主线时:
  本文件的设计合并到 Application/Core/Renderer/Renderer.py。
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, TYPE_CHECKING

import numpy as np

from Application.Core.Renderer.Renderer import Renderer as _MainlineRenderer
from Application.Core.Renderer.Renderer import RenderResourceManger

if TYPE_CHECKING:
    from Application.Core.Camera.CameraBase import CameraBase
    from Test.RHI.Engine.CommandQueue import CommandQueue
    from Test.RHI.Engine.RenderCommand import RenderCommand


class Renderer(_MainlineRenderer):
    """RHI 改进版渲染器基类 — 命令队列 + 两级帧渲染。

    与主线 Renderer 的差异:
      StartFrame  →  execute_all(commands) → _do_start_frame()
      + enqueue() — 主线程安全接口
      OnEvent 降级为可选 (事件→命令转换由 EditorHost 负责)

    子类只需实现 _do_start_frame() 即可得到完整的命令队列支持。
    """

    # ── 命令队列 (新增) ─────────────────────────────────────────
    _command_queue: 'CommandQueue' = None

    @classmethod
    def enqueue(cls, cmd: 'RenderCommand') -> None:
        """主线程安全: 提交一条渲染命令。

        替代旧的 renderer.OnEvent(event) 模式。
        转换逻辑在 EditorHost._on_event 中完成。
        """
        if cls._command_queue is not None:
            cls._command_queue.enqueue(cmd)

    # ════════════════════════════════════════════════════════════
    # 帧渲染 (两级架构: 基类消费命令 → 子类执行渲染)
    # ════════════════════════════════════════════════════════════

    @classmethod
    def StartFrame(cls) -> None:
        """消费所有排队命令，然后调用子类的 _do_start_frame()。"""
        if cls._command_queue is not None:
            commands = cls._command_queue.dequeue_all()
            cls._command_queue.execute_all(commands)
        cls._do_start_frame()

    @classmethod
    @abstractmethod
    def _do_start_frame(cls) -> None:
        """子类实现: 实际的帧渲染逻辑 (clear + pick + entities + overlays)。

        基类已在调用前消费完所有排队命令。
        """
        ...

    # ════════════════════════════════════════════════════════════
    # TODO: 以下内容需要从备份恢复
    # ════════════════════════════════════════════════════════════
    # - OnEvent 的默认实现 (可能是 no-op)
    # - 其他辅助方法
    # - 完整的 _do_start_frame 默认实现
