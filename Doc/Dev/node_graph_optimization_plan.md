# 议题 — 节点图求值优化（2026-11-10 开题，讨论中）

> **性质**: 议题文档（**不是**实施单）。记录"有哪些优化、各自怎么做、代价是什么、
> 为什么现在不做"；结论一旦定稿，再拆成 `product_todo.md` 的具体条目。
> **前置事实**: 2026-11-10 的 `NodeCanvas` 索引化（pin→node / 邻接 / 事件入口）
> 已经把图求值从 3.4 ms/帧 降到 **0.07–0.22 ms/帧**（×20）。本议题讨论的是
> "在那之上还能做什么"。

---

## 0. 先定基线：现在的瓶颈到底在哪

| 环节 | 实测（MI-SSSEP AllConditions，160–193 节点）| 占整帧 |
|---|---:|---:|
| **成品整帧** | **1.96 ms**（511 fps，vsync off）| 100% |
| 成品整帧（vsync on） | 5.01 ms（199.7 fps，显示器 200 Hz）| — |
| 图求值（干跑，纯 CPU） | **0.20 ms** | 10% |
| 编辑器整帧（Node Editor 可见） | 28 ms（35 fps）| — |
| ↳ 其中节点编辑器面板绘制 | **21.5 ms** | 77% |
| 编辑器整帧（面板隐藏） | 6.4 ms（156 fps）| — |

**三条硬结论**（先摆出来，避免讨论跑偏）：

1. **成品端图求值只占 10%**。把图求值优化到 0，成品也只是 1.96 → 1.76 ms。
2. **编辑器"卡"的元凶是面板绘制**（21.5 ms），不是图求值（0.20 ms）。这件事
   已经在 `product_todo.md §11.5` 单独挂着。
3. 因此：**本议题的价值不在 fps，而在"极大规模图"与"CPU 预算"**（同一台机器还要跑
   采集/推理/sidecar）。下面的收益都按"图求值内部占比"表述，不按 fps 表述。

---

## 1. 图求值现在每帧在干什么（理解优化空间的前提）

```
trigger("OnFrameUpdate")
└─ 查 event_nodes_of()  →  拿到事件节点（O(1)，索引化后）
   └─ _walk_exec(nid)                              ← 每节点一次
      ├─ _exec_visited 去重（set）
      ├─ 取 inst / NodeTypeDef（两次 dict 查）
      ├─ _EVALUATORS[type] → 调 evaluator 函数      ← 真正的业务
      │  └─ evaluator 内部：read_pin(每个输入) → 计算 → set_pin(每个输出)
      └─ 遍历 exec 输出 pin → downstream_of()（O(1)）→ 递归
   └─ 数据节点懒求值 _ensure_pin_evaluated()
      └─ 只在输出 pin 值为 None 时才求值（已有"一次性"语义）
```

**关键观测**: 数据节点（`Constant`/`Compare`/`VarGet`/`EntityGet`…）每帧都会被
exec 链**重新拉取**，而它们**没有**跨帧记忆 —— `_ensure_pin_evaluated` 的去重只
在**同一次 trigger 内**有效（`ctx._pin_values` 每帧清空）。这就是下面 85% 白算的来源。

---

## 2. 实测：85% 的求值是白算的

`Test/_runs/perf_2026-11-10/value_churn.py`（300 帧，记录每次调用的输入/输出）：

| 示例 | 求值次数 | /帧 | 输出没变 | **输入完全没变** |
|---|---:|---:|---:|---:|
| MISSSEP-AllConditions | 12 653 | 42.2 | **85.1%** | **99.3%** |
| MISSSEP-BestOnly | 12 653 | 42.2 | 85.1% | 99.3% |
| MISSSEP-OnlineTrain | 8 456 | 28.2 | 77.8% | 99.0% |
| NoFeedback-40Hz-Block | 4 574 | 15.2 | 59.2% | 98.5% |

按类型（AllConditions）：

| 类型 | 调用/300帧 | 输出未变 | 输入未变 |
|---|---:|---:|---:|
| `Compare` | 4 202 | **4 186（100%）** | 4 186 |
| `Constant` | 2 110 | 2 093（99%）| 2 093 |
| `EntityGet` | 1 207 | 1 196（99%）| 1 196 |
| `VarGet` | 1 202 | 1 199（100%）| 1 199 |
| `EntitySetRenderVisible` | 1 207 | 1 196（99%）| 1 196 |
| `TimeTrigger` | 1 500 | 299（20%）| 1 495 |

