# engine-editor-mcp — 编辑器实时 MCP + CLI（独立发布包）

把 **MyGameEngine 编辑器**的实时控制能力带给任意三方工作区里的 AI agent。
引擎开着，agent 就能干活（编辑器未运行时工具返回明确错误，不会静默失败）。

## 三种消费形态（同一 wheel / 同一 op 注册表）

| 形态 | 未使用时常驻成本 | 适用 |
|---|---|---|
| **CLI** `engine-editor-cli`（终端） | **0** | 任意终端型 agent（Codex / Copilot / Claude Code / Cursor ...）；多步、批处理、脚本首选 |
| **MCP lite**（推荐档） | ~0.7k tokens（5 个工具） | IDE 内 agent；`engine_help` / `engine_call` / `engine_batch` / `engine_validate_graph` / `engine_capture` |
| **MCP full**（兼容档） | ~5.6k tokens（44 个工具） | 旧提示词/旧工作流仍绑定 `editor_*` 工具名时（`--profile full`） |

> 另有 Skill（`engine-editor`）：渐进披露的用法文档（SKILL.md + references）——
> agent 只在相关任务时才加载；MCP schema 实测从 17,900 字符（44 工具）降到 2,328 字符（lite 5 工具）≈ **-87%**。

## 安装

```powershell
# 方式 1 — wheel（离线分发）
pip install engine_editor_mcp-0.4.0-py3-none-any.whl

# 方式 2 — 从源码安装（dev）
pip install -e Utils/User/EditorMcp
```

依赖：`mcp>=1.10`、`Pillow`、`numpy`。

## 在三方工作区启用（任意 IDE）

```powershell
# 一条命令：拷贝 Skill（.github/skills/engine-editor/）+ 合并 .vscode/mcp.json（lite 档）
engine-editor-cli setup --workspace C:\path\to\your-experiment-project
```

- `--skills claude|agents|all|none` 选择 Skill 目标目录（默认 `.github/skills`）；
- `--profile full` 用旧 44 工具档；`--python <exe>` 指定 MCP 启动解释器；
- `--dry-run` 预览；`--uninstall` 卸载（移除 Skill + mcp.json 条目）。

不用 MCP 的平台也可以只用 CLI：终端里 `engine-editor-cli call sim.state`。

## 使用前提

1. 启动引擎编辑器（仓库内 `startup.bat`；发行版为安装器快捷方式）；
2. 编辑器控制台出现 `[Live] Editor command server on 127.0.0.1:8977` 即就绪。

## CLI 速览

```powershell
engine-editor-cli ops                      # op 目录（45 个）
engine-editor-cli help entity.transform    # 单 op 详情（参数 + 示例）
engine-editor-cli call entity.add name=MCP_Cue
engine-editor-cli call entity.transform id=5 position='[1,0,2]'   # 数组/对象加引号
engine-editor-cli batch ops.json           # 顺序批处理（- = stdin）
engine-editor-cli exec script.py           # 脚本模式（注入 engine 客户端, 可过滤输出 -> 省 token）
engine-editor-cli validate                 # 图干跑校验（默认 summary）
engine-editor-cli capture pie --out f.png  # 抓帧落盘（只回路径）
```

值解析：先按 JSON（数字/true/false/数组/对象/带引号字符串），失败按纯字符串。
退出码：0 成功 / 1 引擎或运行时错误 / 2 用法错误。

## MCP 注册（手写 mcp.json 时）

```json
{ "servers": { "engine-editor-live": {
  "type": "stdio",
  "command": "engine-editor-mcp",
  "args": ["--profile", "lite"]
} } }
```

## 环境变量

| 变量 | 作用 | 默认 |
|---|---|---|
| `MGE_EDITOR_MCP_PORT` | 引擎命令端口（**两侧需一致**） | `8977` |
| `MGE_MCP_FRAMES_DIR` | 抓帧根目录（server 启动时清空） | `<临时目录>/engine_editor_mcp` |
| `MGE_MCP_PROFILE` | MCP 档位 `lite` / `full`（启动参数 `--profile` 优先） | `full`（仓库安装脚本默认写 `lite`） |

## 抓帧说明

- MCP `engine_capture` → PNG 落盘 + **图像直回**（agent 能直接看到画面）；
- CLI `capture` → 只落盘并回路径（不把图像塞进上下文 — 省 token）。

## 与引擎仓库的关系

- 本包源码唯一维护于引擎仓库 `Utils/User/EditorMcp/`（dev shim + 独立包源码 + 构建器 + Skill 源）；
- 协议细节见引擎仓库 `Doc/Dev/editor_live_protocol.md`；
- 新增 op 后：引擎侧注册 → `ops.py` 加条目 → `python -m engine_editor_mcp.docgen` 重生成
  `skills/engine-editor/references/ops.md`（离线测试 `test_editor_mcp_package.py` 会校验一致性）。

