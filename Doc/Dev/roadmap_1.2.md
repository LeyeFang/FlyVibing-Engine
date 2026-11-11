# 1.2 路线图 — 范围、顺序与决策（2026-11-11 立项）

> **性质**: 规划文档（`*_plan` 类，正文留在引擎仓）。
> **上游**: `node_graph_optimization_plan.md`（2026-11-10）、`scheduler_plan.md`、
> `thread_ownership_plan.md`、`export_distribution_plan.md`（已落地）、
> `crossplatform_plan.md`（2026-10-11）。
> **本文所有"实测"均来自代码核对或当日运行数据，不引用估算。**

---

## 0. 先定基线：1.2 不该是"性能版本"

| 事实 | 数字 | 来源 |
|---|---|---|
| 成品整帧 | **1.44–2.17 ms**（460–693 fps，vsync off） | 7 个 MI-SSSEP 成品实测 |
| 其中图求值 | **0.20 ms（10%）** | `perf_graph.py graph` |
| 成品 CPU | **116–134% of one core**（16 核机器） | `--stats-json` |
| 编辑器整帧（面板可见） | 28 ms（35 fps） | 实测 |
| ↳ 节点编辑器面板绘制 | **21.5 ms（77%）** | 同帧开关面板 |
| ↳ 图求值（编辑器内） | 0.20 ms | 与成品同 |

**三条结论：**

1. **成品不缺性能**。1.44–2.17 ms 对 200 Hz vsync 预算（5 ms）有一倍余量；真正稀缺的是
   "留给采集/推理/sidecar 的空闲核"。
2. **编辑器的问题是面板绘制**（21.5 ms），不是图求值（0.2 ms）。这两件事长期被混在
   同一个话题里。
3. 因此 1.2 的定位是 **契约 + 能力版本**，性能只做"归因、门槛、去浪费"，
   **不追 fps 指标**。

---

## 0. 第 0 步（先做，独立可交付）— 踢出 ZenGL

### 0.1 为什么先做这一步

| 理由 | 说明 |
|---|---|
| 它是**维护负债** | `RendererType.ZenGL` 是个没有归属的第二后端；`EditorHost.init()` 的默认值写的是 `'ZenGL'`，实际走 OpenGL —— 接手者第一眼就会被误导 |
| 它**污染公共层** | `VertexLayout.to_zengl_format()/to_zengl_locations()` 被 `to_gl_attribs()` 和 `get_active_locations()` 调用（`VertexLayout.py:117,132`）—— 想删 ZenGL 必须先拆这层耦合 |
| 它**没有回归覆盖** | `Doc/Dev/test_nodes` 的相关条目已不存在；`test_map_todo.md` 明确写"Vulkan/ZenGL 为 WIP，不承诺覆盖" |
| 它**挡 1.2 的多线程** | 每个后端各一套资源管理器 + MRO 拼装，任何"命令队列/并行提交"改动都要维护两份 |
| 它**挡 mac 适配** | `zengl` 50 KB 原生扩展；mac 基线已决定走 GIL 版，多一个原生依赖多一份风险 |

### 0.2 删除清单（逐项可勾）

**代码**

| # | 位置 | 动作 |
|---|---|---|
| 1 | `Application/Core/Renderer/ZenGL/`（7 文件 ~65 KB） | **整目录删除** |
| 2 | `Application/Core/Engine.py:53` `RendererType.ZenGL` | 删枚举成员 |
| 3 | `Application/Core/Engine.py:216-218` `_get_renderer_class` 的 ZenGL 分支 | 删 |
| 4 | `Application/Core/Engine.py` `_render_one_frame` 的 `in (OpenGL, ZenGL)` 判定 | 收敛为 OpenGL |
| 5 | `Application/Editor/EditorHost.py:306` `renderer_type='ZenGL'` 默认值 | 改 `'OpenGL'` |
| 6 | `Application/Core/Renderer/VertexLayout.py:61-76` `to_zengl_format()` / `to_zengl_locations()` | 删；**先把 `to_gl_attribs()` / `get_active_locations()` 改为自持 locations** |
| 7 | `Application/Core/Renderer/PostProcess.py` / `Renderer.py` 注释里的 ZenGL 提及 | 改注释 |
| 8 | `Application/Editor/Gizmos/{Grid,OutlinerID}.py` 注释 | 改注释（无代码依赖） |

