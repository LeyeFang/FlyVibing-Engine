# 项目改名执行计划（Rebrand）

> 状态：**执行中（2026-10-14 拍板：产品名 FlyVibingEngine，仓库 FlyVibing-Engine）**。
> 旧名 `MyGameEngine-Python`（内部代号 MGE）保留双读 ≥1 版本。
> 已完成：pyproject 名 / 安装器（AppName、目录、Start Menu、文件关联、输出名）/ README 标题与仓库链接 /
> 环境脚本文案 / 窗口标题与横幅 / **数据目录迁 FlyVibingEngine + 首用复制迁移** / **env 双读 `FVE_*` 优先回退 `MGE_*`**
> （`Application/Core/AppIdentity.py`：`env_get()` / `data_dir()` / `migrate_legacy_data_dir()`）。
> 未做：旧名仓库 URL 全量替换（文档内旧链接）、`MGE_GTEC_SERVICE` 等设备类 env 双读、改名后实机 e2e。
> **核心原则：改「分发与标识面」，保留「技术面」** —— 波及面最小化，一次做完，
> 借助"未发布 = 唯一零成本窗口"完成。

---

## 1. 决策点（拍板后执行）

| # | 项 | 建议 | 状态 |
|---|---|---|---|
| D1 | 最终名 | ✅ **FlyVibingEngine**（仓库 `FlyVibing-Engine`、工具仓 `FlyVibing-User-And-Developer-Utils`；env 前缀 `FVE_`）— 2026-10-14 拍板 | 已执行 |
| D2 | CLI / 包名前缀 | `fly` 已被 fly.io 占用 → `flyvibe`（console script、wheel 前缀） | ⏳ 待拍板 |
| D3 | 数据目录迁移 | `%APPDATA%/MyGameEngine` → `%APPDATA%/FlyVibe`，首启动自动迁移（复制不删） | 默认执行 |

## 2. 波及清单

### 2.1 必改（分发 / 标识面）

| 面 | 现状 | 目标 | 备注 |
|---|---|---|---|
| git 仓库名 | MyGameEngine-Python | fly-vibe-engine | 用户自理；GitHub 改名后旧 URL 自动 301 |
| pyproject | name = "FlyExpEngine"（临用） | 终名 | 同步 README 徽章/标题 |
| 窗口标题 / 启动横幅 | `[glfwWindow]` 等 | 终名 | |
| 安装包 | MyGameEngine-Setup-0.1.0.exe | FlyVibe-Setup-*.exe | **Inno AppId 变更 = 系统视为新应用**（旧版需先卸载） |
| 文件关联 | MyGameEngine.Project（.myproj） | FlyVibe.Project | 迁移期可双关联 |
| 环境变量 | `MGE_*`（EXTENSIONS_DIR/STATE/DATA、MCP_FRAMES_DIR、GTEC_SERVICE、EEG_TRANSPORT、TEST_TMP） | `FVE_*` | **双读兼容 ≥1 版本**（见 §3） |
| 用户数据目录 | `%APPDATA%/MyGameEngine`（extensions 等） | `%APPDATA%/FlyVibe` | 迁移逻辑：旧目录存在 → 复制迁移 |
| wheel / import 名 | engine_editor_mcp | flyvibe_mcp（待 D2） | console script 同步改名；仓库内引用一次全改（Test/E2E 自持） |
| 文档标题 | 各 README / 协议头部 | 终名 | |
| engine-editor skill 名 | engine-editor / node-graph | **保留**（功能描述性，动它 = 用户侧破坏） | |
| MCP server 注册名 | engine-editor-live | **保留** | |

### 2.2 保留（技术面 — 改了收益小、破坏大）

- `Application/**` 模块路径（import 面）。
- `ext.*` 扩展命名空间 / `extension.json` 格式 / `.scene` / `game.json`。
- `Plugin` / `EditorPlugin` 旧名 shim（同时保留）。
- 部署副本（`Test/TestProject/EmptyGame/dist`、`MI-SSSEP rst`、Installer stage）——不追改，随下次导出刷新。

## 3. 兼容策略

1. **env 双读**：新增 helper `env_get("FVE_X", "MGE_X")` 统一读取（新名优先，旧名回退），
   写入侧只写新名；文档标注旧名有效期（≥1 版本）。
2. **数据目录迁移**：ExtensionManager 初始化时检测旧目录 → `shutil.copytree`（不删旧）。
3. **安装器**：AppId 变更导致新旧并存 → 安装时检测旧安装并提示先卸载（参考 Inno 脚本钩子）。
4. **旧 URL 引用**：仓库改名后检查 `.vscode/mcp.json`、CI、文档中的绝对路径。

## 4. 执行序列（拍板后，一次性）

1. 全仓清单化：`grep -r "MyGameEngine\|MGE_"`（排除 Test 部署副本 / `.git`）→ 逐项改。
2. pyproject + console scripts + wheel 重发（含 `engine-editor-cli` 是否更名决定）。
3. 启动脚本（startup.bat / run_game.cmd 模板）+ 安装器文案 + Inno AppId。
4. `env_get` 双读 helper 落地（engine / MCP / test_runner 三侧）。
5. 数据目录迁移逻辑 + 首次启动迁移测试。
6. 文档全量抽查（Doc/**/README + 头部标题）。
7. 实机 e2e：启动 → MCP 连接 → 扩展 enable → 截图 → 退出。

## 5. 验收

- [ ] 干净 venv `pip install` 新 wheel → `engine-editor-cli` / MCP 全通
- [ ] 启动横幅 / 窗口标题 / 安装包名为新名
- [ ] 旧 env 变量（MGE_*）单独设置仍生效（兼容验证）
- [ ] 旧数据目录自动迁移（含 extensions.json）
- [ ] 安装器安装 → 卸载 → 残留检查干净
- [ ] 全量 core 测试 36/36 通过
