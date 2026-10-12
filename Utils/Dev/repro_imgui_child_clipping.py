#!/usr/bin/env python3
"""Minimal repro — imgui BeginChild()/EndChild() pairing under full clipping (0x0).

来源: Gtec 扩展作者在写实时监视面板时实测（2026-10-12）—— 宿主窗口最小化 0x0 →
`BeginChild()` 返回 False → 漏 `EndChild()` → 之后任意 `End()` 断言杀掉渲染循环。
卷宗（现象 / 语义实测 / 上游 issue 稿）: `Doc/Dev/upstream_imgui_beginchild_fullclip.md`。

⚠ 本脚本**故意**包含反模式（场景 B 把 `EndChild()` 放进 `if` 内）—— 属于演示用代码,
位于 `Utils/Dev/`（不在 `Application/Editor/**` 与 `Functions/**` 的配对守卫扫描范围内）。

用途: (1) 提交 imgui / imgui_bundle 上游的复现材料; (2) 长期可重跑的语义回归
（升级 imgui_bundle 后重跑, 确认 4 条语义仍成立）。

Companion material for ISSUE.md (now `Doc/Dev/upstream_imgui_beginchild_fullclip.md`).
Runs standalone against imgui_bundle; no GL renderer needed — we only exercise the Begin/End
window-stack bookkeeping (an imgui assert is raised as RuntimeError by imgui_bundle).

Observed environment:
    imgui_bundle 1.92.5 / Dear ImGui 1.92.3, Python 3.14 (free-threaded), Windows.

Scenarios (each runs in a FRESH imgui context — an imgui assert poisons the context):
  A  correct pattern      EndChild() is called ALWAYS; display cycles
                          1280x720 -> 0x0 (minimize) -> 1x1 -> 1280x720.
  B  wrong pattern        EndChild() is placed inside `if (BeginChild()) { ... }`
                          (a historically widespread pattern). At 0x0 the child is
                          fully clipped -> BeginChild() returns false -> EndChild()
                          is skipped -> the window stack is corrupted, and the
                          assert fires on the enclosing End() (or a later End()
                          in real programs), far from the actual cause.
  C  related asymmetry    For contrast: EndCombo() must be called ONLY when
                          BeginCombo() returned true (opposite rule).
  D  official debug tool  io.ConfigDebugBeginReturnValueOnce / ...Loop exist and
                          force Begin()/BeginChild() to return false — the
                          supported way to catch this class of bug in dev.

Exit code: 0 = all semantics confirmed; 2 = unexpected behavior / environment issue.
"""

from __future__ import annotations

import sys

from imgui_bundle import imgui

if hasattr(sys.stdout, "reconfigure"):    # keep C++ [imgui-error] log lines in order
    sys.stdout.reconfigure(line_buffering=True)


def _unbuffer_native_stdout() -> None:
    """Make the CRT's own stdout unbuffered so imgui's C-side log lines
    (e.g. '[imgui-error] ...') appear strictly in chronological order in all
    capture modes (console / pipe / file redirection)."""
    try:
        import ctypes

        crt = ctypes.CDLL("ucrtbase.dll")
        crt._acrt_iob_func.restype = ctypes.c_void_p
        crt._acrt_iob_func.argtypes = [ctypes.c_uint]
        fp = crt._acrt_iob_func(1)                       # FILE* stdout
        crt.setvbuf.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                ctypes.c_int, ctypes.c_size_t]
        crt.setvbuf(ctypes.c_void_p(fp), None, 4, 0)     # _IONBF = 4
    except Exception:                    # noqa: BLE001 — non-Windows / static CRT
        pass


def _flush_native_log() -> None:
    """Force imgui's C-side log lines out now (they bypass Python's stdout)."""
    try:
        import ctypes

        ctypes.CDLL("ucrtbase.dll").fflush(None)
    except Exception:                    # noqa: BLE001 — non-Windows / static CRT
        pass


_unbuffer_native_stdout()


