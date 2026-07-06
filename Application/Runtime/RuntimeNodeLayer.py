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

        # 防止重复初始化
        if cls._evaluator is not None:
            return

        cls._evaluator = GraphEvaluator(cls._canvas, _TYPES)
        cls._context = ExecutionContext()
        cls._frame = 0

        # 触发 OnGameStart（引擎时间从 0 开始）
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

        cls._frame += 1
        # 仅当 frame 为奇数时执行（跳过重复实例的第二次调用）
        if cls._frame % 2 == 1:
            if cls._engine is not None:
                cls._context.delta_time = cls._engine.get_delta_time()
                cls._context.elapsed_time = cls._engine.get_elapsed_time()
            cls._evaluator.trigger("OnFrameUpdate", cls._context)

    @classmethod
    def OnEvent(cls, event: Event) -> None:
        pass

    @classmethod
    def OnRender(cls):
        pass
