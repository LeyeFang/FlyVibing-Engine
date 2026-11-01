"""干跑假场景（core，无头）— 校验 / Player --dry-run 的实体解析回归。

背景（2026-11-01）:
  `validation/dry_run.py` 原来不注入 `ctx.scene`，`EntityGet` 永远 `not found`
  （PlayerEntry --dry-run 里每帧刷屏），校验对"按名/按层级"的图失去意义。
  现在从场景 JSON 的 entities 建只读 `_DryScene`（名称索引 + 层级 + 可见性记录）。

本测试锁定:
  1. `_DryScene` 的只读查询语义（存在性 / 按名 / 子级 / 未找到 -1）
  2. 可见性写入只记录、不报错
  3. 干跑里 `EntityGet` 能解析到场景实体（不再 not found），且无 runtime error
"""

# TIER: core

from __future__ import annotations

import contextlib
import io
import os
import sys

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "_path_setup.py")):
    _parent = os.path.dirname(_d)
    if _parent == _d:
        _d = ""
        break
    _d = _parent
if _d:
    sys.path.insert(0, _d)
import _path_setup  # noqa: E402,F401

from Application.Core.NodeGraph.validation.dry_run import (  # noqa: E402
    _DryScene,
    run_dry_run,
)

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


def test_dry_scene_api() -> None:
    print("-- _DryScene API --")
    scene = _DryScene({
        "1": {"name": "HUD"},
        "2": {"name": "Child", "parent_id": 1},
        "3": {"name": "Other", "parent_id": 1},
    })
    check("EntityExists known", scene.EntityExists(1) and scene.EntityExists(2))
    check("EntityExists unknown", not scene.EntityExists(99))
    check("GetEntityByName hit", scene.GetEntityByName("HUD") == 1)
    check("GetEntityByName miss", scene.GetEntityByName("Nope") == -1)
    check("GetEntityChildren", sorted(scene.GetEntityChildren(1)) == [2, 3])
    check("children of leaf", scene.GetEntityChildren(2) == [])
    check("no components in dry scene", scene.GetComponent(1, "Transform") is None)

    scene.SetEntityRenderVisible(1, False)
    check("visibility recorded", scene.visible[1] is False)
    scene.SetEntitiesRenderVisible([1, 2], True)
    check("batch visibility applied", scene.visible[1] is True and scene.visible[2] is True)
    scene.SetEntityRenderVisible(99, False)   # 未知 id 不应抛
    check("unknown id ignored", 99 not in scene.visible)


def _graph_with_entity_get() -> dict:
    return {
        "nodes": {
            "1": {"node_type": "OnGameStart", "pos": [0, 0],
                  "pin_ids": {"exec": 11}},
            "2": {"node_type": "EntityGet", "pos": [100, 0],
                  "pin_ids": {"exec_in": 21, "exec_out": 22, "Name": 23, "Entity": 24},
                  "props": {"entity_name": "HUD"}},
        },
        "links": {"1": {"id": 1, "from_pin": 11, "to_pin": 21}},
    }


def test_dry_run_resolves_entity() -> None:
    print("-- run_dry_run entity lookup --")
    scene_json = {
        "scene": {
            "entities": {"1": {"name": "HUD", "components": {}}},
            "node_graph": _graph_with_entity_get(),
        }
    }
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        report = run_dry_run(scene_json, frames=1, dt=1.0 / 60.0)
    out = buf.getvalue()
    check("dry-run reports no errors", not report["errors"], str(report["errors"]))
    check("EntityGet no longer prints to console", "EntityGet" not in out, out)
    not_found = [e for e in report["log"] if e.get("action") == "not_found"]
    check("EntityGet resolved (no not_found log)", not not_found, str(not_found))


class _Inst:
    node_type = "EntityGet"

    def __init__(self, name: str) -> None:
        self.props = {"entity_name": name}
        self.pin_ids = {"exec_in": 31, "exec_out": 32, "Name": 33, "Entity": 34}
        self.alias = ""
        self.description = ""


class _Canvas:
    def __init__(self, inst: _Inst) -> None:
        self.nodes = {1: inst}
        self.links: dict = {}


class _G:
    def __init__(self, inst: _Inst) -> None:
        from Application.Core.NodeGraph.node_types import _TYPES

        self._canvas = _Canvas(inst)
        self._types = {"EntityGet": _TYPES["EntityGet"]}

    @staticmethod
    def _read_input(pid, ctx):
        return ctx.get_pin(pid)


def test_entity_get_output() -> None:
    print("-- EntityGet output pin --")
    from Application.Core.NodeGraph.evaluator_engine import ExecutionContext
    from Application.Core.NodeGraph.evaluators.entity.lifecycle import (
        EntityRef,
        _eval_entity_get,
    )

    inst = _Inst("HUD")
    g = _G(inst)
    ctx = ExecutionContext()
    ctx.scene = _DryScene({"7": {"name": "HUD"}})
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        _eval_entity_get(1, ctx, g)
    ref = ctx.get_pin(inst.pin_ids["Entity"])
    check("resolved EntityRef eid", isinstance(ref, EntityRef) and ref.eid == 7, str(ref))
    check("no console output", "EntityGet" not in buf.getvalue(), buf.getvalue())

    inst = _Inst("Nope")
    g = _G(inst)
    ctx = ExecutionContext()
    ctx.scene = _DryScene({"7": {"name": "HUD"}})
    _eval_entity_get(1, ctx, g)
    ref = ctx.get_pin(inst.pin_ids["Entity"])
    check("miss yields invalid EntityRef", isinstance(ref, EntityRef) and ref.eid < 0, str(ref))


def main() -> int:
    print("== validation dry scene tests ==")
    test_dry_scene_api()
    test_dry_run_resolves_entity()
    test_entity_get_output()

    total = _RESULTS["pass"] + _RESULTS["fail"]
    ok = _RESULTS["fail"] == 0
    print()
    print(f"RESULT: {'OK' if ok else 'FAIL'} ({_RESULTS['pass']}/{total})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
