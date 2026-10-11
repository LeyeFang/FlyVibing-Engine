# 扩展开发规范协议（Extension Development Protocol）

> 读者: **外部/无上下文的开发者与 agent**（模拟社区生态 — 只有本文件 + 仓库即可开工）。
> 架构背景: `extension_protocol.md`（三层高度模型 / 三档侵入 / 兼容机制）。
> 状态: **M0 已实装 + M1 部分实装**（`ctx.ui.register_window` 2026-10-11；官方示例 = `Functions/SerialParallelDevice`）；
> M1+ 剩余能力在本文件中以 `[M1 待]` 标注（当前为设计约束, 实装后按其验收）。

---

## 1. 适用范围与阅读顺序

1. 本文件（开发规范, **必读**）→ 2. `extension_protocol.md` §1/§3/§4（架构与侵入纪律）→
3. 相关领域协议（`node_editor_protocol.md` / `threading_protocol.md` / `device_io_protocol.md`）。

**扩展（Extension）** = 编辑器应用层的功能模块。当前规划的默认扩展（状态档案在各自目录 `TODO.md`）：

| id | 目录 | 状态 |
|---|---|---|
| `sigproc` | `Functions/SignalProcess/` | skeleton（可装载样例） |
| `bci` | `Functions/BCIAlgorithm/` | partial（内核算已实现, 待迁移） |
| `device` | `Functions/SerialParallelDevice/` | partial（设备 IO 已实现, 面板待做） |
| `gtec` | `Functions/EEGDevice/Gtec/` | partial（服务进程已实现, 监视面板待做） |

## 2. 快速上手（最小扩展）

```
Functions/MyThing/            # 内置扩展（随仓库分发）
  extension.json              # ① 清单
  extension.py                # ② 入口（headless 安全 — 禁止顶层 import imgui）
  TODO.md                     # ③ 状态档案（计划/进行中的扩展必须有）
```

`extension.json`:

```json
{
  "id": "mything",
  "name": "My Thing",
  "version": "0.1.0",
  "api_version": "1",
  "maturity": "skeleton",
  "description": "一句话说明",
  "entry": "extension.py:create_extension",
  "capabilities": ["ops"],
  "requires": []
}
```

`extension.py`:

```python
from Application.Core.Extension.ExtensionBase import ExtensionBase

class MyThingExtension(ExtensionBase):
    id = "mything"
    name = "My Thing"
    version = "0.1.0"

    def on_load(self, ctx):
        self.ctx = ctx
        ctx.ops.register("info", self._op_info, summary="状态查询")
        ctx.log("loaded")

    def _op_info(self, args: dict) -> dict:
        return {"hello": "world"}

def create_extension() -> MyThingExtension:
    return MyThingExtension()
```

启用与验证（编辑器运行中）：

```
engine-editor-cli call extension.enable id=mything     # 或 Extensions 菜单勾选
engine-editor-cli call extension.list                  # 应出现 mything + ext.mything.info
engine-editor-cli call ext.mything.info                # 扩展 op 直接可调（ext.* 透传）
```

## 3. 目录与命名规范

- 目录名建议 = id; manifest 的 `id` 是唯一权威（`^[a-z][a-z0-9_]*$`）。
- 所有对外贡献**强制命名空间**: ops = `ext.<id>.<name>`; 未来节点 = `ext.<id>.<TypeName>`。
- 私有实现文件不限; 资源放扩展目录内（只读）; 可写数据一律用 `ctx.data_dir`。
- 不要把扩展内部文件丢到仓库其它区; 不得修改 `Application/**`（见 §5 侵入纪律）。

## 4. manifest 参考（extension.json）

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | ✅ | 唯一标识; 命名空间前缀; 全局不可重复（重复 → 后加载者 broken） |
| `name` / `version` | ✅ | 显示名 / semver |
| `api_version` | ✅ | 当前仅支持 `"1"`（或 `1.x`）; 不匹配 → broken（菜单灰显原因） |
| `maturity` | ✅ | `planned` / `skeleton` / `partial` / `stable` — 菜单与 `extension.list` 展示 |
| `entry` | 有代码则必填 | `"extension.py:create_extension"` 形式; **文件缺失 → broken**; 省略 = 仅计划（不可启用） |
| `description` | 建议 | 菜单 tooltip / 文档 |
| `capabilities` | 建议 | 声明所需能力（见 §6 总表）; `requires` 暂仅解析展示（依赖拓扑 M3） |