**依赖 / 产物**

| # | 位置 | 动作 |
|---|---|---|
| 9 | `pyproject.toml:21` `zengl>=2.7.0` | 删 |
| 10 | `Utils/Dev/uv-py314t.lock` | 重新生成（`uv lock`） |
| 11 | `Resource/wheels/zengl-2.7.2-cp314-cp314t-win_amd64.whl` | 删 |
| 12 | `Resource/runtime/Lib/site-packages/{zengl*,zengl-stubs/}` | 重跑 `Utils/Dev/prepare_runtime.py` |

**测试 / 文档**

| # | 位置 | 动作 |
|---|---|---|
| 13 | `Test/Application/Renderer/test_vertex_layout.py:7,90,91` | 删 zengl 断言（保留 `to_gl_attribs`） |
| 14 | `Test/Application/Editor/测试需知.md:29` | 历史记录，保留（标注"已于 1.2 完成"） |
| 15 | `Doc/Dev/print_inventory.md` | 重跑 `Utils/Dev/print_audit.py` |
| 16 | 工具仓 `docs_content/dev/rendering_protocol.md:14,104` | **另开 PR**（引擎仓改不到） |
| 17 | `Doc/Dev/crossplatform_plan.md:15` | 删 `zengl` 行 |

### 0.3 验收

| 项 | 门槛 |
|---|---|
| 无残留 | `grep -ri zengl` 在 `Application/`、`Test/`、`pyproject.toml` 零命中（注释里的历史条目除外，需显式标注） |
| 启动 | 编辑器 + PIE + 成品三种形态正常启动、渲染、截图 |
| 回归 | `--tier core` 保持绿；`test_gl_lighting` / `test_gl_pixels` / `test_gl_render_targets` 全绿 |
| 安装包 | `dist` 体积应减少 ~50 KB（wheel）+ 运行时镜像减少 ~1 MB |
| 无新警告 | 启动日志不出现 `ZenGL` / `zengl` |

> **注意**: 第 6 项是唯一的真实风险点 —— `to_gl_attribs()` 目前复用
> `to_zengl_locations()`。删之前必须把 locations 计算抽成本类自带的能力，
> 否则 GL 顶点属性绑定会静默失效（画面可能只是"看起来不对"）。

---

## 1. 节点图性能 — 重新总结

### 1.1 已经做掉的（1.1.0）

`NodeCanvas._ensure_index()`：`pin→node` / `pin→meta` / 出向邻接 / 入向源 pin /
事件类型→节点 全部缓存，按 `(revision, len(nodes), len(links), len(_TYPES))` 失效。
**3.404 → 0.171 ms/帧（×20）**，事件序列逐条一致。守卫
`test_canvas_pin_index.py`（索引 vs 暴力扫描对拍）。

**这是唯一"值得做且已做完"的那一刀。**

### 1.2 剩余四项的重排（含对上游文档的修正）

| 项 | 图求值内收益 | **换算整帧** | 风险 | 1.2 结论 |
|---|---|---|---|---|
| 常量折叠 | 调用数 −17% | **−0.02 ms（−1%）** | 中（须 pin→props 映射） | ⏸ **不做** |
| 死链裁剪 | 当前 **0%** | 0 | 低 | 改做**编辑器提示** |
| 纯节点记忆化 | −70~85% | −0.14 ms（−7%） | 中高（假 pure → 静默错值） | ⏸ 等触发条件 |
| 运行时融合 / 闭包链 | 天花板 7–12% | −0.05 ms（−2.4%） | 高（图编译器+双校验器） | ❌ 不做 |

**修正上游文档的一处排序**: `node_graph_optimization_plan.md §4.1` 把常量折叠列为
"最稳、先做这个"。换算到整帧后它只值 −1%，而它需要引入的 `pin→props` 声明是四项里
**唯一会改变语义正确性**的开关 —— `ScalarMath` 同时有 `In_0..7` 引脚与 `a/b` props，
`Compare` 同时有 `A/B/C` 引脚与 `operation` prop。**用 1% 帧换一个静默改语义的风险，不划算。**

