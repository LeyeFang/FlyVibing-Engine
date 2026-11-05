"""overlay_probe — Overlay 覆盖层窗口实时自检（Win32，无第三方依赖）。

检查项:
  1. 窗口矩形 = 整屏 (0,0,screen_w,screen_h)，**没有标题栏/边框**（WS_CAPTION / WS_THICKFRAME 已剥）
  2. 透明覆盖层样式: WS_EX_LAYERED + HWND_TOPMOST
  3. 输入穿透: 光标指到"有内容"坐标 → WS_EX_TRANSPARENT 关闭（捕获）
              光标指到"空白"坐标 → WS_EX_TRANSPARENT 打开（穿透，WindowFromPoint = 下方窗口）

为什么需要（2026-11-04 实机踩坑）:
  - 先定位尺寸再剥 chrome → 客户区带偏移: 实测 -8,-31 1936x1100 @1920x1080（右下留缝）
  - 穿透窗口在透明处收不到 WM_MOUSEMOVE → 只靠事件更新 pick 时命中判定会冻结

用法:
  python Utils/Dev/overlay_probe.py --content 960,540 --blank 300,300
  python Utils/Dev/overlay_probe.py --title "Game (PIE)" --settle 0.4

退出码: 0 = 全部通过; 1 = 有检查失败; 2 = 找不到目标窗口
"""

from __future__ import annotations

import argparse
import ctypes
import sys
import time
from ctypes import wintypes

_user32 = ctypes.windll.user32

_GWL_STYLE = -16
_GWL_EXSTYLE = -20
_WS_CAPTION = 0x00C00000
_WS_THICKFRAME = 0x00040000
_WS_EX_TRANSPARENT = 0x00000020
_WS_EX_LAYERED = 0x00080000
_WS_EX_TOPMOST = 0x00000008

_user32.GetWindowLongPtrW.restype = ctypes.c_longlong
_user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_user32.IsWindowVisible.argtypes = [wintypes.HWND]
_user32.WindowFromPoint.restype = wintypes.HWND
_user32.WindowFromPoint.argtypes = [wintypes.POINT]


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


_ENUM_PROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def find_window(title: str) -> int:
    """按标题精确匹配返回 HWND（0 = 未找到）。"""
    found = []

    def _cb(hwnd, _lparam):
        buf = ctypes.create_unicode_buffer(512)
        _user32.GetWindowTextW(hwnd, buf, 512)
        if buf.value == title and _user32.IsWindowVisible(hwnd):
            found.append(int(hwnd))
            return False
        return True

    _user32.EnumWindows(_ENUM_PROC(_cb), 0)
    return found[0] if found else 0


def window_title(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(512)
    _user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


def window_rect(hwnd: int) -> tuple[int, int, int, int]:
    r = _RECT()
    _user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right - r.left, r.bottom - r.top

def styles(hwnd: int) -> dict:
    style = _user32.GetWindowLongPtrW(hwnd, _GWL_STYLE)
    ex = _user32.GetWindowLongPtrW(hwnd, _GWL_EXSTYLE)
    return {
        "caption": bool(style & _WS_CAPTION),
        "thickframe": bool(style & _WS_THICKFRAME),
        "layered": bool(ex & _WS_EX_LAYERED),
        "click_through": bool(ex & _WS_EX_TRANSPARENT),
        "topmost": bool(ex & _WS_EX_TOPMOST),
    }


def move_cursor(x: int, y: int) -> None:
    _user32.SetCursorPos(int(x), int(y))


def window_under(x: int, y: int) -> int:
    pt = wintypes.POINT(int(x), int(y))
    return int(_user32.WindowFromPoint(pt))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Overlay 覆盖层窗口实时自检")
    ap.add_argument("--title", default="Game (PIE)", help="目标窗口标题（默认 'Game (PIE)'）")
    ap.add_argument("--content", default="", help="有渲染内容的屏幕坐标 'x,y'（应捕获鼠标）")
    ap.add_argument("--blank", default="", help="透明区域的屏幕坐标 'x,y'（应穿透鼠标；--modal 时反过来）")
    ap.add_argument("--modal", action="store_true",
                    help="对话框/模态 UI 打开中：此时空白处也必须捕获（不穿透）")
    ap.add_argument("--settle", type=float, default=0.4, help="移动光标后等待秒数（默认 0.4）")
    args = ap.parse_args(argv)

    hwnd = find_window(args.title)
    if not hwnd:
        print(f"[overlay_probe] window not found: {args.title!r}")
        return 2

    fails = 0

    def check(label: str, cond: bool, detail: str = "") -> None:
        nonlocal fails
        if not cond:
            fails += 1
        print(f"  [{'PASS' if cond else 'FAIL'}] {label}"
              + (f"  ({detail})" if detail and not cond else ""))

    screen_w = _user32.GetSystemMetrics(0)
    screen_h = _user32.GetSystemMetrics(1)
    x, y, w, h = window_rect(hwnd)
    st = styles(hwnd)

    print("=" * 60)
    print(f"overlay window probe - {args.title}  hwnd=0x{hwnd:X}")
    print("=" * 60)
    print(f"  rect   : {x},{y} {w}x{h}   (screen {screen_w}x{screen_h})")
    print(f"  styles : {st}")

    print("-- geometry / chrome --")
    check("覆盖整屏 (0,0,screen)", (x, y, w, h) == (0, 0, screen_w, screen_h),
          f"{x},{y} {w}x{h}")
    check("无标题栏 (WS_CAPTION 已剥)", not st["caption"])
    check("无边框 (WS_THICKFRAME 已剥)", not st["thickframe"])
    check("透明覆盖层 (WS_EX_LAYERED)", st["layered"])
    check("置顶 (WS_EX_TOPMOST)", st["topmost"])

    if args.content:
        print("-- hit test: rendered content --")
        cx, cy = (int(v) for v in args.content.split(","))
        move_cursor(cx, cy)
        time.sleep(args.settle)
        st2 = styles(hwnd)
        under = window_under(cx, cy)
        check("有内容 → 捕获鼠标 (WS_EX_TRANSPARENT 关闭)", not st2["click_through"],
              f"clickthrough={st2['click_through']}")
        check("有内容 → WindowFromPoint = 覆盖层窗口", under == hwnd,
              f"under=0x{under:X} '{window_title(under)}'")

    if args.blank:
        print("-- hit test: transparent area --")
        bx, by = (int(v) for v in args.blank.split(","))
        move_cursor(bx, by)
        time.sleep(args.settle)
        st3 = styles(hwnd)
        under = window_under(bx, by)
        if args.modal:
            # 模态 UI 打开：空白处也必须捕获（否则点弹窗会穿到桌面）
            check("模态打开 → 空白处仍捕获 (WS_EX_TRANSPARENT 关闭)",
                  not st3["click_through"], f"clickthrough={st3['click_through']}")
            check("模态打开 → WindowFromPoint = 覆盖层窗口", under == hwnd,
                  f"under=0x{under:X} '{window_title(under)}'")
        else:
            check("透明处 → 穿透鼠标 (WS_EX_TRANSPARENT 打开)", st3["click_through"],
                  f"clickthrough={st3['click_through']}")
            check("透明处 → WindowFromPoint = 下方窗口", under != hwnd,
                  f"under=0x{under:X} '{window_title(under)}'")

    print()
    total = 6 + (2 if args.content else 0) + (2 if args.blank else 0)
    print(f"RESULT: {'OK' if fails == 0 else 'FAIL'} ({total - fails}/{total})")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
