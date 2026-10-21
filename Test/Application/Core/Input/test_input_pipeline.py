"""InputPipeline / InputState P0 contract tests — no window required.

Run:
    python Utils/Dev/test_runner.py --only test_input_pipeline
"""
# TIER: core

from __future__ import annotations

import os
import sys

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "_path_setup.py")):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)
    import _path_setup  # noqa: E402

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


class FakeBackend:
    """Minimal InputBackend replacement; no GLFW window needed."""

    PRESS = 1
    RELEASE = 0
    REPEAT = 2

    def __init__(self) -> None:
        self.pos = (0.0, 0.0)
        self.key_cb = None
        self.mouse_cb = None
        self.cursor_cb = None
        self.scroll_cb = None

    def set_key_callback(self, cb):
        old = self.key_cb
        self.key_cb = cb
        return old

    def set_mouse_button_callback(self, cb):
        old = self.mouse_cb
        self.mouse_cb = cb
        return old

    def set_cursor_pos_callback(self, cb):
        old = self.cursor_cb
        self.cursor_cb = cb
        return old

    def set_scroll_callback(self, cb):
        old = self.scroll_cb
        self.scroll_cb = cb
        return old

    def get_cursor_pos(self):
        return self.pos


class FakeCamera:
    def __init__(self) -> None:
        self.drags: list[tuple] = []
        self.scrolls: list[float] = []

    def on_mouse_drag(self, button, dx, dy, shift):
        self.drags.append((button, dx, dy, shift))

    def on_scroll(self, yoff):
        self.scrolls.append(yoff)


def main() -> int:
    print("=" * 60)
    print("InputPipeline / InputState P0 contract (headless)")
    print("=" * 60)

    from Application.Core.Input.InputBackend import InputBackend
    from Application.Core.Input.InputPipeline import InputPipeline
    from Application.Core.Events.Enum.InputEnum import KeyButtonCode, MouseButtonCode

    check("fake backend implements abstract surface", hasattr(InputBackend, "get_cursor_pos"))
    backend = FakeBackend()
    # InputPipeline checks isinstance(..., InputBackend); register the fake as a
    # test double without requiring a GLFW window.
    InputBackend.register(FakeBackend)
    old_key = object()
    backend.key_cb = old_key
    pipe = InputPipeline(backend)
    state = pipe.input_state

    # ── 1. keyboard / modifiers ──────────────────────────────
    print("-- keyboard/modifiers --")
    keys: list[tuple] = []
    pipe.on_key = lambda *args: keys.append(args)
    pipe._on_key(None, KeyButtonCode.LeftShift, 0, backend.PRESS, 0)
    check("shift press updates state", state.is_shift_pressed())
    check("key hook fires", len(keys) == 1)
    pipe._on_key(None, KeyButtonCode.LeftShift, 0, backend.RELEASE, 0)
    check("shift release updates state", not state.is_shift_pressed())
    pipe._on_key(None, KeyButtonCode.A, 0, backend.PRESS, 0)
    check("ordinary key becomes held", state.is_key_down(KeyButtonCode.A))
    check("held key list contains A", KeyButtonCode.A in state.get_held_keys())
    pipe._on_key(None, KeyButtonCode.A, 0, backend.RELEASE, 0)
    check("key release clears held", not state.is_key_down(KeyButtonCode.A))

    # ── 2. mouse press / drag / click ───────────────────────
    print("-- mouse press/drag/click --")
    drags: list[tuple] = []
    moves: list[tuple] = []
    buttons: list[tuple] = []
    pipe.on_drag = lambda *args: drags.append(args)
    pipe.on_move = lambda *args: moves.append(args)
    pipe.on_mouse_button = lambda *args: buttons.append(args)
    backend.pos = (10.0, 20.0)
    pipe._on_mouse_button(None, MouseButtonCode.Left, backend.PRESS, 0)
    check("mouse press marks dragging", pipe.is_dragging and pipe.drag_button == MouseButtonCode.Left)
    check("press position captured", pipe.press_pos == (10.0, 20.0))
    check("mouse button hook fires", len(buttons) == 1)
    pipe._on_cursor(None, 14.0, 26.0)
    check("cursor while pressed emits drag", len(drags) == 1
          and drags[0][1:3] == (4.0, 6.0), str(drags))
    backend.pos = (14.0, 26.0)
    pipe._on_mouse_button(None, MouseButtonCode.Left, backend.RELEASE, 0)
    check("release clears dragging", not pipe.is_dragging)
    check("click threshold accepts small release",
          pipe.click_detected(14.0, 26.0, threshold=8.0))
    check("click threshold rejects long move",
          not pipe.click_detected(40.0, 40.0, threshold=4.0))
    pipe._on_cursor(None, 20.0, 30.0)
    check("cursor after release emits move", len(moves) == 1)

    # ── 3. scroll / camera preset ────────────────────────────
    print("-- scroll/camera preset --")
    scrolls: list[tuple] = []
    pipe.on_scroll = lambda *args: scrolls.append(args)
    pipe._on_scroll(None, 0.0, -1.0)
    check("scroll hook fires", scrolls == [(0.0, -1.0)])
    camera = FakeCamera()
    pipe.setup_editor_camera(camera)
    pipe._on_scroll(None, 0.0, 2.0)
    check("camera scroll hook", camera.scrolls == [2.0])
    pipe._on_key(None, KeyButtonCode.LeftShift, 0, backend.PRESS, 0)
    pipe._on_mouse_button(None, MouseButtonCode.Middle, backend.PRESS, 0)
    backend.pos = (100.0, 100.0)
    pipe._on_cursor(None, 110.0, 90.0)
    check("middle drag reaches camera with shift",
          bool(camera.drags) and camera.drags[-1][0] == MouseButtonCode.Middle
          and camera.drags[-1][3] is True, str(camera.drags))
    pipe._on_mouse_button(None, MouseButtonCode.Middle, backend.RELEASE, 0)

    # ── 4. detach restores callbacks ────────────────────────
    print("-- detach --")
    pipe.detach()
    check("detach restores previous key callback", backend.key_cb is old_key)

    total = _RESULTS["pass"] + _RESULTS["fail"]
    status = "OK" if _RESULTS["fail"] == 0 else "FAIL"
    print()
    print(f"RESULT: {status} ({_RESULTS['pass']}/{total})")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
