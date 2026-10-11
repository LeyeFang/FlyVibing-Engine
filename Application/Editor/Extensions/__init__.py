"""Extensions — 编辑器扩展体系（L1, M0）。

入口: ExtensionManager（发现/装载/启停/隔离）。
协议: Doc/Dev/extension_protocol.md（架构） + Doc/ExtDev/extension_dev_protocol.md（开发规范）。
"""

from Application.Editor.Extensions.ExtensionManager import ExtensionManager  # noqa: F401

__all__ = ["ExtensionManager"]
