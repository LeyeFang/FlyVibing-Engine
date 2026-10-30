"""1 Hz pulse pipeline — shared template used by the examples and by the live applier.

一个「每秒发一个码、1..N 循环」的最小可运行流水线：

    OnGameStart -> Spawn(template) -> reset index -> NewTimer -> arm timer(-period)
    OnFrameUpdate -> Sequence -> TimeTrigger(timer@0)
        -> Branch(next > max)
             True  -> index = 1     -> send(index) -> re-arm timer
             False -> index = next  -> send(index) -> re-arm timer

为什么这样设计：

- **只有一个发送节点**（SerialSend 或 ParallelSend），设备参数（端口/波特率/地址）
  只存在一处；改设备不需要在一堆节点里找。
- 计数用变量 `pulse_index` + `Compare`/`Branch` 回绕，不依赖任何未安装的节点。
- 定时用命名 Timer + `SetTimer(-period)` 重新武装；`TimeTrigger` 自己会在 timer
  回绕时重新触发，因此周期由 `--period` 控制。

节点身份（用于「覆写已有节点」）：

- 每个流水线节点的 `description` 以 `[pulse:<tag>:<slot>]` 开头。
  再次运行 applier 时按这个前缀找到同一批节点并**复用其 node id**，
  因此面板里改过的属性、位置、连线都保留，不会被复制出一份新的。
- `--overwrite` 表示「用模板值覆盖所有模板属性」；默认**只同步你在命令行显式给出的参数**
  （例如只给 `port=COM7` 就只改 port），其它面板改动（包括你自己加的 props）保持不动。

本模块是**纯数据 + 纯函数**，既被 `build_examples`（离线生成 .scene）使用，
也被 `apply_pulse_pipeline.py`（实时 op 流程）使用。
"""

from __future__ import annotations

import re
from typing import Any

KIND_SERIAL = "serial"
KIND_PARALLEL = "parallel"

DEFAULT_TAG = "pulse"
DEFAULT_PORT = "@mydevice"
DEFAULT_BAUD = 9600
DEFAULT_FORMAT = "string"
DEFAULT_ADDRESS = 0x3FF8
DEFAULT_PERIOD = 1.0
DEFAULT_MAX = 10

# description 前缀: [pulse:<tag>:<slot>]
_TAG_RE = re.compile(r"^\[pulse:([^:\]]+):([^\]]+)\]")

# 每个 slot 出现的位置（仅影响可读性，不影响语义）
_POS = {
    "start": (0.0, 0.0),
    "spawn": (220.0, 0.0),
    "reset_index": (440.0, 0.0),
    "tick_timer": (660.0, 0.0),
    "arm": (880.0, 0.0),
    "frame": (0.0, 240.0),
    "seq": (200.0, 240.0),
    "tt": (400.0, 240.0),
    "branch": (1060.0, 240.0),
    "read": (420.0, 460.0),
    "one": (420.0, 580.0),
    "add": (660.0, 460.0),
    "max": (660.0, 580.0),
    "cmp": (880.0, 460.0),
    "read2": (1180.0, 860.0),
    "wrap_set": (1060.0, 640.0),
    "inc_set": (1060.0, 760.0),
    "send": (1300.0, 700.0),
    "rearm": (1520.0, 700.0),
}

# (from_slot, from_pin, to_slot, to_pin)
_LINKS = [
    ("start", "exec", "spawn", "exec_in"),
    ("spawn", "exec_out", "reset_index", "exec_in"),
    ("reset_index", "exec_out", "tick_timer", "exec_in"),
    ("tick_timer", "exec_out", "arm", "exec_in"),
    ("frame", "exec", "seq", "exec_in"),
    ("seq", "out_0", "tt", "exec_in"),
    ("tt", "out_0", "branch", "exec_in"),
    ("branch", "True", "wrap_set", "exec_in"),
    ("branch", "False", "inc_set", "exec_in"),
    ("wrap_set", "exec_out", "send", "exec_in"),
    ("inc_set", "exec_out", "send", "exec_in"),
    ("send", "exec_out", "rearm", "exec_in"),
    ("read", "Value", "add", "In_0"),
    ("one", "Result", "add", "In_1"),
    ("add", "Result", "cmp", "A"),
    ("max", "Result", "cmp", "B"),
    ("cmp", "Result", "branch", "Condition"),
    ("one", "Result", "wrap_set", "Value"),
    ("add", "Result", "inc_set", "Value"),
    ("read2", "Value", "send", "Value"),
]


