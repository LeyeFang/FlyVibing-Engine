"""
LiveCommandServer — 无头回环测试。

真实 socket + 主线程手动 pump（模拟编辑器帧循环），验证:
  1. 生命周期（port=0 系统分配; stop 后端口关闭）
  2. sim.play 往返（SimulationController._pending_start 置位）
  3. view.set_mode 2d/3d 往返（ViewportController 真实切换）
  4. editor.quit 往返（无窗口 → run_state 回退路径）
  5. 受控错误：未知 op / 非法 JSON
  6. 单连接复用（一条连接两条命令）
  7. 边界：FlyVibing-User-And-Developer-Utils/packages/editor-mcp/（dev shim + 独立包源码）不得 import Application（纯 socket 客户端）
  8. v2 实时通道：sim.stop / sim.state、camera 受控错误、frame 二进制尾随帧往返
  9. v3 容器 ops：entity/component 受控错误、selection/scene/resource 无头冒烟
  10. v4 图校验/导入导出/工程：graph.validate.*（source=graph）、report 落盘、受控错误

用法:
    .venv-py314t\\Scripts\\python.exe Test/Application/Editor/test_live_command_server.py
"""

from __future__ import annotations

import json
import os
import re
import socket
import sys
import threading
import time

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "_path_setup.py")):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)
    import _path_setup  # noqa: F401

ROOT = os.path.dirname(_d)

from Application.Editor.Services.LiveCommandServer import LiveCommandServer  # noqa: E402

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


# ────────────────────────────────────────────────────────────────
# 客户端线程 + 主线程 pump 的往返驱动
# ────────────────────────────────────────────────────────────────


def roundtrip(port: int, op: str, args: dict | None = None, timeout: float = 10.0) -> dict:
    """发一条请求; 主线程循环 pump（模拟帧循环）直到收到回执。"""
    box: dict = {}

    def _client() -> None:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=10.0) as conn:
                req = {"id": 1, "op": op, "args": args or {}}
                conn.sendall((json.dumps(req, ensure_ascii=False) + "\n").encode("utf-8"))
                line = conn.makefile("r", encoding="utf-8", newline="\n").readline()
                box.update(json.loads(line) if line else {"ok": False, "error": "no response"})
        except OSError as e:
            box.update({"ok": False, "error": f"client: {e}"})

    t = threading.Thread(target=_client, daemon=True)
    t.start()
    deadline = time.monotonic() + timeout
    while t.is_alive() and time.monotonic() < deadline:
        LiveCommandServer.pump()
        time.sleep(0.02)
    t.join(timeout=1.0)
    return box or {"ok": False, "error": "client timeout"}


def multi_roundtrip(port: int, ops: list[tuple[str, dict]], timeout: float = 15.0) -> list[dict | None]:
    """单连接顺序发多条命令; 主线程循环 pump。"""
    box: dict = {"responses": []}

    def _client() -> None:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=10.0) as conn:
                reader = conn.makefile("r", encoding="utf-8", newline="\n")
                for i, (op, args) in enumerate(ops):
                    req = {"id": i + 1, "op": op, "args": args}
                    conn.sendall((json.dumps(req, ensure_ascii=False) + "\n").encode("utf-8"))
                    line = reader.readline()
                    box["responses"].append(json.loads(line) if line else None)
        except OSError as e:
            box["error"] = f"client: {e}"

    t = threading.Thread(target=_client, daemon=True)
    t.start()
    deadline = time.monotonic() + timeout
    while t.is_alive() and time.monotonic() < deadline:
        LiveCommandServer.pump()
        time.sleep(0.02)
    t.join(timeout=1.0)
    return box.get("responses", [])


