"""
RuntimeNodeLayer — 由节点图驱动的 GameRuntime Layer。

职责:
  - OnAttach:  从 NodeCanvas 构建 GraphEvaluator，触发 OnGameStart
  - OnUpdate:  更新 ExecutionContext（deltaTime），触发 OnFrameUpdate
  - OnDetach:  触发 OnGameStop

节点图来源:
  生产环境: 从 JSON 反序列化 NodeCanvas
  测试环境: 直接注入预设的 NodeCanvas

使用方式:
    from Application.Runtime.RuntimeNodeLayer import RuntimeNodeLayer
    GameRuntime.push_layer(RuntimeNodeLayer)
    RuntimeNodeLayer.set_canvas(my_canvas)  # 注入节点图
"""

from __future__ import annotations

import time
from Application.Core.Layers.Layer import Layer
from Application.Core.Events.Event import Event
from Application.Core.Events.EngineEvent import LayerLifecycleEvent
from Application.Editor.UI.controllers.NodeEditorController import _TYPES
from Application.Editor.UI.controllers.GraphEvaluator import (
    GraphEvaluator,
    ExecutionContext,
)


class RuntimeNodeLayer(Layer):
    """由节点图驱动的游戏逻辑层。"""

    # ── 外部注入: 节点图 ────────────────────────────────────
    _canvas = None          # NodeCanvas 实例
    _evaluator: GraphEvaluator | None = None
    _context: ExecutionContext | None = None
    _start_time: float = 0.0

    @classmethod
    def set_canvas(cls, canvas) -> None:
        """注入节点图。必须在 push_layer 之前调用。"""
        cls._canvas = canvas

    # ════════════════════════════════════════════════════════════
    # Layer 生命周期
    # ════════════════════════════════════════════════════════════

    @classmethod
    def OnAttach(cls):
        LayerLifecycleEvent.Pack(
            layer_name=cls.__name__, stage="attach", engine=cls._engine
        )
        if cls._canvas is None:
            print("[RuntimeNodeLayer] WARNING: No canvas set — graph will not execute")
            return

        cls._evaluator = GraphEvaluator(cls._canvas, _TYPES)
        cls._context = ExecutionContext()
        cls._start_time = time.perf_counter()

        # 触发 OnGameStart
        cls._context.elapsed_time = 0.0
        cls._context.delta_time = 0.0
        cls._evaluator.trigger("OnGameStart", cls._context)
        print("[RuntimeNodeLayer] Graph execution started")

    @classmethod
    def OnDetach(cls):
        if cls._evaluator is not None and cls._context is not None:
            cls._evaluator.trigger("OnGameStop", cls._context)
            print("[RuntimeNodeLayer] Graph execution stopped")
        cls._evaluator = None
        cls._context = None
        LayerLifecycleEvent.Pack(
            layer_name=cls.__name__, stage="detach", engine=cls._engine
        )

    @classmethod
    def OnUpdate(cls):
        if cls._evaluator is None or cls._context is None:
            return

        now = time.perf_counter()
        cls._context.delta_time = now - cls._start_time - cls._context.elapsed_time
        cls._context.elapsed_time = now - cls._start_time

        cls._evaluator.trigger("OnFrameUpdate", cls._context)

    @classmethod
    def OnEvent(cls, event: Event) -> None:
        pass

    @classmethod
    def OnRender(cls):
        pass