### 1.3 1.2 在这条线上只做三件事

| 优先 | 内容 | 工作量 |
|---|---|---|
| **P0** | **性能分相归因** —— `FrameProfiler` 目前只有 fps/p50/p99，**没有分相**。1.96 ms 里只有 0.2 ms 是图求值，剩下 1.76 ms 去哪了没人知道 | 1–2 天 |
| **P0** | **大规模图拐点测量** —— 200/500/1000/2000 节点合成图，把曲线画出来。现在只有一个 160 节点的点，"要不要闭包链"**无法回答** | 半天 |
| **P0** | **基线回归门** —— `perf_graph --baseline` 已支持，接进 CI | 半天 |

### 1.4 触发条件（写死，避免反复讨论）

记忆化 / 闭包链 **同时满足**以下两条才重开：
- 出现 **≥1000 节点**的真实图，**且**
- 图求值占整帧 **>40%**

届时顺序是 **先折叠再编译**（代码更短），不是反过来。

---

## 2. 扩展线程 + 引擎瘦身

### 2.1 现状（代码核对）

| 件 | 状态 |
|---|---|
| `Application/Core/ThreadRegistry.py` | ✅ 已有 `register/heartbeat/unregister/snapshot`，Core 层、GUI 无关 |
| `ctx.threads` | ❌ `Core/Extension/ExtensionContext.py:41` 仍是 `self.threads = None`（标 M2） |
| `ctx.jobs` | ❌ 同上 `None` |
| 进程内扩展线程 | 4 处：SPD `spd-io`、VirtualDevice `eeg-*-service`、BCI `bci-*`、本地夹具 `acq-imp-*` |
| 进程外 | 夹具后端已在 sidecar（`Popen` 管理）→ **不动** |
| 引擎侧缺陷 | `spd-io` 在零设备节点的图上照样启动（P0-F，见 `product_todo §11.7`） |

### 2.2 新发现：成品加载节点，但不加载扩展对象

做导出修复时确认：

```
成品:  extension.json → nodes{module,factory} → 注册节点类型    ✅（1.1.1 已做）
       扩展对象 / on_load / on_engine_start/stop              ❌ 根本没有
```

后果：SPD 在 v0.6.0 加的 `on_engine_start/on_engine_stop` **在成品里永不触发**。
成品现在能采集，是因为设备会话由**节点求值器自己建**，不是扩展生命周期建的。

这不是 bug，是一个**还没写下来的契约**，而它直接决定 `ctx.threads` 的适用域：

| 选项 | 内容 | 代价 | 评价 |
|---|---|---|---|
| **A** 成品加载扩展对象 | 与 PIE 完全对齐 | 第三方任意 `on_load` 代码在成品里跑；须禁用 UI/ops 注入 | 风险最高 |
| **B** 清单声明 `runtime` 入口 | `"runtime": {"module": "x", "factory": "on_engine_start"}`，成品只调这一个钩子 | 多一个清单字段；扩展要拆"编辑期/运行期" | ✅ **推荐** |
| **C** 只认节点 | 写进契约：引擎级生命周期必须表达为节点 | 每扩展要造"启动节点" | 与 B 并存为默认 |

**建议 B + C 并存**：默认 C（节点是运行时唯一入口），需要进程级资源的扩展用 B 显式声明。
这样 `ctx.threads` 在成品里的适用域就清楚了 —— **只有 B 声明的扩展能拿到**。

### 2.3 责任边界（已定稿，不重谈）

- **A 功能正确性 / B 性能质量** → 收缩，第三方只告警
- **C1 可退出 / C2 故障隔离 / C3 可归因** → **不收缩**（宿主不变量）

> 契约一句话：**扩展可以不好用，但不能让宿主编不了整体退出。**

### 2.4 落地顺序

