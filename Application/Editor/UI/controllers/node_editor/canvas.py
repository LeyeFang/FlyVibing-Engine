"""
节点编辑器 — 画布状态管理 (NodeCanvas)。

管理节点实例与连线的 CRUD、pin 查找、默认节点创建。
"""

from __future__ import annotations

from typing import Optional

from .data_model import NodeInstance, LinkInstance, _gen_id
from .node_types import _TYPES
from . import data_model  # 用于访问 _next_id


# ═══════════════════════════════════════════════════════════════
# Agent 提示词 — 每次导出 scene 时附带此规则文档
# ═══════════════════════════════════════════════════════════════

_NODE_GRAPH_RULES = """## Node Graph JSON Reference (v0.1.0)

### JSON Structure
The node_graph is a JSON object with these keys:
- "version": "0.1.0"
- "nodes": { "<nid>": {NodeInstance}, ... }  — nid is globally unique int (string key)
- "links": { "<lid>": {LinkInstance}, ... }  — lid is globally unique int (string key)
- "next_id": int — 1 + max(all node/link/pin IDs), ensures no collision on future additions
- "_rules": "<this document>"

### NodeInstance Format
  "id": <int>, "node_type": "<type_name>", "pos": [<x>, <y>],
  "props": {<key>: <value>, ...},  — mode-dependent props (see per-node table)
  "pin_ids": {"<pin_name>": <int>, ...}  — instance-level unique pin IDs

### LinkInstance Format
  "id": <int>, "from_pin": <int> (output pin ID), "to_pin": <int> (input pin ID)

### Pin IDs
Every node has a pin_ids dict mapping logical pin name → instance-unique integer.
All links reference these instance-level IDs, NOT template-level PinDef IDs.
When writing a graph, assign pin IDs sequentially starting from a high base (e.g., nid*10).

### Connection Rules (CRITICAL)
1. exec pins connect exec→exec: output exec pin → input exec pin
2. data pins connect data→data: output data pin → input data pin
3. NEVER connect exec→data or data→exec
4. One output pin can fan out to multiple input pins (both exec and data)
5. An input pin can only receive from ONE output pin
6. Event nodes (OnGameStart/OnFrameUpdate/OnGameStop) have NO input exec pins — they are graph roots

### Execution Model
- OnGameStart: fires ONCE when the game begins. Use for initialization (set variables, spawn entities).
- OnFrameUpdate: fires EVERY FRAME. Use for per-frame checks (TimeTrigger, input polling).
- OnGameStop: fires ONCE when the game ends. Use for cleanup.
- Exec chain: _walk_exec follows exec output→input links depth-first.
- Data nodes (Constant, Compare, ScalarMath, MakeVec3, BreakVec3, VecMath, Random, legacy math):
  NO exec pins. Evaluated LAZILY when their output pin is read via a data link.
- Mixed nodes (VarGet): have BOTH exec_in and data output pins. Exec triggers read; data output
  is then available for downstream data links. When data-read without exec context, lazy-eval works too.
- _blocked pattern: TimeDelay and TimeTrigger set _blocked=True to pause exec chain.
  Branch sets _blocked=True after manually walking the matching branch.
- Variable store: ctx._variables persists across frames. VarSet writes, VarGet reads.
  Variables are NOT cleared between triggers — use them for state (counters, timers).

### Pin Naming Convention
- exec_in / exec_out: execution flow pins
- out_0..out_7: Sequence or TimeTrigger multi-output exec pins
- Data pins have descriptive names: Value, Result, A, B, X, Y, Z, In_0..In_7, etc.
- Pin direction is determined by the node type definition (see tables below)

---

### NODE TYPE REFERENCE

#### Event Nodes (graph roots — no input pins)
| type_name      | output pins                  | notes                            |
|----------------|------------------------------|----------------------------------|
| OnGameStart    | exec (exec)                  | fires once at game start         |
| OnFrameUpdate  | exec (exec), delta (float)   | fires every frame                |
| OnGameStop     | exec (exec)                  | fires once at game stop          |

#### Flow Nodes
| type_name | input pins              | output pins               | props              |
|-----------|-------------------------|---------------------------|--------------------|
| Sequence  | exec_in (exec)          | out_0,out_1,out_2 (exec) | —                  |
| Branch    | exec_in,Condition(bool) | True,False (exec)         | —                  |

#### Math Nodes (pure data — no exec pins)
| type_name      | input pins                    | output pins    | props                        |
|----------------|-------------------------------|----------------|------------------------------|
| ScalarMath     | In_0..In_7 (float)           | Result (float) | operation: sum/sub/mul/div   |
| Compare        | A (float), B (float)          | Result (bool)  | operation: gt/lt/eq/neq/gte/lte |
| MathAdd        | A,B (float)                   | Result (float) | — (legacy, hidden)           |
| MathSubtract   | A,B (float)                   | Result (float) | — (legacy, hidden)           |
| MathMultiply   | A,B (float)                   | Result (float) | — (legacy, hidden)           |
| MathDivide     | A,B (float)                   | Result (float) | — (legacy, hidden)           |
| RandomSetSeed  | exec_in,exec_out,Seed(int)   | (exec_out)     | mode: manual/pin, seed: int  |
| Random         | Min,Max,Mean,StdDev (float)   | Result (float) | distribution: uniform/gaussian/discrete, mode: manual/pin |
| MathRandomUniform  | Min,Max (float)           | Result (float) | — (legacy, hidden)           |
| MathRandomGaussian | Mean,StdDev (float)       | Result (float) | — (legacy, hidden)           |
| MakeVec3       | X,Y,Z (float)                 | Vec3 (vec3)    | —                            |
| BreakVec3      | Vec3 (vec3)                   | X,Y,Z (float)  | —                            |
| VecMath        | A,B (vec3)                    | Result(var)   | operation: add/sub/mul/div/dot/cross/normalize/length |

#### Time Nodes
| type_name      | input pins               | output pins                    | props                  |
|----------------|--------------------------|--------------------------------|------------------------|
| TimeGetElapsed | exec_in (exec)           | exec_out (exec), Elapsed(float)| —                      |
| TimeGetDelta   | exec_in (exec)           | exec_out (exec), Delta(float)  | —                      |
| TimeDelay      | exec_in,Seconds(float)   | exec_out (exec)                | —                      |
| TimeTrigger    | exec_in,Time(float)      | Elapsed(float), out_0..out_7(exec×8) | mode: manual/pin, time: float |

TimeTrigger behavior: fires when ctx.elapsed_time >= threshold. Re-armable: increasing the threshold via variable/pin allows repeated triggering. Tracks _last_fired_threshold in state.

#### Variable Nodes
| type_name | input pins                    | output pins             | props                          |
|-----------|-------------------------------|-------------------------|--------------------------------|
| VarSet    | exec_in,Name(string),Value(var)| exec_out (exec)        | mode: manual/pin, var_name, value |
| VarGet    | exec_in,Name(string)          | exec_out,Value(var)     | var_name                       |
| Constant  | —                             | Result (float)          | value: float                   |
| StringConst| —                            | Value (string)          | value: string                  |

VarSet manual mode: Name from textbox prop, Value from props.value.
VarSet pin mode: Name from upstream link, Value from upstream link.
VarGet: reads ctx.get_var(name) and writes to Value output.

#### Entity Nodes
| type_name             | input pins                                  | output pins          | props            |
|-----------------------|---------------------------------------------|----------------------|------------------|
| EntitySpawn           | exec_in (exec)                              | exec_out,Entity(ref) | template: string |
| EntityDestroy         | exec_in,EntityID(int)                       | exec_out             | —                |
| EntityGet             | exec_in,Name(string)                        | exec_out,Entity(ref) | —                |
| EntityAddMesh         | exec_in,EntityID,MeshID,MaterialID (int)    | exec_out             | —                |
| EntityAddCamera       | exec_in,EntityID (int)                      | exec_out             | —                |
| EntitySetRenderVisible| exec_in,EntityID(int),Visible(bool)         | exec_out             | —                |

EntitySpawn: creates entity from Scene.entities template (dropdown). Recursively spawns children.
EntityRef: type-safe wrapper with is_valid property. Output as entity_ref on data pins.

#### Game Nodes
| type_name    | input pins                  | output pins | notes                    |
|--------------|-----------------------------|-------------|--------------------------|
| CameraSetMain| exec_in,Entity(entity_ref)  | exec_out    | sets scene_camera_id     |
| ExitGame     | exec_in                     | —           | terminal node, no output |

#### Component Nodes
| type_name      | input pins                                    | output pins | props             |
|----------------|-----------------------------------------------|-------------|-------------------|
| ComponentAdd   | exec_in,Entity(ref),Position,Rotation,Scale(vec3),MeshID,MaterialID(int),Visible(bool) | exec_out | mode, component, per-prop enabled |
| ComponentRemove| exec_in,Entity(ref)                           | exec_out | component (dropdown) |
| SetComponent   | exec_in,Entity(ref),Position,Rotation,Scale(vec3),MeshID,MaterialID(int),Visible(bool) | exec_out | mode, component, per-prop enabled |
| GetComponent   | exec_in,Entity(ref)                           | exec_out, Position,Rotation,Scale(vec3),MeshID,MaterialID(int),Visible(bool) | component (dropdown) |

Property pins use _SKIP sentinel: unconnected (pin mode) or unchecked (manual mode) → property not modified.

#### Debug Nodes
| type_name   | input pins           | output pins | props           |
|-------------|----------------------|-------------|-----------------|
| Print       | exec_in,Value(var)   | exec_out    | —               |
| PrintString | exec_in              | exec_out    | message: string |

#### IO Nodes
| type_name    | input pins                              | output pins | props                                      |
|--------------|-----------------------------------------|-------------|--------------------------------------------|
| SerialSend   | exec_in,Port(string),BaudRate(int),Value(var) | exec_out | mode: manual/pin, format: string/bytes, port, baud_rate, value |
| ParallelSend | exec_in,Address(int),Value(var)        | exec_out | mode: manual/pin, address: int (0x3FF8 LPT1, 0x3FF0 LPT2, 0x3FE8 LPT3), value: 1-255 |
| PathVar      | —                                      | Path (string) | browse_mode: directory/file, path: string |
| TextFileWrite| exec_in,FilePath(string),FileName(string),Value(var) | exec_out | mode: manual/pin, write_mode: w/a, delimiter: none/space/newline/tab/comma, file_path, file_name, value |

SerialSend format "string"→UTF-8, "bytes"→float32 LE 4 bytes. ParallelSend always sends uint8 (1-255, 0 reserved for auto-reset after 5ms).
PathVar outputs a directory or file path selected via OS file browser. browse_mode=directory uses select_folder, browse_mode=file uses open_file (.txt/.csv/.log/.json).
TextFileWrite writes str(value) + delimiter to {file_path}/{file_name}.txt. FileName auto-appends .txt suffix. Directory created if missing. write_mode="w" overwrites, "a" appends. Delimiter appended after each write: none="", space=" ", newline="\\n", tab="\\t", comma=",".
FilePath is always handled by widget (Browse button); pin connection overrides widget value.

---

### COMMON PATTERNS

#### Pattern 1: Timer + Repeated Action (e.g., send every 1s, 10 times then exit)
```
OnGameStart → VarSet(counter=0, mode=manual) → VarSet(next_time=1.0, mode=manual)
OnFrameUpdate → VarGet("next_time") → TimeTrigger(mode=pin, Time←VarGet.Value)
TimeTrigger.out_0 → SerialSend/ParallelSend → VarGet("counter") → ScalarMath(sum:+1) → VarSet("counter", mode=pin)
  → VarGet("next_time") → ScalarMath(sum:+1) → VarSet("next_time", mode=pin)
  → Branch(exec_in, Condition←Compare(A←ScalarMath.Result, B←Constant(10), gte))
  Branch.True → ExitGame
```
Key: TimeTrigger re-arms because next_time increases each fire. Compare.A uses ScalarMath(counter+1).Result directly (no need for a second VarGet).

#### Pattern 2: OnFrameUpdate per-frame action (no timer)
```
OnFrameUpdate → TimeGetElapsed → Print(Value←TimeGetElapsed.Elapsed)
```

#### Pattern 3: Spawn entity on start
```
OnGameStart → EntitySpawn(template="MyEntity") → ...
```

#### Pattern 4: Conditional branch
```
... → VarGet("some_var") → Compare(A←VarGet.Value, B←Constant(threshold), gte)
  → Branch(Condition←Compare.Result) → True: ... / False: ...
```
Note: Branch needs exec_in from the chain. The Condition is a data link from Compare.Result.
The exec_in usually comes from VarGet.exec_out (the VarGet that fed Compare.A).

#### Pattern 5: Parallel port trigger (EEG/SSVEP)
```
OnFrameUpdate → VarGet("next_time") → TimeTrigger(mode=pin) → ParallelSend(Address=0x3FF8, Value=1)
  → VarGet("counter") → ScalarMath(sum) → VarSet("counter", mode=pin)
  → VarGet("next_time") → ScalarMath(sum) → VarSet("next_time", mode=pin)
  → Branch(Condition←Compare(A←ScalarMath.Result, B←Constant(N), gte)) → ExitGame
```

#### Pattern 6: Write to text file (logging experiment data)
```
OnGameStart → VarSet(trial=1, mode=manual) → VarSet(max_trials=10, mode=manual)
OnFrameUpdate → VarGet("next_time") → TimeTrigger(mode=pin)
  TimeTrigger.out_0 → TextFileWrite(
      mode=pin,
      write_mode="a", delimiter="newline",
      FilePath←PathVar(browse_mode=directory, path="D:/Data/"),
      FileName←StringConst(value="experiment_log"),  // → experiment_log.txt
      Value←VarGet("trial").Value
    )
  → VarGet("trial") → ScalarMath(sum:+1) → VarSet("trial", mode=pin)
  → Branch(Condition←Compare(A←ScalarMath.Result, B←VarGet("max_trials").Value, gte))
  Branch.True → ExitGame
```
Key: TextFileWrite creates the directory and file automatically. FileName "experiment_log" becomes "experiment_log.txt".
Use StringConst for static strings, VarGet for dynamic values (but note VarGet returns float — use StringConst for file names).
PathVar provides a reusable directory path that can fan out to multiple TextFileWrite nodes.

---

### WRITING A GRAPH — STEP BY STEP

1. Plan the exec flow: which event nodes trigger what chains.
2. Assign node IDs starting from 200 (reserve 151-199 for default event nodes).
3. For each node, assign pin IDs. Use a scheme like node_id*10+0, node_id*10+1, ... for clarity.
4. Write nodes dict with correct node_type, pin_ids mapping, and props.
5. Write links dict: exec links first (to establish execution order), then data links.
6. Compute next_id = 1 + max(all node IDs, pin IDs, link IDs).
7. Always include the 3 default event nodes (OnGameStart, OnFrameUpdate, OnGameStop).
8. Pure data nodes (Constant, Compare, ScalarMath, etc.) have NO exec pins — only connect them via data links.
9. Use VarGet/Constant → ScalarMath/Compare → VarSet for arithmetic on variables.
10. For repeated TimeTrigger: feed a variable into TimeTrigger.Time pin, increment that variable after each fire."""


