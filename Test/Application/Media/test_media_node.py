"""
ShowMedia 节点测试 — 注册 / 静态检查 / 干跑惰性 / 节点驱动播放（无头）。

覆盖:
  1. 注册: _TYPES 引脚 / _EVALUATORS / graph_constraints.SHOW_MEDIA
  2. 静态检查: Entity 未连 → media_pin_unconnected(error);
     exec_in 未连 → media_exec_unconnected(warning); 齐全连线 → 无 media_* 条目
  3. 干跑: ctx.dry_run=True → 只记日志, 零副作用（无播放器/纹理）
  4. 节点驱动: GraphEvaluator.trigger("OnFrameUpdate") → 懒初始化 + 逐帧推进
     （引擎=ctx.scene.app; 编辑器侧无 tick — 协议 media_protocol.md）

运行: python Utils/Dev/test_runner.py --only media_node
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

ROOT = os.path.dirname(_d)
GIF_PATH = os.path.join(ROOT, "Resource", "Textures", "demo_animation.gif")

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


class _NodeTestApp:
    """最小运行时替身（无渲染器; scene 注入见 main）。"""
    renderer = None


def _build_graph(with_links: bool) -> dict:
    """OnFrameUpdate → EntityGet(MemeSquare) → ShowMedia（Entity ref 直连）。"""
    from Application.Core.NodeGraph import _TYPES

    pins = {}

    def mk(key: str, t: str, props: dict | None = None) -> dict:
        pid = {}
        base = (len(pins) + 1) * 1000
        for i, p in enumerate(_TYPES[t].pins):
            pid[p.name] = base + i
        pins[key] = pid
        return {"node_type": t, "pos": [0.0, 0.0], "props": props or {}, "pin_ids": pid}

    n1 = mk("1", "OnFrameUpdate")
    n2 = mk("2", "EntityGet", {"entity_name": "MemeSquare"})
    n3 = mk("3", "ShowMedia")
    links: dict = {}
    if with_links:
        links = {
            "1": {"from_pin": n1["pin_ids"]["exec"], "to_pin": n2["pin_ids"]["exec_in"]},
            "2": {"from_pin": n2["pin_ids"]["exec_out"], "to_pin": n3["pin_ids"]["exec_in"]},
            "3": {"from_pin": n2["pin_ids"]["Entity"], "to_pin": n3["pin_ids"]["Entity"]},
        }
    nodes = {"1": n1, "2": n2, "3": n3}
    return {"version": "0.1.0", "nodes": nodes, "links": links, "next_id": 9000}


def main() -> int:
    print("=" * 60)
    print("ShowMedia node — registration / checks / dry-run / drive")
    print("=" * 60)

    from Application.Core.Events.Event import BindPackCallback
    from Application.Resource.ResourceManager import ResourceManager
    from Application.Core.Scene.SceneManager import SceneManager

    BindPackCallback(lambda e: None)
    ResourceManager.Init(_NodeTestApp)
    SceneManager.Init(_NodeTestApp)
    st = SceneManager._state_for(_NodeTestApp.__name__)
    _NodeTestApp.scene = st

    import esper
    from Application.Core.NodeGraph import _TYPES, _EVALUATORS
    from Application.Core.NodeGraph import graph_constraints
    from Application.Core import Media as MediaSystem

    # ── 1. 注册 ──
    print("── registration ──")
    nd = _TYPES.get("ShowMedia")
    check("type registered", nd is not None)
    if nd is not None:
        names = sorted(p.name for p in nd.pins)
        check("pins == {Entity, exec_in, exec_out}",
              names == ["Entity", "exec_in", "exec_out"], str(names))
    check("evaluator registered", "ShowMedia" in _EVALUATORS)
    check("constraint constant", graph_constraints.SHOW_MEDIA == "ShowMedia")

    # ── 2. 静态检查 ──
    print("── static checks ──")
    from Application.Core.NodeGraph.validation.checks import static_check_graph

    bad = static_check_graph(_build_graph(with_links=False))
    codes = {e["code"] for e in bad}
    check("Entity unconnected -> error", "media_pin_unconnected" in codes, str(sorted(codes)))
    check("exec unconnected -> warning",
          any(e["code"] == "media_exec_unconnected" and e["level"] == "warning" for e in bad),
          str([e for e in bad if e["code"].startswith("media")]))

    good = static_check_graph(_build_graph(with_links=True))
    media_left = [e for e in good if e["code"].startswith("media")]
    check("wired graph -> no media_* entries", media_left == [], str(media_left))

    # ── 3. 场景实体（模板: 组件即参数; 编辑器侧无播放）──
    print("── scene template ──")
    from Application.Core.Scene.BasicComponents import Transform, MeshRenderer, MediaPlayer

    eid = esper.create_entity()
    esper.add_component(eid, Transform())
    esper.add_component(eid, MeshRenderer())
    esper.add_component(eid, MediaPlayer(source=GIF_PATH))
    st.entities[str(eid)] = 1
    st.SetEntityName(eid, "MemeSquare")
    check("template entity resolvable", st.GetEntityByName("MemeSquare") == eid,
          str(st.GetEntityByName("MemeSquare")))

    # ── PIE 模板同步白名单携带 MediaPlayer（EntitySpawn 实例化路径）──
    from types import SimpleNamespace
    from Application.Editor.UI.controllers.SimulationController import SimulationController

    tpl = SimpleNamespace(entities={})
    SimulationController._sync_ecs_to_scene(tpl, st)
    comps: set = set()
    for ed in tpl.entities.values():
        if ed.name == "MemeSquare":
            comps = set(ed.components)
    check("PIE template carries MediaPlayer", "MediaPlayer" in comps, str(sorted(comps)))

    # ── 4. 干跑惰性 ──
    print("── dry-run inert ──")
    from Application.Core.NodeGraph import NodeCanvas, GraphEvaluator, ExecutionContext

    canvas = NodeCanvas.from_dict(_build_graph(with_links=True))
    evaluator = GraphEvaluator(canvas, _TYPES)

    ctx = ExecutionContext()
    ctx.scene = st
    ctx.dry_run = True
    logs: list = []
    ctx.log = lambda nid, ntype, action, detail="": logs.append((ntype, action))
    evaluator.trigger("OnFrameUpdate", ctx)
    check("dry-run: no player created",
          MediaSystem.snapshot(_NodeTestApp)["players"] == [],
          str(MediaSystem.snapshot(_NodeTestApp)))
    check("dry-run: logged", ("ShowMedia", "media_advance") in logs, str(logs))

    # ── 5. 节点驱动播放（非干跑）──
    print("── node-driven playback ──")
    ctx2 = ExecutionContext()
    ctx2.scene = st
    ctx2.delta_time = 0.0
    evaluator.trigger("OnFrameUpdate", ctx2)

    snap = MediaSystem.snapshot(_NodeTestApp)
    players = [p for p in snap["players"] if p["entity"] == eid]
    check("player created by node", len(players) == 1, str(snap))
    pl = players[0] if players else {}
    check("no error", pl.get("error") == "", str(pl.get("error")))
    check("frames = 10", pl.get("frames") == 10, str(pl.get("frames")))
    tid = pl.get("texture_id", 0)
    check("dynamic texture created", tid > 0, str(tid))

    mr = esper.component_for_entity(eid, MeshRenderer)
    mat = ResourceManager.GetMaterial(mr.material_id)
    check("material slot0 bound", bool(mat.texture_id_list) and mat.texture_id_list[0] == tid,
          str(getattr(mat, "texture_id_list", None)))

    dur0 = MediaSystem.load_media(GIF_PATH).durations[0]
    ctx2.delta_time = dur0 * 1.1
    evaluator.trigger("OnFrameUpdate", ctx2)
    fr = MediaSystem.snapshot(_NodeTestApp)["players"][0]["frame"]
    check("clock advances via trigger", fr == 1, str(fr))

    ctx2.delta_time = dur0 * 3.0
    evaluator.trigger("OnFrameUpdate", ctx2)
    fr2 = MediaSystem.snapshot(_NodeTestApp)["players"][0]["frame"]
    check("continues advancing", fr2 > fr, f"{fr}->{fr2}")

    # ── 6. 清理 ──
    MediaSystem.reset()
    try:
        esper.delete_entity(eid)
    except Exception:  # noqa: BLE001
        pass
    check("reset clears", MediaSystem.snapshot(_NodeTestApp)["players"] == [])

    total = _RESULTS["pass"] + _RESULTS["fail"]
    status = "OK" if _RESULTS["fail"] == 0 else "FAIL"
    print()
    print(f"RESULT: {status} ({_RESULTS['pass']}/{total})")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