```
① P0-F  spd-io 改条件启动（needs_device_io / 场景设备类型判定）
② P0    成品 runtime 契约定稿（A/B/C）—— ③ 的范围取决于它
③ P0    ctx.threads 托管层：spawn_io / submit / stop_all + 强制 "{ext}:{name}"
④ P1    迁移 一次性任务 → 薄桥 → SPD（最重）
⑤ P1    AST 守卫：Application/Functions/** 不得出现裸 threading.Thread(
```

### 2.5 「清理引擎」的具体清单（已扫过，不是泛泛而谈）

| 项 | 现状 | 动作 |
|---|---|---|
| `Core → Functions` 反向依赖 | **0 处** ✅ | 保持，加守卫钉住 |
| `Editor → Functions` 反向依赖 | **1 处**：`LiveCommandServer.py:400` → `VirtualDevice.save_record` | 改走扩展 op |
| `Core/DeviceRegistry.py` | SPD 已自持台账、过渡期整体委托 core | **删 core 份**（SPD 自动接管）—— 瘦身最大一块 |
| `Core/NodeGraph/graph_rules.py` | **33 KB**，含设备族 IO 规则表，11-09 又为 prefix/suffix 扩了一次 | 设备族规则抽到扩展侧（通用 `pin_visibility` 机制），core 只留**协议** |
| `Core/NodeGraph/graph_constraints.py` | 23 KB | 同上一起看 |

> `graph_rules` + `graph_constraints` 合计 **57 KB**，占 `NodeGraph` 目录约 1/3，
> 是"设备语义泄漏进 core"的着陆点。**最值得动，也最容易动出回归** ——
> 必须先有契约守卫再动。

---

## 3. 官方 SignalProcess + 经典 BCI（SSVEP / MI）

### 3.1 现状（不是从零开始）

| 扩展 | 状态 | 已有什么 |
|---|---|---|
| `sigproc` | **skeleton**（只有 `ext.sigproc.info`） | 无节点；TODO 列了 Init/滤波/参考/变换/坏道/ICA |
| `bci` | **partial** | `FBCSP.py`（CSP+LDA/scipy-SVM）、`CCA.py`（SSVEP，无训练，12 Hz ρ=0.96 已验证）、`EpochDataset.py`（epochs×channels×samples + 标签 + npz）、`ModelRegistry.py`；9 个节点 |

### 3.2 真正的瓶颈不是算法，是**输入契约**

| | SSVEP | MI |
|---|---|---|
| 输入形态 | 连续流 + **相位精度** | 分段 epoch + 标签 + 折数 |
| 已有支撑 | CCA 只需 sin/cos 参考，无需训练 ✅ | FBCSP 三节点链 ✅ |
| 真正缺口 | **刺激相位锁定**（现 40 Hz 抖动 ±5–6 ms） | **trial 切分/剔除/交叉验证**归谁管 |

**关键**：SSVEP 的精度上限由线程/调度决定，不由算法决定。40 Hz 现在均值正确
（24.97 ms）但抖动 ±5–6 ms，因为脉冲落在图 tick 边界（≈8.3 ms）。

> **顺序硬约束：§2 的 deadline 调度必须先于 §3 的 SSVEP 精度验收。**
> 否则会做出一个算法很好、刺激不准的扩展，然后反复怀疑算法。

### 3.3 分层

```
SignalProcess  = DSP 基座（无状态 in→out + 有状态流式）
                 滤波 / 参考 / 变换（含流式 SDFT）/ 坏道
                 ↑ 不认 trial、不认标签
BCIAlgorithm   = 解码器（认 trial 语义）
                 Epoch 切分 → 特征（CSP/CCA/协方差）→ 分类（LDA/Riemann）→ 决策
```

**必须先解决的一条硬约束**：流式节点（SDFT、滤波状态）**必须跨帧保持状态**，
而 `_ensure_pin_evaluated` 的去重是**帧内**的（`ctx._pin_values` 每帧清空）。
跨帧状态必须显式挂在一个 `ProcessorState` 上，按 `device_name`/`processor_name`
绑定（与设备会话同一命名空间）。**这一条不设计好，SDFT 会写成"每帧重启滤波器"，
看起来能用、实际全错。**

