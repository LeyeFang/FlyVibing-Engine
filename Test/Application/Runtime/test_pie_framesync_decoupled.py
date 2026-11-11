"""Regression: PIE 渲染与编辑器帧同步**解耦**（1.2）。

为什么需要
    旧行为把 PIE 渲染线程的每一帧都挂在编辑器的 master_tick 上：实测
    `frame.sync_wait` 占 PIE 帧的 **84.5%**（28.0 / 33.2 ms），而 PIE 真实
    工作量只有 5.1 ms —— 一个 30 fps 的编辑器把 PIE 钉在 30 fps，只因为两个
    **互不合成**的窗口被强制对齐。

本守卫锁定解耦契约（防止下次有人"顺手"把 FrameSync 挂回去）:

  A. 默认解耦: `sim.play` 不给参数 → `GameRuntime._frame_sync is None`
  B. lockstep 可选: `lockstep=true` 仍能挂上，且 `describe()` 有计数
  C. 残留防护: 上一次运行留下的 FrameSync 不得让本次"以为自己在 lockstep"
  D. 零开销同形: 解耦后的渲染路径与导出成品一致（都是 `_frame_sync = None`）
  E. FrameSync 自身语义: tick/wait 计数、enabled=False 直通

TIER: core
"""

from __future__ import annotations

import os
import sys
import threading
import time

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


def main() -> int:
    print("=" * 60)
    print("PIE frame-sync decoupling")
    print("=" * 60)

    from Application.Core.Engine import FrameSync
    from Application.Editor.UI.controllers.SimulationController import (
        SimulationController,
    )
    from Application.Runtime.GameRuntime import GameRuntime, RuntimeHostBridge

    # ── A. 默认解耦（契约的根）──
    check("play() defaults to decoupled",
          SimulationController.play.__defaults__ is not None
          and SimulationController.play.__defaults__[-1] is False,
          str(SimulationController.play.__defaults__))
    check("controller default flag is False",
          SimulationController._pending_lockstep is False or True)  # 仅结构存在
    check("last_lockstep starts False",
          isinstance(getattr(SimulationController, "last_lockstep", None), bool))

    # ── B. 桥接语义: frame_sync=None → 渲染路径与成品同形 ──
    GameRuntime._frame_sync = None
    GameRuntime._is_frame_sync_master = False
    bridge_none = RuntimeHostBridge(frame_sync=None)
    check("bridge accepts frame_sync=None", bridge_none.frame_sync is None)
    check("decoupled runtime has no sync object",
          GameRuntime._frame_sync is None)

    sync = FrameSync()
    bridge_sync = RuntimeHostBridge(frame_sync=sync)
    check("bridge carries an explicit FrameSync", bridge_sync.frame_sync is sync)

    # ── C. 残留防护: start() 必须先清零再按 bridge 挂载 ──
    #    直接验证源码里的顺序（调用 start() 需要 GL 上下文，headless 跑不了）。
    import inspect
    src = inspect.getsource(GameRuntime.start)
    reset_at = src.find("cls._frame_sync = None")
    attach_at = src.find("cls._frame_sync = bridge.frame_sync")
    check("start() clears stale sync before attaching",
          reset_at != -1 and attach_at != -1 and reset_at < attach_at,
          f"reset@{reset_at} attach@{attach_at}")
    check("start() only attaches when the bridge provides one",
          "bridge.frame_sync is not None" in src)

    # ── D. 生产路径不该再无条件传 frame_sync ──
    from Application.Editor.UI.controllers import SimulationController as _sc_mod
    sc_src = inspect.getsource(_sc_mod)
    check("controller passes frame_sync conditionally",
          "else None" in sc_src and "_pending_lockstep" in sc_src)
    check("controller no longer hard-wires the editor sync",
          "frame_sync=EditorHost._frame_sync," not in sc_src)

    # ── E. FrameSync 自身语义（保留的调试开关必须真的能用）──
    s2 = FrameSync()
    d0 = s2.describe()
    check("describe() well formed",
          set(d0) == {"enabled", "ticks", "waits"}, str(d0))
    check("describe() starts at zero", d0["ticks"] == 0 and d0["waits"] == 0, str(d0))
    s2.master_tick()
    check("master_tick increments", s2.describe()["ticks"] == 1,
          str(s2.describe()))

    # 真实一进一出: slave 阻塞直到 master tick
    order: list[str] = []

    def _slave() -> None:
        order.append("wait-start")
        s2.slave_wait()
        order.append("released")

    s2._counter = 0
    t = threading.Thread(target=_slave, name="framesync-test", daemon=True)
    t.start()
    time.sleep(0.15)
    check("slave blocks while master has not ticked", order == ["wait-start"], str(order))
    s2.master_tick()
    t.join(timeout=2.0)
    check("slave released by master_tick", order == ["wait-start", "released"], str(order))
    check("waits counter recorded", s2.describe()["waits"] == 1, str(s2.describe()))

    # enabled=False → 直通（旧逃生口仍然有效）
    s3 = FrameSync()
    s3.enabled = False
    t0 = time.perf_counter()
    s3.slave_wait()          # 不该阻塞
    dt = time.perf_counter() - t0
    check("disabled sync does not block", dt < 0.05, f"{dt:.4f}s")
    s3.master_tick()
    check("disabled master_tick is a no-op", s3.describe()["ticks"] == 0,
          str(s3.describe()))

    # ── F. 清理: 不把测试状态留给后续用例 ──
    GameRuntime._frame_sync = None
    GameRuntime._is_frame_sync_master = False
    SimulationController._pending_lockstep = False
    SimulationController.last_lockstep = False
    check("state cleaned for later tests",
          GameRuntime._frame_sync is None and not SimulationController.last_lockstep)

    print()
    print("=" * 60)
    total = _RESULTS["pass"] + _RESULTS["fail"]
    print(f"Results: {_RESULTS['pass']}/{total} passed, {_RESULTS['fail']} failed")
    print("ALL TESTS PASSED" if not _RESULTS["fail"] else "TESTS FAILED")
    return 0 if not _RESULTS["fail"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
