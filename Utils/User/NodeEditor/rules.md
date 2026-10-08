# Node Graph Reference for AI Agents

> 本文档供 AI agent 编写节点图 JSON 时参考（节点类型表、连线规则、执行模型、常见模式）。
> **按节读取（省 token）**: MCP `get_rules(section="<标题>")` / CLI `python -m Utils.User.NodeEditor.cli rules "<标题>"`;
> 无参只回目录（各节标题与规模）; 仅确需全文时才 `section="all"` / `--all`。

---

## JSON Structure

```json
{
  "version": "0.1.0",
  "nodes": { "<node_id>": { ... }, ... },
  "links": { "<link_id>": { ... }, ... },
  "next_id": <int>
}
```

- **nodes**: key 为 node ID 字符串, value 为 NodeInstance
- **links**: key 为 link ID 字符串, value 为 LinkInstance
- **next_id**: 1 + max(所有 node/link/pin ID), 确保无碰撞

### NodeInstance

```json
{
  "id": <int>,
  "node_type": "<type_name>",
  "pos": [<x>, <y>],
  "props": { <key>: <value>, ... },
  "pin_ids": { "<pin_name>": <int>, ... }
}
```

- `pin_ids`: 实例级唯一定义的 pin ID。所有连线引用这些 ID,而非类型模板的 PinDef ID。
- 事件节点 (OnGameStart/OnFrameUpdate/OnGameStop) 固定 ID: 161/163/166

### LinkInstance

```json
{
  "id": <int>,
  "from_pin": <int>,
  "to_pin": <int>
}
```

- `from_pin`: 必须是 output pin 的 ID
- `to_pin`: 必须是 input pin 的 ID

---

## Connection Rules

1. **exec → exec**, **data → data**, **never cross**
2. One output pin can fan out to **multiple** input pins
3. One input pin can only receive from **one** output pin
4. Event nodes have **no** input exec pins (they are graph roots)

---

## Execution Model

- **OnGameStart**: fires ONCE. Use for init.
- **OnFrameUpdate**: fires EVERY FRAME. Use for TimeTrigger, polling.
- **OnGameStop**: fires ONCE. Use for cleanup.
- **Exec chain**: depth-first traversal following exec output→input links.
- **Pure data nodes** (Constant, Compare, ScalarMath, Random, etc.): NO exec pins. Evaluated LAZILY when their output pin is read via a data link.
- **TimeTrigger**: fires when timer ≥ threshold. Re-arms only when threshold increases.
- **TimeDelay**: blocks exec chain until elapsed.
- **Branch**: walks True or False based on Condition data pin.
- **Variables** persist across frames. VarSet writes, VarGet reads.

---

## Node Type Reference

### Event (graph roots)
| type_name | output pins | notes |
|-----------|------------|-------|
| OnGameStart | exec | once at start |
| OnFrameUpdate | exec, delta(float) | every frame |
| OnGameStop | exec | once at stop |

### Flow
| type_name | input | output | props |
|-----------|-------|--------|-------|
| Sequence | exec_in | out_0..out_4 (exec) | — |
| Branch | exec_in, Condition(bool) | True, False (exec) | — |

### Math (pure data, no exec)
| type_name | input | output | props |
|-----------|-------|--------|-------|
| ScalarMath | In_0..In_7 (float) | Result | operation: sum/sub/mul/div |
| Compare | A,B (float) | Result(bool) | operation: gt/lt/eq/neq/gte/lte |
| Constant | — | Result(float) | value: float |
| RandomSetSeed | exec_in, exec_out, Seed(int) | (exec_out) | source: hardware/manual/pin |
| Random | Min,Max,Mean,StdDev | Result(float) | distribution: uniform/gaussian/discrete, mode: manual/pin |