**这就是"相邻同操作节点能不能压缩"的直觉来源 —— 直觉是对的，但归因错了**：
不是"节点太碎"，而是"**输入没变还在重算**"。

---

## 3. 实测：融合（supernode / 字节码）的天花板只有 7–12%

`Test/_runs/perf_2026-11-10/dispatch_cost.py`（合成 exec 链，对照组把 evaluator 换成空函数）：

| 链长 | 真实求值 | 空 evaluator（纯 dispatch）| 实际工作量 | **融合上限** |
|---:|---:|---:|---:|---:|
| 20 | 0.3112 ms/帧 | 0.0233 | 0.2878 | **7%** |
| 100 | 0.9072 ms/帧 | 0.1075 | 0.7997 | **12%** |

拆到每节点：**dispatch 1.08–1.17 µs**，有效工作量 8–14 µs。

代进真实图：

```
AllConditions 图求值 0.20 ms/帧
  ├ dispatch 42.2 × 1.1 µs ≈ 0.046 ms   (23% 的图求值)
  └ 有效工作               0.154 ms
整帧 1.96 ms → 融合最多省 0.046 ms = 2.4% 整帧
```

**结论：运行时融合不做。** 换来 2.4% 帧，代价是一个图编译器（SuperNode 语义、
props 合并、pin 映射、在线/离线两份校验器同步、UI 显示与调试）—— ROI 不成立。

> 什么时候值得重开？当出现 **1000+ 节点**的图，或图求值占整帧 > 40% 时。
> 那时的正确做法也不是"融合相邻同操作"，而是**把 exec 链编译成 Python 闭包链**
> （见 §4.4），它同时消掉 dispatch 和 pin 读写。

---

## 4. 推荐的四个优化（按 ROI 排序，逐个说"怎么做"）

### 4.1 常量折叠（最稳，先做这个）

**做什么**: 加载/导入时把 `Constant` 节点的值**内联到下游节点的 props**，然后删掉
该 `Constant` 节点与它的连线。运行时图里就没有这个节点了。

**为什么有效**: `Constant` 每帧被拉取 2 110 次（AllConditions），99% 输出没变。
它是**纯函数、无状态、值来自 props**，折叠完全安全。

**怎么实现**（落点 `Application/Core/NodeGraph/`，新增 `compile.py` 或挂在 `canvas.py`）：

```
for each node N (topological order):
    for each data input pin P of N:
        src = canvas.source_pin_of(P)
        if src 属于 Constant 节点 C:
            key = pin_name_of(src)                     # Constant 只有 Result
            value = C.props["value"]
            N.props[<映射名>] = value                   # ← 需要 pin→prop 映射
            删除 P 的连线
        如果 C 的所有出边都被折叠完 → 删除 C
```

**唯一的难点（必须先解决）**: `read_pin` 走的是**引脚**，不是 props。要让下游
"读到 props 里的值"，需要一条**声明式**的映射，例如在 `node_pack` / `NodeTypeDef`
里加：

```python
"fold": {"In_1": "props.a", "In_2": "props.b"}   # pin 名 → props 键
```

或者更简单：**只折叠 `Constant → 同类型 pin` 且下游 evaluator 已经会回退读
props 的情况**。实测 `ScalarMath` 有 `In_0..In_7` 引脚 + `a/b` props 两套输入，
`Compare` 有 `A/B/C` 引脚 + `operation` prop —— 两套并存，所以**必须先有映射表**，
否则折叠会改变语义。

| 项 | 值 |
|---|---|
| 预期收益 | 图求值调用数 **-17%**（Constant 占比），实际时间 -10~15% |
| 风险 | **中**（映射错就静默改语义）→ 必须有"折叠前后干跑事件序列一致"的验收 |
| 工作量 | 1–2 天（含守卫） |
| 必须遵守 | 只在**运行时副本**上折叠（PIE/export 的 canvas copy），**绝不改用户 `.scene`** |

**验收**: 对 7 个示例做"折叠前 vs 折叠后"干跑，`events` / `errors` 序列必须一致
（和索引化改造时用的是同一套方法）。

---

### 4.2 死链裁剪（最便宜）

**做什么**: 从 Event 节点做可达性分析（exec 边 + data 边），不可达的子图整体跳过。

