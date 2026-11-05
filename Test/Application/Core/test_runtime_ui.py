"""运行时 UI（M0）守卫：布局/命中数学 + 退出确认对话框状态机（无 GL、无窗口）。

锁定内容:
  1. `content_box`：fit_height / fit_width / stretch 的内容框与缩放
  2. `resolve_rect`：9 宫格锚点 + 枢轴 + 参考分辨率缩放
  3. `rect_hit`：边界含/不含
  4. 对话框：ESC 开/关、Yes → 停止请求、No → 仅关闭、点空白不触发
  5. 模态：对话框打开时键鼠被 consume（节点图收不到）
"""

# TIER: core

from __future__ import annotations

import os
import sys

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

from Application.Core.Events.InputEvent import (  # noqa: E402
    KeyboardButtonEvent,
    MouseButtonEvent,
    MouseMoveEvent,
)
from Application.Core.Events.WindowEvent import WindowCloseEvent  # noqa: E402
from Application.Core.UI.layout import (  # noqa: E402
    UIQuad,
    content_box,
    rect_hit,
    resolve_rect,
)
from Application.Runtime import RuntimeUILayer as _ui_module  # noqa: E402
from Application.Runtime.RuntimeUILayer import RuntimeUILayer  # noqa: E402

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


def main() -> int:
    print("=" * 60)
    print("runtime UI — layout math + exit-confirm dialog")
    print("=" * 60)

    # ── 1. content_box ──
    print("-- 1. content box --")
    box, scale = content_box(1920, 1080)
    check("1920x1080 → 内容框铺满 / scale=1",
          box == (0.0, 0.0, 1920.0, 1080.0) and scale == (1.0, 1.0), f"{box} {scale}")
    box, scale = content_box(2560, 1080)
    check("2560x1080 (fit_height) → 两侧各留 320 / scale=1",
          box == (320.0, 0.0, 1920.0, 1080.0) and scale == (1.0, 1.0), f"{box} {scale}")
    box, scale = content_box(1920, 540)
    check("1920x540 → 等比缩到 0.5",
          abs(scale[0] - 0.5) < 1e-6 and box[2] == 960.0, f"{box} {scale}")
    box, scale = content_box(1920, 540, "stretch")
    check("stretch → 拉满且 scale 各向异性",
          box == (0.0, 0.0, 1920.0, 540.0) and scale == (1.0, 0.5), f"{box} {scale}")

    # ── 2. resolve_rect ──
    print("-- 2. anchor / pivot --")
    box = (0.0, 0.0, 1920.0, 1080.0)
    one = (1.0, 1.0)
    r = resolve_rect((0.0, 0.0), (200.0, 100.0), box, one, "center", "center")
    check("center/center → 正中", r == (860.0, 490.0, 200.0, 100.0), str(r))
    r = resolve_rect((24.0, 16.0), (200.0, 100.0), box, one, "top_left", "top_left")
    check("top_left + 偏移", r == (24.0, 16.0, 200.0, 100.0), str(r))
    r = resolve_rect((0.0, 0.0), (200.0, 100.0), box, one, "bottom_right", "bottom_right")
    check("bottom_right 贴角", r == (1720.0, 980.0, 200.0, 100.0), str(r))
    r = resolve_rect((0.0, 0.0), (200.0, 100.0), (320.0, 0.0, 1920.0, 1080.0), one,
                     "center", "center")
    check("内容框偏移计入 (超宽屏居中)", r == (1180.0, 490.0, 200.0, 100.0), str(r))
    r = resolve_rect((0.0, 0.0), (200.0, 100.0), box, (0.5, 0.5), "center", "center")
    check("scale=0.5 尺寸同比、锚点仍在框中心", r == (910.0, 515.0, 100.0, 50.0), str(r))

    # ── 3. rect_hit ──
    print("-- 3. hit test --")
    check("内部命中", rect_hit((10, 10, 100, 50), 60, 30))
    check("边界含", rect_hit((10, 10, 100, 50), 10, 10) and rect_hit((10, 10, 100, 50), 110, 60))
    check("外部不命中", not rect_hit((10, 10, 100, 50), 9, 30)
          and not rect_hit((10, 10, 100, 50), 60, 61))

    # ── 4/5. 对话框状态机 + 模态 ──
    print("-- 4. exit-confirm dialog --")
    saved = (RuntimeUILayer._enabled, RuntimeUILayer._open, RuntimeUILayer._hover,
             RuntimeUILayer._pressed, RuntimeUILayer._rects,
             RuntimeUILayer._title, RuntimeUILayer._yes, RuntimeUILayer._no,
             RuntimeUILayer._hint, RuntimeUILayer._renderer, RuntimeUILayer._dirty)

    from Application.Runtime.RuntimeNodeLayer import RuntimeNodeLayer
    real_request_stop = RuntimeNodeLayer.__dict__.get("request_stop")
    stop_calls: list[int] = []

    # 记录文本光栅化调用（避免依赖 Pillow 字体度量结果）
    real_text = RuntimeUILayer._text_image
    RuntimeUILayer._text_image = classmethod(
        lambda cls, text, size, color: (len(str(text)) * max(8, size // 2), size, None, f"t:{text}"))
    try:
        RuntimeNodeLayer.request_stop = classmethod(lambda cls: stop_calls.append(1))
        RuntimeUILayer.configure(title="Exit?", yes="Yes", no="No", hint="Esc = No")
        RuntimeUILayer.set_enabled(True)
        RuntimeUILayer._open = False
        RuntimeUILayer._hover = ""
        RuntimeUILayer._pressed = ""
        RuntimeUILayer._rects = {}

        ev = WindowCloseEvent(source="escape")
        RuntimeUILayer.OnEvent(ev)
        check("ESC → 打开对话框并被消费", RuntimeUILayer.is_open() and ev.consumed)

        quads = RuntimeUILayer.build_quads(1920, 1080)
        check("对话框产出 12 个 quad（遮罩/面板/4 边/标题/提示/2 按钮/2 文字）",
              len(quads) == 12 and all(isinstance(q, UIQuad) for q in quads), f"{len(quads)}")
        check("quad 覆盖整帧遮罩",
              quads[0].x == 0 and quads[0].y == 0 and quads[0].w == 1920 and quads[0].h == 1080)
        check("按钮矩形已登记（yes/no）",
              set(RuntimeUILayer._rects) == {"yes", "no"}, str(RuntimeUILayer._rects))

        # 点 No
        no_x, no_y, no_w, no_h = RuntimeUILayer._rects["no"]
        cx, cy = int(no_x + no_w / 2), int(no_y + no_h / 2)
        move = MouseMoveEvent(cx, cy)
        RuntimeUILayer.OnEvent(move)
        check("鼠标移动被消费且更新 hover",
              move.consumed and RuntimeUILayer._hover == "no", RuntimeUILayer._hover)
        RuntimeUILayer.OnEvent(MouseButtonEvent(0, 1, 0, cx, cy))
        rel = MouseButtonEvent(0, 0, 0, cx, cy)
        RuntimeUILayer.OnEvent(rel)
        check("点 No → 关闭且不请求停止", (not RuntimeUILayer.is_open()) and not stop_calls,
              f"open={RuntimeUILayer.is_open()} stop={stop_calls}")

        # 点 Yes
        RuntimeUILayer.open()
        RuntimeUILayer.build_quads(1920, 1080)
        yes_x, yes_y, yes_w, yes_h = RuntimeUILayer._rects["yes"]
        yx, yy = int(yes_x + yes_w / 2), int(yes_y + yes_h / 2)
        RuntimeUILayer.OnEvent(MouseMoveEvent(yx, yy))
        RuntimeUILayer.OnEvent(MouseButtonEvent(0, 1, 0, yx, yy))
        RuntimeUILayer.OnEvent(MouseButtonEvent(0, 0, 0, yx, yy))
        check("点 Yes → 请求停止（ExitGame 同一条链）",
              stop_calls == [1] and not RuntimeUILayer.is_open(), str(stop_calls))

        # 点空白（面板外）
        RuntimeUILayer.open()
        RuntimeUILayer.build_quads(1920, 1080)
        RuntimeUILayer.OnEvent(MouseMoveEvent(8, 8))
        RuntimeUILayer.OnEvent(MouseButtonEvent(0, 1, 0, 8, 8))
        RuntimeUILayer.OnEvent(MouseButtonEvent(0, 0, 0, 8, 8))
        check("点遮罩空白 → 不关闭也不停止",
              RuntimeUILayer.is_open() and stop_calls == [1], f"stop={stop_calls}")

        # 模态吞键
        kb = KeyboardButtonEvent(32, 0, 1, 0)
        RuntimeUILayer.OnEvent(kb)
        check("对话框打开时键盘事件被消费（节点图收不到）", kb.consumed)

        # ESC 再按 = 关闭（= No）
        ev2 = WindowCloseEvent(source="escape")
        RuntimeUILayer.OnEvent(ev2)
        check("ESC 再按 → 关闭对话框", (not RuntimeUILayer.is_open()) and ev2.consumed)

        # 关闭后 ESC 不再消费（交回引擎的关闭窗口安全网）
        RuntimeUILayer.set_enabled(False)
        ev3 = WindowCloseEvent(source="escape")
        RuntimeUILayer.OnEvent(ev3)
        check("禁用后 ESC 不消费（保留关窗安全网）", not ev3.consumed)
    finally:
        RuntimeUILayer._text_image = real_text
        if real_request_stop is not None:
            RuntimeNodeLayer.request_stop = real_request_stop
        elif hasattr(RuntimeNodeLayer, "request_stop"):
            delattr(RuntimeNodeLayer, "request_stop")
        (RuntimeUILayer._enabled, RuntimeUILayer._open, RuntimeUILayer._hover,
         RuntimeUILayer._pressed, RuntimeUILayer._rects,
         RuntimeUILayer._title, RuntimeUILayer._yes, RuntimeUILayer._no,
         RuntimeUILayer._hint, RuntimeUILayer._renderer, RuntimeUILayer._dirty) = saved
        _ui_module.RuntimeUILayer._text_cache.clear()

    total = _RESULTS["pass"] + _RESULTS["fail"]
    status = "OK" if _RESULTS["fail"] == 0 else "FAIL"
    print()
    print(f"RESULT: {status} ({_RESULTS['pass']}/{total})")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