**状态语义**（`extension.list` / 菜单）: `planned`（无 entry）· `disabled`（可装载未启用）·
`enabled`（已装载）· `broken`（manifest/加载错误 — 原因在 `error` 字段与 tooltip）。

## 5. 生命周期契约

```
enable:  构造实例 → on_load(ctx) → on_enable()
disable: on_disable() → on_unload() → 自动注销该扩展全部 ext.<id>.* ops
rescan:  已装载者全部 unload 后重新扫描（Extensions 菜单 ▸ Rescan）
关闭:    ExtensionManager.unload_all()（不改变持久化启用状态）
```

约定：
1. `on_load` 只做**注册类**工作（ops/窗口/节点）; 重初始化放 `on_enable`。
2. 任何一步抛异常 → 该扩展 `broken`（引擎不受影响）; 修复后 `Rescan` 重试。
3. **禁止 monkey-patch 引擎/编辑器类**（运行时 `setattr` 核心类）; 需要在既有行为上挂钩时,
   走架构 Hook 点（`extension_protocol.md` §3.1）并向引擎侧提需求 — 缝外侵入=违规。
4. 卸载必须无残留: 自建线程/句柄在 `on_disable`/`on_unload` 里停干净（M2 起 `ctx.threads` 代管）。

## 6. ctx 能力总表（M0 实装 vs 规划）

| 能力 | 状态 | 说明 |
|---|---|---|
| `ctx.id / name / version / manifest` | ✅ M0 | 元数据 |
| `ctx.extension_dir` / `ctx.data_dir` / `ctx.engine_root` | ✅ M0 | 只读资产目录 / 可写数据目录 / 引擎根 |
| `ctx.log(msg)` | ✅ M0 | `[ext:<id>]` 前缀日志（Console 通道 M1） |
| `ctx.ops.register(name, fn, summary="")` | ✅ M0 | **扩展 op**（§9 生态核心） |
| `ctx.ui.register_window(name, draw_fn, visible=True, flags=None, close_policy="hide")` | ✅ M1 (2026-10-11) | 注册独立窗口（唯一入口 `ExtensionUI`；重名冲突/异常隔离/purge/窗口生命周期完备性 见 §7） |
| `ctx.ui.register_command / post / kit` | `[M1 待]` | 命令 / 帧安全点 / 控件包（设计见 `extension_protocol.md` §5.1） |
| `ctx.nodes.register_pack(...)` | `[M1]` | 节点包（§8 设计） |
| `ctx.settings(schema)` | `[M1]` | schema 化设置（自动 UI + 持久化） |
| `ctx.threads / ctx.jobs / ctx.bus` | `[M2]` | 受管线程 / 后台任务 / 数据总线 |
| `ctx.ui.post(fn)` | `[M1]` | 后台线程 → 渲染线程帧安全点 |

未实装能力对应的 ctx 属性为 `None` — 扩展必须做能力检测（`if ctx.ui is None: ...`）。

## 7. UI 规范（`ctx.ui` — `register_window` 已实装 2026-10-11）

**实装状态**: `ctx.ui.register_window(...)` ✅（`ExtensionUI` / `ExtensionPanel` 桥）;
`register_command / post / kit` 仍 `[M1 待]`。

**行为契约（宿主保证 — 扩展可依赖）**:

1. **渲染线程纪律**: `draw_fn` 在 `UIManager.draw_all` 帧内被调用（`imgui.begin/end` 已由宿主包裹）;
   禁止在 draw_fn 内自建 imgui context / 自行 render / 跨帧持有 imgui 对象。
2. **窗口命名红线**: 与内建面板或其它扩展重名 → `register_window` 抛 `ValueError`（不静默改写）。
3. **异常遏制**: `draw_fn` 异常 → 本帧跳过 + 计数; 连续 120 帧异常 → 自动隐藏（quarantine）;
   扩展不必在 draw 顶层 try/except（可依赖宿主）, 但业务错误建议自查并展示。
