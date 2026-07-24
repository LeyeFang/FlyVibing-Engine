# Node Graph Reference for AI Agents

> 本文档供 AI agent 编写节点图 JSON 时参考。
> 包含完整的节点类型表、连线规则、执行模型和常见模式。

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

### IO
| type_name | input | output | props |
|-----------|-------|--------|-------|
| ParallelSend | exec_in, Address(int), Value(var) | exec_out | mode: manual/pin, address: int (0x3FF8 LPT1) |
| SerialSend | exec_in, Value(var) | exec_out | format: string/bytes, port, baud_rate |
| PathVar | — | Path(string) | browse_mode: directory/file, path |
| TextFileWrite | exec_in, FilePath, FileName, Value | exec_out | mode: pin, write_mode: w/a, delimiter |

### Game
| type_name | input | output | notes |
|-----------|-------|--------|-------|
| ExitGame | exec_in | — | terminal, no output |

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

```bash
# Static check
python Utils/Validators/node_graph_validator.py <scene_path>

# Static + dry-run N frames
python Utils/Validators/node_graph_validator.py <scene_path> --frames N

# Programmatic
from Utils.NodeEditor.graph_builder import GraphBuilder
g = GraphBuilder()
# ...build graph...
report = g.validate(max_frames=37000)
print(report.passed, report.dry_run)
g.save("scenes/MyScene.scene")
```
