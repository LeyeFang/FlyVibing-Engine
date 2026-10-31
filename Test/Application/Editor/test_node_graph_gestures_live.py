"""E2E (live editor): node graph mouse-gesture semantics.

Verifies the input-queue contract used by Utils (`ui.drag` / `ui.click`):
  * left drag on blank canvas = box select (no accidental pan/menu);
  * right drag = canvas pan, and must NOT open the context menu;
  * right click without movement = open the node context menu on release.

Requires the editor running with the live command server, e.g.:

    startup.bat --port 8977
    $env:MGE_EDITOR_MCP_PORT=8977
    python Utils/Dev/test_runner.py --tier live --only node_graph_gestures

Snapshots: Test/_runs/node_graph_gestures_live/*.png
"""

# TIER: live

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:  # installed wheel first, source checkout fallback
    from engine_editor_mcp.client import capture_png, send  # type: ignore
except ImportError:  # pragma: no cover - developer utility checkout
    sys.path.insert(0, str(ROOT.parent / "FlyVibing-User-And-Developer-Utils"
                                    / "packages" / "editor-mcp" / "src"))
    from engine_editor_mcp.client import capture_png, send  # type: ignore

from Application.Core.NodeGraph import _TYPES  # noqa: E402

OUT = ROOT / "Test" / "_runs" / "node_graph_gestures_live"
OUT.mkdir(parents=True, exist_ok=True)

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


def wait(seconds: float = 0.35) -> None:
    time.sleep(seconds)


def view() -> dict:
    last = None
    for _ in range(8):
        last = send("ui.panel", {"name": "Node Editor"})
        data = last.get("view") if isinstance(last, dict) else None
        if data and data.get("canvas_rect"):
            return data
        wait(0.1)
    raise RuntimeError(f"Node Editor view unavailable: {last}")


def view_ready() -> dict:
    data = view()
    for _ in range(12):
        if data.get("nodes"):
            return data
        wait(0.15)
        data = view()
    return data


def snap(name: str) -> None:
    _, data = capture_png("editor")
    path = OUT / f"{name}.png"
    path.write_bytes(data)
    if len(data) < 10_000:
        raise RuntimeError(f"snapshot too small: {path} ({len(data)} bytes)")


def pin_ids(type_name: str, base: int) -> dict[str, int]:
    return {pin.name: base + i
            for i, pin in enumerate(_TYPES[type_name].pins)}


def node(type_name: str, nid: int, pos: tuple[float, float]) -> dict:
    return {"id": nid, "node_type": type_name, "pos": list(pos),
            "props": {}, "pin_ids": pin_ids(type_name, nid * 10)}


def fixture() -> dict:
    return {
        "version": "0.1.0",
        "nodes": {
            "301": node("OnGameStart", 301, (80, 80)),
            "302": node("OnFrameUpdate", 302, (80, 300)),
            "303": node("OnGameStop", 303, (80, 520)),
        },
        "links": {},
        "next_id": 5000,
    }


def activate_and_fit(graph: dict) -> dict:
    send("ui.panel", {"name": "Node Editor", "visible": True})
    send("graph.import", {"graph": graph, "validate_first": False})
    wait(0.3)
    # Node Editor tab (client pixels; same anchor as the other live editor E2E).
    send("ui.click", {"x": 1370, "y": 32})
    wait(0.3)
    send("graph.fit")
    wait(0.5)
    return view_ready()


def node_bounds(view_data: dict) -> tuple[float, float, float, float]:
    rects = list((view_data.get("nodes") or {}).values())
    if not rects:
        raise RuntimeError("no node rects")
    return (
        min(r[0] for r in rects), min(r[1] for r in rects),
        max(r[2] for r in rects), max(r[3] for r in rects),
    )