def roundtrip_binary(port: int, op: str, args: dict | None = None, timeout: float = 10.0) -> dict:
    """发一条请求; 主线程 pump; 读回执行 + 可选二进制尾随负载。

    Returns: {**resp, "payload": bytes}（无负载时 payload 为 b""）。
    """
    box: dict = {}

    def _client() -> None:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=10.0) as conn:
                req = {"id": 1, "op": op, "args": args or {}}
                conn.sendall((json.dumps(req, ensure_ascii=False) + "\n").encode("utf-8"))
                reader = conn.makefile("rb")
                line = reader.readline()
                resp = json.loads(line.decode("utf-8")) if line else {"ok": False, "error": "no response"}
                n = 0
                result = resp.get("result")
                if isinstance(result, dict) and result.get("binary_bytes"):
                    n = int(result["binary_bytes"])
                payload = reader.read(n) if n else b""
                box.update(resp)
                box["payload"] = payload
        except OSError as e:
            box.update({"ok": False, "error": f"client: {e}", "payload": b""})

    t = threading.Thread(target=_client, daemon=True)
    t.start()
    deadline = time.monotonic() + timeout
    while t.is_alive() and time.monotonic() < deadline:
        LiveCommandServer.pump()
        time.sleep(0.02)
    t.join(timeout=1.0)
    return box or {"ok": False, "error": "client timeout", "payload": b""}