4. **启停对称**: disable / 卸载 → 宿主自动注销该扩展全部窗口与 ops（保险丝）;
   enable 重走 on_load（新实例）→ 推荐扩展实现**幂等 `_install(ctx)`**（on_load/on_enable 共用,
   窗口重名 `ValueError` 静默跳过）— 完整模式见官方示例。
5. **线程 → UI 通道**: 快照式读取（业务模块线程安全快照, 如 device 示例每帧 `monitor_snapshot()`）;
   `ctx.ui.post(fn)` 帧安全点 `[M1 待]`; 后台线程不得直接触碰 UI 状态。
6. **视觉**: 强制 UIManager 主题; 窗口默认浮动（用户可手动 dock; 布局 API `[M1 待]`）;
   图标用 FontAwesome 白名单。

**宿主适配点**（扩展体系向主应用支付的**一次性**接入面 — 新扩展不再需要触碰）:

| 适配点 | 内容 | 日期 |
|---|---|---|
| `UIManager.unregister()` | 面板注销基础能力（原先只有 register） | 2026-10-11 |
| View 菜单动态枚举 | 由硬编码 5 面板改为遍历 `_panels`（扩展窗口自动纳入菜单） | 2026-10-11 |
| `ExtensionUI` 桥 | ctx.ui → UIManager 唯一入口 + owner 追踪 + purge 保险丝 | 2026-10-11 |

> 主菜单栏实际渲染 = `UIManager._draw_menu_bar()`（`UI/panels/MenuBarPanel.py` 为未注册保留文件, 不要改错地方）;
> `Extensions` 菜单 = `ExtensionMenu.draw_extensions_menu()`。

**窗口生命周期完备性（2026-10-11 — 面板开关同步闭环）**:

背景: 面板自身关闭（X）与其它状态（Extensions 菜单勾选）曾出现不同步 —— 根因是
**“启用状态”与“窗口可见性”是两条正交的线, 无人负责其联动**。职责划分: 联动策略由
**扩展作者**决定（宿主不可能预知每个扩展的面板语义）, 宿主提供机制, 三重保障 =
本文档 + 静态审查器 + Python 语言层强制。

| 状态 | 语义 | 责任 |
|---|---|---|
| 注册 | `register_window` 成功（装配期） | 扩展（经 ctx.ui） |
| 可见/隐藏 | 窗口 X / 菜单勾选 / 程序化设置 | **扩展必须声明联动策略（close_policy）** |
| 注销 | disable/卸载 → 宿主 purge | 宿主（保险丝） |

**close_policy（注册时声明, 三选一）**:

| 策略 | 窗口 X 的语义 | 适用场景 |
|---|---|---|
| `"hide"`（默认） | 仅隐藏; 扩展继续运行（再次启用会重置可见 — 宿主保证） | 可选视图侧窗 |
| `"disable"` | **关闭 = 请求停用扩展 → Extensions 菜单勾选同步消失（闭环）** | 单主面板扩展（面板即扩展界面本体） |
| `"custom"` | 仅派发事件, 由扩展全权决策 | 复杂多窗联动 |

**on_ui_event(event, name) 事件契约**:

- `"closed"` — 用户关闭窗口（宿主在 visible True→False 时派发, 渲染线程帧内）;
  推荐在其中做**即时收尾**（例: device 示例在面板关闭时停止监视、释放端口）。
- `"disable"` 策略的执行走**挂起队列**（`ExtensionManager.request_disable` → 主线程
  pump 每帧 `consume_pending_disables`）— 生命周期方法始终在主线程, 扩展无需关心线程。

**语言层强制（三重保障之三）** — `capabilities` 含 `"ui"` 的扩展**必须**:

1. entry 类继承 `UIExtensionBase`（`Application.Core.Extension.ExtensionBase`）— 其
   `on_ui_event` 为 `abstractmethod`, **未实现则无法实例化**
   （`TypeError: Can't instantiate abstract class` → 加载失败隔离为 broken）;
2. 未继承而声明 ui → ExtensionManager 加载时拒载（capabilities↔基类一致性校验, 同为 broken）。

