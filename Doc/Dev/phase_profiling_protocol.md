# 协议 — 分相性能分析（PhaseProfiler）

> **性质**: 工具/协议文档。实现在 `Application/Core/Stats/PhaseProfiler.py`，
> 由 `FrameProfiler.phases` 持有（每 Engine 一个）。
> **本文所有数字均为 2026-11-11 实机实测**（vsync on, 1920x1080@200Hz, 16 核）。

---

## 0. 为什么需要它

`FrameProfiler` 只回答"整帧多久"（mean/p50/p99 + 卡顿桶）。这不足以做优化决策：

| 已有的数字 | 它回答不了的 |
|---|---|
| 成品 1.44–2.17 ms | **这 2 ms 花在哪？** |
| 编辑器 28–33 ms | 面板 / GPU / 命令构建 / poll，各占多少？ |
| p99 / max | 哪一相在制造长尾？ |

2026-11-10 曾把 `p1_low`（最差 1% 帧时间）误读成吞吐，得出"长会话退化到 14 fps"
的结论 —— 而真实平均是 95 fps。**没有分相，整帧数字很容易被误读。**

---

## 1. 用法

### 1.1 代码侧

```python
ph = Engine._get_profiler().phases      # 或 EditorHost / GameRuntime 同名
with ph.phase("frame.layers"):            # 可嵌套；父相自动扣除子相
    for layer in stack:
        with ph.phase(f"layer.{layer.__name__}"):
            layer.OnRender()
ph.counter("draw_calls", n)               # 每帧累加，落一个样本
```

帧边界：**渲染线程**每帧调 `end_frame(frame_ms)`（由 `FrameProfiler.tick()` 自动完成）。
其它线程调 `end_frame(None)` —— 只冲刷样本，**不参与帧内占比**（逻辑帧与渲染帧不同源，
硬凑会得到错误占比）。

### 1.2 实时通道（编辑器）

```powershell
engine-editor-cli call perf.profile on=true reset=true target=editor|pie|all
engine-editor-cli call perf.phases  target=all text=true       # text=true = 人读表格
```

> ★ `on=true` 在**已开启时不会清样本**（避免误丢数据）。做对照实验必须带
> `reset=true`，否则两段不同状态的样本会混在一起 —— 实测曾因此得到
> "相均值 23.8 ms > 帧均值 10.9 ms" 这种自相矛盾的报表。

> 注意：`perf.*` 目前只能在**引擎侧**命令总线使用。CLI/MCP 有本地 op 白名单
> （工具仓 `ops.py` 的 `op_registry`），需要同步登记后才能在 CLI/MCP 直接调用；
> 未登记时可走 `engine_editor_mcp.client.send_raw()`。

### 1.3 成品

```powershell
<product>\runtime\python3.14t.exe -Xgil=0 Application\PlayerEntry.py game.json `
    --seconds 6 --stats-json out.json
