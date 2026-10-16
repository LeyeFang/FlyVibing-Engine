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

**三层消费模型（2026-10-16 定稿 —— "agent 面对 doc 更多时间在查字典索引"）：**

| 层 | 载体 | 回答的问题 | 输出量级 |
|---|---|---|---|
| ① 大方向指引 | 引擎仓 `Doc/**` 的 md stub | 这份文档面对什么问题？内容去哪获得？ | 一屏以内 |
| ② 字典索引（**最常停留层**） | `doc` = 全主题两级索引（主题目的行 + 次级标题）；`doc outline <topic>` = 章节索引（标题 + 一行预览）；`doc search` = 跨主题 | 哪些主题/章节与当前情境相关？ | 数十行 |
| ③ 内容 | `doc show <topic>#节` | 这一节具体怎么规定的？ | 一节 |

关键约束：正文只在第③层出现；①②层必须可"扫读"（短行、目的行/预览自动提取、标题不带噪声）。

- **内容家**：工具仓 `packages/editor-mcp/src/engine_editor_mcp/docs_content/{dev,extdev}/<topic>.md`
  - 随 wheel 打包（`pyproject` package-data + `build_wheel.py` 递归采集均已接）。
- **服务层**：`doclib.py` —— 按 `## ` 分节；裸名解析；跨主题搜索；目的行/预览自动提取
  （句号收尾、CJK 折行伪影清理、去列表标记）。
- **CLI**：`engine-editor-cli doc [list|outline|show|search] <topic[#节号|标题片段]>`
- **指针 stub**：引擎仓 `Doc/Dev|ExtDev/<name>.md` = "面对什么问题" + "去哪获得内容"
  （CLI 命令块 + 章节清单 + 内容权威路径）。
- **容量红线（②层次级标题）**：每主题 ≤ 9 节（`##` 级）；超限先并节——索引的可用性上限是
  "一屏扫完"，不是存储上限。
- **守卫**：`test_editor_mcp_package.py::test_doc` —— 每个 docs_content 主题必须有对应 stub 且
  stub 含 `doc show <topic>`；wheel 载荷含 docs_content。
- **同步纪律**：工具仓为权威源（skill 同款三副本纪律 + 本次新增 MI-SSSEP 部署副本）。

## 3. 试点记录（2026-10-16）

- 迁移：`Doc/Dev/project_export_protocol.md` → `docs_content/dev/project_export_protocol.md`（7 节 / 184 行）；
  引擎侧改 stub（"面对什么问题 / 去哪获得内容"格式）。
- 验证：`doc`（两级索引）/ `doc outline`（标题 + 预览）/ `doc show …#3` / `doc search` 均通；
  wheel 载荷含 docs_content；包测试 + 引擎套件通过。
- 索引质量项（本次打磨）：目的行在句号处收尾（防截断半句）；`_normalize_text` 清理中文折行伪影
  （CJK 间空格、标点后空格）；预览去 `- [ ]`/`- ` 列表标记。

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
- **Q2 stub 风格**：**已定**（2026-10-16）= "面对什么问题" + "去哪获得内容（CLI 命令块）" + 精简章节清单 + 权威路径。
  GitHub 在线浏览只见 stub —— 用户已定"markdown 只做大的方向性指引"，接受。
- **Q3 MCP 暴露**：`engine_help` 增 `doc` 主题，或新 MCP 工具 `engine_doc`（lite 档预算需 <3000 chars）→ 待定。
- **Q4 搜索增强**（相关度/摘要）——先不做。
