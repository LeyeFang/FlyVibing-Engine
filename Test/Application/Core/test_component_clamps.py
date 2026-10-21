"""
组件字段数值范围钳制测试 — FIELD_CLAMPS + 三条写入路径 (无 GL)。

锁定内容:
  1. clamp_component_field 单元: 上/下限截断 / int 保持 int / bool 原样 /
     无规则原样 / tuple 逐元素钳制
  2. Light: intensity 0..10 / color 0..1 / range 0.01..1000
  3. 注册表: "Light" 已注册 (旧名 "DirectionalLight" 不注册 — 由迁移链兼容)
  4. SceneBrowserController.set_component_field (Inspector 路径) 走钳制
  5. LiveCommandServer._op_component_set (MCP/CLI 路径) 走钳制 +
     旧名 "DirectionalLight" 迁移到 "Light"

夹具: 独立 SceneManager 实例注册为 EditorHost (不 Init → 无默认实体)。
运行: python Utils/Dev/test_runner.py --only component_clamps
"""
# TIER: core

from __future__ import annotations

import os
import sys

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "_path_setup.py")):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)
    import _path_setup  # noqa: E402

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


def main() -> int:
    print("=" * 60)
    print("Component field clamps — FIELD_CLAMPS + write paths (headless)")
    print("=" * 60)

    import esper
    from Application.Core.Scene.ComponentRegistry import clamp_component_field
    from Application.Core.Scene.SceneManager import SceneManager
    from Application.Core.Scene.BasicComponents import Transform, Light
    from Application.Editor.EditorHost import EditorHost

    # ═══════════════════════════════════════════════════════════
    # 1. clamp_component_field 单元
    # ═══════════════════════════════════════════════════════════
    print("── clamp_component_field units ──")
    check("Light.intensity 999 → 10.0",
          clamp_component_field("Light", "intensity", 999) == 10.0)
    check("Light.intensity -5 → 0.0",
          clamp_component_field("Light", "intensity", -5) == 0.0)
    check("Light.color_r 2.0 → 1.0 / -1 → 0.0",
          clamp_component_field("Light", "color_r", 2.0) == 1.0
          and clamp_component_field("Light", "color_r", -1) == 0.0)
    check("Light.range 0.0 → 0.01",
          clamp_component_field("Light", "range", 0.0) == 0.01)
    check("Camera.fov 500.0 → 179.0",
          clamp_component_field("Camera", "fov", 500.0) == 179.0)
    size_hi = clamp_component_field("TextDisplay", "size", 9999)
    size_lo = clamp_component_field("TextDisplay", "size", 1)
    check("TextDisplay.size 9999 → 512 / 1 → 4 (int 保持)",
          size_hi == 512 and size_lo == 4
          and isinstance(size_hi, int) and isinstance(size_lo, int),
          f"{size_hi!r}/{size_lo!r}")
    check("TextDisplay.padding 128 → 128 (域内原样)",
          clamp_component_field("TextDisplay", "padding", 128) == 128)
    col = clamp_component_field("TextDisplay", "color", (1.5, -0.5, 0.5, 2.0))
    check("TextDisplay.color tuple 逐元素钳制 → (1,0,0.5,1)",
          isinstance(col, tuple) and col == (1.0, 0.0, 0.5, 1.0), f"{col}")
    check("Transform.position_x -999999 → -100000.0",
          clamp_component_field("Transform", "position_x", -999999) == -100000.0)
    check("MediaPlayer.speed 100 → 10.0",
          clamp_component_field("MediaPlayer", "speed", 100) == 10.0)
    check("无规则字段原样 (Unknown/mesh_id 域内)",
          clamp_component_field("Nope", "x", 7) == 7
          and clamp_component_field("MeshRenderer", "mesh_id", 3) == 3)
    check("bool 原样 (Light.intensity True)",
          clamp_component_field("Light", "intensity", True) is True)

    # ═══════════════════════════════════════════════════════════
    # 2. 写入路径 — SceneBrowserController (Inspector) / LiveCommandServer (MCP)
    # ═══════════════════════════════════════════════════════════
    print("── write paths (Inspector / MCP) ──")
    orig_reg = SceneManager._registry.get("EditorHost")
    orig_scene_attr = EditorHost.scene
    st = SceneManager("EditorHost")
    st.comp_mgr.ensure_defaults()
    SceneManager._registry["EditorHost"] = st
    EditorHost.scene = st
    # headless: 全局事件回调桩 (组件增删会 Pack 事件; 无引擎时回调为 None)
    import importlib
    _ev = importlib.import_module("Application.Core.Events.Event")
    orig_cb = _ev.app_callback_func
    _ev.app_callback_func = lambda _e: None

    eid = -1
    eid2 = -1
    try:
        # Light 在注册表; 旧名不再单独注册 (迁移链兼容)
        registered = st.comp_mgr.get_all()
        check("注册表含 Light 且无 DirectionalLight",
              "Light" in registered and "DirectionalLight" not in registered)

        eid = st.AddEntity("ClampProbe", Transform(),
                           Light(color_r=0.5, color_g=0.5, color_b=0.5))
        comp = esper.component_for_entity(
            eid, st.comp_mgr.get_all()["Light"])

        # ── Inspector 路径 ──
        from Application.Editor.UI.controllers.SceneBrowserController import (
            SceneBrowserController,
        )
        SceneBrowserController.set_component_field(eid, "Light", "intensity", 999)
        check("Inspector: intensity 999 → 10.0",
              comp.intensity == 10.0, f"{comp.intensity}")
        SceneBrowserController.set_component_field(eid, "Light", "range", 0.0)
        check("Inspector: range 0.0 → 0.01",
              abs(comp.range - 0.01) < 1e-9, f"{comp.range}")
        SceneBrowserController.set_component_field(eid, "Light", "color_g", 2.0)
        check("Inspector: color_g 2.0 → 1.0",
              comp.color_g == 1.0, f"{comp.color_g}")
        SceneBrowserController.set_component_field(eid, "Nope", "x", 1)  # 不应抛异常
        check("Inspector: 未知组件静默返回", comp.color_r == 0.5)

        # ── MCP/CLI 路径 ──
        from Application.Editor.Services.LiveCommandServer import LiveCommandServer
        res = LiveCommandServer._op_component_set({
            "id": eid, "type": "Light",
            "fields": {"intensity": 999, "range": 0.0, "color_b": 3.0},
        })
        fields = res.get("fields", {})
        check("MCP: intensity 999 → 10.0 (回读)",
              fields.get("intensity") == 10.0, f"{fields.get('intensity')}")
        check("MCP: range 0.0 → 0.01 (回读)",
              abs(fields.get("range", 0) - 0.01) < 1e-9, f"{fields.get('range')}")
        check("MCP: color_b 3.0 → 1.0 (回读)",
              fields.get("color_b") == 1.0, f"{fields.get('color_b')}")
        check("MCP: applied 三项",
              res.get("applied") == ["intensity", "range", "color_b"],
              f"{res.get('applied')}")

        # ── 旧名迁移 + 非钳制字段直写 ──
        res2 = LiveCommandServer._op_component_set({
            "id": eid, "type": "DirectionalLight",
            "fields": {"light_type": "point", "intensity": 3.0},
        })
        check("MCP: 旧名 DirectionalLight → Light (结果 type)",
              res2.get("type") == "Light", f"{res2.get('type')}")
        check("MCP: light_type 开关直写 point + intensity=3.0",
              comp.light_type == "point" and comp.intensity == 3.0,
              f"{comp.light_type}/{comp.intensity}")

        # ── 旧名迁移: get / add 同表 ──
        res3 = LiveCommandServer._op_component_get({"id": eid, "type": "DirectionalLight"})
        check("MCP: 旧名 get 迁移 (type=Light)",
              res3.get("type") == "Light", f"{res3.get('type')}")
        eid2 = st.AddEntity("ClampProbe2", Transform())
        res4 = LiveCommandServer._op_component_add({"id": eid2, "type": "DirectionalLight"})
        check("MCP: 旧名 add 迁移 (added=True + Light 已挂载)",
              res4.get("added") is True
              and esper.has_component(eid2, st.comp_mgr.get_all()["Light"]),
              f"{res4.get('added')}")
    finally:
        for _eid in (eid, eid2):
            if _eid >= 0:
                try:
                    st.DeleteEntity(_eid)
                except Exception:
                    pass
        _ev.app_callback_func = orig_cb
        EditorHost.scene = orig_scene_attr
        if orig_reg is None:
            SceneManager._registry.pop("EditorHost", None)
        else:
            SceneManager._registry["EditorHost"] = orig_reg

    total = _RESULTS["pass"] + _RESULTS["fail"]
    status = "OK" if _RESULTS["fail"] == 0 else "FAIL"
    print()
    print(f"RESULT: {status} ({_RESULTS['pass']}/{total})")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
