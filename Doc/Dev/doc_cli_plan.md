# Doc CLI 化 — 方案与试点记录（2026-10-16）

> 定位：计划/记录文档（**保留普通 markdown**——记录不是知识）。目标读者：引擎/工具链维护者。

## 1. 背景与目标

- 开发者（尤其 agent）消费内建文档的方式转向 CLI：整篇加载费 token、grep 噪声大、无按节拉取。
- 目标形态（用户定调）：
  1. **内容迁入 CLI**（随 `engine-editor-cli` 的 wheel 分发）；
  2. **markdown 只留指针**（"本页正文已 CLI 化" stub）;
  3. **仍归类为 Doc** —— 只读知识，不是运行时代码。
- 已有先例：node-editor `get_rules`（按节渐进披露，-89% token）、`docgen`（单一源生成 ops.md）。

## 2. 架构（试点已落地）

- **内容家**：工具仓 `packages/editor-mcp/src/engine_editor_mcp/docs_content/{dev,extdev}/<topic>.md`
  - 随 wheel 打包（`pyproject` package-data + `build_wheel.py` 递归采集均已接）。
- **服务层**：`doclib.py` —— 按 `## ` 分节；裸名解析；跨主题搜索。
- **CLI**：`engine-editor-cli doc [list|outline|show|search] <topic[#节号|标题片段]>`
- **指针 stub**：引擎仓 `Doc/Dev|ExtDev/<name>.md` 替换为指针（用法 + 章节清单 + 内容权威路径）。
- **守卫**：`test_editor_mcp_package.py::test_doc` —— 每个 docs_content 主题必须有对应 stub 且
  stub 含 `doc show <topic>`；wheel 载荷含 docs_content。
- **同步纪律**：工具仓为权威源（skill 同款三副本纪律 + 本次新增 MI-SSSEP 部署副本）。

## 3. 试点记录（2026-10-16）

- 迁移：`Doc/Dev/project_export_protocol.md` → `docs_content/dev/project_export_protocol.md`（7 节 / 184 行）；
  引擎侧改 stub（用法指针 + 章节清单）。
- 验证：`doc`（目录）/ `doc outline` / `doc show …#3` / `doc search` 均通；wheel 载荷含 docs_content；
  包测试 + 引擎套件通过。

## 4. 批量迁移 Runbook（待执行）

1. 复制 `Doc/<area>/<name>.md` → `docs_content/<area>/<name>.md`（内容不改）。
2. 引擎侧替换为 stub（现用 `Test/_runs/doc_cli/stub_it.py`；批量阶段抽成工具仓 `scripts/sync_docs.py`，
   生成 stub 时保留章节清单）。
3. 跑 `Test/Application/Editor/test_editor_mcp_package.py`（stub 守卫 + wheel 载荷）。
4. 重建 wheel + 重装：`python Utils/ExtDev/EditorMcp/build_wheel.py` → `pip install --force-reinstall …whl`。

建议批次（按 agent 使用频率）：
- ① `extdev/extension_dev_protocol` + `extdev/README`（社区开发者主入口）
- ② `dev/editor_live_protocol` · `dev/node_editor_protocol` · `dev/graph_validation_protocol`（agent 工作流）
- ③ 各协议正文（rendering / text / shader / media / device_io / i18n / test / …）
- ④ 历史记录类（roadmap / community_feedback / upstream_imgui / *_plan）——**不迁移**（记录不是知识，留 md）

## 5. 待决事项（拍板后执行）

- **Q1 内容家**：现为工具仓（随 wheel）。备选：引擎仓数据文件 + 工具读取（改为随仓库版本耦合）。
  → 推荐维持工具仓（社区 agent 装 wheel 即有文档；与 skills 同源纪律一致）。
- **Q2 stub 风格**：现行保留"用法指针 + 章节清单 + 权威路径"。GitHub 在线浏览将只见 stub —— 用户已定"markdown 用来提示内容在 cli 里"，接受。
- **Q3 MCP 暴露**：`engine_help` 增 `doc` 主题，或新 MCP 工具 `engine_doc`（lite 档预算需 <3000 chars）→ 待定。
- **Q4 搜索增强**（相关度/摘要）——先不做。