**为什么有效**: 编辑器里"改了一半"的分支很常见。实测 4 个示例目前**没有**不可达子图
（裁剪收益 0），但它是**防御性**的：`extension.disable` 后节点变 unknown、用户删了
事件节点但留着下游，都会产生死子图。

**怎么实现**: 已有基础设施直接用 —— `event_nodes_of()` 给出所有入口，
`downstream_of()` / `source_pin_of()` 给出两个方向的边。一次 BFS 即可：

```
reachable = set()
stack = 所有 Event 节点
while stack:
    n = pop(); if n in reachable: continue
    reachable.add(n)
    stack += downstream_of(每个 exec 出 pin)
    stack += pin_owner_of(source_pin_of(每个 data 入 pin).反查)   # 数据上游
dead = all_nodes - reachable
```

| 项 | 值 |
|---|---|
| 预期收益 | 当前 0%；图被改坏时避免全量求值 |
| 风险 | **低**（只是少算，不算错）—— 但要小心"数据节点只为 UI 预览存在"的情况 |
| 工作量 | 半天 |
| 附带价值 | 可以做成**编辑器提示**："有 N 个节点不可达（点击高亮）"，比裁剪本身更有用 |

---

### 4.3 纯节点记忆化（收益最大，风险最需要设计）

**做什么**: 给节点类型加**声明式** `pure: true`。对 pure 节点，如果
（输入 pin 值 + props 版本）与上次调用完全一致，直接复用上次输出，**不进 evaluator**。

**为什么有效**: 实测 **99.0–99.3% 的调用输入完全没变**。理论上可跳过 85% 的求值。

**怎么实现**（三层，缺一不可）：

1. **声明**（扩展作者可选）：`node_pack.py` 的节点定义里加 `"pure": true`；
   核心节点在 `NodeTypeDef` 上加默认值（`Constant`/`Compare`/`ScalarMath`/`VarGet`/
   `EntityGet` 可标 pure；`Random`/`TimeGetElapsed`/`TimeTrigger`/设备节点**不能**）。
2. **判据**：`GraphEvaluator` 维护 `_memo[node_id] = (inputs_tuple, props_rev, outputs)`。
   输入值比较用 `==`（对 numpy 走 `.all()`，已有 `_eq` 写法可复用）。
3. **失效**：
   - 输入变化 → 重算；
   - `props` 变化 → 靠 `NodeCanvas.revision` 或 per-node `props_rev`；
   - **`ctx` 里的隐式状态**（`ctx.elapsed_time`、`ctx.scene`、设备会话）→
     pure 节点**禁止**读这些，靠"声明即承诺"约束。

```
# 示意（不是最终代码）
def _eval_node(self, nid, ctx):
    nd = self._types[inst.node_type]
    if not getattr(nd, "pure", False):
        return self._call_evaluator(nid, ctx)
    ins = tuple(ctx.get_pin(pid) for pid in 入引脚)
    memo = self._memo.get(nid)
    if memo and memo[0] is ins_key_equal and memo[1] == inst.props_rev:
        for name, val in memo[2]:
            ctx.set_pin(inst.pin_ids[name], val)
        return
    self._call_evaluator(nid, ctx)
    self._memo[nid] = (ins, inst.props_rev, [(n, ctx.get_pin(inst.pin_ids[n])) for n, _ in 出引脚])
```

| 项 | 值 |
|---|---|
| 预期收益 | 图求值 **-70~85%**（0.20 → 0.03–0.06 ms/帧），整帧 -7%（1.96 → 1.82 ms）|
| 风险 | **中高**：漏标一个"假 pure"节点（读时间/随机/设备）→ **静默错值**，实验数据报废 |
| 工作量 | 2–3 天（含把核心节点逐个定性 + 守卫） |
| 降低风险的做法 | ① 默认 `pure=false`，只对**逐个 review 过**的核心节点打开 ② 守卫测试：对每个 pure 节点做"改输入必变输出 / 不改输入必同输出"对拍 ③ 加 `MGE_MEMO=off` 一键关掉，出问题立即回退 |

**这是四个里唯一"值得为它写设计评审"的**。我的建议是**先只对 `Constant` 开放**
（4.1 已经能把它整个消掉，所以实际上先做 4.1 就够），等 4.1 稳定后再评估
`Compare`/`EntityGet`。

---

### 4.4 编译成闭包链（现在不做，记录触发条件）

