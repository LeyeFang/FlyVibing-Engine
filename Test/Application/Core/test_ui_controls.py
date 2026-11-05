"""运行期 UI 控件 + UI 节点守卫（无窗口 / 无 GL / 无 esper）。

锁定内容:
  1. 控件编译：开关/滑条/分段/步进/下拉的 quad 与命中种类
  2. `controls` 数学：取值范围、步长吸附、轨道 → 数值、数值文本格式
  3. `RuntimeUILayer` 交互：点开关翻转 / 拖滑条 / 选分段 / 步进 / 下拉展开选择 / 事件队列
  4. `read_value` / `set_visible` / `set_text` / `get_text`（节点读取与显隐/文本的入口）
  5. UI 节点：类型注册 + `SetUIVisible` / `SetUIText` / `OnUIClick` / `GetUIValue` 求值语义（含过滤）
"""

# TIER: core

from __future__ import annotations

import os
import sys
from types import SimpleNamespace

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

from Application.Core.Events.InputEvent import MouseButtonEvent, MouseMoveEvent  # noqa: E402
from Application.Core.UI import controls  # noqa: E402
from Application.Core.UI.theme import DEFAULT_TOKENS  # noqa: E402
from Application.Core.UI.tree import UIElement, build_ui  # noqa: E402

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


