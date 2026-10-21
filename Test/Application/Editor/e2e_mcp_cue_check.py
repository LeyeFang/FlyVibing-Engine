"""
E2E: Editor Live MCP — Transform / MeshRenderer “提示指示”行为演示（需引擎运行中）。

覆盖: 标量缩放 / 相对位移 / 材质改名 / shader 按名切换 / uniform 改色 / 纹理替换 /
      component.get 语义摘要 / 提示显隐切换 + 两次截图。

用法:
    .venv-py314t\\Scripts\\python.exe Test/Application/Editor/e2e_mcp_cue_check.py
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
    print("== Editor Live MCP — cue (Transform / MeshRenderer) E2E ==")

    def call(op: str, args: dict | None = None) -> dict:
        result = m._send(op, args or {})
        print(f"  [{op}] {result}")
        return result

    call("selection.clear")
    add = call("entity.add", {"name": "MCP_Cue", "parent": "none"})
    eid = add.get("entity_id")
    if not isinstance(eid, int):
        print("FAIL: entity.add")
        return 1

    # 标量缩放 + 摆位
    call("entity.transform", {"id": eid, "position": [0, 0, 2], "scale": 2.0})
    call("component.add", {"id": eid, "type": "MeshRenderer"})

    # 提示材质: 颜色 + 改名 + shader（按名称）
    call("component.set", {"id": eid, "type": "MeshRenderer", "fields": {
        "color": [0.2, 0.8, 1.0, 1.0], "material_name": "Cue_Cyan", "shader": "Basic"}})

    # uniform 通道改色（橙色）
    call("component.set", {"id": eid, "type": "MeshRenderer", "fields": {
        "uniform": {"uColor": [1.0, 0.5, 0.0, 1.0]}}})

    # 纹理替换（按名称）
    tex = call("resource.find", {"kind": "texture", "name": "Default"})
    if tex.get("count"):
        call("component.set", {"id": eid, "type": "MeshRenderer", "fields": {"texture": "Default"}})

    # 相对位移: x 0 → 1
    call("entity.transform", {"id": eid, "position": [1, 0, 0], "relative": True})
    info = call("entity.get", {"id": eid})
    pos_x = (info.get("transform") or {}).get("position", [None])[0]
    print(f"  relative-move check: pos_x = {pos_x}")
    if pos_x != 1.0:
        print("FAIL: relative transform")
        return 1

    comp = call("component.get", {"id": eid, "type": "MeshRenderer"})
    meta = (comp.get("meta") or {}).get("material") or {}
    color = meta.get("color")
    print(f"  meta.material: name={meta.get('name')!r} color={color} shader={meta.get('shader_name')!r}")
    if not color or abs(color[0] - 1.0) > 1e-3 or abs(color[1] - 0.5) > 1e-3:
        print("FAIL: uniform color not applied")
        return 1

    # 提示出现 → 截图
    call("selection.set", {"id": eid, "gizmo": True})
    path_show, png_show = m._capture_png("editor")
    print(f"  [capture show] {path_show} ({len(png_show)} bytes)")

    # 提示隐藏 → 截图
    call("selection.clear")
    call("entity.visible", {"id": eid, "render": False})
    path_hide, png_hide = m._capture_png("editor")
    print(f"  [capture hide] {path_hide} ({len(png_hide)} bytes)")
    call("entity.visible", {"id": eid, "render": True})

    # 清理
    call("entity.delete", {"id": eid})
    call("selection.clear")
    print("RESULT: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
