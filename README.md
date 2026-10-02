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
| `Utils/User/` | 使用侧工具：`player.bat`（无编辑器运行）、`EditorMcp/`（编辑器实时 MCP）、`NodeEditor/`（节点图 MCP） |
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

## AI 助手（MCP）

编辑器运行时，可在任意工作区的 `.vscode/mcp.json` 注册实时 MCP（详见 `Doc/User/editor_mcp_guide.md`）：

```json
{ "servers": { "engine-editor-live": { "type": "stdio", "command": "engine-editor-mcp" } } }
```

（`engine-editor-mcp` 为安装器提供的 PATH 命令；仓库开发环境用 `Utils\User\EditorMcp\install_mcp.py` 注册。）
