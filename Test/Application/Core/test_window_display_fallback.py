"""Regression: 显示查询绝不允许打死进程（远程 / SSH / 非交互桌面会话）。

背景（2026-11-10 用户报告）
    SSH 里启动导出成品 → `glfw.get_video_mode(monitor)` →
    `OSError: access violation reading 0x108`，进程直接退出。
    根因是 SSH 会话不在交互式桌面（独立 window station），`get_primary_monitor()`
    交回的句柄失效，GLFW 解引用即崩。

守卫口径
    - 任何显示查询失败 → 返回回退值，**不抛异常**；
    - `MGE_WINDOW_SIZE` 优先级最高，且能完全绕开显示器枚举；
    - `MGE_MONITOR=off` / 一旦探测失败 → 后续不再查询（幂等、不刷屏）；
    - FULLSCREEN 无可用显示器 → 降级结论可判定（由 `_safe_primary_monitor()` 返回 None 表达）。
"""
# TIER: core

from __future__ import annotations

import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Application.Core.Window.glfwWindow import glfwWindow  # noqa: E402

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


class _Restore:
    """保存 / 恢复类属性与环境变量（守卫测试之间不互相污染）。"""

    _ATTRS = ("_monitor_queries_broken", "_env_resolution",
              "_win32_system_resolution_raw")

    def __enter__(self):
        self._saved = {a: getattr(glfwWindow, a, None) for a in self._ATTRS}
        self._env = {k: os.environ.get(k) for k in
                     ("MGE_WINDOW_SIZE", "MGE_MONITOR", "MGE_WINDOW")}
        for k in self._env:
            os.environ.pop(k, None)
        glfwWindow._monitor_queries_broken = False
        glfwWindow._env_resolution = None
        self._win32_orig = glfwWindow._win32_system_resolution
        return self

    def __exit__(self, *exc):
        glfwWindow._win32_system_resolution = self._win32_orig
        for a, v in self._saved.items():
            if v is not None:
                setattr(glfwWindow, a, v)
        glfwWindow._monitor_queries_broken = False
        glfwWindow._env_resolution = None
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return False


def main() -> int:
    with _Restore():
        # ── A. 一切正常：能拿到分辨率 ──
        w, h = glfwWindow._get_system_resolution()
        check("正常路径返回有效分辨率",
              isinstance(w, int) and w >= 320 and isinstance(h, int) and h >= 240,
              f"{w}x{h}")

        # ── B. Win32 与 GLFW 全不可用 → 回退 1920x1080，不抛异常 ──
        glfwWindow._env_resolution = None
        glfwWindow._win32_system_resolution = staticmethod(lambda: None)
        glfwWindow._monitor_queries_broken = True
        try:
            w2, h2 = glfwWindow._get_system_resolution()
            ok_b = (w2, h2) == (1920, 1080)
        except BaseException as exc:                      # noqa: BLE001
            ok_b = False
            w2 = h2 = f"raised {type(exc).__name__}: {exc}"
        check("全部探测失败 → 回退 1920x1080 且不抛", ok_b, f"{w2}x{h2}")

        # ── C. MGE_MONITOR=off 时不查 GLFW ──
        glfwWindow._env_resolution = None
        glfwWindow._monitor_queries_broken = False
        os.environ["MGE_MONITOR"] = "off"
        check("MGE_MONITOR=off → _monitors_disabled()",
              glfwWindow._monitors_disabled() is True)
        check("MGE_MONITOR=off → _safe_primary_monitor() is None",
              glfwWindow._safe_primary_monitor() is None)
        check("MGE_MONITOR=off → _safe_video_mode(None) is None",
              glfwWindow._safe_video_mode(None) is None)
        os.environ.pop("MGE_MONITOR", None)

        # ── D. MGE_WINDOW_SIZE 优先且能解析多种写法 ──
        for raw, want in (("1280x720", (1280, 720)), ("1024X600", (1024, 600)),
                          ("800*600", (800, 600)), ("640,480", (640, 480))):
            os.environ["MGE_WINDOW_SIZE"] = raw
            got = glfwWindow._env_size()
            check(f"MGE_WINDOW_SIZE={raw} → {want}", got == want, str(got))
        os.environ["MGE_WINDOW_SIZE"] = "garbage"
        check("非法 MGE_WINDOW_SIZE → None", glfwWindow._env_size() is None,
              str(glfwWindow._env_size()))
        os.environ["MGE_WINDOW_SIZE"] = "10x10"
        check("过小 MGE_WINDOW_SIZE → None", glfwWindow._env_size() is None,
              str(glfwWindow._env_size()))
        os.environ.pop("MGE_WINDOW_SIZE", None)

        # ── E. MGE_WINDOW 覆盖模式 ──
        os.environ["MGE_WINDOW"] = "windowed"
        check("MGE_WINDOW=windowed 可解析",
              glfwWindow._env_window_mode() is not None
              and glfwWindow._env_window_mode().value == "windowed")
        os.environ["MGE_WINDOW"] = "overlay"
        check("MGE_WINDOW=overlay → borderless",
              glfwWindow._env_window_mode() is not None
              and glfwWindow._env_window_mode().value == "borderless")
        os.environ["MGE_WINDOW"] = "nonsense"
        check("非法 MGE_WINDOW → None（保留原模式）",
              glfwWindow._env_window_mode() is None)
        os.environ.pop("MGE_WINDOW", None)

        # ── F. 探测失败只告警一次（不刷屏）──
        glfwWindow._env_resolution = None
        glfwWindow._monitor_queries_broken = False

        class _Boom:
            def __call__(self, *a, **k):
                raise OSError("access violation reading 0x108")

        glfwWindow._win32_system_resolution = staticmethod(lambda: None)
        import Application.Core.Window.glfwWindow as mod
        _orig_pm = mod.glfw.get_primary_monitor
        mod.glfw.get_primary_monitor = _Boom()
        try:
            w3 = glfwWindow._safe_primary_monitor()
            broke = glfwWindow._monitor_queries_broken
            w4 = glfwWindow._safe_primary_monitor()      # 第二次应短路，不再调用
        except BaseException as exc:                      # noqa: BLE001
            w3 = f"raised {type(exc).__name__}"
            broke = False
        finally:
            mod.glfw.get_primary_monitor = _orig_pm
        check("get_primary_monitor 抛 OSError → 返回 None", w3 is None, str(w3))
        check("失败后置 _monitor_queries_broken", broke is True, str(broke))
        check("失败后再次调用直接短路", w4 is None, str(w4))

    print(f"RESULT: {_RESULTS['pass']}/{_RESULTS['pass'] + _RESULTS['fail']} passed, "
          f"{_RESULTS['fail']} failed")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
