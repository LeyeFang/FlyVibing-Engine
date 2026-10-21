"""
E2E: Editor Live MCP v2 实机验收（需引擎运行中 — 先启动 startup.bat）。

流程: view.set_mode 2d（按钮语义, 影响 PIE 摄像机）→ sim.play → 等 Running
      → frame.capture(pie) / frame.capture(editor)（含 PNG 编码与落盘）
      → camera.get → sim.stop → 等 Stopped。

用法:
    .venv-py314t\\Scripts\\python.exe Test/Application/Editor/e2e_mcp_live_check.py
"""

from __future__ import annotations

import os
import sys
import time

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "_path_setup.py")):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)
    import _path_setup  # noqa: F401

from engine_editor_mcp import mcp_server as m  # noqa: E402


def _wait_state(want: str, timeout: float = 6.0) -> dict:
    deadline = time.monotonic() + timeout
    st: dict = {}
    while time.monotonic() < deadline:
        st = m._send("sim.state")
        if "error" in st:
            break
        if st.get("state") == want:
            return st
        time.sleep(0.05)
    return st


def main() -> int:
    print("== Editor Live MCP v2 — E2E check ==")
    print("frames dir:", m.FRAMES_DIR)

    print("── graph.list ──")
    lst = m._send("graph.list")
    nodes = lst.get("nodes") or []
    print("  canvas nodes:", [(n["id"], n["type"]) for n in nodes])
    onstart = next((n["id"] for n in nodes if n["type"] == "OnGameStart"), None)
    if onstart is None:
        print("FAIL: OnGameStart node not found")
        return 1

    print("── graph.add EntitySpawn(template=DefaultCube) ──")
    added = m._send("graph.add", {"type": "EntitySpawn", "props": {"template": "DefaultCube"}})
    print(" ", added)
    if "node_id" not in added:
        print("FAIL: graph.add failed")
        return 1

    print("── graph.link OnGameStart.exec → EntitySpawn.exec_in ──")
    print(" ", m._send("graph.link", {
        "from": {"node": onstart, "pin": "exec"},
        "to": {"node": added["node_id"], "pin": "exec_in"},
    }))

    print("── set scene type 2d ──")
    print(" ", m._send("view.set_mode", {"mode": "2d"}))

    print("── sim.play ──")
    print(" ", m._send("sim.play"))
    st = _wait_state("Running")
    print(" ", st)
    if st.get("state") != "Running":
        print("FAIL: PIE did not reach Running")
        return 1
    time.sleep(0.4)   # 让 PIE 渲染若干帧

    print("── capture pie ──")
    path_pie, png_pie = m._capture_png("pie")
    print(" ", path_pie, f"{len(png_pie)} bytes")

    print("── capture editor ──")
    path_ed, png_ed = m._capture_png("editor")
    print(" ", path_ed, f"{len(png_ed)} bytes")

    print("── camera.get (3d) ──")
    print(" ", m._send("camera.get", {"role": "3d"}))

    print("── sim.stop ──")
    print(" ", m._send("sim.stop"))
    st = _wait_state("Stopped")
    print(" ", st)

    ok = st.get("state") == "Stopped"
    print("RESULT:", "OK" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
