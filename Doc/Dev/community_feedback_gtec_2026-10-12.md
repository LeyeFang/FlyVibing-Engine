# 扩展开发文档反馈 — 实际困惑点与缺口清单

> 提交对象: 引擎扩展体系 / 文档维护者（供消化进 `Doc/ExtDev/**` 与工具链）。
> 来源: 2026-10-12 开发 `Functions/EEGDevice/Gtec/`（M1 第二个官方示例「实时监视面板」）全程实录。
> 配套材料: `Doc/Dev/upstream_imgui_beginchild_fullclip.md`（imgui 上游 issue 卷宗 — 条目 A1 的证据）
> 与 `Utils/Dev/repro_imgui_child_clipping.py`（复现脚本, 长期可重跑）。
> 存档位置: 本文件原在扩展示例目录内, 2026-10-12 归档到 `Doc/Dev/`（官方示例目录保持纯净）。
> 消化状态: 见本文 §6（引擎侧处置记录）。
> 口径: 只记录**实际卡过、或不得不离开 ExtDev 文档与工具去引擎源码/上游求证**的点；
> 每条 = 场景 → 卡点 → 实际答案出处 → 建议动作。文中行号/引文均以本仓当前文件为准。

---

## 0. 速览

| # | 类别 | 一句话 | 现状态 |
|---|---|---|---|
| A1 | 宿主渲染行为 | 最小化 0x0 → `BeginChild` False → 漏 `EndChild` → 渲染循环被杀; 定位需引擎 UI 源码 + 上游 imgui 头文件 | 已回代文档; 建议再补"排查入口" 3 行 |
| A2 | 加载机制 | 扩展内同目录模块可直接 `import`（加载器注入 `sys.path`）— 该事实只写在 `ExtensionManager` 源码注释里 | 建议 §3 补一行 |
| A3 | 设备数据通路 | 扩展如何消费 EEG 设备（门面 / 三模式 / 无硬件验收通道）— ExtDev 无入口 | 建议增"设备类扩展"指针段 |
| A4 | 实时面板模式 | 节流拉取 / 快照 / 冻结-重建 只存在于示例, 未成规则 | 建议 §7 提炼 3 条 |
| A5 | 验证渠道 | GUI 场景（UiBoot / ui_scenario）+ 实机 e2e 不在 §12; 含双列表同步陷阱 | 建议 §12 加参照 |
| B1 | 口径不一致 | §4 "capabilities 见 §6 总表" → §6 没有 `device`; 合法值集实际只在审查器 M5 | 建议 §4 直列值集 |
| B2 | 口径不一致 | "禁止顶层 import imgui"（§2/§12.3） vs 两个官方示例都顶层 `import imgui_bundle` | 需定夺后统一 |
| B3 | 措辞歧义 | §9.1 "op 名强制前缀 `ext.<id>.`" 与审查器 C4 "不得自带前缀" 表述似相反 | 建议改写 |
| B4 | 缺项 | 审查器 C6 导入白名单 4 个前缀未进正文; 正文只有"公开能力"字样 | 建议列入正文 |
| C1 | 自动化（备查） | Extensions 菜单下拉勾选无法程序化点击 | 无阻塞（op 已覆盖语义） |

---

## 1. 明细（A 组 — 需要引擎/上游信息才能解决的问题）

### A1. 窗口栈配对 / 全裁剪崩溃（本批最大坑）

- **场景**: 面板运行中, 把编辑器窗口最小化。
- **卡点**: 约 51 s 后渲染循环被异常杀死, 报错为
  `Must call EndChild() and not End()! (imgui.cpp:8677)` —— 且报错发生在**无关的** `end_panel()`;
  跳过错配的那一帧当时无任何报错（错误与根因在时间和调用栈上都相隔很远）。
- **实机证据（引擎日志）**:

  ```
  [EditorHost] Time: 33.6011, Event: WindowResizeEvent, Window Size: (width, height) = (0, 0)
  [13740] [imgui-error] In window 'Gtec Monitor/##gtec_controls_E3D4498F/##gtec_view_5A5EAB57':
                        Must call EndChild() and not End()!
  [EditorHost] Time: 84.4790, Event: EngineLifecycleEvent,
               [exception] _render_loop EXCEPTION: IM_ASSERT( (g.WithinEndChildID == window->ID)
               && "Must call EndChild() and not End()!" )   ---   imgui.cpp:8677
  ```

