"""VirtualDevice 面板扩展测试（无头 — 沙箱 ExtensionManager + ops + DSP + 绘制烟测）。

锁定:
  1. 静态: reviewer 对 Application/Functions/VirtualDevice 零 FAIL（manifest M1-M6 + 代码 C1-C11 + F2）
  2. 发现/启停: enable → ext.virtual.* 九件套注册 + 窗口注册; disable → 双清理
  3. 会话流: open(sim) → watch（监视不累积）→ 升级 record → stop(save) 干跑不落盘 →
     watch-only stop 无落盘 → close
  4. 显示滤波 DSP: highpass 30Hz 压制 10Hz 正弦 / lowpass 15Hz 保留（确定性）
  5. 设置持久化: filters 变更 → settings.json 落盘（沙箱 data_dir）
  6. 窗口关闭事件停流; 无头绘制帧（含全裁剪）不抛异常

运行: python Utils/Dev/test_runner.py --only virtual_panel
"""
# TIER: core

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import time

import numpy as np

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "_path_setup.py")):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)
    import _path_setup  # noqa: E402
_REPO = os.path.dirname(_d) if _d else ""
_EXT_DIR = os.path.join(_REPO, "Application", "Functions", "VirtualDevice")

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


def _load_reviewer():
    path = os.path.join(_REPO, "Utils", "ExtDev", "ExtensionKit", "review_extension.py")
    spec = importlib.util.spec_from_file_location("ext_review_vd", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_display_module():
    path = os.path.join(_EXT_DIR, "virtual_display.py")
    spec = importlib.util.spec_from_file_location("vd_display_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    print("=" * 60)
    print("VirtualDevice panel extension — sandbox + ops + DSP (headless)")
    print("=" * 60)

    # ── 1. 静态审查（manifest + C1-C11 + F2） ────────────────────
    print("── static review ──")
    tool = _load_reviewer()
    rep = tool.review_extension(_EXT_DIR)
    check("reviewer: 零 FAIL", rep.fails == 0, "\n".join(rep.lines))
    with open(os.path.join(_EXT_DIR, "extension.json"), encoding="utf-8") as fh:
        manifest = json.load(fh)
    check("manifest: id=virtual / ui+ops+device",
          manifest.get("id") == "virtual"
          and {"ops", "ui", "device"} <= set(manifest.get("capabilities", [])),
          str(manifest))

    # ── 2. 沙箱 + 启停 ──────────────────────────────────────────
    from Application.Editor.Extensions.ExtensionManager import ExtensionManager
    from Application.Editor.Services.LiveCommandServer import LiveCommandServer
    from Application.Editor.UI.UIManager import UIManager
    from Application.Functions.VirtualDevice import get_session

    tmp = tempfile.mkdtemp(prefix="mge_vd_test_")
    saved_env = {k: os.environ.get(k) for k in
                 ("MGE_EXTENSIONS_DIR", "MGE_EXTENSIONS_STATE", "MGE_EXTENSIONS_DATA")}
    os.environ["MGE_EXTENSIONS_DIR"] = os.path.join(tmp, "user_ext")
    os.environ["MGE_EXTENSIONS_STATE"] = os.path.join(tmp, "state.json")
    os.environ["MGE_EXTENSIONS_DATA"] = os.path.join(tmp, "data")

    inst = None
    try:
        ExtensionManager.ensure_init(force=True)
        infos = {i["id"]: i for i in ExtensionManager.list_infos()}
        check("discovered: virtual", "virtual" in infos)
        check("virtual loadable", infos["virtual"]["loadable"] is True)

        r = ExtensionManager.enable("virtual")
        check("enable virtual", r["loaded"] is True, str(r))
        ops = set(LiveCommandServer.extension_ops_snapshot())
        expected = {f"ext.virtual.{n}" for n in
                    ("status", "open", "close", "watch", "record", "stop",
                     "filters", "display", "snapshot")}
        check("ext.virtual.* 九件套", expected <= ops, str(sorted(ops)))
        check("窗口已注册 (ctx.ui.register_window)",
              UIManager.find("Virtual Device Monitor") is not None)
        inst = ExtensionManager._instances.get("virtual")
        check("instance 存在", inst is not None)
        call = LiveCommandServer._ext_ops

        st = call["ext.virtual.status"]({})
        check("status: 初始无会话", st["state"] is None and st["streaming"] is False)
        check("默认 mode=sim", st["mode"] == "sim")

        # ── 3. 会话流 ───────────────────────────────────────────
        print("── session flow ──")
        o = call["ext.virtual.open"]({
            "mode": "sim", "channels": 8, "sampling_rate": 512, "frequency": 10.0,
            "freq_step": 2.0, "amplitude_uv": 50.0, "noise_uv": 0.0, "seed": 0,
            "buffer_seconds": 1.0, "save_dir": os.path.join(tmp, "out")})
        check("open(sim) → dry_run", o["opened"] and o["dry_run"] and o["fs"] == 512, str(o))

        w = call["ext.virtual.watch"]({})
        check("watch → monitoring", w["streaming"] and not w["recording"])
        time.sleep(0.15)
        snap = call["ext.virtual.snapshot"]({"points": 64, "preview_channels": 2})
        check("snapshot: monitoring / 8ch",
              snap["state"] == "monitoring" and len(snap["stats"]) == 8, str(snap)[:160])
        rms = float(snap["stats"][0]["rms"])
        check("snapshot rms 合理（50uV 合成正弦）", 15.0 < rms < 60.0, f"rms={rms}")
        check("preview 键 ch1/ch2 非空",
              set(snap["preview"]) == {"ch1", "ch2"} and len(snap["preview"]["ch1"]) > 0)

        rec = call["ext.virtual.record"]({})
        check("record 升级（监视中）", rec["recording"])
        time.sleep(0.12)
        stp = call["ext.virtual.stop"]({})
        check("stop(save): 干跑不落盘", "would save" in stp["detail"], stp["detail"])

        call["ext.virtual.watch"]({})
        time.sleep(0.08)
        stp2 = call["ext.virtual.stop"]({})
        check("watch-only stop: 无落盘", "nothing recorded" in stp2["detail"], stp2["detail"])

        c = call["ext.virtual.close"]({})
        check("close → 会话释放", c["closed"] is True and get_session("panel") is None)

        # ── 4. 设置持久化 ───────────────────────────────────────
        print("── settings / filters ──")
        f = call["ext.virtual.filters"]({"enabled": True, "filter_type": "highpass",
                                         "low": 30.0, "order": 4, "notch": "off"})
        check("filters op 回显", f["filters"]["enabled"] and f["filters"]["filter_type"] == "highpass")
        found = None
        for cur, _dirs, files in os.walk(os.environ["MGE_EXTENSIONS_DATA"]):
            if "settings.json" in files:
                found = os.path.join(cur, "settings.json")
                break
        persisted = False
        if found:
            with open(found, encoding="utf-8") as fh:
                data = json.load(fh)
            persisted = data.get("filt_type") == "highpass" and data.get("filt_enabled") is True
        check("设置持久化 (sandbox data_dir)", bool(found) and persisted, str(found))

        # ── 5. 显示滤波 DSP 数值 ────────────────────────────────
        print("── dsp ──")
        disp = _load_display_module()
        fs = 512
        t = np.arange(0, 2.0, 1.0 / fs)
        sig = (np.sin(2.0 * np.pi * 10.0 * t) * 50.0).astype(np.float32).reshape(1, -1)
        mid = slice(fs // 2, -fs // 2)
        r_in = float(np.sqrt(np.mean(sig[0, mid] ** 2)))
        stages, _ = disp.build_filter_chain(
            {"enabled": True, "filter_type": "highpass", "low": 30.0, "order": 4,
             "notch": "off"}, fs)
        out = disp.apply_chain(sig, stages)
        r_hp = float(np.sqrt(np.mean(out[0, mid] ** 2)))
        check("DSP highpass 30: 10Hz 被压制", r_hp < r_in * 0.1, f"{r_in:.1f} -> {r_hp:.2f}")
        stages2, _ = disp.build_filter_chain(
            {"enabled": True, "filter_type": "lowpass", "high": 15.0, "order": 4,
             "notch": "off"}, fs)
        out2 = disp.apply_chain(sig, stages2)
        r_lp = float(np.sqrt(np.mean(out2[0, mid] ** 2)))
        check("DSP lowpass 15: 10Hz 保留", r_lp > r_in * 0.8, f"{r_in:.1f} -> {r_lp:.2f}")
        spike = np.zeros((1, 1000), dtype=np.float32)
        spike[0, 500] = 999.0
        _mins, maxs, cols = disp.decimate_minmax(spike, 100)
        check("min/max 抽取保尖峰", float(maxs.max()) == 999.0 and cols == 100)

        # ── 6. 窗口关闭事件 + 绘制烟测 ──────────────────────────
        print("── window lifecycle / draw ──")
        call["ext.virtual.open"]({"mode": "sim", "buffer_seconds": 1.0})
        call["ext.virtual.watch"]({})
        inst.on_ui_event("closed", "Virtual Device Monitor")
        st2 = call["ext.virtual.status"]({})
        check("closed 事件 → 停流", st2["streaming"] is False
              and st2["state"] in ("stopped", "closed"), str(st2["state"]))

        from flyvibing_extension_kit.imgui_headless import headless_imgui
        from imgui_bundle import imgui

        def _draw():
            imgui.begin("vd_panel_test")
            inst._draw_monitor()
            imgui.end()

        try:
            with headless_imgui() as h:
                h.frames([(1200, 800), (0, 0), (1, 1), (1200, 800)], draw=_draw)
            draw_ok = True
            draw_err = ""
        except Exception as e:  # noqa: BLE001 — 测试断言用
            draw_ok = False
            draw_err = repr(e)
        check("无头绘制帧（含全裁剪）不抛异常", draw_ok, draw_err)

        ExtensionManager.disable("virtual")
        check("disable → ops 清理",
              "ext.virtual.status" not in LiveCommandServer.extension_ops_snapshot())
        check("disable → 窗口清理", UIManager.find("Virtual Device Monitor") is None)
        check("disable → 会话已关闭", get_session("panel") is None)
    finally:
        try:
            from Application.Functions.VirtualDevice import get_session as _gs, kill_device as _kd
            if _gs("panel") is not None:
                _kd("panel")
        except Exception:  # noqa: BLE001
            pass
        try:
            ExtensionManager.unload_all()
        except Exception:  # noqa: BLE001
            pass
        LiveCommandServer._ext_ops.clear()
        LiveCommandServer._ext_ops_owner.clear()
        LiveCommandServer._ext_ops_summary.clear()
        ExtensionManager._infos = {}
        ExtensionManager._instances = {}
        ExtensionManager._scanned = False
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    total = _RESULTS["pass"] + _RESULTS["fail"]
    status = "OK" if _RESULTS["fail"] == 0 else "FAIL"
    print()
    print(f"RESULT: {status} ({_RESULTS['pass']}/{total})")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
