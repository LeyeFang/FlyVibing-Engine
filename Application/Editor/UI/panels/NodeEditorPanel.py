"""
NodeEditorPanel — 向后兼容 shim。

实际代码已迁移至:
  Application.Editor.UI.panels.node_editor

本文件保留所有原有导出，避免破坏现有导入。
"""

from Application.Editor.UI.panels.node_editor import NodeEditorPanel

__all__ = ["NodeEditorPanel"]