def normalize_kind(kind: str) -> str:
    k = str(kind or "").strip().lower()
    if k in ("serial", "com", "串口"):
        return KIND_SERIAL
    if k in ("parallel", "lpt", "并口"):
        return KIND_PARALLEL
    raise ValueError(f"unknown pipeline kind: {kind!r} (use 'serial' or 'parallel')")


def tag_prefix(tag: str, slot: str) -> str:
    return f"[pulse:{tag}:{slot}]"


def parse_tag(description: str) -> tuple[str, str] | None:
    """Return (tag, slot) if the description carries a pipeline marker."""
    m = _TAG_RE.match(str(description or ""))
    if not m:
        return None
    return m.group(1), m.group(2)


def build_spec(kind: str = KIND_SERIAL, *, tag: str = DEFAULT_TAG,
               port: str = DEFAULT_PORT, baud: int = DEFAULT_BAUD,
               fmt: str = DEFAULT_FORMAT, address: int = DEFAULT_ADDRESS,
               period: float = DEFAULT_PERIOD, max_value: int = DEFAULT_MAX,
               template: str = "Cross") -> dict[str, Any]:
    """Build the pipeline description (nodes + links), independent of any engine.

    Returns ``{"kind", "tag", "nodes": [...], "links": [...], "params": {...}}``
    where each node carries ``slot/type/props/description/pos/sync``:

    - ``props``: full template properties (used by ``--overwrite`` and by the scene builder)
    - ``sync``:  the subset always re-applied on a later run (device/timing parameters)
    """
    kind = normalize_kind(kind)
    tag = str(tag or DEFAULT_TAG).strip() or DEFAULT_TAG
    period = float(period)
    if period <= 0:
        raise ValueError("period must be > 0")
    max_value = max(1, int(max_value))

    def node(slot: str, type_name: str, props: dict, text: str,
             sync: dict | None = None) -> dict:
        """``sync`` maps prop key -> CLI param name (used to filter incremental updates)."""
        return {
            "slot": slot,
            "type": type_name,
            "props": dict(props),
            "sync": dict(sync if sync is not None else {}),
            "description": f"{tag_prefix(tag, slot)} {text}",
            "pos": _POS.get(slot, (0.0, 0.0)),
        }

    timer = "pulse_tick"
    var = "pulse_index"
    want_spawn = str(template).strip().lower() not in ("", "none", "-", "off")

    nodes = [
        node("start", "OnGameStart", {},
             "Entry: spawn the cue template, reset the counter, arm the 1 Hz timer."),
    ]
    if want_spawn:
        nodes.append(node("spawn", "EntitySpawn", {"template": str(template)},
                          f"Spawn the '{template}' template so PIE/player renders something."))
    nodes.extend([
        node("reset_index", "VarSet",
             {"mode": "manual", "var_name": var, "value": 0},
             f"Start the counter at 0 (first pulse sends 1)."),
        node("tick_timer", "NewTimer",
             {"mode": "manual", "timer_name": timer},
             f"Create the named timer '{timer}' (period = 1 s)."),
        node("arm", "SetTimer",
             {"operate": "set_time", "mode": "manual",
              "timer_name": timer, "value": -period},
             f"Arm the timer: next pulse in {period:g} s.",
             sync={"value": "period"}),
        node("frame", "OnFrameUpdate", {},
             "Per-frame tick: evaluate the timer gate."),
        node("seq", "Sequence", {},
             "Fan-out placeholder (keeps the frame entry tidy / room for more gates)."),
        node("tt", "TimeTrigger",
             {"mode": "manual", "timer": timer, "time": 0},
             "Gate: fires when the timer reaches 0 (i.e. every period)."),
        node("read", "VarGet", {"var_name": var},
             "Read the current counter value (old value, before increment)."),
        node("one", "Constant", {"value": 1.0},
             "Step size / wrap target = 1."),
        node("add", "ScalarMath", {"operation": "sum"},
             "next = index + 1."),
        node("max", "Constant", {"value": float(max_value)},
             f"Upper bound of the cycle ({max_value}).",
             sync={"value": "max_value"}),
        node("cmp", "Compare", {"operation": "gt"},
             "next > max ? wrap : continue."),
        node("branch", "Branch", {},
             "Wrap branch: True -> reset to 1, False -> keep next."),
        node("wrap_set", "VarSet",
             {"mode": "pin", "var_name": var},
             "Wrap: counter = 1."),
        node("inc_set", "VarSet",
             {"mode": "pin", "var_name": var},
             "Advance: counter = next."),
        node("read2", "VarGet", {"var_name": var},
             "Read the counter after the write — this is the value that gets sent."),
        node("rearm", "SetTimer",
             {"operate": "set_time", "mode": "manual",
              "timer_name": timer, "value": -period},
             f"Re-arm the timer for the next pulse ({period:g} s).",
             sync={"value": "period"}),
    ])

    if kind == KIND_SERIAL:
        nodes.append(node(
            "send", "SerialSend",
            {"port": str(port), "baud_rate": int(baud), "format": str(fmt)},
            "Send the pulse value over serial (ONE device node — change it here).",
            sync={"port": "port", "baud_rate": "baud", "format": "format"},
        ))
    else:
        nodes.append(node(
            "send", "ParallelSend",
            {"mode": "pin", "address": int(address)},
            "Write the pulse value to the parallel port (ONE device node — change it here).",
            sync={"address": "address"},
        ))

    params = {
        "kind": kind, "tag": tag, "port": str(port), "baud": int(baud),
        "format": str(fmt), "address": int(address), "period": period,
        "max_value": max_value, "template": str(template),
        "spawn": want_spawn,
    }
    slots = {item["slot"] for item in nodes}
    links = [lk for lk in _LINKS if lk[0] in slots and lk[2] in slots]
    if not want_spawn:
        # start -> spawn -> reset_index 变成 start -> reset_index
        links = [lk for lk in links if "spawn" not in (lk[0], lk[2])]
        links.insert(0, ("start", "exec", "reset_index", "exec_in"))
    return {"kind": kind, "tag": tag, "nodes": nodes, "links": links, "params": params}


