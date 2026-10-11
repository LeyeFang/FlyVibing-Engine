"""过渡别名 — EditorPlugin 已更名 EditorModule（2026-10-11）。

架构决议: Doc/Dev/extension_protocol.md §2（命名重构）。
本 shim 保留 ≥1 个版本以兼容旧引用；新代码一律 import Application.Editor.EditorModule。
"""

from Application.Editor.EditorModule import EditorModule as EditorPlugin  # noqa: F401

__all__ = ["EditorPlugin"]