```

`--stats-json` 会**自动打开分相**（用户既然要统计，就是要诊断），摘要 JSON
多一个 `phases` 键。也可以用环境变量 `MGE_PROFILE=1` 全局打开。

### 1.4 输出结构

```jsonc
{
  "phases": {
    "threads": {
      "render:GameRuntime": {
        "frame":        {"n","mean","p50","p95","p99","max"},
        "unattributed": {"n","mean",...},        // 帧时长 - 顶层相之和
        "unattributed_share": 0.021,
        "phases": {
          "gl.pick": {"excl": {...}, "incl": {...}, "share": 0.315}
        },
        "counters":  {"ne.nodes": {"last","mean","max"}},
        "worst_frames": [{"frame_ms": 68.6, "phases": {...}}]   // 默认最慢 8 帧
      }
    }
  }
}
```

**`excl`（排他）是看优化对象的主指标**；`incl` 是子树总成本。
`unattributed` 是"插桩之外的时间"—— 它应当很小（实测 0.5–2%），
一旦变大就说明有未被插桩的大块工作。

---

## 2. 相清单（当前插桩点）

| 相 | 位置 | 含义 |
|---|---|---|
| `frame.sync_wait` | `Engine._render_one_frame` | PIE 等编辑器（FrameSync）—— **纯阻塞** |
| `frame.sync_notify` | 同上 | master 唤醒 slave |
| `frame.click_through` | 同上 | overlay 模式点击穿透判定 |
| `renderer.start` | 同上 | 命令队列消费 + 渲染管线 |
| ↳ `gl.clear` / `gl.pick` / `gl.pre_overlay` / `gl.entities` / `gl.post` / `gl.overlays` / `gl.runtime_ui` | `OpenGLRenderer._do_start_frame` | 管线分段 |
| `frame.layers` | `Engine._render_one_frame` | 层渲染总耗时 |
| ↳ `layer.<Name>` | 同上 | 单个层的 `OnRender` |
| `renderer.end` / `frame.capture` / `frame.swap` | 同上 | 收尾 / 帧抓取 / 交换（含 vsync 等待） |
| `imgui.settings` / `imgui.new_frame` / `imgui.hotkeys` / `imgui.panels` / `imgui.submit` | `EditorImguiLayer.OnRender` | **Python 构建 draw list vs C++ 提交** |
| ↳ `panel.<Name>` | `UIManager.draw_all` | 单个面板成本（含 `panel.__filedialog` / `panel.__statusbar`） |
| ↳ `ne.scene_sync` | `NodeEditorPanel.draw` | 默认场景同步（每帧 deepcopy） |
| `logic.tick` / `logic.window_poll` / `logic.layers` / `logic.sleep` | `Engine.run` / `Engine._logic_loop` | 逻辑侧（成品内联 / PIE 独立线程） |
| ↳ `logic.layer.<Name>` | 同上 | 单层 `OnUpdate`（图求值在 `RuntimeNodeLayer`） |

计数器：`ne.nodes` / `ne.links`（节点编辑器规模）。

---

## 3. 实测基线（2026-11-11）

### 3.1 成品（MI-SSSEP-NoFeedback-20Hz-Block，vsync on）

| 相 | 排他均值 | 占帧 | 说明 |
|---|---:|---:|---|
| `frame.swap` | **2.60 ms** | 51.8% | **vsync 等待，不是 CPU** |
| `gl.pick` | **1.58 ms** | 31.5% | 鼠标拾取 pass —— **成品里没有任何消费者** |
| `gl.entities` | 0.44 ms | 8.7% | 真正的渲染 |
| 其余合计 | ≈ 0.28 ms | 5.6% | |
| **帧** | **5.01 ms** | | 199.7 fps（显示器 200 Hz） |

逻辑侧（MainThread，内联）：`logic.layer.RuntimeNodeLayer` = **0.097 ms**，
整条逻辑 ≈ 0.16 ms。

> **结论**: 真正做事的 CPU 约 2.4 ms，其中 **1.58 ms（66%）是拾取**。
> 分相对象里 `frame.swap` 应扣掉，因为它量的是"等 vsync"，不是"花掉的时间"。

### 3.2 编辑器（MISSSEP-AllConditions，217 节点 / 247 连线）

| 相 | Node Editor 隐藏 | Node Editor 可见 |
|---|---:|---:|
| **帧** | **6.06 ms**（165 fps） | **32.77 ms**（30 fps） |
| `panel.Node Editor` | —— | **22.83 ms（69.7%）** |
| `gl.pick` | 1.91 ms（31.5%） | 4.98 ms（15.2%） |
| `gl.overlays` | 1.63 ms（26.9%） | 1.64 ms（5.0%） |
| `gl.post` | 0.57 ms | 0.57 ms |
| `panel.Scene` | 0.53 ms | —— |
| `gl.entities` | 0.38 ms | 0.43 ms |
| `imgui` 合计 | 0.42 ms | 1.32 ms（submit 0.09→0.84）|
| `ne.scene_sync` | —— | **0.41 ms（1.3%）** |

**两个重要修正：**

1. **`_ensure_default_scene` 每帧 deepcopy 不是原因** —— 它只占 **0.41 ms（1.3%）**。
   上一轮"面板 21.5 ms 主要来自场景同步"的推断被实测**证伪**；真正的成本在
   **绘制 217 张节点卡片**本身（22.8 ms，且分布集中：p50 32.4 / p95 37.2，不是尖峰）。
2. `imgui.submit` 从 0.09 → 0.84 ms 说明**卡片的 draw 命令数量**也同步暴涨，
   但 C++ 侧只占 2.6% —— 成本在 Python 构建。

### 3.3 PIE（同一工程，Node Editor 可见）

| 线程 | 相 | 排他均值 | 占帧 |
|---|---|---:|---:|
| `render:GameRuntime` | **帧** | **33.15 ms** | |
| | `frame.sync_wait` | **28.02 ms** | **84.5%** |
| | `gl.pick` | 3.97 ms | 12.0% |
| | `gl.entities` | 0.45 ms | 1.4% |
| `logic:GameRuntime` | `logic.layer.RuntimeNodeLayer` | 0.27 ms | —— |
| | `logic.sleep` | 4.65 ms | 240 fps 限帧 |

> **结论**: PIE 渲染线程 **84.5% 的时间在等编辑器**。它的真实工作量约 5 ms
> （≈200 fps 的能力），却被编辑器的 30 fps 钉住。这是"4 条线程表现得像 1.2 条"的
> 直接证据。

---

## 4. 已知限制

| 项 | 说明 |
|---|---|
| 开关本身有开销 | 每相 2 次 `perf_counter` + 一次作用域对象；实测 ~20 相/帧 ≈ 2–4 µs。默认关，测量时打开 |
| `frame.swap` 含 vsync | 它量的是"等缓冲"，看 CPU 成本时应扣除 |
| 非渲染线程无帧占比 | `end_frame(None)` 只冲刷样本；这是刻意的（逻辑帧 ≠ 渲染帧）|
| 同名线程 | 用 `name#ident` 区分（PIE 反复启停会产生同名线程）；报表两代并存是正常的 |
| 无限嵌套 | 栈深无上限但有失配保护（profiler 中途开关不会让父相认错孩子）|

---

## 5. 守卫

`Test/Application/Core/test_phase_profiler.py`（36 项）：
关态零样本 / 帧与未归因 / 嵌套排他 / 三层嵌套 / counter / worst_frames /
开关语义 / **栈失配** / 线程隔离 / 多 profiler 隔离 / reset / 报表 / 百分位单调。
