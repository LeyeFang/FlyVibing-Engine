"""
E2E: Editor Live MCP v3 — 实体/组件/选中/场景/资源 容器级操作（需引擎运行中 — 先启动 startup.bat）。

流程: entity.list → entity.get(DefaultCube) → entity.add → rename → transform →
      component.add(MeshRenderer) → component.set(红色) → component.list/get →
      selection.set(gizmo) → 截编辑器窗口 → resource.find(mesh) → resource.material.get →
      scene.list → reparent(挂到 Cube → 解除) → entity.delete → 列表确认删除。

用法:
    .venv-py314t\\Scripts\\python.exe Test/Application/Editor/e2e_mcp_entities_check.py
"""

from __future__ import annotations

import os
import sys

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "_path_setup.py")):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)
    import _path_setup  # noqa: F401

from engine_editor_mcp import mcp_server as m  # noqa: E402


def main() -> int:
    print("== Editor Live MCP v3 — containers E2E ==")

    def call(op: str, args: dict | None = None) -> dict:
        result = m._send(op, args or {})
        print(f"  [{op}] {result}")
        return result

    lst = call("entity.list")
    cube = next((e for e in lst.get("entities", []) if e["name"] == "DefaultCube"), None)
    if cube is None:
        print("FAIL: DefaultCube not found")
        return 1

    call("entity.get", {"id": cube["entity_id"]})
    call("selection.clear")

    add = call("entity.add", {"name": "MCP_Test"})
    eid = add.get("entity_id")
    if not isinstance(eid, int):
        print("FAIL: entity.add")
        return 1

    call("entity.rename", {"id": eid, "new_name": "MCP_Test_Red"})
    call("entity.transform", {"id": eid, "position": [3, 0, 0], "scale": [1.5, 1.5, 1.5]})
    call("component.add", {"id": eid, "type": "MeshRenderer"})
    call("component.set", {"id": eid, "type": "MeshRenderer", "fields": {"color": [1.0, 0.2, 0.2, 1.0]}})
    call("component.list", {"id": eid})
    call("component.get", {"id": eid, "type": "MeshRenderer"})

    call("selection.set", {"id": eid, "gizmo": True})
    call("selection.get")

    path, png = m._capture_png("editor")
    print(f"  [editor_capture] {path} ({len(png)} bytes)")

    call("resource.find", {"kind": "mesh", "name": "Cube"})
    info = call("entity.get", {"id": eid})
    call("resource.material.get", {"id": info.get("material_id")})
    call("scene.list")

    call("entity.reparent", {"id": eid, "parent": cube["entity_id"]})
    call("entity.reparent", {"id": eid, "parent": "none"})

    call("entity.delete", {"id": eid})
    call("selection.clear")

    lst2 = call("entity.list")
    remaining = [e for e in lst2.get("entities", []) if e["entity_id"] == eid]
    print("RESULT:", "OK (entity removed)" if not remaining else f"FAIL (still present: {remaining})")
    return 0 if not remaining else 1


if __name__ == "__main__":
    sys.exit(main())
