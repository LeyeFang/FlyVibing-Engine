"""glfwWindow 覆盖层窗口语义（core，无 GL/无窗口）。

背景（2026-11-04，用户实机反馈）:
  1. Overlay 场景的 PIE 窗口是**普通窗口**（有标题栏、1280×720）—— 覆盖层不成立；
  2. 改成无边框后仍不铺满：实测 `-8,-31 1936×1100 @1920×1080`（左上溢出、右下留缝）；
  3. 穿透窗口在透明处**收不到 WM_MOUSEMOVE**，只靠事件路径更新 pick 采样点会让
     "光标移到覆盖层内容上也照样穿透"（看得见点不到）。

本测试锁定（不建真实窗口 — 全部 monkeypatch）:
  1. `_win32_fill_rect` 的 SetWindowPos 参数（目标矩形 + FRAMECHANGED）
  2. `set_window_mode(BORDERLESS)` 的调用顺序: **剥 chrome → 再铺满屏幕**
  3. `_update_click_through_state` 用真实光标推进 pick 采样点（像素 = 窗口坐标 × scale）
  4. NDC 命中判定用**窗口坐标**（高 DPI 下与 framebuffer 不同）
  5. 命中/穿透两个分支分别切 WS_EX_TRANSPARENT 样式
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

import Application.Core.Window.glfwWindow as gw  # noqa: E402

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


class _FakeRenderer:
    def __init__(self) -> None:
        self.sample = None

    def update_pick_mouse(self, x, y) -> None:
        self.sample = (x, y)


class _FakeEngine:
    def __init__(self) -> None:
        self.renderer = _FakeRenderer()


class _Recorder:
    """记录 SetWindowPos 参数（替代 user32）。"""

    def __init__(self) -> None:
        self.calls = []

        class _Fn:
            def __init__(self, outer):
                self._o = outer

            def __call__(self, hwnd, insert_after, x, y, cx, cy, flags):
                self._o.calls.append((hwnd, x, y, cx, cy, flags))
                return True

        self.SetWindowPos = _Fn(self)


def main() -> int:
    print("=" * 60)
    print("glfwWindow — borderless fill order + overlay click-through hit source")
    print("=" * 60)

    # ── 保存全局状态（patch 后必须还原）──
    real_glfw = gw.glfw
    real_user32 = gw._user32
    real_strip = gw._win32_strip_chrome
    real_fill = gw._win32_fill_rect
    real_add = gw._win32_add_style
    real_remove = gw._win32_remove_style
    real_hit = gw.glfwWindow.__dict__.get("_is_click_through_target")
    W = gw.glfwWindow
    saved = (W._window_mode, W.glfw_window, W._saved_window_rect,
             W._engine, W._click_through)

    try:
        # ── 1. _win32_fill_rect: 目标矩形 + FRAMECHANGED ──
        rec = _Recorder()
        gw._user32 = rec
        gw._win32_fill_rect(0x1234, 0, 0, 1920, 1080)
        call = rec.calls[0] if rec.calls else None
        check("fill_rect → SetWindowPos(0,0,1920,1080)",
              call is not None and call[1:] == (0, 0, 1920, 1080, 0x0020 | 0x0004 | 0x0010),
              str(call))
        check("fill_rect 带 SWP_FRAMECHANGED", call is not None and (call[5] & 0x0020) != 0,
              str(call))
        check("fill_rect 不改 z-order/不激活",
              call is not None and (call[5] & 0x0004) and (call[5] & 0x0010), str(call))

        # ── 2. set_window_mode(BORDERLESS): 先剥 chrome, 再铺满 ──
        order: list = []
        gw._win32_strip_chrome = lambda hwnd: order.append("strip")
        gw._win32_fill_rect = lambda hwnd, x, y, w, h: order.append(("fill", x, y, w, h))
        gw._user32 = real_user32
        W.glfw_window = object()
        W._window_mode = gw.WindowMode.WINDOWED
        W._saved_window_rect = None
        W._engine = None
        gw.glfw = SimpleNamespace(
            get_primary_monitor=lambda: 1,
            get_video_mode=lambda m: SimpleNamespace(
                size=SimpleNamespace(width=1920, height=1080), refresh_rate=60),
            get_win32_window=lambda w: 0x111,
            get_window_pos=lambda w: (10, 20),
            get_window_size=lambda w: (1600, 900),
        )
        W._reapply_win32_styles = classmethod(lambda cls: None)
        W.set_window_mode(gw.WindowMode.BORDERLESS)
        check("BORDERLESS: strip 在前, fill 在后",
              order == ["strip", ("fill", 0, 0, 1920, 1080)], str(order))

        # ── 3/4/5. 点击穿透: pick 采样点 + NDC 坐标系 + 样式切换 ──
        styles: list = []
        gw._win32_add_style = lambda hwnd, bit: styles.append(("add", bit)) or True
        gw._win32_remove_style = lambda hwnd, bit: styles.append(("remove", bit)) or True
        engine = _FakeEngine()
        ndc_seen: list = []
        verdict = {"capture": False}

        def _fake_hit(cls, ndc_x, ndc_y):
            ndc_seen.append((round(ndc_x, 4), round(ndc_y, 4)))
            return verdict["capture"]

        W._is_click_through_target = classmethod(_fake_hit)
        W._engine = engine
        W._click_through = True
        gw.glfw = SimpleNamespace(
            get_win32_window=lambda w: 0x111,
            get_window_size=lambda w: (1600, 900),
            get_framebuffer_size=lambda w: (3200, 1800),   # 200% DPI
            get_cursor_pos=lambda w: (800.0, 450.0),       # 窗口中心
        )

        engine.renderer.sample = (0, 0)                    # 陈旧采样点
        W._update_click_through_state()
        check("pick 采样点 = 真实光标 × (fb/window) 比例",
              engine.renderer.sample == (1600.0, 900.0), str(engine.renderer.sample))
        check("NDC 用窗口坐标 (中心 → 0,0; 高 DPI 不偏移)",
              ndc_seen and ndc_seen[-1] == (0.0, 0.0), str(ndc_seen))
        check("透明处 → 加 WS_EX_TRANSPARENT (穿透)",
              ("add", gw._WS_EX_TRANSPARENT) in styles, str(styles))

        styles.clear()
        verdict["capture"] = True
        W._update_click_through_state()
        check("有内容 → 移除 WS_EX_TRANSPARENT (捕获)",
              ("remove", gw._WS_EX_TRANSPARENT) in styles, str(styles))

        # 光标离开客户区 → 强制捕获, 不推进 pick
        styles.clear()
        engine.renderer.sample = "sentinel"
        gw.glfw.get_cursor_pos = lambda w: (-5.0, 450.0)
        W._update_click_through_state()
        check("客户区外 → 强制捕获且不污染 pick",
              engine.renderer.sample == "sentinel"
              and ("remove", gw._WS_EX_TRANSPARENT) in styles, str(styles))

    finally:
        gw.glfw = real_glfw
        gw._user32 = real_user32
        gw._win32_strip_chrome = real_strip
        gw._win32_fill_rect = real_fill
        gw._win32_add_style = real_add
        gw._win32_remove_style = real_remove
        if real_hit is not None:
            W._is_click_through_target = real_hit
        elif hasattr(W, "_is_click_through_target"):
            delattr(W, "_is_click_through_target")
        if "_reapply_win32_styles" in vars(W):
            delattr(W, "_reapply_win32_styles")
        (W._window_mode, W.glfw_window, W._saved_window_rect,
         W._engine, W._click_through) = saved

    total = _RESULTS["pass"] + _RESULTS["fail"]
    status = "OK" if _RESULTS["fail"] == 0 else "FAIL"
    print()
    print(f"RESULT: {status} ({_RESULTS['pass']}/{total})")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