def main() -> int:
    print("=" * 60)
    print("LiveCommandServer — Headless Loopback Tests")
    print("=" * 60)

    # ── 事件系统引导（模拟编辑器最小环境 — op 处理器内部会 Pack 事件）──
    from Application.Core.Engine import Engine
    from Application.Core.Events.Event import BindPackCallback, _register_engine
    from Application.Core.Input.InputState import _set_default_input_state

    _register_engine(Engine)
    BindPackCallback(Engine._on_event)
    _set_default_input_state(Engine._get_input_state())

    from Application.Editor.UI.controllers.SimulationController import (
        SimulationController,
        SimulationState,
    )
    from Application.Editor.UI.controllers.ViewportController import ViewportController
    from Application.Editor.EditorHost import EditorHost

    # ── 1. 生命周期 ──
    print("── Lifecycle ──")
    ok = LiveCommandServer.start(port=0)
    check("server starts (ephemeral port)", ok)
    port = LiveCommandServer.port
    check("ephemeral port assigned", port > 0, str(port))

    # ── 2. sim.play ──
    print("── sim.play ──")
    SimulationController._pending_start = False
    resp = roundtrip(port, "sim.play")
    check("sim.play ok", resp.get("ok") is True, str(resp))
    check("requested=True", (resp.get("result") or {}).get("requested") is True, str(resp))
    check("_pending_start set by main thread", SimulationController._pending_start is True)
    SimulationController._pending_start = False  # 测试清理（不真的启动 PIE）

    # ── 2b. PIE 可运行性检查 (模板语义兜底 — 2026-10-16) ──
    print("── sim.play runnability check ──")
    import esper as _esper
    from Application.Core.Scene.BasicComponents import MeshRenderer as _MR

    _prev_scene = EditorHost._active_scene
    _eid = _esper.create_entity()
    _esper.add_component(_eid, _MR(material_id=1))  # 非 0 跳过默认材质查找 (无 ResourceManager)
    resp = roundtrip(port, "sim.play")
    _w = str((resp.get("result") or {}).get("warning", ""))
    check("warning when entities exist but no EntitySpawn", "EntitySpawn" in _w, str(resp))
    SimulationController._pending_start = False

    class _SpawnNode:
        node_type = "EntitySpawn"

    class _CanvasStub:
        nodes = {101: _SpawnNode()}

    class _SceneStub:
        node_graph = _CanvasStub()

    EditorHost._active_scene = _SceneStub()
    resp = roundtrip(port, "sim.play")
    check("no warning when EntitySpawn present",
          "warning" not in (resp.get("result") or {}), str(resp))
    SimulationController._pending_start = False
    EditorHost._active_scene = _prev_scene
    _esper.delete_entity(_eid)

    # ── 3. view.set_mode ──
    print("── view.set_mode ──")
    resp = roundtrip(port, "view.set_mode", {"mode": "2d"})
    check("2d ok", resp.get("ok") is True, str(resp))
    check("mode=2d", (resp.get("result") or {}).get("mode") == "2d", str(resp))
    check("ViewportController.is_2d()", ViewportController.is_2d() is True)
    resp = roundtrip(port, "view.set_mode", {"mode": "3d"})
    check("3d ok", resp.get("ok") is True, str(resp))
    check("ViewportController.is_3d()", ViewportController.is_3d() is True)
    resp = roundtrip(port, "view.set_mode", {"mode": "5d"})
    check("bad mode → controlled error", resp.get("ok") is False and "unsupported" in str(resp.get("error")), str(resp))

    # ── 3b. view.set_grid ──
    print("── view.set_grid ──")
    from Application.Editor.Gizmos.Grid import Grid
    check("grid visible by default", Grid.visible is True)
    resp = roundtrip(port, "view.set_grid", {"visible": False})
    check("set_grid false ok", resp.get("ok") is True, str(resp))
    check("result visible=False", (resp.get("result") or {}).get("visible") is False, str(resp))
    check("Grid.visible flipped", Grid.visible is False)
    resp = roundtrip(port, "view.set_grid", {"visible": True})
    check("set_grid true ok", (resp.get("result") or {}).get("visible") is True, str(resp))
    check("Grid.visible restored", Grid.visible is True)
    resp = roundtrip(port, "view.set_grid", {})
    check("missing visible → controlled error",
          resp.get("ok") is False and "visible" in str(resp.get("error")), str(resp))

    # ── 3c. ui.panels / ui.panel（面板打开关闭闭环）──
    print("── ui.panels / ui.panel ──")
    from Application.Editor.UI.BasePanel import BasePanel
    from Application.Editor.UI.UIManager import UIManager

    class _TestPanel(BasePanel):
        name = "Loopback Panel"
        visible = True

        def draw(self) -> None:
            pass

    _panel = UIManager.register(_TestPanel())
    try:
        resp = roundtrip(port, "ui.panels", {})
        names = [p.get("name") for p in (resp.get("result") or {}).get("panels", [])]
        check("ui.panels lists panel", "Loopback Panel" in names, str(resp))
        resp = roundtrip(port, "ui.panel", {"name": "Loopback Panel"})
        check("ui.panel read visible", (resp.get("result") or {}).get("visible") is True, str(resp))
        resp = roundtrip(port, "ui.panel", {"name": "Loopback Panel", "visible": False})
        check("ui.panel close ok", (resp.get("result") or {}).get("visible") is False, str(resp))
        check("panel.visible closed", UIManager.find("Loopback Panel").visible is False)
        resp = roundtrip(port, "ui.panel", {"name": "Loopback Panel", "toggle": True})
        check("ui.panel toggle ok", (resp.get("result") or {}).get("visible") is True, str(resp))
        check("panel.visible reopened", UIManager.find("Loopback Panel").visible is True)
        resp = roundtrip(port, "ui.panel", {"name": "No Such Panel"})
        check("unknown panel → controlled error",
              resp.get("ok") is False and "unknown panel" in str(resp.get("error")), str(resp))
    finally:
        UIManager.unregister(_panel)

    # ── 3c2. graph description（节点描述读写）──
    print("── graph description ──")
    from Application.Core.NodeGraph.canvas import NodeCanvas

    class _NodePanel(_TestPanel):
        name = "Node Editor"
        _canvas = NodeCanvas()

    _node_panel = UIManager.register(_NodePanel())
    try:
        resp = roundtrip(port, "graph.add", {"type": "Constant",
                                              "description": "seed value"})
        nid = int((resp.get("result") or {}).get("node_id", -1))
        check("graph.add description",
              (resp.get("result") or {}).get("description") == "seed value", str(resp))
        resp = roundtrip(port, "graph.set_description",
                         {"node": nid, "description": "Used by the trial counter."})
        check("graph.set_description write",
              (resp.get("result") or {}).get("description") ==
              "Used by the trial counter.", str(resp))
        resp = roundtrip(port, "graph.list")
        item = next((n for n in (resp.get("result") or {}).get("nodes", [])
                     if n.get("id") == nid), {})
        check("graph.list exposes description",
              item.get("description") == "Used by the trial counter.", str(item))
        resp = roundtrip(port, "graph.set_description", {"node": nid})
        check("graph.set_description read",
              (resp.get("result") or {}).get("description") ==
              "Used by the trial counter.", str(resp))
        resp = roundtrip(port, "graph.set_description",
                         {"node": nid, "description": ""})
        check("graph.set_description clear",
              (resp.get("result") or {}).get("description") == "", str(resp))
    finally:
        UIManager.unregister(_node_panel)

    # ── 3d. threads.snapshot（线程注册表 — 开发协议验证）──
    print("── threads.snapshot ──")
    import time as _t
    from Application.Core.ThreadRegistry import ThreadRegistry
    ThreadRegistry.register("probe-test", owner="loopback", expect_hz=0.0)
    ThreadRegistry.heartbeat("probe-test")
    resp = roundtrip(port, "threads.snapshot")
    check("threads.snapshot ok", resp.get("ok") is True, str(resp))
    snap = resp.get("result") or {}
    check("snapshot structure",
          {"registered", "unregistered", "stale", "count"} <= set(snap),
          str(sorted(snap.keys())))
    reg = {t["name"]: t for t in snap.get("registered", [])}
    check("accept thread registered", "LiveCommandServer" in reg, str(sorted(reg)))
    check("client thread registered", any(n.startswith("live-client:") for n in reg),
          str(sorted(reg)))
    check("probe-test beats >= 1", reg.get("probe-test", {}).get("beats", 0) >= 1,
          str(reg.get("probe-test")))
    ThreadRegistry.register("probe-stale", owner="loopback", expect_hz=4.0)
    _t.sleep(1.15)
    resp = roundtrip(port, "threads.snapshot")
    stale = (resp.get("result") or {}).get("stale", [])
    check("stale detection (probe-stale)", "probe-stale" in stale, str(stale))
    ThreadRegistry.unregister("probe-stale")
    ThreadRegistry.unregister("probe-test")

    # ── 3e. renderer.snapshot（渲染器状态 — 无头路径 available=false）──
    print("── renderer.snapshot ──")
    resp = roundtrip(port, "renderer.snapshot")
    check("renderer.snapshot ok", resp.get("ok") is True, str(resp))
    rsnap = resp.get("result") or {}
    check("headless → available=false (+reason)",
          rsnap.get("available") is False and bool(rsnap.get("reason")), str(rsnap))

    # ── 4. editor.quit ──
    print("── editor.quit ──")
    prior_run_state = EditorHost.run_state
    resp = roundtrip(port, "editor.quit")
    check("quit ok", resp.get("ok") is True, str(resp))
    check("closing=True", (resp.get("result") or {}).get("closing") is True, str(resp))
    check("headless fallback sets run_state False", EditorHost.run_state is False)
    EditorHost.run_state = prior_run_state  # 测试清理

    # ── 5. 受控错误 ──
    print("── Controlled errors ──")
    resp = roundtrip(port, "no.such.op")
    check("unknown op → error", resp.get("ok") is False and "unknown op" in str(resp.get("error")), str(resp))

    with socket.create_connection(("127.0.0.1", port), timeout=10.0) as conn:
        conn.sendall(b"this is not json\n")
        line = conn.makefile("r", encoding="utf-8", newline="\n").readline()
    bad = json.loads(line) if line else {}
    check("invalid JSON → error", bad.get("ok") is False and "invalid request" in str(bad.get("error")), str(bad))

    # ── 6. 单连接复用 ──
    print("── Single-connection reuse ──")
    responses = multi_roundtrip(port, [
        ("view.set_mode", {"mode": "2d"}),
        ("view.set_mode", {"mode": "3d"}),
    ])
    check("two responses", len(responses) == 2, str(responses))
    check("both ok", all(r and r.get("ok") for r in responses), str(responses))

    # ── 7. v2: sim.stop / sim.state ──
    print("── sim.stop / sim.state ──")
    resp = roundtrip(port, "sim.state")
    check("sim.state ok", resp.get("ok") is True, str(resp))
    check("state=Stopped", (resp.get("result") or {}).get("state") == "Stopped", str(resp))
    check("runtime_alive=False", (resp.get("result") or {}).get("runtime_alive") is False, str(resp))
    resp = roundtrip(port, "sim.stop")
    check("stop while stopped → requested False", (resp.get("result") or {}).get("requested") is False, str(resp))
    # 模拟 RUNNING 状态（无头环境不真正启动 PIE）
    SimulationController._state = SimulationState.RUNNING
    resp = roundtrip(port, "sim.state")
    check("state=Running", (resp.get("result") or {}).get("state") == "Running", str(resp))
    resp = roundtrip(port, "sim.stop")
    check("stop requested", (resp.get("result") or {}).get("requested") is True, str(resp))
    check("_pending_stop set by main thread", SimulationController._pending_stop is True)
    SimulationController._pending_stop = False   # 测试清理
    SimulationController._state = SimulationState.STOPPED

    # ── 8. v2: camera 受控错误（无活跃场景）──
    print("── camera ops (no scene) ──")
    resp = roundtrip(port, "camera.get", {"role": "3d"})
    check("camera.get no scene → error", resp.get("ok") is False and "scene" in str(resp.get("error")), str(resp))
    resp = roundtrip(port, "camera.set", {"role": "3d", "position": [0, 0, 10]})
    check("camera.set no scene → error", resp.get("ok") is False and "scene" in str(resp.get("error")), str(resp))

    # ── 9. v2: frame 抓帧（二进制尾随帧协议 — 手动模拟渲染线程发布）──
    print("── frame.request / frame.fetch (binary trailer) ──")
    resp = roundtrip(port, "frame.request", {"target": "pie"})
    check("pie not running → controlled error",
          resp.get("ok") is False and "not running" in str(resp.get("error")), str(resp))

    resp = roundtrip(port, "frame.request", {"target": "editor"})
    gen = (resp.get("result") or {}).get("generation")
    check("frame.request ok", resp.get("ok") is True and isinstance(gen, int), str(resp))

    # 手动模拟渲染线程发布 2x2 红色 RGBA 帧（headless 无 GL）
    red = bytes([255, 0, 0, 255]) * 4
    EditorHost._capture_slot().publish(gen, 2, 2, red)
    resp = roundtrip_binary(port, "frame.fetch", {"target": "editor", "generation": gen})
    result = resp.get("result") or {}
    check("fetch ready", result.get("ready") is True, str(resp))
    check("binary_bytes=16", result.get("binary_bytes") == 16, str(resp))
    check("payload intact (wire)", resp.get("payload") == red, repr(resp.get("payload")))

    # superseded: 旧代请求被新代覆盖
    gen1 = roundtrip(port, "frame.request", {"target": "editor"})["result"]["generation"]
    gen2 = roundtrip(port, "frame.request", {"target": "editor"})["result"]["generation"]
    EditorHost._capture_slot().publish(gen2, 1, 1, bytes([0, 0, 0, 0]))
    resp = roundtrip(port, "frame.fetch", {"target": "editor", "generation": gen1})
    check("stale gen → superseded", (resp.get("result") or {}).get("state") == "superseded", str(resp))
    EditorHost._capture_slot().take_pending()   # 清理未消费请求

    # pending: 尚未发布
    gen3 = roundtrip(port, "frame.request", {"target": "editor"})["result"]["generation"]
    resp = roundtrip(port, "frame.fetch", {"target": "editor", "generation": gen3})
    check("not yet captured → pending", (resp.get("result") or {}).get("state") == "pending", str(resp))
    EditorHost._capture_slot().take_pending()   # 清理未消费请求

    # ── 9.5 v3: 容器 ops 冒烟（无场景环境 → 受控错误 / 空结果）──
    print("── v3 container ops smoke ──")
    resp = roundtrip(port, "entity.list")
    check("entity.list no scene → error",
          resp.get("ok") is False and "no active scene" in str(resp.get("error")), str(resp))
    resp = roundtrip(port, "entity.add", {"name": "x"})
    check("entity.add no scene → error",
          resp.get("ok") is False and "no active scene" in str(resp.get("error")), str(resp))
    resp = roundtrip(port, "entity.get", {"name": "whatever"})
    check("entity.get no scene → error",
          resp.get("ok") is False and "no active scene" in str(resp.get("error")), str(resp))
    resp = roundtrip(port, "component.types")
    check("component.types no scene → error",
          resp.get("ok") is False and "no active scene" in str(resp.get("error")), str(resp))
    resp = roundtrip(port, "selection.get")
    check("selection.get ok (None)",
          resp.get("ok") is True and (resp.get("result") or {}).get("entity_id") is None, str(resp))
    resp = roundtrip(port, "selection.clear")
    check("selection.clear ok", resp.get("ok") is True, str(resp))
    resp = roundtrip(port, "scene.list")
    check("scene.list ok",
          resp.get("ok") is True and "scenes" in (resp.get("result") or {})
          and "active" in (resp.get("result") or {}), str(resp))
    resp = roundtrip(port, "resource.list", {"kind": "mesh"})
    check("resource.list ok (empty ok)",
          resp.get("ok") is True and isinstance((resp.get("result") or {}).get("items"), list), str(resp))
    resp = roundtrip(port, "resource.list", {"kind": "bogus"})
    check("resource.list bad kind → error",
          resp.get("ok") is False and "unknown resource kind" in str(resp.get("error")), str(resp))
    resp = roundtrip(port, "resource.find", {"kind": "material", "name": "Nope"})
    check("resource.find empty ok",
          resp.get("ok") is True and (resp.get("result") or {}).get("count") == 0, str(resp))

    # ── 10. 边界: MCP 客户端（dev shim + 独立包）不 import Application ──
    print("── Boundary scan (FlyVibing-User-And-Developer-Utils/packages/editor-mcp) ──")
    forbidden = re.compile(r"^[ \t]*(?:from|import)[ \t]+Application\b", re.MULTILINE)
    scan_dirs = [
        os.path.join(ROOT, "Utils", "ExtDev", "EditorMcp"),
        os.path.join(ROOT, "Utils", "ExtDev", "EditorMcp", "src", "engine_editor_mcp"),
    ]
    offenders: list[str] = []
    for scan_dir in scan_dirs:
        if not os.path.isdir(scan_dir):
            continue
        for fname in sorted(os.listdir(scan_dir)):
            if not fname.endswith(".py"):
                continue
            with open(os.path.join(scan_dir, fname), encoding="utf-8") as fh:
                for m in forbidden.finditer(fh.read()):
                    offenders.append(f"{fname}: {m.group(0).strip()}")
    check("no Application imports (client side)", not offenders, "; ".join(offenders))

    # ── 11. v4: 图校验 / 导出导入（source=graph 无头可跑）──
    print("── v4 graph.validate (source=graph) ──")
    from Application.Core.NodeGraph import _TYPES as _NODE_TYPES

    _pin_seq = [9000]

    def _mk_node(type_name: str) -> dict:
        pids = {}
        for p in _NODE_TYPES[type_name].pins:
            _pin_seq[0] += 1
            pids[p.name] = _pin_seq[0]
        return {"node_type": type_name, "pos": [0, 0], "props": {}, "pin_ids": pids}

    _n1, _n2, _n3 = _mk_node("OnGameStart"), _mk_node("Constant"), _mk_node("Print")
    _tiny_graph = {
        "version": "0.1.0",
        "nodes": {"1": _n1, "2": _n2, "3": _n3},
        "links": {
            "1": {"from_pin": _n1["pin_ids"]["exec"], "to_pin": _n3["pin_ids"]["exec_in"]},
            "2": {"from_pin": _n2["pin_ids"]["Result"], "to_pin": _n3["pin_ids"]["Value"]},
        },
        "next_id": _pin_seq[0] + 1,
    }

    resp = roundtrip(port, "graph.validate.state")
    check("validate.state ok", resp.get("ok") is True and "state" in (resp.get("result") or {}), str(resp))

    resp = roundtrip(port, "graph.validate.start", {"source": "graph", "graph": _tiny_graph, "frames": 5})
    _started = resp.get("result") or {}
    check("validate.start ok", resp.get("ok") is True and _started.get("started") is True, str(resp))
    _tid = _started.get("task_id")

    _deadline = time.monotonic() + 15.0
    _st = "running"
    while time.monotonic() < _deadline:
        _st = (roundtrip(port, "graph.validate.state", {"task_id": _tid}).get("result") or {}).get("state", "unknown")
        if _st != "running":
            break
        time.sleep(0.05)
    check("task finished (done)", _st == "done", _st)

    resp = roundtrip(port, "graph.validate.report", {"task_id": _tid})
    _rep = (resp.get("result") or {}).get("report") or {}
    check("report found & ok", resp.get("ok") is True and _rep.get("ok") is True, str(_rep.get("counts")))
    check("report log captured Print",
          any(e.get("node_type") == "Print" for e in _rep.get("log") or []), str(_rep.get("counts")))

    _save_path = os.path.join(ROOT, "Utils", "ExtDev", "EditorMcp", "tmp", "test_validation_report.txt")
    resp = roundtrip(port, "graph.validate.report", {"task_id": _tid, "save_path": _save_path})
    _saved = (resp.get("result") or {}).get("saved_path")
    check("report saved (.txt)", resp.get("ok") is True and bool(_saved) and os.path.isfile(_saved), str(resp))
    if _saved and os.path.isfile(_saved):
        os.remove(_saved)

    resp = roundtrip(port, "graph.validate.report", {"task_id": 999999})
    check("report unknown task → error", resp.get("ok") is False, str(resp))

    resp = roundtrip(port, "graph.validate.cancel")
    check("cancel idle → ok (note)",
          resp.get("ok") is True and (resp.get("result") or {}).get("cancelled") is False, str(resp))

    resp = roundtrip(port, "graph.export", {})
    check("graph.export no canvas → error",
          resp.get("ok") is False and "canvas" in str(resp.get("error")), str(resp))

    resp = roundtrip(port, "graph.import", {"graph": {"links": {}}})
    check("graph.import missing nodes key → error", resp.get("ok") is False, str(resp))
    resp = roundtrip(port, "graph.import", {"graph": {"nodes": {}}})
    check("graph.import empty graph → refused (static)",
          resp.get("ok") is True and (resp.get("result") or {}).get("imported") is False, str(resp))
    _bad_graph = {"nodes": {"1": {"node_type": "NoSuchType", "pos": [0, 0], "props": {}, "pin_ids": {}}}, "links": {}}
    resp = roundtrip(port, "graph.import", {"graph": _bad_graph})
    _imp = resp.get("result") or {}
    check("graph.import static errors → refused",
          resp.get("ok") is True and _imp.get("imported") is False and bool(_imp.get("static_errors")), str(resp))

    resp = roundtrip(port, "project.open", {})
    check("project.open no path → error", resp.get("ok") is False, str(resp))
    resp = roundtrip(port, "project.open", {"path": os.path.join(ROOT, "no_such_project.myproj")})
    check("project.open missing file → error", resp.get("ok") is False, str(resp))
    resp = roundtrip(port, "project.save", {})
    check("project.save no project → error", resp.get("ok") is False, str(resp))
    resp = roundtrip(port, "project.export", {"target_parent": ROOT})
    check("project.export no project → error", resp.get("ok") is False, str(resp))
    resp = roundtrip(port, "project.export", {})
    check("project.export no target_parent → error", resp.get("ok") is False, str(resp))
    import Application.Editor.Services.LiveCommandServer as _lcs_mod
    check("project.export 主线程等待上限覆盖 ≥600s",
          _lcs_mod._OP_PUMP_TIMEOUT_OVERRIDES.get("project.export", 0) >= 600.0,
          str(_lcs_mod._OP_PUMP_TIMEOUT_OVERRIDES))

    # ── 7c. 扩展体系（增量扫描 + ext.* 透传）──────────────
    import tempfile
    _ext_state = os.path.join(tempfile.mkdtemp(prefix="mge_ext_loop_"), "state.json")
    os.environ["MGE_EXTENSIONS_STATE"] = _ext_state
    os.environ["MGE_EXTENSIONS_DATA"] = os.path.join(os.path.dirname(_ext_state), "data")
    resp = roundtrip(port, "extension.list")
    _exts = {e.get("id") for e in ((resp.get("result") or {}).get("extensions") or [])}
    check("extension.list ok (含内置默认扩展)", resp.get("ok") is True and
          {"sigproc", "bci", "device"} <= _exts, str(sorted(_exts))[:200])
    resp = roundtrip(port, "extension.enable", {"id": "no_such_extension"})
    check("extension.enable 未知扩展 → 受控错误", resp.get("ok") is False, str(resp)[:200])
    resp = roundtrip(port, "extension.enable", {"id": "bci"})
    check("extension.enable bci → loaded", resp.get("ok") is True and
          (resp.get("result") or {}).get("extension", {}).get("loaded") is True,
          str(resp)[:200])
    resp = roundtrip(port, "ext.bci.status", {})
    check("ext.bci.status 透传",
          resp.get("ok") is True and (resp.get("result") or {}).get("extension") == "bci",
          str(resp)[:200])
    roundtrip(port, "extension.disable", {"id": "bci"})
    resp = roundtrip(port, "extension.enable", {"id": "sigproc"})
    check("extension.enable sigproc → loaded", resp.get("ok") is True and
          (resp.get("result") or {}).get("extension", {}).get("loaded") is True, str(resp)[:200])
    resp = roundtrip(port, "ext.sigproc.info", {})
    check("扩展 op 增量可用 (ext.sigproc.info 透传)",
          resp.get("ok") is True and (resp.get("result") or {}).get("extension") == "sigproc",
          str(resp)[:200])
    resp = roundtrip(port, "extension.disable", {"id": "sigproc"})
    check("extension.disable → op 注销", resp.get("ok") is True, str(resp)[:200])
    resp = roundtrip(port, "ext.sigproc.info", {})
    check("停用后扩展 op 不可用", resp.get("ok") is False, str(resp)[:200])
    os.environ.pop("MGE_EXTENSIONS_STATE", None)
    os.environ.pop("MGE_EXTENSIONS_DATA", None)

    # ── 8. stop 后端口关闭 ──
    print("── Stop ──")
    LiveCommandServer.stop()
    refused = False
    try:
        socket.create_connection(("127.0.0.1", port), timeout=2.0)
    except OSError:
        refused = True
    check("port closed after stop", refused)

    print()
    print("=" * 60)
    total = _RESULTS["pass"] + _RESULTS["fail"]
    print(f"Results: {_RESULTS['pass']}/{total} passed, {_RESULTS['fail']} failed")
    print(f"RESULT: {'OK' if _RESULTS['fail'] == 0 else 'FAIL'} ({_RESULTS['pass']}/{total})")
    if _RESULTS["fail"] == 0:
        print("ALL TESTS PASSED")
        return 0
    print("TESTS FAILED")
    return 1


if __name__ == "__main__":
    sys.exit(main())
