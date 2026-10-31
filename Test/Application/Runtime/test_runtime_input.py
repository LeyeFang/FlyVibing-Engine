"""RuntimeInputLayer + 输入事件节点 — 无头测试。

覆盖:
  1. 输入队列 drain：键按下/释放、鼠标位置/按钮、滚轮
  2. ESC 策略：exit_on_escape=False 时 consume 关闭事件
  3. 图节点 OnKeyPressed / OnMouseClicked 过滤与输出
  4. 数据节点 IsKeyDown / GetMousePosition 读取 ctx.input

运行: python Utils/Dev/test_runner.py --only runtime_input
"""
# TIER: core

from __future__ import annotations

import os
import shutil
import sys
import tempfile

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "_path_setup.py")):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)
    import _path_setup  # noqa: F401

from Application.Core.Events.Enum.InputEnum import (  # noqa: E402
    KeyActionCode,
    KeyButtonCode,
    MouseActionCode,
    MouseButtonCode,
)
from Application.Core.Events.InputEvent import KeyboardButtonEvent  # noqa: E402
from Application.Core.Events.WindowEvent import WindowCloseEvent  # noqa: E402
from Application.Core.NodeGraph import (  # noqa: E402
    ExecutionContext,
    GraphEvaluator,
    NodeCanvas,
    _TYPES,
)
from Application.Runtime.RuntimeInputLayer import (  # noqa: E402
    InputEventRecord,
    RuntimeInputFrame,
    RuntimeInputLayer,
)
from Application.Runtime.RuntimeNodeLayer import RuntimeNodeLayer  # noqa: E402

_RESULTS = {"pass": 0, "fail": 0}
_seq = [9200]


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


def _node(type_name: str, props: dict | None = None) -> dict:
    pids: dict[str, int] = {}
    for p in _TYPES[type_name].pins:
        _seq[0] += 1
        pids[p.name] = _seq[0]
    return {"node_type": type_name, "pos": [0.0, 0.0],
            "props": props or {}, "pin_ids": pids}


def _graph(nodes: dict[int, dict], links: list[tuple]) -> dict:
    links_d: dict[str, dict] = {}
    for i, (fn, fp, tn, tp) in enumerate(links):
        links_d[str(i + 1)] = {
            "from_pin": nodes[fn]["pin_ids"][fp],
            "to_pin": nodes[tn]["pin_ids"][tp],
        }
    return {
        "version": "0.1.0",
        "nodes": {str(nid): nd for nid, nd in nodes.items()},
        "links": links_d,
        "next_id": _seq[0] + 1,
    }


def _eval_pin(g: GraphEvaluator, pin_id: int, ctx: ExecutionContext):
    ctx._pin_values.clear()
    g._eval_guard.clear()
    g._ensure_pin_evaluated(pin_id, ctx)
    return ctx.get_pin(pin_id)


def test_layer_queue() -> None:
    print("── 1. RuntimeInputLayer queue ──")
    RuntimeInputLayer.exit_on_escape = True
    RuntimeInputLayer.OnAttach()
    try:
        RuntimeInputLayer.inject_key(KeyButtonCode.Space, KeyActionCode.Press, 0)
        RuntimeInputLayer.inject_key(KeyButtonCode.A, KeyActionCode.Press, 2)
        frame = RuntimeInputLayer.drain_frame()
        check("key presses count", len(frame.key_presses) == 2, str(frame.key_presses))
        check("held keys", frame.held_keys == {int(KeyButtonCode.Space),
                                               int(KeyButtonCode.A)},
              str(frame.held_keys))

        RuntimeInputLayer.inject_key(KeyButtonCode.Space, KeyActionCode.Release, 0)
        RuntimeInputLayer.inject_mouse_move(12, 34)
        RuntimeInputLayer.inject_mouse_button(
            MouseButtonCode.Left, MouseActionCode.Press, 0, 12, 34)
        frame = RuntimeInputLayer.drain_frame()
        check("key release", len(frame.key_releases) == 1)
        check("mouse pos", frame.mouse_x == 12 and frame.mouse_y == 34,
              f"{frame.mouse_x},{frame.mouse_y}")
        check("mouse pressed", len(frame.mouse_presses) == 1
              and frame.mouse_buttons == {int(MouseButtonCode.Left)})
        check("space removed from held", int(KeyButtonCode.Space) not in frame.held_keys)
        check("drain clears queue", not RuntimeInputLayer.drain_frame().has_events)

        RuntimeInputLayer.OnEvent(KeyboardButtonEvent(
            int(KeyButtonCode.Enter), 0, int(KeyActionCode.Press), 0))
        frame = RuntimeInputLayer.drain_frame()
        check("OnEvent keyboard reaches queue",
              len(frame.key_presses) == 1
              and frame.key_presses[0].key == int(KeyButtonCode.Enter))

        RuntimeInputLayer.inject_key(KeyButtonCode.B, KeyActionCode.Repeat, 0)
        frame = RuntimeInputLayer.drain_frame()
        check("key repeat queued separately",
              len(frame.key_repeats) == 1
              and frame.key_repeats[0].key == int(KeyButtonCode.B))

        RuntimeInputLayer.inject_mouse_button(
            MouseButtonCode.Left, MouseActionCode.Release, 0, 12, 34)
        RuntimeInputLayer.inject_scroll(0, -1)
        frame = RuntimeInputLayer.drain_frame()
        check("mouse release/scroll", len(frame.mouse_releases) == 1
              and len(frame.scrolls) == 1
              and frame.scrolls[0].scroll_y == -1)
        check("stationary press+release = click",
              len(frame.mouse_clicks) == 1
              and frame.mouse_clicks[0].button == int(MouseButtonCode.Left))
        check("mouse no longer held", not frame.mouse_buttons)

        # Right-drag must not become a click.
        RuntimeInputLayer.inject_mouse_button(
            MouseButtonCode.Right, MouseActionCode.Press, 0, 40, 40)
        RuntimeInputLayer.inject_mouse_button(
            MouseButtonCode.Right, MouseActionCode.Release, 0, 80, 40)
        frame = RuntimeInputLayer.drain_frame()
        check("right drag is not a click",
              len(frame.mouse_releases) == 1 and not frame.mouse_clicks)
    finally:
        RuntimeInputLayer.OnDetach()


