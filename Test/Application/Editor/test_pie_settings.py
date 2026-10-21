"""
PIE 窗口偏好测试 — Play 下方 Settings (显示模式 + 窗口化尺寸) 数据与映射 (无 GL)。

锁定内容:
  1. 缺省值: windowed 1280×720 (无配置文件时)
  2. set → JSON 持久化 → 重新加载回读一致
  3. 非法输入: mode 非法→忽略保留; 尺寸 clamp 320..7680
  4. 损坏 JSON → 不抛异常, 保持现值
  5. RuntimeWindow.apply_start_preferences 映射:
     windowed → WINDOWED + _default_size_override=(w,h)
     borderless/fullscreen → 对应枚举 + override=None; 非法 mode → 回退 WINDOWED
  6. _apply_pie_window_prefs: Overlay + fullscreen → 回退 borderless; 3D + fullscreen → FULLSCREEN

运行: python Utils/Dev/test_runner.py --only pie_settings
"""
# TIER: core

from __future__ import annotations

import os
import sys
import json
import shutil
import tempfile

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


def main() -> int:
    print("=" * 60)
    print("PIE window settings — mode/size persistence + window mapping")
    print("=" * 60)

    from Application.Editor.UI.controllers.SimulationController import SimulationController as SC
    from Application.Runtime.RuntimeWindow import RuntimeWindow
    from Application.Core.Window.glfwWindow import WindowMode

    orig_path = SC._PIE_SETTINGS_PATH
    orig_vals = (SC._pie_mode, SC._pie_width, SC._pie_height)
    orig_override = RuntimeWindow._default_size_override
    orig_mode = RuntimeWindow._window_mode

    tmpdir = tempfile.mkdtemp(prefix="pie_cfg_")
    SC._PIE_SETTINGS_PATH = os.path.join(tmpdir, "PIE.json")
    SC._pie_mode, SC._pie_width, SC._pie_height = "windowed", 1280, 720
    SC._pie_settings_loaded = False

    try:
        # ── 1. 缺省值 (文件不存在) ──
        s = SC.get_pie_settings()
        check("默认 windowed 1280×720",
              s == {"mode": "windowed", "width": 1280, "height": 720}, str(s))
        check("缺失配置不建文件 (懒保存)", not os.path.exists(SC._PIE_SETTINGS_PATH))

        # ── 2. set → 持久化 → 重载回读 ──
        SC.set_pie_settings(mode="borderless", width=1600, height=900)
        check("set 后 JSON 落盘", os.path.exists(SC._PIE_SETTINGS_PATH))
        with open(SC._PIE_SETTINGS_PATH, "r", encoding="utf-8") as fh:
            disk = json.load(fh)
        check("磁盘内容一致", disk == {"mode": "borderless", "width": 1600, "height": 900}, str(disk))
        # 模拟重启: 复位内存态后重新加载
        SC._pie_settings_loaded = False
        SC._pie_mode, SC._pie_width, SC._pie_height = "windowed", 1, 1
        s2 = SC.get_pie_settings()
        check("重载回读 borderless 1600×900",
              s2 == {"mode": "borderless", "width": 1600, "height": 900}, str(s2))

        # ── 3. 非法输入 ──
        SC.set_pie_settings(mode="bogus")
        check("非法 mode 被忽略 (保留 borderless)", SC.get_pie_settings()["mode"] == "borderless")
        SC.set_pie_settings(width=5, height=99999)
        s3 = SC.get_pie_settings()
        check("尺寸 clamp 320..7680", s3["width"] == 320 and s3["height"] == 7680, str(s3))

        # ── 4. 损坏 JSON → 不抛, 保持现值 ──
        with open(SC._PIE_SETTINGS_PATH, "w", encoding="utf-8") as fh:
            fh.write("{ this is not json")
        SC._pie_settings_loaded = False
        s4 = SC.get_pie_settings()
        check("损坏 JSON → 不抛异常, 保持现值",
              s4["mode"] == "borderless" and s4["width"] == 320, str(s4))

        # ── 5. RuntimeWindow.apply_start_preferences 映射 ──
        RuntimeWindow.apply_start_preferences("windowed", 900, 600)
        check("windowed → WINDOWED + override (900,600)",
              RuntimeWindow._window_mode == WindowMode.WINDOWED
              and RuntimeWindow._default_size_override == (900, 600),
              f"mode={RuntimeWindow._window_mode} ov={RuntimeWindow._default_size_override}")

        RuntimeWindow.apply_start_preferences("borderless", 900, 600)
        check("borderless → BORDERLESS + override None",
              RuntimeWindow._window_mode == WindowMode.BORDERLESS
              and RuntimeWindow._default_size_override is None,
              f"mode={RuntimeWindow._window_mode} ov={RuntimeWindow._default_size_override}")

        RuntimeWindow.apply_start_preferences("fullscreen", 900, 600)
        check("fullscreen → FULLSCREEN + override None",
              RuntimeWindow._window_mode == WindowMode.FULLSCREEN
              and RuntimeWindow._default_size_override is None)

        RuntimeWindow.apply_start_preferences("bogus", 640, 480)
        check("非法 mode → 回退 WINDOWED (override 仍生效)",
              RuntimeWindow._window_mode == WindowMode.WINDOWED
              and RuntimeWindow._default_size_override == (640, 480))

        # ── 6. _apply_pie_window_prefs 与 GameType 交互 ──
        from Application.Core.Scene.Scene import GameType
        SC.set_pie_settings(mode="fullscreen", width=1280, height=720)
        SC._apply_pie_window_prefs(GameType.OVERLAY)
        check("Overlay + fullscreen → borderless 回退",
              RuntimeWindow._window_mode == WindowMode.BORDERLESS)
        SC._apply_pie_window_prefs(GameType.GAME_3D)
        check("3D + fullscreen → FULLSCREEN",
              RuntimeWindow._window_mode == WindowMode.FULLSCREEN)
        SC.set_pie_settings(mode="windowed", width=900, height=600)
        SC._apply_pie_window_prefs(GameType.GAME_3D)
        check("3D + windowed → override (900,600)",
              RuntimeWindow._default_size_override == (900, 600))

    finally:
        SC._PIE_SETTINGS_PATH = orig_path
        SC._pie_mode, SC._pie_width, SC._pie_height = orig_vals
        SC._pie_settings_loaded = False
        RuntimeWindow._default_size_override = orig_override
        RuntimeWindow._window_mode = orig_mode
        shutil.rmtree(tmpdir, ignore_errors=True)

    total = _RESULTS["pass"] + _RESULTS["fail"]
    status = "OK" if _RESULTS["fail"] == 0 else "FAIL"
    print()
    print(f"RESULT: {status} ({_RESULTS['pass']}/{total})")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
