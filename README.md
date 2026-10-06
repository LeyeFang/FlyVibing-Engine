# MyGameEngine

Python（3.14t free-threaded）游戏引擎 + 可视化编辑器（ImGui / Vulkan / GL / SDL2）。

## 快速开始（开发者）

```powershell
git clone <repo-url>
cd MyGameEngine-Python
Utils\Dev\setup_env.bat      # 一键: uv + Python 3.14t + .venv-py314t（依赖按 uv-py314t.lock 同步）
startup.bat                  # 启动编辑器
```

唯一前提：安装 [uv](https://docs.astral.sh/uv/)（其余自动完成）。

`startup.bat` 自动调度解释器：开发检出优先 `.venv-py314t`（编辑器全量依赖）；安装版（无 venv）回退内置 `Resource/runtime`（游戏子集镜像，启动器优选镜像内 `python3.14t.exe`）。

### 仓库体积策略（重要）

仓库**不携带** wheelhouse 与 Python 运行时镜像（拉取保持轻量）——开发者按需本地重建：

| 产物 | 重建命令 | 说明 |
|---|---|---|
| `Resource/wheels/` | `Utils\Dev\collect_wheels.py` | 从 PyPI 下载全部离线轮子；**唯一例外**：`imgui_bundle` cp314t 引导轮随 git 提供（PyPI 无该发行，无法自动下载） |
| `Resource/runtime/` | `Utils\Dev\prepare_runtime.py` | 内置 Python 运行时镜像（安装器 / 游戏导出共用；启动器优先 `python3.14t.exe`） |

## 目录结构

| 路径 | 内容 |
|---|---|
| `Application/` | 引擎与编辑器源码（Core / Editor / Runtime / Functions） |
| `Resource/` | 内置资源；`runtime/`、`wheels/` 为本地生成物（不进 git） |
| `Utils/Dev/` | 开发与打包工具链：环境脚本、锁文件、轮子收集、运行时镜像、安装器 |
| `Utils/User/` | 使用侧工具：`player.bat`（无编辑器运行）、`EditorMcp/`（编辑器实时 MCP + CLI + Skill）、`NodeEditor/`（节点图工具：CLI + MCP） |
| `Doc/Dev/`、`Doc/User/` | 协议文档 / 用户指南 |
| `Test/` | 本机测试与测试工程（不进版本控制） |

## 常用命令

```powershell
Utils\Dev\setup_env.bat                                            # 环境安装 / 修复 / 更新
.venv-py314t\Scripts\python.exe Utils\Dev\collect_wheels.py        # 重建 wheelhouse
.venv-py314t\Scripts\python.exe Utils\Dev\prepare_runtime.py       # 预制运行时镜像
.venv-py314t\Scripts\python.exe Utils\Dev\Installer\build_installer.py   # 构建 Windows 安装包
Utils\User\player.bat <project.myproj>                             # 播放器（无编辑器）
```

编辑器内 **File ▸ Export** 可导出自包含工程包（含 runtime + wheelhouse，双击 `run_game.cmd` 即玩）。

## AI 助手（MCP / CLI / Skill）

编辑器运行时，AI agent 可实时操控引擎（建模/摆场景/搭节点图/校验/截图——如同 Fusion360+MCP）。
三种形态（省 token 优先）详见 `Doc/User/editor_mcp_guide.md`：

```powershell
# ① 终端 CLI（零常驻上下文成本 — 任意终端型 agent 首选）
engine-editor-cli call sim.state

# ② 在任意项目工作区启用（一条命令：Skill + MCP lite 档）
engine-editor-cli setup --workspace C:\path\to\your-project

# ③ 只想要旧式 MCP：手写 mcp.json
# { "servers": { "engine-editor-live": { "type": "stdio", "command": "engine-editor-mcp", "args": ["--profile", "lite"] } } }
```

（`engine-editor-mcp` / `engine-editor-cli` 为安装器提供的 PATH 命令；仓库开发环境用 `Utils\User\EditorMcp\install_mcp.py` 注册。v0.4.0: lite 档 5 工具
schema 从 ≈17.9k 字符（44 工具）降到 ≈2.3k 字符。）