_EXPECTED = {"confirmed": 0, "unexpected": 0}


def _expect(ok: bool) -> None:
    key = "confirmed" if ok else "unexpected"
    _EXPECTED[key] += 1


def _make_context(display=(1280, 720), debug_once=False, debug_loop=False):
    """Fresh imgui context with a bare, backend-version-agnostic setup."""
    imgui.create_context()
    io = imgui.get_io()
    io.backend_flags |= imgui.BackendFlags_.renderer_has_textures
    io.display_size = imgui.ImVec2(float(display[0]), float(display[1]))
    io.delta_time = 1.0 / 60.0
    try:
        io.set_ini_filename("")          # disable imgui.ini file I/O
    except Exception:                    # noqa: BLE001 — older bindings
        pass
    if debug_once:
        io.config_debug_begin_return_value_once = True
    if debug_loop:
        io.config_debug_begin_return_value_loop = True
    return io


def _frame(body) -> None:
    imgui.new_frame()
    body()
    imgui.end_frame()
    imgui.render()


def _destroy() -> None:
    try:
        imgui.destroy_context()
    except Exception:                    # noqa: BLE001 — poisoned context tolerates
        pass


# ── A ────────────────────────────────────────────────────────────────────────
def scenario_a() -> None:
    print("-- A: correct pattern (EndChild always) --")
    io = _make_context()
    rets = []

    def body():
        imgui.begin("W")
        visible = imgui.begin_child("C", imgui.ImVec2(300.0, 200.0), True)
        rets.append(bool(visible))
        if visible:
            imgui.text("content")
        imgui.end_child()                # ← ALWAYS paired
        imgui.end()

    ok = True
    try:
        for disp in ((1280, 720), (0, 0), (1, 1), (1280, 720)):
            io.display_size = imgui.ImVec2(float(disp[0]), float(disp[1]))
            _frame(body)
    except Exception as e:               # noqa: BLE001
        ok = False
        print(f"   frame sequence RAISED: {type(e).__name__}: {e}")
    finally:
        _destroy()
    if ok:
        print(f"   4 frames OK; begin_child() returned per frame: {rets}")
        print("   children ->", "False at 0x0/1x1" if rets[1:3] == [False, False] else rets)
        _expect(rets[1:3] == [False, False] and rets[0] is True and rets[3] is True)
    else:
        _expect(False)


# ── B ────────────────────────────────────────────────────────────────────────
def scenario_b() -> None:
    print("-- B: wrong pattern (EndChild inside the if) --")
    io = _make_context()
    log = []

    def body():
        imgui.begin("W")
        visible = imgui.begin_child("C", imgui.ImVec2(300.0, 200.0), True)
        log.append(bool(visible))
        if visible:
            imgui.text("content")
            imgui.end_child()            # ← wrong pattern: skipped when false
        imgui.end()

    ok = False
    message = ""
    try:
        # frame 1: normal size -- child visible, the bad pattern HAPPENS TO BALANCE.
        # This is why the bug survives code review and normal-size testing.
        _frame(body)
        print(f"   frame@1280x720: no exception (begin_child={log[-1]})"
              " — mispairing invisible at normal size")
        # frame 2: fully clipped, as when the host window is minimized (0x0).
        io.display_size = imgui.ImVec2(0.0, 0.0)
        try:
            _frame(body)
            print(f"   frame@0x0: no exception (begin_child={log[-1]})")
        except Exception as e:           # noqa: BLE001
            message = f"{type(e).__name__}: {e}"
            print(f"   frame@0x0: begin_child={log[-1]}"
                  f" -> RAISED on the same frame's End() -> {message}")
            _flush_native_log()
            ok = "Must call EndChild" in message and log[-1] is False
    finally:
        _destroy()
    _expect(ok)