**做什么**: 把整条 exec 链在加载期编译成 `list[callable]`，运行时就是一个 `for f in chain: f(ctx)`，
彻底去掉 `_walk_exec` 的递归、去重 set、pin 查找。

**为什么不现在做**: 收益上限就是 §3 的 7–12%（图求值内部），整帧 2.4%。

**什么时候值得**: 出现 1000+ 节点图，或图求值占整帧 > 40%。
届时和 §4.1/4.2 是互补的（折叠完再编译，代码更短）。

---

## 5. 明确"不做"的项

| 项 | 理由 |
|---|---|
| **运行时相邻节点融合（supernode）** | 天花板 7–12% 图求值 = 2.4% 整帧；代价是图编译器 + 双份校验器 + UI 适配 |
| 把手写 evaluator 换成 numpy 批量 | `Compare` 单次 ~1 µs，批量化的收益被 Python 调用开销吃掉；只在"同构大数组"场景有用（`SignalProcess` 已在做） |
| 用 Cython / Rust 重写 evaluator | 破坏"扩展作者写 Python"的生态前提 |
| 提前做多线程并行求值 | 图求值 0.2 ms，线程调度开销同级；且 free-threading 下 GIL 已不是瓶颈 |

---

## 6. 与"性能统计器 → UI 组件"的关系（交叉引用）

2026-11-10 新增的采集链已经就位：

```
Core/Stats/FrameProfiler.snapshot_stats()      ← 唯一数据源（线程安全）
   ├─ Runtime/PerfStatsLayer  → JSON（离线分析，已实现）
   ├─ Core/UI/PerfHUD         → 游戏内 UI 组件（待做，用户已确认方向）
   └─ Editor 面板             → 复用同一 snapshot（可选）
```

- `PerfHUD` 应做成**运行时 UI 系统的一个组件**（`UIPerfLabel`/`UIPerfPanel`，由
  `RuntimeUILayer` 驱动），**不新增 Layer** —— 这样自动获得锚点/布局/DPI/overlay 穿透。
- `FrameProfiler` 必须加 `enabled` 开关，默认关：`snapshot_stats()` 会 `sorted()`
  整个 1000 帧窗口，1 Hz 采样也是 1000 次排序/s，常驻不值得。
- **优化顺序建议**：`snapshot_stats` 先出**增量版**（O(1) 滑动均值 + p99 桶近似，
  避免全排序）→ 再做 `UIPerfLabel` 组件。

---

## 7. 决策清单（待你拍板）

| # | 问题 | 我的建议 |
|---|---|---|
| 1 | 先做哪个？ | **4.1 常量折叠**（收益确定、可验证），但**前提是先补 pin→props 映射的声明** |
| 2 | 4.2 死链裁剪做不做？ | 做，但做成**编辑器提示**（当前收益 0，防御性为主） |
| 3 | 4.3 记忆化什么时候开？ | 等 4.1 稳定后，且**只对 `Constant` 之外再评估 1–2 个高频纯节点** |
| 4 | 4.4 编译闭包链 | 记着，等 1000+ 节点图出现 |
| 5 | 要不要先量"极大规模图"？ | **建议要** —— 用 `Utils/Dev/perf_graph.py graph` 造 500/1000 节点合成图，先确认拐点在哪，再决定 4.4 的优先级 |

---

## 8. 复现命令（本文所有数字都可复跑）

```powershell
# 图求值现状（7 个 MI-SSSEP 示例 + 节点类型归因）
.venv-py314t\Scripts\python.exe Utils/Dev/perf_graph.py graph `
    --dir Application\Functions\missssep\Examples --frames 600

# 冗余度（85% 白算）
.venv-py314t\Scripts\python.exe Test/_runs/perf_2026-11-10/value_churn.py 300

# dispatch 开销 / 融合上限
.venv-py314t\Scripts\python.exe Test/_runs/perf_2026-11-10/dispatch_cost.py 100

# 优化前后等价性（索引化时用的同一套）
.venv-py314t\Scripts\python.exe Test/_runs/perf_2026-11-10/ab_final.py 600

# 回归门槛（把优化前的 JSON 当基线，退化即 exit 3）
.venv-py314t\Scripts\python.exe Utils/Dev/perf_graph.py graph --json before.json
.venv-py314t\Scripts\python.exe Utils/Dev/perf_graph.py graph --baseline before.json
```
