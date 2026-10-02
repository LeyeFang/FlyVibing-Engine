"""
Dev 入口 shim — 真实实现为**独立包**（单一源码）。

  实现:  Utils/User/EditorMcp/src/engine_editor_mcp/server.py
  发布:  Utils/User/EditorMcp（build_wheel.py → console script `engine-editor-mcp`）

本 shim 保留仓库内既有用法（`python -m Utils.User.EditorMcp.mcp_server` —
.vscode/mcp.json / E2E 脚本 / `from Utils.User.EditorMcp import mcp_server`），
行为与独立包完全一致。
"""

from __future__ import annotations

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
_PKG_SRC = os.path.join(_REPO_ROOT, "Utils", "User", "EditorMcp", "src")
if _PKG_SRC not in sys.path:
    sys.path.insert(0, _PKG_SRC)

from engine_editor_mcp.server import (  # noqa: E402,F401
    DEFAULT_PORT,
    FRAMES_DIR,
    _capture_png,
    _encode_and_save,
    _port,
    _send,
    _send_raw,
    _wipe_frames_dir,
    main,
    mcp,
)

if __name__ == "__main__":
    main()
