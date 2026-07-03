"""
Engine lifecycle events — 引擎运维性事件。

与输入/场景/窗口事件不同，此类事件承载引擎自身生命周期中的状态变更消息：
  - 启动 / 停止 / 关闭
  - 插件加载 / 卸载
  - 模拟 (PIE) 状态切换
  - 异常报告

这些事件由各自 Engine 的 DebugLayer 在 OnEvent 中统一输出，
替代散落的 print() 调用。
"""

from Application.Core.Events.Event import Event


class EngineLifecycleEvent(Event):
    """引擎生命周期事件 — 通用运维消息。

    使用场景:
      - Engine 启动/停止/关闭
      - 插件加载/卸载
      - Simulation 状态变更 (Play/Stop)
      - 渲染循环异常

    stage 字段用于分类 (如 "start", "stop", "plugin", "simulation", "exception"),
    message 字段携带人类可读的描述。
    """

    def __init__(self, stage: str, message: str = "") -> None:
        super().__init__()
        self.stage: str = stage
        self.message: str = message

    @property
    def log_info(self) -> str:
        if self.message:
            return f"[{self.stage}] {self.message}"
        return f"[{self.stage}]"

    @classmethod
    def Pack(cls, stage: str, message: str = "", **kwargs) -> None:
        super().Pack(stage, message, **kwargs)

    def unpack(self) -> tuple[str, str]:
        return self.stage, self.message


class LayerLifecycleEvent(Event):
    """Layer 生命周期事件 — OnAttach / OnDetach 通知。

    由各 Layer 在其 OnAttach/OnDetach 中派发。
    若当前 Engine 的 DebugLayer 已 attach，由它打印；
    否则由 Engine._on_event 兜底打印。
    """

    def __init__(self, layer_name: str, stage: str) -> None:
        super().__init__()
        self.layer_name: str = layer_name
        self.stage: str = stage  # "attach" / "detach"

    @property
    def log_info(self) -> str:
        return f"Layer '{self.layer_name}' {self.stage}"

    @classmethod
    def Pack(cls, layer_name: str, stage: str, **kwargs) -> None:
        super().Pack(layer_name, stage, **kwargs)

    def unpack(self) -> tuple[str, str]:
        return self.layer_name, self.stage
