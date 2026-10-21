"""NodePack 注入回归：自动发现 / 无连线持久化 / 反注册。

对应 `Doc/NODE_PACK_MIGRATION_2026-10-20.md` §3 的图级验收。
"""

# TIER: core

from __future__ import annotations

import os
import sys

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "startup.bat")):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)

from Application.Core.NodeGraph import NodeCanvas, _TYPES
from Application.Core.NodeGraph.evaluator_engine import _EVALUATORS
from Application.Core.NodeGraph.node_packs import NodePackRegistry
from Application.Functions.SerialParallelDevice import node_pack as device_pack

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


print("-- 1. auto discovery --")
check("SerialSend registered", "SerialSend" in _TYPES)
check("ParallelSend registered", "ParallelSend" in _TYPES)
check("SerialSend owner=device",
      NodePackRegistry.owner_of("SerialSend") == "device",
      NodePackRegistry.owner_of("SerialSend"))
check("SerialSend evaluator registered", "SerialSend" in _EVALUATORS)
check("ParallelSend evaluator registered", "ParallelSend" in _EVALUATORS)
fields = NodePackRegistry.fields_for("SerialSend")
check("SerialSend fields include serial_port",
      any(f.get("kind") == "serial_port" for f in fields), str(fields))
menu = NodePackRegistry.menu_sections()
device_menu = dict(menu).get("Device") or []
check("menu has Device/Serial",
      any(title == "Serial" for title, _items in device_menu), str(device_menu))

print("-- 2. graph persistence without links --")
canvas = NodeCanvas.from_dict({"nodes": {}, "links": {}})
nid = canvas.add_node("SerialSend", (10.0, 20.0))
check("add_node returns id", nid > 0, str(nid))
inst = canvas.nodes[nid]
inst.props.update({"port": "@SSSEP-Stimulator", "baud_rate": 9600, "format": "string"})
payload = canvas.to_dict()
check("no links required", not payload.get("links"), str(payload.get("links")))
restored = NodeCanvas.from_dict(payload)
check("node survives roundtrip", nid in restored.nodes, str(list(restored.nodes)))
check("props survive roundtrip",
      restored.nodes[nid].props.get("port") == "@SSSEP-Stimulator",
      str(restored.nodes[nid].props))
check("restored graph still has no links", not restored.links)

print("-- 3. unload / re-register --")
removed = NodePackRegistry.unregister_owner("device")
check("unregister removes types", "SerialSend" not in _TYPES, str(removed))
check("unregister removes evaluator", "SerialSend" not in _EVALUATORS)
NodePackRegistry.register(device_pack.register())
check("re-register restores type", "SerialSend" in _TYPES)
check("re-register restores evaluator", "SerialSend" in _EVALUATORS)
check("re-register restores owner",
      NodePackRegistry.owner_of("SerialSend") == "device")

print("-" * 60)
ok = _RESULTS["fail"] == 0
print(f"RESULT: {'OK' if ok else 'FAIL'} ({_RESULTS['pass']}/{_RESULTS['pass'] + _RESULTS['fail']})")
sys.exit(0 if ok else 1)
