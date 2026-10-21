"""
RuntimeNodeLayer — OnAttach/OnUpdate 并发初始化竞态（回归测试，无头）。

背景 (2026-09-28, free-threading 实测):
    OnAttach 在渲染线程执行 (Engine._render_loop: run_ready 放行后逐个 layer.OnAttach)，
    逻辑线程的 OnUpdate 循环 (Engine._logic_loop) 同时起步。
    旧实现先赋值 _evaluator 再赋值 _frame/_pending_start — 逻辑线程可在
    "半初始化窗口"越过 OnUpdate 守卫 → cls._frame += 1
    → AttributeError: type object 'RuntimeNodeLayer' has no attribute '_frame'
    (PIE 启动瞬间逻辑线程崩溃；实测于 editor_run_pie → GameRuntime 启动)。

    修复: _evaluator 作为最后赋值的"可见性开关" (+ _frame 类级默认值)。

本测试用"可控阻塞点"确定性地把 OnAttach 停在半初始化窗口，断言:
    A. 窗口期内 OnUpdate — 不抛异常、不触发任何图逻辑；
    B. OnAttach 完成后 — 首个有效帧触发 OnGameStart，之后才逐帧 OnFrameUpdate。

用法:
    .venv-py314t\\Scripts\\python.exe Test/Application/Runtime/test_runtime_node_layer_race.py
"""

from __future__ import annotations

import os
import sys
import threading
import time

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "_path_setup.py")):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)
    import _path_setup  # noqa: F401

from Application.Core.Events.Event import BindPackCallback  # noqa: E402
from Application.Core.NodeGraph import NodeCanvas  # noqa: E402
import Application.Runtime.RuntimeNodeLayer as _rnl_mod  # noqa: E402
from Application.Runtime.RuntimeNodeLayer import RuntimeNodeLayer  # noqa: E402

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


def _wait_until(pred, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.005)
    return False


# ═══════════════════════════════════════════════════════════════
# 测试替身
# ═══════════════════════════════════════════════════════════════


class _SpyEvaluator:
    """GraphEvaluator 替身 — 只记录 trigger 调用。"""

    instances: list["_SpyEvaluator"] = []

    def __init__(self, canvas, types):
        self.canvas = canvas
        self.triggers: list[str] = []
        _SpyEvaluator.instances.append(self)

    def trigger(self, event_type, ctx) -> None:
        self.triggers.append(event_type)


class _FakeEngine:
    """最小假引擎 — scene 首次读取时可控阻塞；提供时间接口。"""

    def __init__(self) -> None:
        self.renderer = None            # _sync_camera_to_renderer 首次检查即早退
        self.scene_gate = threading.Event()
        self._scene_hits = 0
        self._scene_standin = object()

    @property
    def scene(self):
        self._scene_hits += 1
        if self._scene_hits == 1:
            # 卡住 OnAttach — 模拟渲染线程在"半初始化窗口"被抢占
            self.scene_gate.wait(timeout=10.0)
        return self._scene_standin

    def get_delta_time(self) -> float:
        return 0.016

    def get_elapsed_time(self) -> float:
        return 0.016


# ═══════════════════════════════════════════════════════════════
# main
# ═══════════════════════════════════════════════════════════════


def main() -> int:
    print("=" * 60)
    print("RuntimeNodeLayer — OnAttach/OnUpdate Race (headless)")
    print("=" * 60)

    BindPackCallback(lambda e: None)            # 事件系统最小引导
    _rnl_mod.GraphEvaluator = _SpyEvaluator     # 求值器替换为间谍

    engine = _FakeEngine()

    class Layer(RuntimeNodeLayer):              # 独立子类 = 类状态隔离
        pass

    Layer._engine = engine
    Layer._canvas = NodeCanvas()
    Layer._scene = object()

    # ── A. 启动 OnAttach（会停在 scene 第一次读取处）──
    attach_thread = threading.Thread(target=Layer.OnAttach, name="attach", daemon=True)
    attach_thread.start()
    check("OnAttach 到达阻塞点", _wait_until(lambda: engine._scene_hits >= 1))
    check("阻塞点处 _evaluator 尚不可见（可见性开关语义）", Layer._evaluator is None)

    # 半初始化窗口 — 逻辑线程视角连续调用 OnUpdate（旧实现此处崩溃/提前执行）
    errors: list[BaseException] = []

    def _hammer_on_update(n: int = 64) -> None:
        try:
            for _ in range(n):
                Layer.OnUpdate()
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    _hammer_on_update()
    check("窗口期 OnUpdate 不抛异常", not errors, detail=repr(errors))
    check(
        "窗口期未触发任何图逻辑",
        all(not ev.triggers for ev in _SpyEvaluator.instances),
    )

    # ── 释放阻塞，等待 OnAttach 完成 ──
    engine.scene_gate.set()
    attach_thread.join(timeout=5.0)
    check("OnAttach 正常完成", not attach_thread.is_alive())

    evaluator = Layer._evaluator
    check("_evaluator 已就绪（间谍替身）", isinstance(evaluator, _SpyEvaluator))
    check(
        "就绪后尚无任何 trigger",
        isinstance(evaluator, _SpyEvaluator) and not evaluator.triggers,
    )
    if not isinstance(evaluator, _SpyEvaluator):
        _print_results()
        return 1

    # ── B. 首帧 = OnGameStart（延迟启动路径）──
    Layer.OnUpdate()
    check(
        "首帧触发 OnGameStart",
        evaluator.triggers == ["OnGameStart"],
        detail=repr(evaluator.triggers),
    )
    check("pending 已消费", Layer._pending_start is False)

    # ── C. 次帧 = OnFrameUpdate，帧计数推进 ──
    Layer.OnUpdate()
    check(
        "次帧触发 OnFrameUpdate",
        evaluator.triggers == ["OnGameStart", "OnFrameUpdate"],
        detail=repr(evaluator.triggers),
    )
    check("帧计数推进 (_frame == 1)", Layer._frame == 1, detail=repr(Layer._frame))

    return _print_results()


def _print_results() -> int:
    print()
    print("=" * 60)
    total = _RESULTS["pass"] + _RESULTS["fail"]
    print(f"Results: {_RESULTS['pass']}/{total} passed, {_RESULTS['fail']} failed")
    if _RESULTS["fail"] == 0:
        print("ALL TESTS PASSED")
    else:
        print("TESTS FAILED")
    print("=" * 60)
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
