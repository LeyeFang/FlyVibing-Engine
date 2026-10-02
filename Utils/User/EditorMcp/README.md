# engine-editor-mcp — 编辑器实时 MCP（独立发布包）

把 **MyGameEngine 编辑器**的实时控制能力带给任意三方工作区里的 AI agent：
本包是一个 stdio MCP 服务器（纯 socket 客户端），连接**正在运行**的编辑器
（默认 `127.0.0.1:8977`），提供 50+ 工具：PIE 控制、实体/组件/场景/资源编辑、
节点图编辑与干跑校验、图导入导出、工程打开、抓帧截图等。

> 不需要把引擎源码放进你的工作区。引擎开着，agent 就能干活。

## 安装

```powershell
# 方式 1 — wheel（离线分发）
pip install engine_editor_mcp-0.3.0-py3-none-any.whl

# 方式 2 — 从源码安装（dev）
pip install -e Utils/User/EditorMcp
```

依赖：`mcp>=1.10`、`Pillow`、`numpy`（pip 自动装）。

## 在三方工作区注册（VS Code）

`.vscode/mcp.json`：

```json
{
  "servers": {
    "engine-editor-live": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "engine_editor_mcp"]
    }
  }
}
```

安装了 console script 后也可直接：

```json
{ "servers": { "engine-editor-live": { "type": "stdio", "command": "engine-editor-mcp" } } }
```

## 使用前提

1. 启动引擎编辑器（仓库内 `startup.bat`；发行版为安装器快捷方式）；
2. 控制台出现 `[Live] Editor command server on 127.0.0.1:8977` 即就绪；
3. 编辑器未运行时工具返回明确错误（"编辑器未运行 — 请先启动"）。

## 环境变量

| 变量 | 作用 | 默认 |
|---|---|---|
| `MGE_EDITOR_MCP_PORT` | 引擎命令端口（**两侧需一致**） | `8977` |
| `MGE_MCP_FRAMES_DIR` | 抓帧文件目录（每次 server 启动清空） | `<临时目录>/engine_editor_mcp` |

## 抓帧说明

`editor_capture` 抓取的 PNG 落在上述临时目录（工具返回绝对路径），图片同时以
MCP 图像内容块回传给 agent —— 通常不需要人工打开文件。

## 与引擎仓库的关系

- 本包源码唯一维护于引擎仓库 `Utils/User/EditorMcp/`（dev 入口 shim + 独立包源码 + 构建器）；
- 引擎仓库内 `Utils/User/EditorMcp/mcp_server.py` 是**薄 shim**（同源码，保留 dev 入口）；
- 协议细节见引擎仓库 `Doc/Dev/editor_live_protocol.md`。
