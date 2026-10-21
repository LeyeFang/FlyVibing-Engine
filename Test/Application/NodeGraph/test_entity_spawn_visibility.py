"""实体生成树 + 可见性语义（父/子）— core 回归。

确认：
  1. EntitySpawn 的模板实例化沿 parent_id **递归**生成全部子孙；
  2. `EntitySetRenderVisible` 只写目标实体 MeshRenderer，**不递归**（容器无网格=无效果）；
  3. `EntityGroupSetVisible` 同批写多个显式实体，**也不递归**；
  4. 编辑器眼图标路径 `set_editor_visible_tree` **递归**到子孙（与运行时渲染可见性分离）。

运行: python Utils/Dev/test_runner.py --only entity_spawn_visibility
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


class _App:
    renderer = None


class _FakeRenderer:
    def __init__(self) -> None:
        self.batches: list[list] = []
        self.singles: list = []

    def enqueue(self, cmd) -> None:
        self.singles.append(cmd)

    def enqueue_many(self, cmds) -> None:
        self.batches.append(list(cmds))


def main() -> int:
    print("=" * 60)
    print("Entity spawn tree + visibility semantics")
    print("=" * 60)

    from Application.Core.Events.Event import BindPackCallback
    from Application.Resource.ResourceManager import ResourceManager
    from Application.Core.Scene.SceneManager import SceneManager
    from Application.Core.Scene.Scene import Scene
    from Application.Core.Scene.BasicComponents import MeshRenderer, Transform

    BindPackCallback(lambda e: None)
    ResourceManager.Init(_App)
    SceneManager.Init(_App)
    st = SceneManager._state_for(_App.__name__)
    _App.scene = st
    fake = _FakeRenderer()
    _App.renderer = fake

    import esper
    from Application.Core.NodeGraph.evaluators.entity.lifecycle import _spawn_entity_tree
    from Application.Core.NodeGraph import ExecutionContext

    # ── 模板: Cue(Transform) → Body(MeshRenderer) → Tip(MeshRenderer); Cue → Head(MeshRenderer) ──
    tpl = Scene("Tpl")
    cue = tpl.add_entity("Cue", Transform=Transform())
    body = tpl.add_entity("CueBody", Transform=Transform(),
                          MeshRenderer=MeshRenderer(visible=False))
    tip = tpl.add_entity("CueTip", Transform=Transform(),
                         MeshRenderer=MeshRenderer(visible=False))
    head = tpl.add_entity("CueHead", Transform=Transform(),
                          MeshRenderer=MeshRenderer(visible=True))
    tpl.entities[body].parent_id = cue
    tpl.entities[head].parent_id = cue
    tpl.entities[tip].parent_id = body

    root = st.AddEntity("Cue")
    ctx = ExecutionContext()
    ctx.scene = st
    _spawn_entity_tree(cue, root, tpl, ctx)

    body_eid = st.GetEntityByName("CueBody")
    head_eid = st.GetEntityByName("CueHead")
    tip_eid = st.GetEntityByName("CueTip")
    check("spawn root exists", st.GetEntityByName("Cue") == root)
    check("spawn child exists", body_eid >= 0 and head_eid >= 0, f"{body_eid}/{head_eid}")
    check("spawn grandchild exists (recursive)", tip_eid >= 0, str(tip_eid))
    check("child parent links", st.GetEntityParent(body_eid) == root
          and st.GetEntityParent(head_eid) == root)
    check("grandchild parent link", st.GetEntityParent(tip_eid) == body_eid)
    check("template MeshRenderer copied",
          esper.component_for_entity(body_eid, MeshRenderer).visible is False)

    # ── 渲染可见性: 单实体, 不递归 ──
    print("── render visibility (single entity only) ──")
    fake.singles.clear()
    fake.batches.clear()
    st.SetEntityRenderVisible(root, True)          # 容器无 MeshRenderer
    check("container render flag = False", st.IsEntityRenderVisible(root) is False)
    check("container op does not touch children",
          st.IsEntityRenderVisible(body_eid) is False
          and st.IsEntityRenderVisible(head_eid) is True)
    st.SetEntityRenderVisible(body_eid, True)
    check("target child visible", st.IsEntityRenderVisible(body_eid) is True)
    check("sibling untouched", st.IsEntityRenderVisible(head_eid) is True)
    check("grandchild untouched (no recursion)", st.IsEntityRenderVisible(tip_eid) is False)

    # ── 组可见性: 显式列表 + 单批, 仍不递归 ──
    print("── group visibility (explicit refs, one batch) ──")
    fake.batches.clear()
    n = st.SetEntitiesRenderVisible([body_eid, head_eid], False)
    check("batch applied 2", n == 2, str(n))
    check("one batch emitted", len(fake.batches) == 1, str(len(fake.batches)))
    check("listed refs hidden",
          st.IsEntityRenderVisible(body_eid) is False
          and st.IsEntityRenderVisible(head_eid) is False)
    check("unlisted grandchild unchanged", st.IsEntityRenderVisible(tip_eid) is False)

    # ── 编辑器眼图标: 递归 (仅编辑器视口) ──
    print("── editor visibility (recursive tree) ──")
    from Application.Core.Engine import Engine
    from Application.Editor.EditorHost import EditorHost
    from Application.Editor.UI.controllers.SceneBrowserController import SceneBrowserController

    _prev_scene = getattr(EditorHost, "scene", None)
    EditorHost.scene = st
    try:
        SceneBrowserController.set_editor_visible_tree(root, False)
        check("root editor-visible False", st.IsEditorVisible(root) is False)
        check("child editor-visible False", st.IsEditorVisible(body_eid) is False)
        check("grandchild editor-visible False", st.IsEditorVisible(tip_eid) is False)
        SceneBrowserController.set_editor_visible_tree(root, True)
        check("tree restored (root/child/grandchild)",
              st.IsEditorVisible(root) and st.IsEditorVisible(body_eid)
              and st.IsEditorVisible(tip_eid))
    finally:
        EditorHost.scene = _prev_scene

    # 清理
    st.DeleteEntity(root)
    _App.renderer = None

    total = _RESULTS["pass"] + _RESULTS["fail"]
    status = "OK" if _RESULTS["fail"] == 0 else "FAIL"
    print()
    print(f"RESULT: {status} ({_RESULTS['pass']}/{total})")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
