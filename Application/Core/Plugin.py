"""过渡别名 — Plugin 已更名 EngineModule（2026-10-11）。

架构决议: Doc/Dev/extension_protocol.md §2（命名重构）。
"Plugin" 一词已让位给对外扩展体系（Extension）；L0 宿主装配层统一使用 EngineModule。
本 shim 保留 ≥1 个版本以兼容旧引用；新代码一律 import Application.Core.EngineModule。
"""

from Application.Core.EngineModule import EngineModule as Plugin  # noqa: F401

__all__ = ["Plugin"]