**静态审查（三重保障之二）**: 提交前运行
`python Utils/User/ExtensionKit/review_extension.py <扩展目录>` —
C1/C2 检查基类与实现、C3 检查 close_policy 声明（检查项全表见工具头部）。

**官方示例**: `Functions/SerialParallelDevice/extension.py`（监视面板 — 上述全部契约的活参考:
枚举/文本混合端口选择、设置持久化、快照式事件流、`ext.device.*` ops 六件套、
`close_policy="disable"` + `on_ui_event` 收尾示范）。

## 8. 节点包规范（`[M1]` 设计）

开发者只提交**声明**，ExtensionManager 翻译到引擎既有五注册点（`node_editor_protocol.md`）：

| 声明 | 落位 |
|---|---|
| 节点类型（label/引脚/props） | `Core/NodeGraph/node_types` 动态注册（type 名 `ext.<id>.<Type>`） |
| 求值器回调 | `register_evaluator`（扩展目录内的纯函数; 干跑必须确定性） |
| 卡片控件 | widgets 注册表（key 加扩展前缀） |
| 引脚可见性 | `visible_pins` 规则 |
| Add 菜单 | `MENU_SECTIONS` 新增顶级页 = 扩展 name; 页内可分组 |

红线：不得覆盖内置 type 名（除非 manifest 显式 override 且接受警告）; 未安装扩展的图加载 →
占位提示 "missing extension"（M3）。

## 9. MCP/CLI 服务规范（增量扫描生态 — 本协议的生态核心）

**目标**: 扩展可以携带自己的 op 服务; 主应用 **不重启、不重打包** 即可增量发现并提供
（引擎注册表运行期合并; agent 侧动态发现）。

### 9.1 引擎侧（已实装 M0）

```
扩展 on_load:  ctx.ops.register("open_device", fn, summary="打开设备")
             → LiveCommandServer.register_extension_ops("<id>", {"ext.<id>.open_device": fn}, ...)
约束:  op 名强制前缀 ext.<id>.（违反 → 加载期 ValueError, 扩展 broken）
隔离:  disable/unload → unregister_extension_ops(id) 全量注销
不变式: 扩展 op 不进入核心注册表（_ops）; 核心计数守卫（见 §12）不受扩展影响
```

### 9.2 agent 侧（发现与调用）

| 动作 | 通道 |
|---|---|
| 发现 | `extension.list`（==菜单列表）→ `extensions[].ops` + `extension_ops{}`（owner/summary） |
| 启停 | `extension.enable / extension.disable`（等同菜单勾选; 持久化） |
| 调用 | 任意通道直接发 `ext.<id>.<op>`: CLI `call`（ext.* 透传, 无需静态注册）/ `engine_call` / exec `engine.ok` |
| 文档 | 扩展 op 的 summary 在 `extension.list` 中; 富有文档的扩展建议带 README 路径 |

### 9.3 边界与版本

- 扩展 op 的**参数契约属于扩展自身**（核心注册表的 `Param` 元数据不覆盖 ext.* — 保持核心表纯净）。
- CLI `ops` 静态目录只列核心 op; 扩展 op 以 `extension.list` 为权威（避免静态/动态双源冲突）。
- 长任务的超时放宽: 核心 `call_timeout` 对 ext.* 默认 15s; 扩展如需长超时, 在 README 声明并在
  CLI 调用时显式 `--timeout`（未来可支持扩展在 manifest 里声明 `op_timeouts`）。
- 安全边界: ext.* op 与核心 op **同权限**（进程内执行）; 需要硬隔离的走 T2 进程扩展（设备类）。

### 9.4 迁移指引（从核心抽出）

把现有核心 op 迁移到扩展时的步骤（例: 未来的 `ext.gtec.*`）：
1. 在扩展内实现 handler（纯函数; 返回值 JSON 可序列化）;
2. `ctx.ops.register` 注册新名; 核心侧旧名保留一版转发或标记 deprecated;
3. 更新 `ui_protocol.md` §10（该表只管核心 op; 扩展 op 由 `extension.list` 呈现）;
4. 核心注册表删除旧 op → 五处同步（`editor_live_protocol.md` §6 检查单）+ 计数守卫更新。