class NodeCanvas:
    """节点画布 — 管理节点实例与连线"""

    def __init__(self):
        self._nodes: dict[int, NodeInstance] = {}
        self._links: dict[int, LinkInstance] = {}

    # ── 属性 ──────────────────────────────────────────────

    @property
    def nodes(self) -> dict[int, NodeInstance]:
        return self._nodes

    @property
    def links(self) -> dict[int, LinkInstance]:
        return self._links

    # ── 节点 CRUD ──────────────────────────────────────────

    def add_node(self, type_name: str, pos: tuple[float, float]) -> int:
        """添加一个节点实例，返回其 ID。

        为每个 pin 生成实例级唯一 ID（存于 inst.pin_ids），
        避免同类型多节点时 PinId 冲突导致 imgui_node_editor 内部混乱。
        """
        if type_name not in _TYPES:
            return -1
        nid = _gen_id()
        nd = _TYPES[type_name]
        pin_ids = {p.name: _gen_id() for p in nd.pins}
        self._nodes[nid] = NodeInstance(nid, type_name, pos, pin_ids=pin_ids)
        return nid

    def remove_node(self, nid: int) -> None:
        """删除节点及其关联的连线"""
        if nid not in self._nodes:
            return
        inst = self._nodes[nid]
        node_pins = set(inst.pin_ids.values())
        to_del = [
            lid for lid, lk in self._links.items()
            if lk.from_pin in node_pins or lk.to_pin in node_pins
        ]
        for lid in to_del:
            del self._links[lid]
        del self._nodes[nid]

    def add_link(self, from_pin: int, to_pin: int) -> int:
        """添加一条连线，返回连线 ID（重复返回 -1）"""
        for lk in self._links.values():
            if (lk.from_pin == from_pin and lk.to_pin == to_pin) or \
               (lk.from_pin == to_pin and lk.to_pin == from_pin):
                return -1
        lid = _gen_id()
        self._links[lid] = LinkInstance(lid, from_pin, to_pin)
        return lid

    def remove_link(self, lid: int) -> None:
        self._links.pop(lid, None)

    # ── Pin 查找 ───────────────────────────────────────────

    def find_pin_dir(self, pin_id: int) -> Optional[str]:
        """查找实例级 Pin 的方向 ("input" / "output")"""
        for inst in self._nodes.values():
            nd = _TYPES.get(inst.node_type)
            if nd:
                for p in nd.pins:
                    if inst.pin_ids.get(p.name) == pin_id:
                        return p.direction
        return None

    def find_pin_node(self, pin_id: int) -> Optional[int]:
        """查找实例级 Pin 所属的节点 ID"""
        for nid, inst in self._nodes.items():
            nd = _TYPES.get(inst.node_type)
            if nd:
                for p in nd.pins:
                    if inst.pin_ids.get(p.name) == pin_id:
                        return nid
        return None

    def find_pin_name(self, pin_id: int) -> Optional[str]:
        """查找实例级 Pin 的名称 (如 "Value", "exec_in")"""
        for inst in self._nodes.values():
            nd = _TYPES.get(inst.node_type)
            if nd:
                for p in nd.pins:
                    if inst.pin_ids.get(p.name) == pin_id:
                        return p.name
        return None

    # ── 默认节点 ───────────────────────────────────────────

    def create_default_nodes(self) -> None:
        """创建必要的初始节点 — 仅 3 个事件入口。

        OnGameStart  → 图执行入口
        OnFrameUpdate → 逐帧入口
        OnGameStop   → 清理入口

        其余所有节点通过 Add 菜单按需创建。
        """
        essential = ["OnGameStart", "OnFrameUpdate", "OnGameStop"]
        for i, tn in enumerate(essential):
            if tn in _TYPES:
                nid = _gen_id()
                nd = _TYPES[tn]
                pin_ids = {p.name: _gen_id() for p in nd.pins}
                self._nodes[nid] = NodeInstance(
                    nid, tn, (80, 80 + i * 200), pin_ids=pin_ids,
                )

    # ── 序列化 ───────────────────────────────────────────

    def to_dict(self) -> dict:
        """序列化画布状态为纯 dict（可 JSON 导出）。

        Returns:
            {
                "version": "0.1.0",
                "nodes": {str(nid): {...}, ...},
                "links": {str(lid): {...}, ...},
                "next_id": int,
            }
        """
        import dataclasses

        # 收集所有已分配的 ID，确定 next_id 下界
        max_id = 1
        nodes_dict: dict[str, dict] = {}
        for nid, inst in self._nodes.items():
            nd = dataclasses.asdict(inst)
            nodes_dict[str(nid)] = nd
            max_id = max(max_id, nid)
            for pid in inst.pin_ids.values():
                max_id = max(max_id, pid)

        links_dict: dict[str, dict] = {}
        for lid, lk in self._links.items():
            links_dict[str(lid)] = dataclasses.asdict(lk)
            max_id = max(max_id, lid, lk.from_pin, lk.to_pin)

        return {
            "version": "0.1.0",
            "nodes": nodes_dict,
            "links": links_dict,
            "next_id": max_id + 1,
            "_rules": _NODE_GRAPH_RULES,
        }

    @staticmethod
    def from_dict(data: dict) -> 'NodeCanvas':
        """从 dict 恢复画布状态。

        Args:
            data: to_dict() 的输出

        Returns:
            新的 NodeCanvas 实例
        """
        global _next_id
        canvas = NodeCanvas()

        # ── 恢复节点 ──
        for nid_str, nd in data.get("nodes", {}).items():
            nid = int(nid_str)
            canvas._nodes[nid] = NodeInstance(
                id=nid,
                node_type=nd["node_type"],
                pos=tuple(nd.get("pos", (0.0, 0.0))),
                props=nd.get("props", {}),
                pin_ids={k: int(v) for k, v in nd.get("pin_ids", {}).items()},
            )

        # ── 恢复连线 ──
        for lid_str, ld in data.get("links", {}).items():
            lid = int(lid_str)
            canvas._links[lid] = LinkInstance(
                id=lid,
                from_pin=int(ld["from_pin"]),
                to_pin=int(ld["to_pin"]),
            )

        # ── 恢复 ID 生成器 ──
        data_model._next_id = max(data_model._next_id, data.get("next_id", 1))

        return canvas

    def clear(self) -> None:
        """清空画布（保留 _next_id 不重置）。"""
        self._nodes.clear()
        self._links.clear()
