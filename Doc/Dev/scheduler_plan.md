# 议题 — Engine 级调度器（Scheduler）设计（2026-11-11 立项，未实现）

> **性质**: 设计/计划文档（`*_plan` 类，正文留在引擎仓）。
> 实现完成后按 `Doc/Dev/README.md` 的约定迁到工具仓
> `docs_content/dev/scheduler_protocol.md`，引擎侧只留指针 stub。
> **前置事实**: 本文所有线程数与时序数字都来自 2026-11-10/11 实测
> （`PlayerEntry --stats-json` 的 `threads` 字段 + `pulse_precision.py`）。

---

## 0. 结论先行

| 问题 | 结论 |
|---|---|
| 该不该有 Engine 级调度器 | **该有**，但价值不在"三个运行形态都能拿到"（那只是顺带）|
| 归谁管 | **归 `Engine`**，用既有的 `_state()` + `_get_xxx()` 延迟创建范式（照抄 `FrameProfiler`）|
| 每个 Engine 一根线程？ | **是**，按 `cls.__name__` 隔离；`sched:EditorHost` / `sched:GameRuntime` |
| 常驻成本 | **懒创建**：没人排过 job 就不起线程。空闲时阻塞在 `Condition.wait()`，实测 CPU ≈ 0 |
| 它替代 SPD 的绝对时刻调度吗 | **不替代**。引擎做"派发器"（谁在何时被叫醒），SPD 做"节拍器"（每 N ms 发哪些字节）|
| 现在做吗 | 不做。排在 SPD 的 `StartPulseTrain` 之后（见 §9）|

---

## 1. 线程账（实测，不是估算）

导出成品跑 4 秒，`PerfStatsLayer` 记录的线程清单：

```text
project: Examples/UIShowcase   (node_graph 只有 4 种节点，零设备节点)
threads:
   MainThread              daemon=False
   Thread-1 (_render_loop) daemon=True
   spd-io                  daemon=True
```

### 1.1 现状

| 运行形态 | 线程 | 数量 |
|---|---|---:|
| **导出成品** | `MainThread`（内联逻辑 + `window.Update`）+ `_render_loop` + `spd-io` | **3** |
| **PIE** | `MainThread`（编辑器）+ `render:EditorHost` + `logic:GameRuntime` + `render:GameRuntime` + `spd-io` + `live-client:*`（按连接数） | **5 + N** |
| **编辑器** | `MainThread` + `render:EditorHost` + `LiveCommandServer`（accept 循环）+ `live-client:*` | **3 + N** |

> `spd-io` 在**零设备节点的图上也会启动** —— 这是缺陷，见 §5 与
> `product_todo.md §11.7`。上表是"当前实际"，不是"应该是"。

### 1.2 加调度器之后

| 运行形态 | 无定时需求 | 有定时需求 |
|---|---:|---:|
| 导出成品 | **3**（不变） | **4** |
| PIE | **5 + N**（不变） | **7 + N** |
| 编辑器 | **3 + N**（不变） | **4 + N** |

前提是 **`_get_scheduler()` 懒创建**；若在 `init()` 里 eager 起线程，上面三行全部 +1，而绝大多数成品根本不需要定时器 —— 那是纯浪费。

---

## 2. 为什么归 `Engine` 管（五条都能指到代码）

| # | 理由 | 依据 |
|---|---|---|
| 1 | **时间基必须一致**。`schedule(delay)` 的 deadline 与 `get_elapsed_time()` 必须是同一个 `perf_counter` 起点，否则日志/回放对不上 | `Engine._tick_timing()` 用 `perf_counter`；`_engine_start_time` 是 **per-engine** 的（`_state()` 内） |
| 2 | **per-engine 隔离是既有设计**，不是新发明 | `Engine._state()` 注释："避免 `layer_stack` / `renderer_ready` 等可变类变量在子类间意外共享" |
| 3 | **线程命名已有规范**：`render:{cls.__name__}` / `logic:{cls.__name__}` → 调度器自然叫 `sched:{cls.__name__}`，`threads.snapshot` 一眼看出归属 | `Engine._render_loop()` / `_logic_loop()` |
| 4 | **暂停语义需要 per-engine 时钟**。`product_todo.md §10.7` 定的 scope（graph / timers / media / device_io / render 逐项开关）若放全局单例，暂停 PIE 会连带影响编辑器 | `product_todo.md §10.7` |
| 5 | **生命周期天然对齐**：`_get_profiler().start()` 在 `_render_loop` 里、`stop()` 在 finally；调度器同一处 start/stop | `Engine.py:570` / `:607` |