### Time (✅ has timer support)
| type_name | input | output | props |
|-----------|-------|--------|-------|
| TimeGetElapsed | exec_in | exec_out, Elapsed(float) | timer: "" (global) or name |
| TimeTrigger | exec_in, Time(float) | Elapsed, out_0..out_7 (exec×8) | mode: manual/pin, time: float, **timer**: "" or name |
| TimeGetDate | — | DateString(string) | year/month/day/hour/minute: bool, format: str |
| NewTimer | exec_in, Name(string) | exec_out | mode: manual/pin, timer_name: str |
| SetTimer | exec_in, Value(float) | exec_out | operate: reset/set_time, mode: manual/pin, timer_name: str, value: float |

### Variable
| type_name | input | output | props |
|-----------|-------|--------|-------|
| VarSet | exec_in, Name(string), Value(var) | exec_out | mode: manual/pin, var_name, value |
| VarGet | exec_in, Name(string) | exec_out, Value(var) | var_name |

### Entity
| type_name | input | output | props |
|-----------|-------|--------|-------|
| EntitySpawn | exec_in | exec_out, Entity(ref) | template: string |
| EntityGet | exec_in, Name(string) | exec_out, Entity(ref) | entity_name: string |
| EntitySetRenderVisible | exec_in, EntityID(int), Visible(bool) | exec_out | — |
| EntityGroupSetVisible | exec_in, Entity1-4(ref, 可选), Visible(bool) | exec_out | — |
| SetText | exec_in, Entity(ref), Text(string) | exec_out | — |

多部件 cue（箭把+箭头等）显隐 MUST 用 `EntityGroupSetVisible`：同一批命令下发，
组内实体**同帧生效**（渲染帧边界不会把一组切成两半）；`EntitySetRenderVisible`
保留给单实体。
`SetText`：设置目标实体 `TextDisplay.text` 并立即重新光栅化（PIE）；目标实体需有
`TextDisplay` 组件（字号/颜色/粗斜体等样式在组件上，编辑器/MCP 可改）。

### IO
| type_name | input | output | props |
|-----------|-------|--------|-------|
| ParallelSend | exec_in, Address(int), Value(var) | exec_out | mode: manual/pin, address: int (0x3FF8 LPT1) |
| SerialSend | exec_in, Value(var) | exec_out | format: string/bytes, port, baud_rate |
| PathVar | — | Path(string) | browse_mode: directory/file, path |
| TextFileWrite | exec_in, FilePath, FileName, Value | exec_out | mode: pin, write_mode: w/a, delimiter |

### Gtec (g.HIamp EEG — IO ▸ Gtec)
| type_name | input | output | props |
|-----------|-------|--------|-------|
| InitGtecDevice | exec_in | exec_out | device: HIAMP, device_name, serial(""=auto), template: 64ch/128ch/144ch, sampling_rate: 256..38400, notch: off/50/60, filter_type: none/highpass/lowpass/bandpass, low_cut, high_cut (0 = unset), export_format: npz/csv, save_dir ("." = cwd), buffer_seconds |
| StartGtecRecord | exec_in | exec_out | device_name |
| StopGtecRecord | exec_in | exec_out | device_name, save_scope: session/buffer |
| KillGtecDevice | exec_in | exec_out | device_name |
| GetGtecData | — (pure data node) | Data(variant ndarray channels×samples), Channels(int), Samples(int), Fs(float) | device_name |

Gtec 规则 (MUST):
1. **InitGtecDevice 与 KillGtecDevice 强制成对出现** — 引擎校验静态检查会报错；
   编辑器删除任一侧会级联删除另一侧。Kill 与 Init 通过 device_name 绑定
   (Kill 的 device_name 为空且仅 1 个 Init 时自动绑定)。
2. Trigger 固定启用（16 条数字线合并为 1 个附加通道），无用户配置项。
3. 在线滤波: notch 独立选择；截止频率 = 0 表示"未填"→ 不生效；与 filter_type
   不匹配的字段被忽略（如 lowpass + low_cut 只生效 high_cut）。设备滤波器是离散预设，
   匹配不到预设时跳过并告警（不阻塞采集）。