## 10. 线程规范（现状纪律 + `[M2]` 受管模型）

- **M0 阶段**: 扩展如必须用线程, 照 `threading_protocol.md` 手工执行（ThreadRegistry 注册,
  命名 `ext:<id>:<用途>`, 心跳, 关闭清理）; 但推荐等到 M2 的 `ctx.threads` 统一代管。
- `[M2]` 目标模型: `ctx.threads.spawn(name, fn, expect_hz)`（自动注册/心跳/统一 join）;
  `ctx.jobs.submit(fn) → Future`（结果回调经主线程）; `ctx.bus.ringbuffer/queue`（唯一推荐共享媒介）。
- 永久禁止: 渲染/主线程阻塞等待; 无锁共享可变结构（引擎为 free-threaded Python, 无 GIL 保护）。

## 11. 设置与数据目录

- 可写状态一律 `ctx.data_dir`（`Application/Editor/Config/extensions_data/<id>/`, 随启用状态独立）。
- `[M1]` `ctx.settings(schema)` 落地后: schema 自动生成设置 UI + 持久化, 禁止自建配置文件到其它位置。

## 12. 测试规范（扩展必带自测）

1. 每个扩展自带 `test_<id>_extension.py`（放 `Test/Application/Extensions/` 或扩展目录的
   `tests/`—M3 定稿; 现阶段建议前者）, 遵守 `test_protocol.md` 输出契约（`RESULT: OK (n/m)`）。
2. 至少覆盖: manifest 校验 / on_load 注册的 ops 可调 / 重复 enable-disable 无残留 / 异常遏制。
3. 无头约束: 扩展入口必须 headless 可加载（顶层不得 import imgui; GUI 代码放窗口回调内）。
4. **不变式守卫**（引擎侧已有, 扩展不得破坏）:
   - `test_action_contract` 三方一致（核心 ops ↔ 文档表 ↔ 引擎注册表）— 扩展 op 在核心表外;
   - `test_editor_mcp_package` 核心计数 — 扩展不改变核心计数;
   - 扩展 op 出现/消失只影响 `extension.list`。

## 13. 实装地图（M0 → M3）

| 项 | 状态 |
|---|---|
| 发现/校验/启停/持久化/隔离 · ops 增量扫描 · Extensions 菜单 · `extension.*` ops | ✅ M0 (2026-10-11) |
| `ctx.ui.register_window` + ExtensionUI 桥 + **官方示例扩展**（device 监视面板 — 含真实串口闭环与侵入风险审查） | ✅ M1 部分 (2026-10-11) |
| **窗口生命周期完备性**（close_policy / on_ui_event / `UIExtensionBase` 语言层强制 / 挂起停用队列）+ ExtensionKit 审查器 v0 | ✅ M1 (2026-10-11) |
| UI 剩余（command/kit/post）· 节点包 · 设置 · Gtec 监视面板样例 | `[M1 待]` |
| 线程/任务/总线受管模型 · ThreadRegistry 集成 | `[M2]` |
| 外部目录安装（.mgext）· 脚手架 `ext-init` · 示例扩展 · 贡献审计 · 边界测试全套 | `[M3]` |
| 依赖拓扑 requires · 热重载（dev）· 扩展 op 超时声明 | `[M3+]` |

## 14. 提交检查单（无上下文 agent 开工前自查）

- [ ] 读了本文件 + `extension_protocol.md` §1/§3/§4 + 对应领域协议
- [ ] 目录/命名/id/ops 前缀合规; manifest 字段完整（api_version="1"）
- [ ] 入口 headless 可加载; 生命周期无残留; 未 monkey-patch 任何核心类
- [ ] （UI 扩展）继承 `UIExtensionBase` + 声明 `close_policy` + 实现 `on_ui_event` 收尾;
      `python Utils/User/ExtensionKit/review_extension.py <扩展目录>` 无 FAIL
- [ ] `extension.enable` → `extension.list` 显示 enabled + ops 齐全 → 逐 op 实调通过
- [ ] 自带测试按 `test_protocol.md` 契约全绿; 未破坏核心计数守卫
- [ ] `TODO.md` 状态更新（maturity 与清单勾选）