### 2.1 直接照抄 `FrameProfiler` 的三件套

```python
# Engine._state() 里加一项
'_scheduler': None,

@classmethod
def _get_scheduler(cls) -> 'Scheduler':
    """返回当前 Engine 的调度器（懒创建 —— 没人排过 job 就不起线程）。"""
    st = cls._state()
    if st['_scheduler'] is None:
        st['_scheduler'] = Scheduler(engine=cls)
        st['_scheduler'].start()
    return st['_scheduler']
```

---

## 3. 形态：独立线程、只派发不执行、空闲零成本

### 3.1 绝对不能这么做

| 做法 | 后果 |
|---|---|
| `scheduler.tick()` 塞进 `_tick_timing()` 或 `layer.OnUpdate()` | 立刻退化成第二个 `TimeTrigger`，**8.3 ms 天花板原样保留**（图求值只在逻辑 tick 奇数帧跑）|
| 再开一个"跑图的逻辑线程" | 同步面积翻倍，且逻辑线程已被 `logic_target_fps=240` 限速 |
| 调度线程里直接调 GL / 串口 / esper | 破坏三通道纪律（`threading_protocol.md §2`）|

### 3.2 正确形态

```python
# Core/Scheduler.py（约 200 行）
线程名 / 注册名: f"sched:{engine.__name__}"
ThreadRegistry.register(..., expect_hz=0.0,
                        note="deadline 驱动; 空闲不推进心跳=正常")

while engine.run_state:
    现在 = perf_counter()
    while 堆 and 堆[0].deadline <= 现在:
        job = heappop()
        if not job.cancelled:
            queue.put(job)              # ← 只入队，不执行
    next_dl = 堆[0].deadline if 堆 else None
    cond.wait(timeout=None if next_dl is None else max(0.0, next_dl - 现在))
```

三条硬约束：

1. **派发器不是执行器**。调度线程只把到期 job 入队，由**逻辑线程** drain 或调用方指定线程。这就是 `sched` 与 `spd-io` 必须分开的原因：`sched` 说"到点了"，`spd-io` 做"发字节"。
2. **空闲必须几乎零成本**。用 `Condition.wait(timeout)`，**禁止 `sleep(0.001)` 轮询**。实测：一个空闲的阻塞线程在 3 s 内 CPU < 0.03%（`spd-io` 的实测值，同样是阻塞在 `queue.get(timeout=0.05)`）。
3. **不保证绝对精度**。调度器只保证"不晚于 deadline 太多"；`deadline += period` 这种不漂移的累加**必须由需要高精度的一方做**（只有它知道硬件延迟）。

---

## 4. 生命周期与清理（唯一真正的风险点）

PIE 与导出**共用 `GameRuntime._state()`**（同一 dict，`stop()` 会重置）。所以不清理会留下死调度器，重演 `FrameProfiler.stop()` 那个坑（旧会话帧时间混进新会话）。

| 时机 | 动作 | 位置 |
|---|---|---|
| `Engine.shutdown()` | `scheduler.stop()`（`cancel_all` + join + `st['_scheduler'] = None`）| `Engine.py:451` |
| `GameRuntime.stop()`（PIE 停） | 同上 | `GameRuntime.py:174+` |
| `layer.OnDetach()` 全部完成 | `cancel_owner(f"layer:{name}")` | `_render_loop` finally |
| `extension.disable` | `cancel_owner(ext_id)` | `ExtensionManager` |
| `SceneManager` 场景切换 | 可选 `cancel_owner(f"scene:{name}")` | `SceneManager` |

**`owner` 机制是这套设计最值钱的部分** —— 它让"扩展必须自己清理定时器"变成宿主的责任，扩展侧一行代码都不用写。

---

## 5. 与 `spd-io` 的分工（当前缺陷见 `§11.7`）

| 层 | 归属 | 内容 |
|---|---|---|
| "在 t 时刻叫我" | **本调度器** | 通用、可复用、带 owner 清理 |
| "每 25 ms 精确发一串字节" | **SPD 扩展** | 绝对时刻累加 + 硬件/驱动延迟补偿 |
| 图里"开始/停止" | 节点图 | 不变 |

