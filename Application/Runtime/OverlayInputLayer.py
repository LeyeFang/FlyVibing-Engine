"""
OverlayInputLayer — Overlay 模式的输入穿透判定层。

通过 Pick 系统判断光标下是否有渲染内容:
  - 有 entity/overlay → 捕获鼠标 (不穿透)
  - 无任何命中     → 开启穿透 (事件透传到桌面)

使用方式:
    GameRuntime.push_layer(OverlayInputLayer)
"""

from __future__ import annotations

from Application.Core.Layers.Layer import Layer
from Application.Core.Events.Event import Event
from Application.Core.Events.InputEvent import MouseMoveEvent


class OverlayInputLayer(Layer):
    """Overlay 输入层 — 追踪鼠标位置并通过 Pick 系统判定命中。"""

    renderer = None

    @classmethod
    def OnAttach(cls):
        super().OnAttach()
        cls.renderer = cls._engine.renderer
        # ★ Overlay 模式: 透明背景 — 必须在渲染器创建后、首帧渲染前设置
        from Application.Core.Renderer.RenderCommand import SetClearColorCommand
        cls.renderer.enqueue(SetClearColorCommand(r=0.0, g=0.0, b=0.0, a=0.0))

    @classmethod
    def OnDetach(cls):
        cls.renderer = None

    @classmethod
    def OnUpdate(cls):
        pass

    @classmethod
    def OnEvent(cls, event: Event) -> None:
        if isinstance(event, MouseMoveEvent):
            if cls.renderer is not None:
                cls.renderer.update_pick_mouse(event.pos_x, event.pos_y)

    @classmethod
    def is_cursor_hit(cls) -> bool:
        """光标下是否有渲染内容 (entity 或 overlay)。

        Renderer 为 None 时保守返回 True (全捕获, 不穿透)。
        """
        if cls.renderer is None:
            return True
        pick_type, _ = cls.renderer.pick_at(0, 0)
        return pick_type is not None
