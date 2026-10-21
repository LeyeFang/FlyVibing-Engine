"""Extension UI 桥测试 — ctx.ui.register_window 窗口注册/清理/异常遏制（无 GL）。

锁定内容（协议: Doc/ExtDev/extension_dev_protocol.md §7）:
  1. register_window → UIManager 命中 + owner 归属正确
  2. 重名注册 → ValueError（不静默改写）
  3. 扩展间隔离: B 无法注销 A 的窗口
  4. purge(ext_id) → 该扩展窗口全清, 他人保留
  5. draw_fn 异常遏制: 连续 _QUARANTINE_AFTER 帧 → quarantine (visible=False)
  6. 正常帧重置异常计数

注意: 全程不触碰真实 imgui 帧循环（draw_fn 由测试自有函数替代）, headless 安全。
运行: python Utils/Dev/test_runner.py --only extension_ui
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


def main() -> int:
    print("=" * 60)
    print("Extension UI bridge — register/purge/quarantine (headless)")
    print("=" * 60)

    from Application.Editor.Extensions.ExtensionUI import (
        ExtensionPanel, ExtensionUI, _QUARANTINE_AFTER)
    from Application.Editor.UI.UIManager import UIManager

    ui_a = ExtensionUI("extA")
    ui_b = ExtensionUI("extB")

    def draw_ok() -> None:
        pass

    def draw_boom() -> None:
        raise RuntimeError("boom")

    try:
        # ── 1. 注册 ──────────────────────────────────────────
        print("── register ──")
        ui_a.register_window("Test Mon A", draw_ok)
        p = UIManager.find("Test Mon A")
        check("register → UIManager 命中且归属 extA",
              isinstance(p, ExtensionPanel) and p.ext_id == "extA")

        # ── 2. 重名 ──────────────────────────────────────────
        try:
            ui_b.register_window("Test Mon A", draw_ok)
            check("重名注册 → ValueError", False, "no exception")
        except ValueError:
            check("重名注册 → ValueError", True)

        # ── 3. 隔离与注销 ────────────────────────────────────
        check("B 无法注销 A 的窗口", ui_b.unregister_window("Test Mon A") is False)
        check("A 注销自己的窗口",
              ui_a.unregister_window("Test Mon A") is True
              and UIManager.find("Test Mon A") is None)

        # ── 4. purge ────────────────────────────────────────
        print("── purge ──")
        ui_a.register_window("Test Mon A1", draw_ok)
        ui_a.register_window("Test Mon A2", draw_ok)
        ui_b.register_window("Test Mon B", draw_ok)
        ExtensionUI.purge("extA")
        check("purge(extA) → A 全清 / B 保留",
              UIManager.find("Test Mon A1") is None
              and UIManager.find("Test Mon A2") is None
              and UIManager.find("Test Mon B") is not None)

        # ── 5. 异常遏制 ──────────────────────────────────────
        print("── quarantine ──")
        # 扩展窗口默认隐藏；这里显式打开以验证绘制异常遏制路径
        ui_a.register_window("Test Boom", draw_boom, visible=True)
        boom = UIManager.find("Test Boom")
        for _ in range(_QUARANTINE_AFTER):
            boom.draw()
        check(f"连续 {_QUARANTINE_AFTER} 帧异常 → quarantine",
              boom.visible is False and boom._error_streak >= _QUARANTINE_AFTER)

        # ── 6. 正常帧重置 ────────────────────────────────────
        ui_b.register_window("Test Flip", draw_ok, visible=True)
        flip = UIManager.find("Test Flip")
        flip._draw_fn = draw_boom
        flip.draw()
        flip.draw()
        check("异常计数累计 (2)", flip._error_streak == 2 and flip.visible is True)
        flip._draw_fn = draw_ok
        flip.draw()
        check("正常帧重置计数", flip._error_streak == 0)

        # ── 7. close_policy / on_ui_event / 停用请求链 ────────
        print("── close policy / close event ──")
        from Application.Editor.Extensions.ExtensionManager import ExtensionManager

        events: list = []

        class FakeExt:
            def on_ui_event(self, event, name):
                events.append((event, name))

        ui_c = ExtensionUI("extC", FakeExt())
        ui_c.register_window("Test C", draw_ok, close_policy="disable")
        pc = UIManager.find("Test C")
        check("close_policy 已记录", getattr(pc, "close_policy", "") == "disable")
        pc._notify_closed()
        check("on_ui_event('closed', name) 已派发",
              events == [("closed", "Test C")], str(events))
        check("close_policy=disable → 停用请求入队",
              "extC" in ExtensionManager._pending_disable)
        ExtensionManager._pending_disable.discard("extC")
        try:
            ui_c.register_window("Test Bad", draw_ok, close_policy="nope")
            check("非法 close_policy → ValueError", False, "no exception")
        except ValueError:
            check("非法 close_policy → ValueError", True)

        # show_all — hide 策略的恢复路径（enable 时宿主重置可见）
        ui_a.register_window("Test ShowAll", draw_ok)
        ps = UIManager.find("Test ShowAll")
        ps.visible = False
        ExtensionUI.show_all("extA")
        check("show_all 重置可见 (enable 恢复路径)", ps.visible is True)

        # ── 8. 语言层强制（UIExtensionBase） ────────────────
        print("── language enforcement ──")
        from Application.Core.Extension.ExtensionBase import ExtensionBase, UIExtensionBase
        check("UIExtensionBase 是 ExtensionBase 子类", issubclass(UIExtensionBase, ExtensionBase))
        try:
            class Incomplete(UIExtensionBase):
                id = "incomplete"

            Incomplete()
            check("未实现 on_ui_event → 实例化 TypeError", False, "no exception")
        except TypeError:
            check("未实现 on_ui_event → 实例化 TypeError", True)

        class Complete(UIExtensionBase):
            def on_ui_event(self, event, name):
                pass

        Complete()
        check("实现后可实例化", True)
    finally:
        # 清理 — 不留残面板
        ExtensionUI.purge("extA")
        ExtensionUI.purge("extB")
        ExtensionUI.purge("extC")

    left = [p for p in UIManager._panels if isinstance(p, ExtensionPanel)]
    check("测试后无 ExtensionPanel 残留", not left, str([p.name for p in left]))

    total = _RESULTS["pass"] + _RESULTS["fail"]
    status = "OK" if _RESULTS["fail"] == 0 else "FAIL"
    print()
    print(f"RESULT: {status} ({_RESULTS['pass']}/{total})")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