### 3.4 路线（按 ROI）

**SSVEP**

| 步 | 内容 | 状态 |
|---|---|---|
| 1 | CCA（正弦参考，无训练） | ✅ 已有 |
| 2 | **FBCCA**（滤波器组 + 谐波加权），通常 +10~20% 准确率 | 必做 |
| 3 | **TRCA**（任务相关成分分析，集成校准 trial），小样本最优 | 必做（主力） |
| 4 | 决策窗扫描 + 谐波/子带数做成 props（可被实验扫描） | 必做 |
| 5 | PSDA / eCCA（相位约束） | 可选 |

**MI**

| 步 | 内容 | 状态 |
|---|---|---|
| 1 | CSP / FBCSP + LDA | ✅ 已有 |
| 2 | **收缩 LDA（shrinkage）+ 正则化**，小样本比换模型更有效 | 必做（便宜） |
| 3 | **Riemannian**（协方差 + 切空间 + MDM）/ 或 TS+LR | 必做（现代经典方法的事实标准） |
| 4 | Artifact rejection（幅度/方差/漂移）+ 试次剔除 | 必做（否则 acc 不可信） |
| 5 | **交叉验证**（within-session k-fold）作为节点/op | 必做（现无 CV = 无法报告泛化） |
| 6 | 在线自适应（增量更新协方差均值） | 可选 |

### 3.5 1.2 范围（刻意收窄）

> 目标是"能跑通一个 SSVEP 实验 + 一个 MI 实验，**并且能报告数字**"，不是铺满 TODO。

- **必须**：`SignalProcessorInit` + `BandpassFilter`（SOS，流式/离线双语义）+ `Reference`
  （CAR/Laplacian）+ `SDFT` + **`ProcessorState` 状态容器**
- **必须**：FBCCA + TRCA；shrinkage-LDA + Riemannian + artifact rejection + CV
- **不做**：ICA（要 sklearn，不引依赖）、CWT、完整坏道插值
- **每节点门槛**：① 合成信号数值钉死 ② 与 scipy 对拍 <1e-6 ③ 图校验零 error
  ④ dry-run 确定性（无设备/文件 IO）

---

## 4. 多线程性能优化（1.2 主攻方向）

> 本节回答："优先瞄准编辑器与 PIE 的性能，尽可能利用用户 CPU 核数"。
> 详细分析见 §4.1–§4.7；此处给结论与顺序。

### 4.1 先纠正一个前提：架构**已经**是多线程的

| 机制 | 状态 |
|---|---|
| `CommandQueue`（SPSC，主线程 enqueue / 渲染线程 drain） | ✅ |
| **原子批** `begin_batch/end_batch`（逻辑 tick 内命令要么整批可见要么不可见） | ✅（曾修过真实帧边界竞态） |
| `FrameSync`（PIE slave 等 Editor master） | ✅ 但见 §4.4 |
| 每 Engine 独立 `_state()`（`logic:GameRuntime` / `render:EditorHost` 隔离） | ✅ |
| `ThreadRegistry` 归因 | ✅ |
| 渲染线程 | ✅ 三种形态都有 |
| 导出成品的逻辑仍在主线程 | ⚠️ 唯一缺口 |
| **free-threading** | ✅ 3.14.6t，`_is_gil_enabled() == False`，16 核 |

**"适不适合多线程"这个问题已经答了 —— 适合，而且是照着做的。缺的不是架构。**

### 4.2 但"多核"不是目标，先把目标说准

| 形态 | 现状 | 正确目标 |
|---|---|---|
| **成品** | 116–134% of one core | **不是"用更多核"，是"用更少核 + 更稳的延迟"** —— 空出来的核要给采集/推理/sidecar |
| **PIE** | 被 FrameSync 锁到编辑器帧率 | **解耦**，让实验逻辑不受 UI 影响 |
| **编辑器** | 28 ms/帧（面板 21.5 ms） | 降到 8 ms 以内（120 fps），且**不要靠堆线程** |

> 一句话：**成品的正确方向是省核，编辑器的正确方向是少做无用功，PIE 的方向是解耦。**

