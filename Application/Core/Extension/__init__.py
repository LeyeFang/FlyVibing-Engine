"""Extension 核心契约包（L1 扩展层, 与 GUI 无关的部分）。

架构: Doc/Dev/extension_protocol.md §1（三层高度模型）
开发规范: Doc/ExtDev/extension_dev_protocol.md（对外开发者必读）

本包提供:
  - ExtensionBase      — 扩展基类（生命周期）
  - ExtensionContext   — 上下文门面（能力由 ExtensionManager 注入）

★ 本包禁止 import imgui / Application.Editor（扩展代码的 GUI 能力经 ctx 注入）。
"""

from Application.Core.Extension.ExtensionBase import ExtensionBase  # noqa: F401
from Application.Core.Extension.ExtensionContext import ExtensionContext  # noqa: F401

__all__ = ["ExtensionBase", "ExtensionContext"]