4. 窗口缓冲: buffer_seconds × sampling_rate → (channels, N) float32，旧数据被新数据覆盖。
   GetGtecData 每次求值返回 (channels, N) 的非销毁副本（未填充区为 0），
   同时给出 Channels / Samples(有效样本数) / Fs。数组大小只取决于 Init 配置。
5. StopGtecRecord 保存: scope=session → 本次 Start 以来全部数据; scope=buffer → 仅当前窗口。
   目录与格式来自 Init（默认 "." 当前目录）；npz/csv + 同名 .json 元数据。
6. 无硬件 / MCP 干跑（validate_graph 设 max_frames>0）: 全部节点走确定性空跑后端 —
   不触硬件、不落盘、不起线程，干跑可复现。
7. device_name 为空 = 运行时注册表仅一个会话时自动绑定；多会话时必须显式指定。

### SigGen (虚拟信号发生器 — IO ▸ SigGen)
| type_name | input | output | props |
|-----------|-------|--------|-------|
| InitSigGenDevice | exec_in | exec_out | device_name, channels: 1..256, sampling_rate: 1..38400, frequency (Hz, ≤0=未填→10), freq_step (Hz/ch, ≥0), amplitude_uv (≥0), noise_uv (0=纯正弦), seed, export_format: npz/csv, save_dir ("." = cwd), buffer_seconds |
| StartSigGenRecord | exec_in | exec_out | device_name |
| StopSigGenRecord | exec_in | exec_out | device_name, save_scope: session/buffer |
| KillSigGenDevice | exec_in | exec_out | device_name |
| GetSigGenData | — (pure data node) | Data(variant ndarray channels×samples), Channels(int), Samples(int), Fs(float) | device_name |

SigGen 规则 (MUST):
1. **InitSigGenDevice 与 KillSigGenDevice 强制成对出现** — 与 Gtec 同一配对规则
   (引擎校验静态检查 + 编辑器删除级联; 绑定规则同 Gtec)。
2. 纯软件正弦源: 通道 i 频率 = frequency + i·freq_step Hz, 幅度 µV float32,
   noise_uv>0 时按 seed 叠加确定性高斯噪声 — 任意机器可跑, 无硬件依赖。
3. 窗口缓冲 / GetSigGenData / Stop 保存语义与 Gtec 完全一致 (§Gtec 规则 4/5/6)。
   区别: 真实模式 (非干跑) 会真正写出 npz/csv + .json 到 save_dir; 干跑不落盘。
4. Gtec 与 SigGen 共用同一设备会话注册表 — device_name 跨族必须唯一。

### Game
| type_name | input | output | notes |
|-----------|-------|--------|-------|
| ExitGame | exec_in | — | terminal, no output |

### Media (动态媒体 — GIF/图像)
| type_name | input | output | props |
|-----------|-------|--------|-------|
| ShowMedia | exec_in, Entity(entity_ref) | exec_out | — |

ShowMedia 规则 (MUST):
1. **编辑器侧编辑只是模板**（实体上 MediaPlayer 组件声明 source 等参数, 编辑器不播放）;
   播放必须由本节点在图中正确接线才生效（PIE / 独立运行）。
2. 目标实体: `Get Entity`(Name) → `Entity` ref → `ShowMedia.Entity`
   （Entity 引脚未连 → 引擎校验报 media_pin_unconnected）。
3. 驱动频率 = 接线频率: 挂 `OnFrameUpdate` 链 → 逐帧播放（推荐）;
   挂 OnGameStart → 只推首帧。exec_in 未连仅警告（media_exec_unconnected）。
4. 同一实体被多个 ShowMedia 驱动 → 引擎帧内自动去重（每帧只推进一次, 不加速）。
5. 媒体播放状态（帧号/时钟）不序列化; 场景只存 MediaPlayer.source 等模板参数。

### Debug
| type_name | input | output | props |
|-----------|-------|--------|-------|
| Print | exec_in, Value(var) | exec_out | — |
| PrintString | exec_in | exec_out | message: string |

---

## ID Allocation Convention

- Event nodes: **161, 163, 166** (fixed)
- User nodes: start from **200**
- Pin IDs: start from **10000**
- Link IDs: start from **500**