### 4.3 顺序：并行是最后一步，不是第一步

绝大多数"用满多核"的尝试失败在顺序上。正确顺序：

```
① 消除浪费      不该做的工作（缓存失效、视口裁剪、每帧 deepcopy）
② 归因          分相计时：剩下的究竟是 ImGui C++ 调用还是 Python 数据准备
③ 拆分离        把 CPU 工作从"必须串行的 ImGui 段"里搬出去
④ 并行          对剩下的纯计算分段并行
⑤ 跨帧流水线    用上一帧的结果（真正的"延迟隐藏"）
```

**为什么必须先 ①②**：把 21.5 ms 的循环并行到 4 线程，最乐观是 ÷4；
而"只画可见节点 + 缓存失效"通常是 ×8–×20，且不引入任何同步开销和不确定性。
**先并行等于把优化天花板锁死在 4 倍。**

### 4.4 三个已确认的具体浪费（代码核对，非推测）

| # | 位置 | 现象 | 建议 |
|---|---|---|---|
| 1 | `node_editor/panel.py:386` `self._ensure_default_scene()` | **每帧**调用，内部 `entities.clear()` + 逐实体 `copy.deepcopy`（`panel.py:664-676`）。实测 2 实体 0.044 ms → 16 实体 0.5–0.7 ms；同时也是历史竞态源 | 改为**事件驱动**（场景变更 / revision 变化时才算），并可下沉到 worker |
| 2 | 节点画布绘制 | 160 个节点全部构建 ImGui 卡片，**无视口裁剪** | 引入 ImGui clipper（只画可见卡片）；预期 21.5 ms → 数 ms |
| 3 | `FrameSync` 默认 `enabled=True` | PIE 渲染线程帧首等编辑器 master tick → **PIE fps 被编辑器 fps 直接乘上**。面板可见 35 fps 时 PIE 也只有 35 fps | 见 §4.5 |

### 4.5 FrameSync 的取舍（这是 PIE 性能的根，不是线程数）

现状语义：`slave_wait()` 每帧阻塞，**强 lockstep**。好处是确定性；代价是性能耦合。

三个选项：

| 选项 | 语义 | 适合 |
|---|---|---|
| **A** 保持 lockstep | 完全确定 | 需要逐帧对齐的视觉实验 |
| **B** `enabled=False` 自由竞速 | 最大吞吐 | 采集/算法验证 —— **但它已经存在，只是没人开** |
| **C** **逻辑锁步、渲染解耦** | 逻辑帧由 master 的"逻辑节拍"驱动，渲染各自跑 | ✅ **推荐** |

C 的含义：把"每帧对齐"下沉成"**每逻辑 tick 对齐**"。PIE 渲染线程不再等编辑器
渲染完，而是等编辑器的**逻辑边界**（或直接用自己的 tick）。这样编辑器 UI 卡顿
不会传导到 PIE 的刺激时序。

> 注意与 §2/§3 的关系：**刺激时序本来就不该由图 tick 或帧率决定** —— 最终形态是
> `spd-io` 线程里的 deadline 调度。FrameSync 的 C 选项是过渡，不是终点。

### 4.6 free-threading 下"能不能真并行"的冷判断

| 场景 | 真并行？ | 原因 |
|---|---|---|
| 两个线程改**同一个 dict/list** | ❌ 串行 | 3.14t 是**每对象锁**，争用即串行 |
| 两个线程读共享 + 写**各自私有缓冲** | ✅ | 无争用 |
| ImGui 任意调用 | ❌ 必须串行 | 全局上下文 + 单一 draw-data |
| GL 调用 | ❌ 必须同一上下文线程 | 除非多上下文/共享上下文（复杂度极高） |
| numpy/scipy 大数组运算 | ✅（且多数已释放 GIL） | 天然 |

**推论**：可并行的必须满足"**数据不相交 + 结果后合并**"。这正好是我们已有的
`CommandQueue` 模式 —— 逻辑线程写命令、渲染线程执行。**扩展这个模式，而不是另造一套。**

