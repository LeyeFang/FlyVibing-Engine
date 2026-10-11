"""ExtensionBase — 扩展基类（L1 扩展层）。

生命周期（由 ExtensionManager 调用, 全部在主线程）:

    load:   实例化 → on_load(ctx)           # 注册贡献 (ops / 未来的 nodes/ui/threads)
    enable: on_enable()                     # 运行期启用 (选中菜单勾选)
    disable:on_disable() → unload           # 运行期停用
    unload: on_unload() + 注销该扩展全部 ops

子类约定（详见 Doc/ExtDev/extension_dev_protocol.md）:
  - 类属性 id / name / version 必须与 extension.json 一致;
  - on_load 里只做注册类工作（重初始化放 on_enable）;
  - 禁止 monkey-patch 引擎类; 禁止阻塞主线程; 线程必须经 ctx 能力创建（M2 实装）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from Application.Core.Extension.ExtensionContext import ExtensionContext


class ExtensionBase:
    """扩展基类 — 全部生命周期方法可选覆写。"""

    # ── 元数据（与 extension.json 一致; 由 ExtensionManager 校验） ──
    id: str = ""
    name: str = "UnnamedExtension"
    version: str = "0.1.0"

    # ════════════════════════════════════════════════════════════
    # 生命周期（子类按需覆写）
    # ════════════════════════════════════════════════════════════

    def on_load(self, ctx: 'ExtensionContext') -> None:
        """加载回调 — 注册贡献（ops / 节点 / 窗口 / 设置）。

        Args:
            ctx: 扩展上下文门面（能力集由 ExtensionManager 按 capabilities 注入）。
        """
        ...

    def on_enable(self) -> None:
        """运行期启用回调（菜单勾选启用后调用）。"""
        ...

    def on_disable(self) -> None:
        """运行期停用回调（在 on_unload 之前调用）。"""
        ...

    def on_unload(self) -> None:
        """卸载回调 — 释放资源（ops 由 Manager 统一注销, 此处只清自有资源）。"""
        ...

    def on_ui_event(self, event: str, name: str) -> None:
        """窗口生命周期事件（宿主 UI 桥调用 — 仅注册了窗口的扩展会收到）。

        Args:
            event: 事件名 — 当前仅 "closed"（用户点击窗口 X）;
            name:  窗口名（`ctx.ui.register_window` 返回值）。

        默认 no-op — 未注册窗口的扩展无需关心。声明 `capabilities: ["ui"]`
        的扩展**必须**继承 `UIExtensionBase`（本方法被提升为抽象 — 语言层强制
        实现, 未实现则无法实例化; 详见 Doc/ExtDev/extension_dev_protocol.md §7）。
        """
        ...


class UIExtensionBase(ExtensionBase, ABC):
    """UI 扩展基类 — 声明 `capabilities: ["ui"]` 的扩展必须继承本类。

    语言层强制（三重保障之一 — 另两层: 开发协议 §7 文档 / `ExtensionKit` 审查器）:
      - `on_ui_event` 为 abstractmethod → 子类未实现即无法实例化
        （`TypeError: Can't instantiate abstract class` — 加载时失败并隔离为 broken）;
      - `ExtensionManager` 校验 capabilities↔基类一致性（声明 ui 但未继承 → broken）。

    窗口生命周期完备性约定（dev protocol §7）:
      - 经 `ctx.ui.register_window(name, draw_fn, close_policy=...)` 注册;
      - `close_policy` 决定窗口 X 的语义:
          "hide"    仅隐藏（扩展继续运行; 需自行提供恢复路径 — 再次勾选启用会重置可见）;
          "disable" 关闭 = 请求停用扩展（**菜单勾选随窗口关闭同步消失** — 闭环）;
          "custom"  完全自定义（仅收到 on_ui_event, 由扩展自行决策）;
      - `on_ui_event("closed", name)` 中做关闭收尾（如停掉该面板正在跑的实时任务）。
    """

    @abstractmethod
    def on_ui_event(self, event: str, name: str) -> None:
        """窗口生命周期事件 — UI 扩展必须实现（见基类 docstring 与协议 §7）。"""
        ...
