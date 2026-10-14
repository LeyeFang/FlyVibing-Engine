# FlyVibingEngine

游戏引擎 + 可视化编辑器（Dear ImGui / OpenGL / SDL2）。为**实验范式开发**而做：在编辑器里摆场景、
连节点图、跑 PIE 预览，最后导出成可双击运行的成品。

**自带 Python 运行时**：装好即用 —— 使用者不需要装 Python、pip 或任何环境管理器。

- 编辑器：场景/实体/组件、节点图、资源面板、设置（字号/语言）、Extensions 菜单
- 运行时：`Application/Runtime` 可脱离编辑器跑（`player.bat` / 导出成品的 `run_game.cmd`）
- 自动化：编辑器内置**实时命令总线**（回环 TCP），agent 可通过 MCP/CLI 全权操作（见下）

## 安装与启动

### 使用者

跑 `FlyVibingEngine-Setup-*.exe` → 用开始菜单/桌面快捷方式启动。
运行时与全部依赖随安装包交付（安装时用内置 pip + 离线 wheelhouse 就位），**不需求 uv、不需自备 Python**。

> 从空工作区到实验成品的完整教学（配 AI agent）：工具仓库 [`docs/TUTORIAL.md`](https://github.com/LeyeFang/FlyVibing-User-And-Developer-Utils/blob/main/docs/TUTORIAL.md)。

### 开发者（源码）

```powershell
git clone https://github.com/LeyeFang/FlyVibing-Engine
cd FlyVibing-Engine
Utils\Dev\setup_env.bat      # 开发环境（uv 管解释器与锁文件）→ .venv-py314t
startup.bat                  # 启动编辑器
```

前置：装 [uv](https://docs.astral.sh/uv/) —— **仅开发者需要**（它负责把开发环境的解释器与依赖版本
对齐到仓库里的锁文件 `uv-py314t.lock`；使用者那一侧由安装包内的运行时 + wheelhouse 对齐）。

`startup.bat` 自动挑解释器：开发机优先 `.venv-py314t`；安装版（无 venv）回退内置 `Resource/runtime`。

## 两个仓库

本仓库只放**引擎本身与引擎研发工具**；面向"使用引擎"的工具在独立仓库。

| 仓库 | 内容 | 谁用 |
|---|---|---|
| **本仓库** `FlyVibing-Engine` | `Application/`（引擎+编辑器+运行时）、`Functions/`（内置扩展）、`Resource/`、`Doc/`、`Utils/Dev`（研发工具）、`Utils/User`（随成品分发） | 引擎研发；打包实验成品 |
| **[FlyVibing-User-And-Developer-Utils](https://github.com/LeyeFang/FlyVibing-User-And-Developer-Utils)** | `editor-mcp`（编辑器实时 MCP/CLI）、`node-editor`（离线节点图）、`extension-kit`（扩展审查 + 无头测试）、`skills/` | 实验设计者、扩展作者，以及引擎团队自己 |

在引擎仓库里干活时，把工具链链接进来即可（`Utils/ExtDev` 是**链接**，已 gitignore，内容不进本仓库）：

```powershell
Utils\Dev\link_tools.bat                 # 或先 git clone 工具仓库到本仓库同级目录
pip install -e ..\FlyVibing-User-And-Developer-Utils\packages\editor-mcp
```

## 目录结构

| 路径 | 内容 |
|---|---|
| `Application/` | 引擎与编辑器源码（Core / Editor / Runtime / Functions 门面） |
| `Functions/` | 内置扩展（`device` 串并口、`gtec` 脑电监视、`sigproc`、`bci`…） |
| `Resource/` | 资源与预制体；`runtime/`、`wheels/` 为本地生成物（不进 git） |
| `Utils/Dev/` | 研发工具：环境脚本、测试入口 `test_runner.py`、轮子收集、运行时镜像、安装器 |
| `Utils/User/` | 随成品分发的一层：`player.bat`（导出游戏包只带这一层） |
| `Doc/` | `Doc/Dev`（引擎内部协议）、`Doc/ExtDev`（扩展开发规范）、`Doc/User`（用户指南） |
| `Test/` | 测试与测试工程（本机使用，不进版本控制） |

## 常用命令

```powershell
Utils\Dev\setup_env.bat                                         # 环境安装/修复/更新
.venv-py314t\Scripts\python.exe Utils\Dev\test_runner.py --tier core   # 回归测试
.venv-py314t\Scripts\python.exe Utils\Dev\collect_wheels.py     # 重建离线 wheelhouse
.venv-py314t\Scripts\python.exe Utils\Dev\prepare_runtime.py    # 预制内置运行时镜像
.venv-py314t\Scripts\python.exe Utils\Dev\Installer\build_installer.py  # 构建 Windows 安装包
Utils\User\player.bat <project.myproj>                          # 播放器（无编辑器）
```

编辑器内 **File ▸ Export** 可导出成品包（含 runtime + wheelhouse，双击 `run_game.cmd` 即玩）。

## 用 AI agent 操作编辑器

编辑器运行时，agent 可实时建模/摆场景/连节点图/校验/截图（类似 Fusion360 + MCP）。工具与用法见
工具仓库：`engine-editor-cli`（CLI，零常驻上下文）、`engine-editor-mcp`（MCP，lite/full 档）、
`node-graph`（离线设计）。在任意工作区装配 skill + MCP 配置：

```powershell
engine-editor-cli setup --workspace C:\path\to\your-project
```

文档入口：`Doc/User/editor_mcp_guide.md`（用户向）、`Doc/Dev/editor_live_protocol.md`（协议）。

## 文档

| 读者 | 入口 |
|---|---|
| 引擎开发者 | `Doc/Dev/README.md`（协议地图） |
| 扩展开发者 / 社区 | `Doc/ExtDev/README.md`（自包含） |
| 实验/游戏使用者 | `Doc/User/**` |
| 工具链维护 | 工具仓库 README（本仓库 `Utils/README.md` 说明两仓分工） |