def test_escape_policy() -> None:
    print("── 2. ESC policy ──")
    RuntimeInputLayer.OnAttach()
    try:
        RuntimeInputLayer.set_escape_exit(True)
        ev = WindowCloseEvent(source="escape")
        RuntimeInputLayer.OnEvent(ev)
        check("default ESC passes through", not ev.consumed)

        RuntimeInputLayer.set_escape_exit(False)
        ev2 = WindowCloseEvent(source="escape")
        RuntimeInputLayer.OnEvent(ev2)
        check("exit_on_escape=False consumes ESC", ev2.consumed)

        ev3 = WindowCloseEvent(source="window")
        RuntimeInputLayer.OnEvent(ev3)
        check("title-bar close still passes", not ev3.consumed)
    finally:
        RuntimeInputLayer.set_escape_exit(True)
        RuntimeInputLayer.OnDetach()


def test_event_nodes(tmp: str) -> None:
    print("── 3. input event nodes ──")
    nodes = {
        1: _node("OnKeyPressed", {"key": "Space", "mods": "any"}),
        2: _node("SaveData", {
            "mode": "manual", "format": "json", "file_path": tmp,
            "file_name": "key_hit", "unique": False, "value": "1",
        }),
    }
    canvas = NodeCanvas.from_dict(_graph(nodes, [(1, "exec", 2, "exec_in")]))
    ctx = ExecutionContext()
    g = GraphEvaluator(canvas, _TYPES)

    ctx.input_event = InputEventRecord(kind="key_press", key=int(KeyButtonCode.A))
    g.trigger("OnKeyPressed", ctx)
    check("wrong key blocked", not os.path.exists(
        os.path.join(tmp, "key_hit.json")))

    ctx.input_event = InputEventRecord(
        kind="key_press", key=int(KeyButtonCode.Space), mods=0)
    g.trigger("OnKeyPressed", ctx)
    check("matching key runs chain",
          os.path.isfile(os.path.join(tmp, "key_hit.json")))

    nodes2 = {
        1: _node("OnMouseClicked", {"button": "Left", "mods": "any"}),
    }
    canvas2 = NodeCanvas.from_dict(_graph(nodes2, []))
    ctx2 = ExecutionContext()
    g2 = GraphEvaluator(canvas2, _TYPES)
    ctx2.input_event = InputEventRecord(
        kind="mouse_click", button=int(MouseButtonCode.Left), x=7, y=9)
    g2.trigger("OnMouseClicked", ctx2)
    p = canvas2.nodes[1].pin_ids
    check("mouse outputs button/pos",
          ctx2.get_pin(p["Button"]) == int(MouseButtonCode.Left)
          and ctx2.get_pin(p["X"]) == 7 and ctx2.get_pin(p["Y"]) == 9,
          f"{ctx2.get_pin(p['Button'])} {ctx2.get_pin(p['X'])} {ctx2.get_pin(p['Y'])}")

    ctx2.input_event = InputEventRecord(
        kind="mouse_click", button=int(MouseButtonCode.Right), x=1, y=2)
    g2.trigger("OnMouseClicked", ctx2)
    check("wrong mouse button blocked", ctx2.get_pin(p["X"]) is None)