- **当时必须知道、但 ExtDev（及主应用文档）都没有的四个事实**:
  1. 宿主窗口最小化 → 后续帧 `DisplaySize = 0x0`（全裁剪）——引擎日志里唯一的线索是那条
     `WindowResizeEvent (0,0)`;
  2. `BeginChild()` 在全裁剪时返回 **False**, 但 `EndChild()` **无条件配对**
     （Dear ImGui 1.92.3 `imgui.h` 原文已写明; 官方自认这是与其它 BeginXXX 不一致的历史遗留）;
  3. 官方调试开关 `io.ConfigDebugBeginReturnValueOnce / ...Loop` 可主动翻转返回值, 专抓此类错配;
  4. **首帧例外**: 窗口首次在 0x0 下绘制时 `BeginChild()` 仍返回 True（从第二帧起才判定裁剪）
     —— 复现脚本必须先在正常尺寸画一帧, 否则复现不出来。
- **实际答案出处**: 引擎崩溃日志 → 引擎 UI 源码链（`UIManager.draw_all` → `BasePanel.end_panel`
  → `imgui.end`）→ 上游 `imgui.h` v1.92.3 → 裸 imgui 复现实验（本次成稿
  `Utils/Dev/repro_imgui_child_clipping.py`, 4/4 语义实证）。
- **已回代**: `extension_dev_protocol.md` §7 第 7 条 + `ui_protocol.md` §2 第 13 条 +
  回归测试（`test_gtec_extension` 全裁剪段）+ 复现/issue 材料。
- **建议**: §7 第 7 条再补 3 行, 让后来者 10 分钟定位而非 1 小时 —
  (a) 最常见触发 = 宿主窗口最小化（0x0 全裁剪）;
  (b) 排查入口 = 引擎日志中 `WindowResizeEvent (0,0)` 之后的时段 + 逐处检查 `begin_child` 配对;
  (c) 首帧例外 + 复现脚本路径（`Utils/Dev/repro_imgui_child_clipping.py`）。

### A2. 同目录模块导入机制（加载器行为未见于文档）

- **场景**: 扩展拆成多文件: `extension.py + gtec_display.py + gtec_scope.py`。
- **卡点**: 同目录模块能否直接 `import`？需要相对导入吗？文档（§2/§3/§12）未提加载器行为,
  无从确认。
- **实际答案出处**: `Application/Editor/Extensions/ExtensionManager.py` `_load()`:
  ```python
  if info.dir not in sys.path:
      sys.path.insert(0, info.dir)   # 允许扩展 import 同目录模块（M0; 打包期再收窄）
  ```
- **建议**: §3（目录与命名规范）增一行: 「同目录私有模块: 加载器会把扩展目录加入 `sys.path`,
  可直接裸 `import <module>`; 不要用包相对导入（扩展不是包）; 该机制标注 M0、打包期可能收窄,
  以本节为准」。

### A3. 设备类扩展的数据通路（ExtDev 无入口）

- **场景**: 设计"实时观察 + 软件实时滤波 + 采集落盘"面板, 需要拿到 EEG 设备数据。
- **卡点**: ExtDev 没有"如何消费设备"的入口。实际需要知道的一整套都在别处:
  门面 API（`init_session / start_record / get_data / session.stop`）、
  `sim / device / virtual` 三模式的用途、**无硬件如何跑全链路验收**、
  面板能否直接调品牌 API（结论: 不能）、真实模式服务进程如何启动。
- **实际答案出处**: `Doc/Dev/device_io_protocol.md` §7/§8/§11 + 门面源码
  `Application/Functions/EEGDevice/Device.py` + 品牌 README
  `Application/Functions/EEGDevice/Gtec/README.md` + `ServiceClient.py`。
- **建议**: ExtDev 增短节「设备类扩展（指针）」, 5 行即可:
  统一经门面（`Application.Functions.EEGDevice` — 在 C6 白名单内; **禁直触品牌 API**）;
  三模式用途（`sim` 进程内确定性/无副作用 · `device` 真实硬件+外部服务进程 ·
  `virtual` 引擎自动拉起、**无硬件全链路验收通道**）; 真实模式服务进程启动见品牌 README;
  指针 → `device_io_protocol.md` §8/§11。

