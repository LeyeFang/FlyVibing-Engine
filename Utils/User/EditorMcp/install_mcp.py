#!/usr/bin/env python3
r"""
Engine Editor Live MCP — 一键安装（跨平台）。

用法（dev 仓库）:
  .venv-py314t\Scripts\python.exe Utils/User/EditorMcp/install_mcp.py                # 默认 lite 档（5 精简工具, 省 token）
  .venv-py314t\Scripts\python.exe Utils/User/EditorMcp/install_mcp.py --profile full # 旧 44 工具档
  .venv-py314t\Scripts\python.exe Utils/User/EditorMcp/install_mcp.py --uninstall

用法（安装版 / 零外部 Python）:
  Resource\runtime\python3.14t.exe Utils\User\EditorMcp\install_mcp.py

注册到工作区 .vscode/mcp.json（名称: engine-editor-live）并把 engine-editor Skill
同步到 <仓库>/.github/skills/engine-editor/（渐进披露; 编辑器内 AI 直接可用）。
安装后需重载 VS Code 窗口（或 MCP: List Servers → 重启）才能被 agent 看到。
"""

import json
import os
import shutil
import sys

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SERVER_NAME = "engine-editor-live"


def _python_command() -> str:
    """解释器调度（自包含优先）: dev venv → 内置 runtime → 当前解释器。

    安装版（无 venv）用内置 runtime（含全量依赖, 零外部 Python 负担）;
    dev 检出用 .venv-py314t；绝不留下 PATH 级 python 依赖。
    """
    venv_py = os.path.join(PROJECT_DIR, ".venv-py314t", "Scripts", "python.exe")
    if os.path.isfile(venv_py):
        return venv_py
    for exe in ("python3.14t.exe", "python.exe"):
        rt = os.path.join(PROJECT_DIR, "Resource", "runtime", exe)
        if os.path.isfile(rt):
            return rt
    return sys.executable


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


def _skill_source() -> str:
    return os.path.join(PROJECT_DIR, "Utils", "User", "EditorMcp", "src", "engine_editor_mcp", "skills", "engine-editor")


def _skill_dest() -> str:
    return os.path.join(PROJECT_DIR, ".github", "skills", "engine-editor")


def _sync_skill() -> None:
    """把 Skill（含 references）同步到仓库 .github/skills/（渐进披露, agent 按需加载）。"""
    src, dest = _skill_source(), _skill_dest()
    if not os.path.isdir(src):
        print("  ! skill payload missing:", src)
        return
    shutil.rmtree(dest, ignore_errors=True)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copytree(src, dest)
    print(f"  ✓ skill 已同步 → {dest}")


def install(profile: str = "lite") -> int:
    print("=" * 50)
    print("  Engine Editor Live MCP — Install")
    print("=" * 50)

    try:
        import mcp  # noqa: F401
        print("  ✓ mcp package importable")
    except ImportError:
        print("  ✗ mcp 包不可用 — 先运行 Utils/Dev/setup_env.bat（或 pip install mcp）")
        return 1

    config_path = _mcp_path()
    config = _read_config(config_path)
    config.setdefault("servers", {})
    config["servers"][SERVER_NAME] = {
        "type": "stdio",
        "command": _python_command(),
        "args": ["-m", "Utils.User.EditorMcp.mcp_server", "--profile", profile],
        "cwd": PROJECT_DIR,
    }
    _write_config(config_path, config)
    print(f"  ✓ 注册 '{SERVER_NAME}'（profile={profile}） → {config_path}")
    print(f"    command: {_python_command()} -m Utils.User.EditorMcp.mcp_server --profile {profile}")

    server_src = os.path.join(PROJECT_DIR, "Utils", "User", "EditorMcp", "mcp_server.py")
    print(f"  ✓ mcp_server.py: {'found' if os.path.isfile(server_src) else 'MISSING!'}")
    _sync_skill()
    print()
    print("下一步: 重载 VS Code 窗口（或 Command Palette → 'MCP: List Servers' 重启）")
    print("提示: lite 档 = 5 个精简工具（省 token）; 需要旧 44 工具用 --profile full")
    return 0


def uninstall() -> int:
    config_path = _mcp_path()
    config = _read_config(config_path)
    if config.get("servers", {}).pop(SERVER_NAME, None) is not None:
        _write_config(config_path, config)
        print(f"  ✓ 已移除 '{SERVER_NAME}'")
    else:
        print(f"  - '{SERVER_NAME}' 未注册")
    dest = _skill_dest()
    if os.path.isdir(dest):
        shutil.rmtree(dest, ignore_errors=True)
        print(f"  ✓ 已移除 skill: {dest}")
    return 0


if __name__ == "__main__":
    _profile = "lite"
    if "--profile" in sys.argv:
        _i = sys.argv.index("--profile")
        if _i + 1 < len(sys.argv):
            _profile = sys.argv[_i + 1]
    sys.exit(uninstall() if "--uninstall" in sys.argv else install(_profile))
