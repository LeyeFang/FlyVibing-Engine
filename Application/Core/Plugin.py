"""
Plugin — 插件基类。

职责:
  - 定义插件的加载/卸载生命周期
  - 暴露插件拥有的 Layer 列表（由 Engine 自动 push/pop）
  - 不参与帧循环（不是 Layer）

Layer vs Plugin:
  Layer   — 帧级调度单位（每帧 OnUpdate / OnRender / OnEvent）
  Plugin  — 功能模块容器（加载/卸载时批量注册/注销 Layer + Service）

继承层次:
  Plugin
    ├── EditorPlugin   — 编辑器功能包（ImGui + 面板 + 3D 视口交互）
    └── ...             — 未来: 音频插件、网络插件、物理插件等
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from Application.Core.Layers.Layer import Layer

if TYPE_CHECKING:
    from Application.Core.Engine import Engine


class Plugin(ABC):
    """插件基类 — 管理一组 Layer 和 Service 的加载/卸载。

    子类必须覆写:
      - on_load(engine)   → 插件加载时的初始化
      - on_unload()       → 插件卸载时的清理

    子类可选覆写:
      - get_layers()      → 返回插件拥有的 Layer 列表 (默认空)
    """

    # ── 插件元数据 ──────────────────────────────────────────────
    name: str = "UnnamedPlugin"
    version: str = "0.1.0"

    # ════════════════════════════════════════════════════════════
    # 生命周期（子类必须实现）
    # ════════════════════════════════════════════════════════════

    @abstractmethod
    def on_load(self, engine: 'Engine') -> None:
        """插件加载回调。

        由 PluginManager / EditorHost 在引擎初始化后、
        主循环开始前调用。运行在主线程。

        Args:
            engine: 引擎单例引用（可用于 push_layer 等操作）
        """
        ...

    @abstractmethod
    def on_unload(self) -> None:
        """插件卸载回调。

        由 PluginManager / EditorHost 在引擎关闭时调用。
        运行在主线程。
        """
        ...

    # ════════════════════════════════════════════════════════════
    # Layer 暴露（子类可选覆写）
    # ════════════════════════════════════════════════════════════

    def get_layers(self) -> list[type[Layer]]:
        """返回此插件拥有的所有 Layer 类。

        Engine 在加载插件后自动将这些 Layer push 到层栈，
        在卸载插件时自动 pop。

        注意:
          返回的是 Layer 类（不是实例），因为当前 Layer 是
          @classmethod 单例模式。未来如果改为实例模式，
          这里返回 list[Layer] 实例即可。

        Returns:
            Layer 类列表（默认空）
        """
        return []
