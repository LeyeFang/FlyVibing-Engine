"""
E2E: 渲染器验证体系实机验收（需引擎运行中 — 先启动 startup.bat）。

流程: renderer.snapshot（后端 / GL 信息 / 资源计数 / overlays / 帧统计）
      → 裸帧像素采样（frame.request/fetch, 与 CLI `probe` 同协议）
      → 抓帧落盘（capture 同路径）。
断言保持宽松（工具链可用性 + 数值合理性）——像素金标准在 core 的
Test/Application/Renderer/test_gl_pixels.py 锁定, 本脚本只验实机链路。

用法:
    .venv-py314t\\Scripts\\python.exe Test/Application/Editor/e2e_renderer_check.py
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

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


def _fetch_raw(target: str, timeout: float = 6.0) -> dict:
    req = m._send("frame.request", {"target": target})
    if "error" in req:
        raise RuntimeError(req["error"])
    generation = req.get("generation")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        info, payload = m._send_raw("frame.fetch", {"target": target, "generation": generation})
        if "error" in info:
            raise RuntimeError(info["error"])
        if info.get("ready"):
            return {"width": int(info["width"]), "height": int(info["height"]),
                    "payload": payload}
        if info.get("state") == "error":
            raise RuntimeError(info.get("error") or "capture failed")
        time.sleep(0.03)
    raise RuntimeError("frame timeout")


def _sample(frame: dict, x: int, y: int) -> tuple:
    w, h, data = frame["width"], frame["height"], frame["payload"]
    idx = ((h - 1 - y) * w + x) * 4
    return (data[idx], data[idx + 1], data[idx + 2], data[idx + 3])


def main() -> int:
    print("== Renderer e2e — snapshot + pixel probe + capture ==")

    # ── 1. renderer.snapshot ──
    print("── renderer.snapshot ──")
    snap = m._send("renderer.snapshot")
    check("op ok", "error" not in snap, str(snap)[:200])
    check("available", snap.get("available") is True, str(snap)[:200])
    check("backend == OpenGLRenderer", snap.get("backend") == "OpenGLRenderer",
          str(snap.get("backend")))
    gl = snap.get("gl") or {}
    check("GL version 4.4 (core)", "4.4" in str(gl.get("version", "")), str(gl))
    check("GL vendor non-empty", bool(gl.get("vendor")), str(gl))
    vw, vh = snap.get("viewport") or [0, 0]
    check("viewport sane", vw >= 800 and vh >= 500, f"{vw}x{vh}")
    counts = snap.get("counts") or {}
    check("entities registered >= 1", counts.get("entities", 0) >= 1, str(counts))
    check("overlay drawables registered >= 1", counts.get("overlays", 0) >= 1, str(counts))
    check("overlays listed (list)", isinstance(snap.get("overlays"), list), str(snap.get("overlays")))
    check("stats present", isinstance(snap.get("stats"), dict), str(snap.get("stats")))

    # ── 2. 裸帧像素采样（CLI probe 同协议） ──
    print("── pixel probe (editor) ──")
    frame = _fetch_raw("editor")
    check("frame decoded", frame["width"] > 0 and len(frame["payload"]) ==
          frame["width"] * frame["height"] * 4, f"{frame['width']}x{frame['height']}")
    corner = _sample(frame, 5, 5)
    # 视口中心（回避右侧面板; 1600x900 窗口 ≈ 视口中心区）
    mid = _sample(frame, 600, 450)
    check("corner pixel readable", len(corner) == 4, str(corner))
    check("corner dark-ish (menu bar/toolbar)", max(corner[:3]) <= 240, str(corner))
    print(f"  corner(5,5) = {corner}   mid(600,450) = {mid}")
    check("3D viewport renders non-uniform content", corner != mid, f"{corner} vs {mid}")

    # ── 3. capture 同路径 ──
    print("── capture (editor) ──")
    path, png = m._capture_png("editor")
    check("capture png saved", os.path.isfile(path) and len(png) > 1000, path)
    print("  saved:", path)

    total = _RESULTS["pass"] + _RESULTS["fail"]
    print()
    print(f"RESULT: {'OK' if _RESULTS['fail'] == 0 else 'FAIL'} ({_RESULTS['pass']}/{total})")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