另一条 3.14t 的现实：**单线程代码在 free-threading 构建上通常慢 10–20%**（每对象锁）。
所以"加线程"只有在真拿到并行收益时才划算；为 0.2 ms 的图求值开线程池是净亏。

### 4.7 我建议的 1.2 多线程落地（按 ROI）

| 优先 | 项 | 预期 | 是否并行 |
|---|---|---|---|
| **P0** | **分相计时**（§1.3）+ 每相 P50/P99 | 让后面所有决策有据 | 否 |
| **P0** | 面板 `_ensure_default_scene` 事件驱动；ImGui clipper | 21.5 ms → **数 ms**（编辑器和 PIE 同时受益） | 否 |
| **P0** | **FrameSync 选项 C**（逻辑锁步、渲染解耦） | PIE 不再被编辑器帧率绑架 | 否 |
| **P1** | 成品逻辑线程定速方案（现在内联，因为 `logic_target_fps=0` 会 busy-spin） | 行为一致 + 不烧核 | 否 |
| **P1** | **帧快照流水线**：worker 池算"下一帧输入"（矩阵/可见性/文本排版/节点卡片布局），渲染线程**永不阻塞**，取最近完成快照 | 真正的延迟隐藏；慢 worker 只掉一帧，不拖帧率 | ✅ |
| **P2** | 场景遍历 / 剔除 / 拾取并行化 | 仅当实体数上百才划算（现 13 实体，收益≈0） | ✅ |
| **不做** | 并行图求值 | 0.2 ms，线程调度开销同级 | — |
| **不做** | 多 GL 上下文 / 并行命令提交 | 复杂度极高，收益要 1000+ draw call 才显现 | — |

**P1 的"帧快照流水线"是本节唯一真正的架构增量**，形态：

```
Frame N-1 完成 → 发布 snapshot(epoch=N-1)  ← 原子替换引用
Frame N 渲染：
    render thread 取 snapshot(最新完整 epoch)   ← 永不阻塞
    worker 池同时算 epoch=N（私有缓冲）
    若 worker 未完成 → 本帧重复用 N-1（降级但不断帧）
```

这与 `Scene.entities_snapshot()` / `replace_entities()` 的既有做法同构 —— **不是新发明，
是把已验证的模式推广到渲染输入**。

### 4.8 与 mac 的关系（这条会影响线程模型，必须现在知道）

`crossplatform_plan.md` 已把这条列为**最高优先级风险**：

> macOS Cocoa 要求**窗口与事件在进程主线程**；现架构是**渲染线程持窗**（`_render_loop`
> 里 `MakeContextCurrent` + 渲染）。若属实，mac 适配会迫使线程模型加平台适配层。

**含义**：§4.7 的 P1（帧快照流水线）设计时**不要**假设"渲染线程就是持窗线程"。
把"窗口/事件线程"与"GPU 提交线程"在概念上分开（哪怕在 Windows 上仍是同一个线程），
否则 mac 上要重写一遍。

---

## 5. 渲染后端与 Vulkan（结论：不做，理由不是性能）

### 5.1 ImGui 在 Python 绑定里**没有** Vulkan 渲染后端

```
imgui_bundle 1.92.5  →  imgui.backends 只有：
    opengl2_* / opengl3_*（init / new_frame / render_draw_data / shutdown）
    glfw_init_for_vulkan        ← 平台侧回调，不是渲染后端
hasattr(imgui.backends, "vulkan")  →  False
```

**结论：现在"ImGui + Vulkan"在 Python 绑定层做不了。** 不是适配不好，是没有这个后端。

### 5.2 我们自己的 Vulkan 后端状态

| 项 | 状态 |
|---|---|
| `VulkanCore.py` 46 KB / `VulkanResourceManager.py` 24 KB | 有体量 |
| 测试 | **无**（只剩 `.pyc`，源文件已不在） |
| 选择入口 | 无（`EditorHost` / `GameRuntime` 默认全 OpenGL） |
| 架构契合 | 全 `@classmethod` 单例 + MRO 拼装，双后端维护成本高 |

### 5.3 重开条件（写死）

