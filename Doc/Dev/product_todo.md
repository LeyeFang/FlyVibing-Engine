# 产品待办 — 扩展剥离 / 节点编辑器 UX / 1.0 与 macOS

> 状态：活文档（2026-10-21 建立）。记录“现在不做但别忘”的事项；完成一项就改状态并留验收证据。
> 测试体系待办另见 `Doc/Dev/test_map_todo.md`。

## 1. 流程与 CI（暂缓）

| 事项 | 状态 | 说明 |
|---|---|---|
| GitHub Actions PR 门禁 | **暂缓** | 团队规模小、测试面仍在变；先把本地 `test_runner --tier core` 用顺 |
| 本地 pre-push 快检 | 可选 | `test_map.py check` + `ui check` + `core` 即可；不要阻塞小团队节奏 |
| 重新评估 CI 的信号 | 待触发 | ≥2 名常态维护者 / 外部 PR 增多 / 需要夜间 GUI 回归 / 发布节奏固定 |
| 社区扩展仓库治理 | **不接管** | 我们只保证引擎侧扩展 API、审查器和文档；社区自己的 Git 仓库由他们负责 |

> CI 方案已在上轮讨论：PR 跑 `guards + core`，GUI nightly/self-hosted；不要在团队小、测试未稳时引入高协调成本。

## 2. BCI Algorithm / Virtual Device 出核心

| 事项 | 状态 | 验收 |
|---|---|---|
| BCI 求值器迁入扩展 | **已完成** | `evaluator.py` / `evaluator_epoch.py`；核心不再 import |
| Virtual 求值器迁入扩展 | **已完成** | `evaluator_siggen.py` / `evaluator_pool.py`；核心不再 import |
| BCI 扩展壳 + ops | **已完成** | `extension.py`；`ext.bci.status/models/datasets` |
| 交接书 | **已完成** | `Application/Functions/BCIAlgorithm/HANDOFF.md`；`VirtualDevice/HANDOFF.md` |
| 通用规则注册 API | 待做 | 把 `graph_constraints` 的 BCI/Epoch/DevicePool 规则迁到扩展注册 |
| 通用 dry-run cleanup hook | 待做 | 核心不再直接 import BCI/Virtual 清理函数 |
| Runtime cleanup hook | 待做 | `GameRuntime` / `PlayerBootstrap` 不再知道具体设备扩展 |
| 物理独立仓库/包 | 待做 | 引擎只保留 manifest 发现路径；`export` 清单明确 |
| 扩展自测迁移 | 部分 | BCI 35/35、Virtual 119/49/29；`test_bci_empty_data` 仍在归档 |

## 3. 节点编辑器 UX

### 3a. 节点组拖动 / 重排 / 嵌套

| 事项 | 状态 | 验收 |
|---|---|---|
| 组框可拖动 | **已完成** | 拖动 group frame → 整棵成员子树平移；`node_groups_smoke` 覆盖真实 NodeId 拖动 |
| 组感知 Rearrange | **已完成** | `group_layout.py`；组是外层布局单元，父组包住子组，节点连到组时相邻排开 |
| 组内重排 | **已完成** | 组内递归布局；`Rearrange Group` + `Fit Group`；父组自动回流 |
| 嵌套组编辑 | **已完成（首版）** | Groups 窗口显示 parent/children 树；选中子组可单独重排 |
| 组创建/删除/改父子关系 GUI | 待做 | 目前只能由 tools `add_group/set_group` 产生/修改；GUI 只做布局编辑 |
| 组框缩放手柄 | 待做 | 当前尺寸由成员包围盒推导；手动 resize 需要持久化 layout 元数据 |
| 组成员增删 GUI | 待做 | 拖入/拖出组成员尚未实现 |

### 3b. 节点查询窗口

| 事项 | 状态 | 验收 |
|---|---|---|
| Find Node 窗口 | **已完成** | 工具栏 Add 同级；搜索 alias/type/label/description；`node_editor_find` 10/10 |
| Go To | **已完成** | `center_node_on_screen`（API 缺失回退 `navigate_to_selection`） |
| Delete | **已完成** | 删除选中结果并清理连线 |
| 快捷键 / 过滤类型 | 待做 | 例如 Ctrl+F、仅看当前组、仅看未命名 |
| 模糊匹配 / 拼音 | 待做 | 当前为大小写不敏感 token 子串匹配 |

### 3c. 适配视图（Fit）

- **结论：保留**。实现是 `imgui_node_editor.navigate_to_content()`，把全部节点/组框缩放进视口；用于全景检查和截图。
- 已加 tooltip（`node_editor.fit_tip`）；`node_editor_smoke` 覆盖调用路径。
- 若未来增加“适配当前组”，使用 `Fit Group`（已实现，选中组成员后 `navigate_to_selection`）。

## 4. FlyVibing 1.0.0 Release

| 事项 | 状态 | 说明 |
|---|---|---|
| 版本号 / 品牌收口 | 待做 | 引擎名统一 FlyVibing；检查 `AppIdentity`、窗口标题、导出包名、文档 |
| Release 内容冻结 | 待做 | 先完成 3a–3c + BCI/Virtual 出核心 + core 全绿 |
| 安装器 / 导出成品 | 待做 | Windows 安装包、runtime wheelhouse、示例工程、许可证 |
| Release notes / 兼容矩阵 | 待做 | engine / extension api_version / Python 3.14t / 依赖版本 |
| 发布后回归 | 待做 | 干净机器安装 + 打开示例 + PIE + 导出成品 |

## 5. macOS 适配与发布（1.0 之后）

| 风险 | 说明 | 先验证什么 |
|---|---|---|
| OpenGL / GLFW | macOS 对 OpenGL 已弃用；当前渲染后端是 GL | 先跑最小 GLFW 窗口 + 现有 shader；评估 Metal 后端成本 |
| free-threaded Python | 3.14t 在 macOS 的轮子可用性 | `uv python install 3.14t` + numpy/scipy/pillow/imgui_bundle 安装矩阵 |
| 字体 | `Locale/*.json` 声明 msyh/PingFang；Linux/mac 回退 | 中文 UI 无 `?`；字体候选按 `_meta.fonts` 增量 |
| 路径/大小写 | Windows 反斜杠、junction、盘符 | 全仓路径审计；`Utils/ExtDev` 符号链接替代 |
| 设备 SDK | 厂家 SDK/串并口驱动的平台差异 | 虚拟设备先通；真实品牌按 macOS SDK 单独评估 |
| 打包 | 安装器 / runtime 镜像 / wheelhouse | 先在 macOS 源码运行；再决定 .app / dmg |
| CI | 无 macOS runner 时至少本地脚本 | 先做 `startup.sh` + `test_runner --tier core` 的 macOS 冒烟 |

> 原则：**先让源码在 macOS 跑起来，再谈发布**；不要在没有真实 macOS 回归前承诺 Release 可用。