---

## build_graph Spec

`build_graph`（MCP）/ `build`（CLI）从**实验描述 spec** 自动生成整张图（OnGameStart
初始化链 + OnFrameUpdate 计时/分支链）:

```json
{
  "seed_dir": "Test/.../seed",
  "seed_prefix": "MI-Seed",
  "init_delay": 5.0,
  "trials": 60,
  "timer": "trial_phase",
  "phases": [
    {"time": 0, "type": "cue_pick",
     "random": {"min": 1, "max": 2},
     "branches": [
       {"value": 1, "show": ["L_arrow_body", "L_arrow_head"], "parallel": 11},
       {"value": 2, "show": ["R_arrow_head", "R_arrow_body"], "parallel": 12}
     ]},
    {"time": 2, "show": ["TaskCue"]},
    {"time": 6, "hide": ["L_arrow_body", "L_arrow_head", "R_arrow_head", "R_arrow_body", "TaskCue"]},
    {"time": 10, "type": "trial_end"}
  ],
  "entities": ["Cross", "LeftCue", "RightCue", "TaskCue"],
  "pulse": null
}
```

- `phases[].type`: `cue_pick`（随机分支 + show + 并行口触发） / `action|show` / `trial_end`（trial 计数 + 复位 timer）;
- `pulse`（可选）: `{count, interval, timer, parallel_addr, serial_port, encode}` — 50ms 发送循环;
- `entities[]` 先 spawn 后统一隐藏，由 phases 显隐控制；seed 链固定串在 OnGameStart 上;
- CLI 等价: `python -m Utils.User.NodeEditor.cli build --spec spec.json --out graph.json`（--out 落盘只回摘要）。

---

## Common Patterns

### 1. Timer-driven trial experiment
```
OnGameStart → seed → spawn → hide → VarSet(trial) → NewTimer("phase") → SetTimer(-delay)
OnFrameUpdate → Sequence → TimeTrigger×4 (timer="phase", time=0,2,6,10)
  TT0 → cue pick + show + send
  TT2 → show TaskCue
  TT6 → hide all
  TT10 → trial++ → Branch(trial>60) → ExitGame / SetTimer(reset)
```

### 2. 50ms pulse loop
```
OnFrameUpdate → Sequence → TTPulse (timer="pulse", time=0)
  → VarGet("count") → Compare(lt, 80) → Branch
    True  → send → inc count → SetTimer("pulse", -0.05)
    False → (stop)
Start: VarSet("count", 0) → SetTimer("pulse", -0.05)
```

### 3. Cue visibility toggle
```
EntityGet("entity_name") → EntitySetRenderVisible
  Entity.Get → EntitySet.EntityID
  Constant(0 or 1) → EntitySet.Visible
```

### 4. Binary random pick
```
Random(min=1, max=2, discrete) → Compare(eq, 1) → Branch
  True → (chain A)
  False → (chain B)
```

### 5. MI×SSSEP encoding (trigger = MI<<6 | SSSEP)
```
Constant(MI<<6) → ScalarMath(sum, In_0)
VarGet("sss_code") → ScalarMath(sum, In_1)
ScalarMath.Result → VarSet("trigger_val", mode=pin)
```

---

## Validation

- **引擎运行中（推荐）**: 引擎内校验服务 — Node Editor ▸ Validate 按钮 /
  `engine_validate_graph`（editor MCP, lite 档）/ `engine-editor-cli validate`（终端;
  `--source graph` 可先验 agent 生成的图，不用先导入画布）。
- **无头 / CI**: `PlayerEntry --dry-run` 或 `Test/Application/NodeGraph/test_graph_validation.py`。
- 旧离线路径说明（2026-10-05）: 本 MCP 的 `validate_graph` 工具已移除；
  `node_graph_validator.py` / `GraphBuilder.validate()` 仅供旧脚本与单元测试复用，不再是推荐入口 —
  校验的单一事实源是引擎内服务（`Doc/Dev/graph_validation_protocol.md`）。
