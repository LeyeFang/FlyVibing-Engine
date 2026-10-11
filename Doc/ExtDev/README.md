# Doc/ExtDev — 扩展开发者文档（社区）

> **读者**：为引擎编写 **扩展（Extension）** 的社区开发者 —— 引擎团队以外的开发者，
> 以及**无上下文的 AI agent**（本区文档自包含：开发扩展**不需要**阅读 `Doc/Dev/` 内部协议）。
>
> 当前项目名 `MyGameEngine-Python` 为临时名，改名计划见 `../Dev/rebrand_plan.md`。

---

## 1. 从这里开始

| 步骤 | 入口 |
|---|---|
| ① 理解扩展体系是什么 | `extension_dev_protocol.md` §1（三层模型与适用范围） |
| ② 写第一个扩展（3 文件最小样例） | `extension_dev_protocol.md` §2 快速上手 |
| ③ manifest（extension.json）字段参考 | §4（含状态语义/broken 规则） |
| ④ 生命周期与 ctx 能力 | §5 / §6（M0 实装 vs M1/M2 规划） |
| ⑤ 扩展 UI / 节点包 | §7 / §8（`[M1]` 设计约定） |
| ⑥ agent 工具链（MCP / CLI / Skill） | §9 生态核心 + `../User/editor_mcp_guide.md` |
| ⑦ 测试与提交检查单 | §12 / §14 |
| ⑧ 静态审查（提交前必跑） | `python Utils/User/ExtensionKit/review_extension.py <扩展目录>`（manifest/代码/完备性全查） |

## 2. 官方示例扩展（对照学习 — 推荐先读源码）

| 扩展 | 目录（本仓库） | 状态 | 示范内容 |
|---|---|---|---|
| SignalProcess | `Functions/SignalProcess/` | skeleton（可装载） | 最小 extension.py + `ext.sigproc.info` op 注册 |
| SerialParallelDevice | `Functions/SerialParallelDevice/` | partial | **官方完整示例**：独立监视面板 + 设置管理 + `ext.device.*` ops（开发中） |
| BCIAlgorithm | `Functions/BCIAlgorithm/` | partial | FBCSP/CCA 算法资产迁移规划 |
| EEGDevice (Gtec) | `Functions/EEGDevice/Gtec/` | partial | 品牌设备进程架构（独立 env + 中介线程） |

> 每个扩展目录内含 `TODO.md`（状态档案 + 落地清单），是本展示范。

## 3. 获取方式与生态（过渡期 → 目标）

- **当前（过渡期）**：扩展开发在引擎仓库内进行（`Functions/**`）；agent 工具链经
  `Utils/User/EditorMcp` 的 wheel 安装（`engine-editor-cli setup` 可向任意工作区装配 skill + mcp.json）。
- **目标（规划）**：SDK 包（类型存根 + 脚手架模板 + 文档）+ 一条安装命令的开发者体验；
  剥离路径与触发条件见 `../Dev/ecosystem_plan.md`。

## 4. 硬性约定速览（详细见规范全文）

- **命名空间**：一切对外贡献挂在 `ext.<id>.`（ops / 节点类型 `ext.<id>.<Type>`）；
  不得覆盖内置名字（除非 manifest 显式 override 且接受警告）。
- **版本闸门**：`api_version` 必须与宿主兼容（当前 `"1"`），否则扩展被隔离为 broken。
- **依赖方向**：扩展可依赖引擎公开能力（`ctx.*` / SDK），**严禁** monkey-patch 引擎内部；
  引擎仓库代码不得反向 import 扩展（唯一例外 = ExtensionManager 动态导入）。
- **线程纪律**：后台线程不得触碰 UI；唯一通道 `ctx.ui.post`（`[M1]`）；见规范 §10。
- **窗口完备性**（含 ui 的扩展）：继承 `UIExtensionBase` + 声明 `close_policy`（窗口 X 语义）+
  实现 `on_ui_event` 收尾 —— 语言层强制 + 审查器自动查；见规范 §7。
- **测试**：每个扩展必须带自测（无头可跑）；见 §12。

---

## 文档地图（本区）

| 文档 | 内容 |
|---|---|
| `extension_dev_protocol.md` | **规范全文**（14 节）：快速上手 / manifest / 生命周期 / ctx 能力 / UI / 节点包 / MCP-CLI 生态 / 线程 / 测试 / 实装地图 / 提交检查单 |
| （规划）`../Dev/ecosystem_plan.md` | 开发者生态剥离路径（SDK / 发布物化 / 社区仓库） |
