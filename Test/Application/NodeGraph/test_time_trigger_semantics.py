"""TimeTrigger 触发语义（core，无头）— 上升沿 = 每个阈值只触发一次。

背景（2026-11-01，用户实测反馈）:
  旧实现是「电平 + 阈值比上次触发时大」：`mode=pin` 且阈值随帧增长时**每帧都触发**，
  下游带副作用的节点（HTTP / 写文件 / 训练）会被连续调用（实测 4.7 次/秒）。
  新实现记录上一帧 `current >= threshold` 的结果，只在 False → True 的那一帧触发。

本测试锁定:
  1. manual + 固定阈值：每个 timer 周期只触发一次（24 s / 11 s 周期 = 2 次）
  2. manual + timer 不重置：总共只触发一次
  3. pin + 增长阈值：只触发一次（不是每帧）
  4. timer 重置后重新武装：下一周期再次触发
  5. manual 修改阈值：当前已越过时立即触发一次
"""

# TIER: core

from __future__ import annotations

import os
import sys

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "_path_setup.py")):
    _parent = os.path.dirname(_d)
    if _parent == _d:
        _d = ""
        break
    _d = _parent
if _d:
    sys.path.insert(0, _d)
import _path_setup  # noqa: E402,F401

from Application.Core.NodeGraph import _TYPES  # noqa: E402
from Application.Core.NodeGraph.evaluator_engine import ExecutionContext  # noqa: E402
from Application.Core.NodeGraph.evaluators.time import _eval_time_trigger  # noqa: E402

_RESULTS = {"pass": 0, "fail": 0}
_ND = _TYPES["TimeTrigger"]
_IDS = {p.name: 300 + i for i, p in enumerate(_ND.pins)}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


class _Inst:
    node_type = "TimeTrigger"

    def __init__(self, props: dict) -> None:
        self.props = dict(props)
        self.pin_ids = dict(_IDS)
        self.alias = ""
        self.description = ""


class _Canvas:
    def __init__(self, inst: _Inst) -> None:
        self.nodes = {1: inst}
        self.links: dict = {}


class _G:
    def __init__(self, inst: _Inst) -> None:
        self._canvas = _Canvas(inst)
        self._types = {"TimeTrigger": _ND}
        self.state: dict = {}

    def get_state(self, nid, key, default=None):
        return self.state.get(key, default)

    def set_state(self, nid, key, value):
        self.state[key] = value

    @staticmethod
    def _read_input(pid, ctx):
        return ctx.get_pin(pid)


def run_ticks(props: dict, ticks, *, reset_every=None, pin_time=None):
    """按 ticks 逐帧求值，返回触发时刻列表。"""
    inst = _Inst(props)
    g = _G(inst)
    ctx = ExecutionContext()
    ctx.create_timer("t")
    fires: list[float] = []
    for t in ticks:
        ctx.elapsed_time = t
        # timer 值 = 周期内相位（周期边界自动回 0，模拟 NewTimer reset）
        ctx.set_timer("t", (t % reset_every) if reset_every else t)
        if pin_time is not None:
            ctx.set_pin(_IDS["Time"], pin_time(t))
        _eval_time_trigger(1, ctx, g)
        if g.get_state(1, "_blocked", True) is False:
            fires.append(round(t, 3))
    return fires


def ticks(seconds: float, step: float = 0.1):
    n = int(round(seconds / step))
    return [round(i * step, 6) for i in range(n + 1)]


def main() -> int:
    print("== TimeTrigger semantics ==")

    fires = run_ticks({"mode": "manual", "time": 6.0, "timer": "t"},
                      ticks(24), reset_every=11)
    check("manual 6s on 11s cycle fires twice in 24s",
          len(fires) == 2, str(fires))
    check("manual fires at 6s and 17s",
          all(abs(f - want) < 0.15 for f, want in zip(fires, (6.0, 17.0))), str(fires))

    fires = run_ticks({"mode": "manual", "time": 6.0, "timer": "t"}, ticks(24))
    check("manual without timer reset fires once", len(fires) == 1, str(fires))

    fires = run_ticks({"mode": "pin", "timer": "t"}, ticks(20),
                      pin_time=lambda t: t / 10.0)
    check("pin + growing threshold does not refire every frame",
          len(fires) == 1, f"{len(fires)} fires, first {fires[:5]}")

    fires = run_ticks({"mode": "manual", "time": 6.0, "timer": "t"},
                      ticks(24), reset_every=11)
    check("timer reset re-arms the next cycle", len(fires) == 2, str(fires))

    # 5) manual 改阈值: 当前 elapsed=8 > 新阈值 3 → 立即触发一次
    inst = _Inst({"mode": "manual", "time": 6.0, "timer": "t"})
    g = _G(inst)
    ctx = ExecutionContext()
    ctx.create_timer("t")
    ctx.elapsed_time = 1.0
    ctx.set_timer("t", 1.0)
    _eval_time_trigger(1, ctx, g)
    check("before retarget: blocked", g.get_state(1, "_blocked") is True)
    ctx.elapsed_time = 2.0
    ctx.set_timer("t", 2.0)
    inst.props["time"] = 1.5
    _eval_time_trigger(1, ctx, g)
    check("manual retarget fires once", g.get_state(1, "_blocked") is False)
    ctx.elapsed_time = 2.1
    ctx.set_timer("t", 2.1)
    _eval_time_trigger(1, ctx, g)
    check("manual retarget does not repeat", g.get_state(1, "_blocked") is True)

    total = _RESULTS["pass"] + _RESULTS["fail"]
    ok = _RESULTS["fail"] == 0
    print()
    print(f"RESULT: {'OK' if ok else 'FAIL'} ({_RESULTS['pass']}/{total})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