### A4. 实时数据面板模式（建议提炼为规则）

- **场景**: `draw_fn`（渲染线程帧内）每帧画实时波形。
- **卡点**: 拉数据频率多少才不伤害渲染帧？设置变更要不要重新拉数据？冻结态如何保持？
  —— 文档没有答案, 全靠自行判断（最终实现: 刷新节流 ~25 Hz + 环形缓冲只读拷贝 +
  设置变更"冻结帧重建、不拉新数据"）。
- **现状**: §7 行为契约第 5 条只有"快照式读取"一句; 节流/冻结语义只存在于示例代码里。
- **建议**: §7 提炼 3 条:
  (a) **节流**: 拉取按 ~25 Hz 级节流, 绝不每帧全量拷贝;
  (b) **快照**: 只读会话缓冲快照（如 `session.get_data(elapsed)` 的时间序拷贝）,
  渲染线程零阻塞;
  (c) **解耦**: UI 设置变更只重算展示层（抽取/滤波/标尺）, 不触发数据拉取 ——
  冻结语义因此完好（参见 gtec 示例 `_last_pull` / `_rebuild_view()`）。

### A5. 验证渠道: GUI 场景与实机 e2e（§12 只覆盖无头单测）

- **场景**: 验证"面板画得出来 / 全裁剪不崩 / ops 能驱动"。
- **卡点**: §12 只讲无头单测（`test_<id>_extension.py`）; GUI 场景怎么跑、实机 e2e 走什么通道、
  截图/证据放哪, 均需从既有测试基建逆向。
- **实际渠道**（可作 §12 参照示例）:
  - GUI 场景（手动）: `python Test/Application/Editor/ui_scenario.py gtec_panel_smoke`
    — 场景文件 `Test/Application/Editor/scenarios/gtec_panel_smoke.py`, 截图落 `Test/_runs/`;
  - 实机 e2e（引擎运行中）: `Test/Application/Extensions/e2e_gtec_monitor_check.py`
    — 经 CLI/MCP 驱动 `extension.enable` → `ext.gtec.*` 全链路。
- **附带陷阱（值得写进 §12）**: `Test/Application/Editor/_ui_boot.py` 的**面板注册列表是
  `EditorImguiLayer._init_ui_panels` 的手工副本** —— 扩展/内建新增窗口时两处都要加;
  本项目曾漂移（被 `panels_smoke` 抓出）。另: scenarios 目前不在 runner 档位内, 需手动运行
  （`test_protocol.md` 口径）。
- **建议**: §12 加一行「GUI 场景与实机 e2e 参照」: 上面两条路径 + 运行命令 + 双列表同步警示。

---

## 2. 明细（B 组 — 文档内部口径不一致, 需人工定夺）

### B1. `capabilities` 合法值集（§4 指向错误）

- **现状**: §4 表格写「`capabilities` | 建议 | 声明所需能力（**见 §6 总表**）」;
  但 §6 是"ctx 能力总表"（`ops/ui/nodes/settings/threads/jobs/bus`）—— **没有 `device` 行**;
  合法值集实际在审查器 M5: `{"ops","ui","nodes","threads","jobs","settings","device"}`。
  本扩展示例 manifest 使用 `["ops","ui","device"]`（`device` 不在 §6 表内）。
- **建议**: §4 直接列出值集（与 M5 同源声明）; 或在 §6 补 `device` 行并说明
  "capabilities 取值 = 能力表 key, 另含 `device`（进程外品牌设备）特例"。

### B2. "禁止顶层 import imgui" 与官方示例互相矛盾

- **规则文本**: §2 代码块注释「入口（headless 安全 — **禁止顶层 import imgui**）」+
  §12.3「扩展入口必须 headless 可加载（**顶层不得 import imgui**; GUI 代码放窗口回调内）」。
- **实际**: 两个官方示例（`Functions/EEGDevice/Gtec/extension.py` 与
  `Functions/SerialParallelDevice/extension.py`）都**顶层** `from imgui_bundle import imgui`;
  实测无显示环境下纯导入**无副作用**（不建 context/GL/窗口）, 全部无头测试
  （含 ExtensionManager 装载冒烟）通过; 审查器 C 项也没有该检查。