**同时满足**：
1. `imgui_bundle` 上游提供 Vulkan 渲染后端，**且**
2. 我们真需要 GL 4.2+ 特性（compute / indirect / 多线程命令缓冲）

现在两条都不成立。

### 5.4 macOS：障碍不是"没有 OpenGL"，是线程模型

| 检查项 | 结果 |
|---|---|
| 窗口请求的 GL 版本 | **4.4 core**（`EditorWindow.py:82-84`、`RuntimeWindow.py:94-96`） |
| macOS 上限 | **4.1 core** |
| shader | 6 个文件全部 `#version 440 core` |
| **代码里的 4.2+ 特性** | **0 个**（无 DSA / SSBO / compute / `layout(binding)` / instancing） |
| 实际能力需求 | 等价 GL 3.3 级别 |

**所以 mac 路径是 GL 4.4 → 4.1 化，不是上 Vulkan**：
shader 版本号（半天）→ 全 GL 回归（1 天）→ mac 上补 GLFW cocoa 窗口 + 无框全屏
（真工作量）→ 打包/签名/公证（独立大话题）。
**真正的风险是 §4.8 的主线程约束，不是图形 API。**

---

## 6. 三档范围

| 档 | 内容 |
|---|---|
| **Must** | ⓿ ZenGL 全删（§0）· ① 分相计时 + 回归门 ② 面板去浪费（事件驱动 + clipper） ③ FrameSync 选项 C ④ `ctx.threads` 托管层 + P0-F ⑤ 成品 runtime 契约定稿（A/B/C） ⑥ DeviceRegistry 收尾 + `Editor→Functions` 那 1 处 |
| **Should** | ⑦ 帧快照流水线（P1） ⑧ SignalProcess 基座（Init/滤波/参考/SDFT + `ProcessorState`） ⑨ FBCCA + TRCA ⑩ shrinkage-LDA + Riemannian + CV |
| **Could** | ⑪ 大规模图拐点测量 → 决定闭包链 ⑫ PerfHUD ⑬ GL 4.1 化实验分支 ⑭ 死链检测做成编辑器提示 |
| **Won't** | Vulkan · 运行时融合 · 并行图求值 · 常量折叠 · ICA（要 sklearn） · 多 GL 上下文 |

---

## 7. 决策表（待拍板）

| # | 问题 | 影响 | 建议 |
|---|---|---|---|
| D1 | 有没有 ≥1000 节点的真实图？ | §1 是"只做归因"还是重开记忆化/编译 | 若有 → 提前 |
| D2 | 成品要不要加载扩展对象？ | `ctx.threads` 适用域 | **B + C 并存** |
| D3 | 1.2 的 SSVEP 是否要求"报告准确率"？ | 决定 deadline 调度是否必须先做 | 是 → 先做 §2 |
| D4 | Mac 是 1.2 交付目标还是"架构不挡路"？ | 是否要真机/打包 | 建议只做"不挡路" |
| D5 | FrameSync 走 C 还是先开 `enabled=False` 顶一阵？ | PIE 性能 | 先 B 顶、同版本做 C |
| D6 | 成品逻辑线程定速方案 | 行为一致性 | 用事件等待而非 sleep 轮询 |

---

## 8. 复现命令

```powershell
# 当前基线（发版前必跑）
.venv-py314t\Scripts\python.exe Utils\Dev\test_runner.py --tier core

# 图求值 / 大规模图
.venv-py314t\Scripts\python.exe Utils\Dev\perf_graph.py graph --dir Application\Functions\missssep\Examples --frames 600
.venv-py314t\Scripts\python.exe Utils\Dev\perf_graph.py graph --synthetic 1000 --frames 300

# 成品性能 + 线程清单
<product>\runtime\python3.14t.exe -Xgil=0 Application\PlayerEntry.py game.json --seconds 8 --stats-json out.json

# 线程表
.venv-py314t\Scripts\python.exe Utils\Dev\thread_probe.py

# ZenGL 残留检查（第 0 步验收）
Select-String -Path Application\**\*.py,Test\**\*.py,pyproject.toml -Pattern "zengl|ZenGL" -SimpleMatch
```
