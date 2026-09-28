#!/usr/bin/env python3
"""
Engine Editor Live MCP — 一键安装（跨平台）。

用法:
  .venv-py314t\\Scripts\\python.exe Utils/Editor/install_mcp.py
  .venv-py314t\\Scripts\\python.exe Utils/Editor/install_mcp.py --uninstall

注册到工作区 .vscode/mcp.json（名称: engine-editor-live）。
安装后需重载 VS Code 窗口（或 MCP: List Servers → 重启）才能被 agent 看到。
"""

import json
import os
import sys

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SERVER_NAME = "engine-editor-live"


def _python_command() -> str:
    """优先用项目 venv 的 python（mcp 包在其中），否则回退 PATH 的 python。"""
    venv_py = os.path.join(PROJECT_DIR, ".venv-py314t", "Scripts", "python.exe")
    return venv_py if os.path.isfile(venv_py) else "python"


def _mcp_path() -> str:
    return os.path.join(PROJECT_DIR, ".vscode", "mcp.json")


def _read_config(path: str) -> dict:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _write_config(path: str, config: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def install() -> int:
    print("=" * 50)
    print("  Engine Editor Live MCP — Install")
    print("=" * 50)

    try:
        import mcp  # noqa: F401
        print("  ✓ mcp package importable")
    except ImportError:
        print("  ✗ mcp 包不可用 — 先运行 Utils/generate_venv.bat（或 pip install mcp）")
        return 1

    config_path = _mcp_path()
    config = _read_config(config_path)
    config.setdefault("servers", {})
    config["servers"][SERVER_NAME] = {
        "type": "stdio",
        "command": _python_command(),
        "args": ["-m", "Utils.Editor.mcp_server"],
        "cwd": PROJECT_DIR,
    }
    _write_config(config_path, config)
    print(f"  ✓ 注册 '{SERVER_NAME}' → {config_path}")
    print(f"    command: {_python_command()} -m Utils.Editor.mcp_server")

    server_src = os.path.join(PROJECT_DIR, "Utils", "Editor", "mcp_server.py")
    print(f"  ✓ mcp_server.py: {'found' if os.path.isfile(server_src) else 'MISSING!'}")
    print()
    print("下一步: 重载 VS Code 窗口（或 Command Palette → 'MCP: List Servers' 重启）")
    return 0


def uninstall() -> int:
    config_path = _mcp_path()
    config = _read_config(config_path)
    if config.get("servers", {}).pop(SERVER_NAME, None) is not None:
        _write_config(config_path, config)
        print(f"  ✓ 已移除 '{SERVER_NAME}'")
    else:
        print(f"  - '{SERVER_NAME}' 未注册")
    return 0


if __name__ == "__main__":
    sys.exit(uninstall() if "--uninstall" in sys.argv else install())
