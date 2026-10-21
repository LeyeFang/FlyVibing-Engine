"""
EntityGroupSetVisible 节点测试 — 注册 / dry-run / 单批下发 / 原子显隐（无头）。

覆盖:
  1. 注册: _TYPES 引脚 (Entity1-4 optional + Visible) / _EVALUATORS
  2. 干跑: ctx.dry_run=True → 只记日志 (set_group_visible), 零渲染器调用
  3. 节点驱动: EntityGet×2 → 组节点 → **单批 enqueue_many** (2 条同批命令,
     修复多部件 cue "箭把/箭头各自一帧出现" 的帧边界竞态)
  4. SceneManager.SetEntitiesRenderVisible 批量 API: 单批 + MeshRenderer.visible 同步

运行: python Utils/Dev/test_runner.py --only entity_group_visible
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


class _NodeTestApp:
    """最小场景宿主替身 (renderer 注入见 main)。"""
    renderer = None


class _FakeRenderer:
    """记录 enqueue / enqueue_many 的渲染器替身 — 验证"单批下发"路径。"""

    def __init__(self) -> None:
        self.batches: list[list] = []
        self.singles: list = []

    def enqueue(self, cmd) -> None:
        self.singles.append(cmd)

    def enqueue_many(self, cmds) -> None:
        self.batches.append(list(cmds))


def _build_graph() -> dict:
    """OnGameStart → EntityGet(A) → EntityGet(B) → EntityGroupSetVisible(Entity1/2)。"""
    from Application.Core.NodeGraph import _TYPES

    pins: dict[str, dict] = {}

    def mk(key: str, t: str, props: dict | None = None) -> dict:
        pid = {}
        base = (len(pins) + 1) * 1000
        for i, p in enumerate(_TYPES[t].pins):
            pid[p.name] = base + i
        pins[key] = pid
        return {"node_type": t, "pos": [0.0, 0.0], "props": props or {}, "pin_ids": pid}

    n1 = mk("1", "OnGameStart")
    n2 = mk("2", "EntityGet", {"entity_name": "GrpA"})
    n3 = mk("3", "EntityGet", {"entity_name": "GrpB"})
    n4 = mk("4", "EntityGroupSetVisible")
    links = {
        "1": {"from_pin": n1["pin_ids"]["exec"], "to_pin": n2["pin_ids"]["exec_in"]},
        "2": {"from_pin": n2["pin_ids"]["exec_out"], "to_pin": n3["pin_ids"]["exec_in"]},
        "3": {"from_pin": n3["pin_ids"]["exec_out"], "to_pin": n4["pin_ids"]["exec_in"]},
        "4": {"from_pin": n2["pin_ids"]["Entity"], "to_pin": n4["pin_ids"]["Entity1"]},
        "5": {"from_pin": n3["pin_ids"]["Entity"], "to_pin": n4["pin_ids"]["Entity2"]},
    }
    nodes = {"1": n1, "2": n2, "3": n3, "4": n4}
    return {"version": "0.1.0", "nodes": nodes, "links": links, "next_id": 9000}


def main() -> int:
    print("=" * 60)
    print("EntityGroupSetVisible node — registration / dry-run / single batch")
    print("=" * 60)

    from Application.Core.Events.Event import BindPackCallback
    from Application.Resource.ResourceManager import ResourceManager
    from Application.Core.Scene.SceneManager import SceneManager
    from Application.Core.Scene.BasicComponents import Transform, MeshRenderer

    BindPackCallback(lambda e: None)
    ResourceManager.Init(_NodeTestApp)
    SceneManager.Init(_NodeTestApp)
    st = SceneManager._state_for(_NodeTestApp.__name__)
    _NodeTestApp.scene = st
    fake = _FakeRenderer()
    _NodeTestApp.renderer = fake

    import esper
    from Application.Core.NodeGraph import _TYPES, _EVALUATORS
    from Application.Core.NodeGraph import NodeCanvas, GraphEvaluator, ExecutionContext

    # ── 1. 注册 ──
    print("── registration ──")
    nd = _TYPES.get("EntityGroupSetVisible")
    check("type registered", nd is not None)
    if nd is not None:
        names = sorted(p.name for p in nd.pins)
        check("pins == {Entity1..4, Visible, exec_in, exec_out}",
              names == ["Entity1", "Entity2", "Entity3", "Entity4",
                        "Visible", "exec_in", "exec_out"], str(names))
        opt = {p.name: p.optional for p in nd.pins if p.name.startswith("Entity")}
        check("Entity1-4 optional (旧图兼容)", all(opt.values()) and len(opt) == 4, str(opt))
    check("evaluator registered", "EntityGroupSetVisible" in _EVALUATORS)

    # ── 2. 场景: 两个实体 (组目标) ──
    eid_a = st.AddEntity("GrpA", Transform(), MeshRenderer())
    eid_b = st.AddEntity("GrpB", Transform(), MeshRenderer())
    fake.singles.clear()   # 注册噪声不计入断言

    # ── 3. 干跑惰性: 只记日志 ──
    print("── dry-run inert ──")
    canvas = NodeCanvas.from_dict(_build_graph())
    evaluator = GraphEvaluator(canvas, _TYPES)
    ctx = ExecutionContext()
    ctx.scene = st
    ctx.dry_run = True
    logs: list = []
    ctx.log = lambda nid, ntype, action, detail="": logs.append((ntype, action, detail))
    evaluator.trigger("OnGameStart", ctx)
    check("dry-run logged set_group_visible",
          any(t == "EntityGroupSetVisible" and a == "set_group_visible" for t, a, _ in logs),
          str(logs))
    check("dry-run: no renderer calls", fake.batches == [] and fake.singles == [],
          f"batches={len(fake.batches)} singles={len(fake.singles)}")

    # ── 4. 节点驱动: 单批下发 (组内同帧) ──
    print("── node-driven group toggle (single batch) ──")
    ctx2 = ExecutionContext()
    ctx2.scene = st
    evaluator.trigger("OnGameStart", ctx2)
    check("exactly one batch emitted", len(fake.batches) == 1, str(len(fake.batches)))
    batch = fake.batches[0] if fake.batches else []
    check("batch has 2 EntityRenderVisibleCommand",
          len(batch) == 2 and all(type(c).__name__ == "EntityRenderVisibleCommand" for c in batch),
          str([type(c).__name__ for c in batch]))
    check("batch visible=True", all(c.visible for c in batch), str([c.visible for c in batch]))
    check("no per-entity singles for visibility",
          not any(type(c).__name__ == "EntityRenderVisibleCommand" for c in fake.singles))
    mr_a = esper.component_for_entity(eid_a, MeshRenderer)
    mr_b = esper.component_for_entity(eid_b, MeshRenderer)
    check("MeshRenderer.visible synced", mr_a.visible and mr_b.visible,
          f"a={mr_a.visible} b={mr_b.visible}")

    # ── 5. 批量 API: 隐藏路径 + 去重 ──
    print("── batch API (hide) ──")
    n = st.SetEntitiesRenderVisible([eid_a, eid_b, eid_b], False)
    check("applied count dedup (2)", n == 2, str(n))
    check("second batch emitted", len(fake.batches) == 2)
    check("second batch visible=False",
          all(not c.visible for c in fake.batches[1]), str([c.visible for c in fake.batches[1]]))
    check("visible flags False", (not mr_a.visible) and (not mr_b.visible))
    n0 = st.SetEntitiesRenderVisible([999999], True)
    check("invalid ids -> 0, no batch", n0 == 0 and len(fake.batches) == 2, str(n0))

    # ── 清场 ──
    st.DeleteEntity(eid_a)
    st.DeleteEntity(eid_b)
    _NodeTestApp.renderer = None

    total = _RESULTS["pass"] + _RESULTS["fail"]
    status = "OK" if _RESULTS["fail"] == 0 else "FAIL"
    print()
    print(f"RESULT: {status} ({_RESULTS['pass']}/{total})")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
