"""remote_display_probe — 远程/无物理显示器下的 OpenGL 窗口呈现探针。

用途:
  区分“引擎帧缓冲渲染错误”与“Windows/远程软件的窗口呈现或截屏错误”。
  创建与 RuntimeWindow 相同的 OpenGL 4.4 Core 窗口，填充纯色后:
    1. 读回后缓冲 (back.png)
    2. SwapBuffers
    3. 读回前缓冲 (front.png)
    4. 用 GDI 截取窗口所在屏幕区域 (screen.png)
  对比三张图的中心像素:
    - back/front 均为目标色，screen 为白色 → 渲染与 Swap 正常，问题在窗口呈现/远程截屏层
    - back/front 不是目标色 → 引擎/GL 渲染问题

用法:
  .venv-py314t\\Scripts\\python.exe Utils/Dev/remote_display_probe.py
  .venv-py314t\\Scripts\\python.exe Utils/Dev/remote_display_probe.py --out-dir Test/_runs/remote_probe

退出码:
  0 = 探针执行完成（无论是否 mismatch；结果写入 JSON）
  2 = 创建窗口 / OpenGL / 读回失败
零业务依赖；只用于开发机诊断，不随游戏包分发。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import glfw
import numpy as np
from OpenGL import GL as gl
from PIL import Image, ImageGrab


TARGET_RGBA = (0.10, 0.80, 0.20, 1.0)   # 纯绿色，便于与白屏区分
WINDOW_W, WINDOW_H = 800, 450


def _read_pixels(width: int, height: int, which: int) -> np.ndarray:
    """读回当前缓冲的 RGBA 像素（OpenGL 原点在左下，翻转成图像坐标）。"""
    gl.glReadBuffer(which)
    raw = gl.glReadPixels(0, 0, width, height, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE)
    arr = np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 4)
    return np.flipud(arr)


def _center_px(img: np.ndarray) -> list[int]:
    h, w = img.shape[:2]
    return [int(v) for v in img[h // 2, w // 2, :4]]


def _screen_capture(bbox: tuple[int, int, int, int], path: Path) -> np.ndarray | None:
    try:
        shot = ImageGrab.grab(bbox=bbox, all_screens=True)
    except Exception as exc:  # noqa: BLE001 — 截屏失败本身也要记录
        print(f"[probe] screen capture failed: {exc}", file=sys.stderr)
        return None
    shot.save(path)
    return np.asarray(shot.convert("RGBA"))


def _monitor_info() -> list[dict]:
    out: list[dict] = []
    monitors = glfw.get_monitors()
    for mon in monitors:
        try:
            name = glfw.get_monitor_name(mon)
            mode = glfw.get_video_mode(mon)
            out.append({
                "name": name.decode("utf-8", "replace") if isinstance(name, bytes) else str(name),
                "size": [mode.size.width, mode.size.height] if mode else None,
                "refresh_hz": mode.refresh_rate if mode else None,
            })
        except Exception as exc:  # noqa: BLE001
            out.append({"error": str(exc)})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="远程/无显示器 OpenGL 窗口呈现探针")
    ap.add_argument("--out-dir", default="", help="输出目录（默认 Test/_runs/remote_display_probe/<时间戳>）")
    ap.add_argument("--hold", type=float, default=1.0, help="窗口保留秒数（默认 1.0）")
    ns = ap.parse_args()

    root = Path(__file__).resolve().parents[2]
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(ns.out_dir) if ns.out_dir else root / "Test" / "_runs" / "remote_display_probe" / stamp
    if not out_dir.is_absolute():
        out_dir = root / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    if not glfw.init():
        print("[probe] glfw.init failed", file=sys.stderr)
        return 2

    window = None
    try:
        glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 4)
        glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 4)
        glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
        window = glfw.create_window(WINDOW_W, WINDOW_H, "FlyVibing Remote Display Probe", None, None)
        if not window:
            print("[probe] glfw.create_window failed", file=sys.stderr)
            return 2
        glfw.make_context_current(window)
        glfw.show_window(window)
        glfw.focus_window(window)

        vendor = gl.glGetString(gl.GL_VENDOR)
        renderer = gl.glGetString(gl.GL_RENDERER)
        version = gl.glGetString(gl.GL_VERSION)
        decode = lambda v: v.decode("utf-8", "replace") if isinstance(v, bytes) else str(v)

        fb_w, fb_h = glfw.get_framebuffer_size(window)
        gl.glViewport(0, 0, fb_w, fb_h)
        gl.glClearColor(*TARGET_RGBA)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)

        # 后缓冲读回（Swap 前）
        back = _read_pixels(fb_w, fb_h, gl.GL_BACK)
        Image.fromarray(back, "RGBA").save(out_dir / "back.png")

        # 让窗口完成至少一次真实 Swap；再读前缓冲
        for _ in range(3):
            glfw.swap_buffers(window)
            glfw.poll_events()
            time.sleep(0.05)
        front = _read_pixels(fb_w, fb_h, gl.GL_FRONT)
        Image.fromarray(front, "RGBA").save(out_dir / "front.png")

        x, y = glfw.get_window_pos(window)
        w, h = glfw.get_window_size(window)
        screen_img = _screen_capture((int(x), int(y), int(x + w), int(y + h)),
                                     out_dir / "screen.png")
        if ns.hold > 0:
            end = time.monotonic() + ns.hold
            while time.monotonic() < end:
                glfw.poll_events()
                time.sleep(0.03)

        expected = [int(round(c * 255)) for c in TARGET_RGBA]

        def _close(rgba: list[int] | None, tol: int = 3) -> bool:
            if rgba is None or len(rgba) < 3:
                return False
            return all(abs(int(a) - int(b)) <= tol for a, b in zip(rgba[:3], expected[:3]))

        result = {
            "timestamp": stamp,
            "out_dir": str(out_dir),
            "gl": {"vendor": decode(vendor), "renderer": decode(renderer), "version": decode(version)},
            "monitors": _monitor_info(),
            "window": {
                "pos": [int(x), int(y)],
                "size": [int(w), int(h)],
                "framebuffer": [int(fb_w), int(fb_h)],
                "visible": bool(glfw.get_window_attrib(window, glfw.VISIBLE)),
                "iconified": bool(glfw.get_window_attrib(window, glfw.ICONIFIED)),
            },
            "expected_rgba": expected,
            "back_center": _center_px(back),
            "front_center": _center_px(front),
            "screen_center": _center_px(screen_img) if screen_img is not None else None,
        }
        result["back_matches"] = _close(result["back_center"])
        result["front_matches"] = _close(result["front_center"])
        result["screen_matches"] = _close(result["screen_center"])
        result["presentation_mismatch"] = bool(result["front_matches"] and not result["screen_matches"])

        (out_dir / "result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"[probe] failed: {exc}", file=sys.stderr)
        return 2
    finally:
        if window is not None:
            glfw.destroy_window(window)
        glfw.terminate()


if __name__ == "__main__":
    sys.exit(main())