def blank_point(view_data: dict) -> tuple[float, float]:
    """Find a canvas point not covered by a node (for pan/box gestures)."""
    canvas = view_data.get("canvas_rect")
    if not canvas:
        raise RuntimeError("canvas_rect missing")
    rects = list((view_data.get("nodes") or {}).values())
    candidates = [
        (canvas[0] + 12, canvas[3] - 12),
        (canvas[0] + 12, canvas[1] + 12),
        (canvas[2] - 12, canvas[3] - 12),
        (canvas[2] - 12, canvas[1] + 12),
        (canvas[0] + 12, (canvas[1] + canvas[3]) * 0.5),
    ]
    for x, y in candidates:
        if not any(r[0] <= x <= r[2] and r[1] <= y <= r[3] for r in rects):
            return x, y
    raise RuntimeError(f"no blank canvas point: canvas={canvas} nodes={rects}")


def wait_for(predicate, label: str, attempts: int = 20) -> dict:
    data = view()
    for _ in range(attempts):
        if predicate(data):
            return data
        wait(0.1)
        data = view()
    raise RuntimeError(f"timed out waiting for {label}: {data}")


def main() -> int:
    print("== Node graph gesture live test ==")
    data = activate_and_fit(fixture())
    node_ids = sorted(int(k) for k in (data.get("nodes") or {}))
    check("fixture nodes visible", node_ids == [301, 302, 303], str(node_ids))
    canvas = data.get("canvas_rect")
    if not canvas:
        raise RuntimeError(f"canvas_rect missing: {data}")

    # ── 1. Left drag on blank canvas = box select ──
    left, top, right, bottom = node_bounds(data)
    start = (max(canvas[0] + 6, left - 14), max(canvas[1] + 6, top - 14))
    end = (min(canvas[2] - 6, right + 14), min(canvas[3] - 6, bottom + 14))
    send("ui.drag", {"x0": start[0], "y0": start[1],
                     "x1": end[0], "y1": end[1],
                     "button": 0, "steps": 12})
    data = wait_for(lambda v: bool(v.get("last_box_apply", {}).get("hits")),
                    "box select")
    hits = set(data.get("last_box_apply", {}).get("hits") or [])
    check("left drag selects nodes", set(node_ids).issubset(hits), str(hits))
    check("left drag did not open menu", not data.get("context_open"))
    snap("box_select")

    # ── 2. Right drag on blank canvas = pan, no menu ──
    bx, by = blank_point(data)
    drag = (bx, by, min(canvas[2] - 12, bx + 40),
            max(canvas[1] + 12, by - 40))
    before = dict(data.get("nodes") or {})
    send("ui.drag", {"x0": drag[0], "y0": drag[1],
                     "x1": drag[2], "y1": drag[3],
                     "button": 1, "steps": 12})
    dx, dy = drag[2] - drag[0], drag[3] - drag[1]

    def _pan_moved(v: dict) -> bool:
        after = v.get("nodes") or {}
        return any(
            nid in after
            and abs((after[nid][0] - before[nid][0]) - dx) < 8
            and abs((after[nid][1] - before[nid][1]) - dy) < 8
            for nid in before
        )

    data = wait_for(_pan_moved, "right drag pan")
    after = dict(data.get("nodes") or {})
    check("right drag pans canvas", _pan_moved(data), f"{before} -> {after}")
    check("right drag did not open menu", not data.get("context_open"))
    snap("right_drag")

    # ── 3. Right click (no movement) = context menu on release ──
    rects = data.get("nodes") or {}
    nid, rect = sorted(rects.items(), key=lambda kv: int(kv[0]))[0]
    cx, cy = (rect[0] + rect[2]) * 0.5, (rect[1] + rect[3]) * 0.5
    send("ui.click", {"x": cx, "y": cy, "button": 1})
    data = wait_for(lambda v: bool(v.get("context_open")), "context menu")
    check("right click opens menu", data.get("context_kind") == "node",
          str(data.get("context_kind")))
    check("right click preserves selection",
          int(nid) in (data.get("context_selection") or []),
          str(data.get("context_selection")))
    snap("context_menu")

    total = _RESULTS["pass"] + _RESULTS["fail"]
    ok = _RESULTS["fail"] == 0
    print()
    print(f"RESULT: {'OK' if ok else 'FAIL'} ({_RESULTS['pass']}/{total})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
