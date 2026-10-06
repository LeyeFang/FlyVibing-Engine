# 线程开发协议（线程治理 + 实时探针）

> 适用：**任何新开线程 / 跨线程通信 / 服务进程集成**（例：品牌设备独立进程 + 引擎侧通信线程）。
> 运行时侧：`Application/Core/ThreadRegistry.py`；实时探针：`Utils/Dev/thread_probe.py`（op:`threads.snapshot`）。
> 最小纪律见 `runtime_packaging_protocol.md` §3.1（就绪标记最后赋值）——本文是全文；§3.1 仍是 PIE 必读。

---

## 1. 线程清单（2026-10-05 实况, `threads.snapshot` 可随时核对）

| name（注册名） | owner | 启动点 | 心跳 | 同步通道 |
|---|---|---|---|---|
| `render:<Engine>` | Engine | `Engine.init` → `_render_loop` | expect_hz=20（每帧） | 命令队列（renderer.enqueue） |
| `logic:<Engine>` | Engine | PIE 时 `logic_loop` | expect_hz=20（每帧; 限帧 240） | 帧同步（FrameSync master/slave） |
| `LiveCommandServer` | LiveCommandServer | `start()` → `_accept_loop` | expect_hz=2（0.5s 超时轮询） | `_queue` + Event（主线程 pump） |
| `live-client:<tid>` | LiveCommandServer | 每连接一个 | 0（阻塞 recv） | 同上（每请求投递） |
| `GraphValidation#<id>` | NodeGraph.validation | `start()` → `_work` | 0（单任务） | 锁保护任务槽 |
| `bci-<name>` | SyncJob | `run_async` | 0（长任务） | 锁保护结果槽 |
| `eeg-<brand>-service` | ServiceClient | `_start_reader`（push 模式） | 0（阻塞 recv） | rid 路由 + 回调 |
| `spd-io` | SerialParallelDevice | `start()` | 0（队列驱动） | 任务队列（tx_queue） |

> 品牌独立进程（如 Gtec）**自己的线程**运行在它自己的进程里——引擎快照看不到它；
> 引擎侧与之通信的线程 = `eeg-<brand>-service`（ServiceClient reader 模式，本协议的标准样例）。

## 2. 跨线程三通道（只许这三种）+ 禁止项

1. **命令队列**（enqueue）：写方入队、拥有方线程消费 —— 例：`renderer.enqueue(...)`、`LiveCommandServer._queue`。
2. **不可变快照**：写方生成新对象、读方取引用 —— 例：`FrameCaptureSlot`（抓帧信箱）。
3. **阻塞任务槽**：worker 只碰自己的锁保护槽，绝不触碰 ctx/求值器/面板 —— 例：`SyncJob`、validation service。

**禁止**（边界守卫测试将逐条上钩，见 §6）：
- 跨线程直接调用 ImGui / GLFW / 渲染器状态（只能经三通道）；
- `OnUpdate` 读取无类级默认值的字段（§3.1 半初始化窗口）；
- **启动链吞错**：`except → print 继续`（例：host-sync 失败仅打印）——必须上抛或置错误态 + 明确日志。

## 3. 新线程检查单（四步，缺一不可）

```python
# 1. 线程入口（在目标线程内部调用, 记录线程对象）
ThreadRegistry.register("my-worker", owner="模块名", expect_hz=20.0, note="用途")
try:
    while running:
        ThreadRegistry.heartbeat("my-worker")   # 2. 每轮一次
        ...工作...
finally:
    ThreadRegistry.unregister("my-worker")      # 3. finally 注销
# 4. 验收: python Utils/Dev/thread_probe.py --assert-alive my-worker
```

- **命名**：小写「域-用途」（`spd-io` / `eeg-gtec-service`）；每实例带后缀（`render:EditorHost`）；每连接带 tid（`live-client:<tid>`）。
- **expect_hz**：周期循环填实际频率（建议 20）；**阻塞等待型填 0**（静默不推进 = 正常，探针永不误报 stale）。
- **未注册也不丢心跳**：`heartbeat` 对陌生名字自动注册（owner=`<auto>`）——但仍要求显式 register（owner/note 给人和 agent 看）。
- **存活判定**：`alive` 字段来自注册时记录的线程对象；`unregistered` 字段列出进程内**未注册的命名线程**（漂移收编清单）。

## 4. 实时探针（人 / agent 双通道）

| 通道 | 用法 |
|---|---|
| op（全通道自动获得） | `engine-editor-cli call threads.snapshot`；MCP：`engine_call({"op": "threads.snapshot"})` |
| 开发 CLI（可监视/断言） | `python Utils/Dev/thread_probe.py`（`--watch --hz 4` / `--assert-alive a,b` / `--fail-on-stale`） |

- 判定规则：`expect_hz > 0` 且 `age > max(1.0s, 3/expect_hz)` → **stale**（停滞嫌疑，`*` 标记）。
- 退出码（脚本/e2e 可吃）：0 正常 / 2 引擎未连接 / 3 断言失败。
- 工具归属：`Utils/Dev/`（开发者侧，不随产品分发）；op 本体在引擎内（`threads.snapshot`，只读诊断）。

## 5. 压力 / 竞态测试（已落地）

- **运行**：`python Utils/Dev/test_runner.py --stress N`（每测重复 N 轮，日志带 `_rN` 后缀）；
  单跑：`--only stress`。
- **用例**（`Test/Application/stress/test_stress_thread_races.py`，core 档，内部 4 轮）：
  A. ThreadRegistry churn（6 线程并行注册/心跳/注销 + 快照读者，beats 精确断言）；
  B. LiveCommandServer 并发（8 客户端 × 10 ops + 主线程 pump，全应答全 ok）。
- 放大策略：外层 `--stress N` × 内层轮数；失败日志在 `Test/_runs/run_*/logs/*_rN.log`。
- 先例模式参考：`test_runtime_node_layer_race.py`（受控阻塞点，确定性复现）。

## 6. 启动/就绪与边界守卫（已落地）

- **READY 屏障**：`GameRuntime.start` 等 `layers_attached`（≤15s）；超时或 `sync_scene_from_host`
  失败 → 抛错 + `stop()` 清理；`SimulationController` 捕获后置 `last_error`（`sim.state` 可查）
  并回 STOPPED —— 不再静默"启动但没内容"。
- **逻辑限帧**：`Engine.logic_target_fps`（默认 0=不限）；PIE（`GameRuntime`）= 240 ——
  实测 busy-spin ~63kHz → ~240Hz（`test_pie_bare` 33s→11.5s，CPU 空转降 ~99%）。
- **边界守卫测试**：`Test/Application/Core/test_thread_boundary.py`（core 档）：
  R1 启动点白名单 / R2 接线校验（wired + delegated）/ R3 纯逻辑层零 threading。
  新增线程 = 改白名单 + 接线，测试自动把关。

> 章节归属与里程碑：`roadmap_next.md` 章 T（本协议的执行进展同步在那里）。
