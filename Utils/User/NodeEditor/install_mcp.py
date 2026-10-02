#!/usr/bin/env python3
"""
Node Graph Editor MCP — 一键安装 (跨平台)。

用法:
  python Utils/User/NodeEditor/install_mcp.py
  python Utils/User/NodeEditor/install_mcp.py --uninstall
"""

import json, os, subprocess, sys

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

MCP_SERVER_CONFIG = {
    "type": "stdio",
    "command": "python",
    "args": ["-m", "Utils.User.NodeEditor.mcp_server"],
    "cwd": PROJECT_DIR,
}


def get_mcp_path() -> str:
    """返回 MCP 配置文件的路径 (工作区优先)。"""
    workspace_mcp = os.path.join(PROJECT_DIR, ".vscode", "mcp.json")
    if os.path.exists(os.path.dirname(workspace_mcp)):
        return workspace_mcp

    os.makedirs(os.path.dirname(workspace_mcp), exist_ok=True)
    return workspace_mcp


def read_mcp_config(path: str) -> dict:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def write_mcp_config(path: str, config: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def install():
    print("=" * 50)
    print("  Node Graph Editor MCP — Install")
    print("=" * 50)
    print(f"  Project: {PROJECT_DIR}")

    # 1. Install mcp package
    print("\n[1/3] Installing mcp Python package...")
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "mcp", "--quiet"],
                       check=True)
        print("  ✓ mcp installed")
    except subprocess.CalledProcessError:
        print("  ⚠ mcp install failed, trying fastmcp...")
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", "fastmcp", "--quiet"],
                           check=True)
            print("  ✓ fastmcp installed")
        except subprocess.CalledProcessError:
            print("  ✗ Failed to install mcp/fastmcp")
            return 1

    # 2. Generate config
    print("\n[2/3] Generating MCP config...")
    mcp_path = get_mcp_path()
    config = read_mcp_config(mcp_path)
    config.setdefault("servers", {})
    config["servers"]["node-graph-editor"] = MCP_SERVER_CONFIG
    write_mcp_config(mcp_path, config)
    print(f"  ✓ Config written to: {mcp_path}")

    # 3. Verify
    print("\n[3/3] Verifying...")
    server_path = os.path.join(PROJECT_DIR, "Utils", "User", "NodeEditor", "mcp_server.py")
    if os.path.exists(server_path):
        print("  ✓ mcp_server.py found")
    else:
        print("  ✗ mcp_server.py NOT found")
        return 1

    try:
        import mcp  # noqa: F401
        print("  ✓ mcp module importable")
    except ImportError:
        try:
            import fastmcp  # noqa: F401
            print("  ✓ fastmcp module importable")
            # Update config for fastmcp
            config["servers"]["node-graph-editor"] = {
                "type": "stdio",
                "command": "fastmcp",
                "args": ["run", "Utils/User/NodeEditor/mcp_server.py"],
                "cwd": PROJECT_DIR,
            }
            write_mcp_config(mcp_path, config)
        except ImportError:
            print("  ✗ No MCP module available")
            return 1

    print("\n" + "=" * 50)
    print("  Install complete!")
    print(f"  Config: {mcp_path}")
    print("  Restart VS Code to activate.")
    print("=" * 50)
    return 0


def uninstall():
    print("=" * 50)
    print("  Node Graph Editor MCP — Uninstall")
    print("=" * 50)

    mcp_path = get_mcp_path()
    config = read_mcp_config(mcp_path)
    if "servers" in config and "node-graph-editor" in config["servers"]:
        del config["servers"]["node-graph-editor"]
        write_mcp_config(mcp_path, config)
        print(f"  ✓ Removed from: {mcp_path}")
    else:
        print("  (no config found)")

    print("=" * 50)
    return 0


if __name__ == "__main__":
    if "--uninstall" in sys.argv:
        sys.exit(uninstall())
    else:
        sys.exit(install())
