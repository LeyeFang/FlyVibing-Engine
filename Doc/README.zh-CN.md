# FlyVibingEngine

**语言：** [English](../README.md) | 简体中文

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](../LICENSE)
[![Python 3.14](https://img.shields.io/badge/python-3.14%20free--threaded-3776AB.svg)](https://www.python.org/)
[![Platform: Windows](https://img.shields.io/badge/platform-Windows-0078D4.svg)](#环境要求)

FlyVibingEngine 是一个用于构建、预览和运行实验范式的 Python 游戏引擎与可视化编辑器。它将场景与实体编辑、节点图编排、编辑器内运行（PIE）以及带自包含导出流水线的独立运行时整合在一起。

引擎面向实验工作而非通用游戏生产：工程是可直接纳入版本控制的普通文件；行为以可检查的节点图表达；设备 I/O 与信号处理模块是一等能力；导出的成品自带 Python 运行时与依赖。

> 面向引擎使用者的创作与自动化工具链维护在独立仓库：[FlyVibing-User-And-Developer-Utils](https://github.com/LeyeFang/FlyVibing-User-And-Developer-Utils)。

## 主要特性

引擎聚焦四个方向：

- **Agent 辅助开发** —— 编辑器操作通过本地命令接口开放给 CLI 与 MCP 客户端。
- **实验场景构建** —— 场景、刺激与设备可在编辑器内配置，并与导出成品共用运行时预览。
- **实验流程设计** —— 以节点图定义试次流程，支持节点组复用、校验与流程检查。
- **社区扩展支持** —— 通过分层扩展模型添加设备、算法、界面与节点，无需改动引擎核心。

## 环境要求

| 角色 | 要求 |
|---|---|
| 终端用户 | Windows 10/11。安装包已包含引擎、Python 运行时与全部依赖，无需安装 Python 或包管理器。 |
| 开发者 | [uv](https://docs.astral.sh/uv/) 与 Python 3.14 自由线程环境，由 `Utils\Dev\setup_env.bat` 安装到 `.venv-py314t`。 |
| 自动化客户端 | 独立[工具链包](https://github.com/LeyeFang/FlyVibing-User-And-Developer-Utils)需要 Python 3.10+。实时操作要求编辑器正在运行。 |

## 快速开始

### 安装（终端用户）

运行单独分发的 `FlyVibingEngine-Setup-*.exe` 安装包，然后从开始菜单或桌面快捷方式启动编辑器。

### 从源码运行

```powershell
git clone https://github.com/LeyeFang/MyGameEngine-Python.git
cd MyGameEngine-Python
Utils\Dev\setup_env.bat
startup.bat
```

`setup_env.bat` 通过 uv 安装 Python 3.14t，并按 `Utils\Dev\uv-py314t.lock` 同步依赖。`startup.bat` 优先使用 `.venv-py314t`；在安装版中回退到内置运行时。

### 不打开编辑器运行工程

```powershell
Utils\User\player.bat path\to\project.myproj
```

也可以在编辑器中通过 **File ▸ Export** 导出工程。导出包包含运行时、离线 wheelhouse 与 `run_game.cmd`。

## 仓库结构

| 路径 | 内容 |
|---|---|
| `Application/` | 引擎、编辑器与运行时源码（`Core/`、`Editor/`、`Runtime/`、`Functions/`） |
| `Application/Functions/` | 内置模块与扩展：设备 I/O、信号处理、BCI 算法、虚拟设备 |
| `Resource/` | 字体、图标、材质、网格、Shader、纹理与预制体；`wheels/` 包含离线依赖清单与引导轮 |
| `Utils/Dev/` | 开发环境、测试入口、轮子收集、运行时预制与安装器构建 |
| `Utils/User/` | 随导出成品分发的文件（`player.bat`） |
| `Doc/Dev/` | 引擎内部开发协议与架构约定 |
| `Doc/ExtDev/` | 扩展开发规范 |
| `Doc/User/` | 用户指南，包括编辑器自动化 |

## 相关仓库

| 仓库 | 范围 |
|---|---|
| **MyGameEngine-Python**（本仓库） | 引擎、编辑器、运行时、内置模块与引擎研发工具 |
| [**FlyVibing-User-And-Developer-Utils**](https://github.com/LeyeFang/FlyVibing-User-And-Developer-Utils) | 创作与自动化工具链：`editor-mcp`、`node-editor`、`extension-kit` 与 agent skills |

两个仓库并排开发时：

```powershell
git clone https://github.com/LeyeFang/FlyVibing-User-And-Developer-Utils.git ..\FlyVibing-User-And-Developer-Utils
Utils\Dev\link_tools.bat
pip install -e ..\FlyVibing-User-And-Developer-Utils\packages\editor-mcp
```

## 编辑器自动化

编辑器运行时，回环命令服务器监听 `127.0.0.1:8977`。工具链仓库提供：

- `engine-editor-cli` —— 命令行客户端；
- `engine-editor-mcp` —— 提供 lite 与 full 两档的 MCP 服务端；
- `flyvibing-node-editor` —— 离线构图、校验与场景注入。

一条命令完成工作区的 Skill 与 MCP 配置：

```powershell
engine-editor-cli setup --workspace C:\path\to\your-project
```

用户指南见 [`Doc/User/editor_mcp_guide.md`](User/editor_mcp_guide.md)，协议见 [`Doc/Dev/editor_live_protocol.md`](Dev/editor_live_protocol.md)。

## 文档

| 读者 | 入口 |
|---|---|
| 引擎开发者 | [`Doc/Dev/README.md`](Dev/README.md) —— 开发协议与文档地图 |
| 扩展开发者 | [`Doc/ExtDev/README.md`](ExtDev/README.md) —— 自包含扩展指南 |
| 实验设计者 | [`Doc/User/editor_mcp_guide.md`](User/editor_mcp_guide.md) 与[工具链教学](https://github.com/LeyeFang/FlyVibing-User-And-Developer-Utils/blob/main/docs/TUTORIAL.md) |
| 工具链维护者 | [工具链 README](https://github.com/LeyeFang/FlyVibing-User-And-Developer-Utils) |

## 开发

| 任务 | 命令 |
|---|---|
| 安装或修复开发环境 | `Utils\Dev\setup_env.bat` |
| 运行核心回归测试 | `.venv-py314t\Scripts\python.exe Utils\Dev\test_runner.py --tier core` |
| 重建离线 wheelhouse | `.venv-py314t\Scripts\python.exe Utils\Dev\collect_wheels.py` |
| 预制内置运行时镜像 | `.venv-py314t\Scripts\python.exe Utils\Dev\prepare_runtime.py` |
| 构建 Windows 安装包 | `.venv-py314t\Scripts\python.exe Utils\Dev\Installer\build_installer.py` |

开发流程遵循 `Doc/Dev/` 中的协议。改动应通过相关测试，并同步更新对应协议文档。

## 贡献

欢迎提交 Issue 与 Pull Request。涉及编辑器行为、节点类型、设备集成或打包流程的改动，请先阅读 `Doc/Dev/` 中对应文档，并在实现时同步更新。

## 许可证

[MIT](../LICENSE) © 2026 Leye Fang
