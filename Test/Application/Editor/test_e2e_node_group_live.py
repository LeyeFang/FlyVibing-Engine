"""E2E (live editor): node group visuals + natural mouse interactions.

Requires the editor running with the live command server, e.g.:

    startup.bat --port 8979

Covers:
  * group frame/title/description are visible and inside the frame;
  * Group entry/exit pills sit in the left/right gutters and do not
    overlap member cards; the description has a Description/Hide toggle;
  * dragging the title moves the frame and its members together;
  * a member can leave and re-enter the group, with the frame auto-fitting;
  * real mouse drags from the edge exec pills create links to/from members.

Snapshots: Test/_runs/e2e_node_group_live/*.png
"""

# TIER: live

from __future__ import annotations

import json
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

OUT = ROOT / "Test" / "_runs" / "e2e_node_group_live"
OUT.mkdir(parents=True, exist_ok=True)


def wait(seconds: float = 0.5) -> None:
    time.sleep(seconds)


def view() -> dict:
    last = None
    for _ in range(6):
        last = send("ui.panel", {"name": "Node Editor"})
        data = last.get("view") if isinstance(last, dict) else None
        if data:
            return data
        wait(0.1)
    raise RuntimeError(f"Node Editor view unavailable: {last}")


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


def fixture(alias: str = "e2e_group") -> dict:
    return {
        "version": "0.1.0",
        "nodes": {
            "1": node("OnGameStart", 1, (80, 80)),
            "2": node("NewTimer", 2, (380, 80)),
            "3": node("NewTimer", 3, (380, 300)),
        },
        "links": {},
        "next_id": 5000,
        "node_groups": {
            "g1": {
                "type": "container", "version": 1, "alias": alias,
                "description": "group visual regression", "members": [2, 3],
                "params": {}, "slots": {},
            }
        },
    }


def view_ready(require_nodes: bool = True) -> dict:
    """等绘制帧把节点屏幕矩形写入 view；导入/ Fit 后可能有一两帧空表。"""
    data = view()
    for _ in range(12):
        if not require_nodes or data.get("nodes"):
            return data
        wait(0.15)
        data = view()
    return data


def activate_and_fit(graph: dict | None = None) -> dict:
    send("ui.panel", {"name": "Node Editor", "visible": True})
    if graph is not None:
        send("graph.import", {"graph": graph, "validate_first": False})
    wait(0.4)
    send("ui.click", {"x": 1370, "y": 32})  # Node Editor tab
    wait(0.4)
    send("graph.fit")
    wait(0.6)
    return view_ready()


def drag(x0: float, y0: float, x1: float, y1: float) -> None:
    send("ui.drag", {"x0": x0, "y0": y0, "x1": x1, "y1": y1,
                     "steps": 14, "button": 0})
    wait(0.7)


def rect_hits(a, b, pad: float = 0.5) -> bool:
    return not (a[2] <= b[0] + pad or b[2] <= a[0] + pad
                or a[3] <= b[1] + pad or b[3] <= a[1] + pad)


def group_members() -> int:
    groups = (send("graph.list") or {}).get("node_groups") or {}
    return int((groups.get("g1") or {}).get("members") or 0)


