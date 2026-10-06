#!/usr/bin/env python3
"""
Node Graph Editor MCP — 一键安装 (跨平台)。

用法（dev 仓库）:
  python Utils/User/NodeEditor/install_mcp.py
  python Utils/User/NodeEditor/install_mcp.py --uninstall

用法（安装版 / 零外部 Python）:
  Resource\\runtime\\python3.14t.exe Utils\\User\\NodeEditor\\install_mcp.py

注册到工作区 .vscode/mcp.json（node-graph-editor）并把 node-graph Skill
（渐进披露使用说明）同步到 <仓库>/.github/skills/node-graph/。
"""

import json, os, shutil, subprocess, sys

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _python_command() -> str:
    """解释器调度（自包含优先）: dev venv → 内置 runtime → 当前解释器。"""
    venv_py = os.path.join(PROJECT_DIR, ".venv-py314t", "Scripts", "python.exe")
    if os.path.isfile(venv_py):
        return venv_py
    for exe in ("python3.14t.exe", "python.exe"):
        rt = os.path.join(PROJECT_DIR, "Resource", "runtime", exe)
        if os.path.isfile(rt):
            return rt
    return sys.executable


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


def _skill_source() -> str:
    return os.path.join(PROJECT_DIR, "Utils", "User", "NodeEditor", "skills", "node-graph")


def _skill_dest() -> str:
    return os.path.join(PROJECT_DIR, ".github", "skills", "node-graph")


def _sync_skill() -> None:
    """同步 node-graph Skill（渐进披露使用说明）到仓库 .github/skills/。"""
    src, dest = _skill_source(), _skill_dest()
    if not os.path.isdir(src):
        print("  ! skill payload missing:", src)
        return
    shutil.rmtree(dest, ignore_errors=True)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copytree(src, dest)
    print(f"  ✓ skill synced -> {dest}")


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

    # 1. Ensure mcp package (安装版 runtime 已预装 → 直接跳过; 否则 pip 补齐)
    print("\n[1/3] Checking mcp Python package...")
    try:
        import mcp  # noqa: F401
        print("  ✓ mcp already available")
    except ImportError:
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", "mcp", "--quiet"],
                           check=True)
            print("  ✓ mcp installed")
        except subprocess.CalledProcessError:
            print("  ⚠ mcp install failed (offline?) — continuing, pip later if needed")

    # 2. Generate config（command = 自包含调度后的解释器）
    print("\n[2/3] Generating MCP config...")
    mcp_path = get_mcp_path()
    config = read_mcp_config(mcp_path)
    config.setdefault("servers", {})
    MCP_SERVER_CONFIG["command"] = _python_command()
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

    # 4. Sync skill（渐进披露使用说明 → .github/skills/node-graph）
    _sync_skill()

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

    skill_dest = _skill_dest()
    if os.path.isdir(skill_dest):
        shutil.rmtree(skill_dest, ignore_errors=True)
        print(f"  ✓ Removed skill: {skill_dest}")

    print("=" * 50)
    return 0


if __name__ == "__main__":
    if "--uninstall" in sys.argv:
        sys.exit(uninstall())
    else:
        sys.exit(install())
