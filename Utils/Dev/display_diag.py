"""display_diag — 显示环境诊断（远程 / SSH / 无交互桌面会话排查用）。

背景（2026-11-10 用户实测）
    通过 SSH 启动导出成品时报:
        glfw.get_video_mode(monitor) → OSError: access violation reading 0x108
    机器有屏幕、远程软件也能看到桌面 —— 问题不是"没有显示器"，而是**进程不在
    交互式桌面会话里**：Windows 的 SSH 会话有自己的 window station，GLFW 初始化
    能成功，但 `get_primary_monitor()` 交回的句柄指向已失效的显示器结构。

本工具把四种显示信息源并排打印，用来判断"当前会话能拿到什么":

    1. 进程/会话身份 — SessionId、window station、是否交互式桌面
    2. Win32 `EnumDisplaySettings` — 不经 GLFW 的显示模式查询（最可靠）
    3. Win32 `GetSystemMetrics` — 会话桌面尺寸
    4. GLFW `get_primary_monitor` / `get_video_mode` — 引擎实际走的路径（可能崩）

用法:
    .venv-py314t\\Scripts\\python.exe Utils/Dev/display_diag.py
    .venv-py314t\\Scripts\\python.exe Utils/Dev/display_diag.py --json out.json

退出码: 0 表示 Win32 能取到分辨率（引擎可以正常跑）; 3 表示只有回退值。
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
from ctypes import wintypes

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# ── 1. 进程 / 会话身份 ──────────────────────────────────────

def session_info() -> dict:
    out: dict = {"pid": os.getpid(), "session_id": None,
                 "window_station": None, "interactive_desktop": None}
    if os.name != "nt":
        return out
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        u32 = ctypes.WinDLL("user32", use_last_error=True)
        sid = wintypes.DWORD()
        k32.ProcessIdToSessionId(wintypes.DWORD(os.getpid()), ctypes.byref(sid))
        out["session_id"] = int(sid.value)

        # window station / desktop 名字（"WinSta0" + "Default" = 交互式桌面）
        u32.GetProcessWindowStation.restype = wintypes.HANDLE
        station = u32.GetProcessWindowStation()
        buf = ctypes.create_unicode_buffer(256)
        need = wintypes.DWORD()
        if station and u32.GetUserObjectInformationW(
                station, 2, buf, ctypes.sizeof(buf), ctypes.byref(need)):
            out["window_station"] = buf.value

        u32.GetThreadDesktop.restype = wintypes.HANDLE
        desk = u32.GetThreadDesktop(k32.GetCurrentThreadId())
        dbuf = ctypes.create_unicode_buffer(256)
        if desk and u32.GetUserObjectInformationW(
                desk, 2, dbuf, ctypes.sizeof(dbuf), ctypes.byref(need)):
            out["desktop"] = dbuf.value
        out["interactive_desktop"] = (
            out.get("window_station") == "WinSta0" and out.get("desktop") == "Default")
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


# ── 2. Win32 显示模式 ───────────────────────────────────────

class _DEVMODE(ctypes.Structure):
    _fields_ = [
        ("dmDeviceName", wintypes.WCHAR * 32),
        ("dmSpecVersion", wintypes.WORD),
        ("dmDriverVersion", wintypes.WORD),
        ("dmSize", wintypes.WORD),
        ("dmDriverExtra", wintypes.WORD),
        ("dmFields", wintypes.DWORD),
        ("dmPositionX", ctypes.c_long),
        ("dmPositionY", ctypes.c_long),
        ("dmDisplayOrientation", wintypes.DWORD),
        ("dmDisplayFixedOutput", wintypes.DWORD),
        ("dmColor", wintypes.SHORT),
        ("dmDuplex", wintypes.SHORT),
        ("dmYResolution", wintypes.SHORT),
        ("dmTTOption", wintypes.SHORT),
        ("dmCollate", wintypes.SHORT),
        ("dmFormName", wintypes.WCHAR * 32),
        ("dmLogPixels", wintypes.WORD),
        ("dmBitsPerPel", wintypes.DWORD),
        ("dmPelsWidth", wintypes.DWORD),
        ("dmPelsHeight", wintypes.DWORD),
        ("dmDisplayFlags", wintypes.DWORD),
        ("dmDisplayFrequency", wintypes.DWORD),
        ("dmICMMethod", wintypes.DWORD),
        ("dmICMIntent", wintypes.DWORD),
        ("dmMediaType", wintypes.DWORD),
        ("dmDitherType", wintypes.DWORD),
        ("dmReserved1", wintypes.DWORD),
        ("dmReserved2", wintypes.DWORD),
        ("dmPanningWidth", wintypes.DWORD),
        ("dmPanningHeight", wintypes.DWORD),
    ]


def win32_mode() -> dict:
    if os.name != "nt":
        return {"available": False, "reason": "not windows"}
    try:
        u32 = ctypes.WinDLL("user32", use_last_error=True)
        dm = _DEVMODE()
        dm.dmSize = ctypes.sizeof(_DEVMODE)
        if not u32.EnumDisplaySettingsW(None, -1, ctypes.byref(dm)):   # CURRENT
            return {"available": False, "reason": "EnumDisplaySettings failed"}
        return {
            "available": True,
            "size": [int(dm.dmPelsWidth), int(dm.dmPelsHeight)],
            "refresh_hz": int(dm.dmDisplayFrequency),
            "bpp": int(dm.dmBitsPerPel),
            "device": dm.dmDeviceName,
        }
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}"}


def win32_metrics() -> dict:
    if os.name != "nt":
        return {"available": False}
    try:
        u32 = ctypes.WinDLL("user32", use_last_error=True)
        return {"available": True,
                "screen": [int(u32.GetSystemMetrics(0)), int(u32.GetSystemMetrics(1))],
                "virtual_screen": [int(u32.GetSystemMetrics(78)),
                                   int(u32.GetSystemMetrics(79))],
                "monitors": int(u32.GetSystemMetrics(80))}
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}"}


def win32_monitor_devices() -> list:
    """EnumDisplayDevicesW — 列出适配器/显示器（不触碰 GLFW 结构）。"""
    if os.name != "nt":
        return []

    class _DISPLAY_DEVICE(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD),
                    ("DeviceName", wintypes.WCHAR * 32),
                    ("DeviceString", wintypes.WCHAR * 128),
                    ("StateFlags", wintypes.DWORD),
                    ("DeviceID", wintypes.WCHAR * 128),
                    ("DeviceKey", wintypes.WCHAR * 128)]

    out = []
    try:
        u32 = ctypes.WinDLL("user32", use_last_error=True)
        i = 0
        while True:
            dd = _DISPLAY_DEVICE()
            dd.cb = ctypes.sizeof(_DISPLAY_DEVICE)
            if not u32.EnumDisplayDevicesW(None, i, ctypes.byref(dd), 0):
                break
            out.append({"name": dd.DeviceName, "desc": dd.DeviceString,
                        "flags": hex(int(dd.StateFlags)),
                        "primary": bool(dd.StateFlags & 0x4),
                        "attached": bool(dd.StateFlags & 0x1)})
            i += 1
            if i > 16:
                break
    except Exception as exc:  # noqa: BLE001
        out.append({"error": f"{type(exc).__name__}: {exc}"})
    return out


# ── 3. GLFW（引擎实际路径，可能崩）─────────────────────────

def glfw_info() -> dict:
    out: dict = {"init": False, "primary_monitor": None, "video_mode": None,
                 "monitors": [], "errors": []}
    try:
        import glfw
    except Exception as exc:  # noqa: BLE001
        out["errors"].append(f"import glfw: {type(exc).__name__}: {exc}")
        return out

    errs: list[str] = []

    def _cb(code, desc):
        errs.append(f"[{code}] {desc}")

    try:
        glfw.set_error_callback(_cb)
    except Exception:  # noqa: BLE001
        pass

    try:
        out["init"] = bool(glfw.init())
    except OSError as exc:
        out["errors"].append(f"init: {type(exc).__name__}: {exc}")
        return out
    if not out["init"]:
        out["errors"].append("glfw.init() returned False")
        return out

    try:
        monitors = glfw.get_monitors() or []
        out["monitor_count"] = len(monitors)
        for m in monitors:
            entry = {"name": None, "size": None, "refresh_hz": None}
            try:
                entry["name"] = glfw.get_monitor_name(m)
            except OSError as exc:
                entry["name"] = f"<get_monitor_name failed: {exc}>"
            try:
                vm = glfw.get_video_mode(m)
                if vm is not None:
                    entry["size"] = [vm.size.width, vm.size.height]
                    entry["refresh_hz"] = vm.refresh_rate
            except OSError as exc:
                entry["video_mode_error"] = f"{type(exc).__name__}: {exc}"
            out["monitors"].append(entry)
    except OSError as exc:
        out["errors"].append(f"get_monitors: {type(exc).__name__}: {exc}")

    try:
        pm = glfw.get_primary_monitor()
        out["primary_monitor"] = bool(pm)
        if pm:
            try:
                vm = glfw.get_video_mode(pm)
                if vm is not None:
                    out["video_mode"] = {"size": [vm.size.width, vm.size.height],
                                         "refresh_hz": vm.refresh_rate}
            except OSError as exc:
                # ★ 这正是用户报告的那一行
                out["errors"].append(
                    f"get_video_mode(primary): {type(exc).__name__}: {exc}")
    except OSError as exc:
        out["errors"].append(f"get_primary_monitor: {type(exc).__name__}: {exc}")
    finally:
        try:
            glfw.terminate()
        except Exception:  # noqa: BLE001
            pass
    out["glfw_errors"] = errs
    return out


# ── 汇总 ────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(prog="display_diag",
                                 description="显示环境诊断（远程 / SSH）")
    ap.add_argument("--json", default=None, help="结果写 JSON")
    args = ap.parse_args()

    ses = session_info()
    wmode = win32_mode()
    wmet = win32_metrics()
    wdev = win32_monitor_devices()
    gl = glfw_info()

    print("=" * 62)
    print("display_diag — 显示环境诊断")
    print("=" * 62)
    print(f"\n[1] 进程 / 会话")
    print(f"    pid={ses['pid']}  session_id={ses['session_id']}  "
          f"window_station={ses.get('window_station')!r}  desktop={ses.get('desktop')!r}")
    print(f"    interactive_desktop={ses.get('interactive_desktop')}"
          + ("   ← False 时 GLFW 显示器枚举不可靠" if ses.get("interactive_desktop") is False else ""))

    print(f"\n[2] Win32 EnumDisplaySettings（绕开 GLFW）")
    print(f"    {wmode}")

    print(f"\n[3] Win32 GetSystemMetrics")
    print(f"    {wmet}")

    print(f"\n[4] EnumDisplayDevices")
    for d in wdev:
        print(f"    {d}")

    print(f"\n[5] GLFW（引擎实际走的路径）")
    print(f"    init={gl.get('init')}  monitor_count={gl.get('monitor_count')}")
    for m in gl.get("monitors") or []:
        print(f"    monitor: {m}")
    print(f"    video_mode={gl.get('video_mode')}")
    for e in gl.get("errors") or []:
        print(f"    !! {e}")
    for e in gl.get("glfw_errors") or []:
        print(f"    glfw_error: {e}")

    # ── 判据 ──
    ok = bool(wmode.get("available"))
    print("\n" + "-" * 62)
    if gl.get("errors"):
        print("结论: 当前会话**不能**安全查询 GLFW 显示器（引擎已自动回退）。")
        print("      建议: 用 MGE_WINDOW=windowed + MGE_WINDOW_SIZE=<W>x<H> 启动。")
    elif ok:
        print("结论: 显示查询正常，引擎可按任意模式启动。")
    else:
        print("结论: 只能拿到回退值（1920x1080），画面可能不在预期位置。")
    print("-" * 62)

    if args.json:
        payload = {"session": ses, "win32_mode": wmode, "win32_metrics": wmet,
                   "win32_devices": wdev, "glfw": gl,
                   "env": {k: os.environ.get(k) for k in
                           ("MGE_WINDOW", "MGE_WINDOW_SIZE", "MGE_MONITOR",
                            "MGE_VSYNC", "SESSIONNAME")}}
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1)
        print(f"(已写入 {args.json})")
    return 0 if ok else 3


if __name__ == "__main__":
    raise SystemExit(main())
