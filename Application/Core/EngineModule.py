"""
EngineModule — 宿主装配模块（L0 引擎层）。

职责:
  - 定义"宿主装配"的加载/卸载生命周期（Engine 启动/关闭时调用）
  - 暴露装配单元拥有的 Layer 列表（由 Engine 自动 push/pop）
  - 不参与帧循环（不是 Layer）

架构定位（见 Doc/Dev/extension_protocol.md §1 三层高度模型）:
  L0 EngineModule — 宿主如何装配自己的骨架（本文件）
  L1 Extension    — 编辑器应用层的功能模块（Application/Functions/**，对外开发者接口）
  L2 Mod          — 运行时内容层（parked）
  ★ "Plugin" 一词已让位给对外扩展体系（Extension）；本层禁止被扩展代码实现/使用。

Layer vs EngineModule:
  Layer        — 帧级调度单位（每帧 OnUpdate / OnRender / OnEvent）
  EngineModule — 装配单元（加载/卸载时批量注册/注销 Layer + 服务）

实例:
  EditorModule  — 编辑器宿主装配（ImGui + 面板 + 3D 视口交互 + LiveCommandServer）
  运行时最小宿主（GameRuntime）允许硬装配，不经本机制（见协议 §2.2-4）。

历史: 原名 Plugin（2026-10-11 依据 extension_protocol §2 更名）；
`Application/Core/Plugin.py` 为过渡别名 shim（≥1 个版本）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from Application.Core.Layers.Layer import Layer

if TYPE_CHECKING:
    from Application.Core.Engine import Engine


class EngineModule(ABC):
    """宿主装配模块基类 — 管理一组 Layer 和服务的加载/卸载。

    子类必须覆写:
      - on_load(engine)   → 装配加载时的初始化
      - on_unload()       → 装配卸载时的清理

    子类可选覆写:
      - get_layers()      → 返回装配拥有的 Layer 列表 (默认空)
    """

    # ── 装配元数据 ──────────────────────────────────────────────
    name: str = "UnnamedModule"
    version: str = "0.1.0"

    # ════════════════════════════════════════════════════════════
    # 生命周期（子类必须实现）
    # ════════════════════════════════════════════════════════════

    @abstractmethod
    def on_load(self, engine: 'Engine') -> None:
        """装配加载回调。

        由宿主 (如 EditorHost) 在引擎初始化后、
        主循环开始前调用。运行在主线程。

        Args:
            engine: 引擎单例引用（可用于 push_layer 等操作）
        """
        ...

    @abstractmethod
    def on_unload(self) -> None:
        """装配卸载回调。

        由宿主 (如 EditorHost) 在引擎关闭时调用。
        运行在主线程。
        """
        ...

    # ════════════════════════════════════════════════════════════
    # Layer 暴露（子类可选覆写）
    # ════════════════════════════════════════════════════════════

    def get_layers(self) -> list[type[Layer]]:
        """返回此装配拥有的所有 Layer 类。

        Engine 在加载装配后自动将这些 Layer push 到层栈，
        在卸载装配时自动 pop。

        注意:
          返回的是 Layer 类（不是实例），因为当前 Layer 是
          @classmethod 单例模式。未来如果改为实例模式，
          这里返回 list[Layer] 实例即可。

        Returns:
            Layer 类列表（默认空）
        """
        return []
