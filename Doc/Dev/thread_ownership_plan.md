# 议题 — 扩展线程所有权（Thread Ownership）设计（2026-11-11 立项，未实现）

> **性质**: 设计/计划文档（`*_plan`）。实现完成后按 `Doc/Dev/README.md` 约定迁到工具仓
> `docs_content/dev/thread_ownership_protocol.md`。
> **上游关系**: 本文是 `scheduler_plan.md` 的上游 —— **先定线程归属，再谈调度器**。
> **本文所有"现状"均来自代码实测**（2026-11-11，含进程归属核对）。

---

## 0. 结论先行

| 问题 | 结论 |
|---|---|
| 要不要做"扩展申请线程"的管理体系 | **要**，但管理的是**生命周期 / 归因 / 异常隔离**，不是 CPU 调度 |
| 引擎能"调度线程"吗 | **不能**。CPython 无线程优先级/时间片 API；Windows 默认定时器精度 ~15.6 ms |
| 不负责第三方扩展的可靠性，问题会收缩吗 | **大幅收缩**：收缩掉"功能正确性"与"性能质量"；但**宿主不变量（可退出/不崩/可归因）不能收缩** |
| 官方扩展 vs 第三方 | 官方：声明 + 校验 + CI 报警；第三方：**只告警不阻断**（除三件不变量）|
| 只给"并发手段"够不够 | 够，但**必须比裸 `threading.Thread` 更省事**，否则没人用（§7）|
| 现在就做吗 | 是。它比 `Scheduler` 便宜（不引入新线程模型），且能顺手收掉 P0-F 与 6 个裸 spawn 点 |

---

## 1. 范围收缩：责任边界到底收缩了什么

「我们不负责第三方扩展的可靠性」这句话，要拆成两层才可执行：

| 层 | 内容 | 第三方扩展 | 官方扩展 | 引擎强制？ |
|---|---|---|---|---|
| **A. 功能正确性** | 采集对不对、时序准不准、算法对不对 | 扩展作者 | 主线 | ❌ 不管 |
| **B. 性能质量** | 是否吃满一核、是否漂移、是否 40 Hz 抖动 | 扩展作者（恶意/低效只上报）| 主线（CI 报警）| ⚠️ 只**上报** |
| **C1. 可退出性** | `disable` / 关引擎时线程能收（收不掉也不能挂死宿主）| **必须** | 必须 | ✅ **强制** |
| **C2. 故障隔离** | 线程内未捕获异常不得让宿主静默死亡/卡死 | **必须** | 必须 | ✅ **强制** |
| **C3. 可归因** | 线程名带扩展 id；泄漏能定位到谁 | **必须** | 必须 | ✅ **强制** |

**核心判断**：A/B 收缩，C1–C3 不收缩。原因不是"对第三方苛刻"，而是 **C 不是关于扩展的正确性，而是关于宿主的不变量** ——
用户装了一个烂扩展，可以功能不好用，但不能导致"编辑器关不掉"。

这正好对应一句可写进契约的话：

> **扩展可以不好用，但不能让宿主编不了整体退出。**

---

## 2. 现状实测：重 IO 已经在进程外了

### 2.1 引擎进程内的扩展线程（4 处）

| 扩展 | 线程名 | 位置 | 原型 | 生命周期 |
|---|---|---|---|---|
| SerialParallelDevice | `spd-io` | `SerialParallelDevice/api.py:57` | **阻塞队列循环**（`queue.get(timeout=0.05)`）| 进程级，租约制 |
| VirtualDevice（Gtec 复用）| `eeg-{brand}-service` | `VirtualDevice/ServiceClient.py:383` | **阻塞 recv（薄桥）** | 会话级 |
| BCIAlgorithm | `bci-{name}` | `BCIAlgorithm/Jobs.py:81` | **一次性任务** | job 级 |
| Gtec | `gtec-imp-{reason}` | `Gtec/extension.py:1187` | **一次性任务** | job 级 |

### 2.2 进程外（不是引擎线程）

| 扩展 | 线程名 | 位置 | 说明 |
|---|---|---|---|
| Gtec | `gtec-acq` + watchdog | `Gtec/brand_backend.py:288,290` | `brand_backend` **只被 `brand_service.py` 导入** → 跑在**服务进程**里（`python -m Application.Functions.Gtec.brand_service --port 47810`），由 `ServiceClient._proc = subprocess.Popen(...)` 拉起 |

### 2.3 这个实测说明了什么

> **Gtec 的重 IO 早就走"独立进程 + 引擎侧薄线程"了；引擎进程内剩下的确实只有
> 「通信」和「一次性任务」。**