def test_node_layer_dispatch(tmp: str) -> None:
    print("-- 5. RuntimeNodeLayer dispatch --")
    nodes = {
        1: _node("OnKeyPressed", {"key": "Space", "mods": "any"}),
        2: _node("SaveData", {
            "mode": "manual", "format": "json", "file_path": tmp,
            "file_name": "layer_hit", "unique": False, "value": "1",
        }),
    }
    canvas = NodeCanvas.from_dict(_graph(nodes, [(1, "exec", 2, "exec_in")]))
    RuntimeInputLayer.OnAttach()
    RuntimeNodeLayer._evaluator = GraphEvaluator(canvas, _TYPES)
    RuntimeNodeLayer._context = ExecutionContext()
    try:
        RuntimeInputLayer.inject_key(KeyButtonCode.Space, KeyActionCode.Press, 0)
        RuntimeNodeLayer._dispatch_input_events()
        check("node layer consumes frame",
              RuntimeNodeLayer._context.input is not None)
        check("node layer fires input graph",
              os.path.isfile(os.path.join(tmp, "layer_hit.json")))
        RuntimeNodeLayer._dispatch_input_events()
        check("empty frame no repeat",
              not RuntimeNodeLayer._context.input.has_events)
    finally:
        RuntimeNodeLayer._evaluator = None
        RuntimeNodeLayer._context = None
        RuntimeInputLayer.OnDetach()


def test_node_layer_mouse_click(tmp: str) -> None:
    print("-- 6. RuntimeNodeLayer mouse click --")
    nodes = {
        1: _node("OnMouseClicked", {"button": "Left", "mods": "any"}),
        2: _node("SaveData", {
            "mode": "manual", "format": "json", "file_path": tmp,
            "file_name": "mouse_layer_hit", "unique": False, "value": "1",
        }),
    }
    canvas = NodeCanvas.from_dict(_graph(nodes, [(1, "exec", 2, "exec_in")]))
    RuntimeInputLayer.OnAttach()
    RuntimeNodeLayer._evaluator = GraphEvaluator(canvas, _TYPES)
    RuntimeNodeLayer._context = ExecutionContext()
    try:
        RuntimeInputLayer.inject_mouse_button(
            MouseButtonCode.Left, MouseActionCode.Press, 0, 20, 20)
        RuntimeInputLayer.inject_mouse_button(
            MouseButtonCode.Left, MouseActionCode.Release, 0, 20, 20)
        RuntimeNodeLayer._dispatch_input_events()
        check("mouse click fires OnMouseClicked chain",
              os.path.isfile(os.path.join(tmp, "mouse_layer_hit.json")))

        canvas.nodes[2].props["file_name"] = "mouse_drag_hit"
        RuntimeInputLayer.inject_mouse_button(
            MouseButtonCode.Right, MouseActionCode.Press, 0, 20, 20)
        RuntimeInputLayer.inject_mouse_button(
            MouseButtonCode.Right, MouseActionCode.Release, 0, 60, 20)
        RuntimeNodeLayer._dispatch_input_events()
        check("mouse drag does not fire click chain",
              not os.path.isfile(os.path.join(tmp, "mouse_drag_hit.json")))
    finally:
        RuntimeNodeLayer._evaluator = None
        RuntimeNodeLayer._context = None
        RuntimeInputLayer.OnDetach()


def test_data_nodes() -> None:
    print("── 4. input data nodes ──")
    nodes = {
        1: _node("IsKeyDown", {"key": "Space"}),
        2: _node("IsMouseButtonDown", {"button": "Left"}),
        3: _node("GetMousePosition"),
    }
    canvas = NodeCanvas.from_dict(_graph(nodes, []))
    ctx = ExecutionContext()
    ctx.input = RuntimeInputFrame(
        mouse_x=42, mouse_y=24,
        held_keys=frozenset({int(KeyButtonCode.Space)}),
        mouse_buttons=frozenset({int(MouseButtonCode.Left)}),
    )
    g = GraphEvaluator(canvas, _TYPES)
    check("IsKeyDown true", _eval_pin(g, canvas.nodes[1].pin_ids["Down"], ctx) == 1)
    check("IsMouseButtonDown true",
          _eval_pin(g, canvas.nodes[2].pin_ids["Down"], ctx) == 1)
    check("GetMousePosition",
          _eval_pin(g, canvas.nodes[3].pin_ids["X"], ctx) == 42
          and _eval_pin(g, canvas.nodes[3].pin_ids["Y"], ctx) == 24)

    ctx.input = RuntimeInputFrame()
    check("IsKeyDown false when empty",
          _eval_pin(g, canvas.nodes[1].pin_ids["Down"], ctx) == 0)


def main() -> int:
    print("== Runtime input tests ==")
    tmp = tempfile.mkdtemp(prefix="runtime_input_test_")
    try:
        test_layer_queue()
        test_escape_policy()
        test_event_nodes(tmp)
        test_data_nodes()
        test_node_layer_dispatch(tmp)
        test_node_layer_mouse_click(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    total = _RESULTS["pass"] + _RESULTS["fail"]
    ok = _RESULTS["fail"] == 0
    print()
    print(f"RESULT: {'OK' if ok else 'FAIL'} ({_RESULTS['pass']}/{total})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
