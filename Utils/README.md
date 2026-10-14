# Utils — 引擎研发工具

本目录只放**引擎研发侧**的东西。使用引擎的工具（编辑器 MCP/CLI、节点图工具、扩展工具包）在**独立仓库**：

> **FlyVibing-User-And-Developer-Utils** — https://github.com/LeyeFang/FlyVibing-User-And-Developer-Utils
> 安装：`pip install -e <tools repo>/packages/*`（实验设计者、扩展开发者、引擎团队自己都用它）
> 本机开发：`Utils\Dev\link_tools.bat` 把工具仓库链接进来（`Utils/ExtDev` 是链接，已 gitignore）

## 内容

| 目录 | 受众 | 是否发布 | 内容 |
|---|---|---|---|
| `Dev/` | 引擎研发 | 否 | 环境与测试链（`setup_env.bat` / `test_runner.py` / `rebuild_lock.bat`）、打包与安装器（`collect_wheels.py` / `prepare_runtime.py` / `Installer/`）、探针与复现脚本 |
| `User/` | 终端用户 / 实验员 | **随成品走** | `player.bat`（无编辑器启动游戏）。导出游戏包只带这一层，且跳过 `dist/` `tmp/` `__pycache__` |

## 放新文件前问三句

1. **这是造引擎，还是用引擎？** 造 → `Utils/Dev`；用 → 工具仓库（见上）。
2. **要不要随成品发给实验员？** 要 → `Utils/User`（并登记到守卫的 `USER_ALLOWED_FILES`）。
3. **会不会被外部开发者需要？** 会 → 工具仓库，而不是这里。

## 守卫

`Test/Application/Editor/test_utils_layout.py`（core）机器校验：

- `Utils/` 顶层只有 `Dev` / `User`（工具目录不得回迁）；
- 全仓无 `Utils/ExtDev` 残留引用；
- `Utils/User` 登记制白名单 + 导出行为（whl / png / pyc 不进游戏包）；
- `.github/skills/**` 与工具仓库 `skills/**` 逐字节一致（权威源 = 工具仓库；工具仓库不在本机时该项跳过）。

> 背景：工具链曾与运行时混居在 `Utils/User`，导出游戏时把 wheel、调试截图一并带进了成品（46 个文件）。
> 现在两仓分工 + 守卫把这个坑封住了。