也就是说，你描述的模型不是"提议"，而是**代码已经在这么做、只是没有正式的并发原语**。
这大大降低了设计风险：托管层不需要发明新模型，只需要把现有 4 处收口。

---

## 3. 三种原型，引擎只托管两种

| 原型 | 特征 | 是否池化 | 归谁 |
|---|---|---|---|
| **阻塞 IO 循环**（`spd-io`、`eeg-*-service`）| 独占一个线程跑 `recv` / `get(timeout)` | ❌ **绝不能池化** | 引擎管生命周期，扩展管循环体 |
| **一次性任务**（`bci-*`、`gtec-imp-*`）| 有界时间内跑完即退 | ✅ 可进有界池 | 引擎管（并发上限 + 超时）|
| **周期巡检**（watchdog 类）| 低频、按点唤醒 | ✅ 归调度器 | `Scheduler`（`scheduler_plan.md`）|

**为什么阻塞 IO 绝不能池化**：一个阻塞 `read()` 会长期占住池槽，把其他任务饿死 ——
这是 Java `ThreadPoolExecutor` 上最经典的陷阱（无界队列 + 阻塞任务 = 静默饿死）。
Gtec 把重 IO 挪进独立进程，本质上就是绕开了这个问题。

---

## 4. API（刻意最小）

```python
# 1) 阻塞 IO 循环（独占线程，不可池化）
h = ctx.threads.spawn_io(
    "io",                          # → 线程名 "{ext_id}:io"
    body,                          # body(cancel: threading.Event) -> None
    expect_hz=0,                   # 0 = 事件驱动（永不判 stale；只报 age）
)
h.cancel()                         # 置位 cancel 事件
h.join(timeout=2.0)                # 返回 True 表示已退出
h.alive                            # bool

# 2) 一次性任务（有界池 = CPU 核数上限，或扩展声明的小值）
ctx.threads.submit("imp", body, timeout_s=30) -> Future-like

# 3) 自查
ctx.threads.pending()              # 本扩展当前线程/任务数
```

引擎内部固定做这四件事（扩展**不需要**再写）：

1. **造线程**：`name=f"{ext_id}:{name}"`、`daemon=True`、uncaught hook 记录
2. **注册表**：`ThreadRegistry.register/unregister` 自动（含 `expect_hz` / note）
3. **取消**：`cancel` 事件 + 有界 `join`；`disable` 时统一触发
4. **上报**：正常退出 / 超时未退 / 抛异常 → 计数 + 日志（启动 `MGE_THREAD_TRACE=1` 时打栈）

对照现有 `threading_protocol.md` 的手写四步，托管版是 **1 次调用 vs 4 步样板** ——
这是采用率的唯一保证（§7）。

---

## 5. 强制 vs 建议

| 项 | 官方扩展 | 第三方扩展 | 实现 |
|---|---|---|---|
| 走 `ctx.threads`（不裸 spawn）| 强制（AST 守卫）| **建议**（无法扫描外部仓库）| 守卫扫 `Application/Functions/**` |
| `disable` 时必须能收（C1）| 强制 | **强制**：`cancel` + join 超时 → 告警；**仍存活则记录并放生**（daemon，不挂宿主）| 托管层 |
| 异常不得静默（C2）| 强制 | 强制 | `sys.excepthook` / wrapper |
| 命名带 ext id（C3）| 强制 | 强制（托管层自动命名，无法绕过）| 托管层 |
| 线程数预算 | 超出 → `spawn` 抛错 | 超出 → **只告警** | `MGE_THREAD_BUDGET`（默认 16）|
| `expect_hz` 漂移 | CI 报警 | 只上报（`threads.snapshot` 的 `stale`）| 已有 `ThreadRegistry` |
| 功能/性能 | 主线负责 | 扩展作者 | — |

> **"放生"的含义**：join 超时后不 `kill`（Python 无法安全杀线程），而是
> ① 记录 `{ext_id, name, alive_since}`；② 从 `ThreadRegistry` 标记为 `orphan`；
> ③ 让引擎继续退出。这样"宿主不被挂死"成立，同时泄漏可被 `threads.snapshot` 看到。

---

## 6. 明确不做

| 项 | 理由 |
|---|---|
| 线程**优先级 / 时间片 / 绑核** | CPython 无 API；`os.sched_setaffinity` 仅 Linux 且无优先级语义 |
| 实时性保证（"1 ms 内必醒"）| Windows 定制定时器精度 ~15.6 ms + GC 抖动；高精度需求归设备扩展（`scheduler_plan.md §8`）|
| 线程**重启 / 自愈** | 官方扩展在 `enable` 里自己写；第三方不做（不可控） |
| 健康检查协议（`expect_hz` 用于重启）| 只用于**报告**，不用于动作 |
| 用池托管阻塞 IO | §3 |
| 引擎替扩展决定"循环体何时执行" | 会让 `spd-io` / 设备轮询延迟失控 |
| 全局单一"线程总管" | 破坏 per-engine 暂停作用域（见 `scheduler_plan.md §2` 理由 4）|