**为什么不能合并**：调度器不知道硬件缓冲延迟，SPD 不应该重复实现 timer。两者组合才是最优；单独任一方都有缺口（见 `node_graph_optimization_plan.md §5` 里 `spd-io` 的抖动数据：20 Hz p50 = 50.0000 ms 达标、40 Hz ±5–6 ms 不达标）。

> ⚠️ 现状提醒：`spd-io` 目前在**零设备节点的图上也会启动**，且启动时会向 LPT1/2/3
> 写 0（`api.start()` 的并口复位）。这条与调度器无关，是要单独修的缺陷
> （`product_todo.md §11.7`）。

---

## 6. 扩展侧门面（与 `ctx.ops` / `ctx.nodes` / `ctx.ui` / `ctx.graph` 同级）

```python
ctx.scheduler.schedule(delay_s, cb, repeat_s=None)   # owner 自动 = ext_id
ctx.scheduler.cancel(handle)
ctx.scheduler.pending()                              # 诊断: 本扩展排了几个
```

注入点：`ExtensionManager` 构造 `ExtensionScheduler(ext_id)` 时把 `ext_id` 绑成 owner，扩展**无法**误取消别人的 job。与 `ExtensionGraph(ext_id)` 同一模式。

---

## 7. 验收

| 项 | 门槛 |
|---|---|
| 懒创建 | 不使用调度器时，`threads.snapshot` 里**没有** `sched:*` |
| 空闲成本 | 有 `sched:*` 但无 job 时，进程 CPU 增量 < 0.1% 单核 |
| 派发延迟 | 1 ms / 10 ms / 100 ms 三档，`deadline` 到实际入队的偏差 p99 < 2 ms（无重负载时）|
| 不漂移 | 以 `repeat_s=25ms` 连跑 60 s，累计触发次数 = 2400 ± 1 |
| 清理 | `stop()` 后 `threads.snapshot` 无 `sched:*`；再次 `start()` 后重新出现 |
| owner 清理 | `extension.disable` 后该扩展的 job 全部消失（`pending(owner)` == 0）|
| 不阻塞主循环 | 排 1000 个 job 后，图求值帧时间变化 < 5% |

---

## 8. 明确不做

| 项 | 理由 |
|---|---|
| 全局单例调度器 | 破坏 per-engine 暂停作用域（§2 理由 4）|
| 调度器负责执行回调 | 会把 GL/IO 拉进调度线程，破坏三通道纪律 |
| 用 `TimeTrigger` 节点"改准" | 天花板是帧粒度，改节点无用（`node_graph_optimization_plan.md §5`）|
| 高精度（< 0.1 ms）保证 | Windows 调度器分辨率不够；高精度需求归设备扩展 |
| 用 `time.sleep` 轮询 | 空闲成本会变成可测量的 CPU，且唤醒抖动大 |

---

## 9. 落地顺序（不进 1.1.0）

| 顺序 | 事项 | 理由 |
|---|---|---|
| 1 | SPD 的 `StartPulseTrain` / `StopPulseTrain` | 已发回执，直接决定实验数据质量 |
| 2 | `product_todo.md §11.7`（`spd-io` 按需启动） | 与调度器无关，但同属"不该无条件占用"的问题，先修便宜的那个 |
| 3 | `Core/Scheduler.py`（堆 + Condition + owner） | 通用能力，补"事件时刻"缺口 |
| 4 | `Engine._get_scheduler()` + 五个清理点 + `ctx.scheduler` | 接入生命周期 |
| 5 | `SetTimer` / `Delay` 类节点改走 Scheduler | 让"延时"不再吃帧率 |
| 6 | SPD 落地时**可选**改用 `ctx.scheduler` | 他们已达标就不再动 |

---

## 10. 复现命令

```powershell
# 线程清单（任意工程 / 成品）
.venv-py314t\Scripts\python.exe Application\PlayerEntry.py <proj> `
    --seconds 4 --stats-json out.json
# out.json 的 "threads" 字段即实测线程表

# 零设备节点的图（用于验证 §11.7）
.venv-py314t\Scripts\python.exe Application\PlayerEntry.py `
    Examples\UIShowcase\UIShowcase.myproj --seconds 4 --stats-json out.json
# 预期（修复前）: threads 含 spd-io
# 预期（修复后）: threads 不含 spd-io
```