# ── 实时（op）侧 ──────────────────────────────────────────────

def scan_pipeline(graph_list: dict, tag: str = DEFAULT_TAG) -> dict[str, dict]:
    """Map slot -> node snapshot for nodes carrying ``[pulse:<tag>:<slot>]``."""
    out: dict[str, dict] = {}
    for item in (graph_list.get("nodes") or []):
        parsed = parse_tag(item.get("description") or "")
        if parsed and parsed[0] == str(tag):
            out[parsed[1]] = item
    return out


def plan(spec: dict, existing: dict[str, dict], *,
         overwrite: bool = False, explicit: set[str] | None = None) -> dict:
    """Compare spec with existing nodes; return a plan of create/update/link ops.

    ``overwrite=True`` -> push all template props back onto existing nodes.
    Otherwise only props whose ``sync`` param name is in ``explicit`` are updated
    (so a run that only says ``port=COM7`` leaves ``format`` etc. untouched).
    """
    have_pins = {slot: (node.get("pins") or {}) for slot, node in existing.items()}
    creates, updates = [], []
    for item in spec["nodes"]:
        slot = item["slot"]
        cur = existing.get(slot)
        if cur is None:
            creates.append(item)
            continue
        if overwrite:
            props = item["props"]
        else:
            explicit_set = set(explicit or ())
            props = {k: v for k, v in item["props"].items()
                     if item.get("sync", {}).get(k) in explicit_set}
        delta = {k: v for k, v in props.items()
                 if cur.get("props", {}).get(k) != v}
        if delta:
            updates.append({"slot": slot, "node_id": cur["id"], "props": delta})
    return {"creates": creates, "updates": updates, "existing": existing,
            "have_pins": have_pins}


