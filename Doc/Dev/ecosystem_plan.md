# 开发者生态剥离计划（工具链分发）

> 状态：**立项（2026-10-11）**。触发背景：第三方开发者（扩展作者 / 实验开发者）要接入
> agent 工具链时，需进引擎应用目录手动复制 wheel、翻找文档 —— 文档复杂、路径不可发现。
> **核心洞见：痛点是「分发方式」而非「文件位置」** —— 只要一条安装命令可得全套工具，
> 物理位置就不重要。故：**发布物化优先，物理拆分后置**。

---

## 1. 三层模型

| 层 | 内容 | 触发条件 | 状态 |
|---|---|---|---|
| **L0 发布物化** | ① MCP/CLI wheel（已有）② **SDK**（类型存根 + 扩展模板 + 文档入口）③ 文档三分区 ④ 一键发布脚本 | 立即 | ⏳ 部分已有 |
| **L1 独立工具仓库** | `fly-tools`（tools 源码 + skills + SDK），CI 发 GitHub Release / PyPI；引擎仓引用发布版 | ≥2 个外部扩展作者，或克隆体积成为痛点 | 未开始 |
| **L2 SDK 版本轴** | SDK 独立 semver + 兼容矩阵（sdk ↔ api_version ↔ engine）；脚手架 `flyvibe ext new` | 社区成型 | 未开始 |

## 2. L0 具体项（本阶段）

- [x] **文档三分区**（2026-10-11 完成）：`Doc/User`（用户）/ `Doc/ExtDev`（社区开发者，自包含）/
      `Doc/Dev`（引擎内部）；扩展开发规范已迁 `Doc/ExtDev/extension_dev_protocol.md`。
- [ ] **SDK 目录** `SDK/`：
  - `SDK/ext-template/` — 扩展脚手架模板（现阶段 = 以 `Functions/SignalProcess` 为最小活模板，
    后续抽 cookiecutter 化）；
  - `SDK/stubs/` — `ExtensionBase` / `ExtensionContext` / ctx 能力的 `.pyi` 存根
    （开发者不在引擎仓也有 IDE 补全）；
  - `SDK/README.md` — 开发者入口（指向 `Doc/ExtDev`）。
- [ ] **发布脚本**：一次构建全部 wheel（EditorMcp / NodeEditor / SDK）+ 生成 checksums →
  `dist/`；GitHub Release 流程文档化。
- [ ] **开发者体验链文档化**：`pip install <tools-wheel>` → `engine-editor-cli setup`（已有，向任意
  工作区装 skill + mcp.json）→ （L2）`ext new`。`Doc/User/editor_mcp_guide.md` 中"从仓库复制"措辞
  改为安装命令表述。

## 3. 决策点

| # | 决策 | 建议 |
|---|---|---|
| D1 | 仓库策略 | **monorepo 发布物化先行**；拆仓库等外部作者信号（过早拆 = 同步地狱） |
| D2 | SDK 形态 | wheel 内含存根 + 模板（pypi 可发）；git 模板作为补充 |
| D3 | 发布渠道 | GitHub Release 附件先行（改名完成后考虑 PyPI） |
| D4 | CLI 终名 | 依赖 `rebrand_plan.md` D2 |

## 4. 依赖关系

- 发布渠道与命名 **依赖改名拍板**（rebrand_plan D1/D2）——L0 内容开发可并行，
  发布动作在改名完成后执行。
- SDK `api_version` 契约与引擎 `extension_dev_protocol.md` §4 版本闸门联动
  （api_version 升版 → SDK 兼容矩阵更新）。
