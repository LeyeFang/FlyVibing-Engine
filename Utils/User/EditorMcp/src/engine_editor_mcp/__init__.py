"""engine_editor_mcp — MyGameEngine 编辑器实时 MCP（独立发布包）。

用法:
    python -m engine_editor_mcp         （或安装后 console script: engine-editor-mcp）

依赖**运行中的**引擎编辑器（默认 127.0.0.1:8977; 环境变量 MGE_EDITOR_MCP_PORT
两侧设置一致可改端口）。工具为纯 socket 客户端 — 不依赖引擎源码, 可放入任何
三方项目工作区使用。
"""

__version__ = "0.3.0"

from .server import mcp  # noqa: E402,F401

__all__ = ["mcp", "__version__"]