# ── C ────────────────────────────────────────────────────────────────────────
def scenario_c() -> None:
    print("-- C: asymmetry contrast — EndCombo is conditional --")
    io = _make_context()
    ok_cond = False
    msg_uncond = "no exception"

    def body_ok():
        imgui.begin("W")
        opened = imgui.begin_combo("CB", "closed")
        if opened:
            imgui.end_combo()            # ← only when open (correct)
        imgui.end()

    try:
        _frame(body_ok)
        ok_cond = True
        print("   conditional EndCombo: OK")
    except Exception as e:               # noqa: BLE001
        print(f"   conditional EndCombo: RAISED {type(e).__name__}: {e}")

    def body_bad():
        imgui.begin("W")
        imgui.begin_combo("CB2", "closed")
        imgui.end_combo()                # ← always (wrong)
        imgui.end()

    try:
        _frame(body_bad)
        print("   unconditional EndCombo: no exception (unexpected)")
    except Exception as e:               # noqa: BLE001
        msg_uncond = f"{type(e).__name__}: {e}"
        print(f"   unconditional EndCombo: RAISED -> {msg_uncond}")
        _flush_native_log()
    _destroy()
    _expect(ok_cond and "EndPopup" in msg_uncond)


# ── D ────────────────────────────────────────────────────────────────────────
def scenario_d() -> None:
    print("-- D: official debug tool — io.ConfigDebugBeginReturnValue* --")
    # D1: debug_once=True + correct pattern → returns false once, still balanced.
    io = _make_context(debug_once=True)
    rets = []

    def body_ok():
        r0 = imgui.begin("W")
        rets.append(("begin", bool(r0)))
        visible = imgui.begin_child("C", imgui.ImVec2(300.0, 200.0), True)
        rets.append(("child", bool(visible)))
        if visible:
            imgui.text("content")
        imgui.end_child()                # always
        imgui.end()

    ok_once = False
    try:
        _frame(body_ok)
        ok_once = True
        print(f"   debug-once + correct pattern: OK, returns={rets}")
    except Exception as e:               # noqa: BLE001
        print(f"   debug-once + correct pattern: RAISED {type(e).__name__}: {e}")
    _destroy()
    _flush_native_log()

    # D2: debug_loop=True + wrong pattern -> the same failure class, surfaced in dev.
    # (imgui cycles Begin()/BeginChild() return values through window depths;
    #  with this minimal window stack the child flips to false on frame 12.)
    io = _make_context(debug_loop=True)
    rets_loop = []
    msg_loop = "no exception in 40 frames"

    def body_bad():
        r0 = imgui.begin("W")
        visible = imgui.begin_child("C", imgui.ImVec2(300.0, 200.0), True)
        rets_loop.append((bool(r0), bool(visible)))
        if visible:
            imgui.end_child()            # wrong pattern
        imgui.end()

    try:
        for _ in range(40):
            _frame(body_bad)
        print("   debug-loop + wrong pattern: no exception in 40 frames")
    except Exception as e:               # noqa: BLE001
        msg_loop = f"{type(e).__name__}: {e}"
        first_false = next((i + 1 for i, r in enumerate(rets_loop) if not r[1]), None)
        print(f"   debug-loop + wrong pattern: child flipped to false at frame {first_false}"
              f" of {len(rets_loop)} -> RAISED -> {msg_loop}")
        _flush_native_log()
    _destroy()
    _expect(ok_once and "EndChild" in msg_loop)


def main() -> int:
    print("== imgui BeginChild/EndChild pairing under full clipping (0x0) ==")
    print(f"   Dear ImGui: {imgui.get_version()}")
    try:
        import imgui_bundle
        print(f"   imgui_bundle: {imgui_bundle.__version__}")
    except Exception:                    # noqa: BLE001
        pass
    print()
    scenario_a()
    scenario_b()
    scenario_c()
    scenario_d()
    print()
    total = _EXPECTED["confirmed"] + _EXPECTED["unexpected"]
    status = "OK" if _EXPECTED["unexpected"] == 0 else "UNEXPECTED"
    print(f"RESULT: {status} ({_EXPECTED['confirmed']}/{total} semantics confirmed)")
    return 0 if _EXPECTED["unexpected"] == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