def main() -> int:
    failures: list[str] = []

    def check(ok: bool, label: str, detail: object = "") -> None:
        print(("PASS " if ok else "FAIL ") + label
              + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(label)

    state = activate_and_fit(fixture())
    nodes = state.get("nodes") or {}
    io = (state.get("group_io_rects") or {}).get("g1") or {}
    frame = (state.get("group_frames") or {}).get("g1")
    title = (state.get("group_titles") or {}).get("g1")
    desc = (state.get("group_descriptions") or {}).get("g1")
    desc_rect = (state.get("group_description_rects") or {}).get("g1")
    start, end = io.get("start_node"), io.get("end_node")
    print("rects", json.dumps({"frame": frame, "title": title,
                               "desc": desc, "start": start, "end": end,
                               "nodes": nodes}, ensure_ascii=False))
    snap("01_base")

    check(bool(frame), "group frame visible", frame)
    check(bool(title), "group title rect visible", title)
    check(str((state.get("group_title_texts") or {}).get("g1", "")).startswith("@e2e_group"),
          "group title shows alias",
          (state.get("group_title_texts") or {}).get("g1"))
    check(desc == "group visual regression", "group description visible", desc)
    check(desc_rect is not None, "group description rect visible", desc_rect)
    check(bool(start and end), "group entry/exit pills visible", io)
    if frame and title:
        check(frame[0] <= title[0] and title[2] <= frame[2]
              and frame[1] <= title[1] and title[3] <= frame[3],
              "title lies inside group frame", title)
    if frame and desc_rect:
        check(frame[0] <= desc_rect[0] and desc_rect[2] <= frame[2],
              "description lies inside group frame", desc_rect)
    for key, rect in (("start", start), ("end", end)):
        if not rect or not frame:
            continue
        check(frame[0] <= rect[0] and rect[2] <= frame[2],
              f"{key} pill is inside group frame horizontally", rect)
        for nid, nrect in nodes.items():
            check(not rect_hits(rect, nrect),
                  f"{key} pill does not overlap node {nid}", (rect, nrect))

    # 与普通节点一致的 Description/Hide 按钮：默认展开，点击折叠/展开。
    desc_button = (state.get("group_desc_buttons") or {}).get("g1")
    check(desc_button is not None, "group description toggle button visible",
          desc_button)
    if desc_button:
        bx = (desc_button[0] + desc_button[2]) / 2
        by = (desc_button[1] + desc_button[3]) / 2
        send("ui.click", {"x": bx, "y": by})
        wait(0.5)
        collapsed = view()
        check(not (collapsed.get("group_descriptions") or {}).get("g1"),
              "description button collapses the description",
              (collapsed.get("group_descriptions") or {}).get("g1"))
        snap("02_desc_collapsed")
        btn2 = (collapsed.get("group_desc_buttons") or {}).get("g1") or desc_button
        send("ui.click", {"x": (btn2[0] + btn2[2]) / 2,
                          "y": (btn2[1] + btn2[3]) / 2})
        wait(0.5)
        expanded = view()
        check((expanded.get("group_descriptions") or {}).get("g1")
              == "group visual regression",
              "description button expands it again",
              (expanded.get("group_descriptions") or {}).get("g1"))

    # title drag moves frame + members
    if frame and title:
        n2_before = list(nodes.get("2") or [])
        drag((title[0] + title[2]) / 2, (title[1] + title[3]) / 2,
             (title[0] + title[2]) / 2 - 24, (title[1] + title[3]) / 2 - 14)
        moved = view()
        frame_after = (moved.get("group_frames") or {}).get("g1") or []
        n2_after = (moved.get("nodes") or {}).get("2") or []
        check(frame_after and abs(frame_after[0] - frame[0]) > 10
              and abs(frame_after[1] - frame[1]) > 5,
              "dragging title moves group frame", (frame, frame_after))
        check(n2_before and n2_after
              and abs(n2_after[0] - n2_before[0]) > 10,
              "dragging title moves members", (n2_before, n2_after))
        snap("02_title_drag")

    # member leaves and re-enters
    state = view()
    nodes = state.get("nodes") or {}
    frame = (state.get("group_frames") or {}).get("g1")
    n3 = nodes.get("3")
    if frame and n3:
        check(group_members() == 2, "fixture starts with two members",
              group_members())
        drag(n3[0] + 54, n3[1] + 14, frame[0] + 40, frame[1] - 90)
        check(group_members() == 1, "dragging member out of group removes it",
              group_members())
        snap("03_member_out")
        # 成员离开后组框会收紧；用刷新后的 frame 命中右下角手柄。
        out_state = view()
        frame = (out_state.get("group_frames") or {}).get("g1") or frame
        # 用户先把组框向下拉出空位，再把成员拖回；这样成员不会叠在旧卡片上。
        drag(frame[2] - 6, frame[3] - 6, frame[2] - 6, frame[3] + 180)
        state = view()
        resized_frame = (state.get("group_frames") or {}).get("g1")
        if resized_frame:
            check(resized_frame[3] > frame[3] + 20,
                  "corner handle grows the group frame",
                  (frame, resized_frame))
        nodes = state.get("nodes") or {}
        frame = resized_frame
        n2 = nodes.get("2")
        n3 = nodes.get("3")
        if frame and n2 and n3:
            drag(n3[0] + 54, n3[1] + 14,
                 n2[0] + 10, n2[3] + 30)
            check(group_members() == 2,
                  "dragging member back into group re-adds it",
                  group_members())
            after = view()
            after_nodes = after.get("nodes") or {}
            n2_after, n3_after = after_nodes.get("2"), after_nodes.get("3")
            if n2_after and n3_after:
                check(not rect_hits(n2_after, n3_after),
                      "re-entered member does not overlap another member",
                      (n2_after, n3_after))
            snap("04_member_in")

    # clean graph, then real mouse chain through group exec ports
    state = activate_and_fit(fixture("chain_group"))
    nodes = state.get("nodes") or {}
    io = (state.get("group_io_rects") or {}).get("g1") or {}
    n2, n3 = nodes.get("2"), nodes.get("3")
    start, end = io.get("start_node"), io.get("end_node")
    if not all((n2, n3, start, end)):
        raise RuntimeError(f"missing chain rects: {state}")
    drag(start[2] - 6, (start[1] + start[3]) / 2,
         n2[0] + 10, n2[3] - 30)
    drag(n2[2] - 42, n2[3] - 11, n3[0] + 10, n3[3] - 30)
    drag(n3[2] - 42, n3[3] - 11,
         end[0] + 8, (end[1] + end[3]) / 2)
    graph = send("graph.list")
    links = graph.get("links") or []
    pinmap = {int(n["pins"].get(k)): (n["type"], k)
              for n in graph.get("nodes") or []
              for k in n.get("pins", {})}
    pairs = {(pinmap.get(l["from_pin"]), pinmap.get(l["to_pin"]))
             for l in links}
    check(("GroupStart", "exec_out") in {p[0] for p in pairs},
          "link starts at group exec out", pairs)
    check(("GroupEnd", "exec_in") in {p[1] for p in pairs},
          "link ends at group exec in", pairs)
    check(("NewTimer", "exec_out") in {p[0] for p in pairs},
          "member output links onward", pairs)
    check(len(links) == 3, "chain has three links", links)
    snap("05_exec_chain")

    print("snapshots:", OUT)
    if failures:
        print("RESULT: FAIL", failures)
        return 1
    print("RESULT: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