- **推测动机**: 运行环境（游戏层 runtime / 导出包）可能不含 `imgui_bundle`? 但扩展只在
  编辑器装载, 不会触达该环境 —— 规则的真实边界需要澄清。
- **建议**: 择一统一口径, 推荐「禁止顶层**创建** context/窗口/GL; 纯模块导入允许
  （编辑器环境必有 imgui_bundle; 未来若需在无 imgui 环境加载扩展, 由宿主先做能力探测）」;
  或为两个示例补延迟导入。**文档与示例必须一致**（当前开发者会先读到规则、再被示例推翻）。

### B3. op 前缀措辞（容易被读反）

- **现状**: §9.1 写「约束: op 名**强制前缀** `ext.<id>.`（违反 → 加载期 ValueError）」;
  审查器 C4 写「ops 注册名**不得自带** "ext." 前缀（前缀由宿主强制）」—— 两句话字面相反。
- **实际正确行为** = C4: 扩展注册裸名（`ctx.ops.register("status", ...)`）→
  宿主生成 `ext.gtec.status`; 若注册名自带 `ext.` 前缀会被拒。
- **建议**: §9.1 改写为「宿主**强制加**前缀 `ext.<id>.`; 扩展注册名**不得自带** `ext.`
  前缀（自带 → 加载期 ValueError, 扩展 broken）」。

### B4. 导入白名单未进正文

- **现状**: 审查器 C6 的白名单 = `Application.Core.Extension` / `Application.Functions` /
  `Application.Core.Events` / `Application.Core.ThreadRegistry`; 但正文（README §4 与协议 §3）
  只有"扩展可依赖引擎公开能力（`ctx.*` / SDK）"这类字样 —— "`Application.Functions.*`
  可导入"（设备门面就走这条）这类关键信息实际只在工具里。
- **建议**: §3 或 §14 检查单列出这 4 个前缀, 并与 C6 同源声明"以审查器为准"。

---

## 3. 其他（C 组 — 备查, 不构成阻塞）

- **C1 实机自动化**: Extensions 菜单下拉的勾选无法被程序化点击（菜单弹出层没有自动化入口;
  本批用真实鼠标脚本时也仅作补充）。实际 e2e 用 `extension.enable` / `extension.disable`
  op 已完整覆盖勾选语义 —— 仅列备查; 若未来提供"菜单项可编程触发"指引（哪怕一句"用
  `extension.enable` 代替 UI 勾选"）可省去每个扩展作者各自摸索。

---

## 4. 本批已自行回代/新增的文档改动（供核对）

| 文件 | 位置 | 内容 | 日期 |
|---|---|---|---|
| `Doc/ExtDev/extension_dev_protocol.md` | §7 第 7 条 | imgui 窗口栈配对纪律（全裁剪 / 无条件 `EndChild` / 回归测试指针） | 2026-10-12 |
| `Doc/ExtDev/extension_dev_protocol.md` | §7 官方示例行 / §13 实装地图 | gtec 监视面板示例登记 | 2026-10-12 |
| `Doc/Dev/ui_protocol.md` | §2 第 13 条 | 同规则（主应用侧口径）+ 全裁剪回归测试指针 | 2026-10-12 |
| `Doc/Dev/device_io_protocol.md` | §11 | 监视面板数据通路 / 三模式 / 面板纪律 | 2026-10-12 |

## 5. 开发期实际依赖过的 ExtDev 之外资料（自包含性评估素材）

