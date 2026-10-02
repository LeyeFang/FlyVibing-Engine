"""
GraphBuilder 冒烟测试 — 验证 API 可用性。

用法: python Utils/User/NodeEditor/test_smoke.py
"""

import sys, os
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from Utils.User.NodeEditor.graph_builder import GraphBuilder

g = GraphBuilder()

# 基础节点
a = g.node("Constant", ["Result"], {"value": 42})
b = g.node("Print", ["exec_in", "exec_out", "Value"])
g.link(a, "Result", b, "Value")
print(f"  node: {a=}, {b=}, link OK")

# event nodes
GS, FU, GP = g.event_nodes()
print(f"  events: GS={GS}, FU={FU}, GP={GP}")

# chain
c = g.node("VarSet", ["exec_in", "exec_out", "Name", "Value"],
           {"mode": "manual", "var_name": "x", "value": 1})
g.chain(b, c)
print("  chain: OK")

# validate
r = g.validate(max_frames=0)
assert r.passed, f"Static failed: {r.static_errors}"
print(f"  validate: PASSED (static)")

# build
d = g.build()
assert len(d["nodes"]) >= 6, f"Expected >=6 nodes, got {len(d['nodes'])}"
assert len(d["links"]) >= 2, f"Expected >=2 links, got {len(d['links'])}"
print(f"  build: {len(d['nodes'])} nodes, {len(d['links'])} links")

print("\n✅ All GraphBuilder smoke tests passed")
