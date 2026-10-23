"""UI 场景回放 — 秒级 UI 迭代（真实面板 + 输入注入 + PNG 快照）。

用法:
    python Test/Application/Editor/ui_scenario.py --preview                  # 交互预览（ESC 退出）
    python Test/Application/Editor/ui_scenario.py scenarios/panels_smoke.py  # 回放场景
    python Test/Application/Editor/ui_scenario.py scenarios/xx.py --show --out DIR

场景文件协议（普通 .py）:
    NAME = "panels_smoke"          # 可选（默认文件名）
    def run(ctx):                  # 必需
        ctx.frames(3)
        s = ctx.snapshot("boot")   # → {path, width, height, bytes, std}
        ctx.expect(s["bytes"] > 20000, "snapshot non-trivial")

ctx API:
    frames(n) / snapshot(name) / expect(cond, msg)
    key(imgui_key, down=True) / mouse_move(x, y) / click(x, y)   — imgui io 注入
    ctrl("SceneBrowser") / panel("Node Editor")                  — 查控制器/面板实例

输出: 过程行 + 末行 `RESULT: OK (n)  snapshots: <dir>`; 退出码 0/1。
约定见 Doc/Dev/test_protocol.md（TIER: gui）。
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import time
import traceback

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "_path_setup.py")):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)
    import _path_setup  # noqa: F401

from imgui_bundle import imgui  # noqa: E402

from _ui_boot import UiBoot  # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class ScenarioContext:
    def __init__(self, boot: UiBoot, out_dir: str) -> None:
        self.boot = boot
        self.out_dir = out_dir
        self.checks: list[tuple[bool, str]] = []
        self.snapshots: list[dict] = []

    # ── 断言 / 帧 ──

    def expect(self, cond: bool, msg: str) -> bool:
        ok = bool(cond)
        self.checks.append((ok, msg))
        print(f"  [{'OK' if ok else 'FAIL'}] {msg}")
        return ok

    def frames(self, n: int) -> None:
        self.boot.frames(n)

    def snapshot(self, name: str) -> dict:
        snap = self.boot.frame(snapshot=name, out_dir=self.out_dir)
        assert snap is not None
        self.snapshots.append(snap)
        print(f"  [snap] {snap['path']} ({snap['bytes']} bytes, std={snap['std']})")
        return snap

    # ── 输入注入（imgui io — 与真实事件同管线）──

    def key(self, key, down: bool = True) -> None:
        imgui.get_io().add_key_event(key, down)

    def mouse_move(self, x: float, y: float) -> None:
        imgui.get_io().add_mouse_pos_event(float(x), float(y))

    def click(self, x: float, y: float) -> None:
        io = imgui.get_io()
        io.add_mouse_pos_event(float(x), float(y))
        io.add_mouse_button_event(0, True)
        io.add_mouse_button_event(0, False)

    # ── 查实例 ──

    def ctrl(self, name: str):
        from Application.Editor.Services.ControllerRegistry import get_ctrl

        return get_ctrl(name)

    def panel(self, name: str):
        from Application.Editor.UI.UIManager import UIManager

        return UIManager.find(name)


# ── 运行器 ──


def _load_scenario(path: str):
    spec = importlib.util.spec_from_file_location("ui_scenario_mod", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load scenario: {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _preview_loop() -> int:
    import glfw

    boot = UiBoot(hidden=False, title="UI Scenario — preview (ESC to exit)").create()
    print("[preview] Ready — ESC to exit")
    while not glfw.window_should_close(boot.window):
        boot.frame()
        if imgui.is_key_pressed(imgui.Key.escape, False):
            glfw.set_window_should_close(boot.window, True)
    boot.close()
    print("[preview] Done")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ui_scenario", description="UI 场景回放 / 交互预览")
    parser.add_argument("scenario", nargs="?", help="场景脚本路径（省略或 --preview 进入交互预览）")
    parser.add_argument("--preview", action="store_true", help="交互预览模式（ESC 退出）")
    parser.add_argument("--show", action="store_true", help="回放时显示窗口（默认隐藏窗口离屏跑）")
    parser.add_argument("--out", default="", help="快照目录（默认 Test/_runs/ui_<时间戳>/<场景名>）")
    ns = parser.parse_args(argv)

    try:  # GBK 控制台安全
        sys.stdout.reconfigure(errors="replace")
        sys.stderr.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

    if ns.preview or not ns.scenario:
        return _preview_loop()

    if not os.path.isabs(ns.scenario):
        ns.scenario = os.path.join(_ROOT, ns.scenario)
    if not os.path.isfile(ns.scenario):
        print(f"scenario not found: {ns.scenario}", file=sys.stderr)
        return 2

    mod = _load_scenario(ns.scenario)
    name = getattr(mod, "NAME", os.path.splitext(os.path.basename(ns.scenario))[0])
    out_dir = ns.out or os.path.join(
        _ROOT, "Test", "_runs", f"ui_{time.strftime('%Y%m%d_%H%M%S')}", name)

    print(f"== UI scenario: {name} ==")
    # 场景脚本默认把工作区当作一整块画布；真实编辑器启动布局由
    # test_editor_settings + 实机截图覆盖（默认右侧面板列）。
    from Application.Editor.UI.UIManager import UIManager
    UIManager.DEFAULT_PANEL_DOCK_FRACTION = 1.0
    UIManager._dock_layout_done = False
    boot = UiBoot(hidden=not ns.show, title=f"UI Scenario — {name}").create()
    ctx = ScenarioContext(boot, out_dir)

    t0 = time.time()
    error: Exception | None = None
    try:
        mod.run(ctx)
    except Exception as e:  # noqa: BLE001
        error = e
        traceback.print_exc()
    finally:
        boot.close()
    elapsed = time.time() - t0

    failed = [msg for ok, msg in ctx.checks if not ok]
    ok = error is None and not failed
    print()
    if ok:
        print(f"RESULT: OK ({len(ctx.checks)})  snapshots: {out_dir}  ({elapsed:.1f}s)")
        return 0
    detail = f"error={error!r}; " if error else ""
    print(f"RESULT: FAIL ({len(failed)} checks){' -- ' + detail if detail else ''}"
          f"failed: {'; '.join(failed) or '-'}  snapshots: {out_dir}  ({elapsed:.1f}s)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