def fake_text(text, size, color, bold=False):
    return (max(1, len(str(text)) * max(4, int(size) // 2)), max(1, int(size)),
            None, f"t:{text}:{int(size)}")


CV = SimpleNamespace(scale_mode="fit_height", reference_w=1920, reference_h=1080,
                     sort_order=0, visible=True)


def rect(dx=0.0, dy=0.0, w=600.0, h=60.0, visible=True):
    return SimpleNamespace(anchor="center", pivot="center", pos_x=dx, pos_y=dy,
                           width=w, height=h, visible=visible, order=0)


def toggle(label="Sound", value=False, action=""):
    return SimpleNamespace(label=label, value=bool(value), action=action, size=0.0)


def slider(label="Volume", lo=0.0, hi=100.0, step=0.0, value=50.0, action=""):
    return SimpleNamespace(label=label, min_value=lo, max_value=hi, step=step,
                           value=value, show_value=True, action=action, size=0.0)


def select(label="Mode", options=("A", "B", "C"), index=1, skin="segmented", action=""):
    return SimpleNamespace(label=label, options=tuple(options), index=index,
                           skin=skin, action=action, size=0.0)


class _FakeCtx:
    dry_run = False
    input_event = None
    delta_time = 0.0

    def __init__(self):
        self.pins = {}
        self.logs = []

    def set_pin(self, pin_id, value):
        self.pins[pin_id] = value

    def emit_log(self, node_id, node_type, code, message=""):
        self.logs.append((node_id, node_type, code, message))


class _FakeGraph:
    def __init__(self, canvas):
        from Application.Core.NodeGraph import _TYPES
        self._canvas = canvas
        self._types = _TYPES
        self.states = {}

    def set_state(self, node_id, key, value):
        self.states[(node_id, key)] = value

    def _read_input(self, pin_id, ctx):
        """测试替身：未连线 → None（上游戏路值由 ctx.pins 注入）。"""
        return ctx.pins.get(pin_id)


def _run_node(node_type: str, props: dict, ctx):
    """执行一次 UI 节点求值 → (ctx, inst, g, node_id)。"""
    from Application.Core.NodeGraph import _EVALUATORS
    from Application.Core.NodeGraph.canvas import NodeCanvas

    canvas = NodeCanvas()
    nid = canvas.add_node(node_type, (0.0, 0.0))
    canvas.nodes[nid].props.update(props)
    g = _FakeGraph(canvas)
    _EVALUATORS[node_type](nid, ctx, g)
    return ctx, canvas.nodes[nid], g, nid


def main() -> int:
    print("=" * 60)
    print("runtime UI — controls + UI nodes")
    print("=" * 60)

    # ── 1. 编译 ──
    print("-- 1. control rendering --")
    els = [
        UIElement(eid=1, canvas=CV, rect=rect(0, -200), toggle=toggle("Sound")),
        UIElement(eid=2, canvas=CV, rect=rect(0, -100), slider=slider()),
        UIElement(eid=3, canvas=CV, rect=rect(0, 0),
                  select=select("Quality", ("Low", "Medium", "High"), 1, "segmented")),
        UIElement(eid=4, canvas=CV, rect=rect(0, 100),
                  select=select("Res", ("720", "1080"), 0, "stepper")),
        UIElement(eid=5, canvas=CV, rect=rect(0, 200),
                  select=select("Theme", ("Dark", "Light"), 0, "dropdown")),
    ]
    r = build_ui(els, 1920, 1080, text_fn=fake_text)
    kinds = [h.kind for h in r.hits]
    check("hit kinds cover every control",
          kinds == ["toggle", "slider", "select", "select", "select", "step", "step", "dropdown"],
          str(kinds))
    check("toggle draws track + knob", len(build_ui(els[:1], 1920, 1080,
                                                    text_fn=fake_text).quads) == 3,
          str(len(build_ui(els[:1], 1920, 1080, text_fn=fake_text).quads)))
    check("slider hit carries a track",
          len(r.hits[1].track) == 2 and r.hits[1].track[1] > r.hits[1].track[0],
          str(r.hits[1].track))

    expanded = build_ui(els, 1920, 1080, expanded_eid=5, text_fn=fake_text)
    popup_hits = [h for h in expanded.hits if h.eid == 5 and h.kind == "select"]
    check("dropdown expands into option rows", len(popup_hits) == 2, str(len(popup_hits)))
    check("popup rows are topmost",
          expanded.hits[-1].eid == 5 and expanded.hits[-1].kind == "select")
    check("popup is painted after the HUD",
          len(expanded.quads) > len(r.quads), f"{len(expanded.quads)} vs {len(r.quads)}")

    hovered = build_ui(els, 1920, 1080, hover_eid=1, text_fn=fake_text)
    off_track = build_ui(els[:1], 1920, 1080, text_fn=fake_text)
    check("toggle hover changes the track colour",
          any(q.color == DEFAULT_TOKENS["color.button.hover"] for q in hovered.quads)
          and any(q.color == DEFAULT_TOKENS["color.button"] for q in off_track.quads),
          str([q.color for q in hovered.quads[:3]]))

    # ── 2. 数值数学 ──
    print("-- 2. value math --")
    check("clamp + step snap", controls.clamp_value(37.0, 0.0, 100.0, 5.0) == 35.0,
          str(controls.clamp_value(37.0, 0.0, 100.0, 5.0)))
    check("step keeps range ends",
          controls.clamp_value(-10.0, 0.0, 100.0, 5.0) == 0.0
          and controls.clamp_value(1000.0, 0.0, 100.0, 5.0) == 100.0)
    check("track middle = middle value", controls.value_at_track((100.0, 200.0), 150.0, 0.0, 10.0) == 5.0)
    check("track clamps outside", controls.value_at_track((100.0, 200.0), 10.0, 0.0, 10.0) == 0.0
          and controls.value_at_track((100.0, 200.0), 900.0, 0.0, 10.0) == 10.0)
    check("step snaps on drag",
          controls.value_at_track((0.0, 100.0), 23.0, 0.0, 100.0, 10.0) == 20.0,
          str(controls.value_at_track((0.0, 100.0), 23.0, 0.0, 100.0, 10.0)))
    check("format_value int for step>=1", controls.format_value(60.0, 5.0) == "60")
    check("format_value trims floats", controls.format_value(0.5, 0.0) == "0.5")
    check("swapped range tolerated",
          controls.slider_range(slider(lo=10.0, hi=0.0)) == (0.0, 10.0, 0.0),
          str(controls.slider_range(slider(lo=10.0, hi=0.0))))

    # ── 3. 图层交互 ──
    print("-- 3. layer interaction --")
    from Application.Runtime.RuntimeUILayer import RuntimeUILayer as UI

    saved = (UI._elements, UI._scene_result, UI._values, UI._overrides, UI._expanded,
             UI._pressed_eid, UI._press_kind, UI._drag_track, UI._hover_eid, UI._hover_index,
             UI._events, UI._renderer)
    try:
        UI._elements = tuple(els)
        UI._scene_result = r
        UI._values = {}
        UI._overrides = {}
        UI._expanded = 0
        UI._pressed_eid = 0
        UI._press_kind = ""
        UI._drag_track = ()
        UI._hover_eid = 0
        UI._hover_index = -1
        UI._events.clear()
        UI._renderer = None

        def click(element_eid: int, x: float, y: float) -> None:
            UI.OnEvent(MouseButtonEvent(0, 1, 0, int(x), int(y)))
            UI.OnEvent(MouseButtonEvent(0, 0, 0, int(x), int(y)))
            _ = element_eid

        # 开关：点一次翻转并产生事件
        tx, ty, tw, th = r.rects[1]
        click(1, tx + tw - 40, ty + th / 2)
        check("toggle flips on click", UI.read_value(1) == (1.0, 0), str(UI.read_value(1)))
        events = UI.drain_events()
        check("toggle emits one UI event",
              len(events) == 1 and events[0].kind == "ui_event"
              and events[0].control == "toggle" and events[0].eid == 1, str(events))
        UI.OnEvent(MouseButtonEvent(0, 1, 0, int(tx + tw - 40), int(ty + th / 2)))
        UI.OnEvent(MouseButtonEvent(0, 0, 0, int(tx + tw - 40), int(ty + th / 2)))
        check("toggle flips back", UI.read_value(1)[0] == 0.0)

        # 滑条：按下即跳，拖拽更新
        sx_, sy_, sw_, sh_ = r.rects[2]
        track = r.hits[1].track
        UI.OnEvent(MouseButtonEvent(0, 1, 0, int(track[0] + (track[1] - track[0]) * 0.25),
                                    int(sy_ + sh_ / 2)))
        check("slider jumps on press", abs(UI.read_value(2)[0] - 25.0) < 1.0,
              str(UI.read_value(2)))
        UI.OnEvent(MouseMoveEvent(int(track[0] + (track[1] - track[0]) * 0.8),
                                  int(sy_ + sh_ / 2)))
        check("slider follows the drag", abs(UI.read_value(2)[0] - 80.0) < 2.0,
              str(UI.read_value(2)))
        UI.OnEvent(MouseButtonEvent(0, 0, 0, int(track[1]), int(sy_ + sh_ / 2)))
        check("slider emits an event on release",
              any(e.control == "slider" for e in UI.drain_events()))

        # 分段选择：点第三段
        sel_hit = [h for h in r.hits if h.kind == "select" and h.eid == 3][2]
        hx, hy, hw, hh = sel_hit.rect
        click(3, hx + hw / 2, hy + hh / 2)
        check("segmented select sets the index", UI.read_value(3) == (2.0, 2),
              str(UI.read_value(3)))

        # 步进：+ → 下一项
        step_up = [h for h in r.hits if h.kind == "step" and h.index > 0][0]
        hx, hy, hw, hh = step_up.rect
        click(4, hx + hw / 2, hy + hh / 2)
        check("stepper increments", UI.read_value(4) == (1.0, 1), str(UI.read_value(4)))
        check("stepper clamps at the last option",
              (UI._values.__setitem__(4, 1), click(4, hx + hw / 2, hy + hh / 2),
               UI.read_value(4))[2] == (1.0, 1))

        # 下拉：点开 → 选第二项
        dx, dy, dw, dh = r.rects[5]
        UI.OnEvent(MouseButtonEvent(0, 1, 0, int(dx + dw - 20), int(dy + dh / 2)))
        UI.OnEvent(MouseButtonEvent(0, 0, 0, int(dx + dw - 20), int(dy + dh / 2)))
        check("dropdown opens", UI._expanded == 5, str(UI._expanded))
        expanded = build_ui(els, 1920, 1080, expanded_eid=5, text_fn=fake_text)
        option = [h for h in expanded.hits if h.eid == 5 and h.kind == "select"][1]
        ox, oy, ow, oh = option.rect
        UI._scene_result = expanded
        click(5, ox + ow / 2, oy + oh / 2)
        check("dropdown option selects + closes",
              UI.read_value(5) == (1.0, 1) and UI._expanded == 0,
              f"{UI.read_value(5)} expanded={UI._expanded}")

        # 显隐入口（节点用）
        check("set_visible by eid", UI.set_visible(4, False) and not UI.panel_visible(4))
        check("set_visible unknown target -> False", UI.set_visible("NoSuchThing", True) is False)

        # 值覆盖参与编译（悬停态重建）
        overridden = build_ui(els, 1920, 1080, values={1: True}, text_fn=fake_text)
        primary = DEFAULT_TOKENS["color.button.primary"]
        check("values override reaches the compiler",
              any(q.color == primary for q in overridden.quads),
              str([q.color for q in overridden.quads[:4]]))
    finally:
        (UI._elements, UI._scene_result, UI._values, UI._overrides, UI._expanded,
         UI._pressed_eid, UI._press_kind, UI._drag_track, UI._hover_eid, UI._hover_index,
         UI._events, UI._renderer) = saved
        UI._events.clear()

    # ── 4. 节点 ──
    print("-- 4. UI nodes --")
    from Application.Core.NodeGraph import _TYPES, _EVALUATORS
    for name in ("SetUIVisible", "SetUIText", "OnUIClick", "GetUIValue"):
        check(f"{name} registered", name in _TYPES and name in _EVALUATORS)
    check("SetUIVisible pins",
          sorted(p.name for p in _TYPES["SetUIVisible"].pins)
          == ["Entity", "Visible", "exec_in", "exec_out"],
          str(sorted(p.name for p in _TYPES["SetUIVisible"].pins)))
    check("SetUIText pins",
          sorted(p.name for p in _TYPES["SetUIText"].pins)
          == ["Entity", "Text", "exec_in", "exec_out"],
          str(sorted(p.name for p in _TYPES["SetUIText"].pins)))
    check("OnUIClick is a graph entry (exec out only)",
          any(p.name == "exec" and p.direction == "output" for p in _TYPES["OnUIClick"].pins))
    check("OnUIClick lives in the Event category (trigger() only fires Event nodes)",
          _TYPES["OnUIClick"].category == "Event", _TYPES["OnUIClick"].category)

    calls = []
    real_set = UI.set_visible
    real_set_text = UI.set_text
    real_read = UI.read_value
    UI.set_visible = classmethod(lambda cls, target, visible: (calls.append((target, visible)), True)[1])
    UI.set_text = classmethod(lambda cls, target, text: (calls.append((target, text)), True)[1])
    UI.read_value = classmethod(lambda cls, target: (0.75, 3) if str(target) == "SetVolume" else (0.0, 0))
    try:
        ctx, inst, g, nid = _run_node("SetUIVisible", {"target": "DetailPanel", "visible": False}, _FakeCtx())
        check("SetUIVisible resolves props.target", calls == [("DetailPanel", False)], str(calls))

        calls.clear()
        ctx = _FakeCtx()
        ctx.dry_run = True
        ctx2, inst2, g2, nid2 = _run_node("SetUIVisible", {"target": "X", "visible": True}, ctx)
        check("dry-run writes nothing",
              calls == [] and any(log[2] == "set_ui_visible" for log in ctx.logs),
              str((calls, ctx.logs)))

        # SetUIText：props.text → 图层
        calls.clear()
        _run_node("SetUIText", {"target": "DetailTitle", "text": "Hi"}, _FakeCtx())
        check("SetUIText resolves props.target/text",
              calls == [("DetailTitle", "Hi")], str(calls))

        calls.clear()
        ctx = _FakeCtx()
        ctx.dry_run = True
        _run_node("SetUIText", {"target": "DetailTitle", "text": "Hi"}, ctx)
        check("SetUIText dry-run writes nothing",
              calls == [] and any(log[2] == "set_ui_text" for log in ctx.logs),
              str((calls, ctx.logs)))

        # OnUIClick 过滤
        ctx = _FakeCtx()
        ctx.input_event = SimpleNamespace(kind="ui_event", name="BtnPrimary",
                                          action="show:DetailPanel", value=0.0, index=0)
        _ctx, inst, g, nid = _run_node("OnUIClick", {"action": "show:DetailPanel"}, ctx)
        check("OnUIClick passes matching action", g.states.get((nid, "_blocked")) is False)
        check("OnUIClick writes Action/Name",
              ctx.pins.get(inst.pin_ids["Action"]) == "show:DetailPanel"
              and ctx.pins.get(inst.pin_ids["Name"]) == "BtnPrimary", str(ctx.pins))

        ctx = _FakeCtx()
        ctx.input_event = SimpleNamespace(kind="ui_event", name="B", action="other",
                                          value=1.0, index=0)
        _ctx, inst, g, nid = _run_node("OnUIClick", {"action": "show:DetailPanel"}, ctx)
        check("OnUIClick blocks non-matching action", g.states.get((nid, "_blocked")) is True)

        ctx = _FakeCtx()
        ctx.input_event = SimpleNamespace(kind="mouse_click", button=0, mods=0, x=0, y=0)
        _ctx, inst, g, nid = _run_node("OnUIClick", {}, ctx)
        check("OnUIClick ignores non-UI events", g.states.get((nid, "_blocked")) is True)

        ctx = _FakeCtx()
        _ctx, inst, g, nid = _run_node("GetUIValue", {"target": "SetVolume"}, ctx)
        check("GetUIValue reads the layer",
              ctx.pins.get(inst.pin_ids["Value"]) == 0.75
              and ctx.pins.get(inst.pin_ids["Index"]) == 3, str(ctx.pins))
    finally:
        UI.set_visible = real_set
        UI.set_text = real_set_text
        UI.read_value = real_read

    # ── 5. 全链：UI 点击 → OnUIClick → SetUIVisible（真示例场景）──
    print("-- 5. click -> node -> visibility --")
    from Application.Core.Scene.Scene import Scene
    import Application.Core.NodeGraph  # noqa: F401 — NodeCanvas 契约

    root = os.path.dirname(_d)
    scene_path = os.path.join(root, "Examples", "UIShowcase", "scenes", "UIShowcase.scene")

    class _Mgr:
        def __init__(self, sc):
            self._s = sc
            self._by = {}
            for eid, ed in sc.entities.items():
                for name, comp in ed.components.items():
                    self._by.setdefault(name, []).append((eid, comp))

        def GetAllEntitiesWithComponent(self, cls):
            return list(self._by.get(cls.__name__, ()))

        def GetEntityParent(self, eid):
            ed = self._s.entities.get(int(eid))
            return ed.parent_id if ed else None

        def GetEntityName(self, eid):
            ed = self._s.entities.get(int(eid))
            return ed.name if ed else ""

        def GetEntityByName(self, name):
            for eid, ed in self._s.entities.items():
                if ed.name == name:
                    return eid
            return -1

    sc = Scene.load_from_file(scene_path)
    mgr = _Mgr(sc)
    from Application.Core.UI.scene import collect_elements
    real_elements = collect_elements(mgr)
    saved_els = (UI._elements, UI._scene_result, UI._values, UI._overrides, UI._expanded,
                 UI._pressed_eid, UI._press_kind, UI._drag_track, UI._events, UI._texts)
    try:
        UI._elements = real_elements
        UI._values, UI._overrides, UI._expanded = {}, {}, 0
        UI._pressed_eid, UI._press_kind, UI._drag_track = 0, "", ()
        UI._events.clear()
        res = build_ui(real_elements, 1280, 720, text_fn=fake_text)
        UI._scene_result = res
        primary = next(h for h in res.hits if h.action == "show:DetailPanel")
        px, py = int(primary.rect[0] + primary.rect[2] / 2), int(primary.rect[1] + primary.rect[3] / 2)
        UI.OnEvent(MouseButtonEvent(0, 1, 0, px, py))
        UI.OnEvent(MouseButtonEvent(0, 0, 0, px, py))
        evs = UI.drain_events()
        check("button click yields a ui_event", len(evs) == 1
              and evs[0].kind == "ui_event" and evs[0].action == "show:DetailPanel",
              str(evs))

        from Application.Core.NodeGraph import _TYPES
        from Application.Core.NodeGraph.evaluator_engine import ExecutionContext, GraphEvaluator
        graph = sc.node_graph
        node_hint = next(e.eid for e in real_elements if e.name == "NodeHint")
        UI._overrides = {}
        ctx = ExecutionContext()
        ctx.scene = mgr
        ge = GraphEvaluator(graph, _TYPES)
        ge.trigger("OnGameStart", ctx)
        check("OnGameStart hides NodeHint", UI._overrides.get(node_hint) is False,
              str(UI._overrides))
        for record in evs:
            ctx.input_event = record
            ge.trigger("OnUIClick", ctx)
        check("OnUIClick -> SetUIVisible shows NodeHint",
              UI._overrides.get(node_hint) is True, str(UI._overrides))
        drawn = build_ui(real_elements, 1280, 720, visible_overrides=UI._overrides,
                         text_fn=fake_text)
        hidden = build_ui(real_elements, 1280, 720,
                          visible_overrides={node_hint: False}, text_fn=fake_text)
        marker = "Shown by the node graph"
        check("hidden label really disappears from the quad list",
              any(marker in q.key for q in drawn.quads)
              and not any(marker in q.key for q in hidden.quads))

        # ── 标签文本覆盖（SetUIText 的运行期路径）──
        UI._texts = {}
        label_eid = next(e.eid for e in real_elements
                        if e.label is not None and e.name == "DetailTitle")
        original = str(UI.get_text(label_eid))
        check("get_text falls back to UILabel.text", bool(original), repr(original))
        check("set_text by name stores the override",
              UI.set_text("DetailTitle", "Trial 3 / 12")
              and UI.get_text("DetailTitle") == "Trial 3 / 12"
              and UI._texts.get(label_eid) == "Trial 3 / 12", str(UI._texts))
        with_text = build_ui(real_elements, 1280, 720, texts=UI._texts, text_fn=fake_text)
        check("text override reaches the quad list",
              any("Trial 3 / 12" in q.key for q in with_text.quads)
              and not any(original in q.key for q in with_text.quads))
        check("set_text with empty text clears the override",
              UI.set_text("DetailTitle", "") and label_eid not in UI._texts
              and UI.get_text("DetailTitle") == original, str(UI._texts))
        check("set_text unknown target -> False",
              UI.set_text("NoSuchLabel", "x") is False)
    finally:
        (UI._elements, UI._scene_result, UI._values, UI._overrides, UI._expanded,
         UI._pressed_eid, UI._press_kind, UI._drag_track, UI._events,
         UI._texts) = saved_els
        UI._events.clear()

    total = _RESULTS["pass"] + _RESULTS["fail"]
    status = "OK" if _RESULTS["fail"] == 0 else "FAIL"
    print()
    print(f"RESULT: {status} ({_RESULTS['pass']}/{total})")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