---

## 7. 真正的风险不是设计，是采用率

第三方扩展**无法被 AST 扫描**（代码不在本仓），所以：

> **托管原语必须比裸 `threading.Thread` 更省事**，否则第三方一律绕过，管理体系退化成"官方内部规范"。

三条设计约束（都服务于采用率）：

1. **一次调用 vs 四步样板**（§4）—— 已经赢。
2. **默认值就是正确答案**：`spawn_io("io", body)` 不传任何参数就已经命名/注册/可取消。
3. **不用它也不至于立刻崩**：裸 spawn 的线程仍会被 `ThreadRegistry` 的
   `unregistered` 列表捕获（已有能力），只是不可取消、不可归因到扩展。

对照：VS Code 用**独立进程 + extension host** 强制隔离（成本高，但第三方无从绕过）；
Blender 不做托管，结果扩展作者各自踩坑。**我们选中间路线：便宜、可选、但默认可观测。**

---

## 8. 迁移清单

| # | 位置 | 现状 | 迁移后 |
|---|---|---|---|
| 1 | `SerialParallelDevice/api.py:57` `spd-io` | 自建线程 + 租约 `_leases` | `ctx.threads.spawn_io("io", ...)`；租约保留（多 owner 语义）|
| 2 | `VirtualDevice/ServiceClient.py:383` `eeg-*-service` | 自建线程 + `_reader_stop` | `spawn_io("service", ...)`；`_reader_stop` → `cancel` |
| 3 | `BCIAlgorithm/Jobs.py:81` `bci-*` | 裸 Thread（一次性）| `ctx.threads.submit(...)` + 超时 |
| 4 | `Gtec/extension.py:1187` `gtec-imp-*` | 裸 Thread（一次性）| `ctx.threads.submit(..., timeout_s=30)` |
| 5 | `Gtec/brand_backend.py:288,290` | **服务进程内**，不属于引擎 | **不动**（进程外，已有 `Popen` 管理）|
| 6 | `GameRuntime` 两处 `spd_start`（P0-F）| 无条件启动 | 由 `needs_device_io` 决定是否 `spawn`（§11.7）|

**迁移顺序**：托管层 → #3/#4（一次性任务，风险最低）→ #2（薄桥）→ #1（SPD，最重）→ #6。

---

## 9. 验收

| 项 | 门槛 |
|---|---|
| 命名与归因 | `threads.snapshot` 里扩展线程名全部形如 `{ext_id}:{name}` |
| 可退出 | `extension.disable` 后 2 s 内该扩展线程全部消失；收不掉的出现在 `orphan` 列表 |
| 不挂宿主 | 故意写一个 `while True: pass` 的扩展线程 → `disable` 后引擎仍能在 5 s 内正常退出 |
| 异常隔离 | 线程内 `raise` → 宿主不崩；`MGE_THREAD_TRACE=1` 时能定位到扩展与栈 |
| 预算 | `MGE_THREAD_BUDGET=2` 时第三次 `spawn_io` 对官方扩展抛错、对第三方只告警 |
| 零裸 spawn | AST 守卫扫 `Application/Functions/**` 无 `threading.Thread(` |
| 无回归 | 7 个 MI-SSSEP 示例的 `spd-io` 行为与刺激时序不变（20 Hz p50 = 50.0000 ms）|

---

## 10. 与 `scheduler_plan.md` 的关系

```
thread_ownership_plan（本文）    ← 线程从哪来、谁负责收
        ↓
scheduler_plan                 ← 到点什么时刻被叫醒（周期巡检的一种实现）
        ↓
spd-io / 设备扩展                ← 每次发多少字节、硬件延迟补偿
```

- **顺序**：本文 → `scheduler_plan` → SPD 的脉冲序列节点。
- **不重叠**：本文不管"何时执行"，`scheduler` 不管"线程谁造的"。
- **共同点**：两者都用 `owner`（= ext_id）做统一清理；两者都不碰 CPU 优先级。

---

## 11. 复现命令

```powershell
# 扩展线程现状（含 unregistered / stale / orphan）
.venv-py314t\Scripts\python.exe Utils\Dev\thread_probe.py
engine-editor-cli call threads.snapshot

# 零设备节点的成品若仍起 spd-io → 见 product_todo.md §11.7 (P0-F)
.venv-py314t\Scripts\python.exe Application\PlayerEntry.py `
    Examples\UIShowcase\UIShowcase.myproj --seconds 4 --stats-json out.json
```
