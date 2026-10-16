"""Text 函数域 — 文字显示系统 (协议: Doc/Dev/text_protocol.md)。

- `TextDisplay` 组件 (Application/Core/Scene/BasicComponents.py) = 状态载体;
- `TextSystem` = 文本→动态纹理光栅化 (refresh / tick / rasterize);
- `SetText` 节点 = PIE 控制面 (组件=状态 / 节点=控制, 与媒体同构)。
"""

from .TextSystem import refresh, tick, snapshot, reset, rasterize

__all__ = ["refresh", "tick", "snapshot", "reset", "rasterize"]