def apply(engine_client, kind: str = KIND_SERIAL, *, tag: str = DEFAULT_TAG,
          port: str = DEFAULT_PORT, baud: int = DEFAULT_BAUD,
          fmt: str = DEFAULT_FORMAT, address: int = DEFAULT_ADDRESS,
          period: float = DEFAULT_PERIOD, max_value: int = DEFAULT_MAX,
          template: str = "Cross", overwrite: bool = False,
          explicit: set[str] | None = None,
          dry_run: bool = False, position_base: tuple[float, float] = (0.0, 0.0)) -> dict:
    """Create-or-update the pipeline on the current canvas via live ops.

    ``engine_client`` is the ``engine`` object injected by ``engine-editor-cli exec``
    (needs ``ok(op, **kwargs)``).  ``explicit`` lists the parameter names the caller
    actually passed (``{"port", "period", ...}``) — only those are re-applied to
    existing nodes unless ``overwrite`` is set.
    """
    spec = build_spec(kind, tag=tag, port=port, baud=baud, fmt=fmt,
                      address=address, period=period, max_value=max_value,
                      template=template)
    graph = engine_client.ok("graph.list")
    existing = scan_pipeline(graph, spec["tag"])
    steps = plan(spec, existing, overwrite=overwrite, explicit=explicit)

    result = {"kind": spec["kind"], "tag": spec["tag"], "params": spec["params"],
              "created": [], "updated": [], "skipped": [], "linked": [],
              "dry_run": bool(dry_run)}

    slot_pins: dict[str, dict] = {s: (n.get("pins") or {}) for s, n in existing.items()}
    slot_ids: dict[str, int] = {s: int(n["id"]) for s, n in existing.items()}

    for item in steps["creates"]:
        slot = item["slot"]
        if dry_run:
            result["created"].append({"slot": slot, "type": item["type"]})
            continue
        pos = (position_base[0] + item["pos"][0], position_base[1] + item["pos"][1])
        added = engine_client.ok(
            "graph.add", type=item["type"], props=item["props"],
            position=[pos[0], pos[1]], description=item["description"])
        slot_ids[slot] = int(added["node_id"])
        slot_pins[slot] = dict(added.get("pins") or {})
        result["created"].append({"slot": slot, "node_id": slot_ids[slot],
                                  "type": item["type"]})

    for upd in steps["updates"]:
        if dry_run:
            result["updated"].append({"slot": upd["slot"], "props": upd["props"]})
            continue
        engine_client.ok("graph.set_props", node=upd["node_id"], props=upd["props"])
        result["updated"].append({"slot": upd["slot"], "node_id": upd["node_id"],
                                  "props": upd["props"]})

    if not dry_run:
        # 重新读取一次画布（新节点/新连线后的唯一真相）
        graph = engine_client.ok("graph.list")
        links = graph.get("links") or []
        have = {(int(l["from_pin"]), int(l["to_pin"])) for l in links}
        for from_slot, from_pin, to_slot, to_pin in spec["links"]:
            fp = (slot_pins.get(from_slot) or {}).get(from_pin)
            tp = (slot_pins.get(to_slot) or {}).get(to_pin)
            if fp is None or tp is None or from_slot not in slot_ids or to_slot not in slot_ids:
                result["skipped"].append({"link": f"{from_slot}.{from_pin} -> {to_slot}.{to_pin}",
                                          "reason": "missing slot/pin"})
                continue
            if (int(fp), int(tp)) in have:
                continue
            engine_client.ok("graph.link",
                             **{"from": {"node": slot_ids[from_slot], "pin": from_pin},
                                "to": {"node": slot_ids[to_slot], "pin": to_pin}})
            have.add((int(fp), int(tp)))
            result["linked"].append(f"{from_slot}.{from_pin} -> {to_slot}.{to_pin}")
    else:
        result["linked"] = [f"{a}.{b} -> {c}.{d}" for a, b, c, d in spec["links"]]

    result["nodes_total"] = len(slot_ids)
    return result


def summary_line(result: dict) -> str:
    """One-line human summary for CLI output."""
    p = result.get("params") or {}
    kind = result.get("kind", "?")
    dev = (f"{p.get('port')}@{p.get('baud')} fmt={p.get('format')}"
           if kind == KIND_SERIAL else f"addr=0x{int(p.get('address', 0)):04X}")
    return (f"pulse pipeline [{result.get('tag')}] {kind}: create "
            f"{len(result.get('created') or [])}, update "
            f"{len(result.get('updated') or [])}, link "
            f"{len(result.get('linked') or [])} | {dev} | period={p.get('period')}s "
            f"values 1..{p.get('max_value')}")
