"""
Engine Editor Live MCP — 运行中编辑器的热注入工具（最小版）。

Tools:
  - editor_run_pie    → 触发编辑器 Play（启动 PIE 运行时）
  - editor_switch_2d  → 编辑器视口切到 2D 正交俯视
  - editor_quit       → 请求关闭编辑器引擎

原理（详见 Doc/Dev/editor_live_protocol.md）:
    MCP(stdio) → 本工具 → 本机回环 TCP 127.0.0.1:8977 (NDJSON)
    → 编辑器 LiveCommandServer → 主线程 pump 执行（复用编辑器按钮同款 API）。
编辑器未运行时工具返回明确错误（先启动 startup.bat）。

启动方式:
    python -m Utils.Editor.mcp_server     （由 .vscode/mcp.json 配置自动拉起）
"""

import json
import os
import socket
import sys

# ── 确保项目根在 sys.path ──
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from mcp.server.fastmcp import FastMCP  # noqa: E402

mcp = FastMCP("Engine Editor Live", version="0.1.0")

DEFAULT_PORT = 8977
_ENV_PORT = "MGE_EDITOR_MCP_PORT"
_next_id = [0]


def _port() -> int:
    try:
        return int(os.environ.get(_ENV_PORT, "") or DEFAULT_PORT)
    except ValueError:
        return DEFAULT_PORT


def _send(op: str, args: dict | None = None, timeout: float = 15.0) -> dict:
    """向编辑器 LiveCommandServer 发送一条命令并等待回执（一行 JSON 往返）。"""
    _next_id[0] += 1
    req = {"id": _next_id[0], "op": op, "args": args or {}}
    port = _port()
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout) as conn:
            conn.sendall((json.dumps(req, ensure_ascii=False) + "\n").encode("utf-8"))
            reader = conn.makefile("r", encoding="utf-8", newline="\n")
            line = reader.readline()
    except ConnectionRefusedError:
        return {"error": f"编辑器未运行（127.0.0.1:{port} 无监听）— 请先启动 startup.bat。"}
    except (socket.timeout, TimeoutError):
        return {"error": f"等待编辑器响应超时（{timeout}s）— 编辑器可能未在处理帧。"}
    except OSError as e:
        return {"error": f"连接失败: {e}"}
    if not line:
        return {"error": "编辑器连接被关闭（可能正在退出）"}
    try:
        resp = json.loads(line)
    except ValueError:
        return {"error": f"无法解析编辑器回执: {line!r}"}
    if resp.get("ok"):
        return resp.get("result") or {"ok": True}
    return {"error": resp.get("error") or "unknown editor error"}


@mcp.tool()
def editor_run_pie() -> dict:
    """触发编辑器 Play（等同 Run 按钮）：启动 PIE 运行时。

    Returns:
        {"requested": true, "state": "pending_start"} 或 {"requested": false, "state": ...}
        或 {"error": "..."}
    """
    return _send("sim.play")


@mcp.tool()
def editor_switch_2d() -> dict:
    """把编辑器视口切换到 2D 正交俯视模式（等同视图工具栏的 2D 按钮）。

    Returns:
        {"mode": "2d", "label": "2D (Ortho)"} 或 {"error": "..."}
    """
    return _send("view.set_mode", {"mode": "2d"})


@mcp.tool()
def editor_quit() -> dict:
    """请求关闭编辑器引擎（等同点击窗口关闭按钮，下一帧开始正常退出流程）。

    Returns:
        {"closing": true, "via": "window_close_request" | "run_state"} 或 {"error": "..."}
    """
    return _send("editor.quit")


if __name__ == "__main__":
    mcp.run()