| 资料 | 为什么需要它 |
|---|---|
| `Doc/Dev/device_io_protocol.md` | 设备门面 / 服务进程 / 三模式（A3） |
| `Doc/Dev/threading_protocol.md` | 线程纪律 —— "面板零阻塞"原则的底线来源 |
| `Doc/Dev/test_protocol.md` | runner 档位 / 输出契约 / scenario 运行方式（A5） |
| `Doc/Dev/ui_protocol.md` | 文本安全（§12）、配对纪律（§2 第 13 条 — 本批回代） |
| `Application/Editor/Extensions/ExtensionManager.py` | 加载机制 / `sys.path` 注入 / 状态机（A2） |
| `Application/Editor/Extensions/ExtensionUI.py` | 窗口隔离 / close_policy 实现细节核查 |
| `Application/Editor/UI/panels/**`（UIManager / BasePanel / ExtensionPanel） | 崩溃链定位（A1） |
| `Application/Functions/EEGDevice/**`（门面 + 品牌 README + ServiceClient） | 数据通路（A3） |
| `Test/Application/Editor/{ui_scenario.py, _ui_boot.py, scenarios/}` | GUI 场景引导（A5） |
| 上游 Dear ImGui 1.92.3 `imgui.h` | `BeginChild` 契约 / 官方调试开关（A1） |
| 上游 `imgui_bundle` 绑定细节（如 `set_ini_filename`） | 复现脚本工程化 |

## 6. 复现 / 验证资产索引

| 资产 | 路径 | 用途 |
|---|---|---|
| imgui 上游 issue 卷宗（ISSUE.md + 复现脚本） | `Doc/Dev/upstream_imgui_beginchild_fullclip.md` + `Utils/Dev/repro_imgui_child_clipping.py`（2026-10-12 由扩展示例目录迁出） | A1 证据（可直接转交 imgui / imgui_bundle 上游） |

---

## 6. 引擎侧消化记录（2026-10-12）

| 条目 | 处置 | 落点 |
|---|---|---|
| A1 | 纪律已回代（他的 §4）+ **新增静态守卫**：反模式从"1 小时定位"变为 CI 拦截 | `ui_protocol.md` §2.13 / `ExtDev` §7.7 / `Test/Application/Editor/test_imgui_stack_pairing.py` / reviewer C8 |
| A2 | **待办**（本轮范围外）：加载器 `sys.path` 注入行为写入 `ExtDev` §3 | `[M1]` |
| A3 | **待办**：ExtDev 增「设备类扩展（指针）」短节 | `[M1]` |
| A4 | **待办**：实时面板三规则（节流/快照/设置解耦）提炼进 `ExtDev` §7 | `[M1]` |
| A5 | **待办**：`ExtDev` §12 补 GUI 场景 + 实机 e2e 渠道与 `_ui_boot` 双列表警示 | `[M1]` |
| B1 | **已裁决**：`capabilities` 值集直列于 §4（与审查器 M5 同源）；`device` 补进 §6 能力表，语义 = 「允许导入设备门面（`Application.Functions.EEGDevice`）」, **不引入 `ctx.device`** | `ExtDev` §4/§6 |
| B2 | **已裁决**：口径改为「禁止顶层**创建** context/窗口/GL；纯模块导入允许」；审查器新增 C10 机械检查 | `ExtDev` §2/§12 · `review_extension.py` C10 |
| B3 | **已修正**：措辞改为「宿主**强制加**前缀 `ext.<id>.`；扩展注册名**不得自带**前缀」 | `ExtDev` §9.1 |
| B4 | **已修正**：C6 白名单 4 前缀进正文并声明"以审查器为准" | `ExtDev` §3/§14 |
| C1 | **已补一句**：实机自动化用 `extension.enable` / `extension.disable` op 替代菜单勾选 | `ExtDev` §12 |
| 材料位置 | **已迁出**：issue 卷宗 + 复现脚本 + 本反馈文档移出官方示例目录（示例保持"可被复制"的纯净度） | 本表首行 + 本文头部 |

> 遗留（未纳入本轮）：A2–A5 的 ExtDev 自包含性补强；扩展侧 i18n 通道（`ctx.i18n` + 目录注册 + 审查器 C8/M7 命名让位 — 现 C8 已被窗口栈占用，i18n 检查编号顺延）。
| 扩展无头测试（含全裁剪回归段） | `Test/Application/Extensions/test_gtec_extension.py` | A1 回归守卫 / A4 数值断言 |
| 实机 e2e | `Test/Application/Extensions/e2e_gtec_monitor_check.py` | A5 实机通道样板 |
| GUI 场景 | `Test/Application/Editor/scenarios/gtec_panel_smoke.py` | A5 GUI 场景样板 |
| 本扩展运作说明 / 状态档案 | `Functions/EEGDevice/Gtec/README.md` / `TODO.md` | 背景 |
