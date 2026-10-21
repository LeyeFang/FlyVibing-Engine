"""
TextSystem 测试 — 文本→动态纹理光栅化 / 两形态 / auto 画布 / 节点驱动（无头纯 Pillow）。

覆盖:
  1. 注册: TextDisplay 进组件注册表 + PIE 模板白名单携带
  2. 两形态: 有色画布 (bg alpha=1, 角落=底色) / 浮空文字 (bg alpha=0, 角落透明)
  3. auto 画布: 内容变化 → 画布宽自适应; 同尺寸 → TextureUpdateCommand 热更 (纹理 id 不变)
  4. 合成加粗 (描边 — 字形像素数增加) / 合成斜体 (斜切 — 画布加宽)
  5. auto_scale: 载体缩放 = 画布纵横比 × (world_height/2)
  6. SetText 节点: 注册 / 干跑惰性 / 驱动 (改组件 + 刷新纹理)
  7. reset() 清理

运行: python Utils/Dev/test_runner.py --only text_system
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


class _FakeApp:
    renderer = None


class _FakeRenderer:
    def __init__(self) -> None:
        self.singles: list = []
        self.batches: list[list] = []

    def enqueue(self, cmd) -> None:
        self.singles.append(cmd)

    def enqueue_many(self, cmds) -> None:
        self.batches.append(list(cmds))


def _tex_arr(tid: int):
    from Application.Resource.ResourceManager import ResourceManager
    entry = ResourceManager.loaded_texture.get(str(tid))
    return entry['data'].image_data if entry else None


def main() -> int:
    print("=" * 60)
    print("TextSystem — raster / forms / auto-canvas / node drive (headless)")
    print("=" * 60)

    import numpy as np
    import esper
    from Application.Core.Events.Event import BindPackCallback
    from Application.Resource.ResourceManager import ResourceManager
    from Application.Core.Scene.SceneManager import SceneManager
    from Application.Core.Scene.BasicComponents import Transform, MeshRenderer, TextDisplay
    from Application.Core import Text as TextSystem

    BindPackCallback(lambda e: None)
    ResourceManager.Init(_FakeApp)
    SceneManager.Init(_FakeApp)
    st = SceneManager._state_for(_FakeApp.__name__)
    _FakeApp.scene = st
    fake = _FakeRenderer()
    _FakeApp.renderer = fake

    # ── 1. 注册 ──
    print("── registration ──")
    registered = st.comp_mgr.get_all()
    check("TextDisplay in component registry", "TextDisplay" in registered)
    from Application.Core.NodeGraph.component_registry import get_properties
    check("node property table", len(get_properties("TextDisplay")) >= 8,
          str(len(get_properties("TextDisplay"))))

    eid = st.AddEntity("Txt", Transform(), MeshRenderer())
    td = esper.component_for_entity(eid, MeshRenderer)  # 占位 — 立即覆盖
    td = TextDisplay()
    esper.add_component(eid, td)

    from types import SimpleNamespace
    from Application.Editor.UI.controllers.SimulationController import SimulationController
    tpl = SimpleNamespace(entities={})
    SimulationController._sync_ecs_to_scene(tpl, st)
    comps: set = set()
    for ed in tpl.entities.values():
        if ed.name == "Txt":
            comps = set(ed.components)
    check("PIE template carries TextDisplay", "TextDisplay" in comps, str(sorted(comps)))

    # ── 2. 浮空文字 (bg alpha=0) ──
    print("── floating text (transparent canvas) ──")
    td.text = "WW"
    td.size = 64
    td.bg_color = (0.0, 0.0, 0.0, 0.0)
    td.color = (1.0, 1.0, 1.0, 1.0)
    td.auto_scale = False
    TextSystem.refresh(_FakeApp, eid)
    state = TextSystem.snapshot(_FakeApp)["texts"]
    tid = state[0]["texture_id"] if state else 0
    arr = _tex_arr(tid)
    check("texture registered as text:<eid>",
          ResourceManager.loaded_texture[str(tid)]['name'] == f"text:{eid}", str(tid))
    check("corner transparent (浮空)", arr is not None and arr[0, 0, 3] == 0,
          str(arr[0, 0].tolist() if arr is not None else None))
    glyph_px = int((arr[:, :, 3] > 0).sum()) if arr is not None else 0
    check("glyphs present (alpha>0 像素)", glyph_px > 50, str(glyph_px))
    mat = ResourceManager.GetMaterial(esper.component_for_entity(eid, MeshRenderer).material_id)
    check("material slot0 bound", bool(mat.texture_id_list) and mat.texture_id_list[0] == tid,
          str(mat.texture_id_list))

    # ── 3. 有色画布 (bg alpha=1) ──
    print("── colored canvas (opaque bg) ──")
    td.bg_color = (1.0, 0.0, 0.0, 1.0)
    TextSystem.refresh(_FakeApp, eid)
    tid2 = TextSystem.snapshot(_FakeApp)["texts"][0]["texture_id"]
    arr2 = _tex_arr(tid2)
    corner = arr2[0, 0].tolist()
    check("corner = bg color (有色画布)", corner == [255, 0, 0, 255], str(corner))

    # ── 4. auto 画布: 内容变化 → 宽度自适应; 同尺寸变化 → 热更 (id 不变) ──
    print("── auto canvas + same-size hot update ──")
    td.bg_color = (0.0, 0.0, 0.0, 0.0)
    td.text = "i"
    TextSystem.refresh(_FakeApp, eid)
    s1 = TextSystem.snapshot(_FakeApp)["texts"][0]
    w1 = s1["size"][0]
    td.text = "WWWWWW"
    TextSystem.refresh(_FakeApp, eid)
    s2 = TextSystem.snapshot(_FakeApp)["texts"][0]
    check("auto canvas grows", s2["size"][0] > w1, f"{w1} -> {s2['size'][0]}")
    check("size change swaps texture id (无感换纹理)",
          s2["texture_id"] != s1["texture_id"], f"{s1['texture_id']} -> {s2['texture_id']}")

    tid_before = s2["texture_id"]
    n_singles = len(fake.singles)
    td.color = (0.0, 1.0, 0.0, 1.0)   # 同尺寸变化 (颜色不改画布)
    TextSystem.refresh(_FakeApp, eid)
    s3 = TextSystem.snapshot(_FakeApp)["texts"][0]
    check("same-size keeps texture id", s3["texture_id"] == tid_before)
    updated_cmds = [c for c in fake.singles[n_singles:]
                    if type(c).__name__ == "TextureUpdateCommand"]
    check("same-size emits TextureUpdateCommand", len(updated_cmds) == 1,
          str([type(c).__name__ for c in fake.singles[n_singles:]]))
    arr3 = _tex_arr(tid_before)
    green_px = int(((arr3[:, :, 1] > 200) & (arr3[:, :, 3] > 0)).sum()) if arr3 is not None else 0
    check("cpu raster updated to green", green_px > 50, str(green_px))

    # ── 5. 合成加粗 / 合成斜体 ──
    print("── synthetic bold / italic ──")
    td.color = (1.0, 1.0, 1.0, 1.0)
    td.text = "WW"
    td.bold = False
    td.italic = False
    TextSystem.refresh(_FakeApp, eid)
    reg_arr = _tex_arr(TextSystem.snapshot(_FakeApp)["texts"][0]["texture_id"]).copy()
    td.bold = True
    TextSystem.refresh(_FakeApp, eid)
    bold_arr = _tex_arr(TextSystem.snapshot(_FakeApp)["texts"][0]["texture_id"])
    check("bold thickens glyphs (描边扩展)",
          int((bold_arr[:, :, 3] > 0).sum()) > int((reg_arr[:, :, 3] > 0).sum()),
          f"{int((reg_arr[:,:,3]>0).sum())} -> {int((bold_arr[:,:,3]>0).sum())}")
    td.bold = False
    td.italic = True
    TextSystem.refresh(_FakeApp, eid)
    ital_arr = _tex_arr(TextSystem.snapshot(_FakeApp)["texts"][0]["texture_id"])
    check("italic widens canvas (斜切扩宽)",
          ital_arr.shape[1] > reg_arr.shape[1],
          f"{reg_arr.shape[1]} -> {ital_arr.shape[1]}")
    td.italic = False

    # ── 6. auto_scale: 载体 = 画布纵横比 × (world_height/2) ──
    print("── auto scale carrier ──")
    td.auto_scale = True
    td.world_height = 2.0
    TextSystem.refresh(_FakeApp, eid)
    s4 = TextSystem.snapshot(_FakeApp)["texts"][0]
    wpx, hpx = s4["size"]
    xf = esper.component_for_entity(eid, Transform)
    expect_sz = 1.0
    expect_sx = 1.0 * (wpx / max(1, hpx))
    check("carrier scale matches canvas aspect",
          abs(xf.scale_z - expect_sz) < 1e-5 and abs(xf.scale_x - expect_sx) < 1e-5,
          f"scale=({xf.scale_x:.3f},{xf.scale_z:.3f}) expect=({expect_sx:.3f},{expect_sz:.3f})")

    # ── 7. SetText 节点 ──
    print("── SetText node ──")
    from Application.Core.NodeGraph import _TYPES, _EVALUATORS, NodeCanvas, GraphEvaluator, ExecutionContext

    ndef = _TYPES.get("SetText")
    check("SetText type registered", ndef is not None)
    if ndef is not None:
        check("SetText pins", sorted(p.name for p in ndef.pins)
              == ["Entity", "Text", "exec_in", "exec_out"],
              str(sorted(p.name for p in ndef.pins)))
    check("SetText evaluator registered", "SetText" in _EVALUATORS)

    def _mk_graph() -> dict:
        pins: dict[str, dict] = {}

        def mk(key, t, props=None):
            pid = {}
            base = (len(pins) + 1) * 1000
            for i, p in enumerate(_TYPES[t].pins):
                pid[p.name] = base + i
            pins[key] = pid
            return {"node_type": t, "pos": [0.0, 0.0], "props": props or {}, "pin_ids": pid}

        n1 = mk("1", "OnGameStart")
        n2 = mk("2", "EntityGet", {"entity_name": "Txt"})
        n3 = mk("3", "StringConst", {"value": "PIE!"})
        n4 = mk("4", "SetText")
        links = {
            "1": {"from_pin": n1["pin_ids"]["exec"], "to_pin": n2["pin_ids"]["exec_in"]},
            "2": {"from_pin": n2["pin_ids"]["exec_out"], "to_pin": n4["pin_ids"]["exec_in"]},
            "3": {"from_pin": n2["pin_ids"]["Entity"], "to_pin": n4["pin_ids"]["Entity"]},
            "4": {"from_pin": n3["pin_ids"]["Value"], "to_pin": n4["pin_ids"]["Text"]},
        }
        return {"version": "0.1.0", "nodes": {"1": n1, "2": n2, "3": n3, "4": n4},
                "links": links, "next_id": 9000}

    evaluator = GraphEvaluator(NodeCanvas.from_dict(_mk_graph()), _TYPES)

    ctx = ExecutionContext()
    ctx.scene = st
    ctx.dry_run = True
    logs: list = []
    ctx.log = lambda nid, ntype, action, detail="": logs.append((ntype, action))
    evaluator.trigger("OnGameStart", ctx)
    check("dry-run logs set_text", ("SetText", "set_text") in logs, str(logs))
    check("dry-run: component untouched", td.text != "PIE!", repr(td.text))

    ctx2 = ExecutionContext()
    ctx2.scene = st
    evaluator.trigger("OnGameStart", ctx2)
    check("node sets component text", td.text == "PIE!", repr(td.text))
    s5 = TextSystem.snapshot(_FakeApp)["texts"][0]
    check("node refreshed texture", s5["texture_id"] > 0, str(s5))

    # ── 8. reset ──
    TextSystem.reset()
    check("reset clears states", TextSystem.snapshot(_FakeApp)["count"] == 0)

    # ── 清场 ──
    _FakeApp.renderer = None
    st.DeleteEntity(eid)

    total = _RESULTS["pass"] + _RESULTS["fail"]
    status = "OK" if _RESULTS["fail"] == 0 else "FAIL"
    print()
    print(f"RESULT: {status} ({_RESULTS['pass']}/{total})")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
