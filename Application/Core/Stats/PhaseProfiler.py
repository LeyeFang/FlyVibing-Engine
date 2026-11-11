"""PhaseProfiler — 帧内**分相**计时（1.2 性能分析的第一块地基）。

为什么需要它
    `FrameProfiler` 只回答"整帧多久"（mean / p50 / p99 + 卡顿桶）。实测
    成品 1.44–2.17 ms 里图求值只占 **0.20 ms（10%）** —— 剩下 1.76 ms
    去了哪里**没有任何出口**；编辑器 28 ms 里除 Node Editor 面板 21.5 ms
    之外的 6.5 ms 同样不可见。没有分相，任何"多线程 / 缓存 / 视口裁剪"
    方案都是押宝。

设计要点（每一条都是为"不骗自己"服务的）
  1. **嵌套**：`frame.layers` > `layer.NodeEditor` > `panel.draw`。父相包含子相，
     所以本模块统计**排他时间**（exclusive = 自身耗时 − 子相之和），
     避免"每个相都占满整帧"的假账。同时保留 inclusive 便于看子树总成本。
  2. **线程本地，热路径不加锁**：每个线程自己的栈与样本桶；`snapshot()`
     （1 Hz 量级）时才合并。加锁会让我们要测量的东西本身失真。
  3. **零成本关闭**：`enabled=False` 时 `phase()` 返回共享空对象，
     开销只有一次属性查找 + 一次函数调用。
  4. **诚实**：只有调用 `end_frame()` 的线程才计算"帧内占比 / 未归因"。
     其它线程的相只报自己的分布，不硬凑帧占比。

典型用法::

    with prof.phase("frame.layers"):
        for layer in stack:
            with prof.phase(f"layer.{type(layer).__name__}"):
                layer.OnRender()
    prof.counter("draw_calls", n)
    prof.end_frame(frame_ms)          # 渲染线程每帧一次

    prof.snapshot()                   # 结构化（JSON 友好）
    print(prof.report_text())         # 人读表格（按排他时间排序）

守卫: `Test/Application/Core/test_phase_profiler.py`。
"""

from __future__ import annotations

import threading
import time
from collections import deque

__all__ = ["PhaseProfiler", "NULL_SCOPE"]


# ════════════════════════════════════════════════════════════════
# 空对象 — 关闭时的零成本路径
# ════════════════════════════════════════════════════════════════

class _NullScope:
    """关闭状态下的占位作用域（不分配、不记录、不检查）。"""

    __slots__ = ()

    def __enter__(self):
        return None

    def __exit__(self, exc_type, exc, tb):
        return False


_NULL = _NullScope()

#: 给"可能根本没有 profiler"的调用方（如无 Engine 的渲染器单元测试）用。
NULL_SCOPE = _NULL


# ════════════════════════════════════════════════════════════════
# 线程本地状态
# ════════════════════════════════════════════════════════════════

class _ThreadState:
    """单个线程的采样状态（只有该线程写；snapshot 时被读，见 §线程安全）。"""

    __slots__ = ("name", "ident", "stack", "top", "excl", "incl", "counters",
                 "frame_ms", "unattributed", "worst", "flushes",
                 "_cur_excl", "_cur_incl", "_cur_counters",
                 "_window", "_worst_frames", "_depth_zero")

    def __init__(self, name: str, window: int, worst_frames: int,
                 ident: int = 0) -> None:
        self.name = name
        self.ident = ident
        self.stack: list[list] = []       # [name, t0, child_sum]
        self.top: set[str] = set()        # 本帧出现过的顶层相（用于未归因计算）
        self.excl: dict[str, deque] = {}
        self.incl: dict[str, deque] = {}
        # 计数器：name → deque（每帧一个值）
        self.counters: dict[str, deque] = {}
        self.frame_ms: deque = deque(maxlen=window)
        self.unattributed: deque = deque(maxlen=window)
        self.worst: list[tuple[float, dict]] = []   # 保留最慢的 N 帧
        self.flushes: int = 0
        # 本帧累积（end_frame 时落到上面）
        self._cur_excl: dict[str, float] = {}
        self._cur_incl: dict[str, float] = {}
        self._cur_counters: dict[str, float] = {}
        self._window = window
        self._worst_frames = worst_frames
        self._depth_zero: set[str] = set()

    # ── 内部：槽位（延迟创建 deque，避免为从未出现的相付内存）──
    def _slot(self, table: dict, name: str) -> deque:
        d = table.get(name)
        if d is None:
            d = deque(maxlen=self._window)
            table[name] = d
        return d

    # ── 记录 ────────────────────────────────────────────────
    def push(self, name: str) -> list:
        entry = [name, time.perf_counter(), 0.0]
        if not self.stack:
            self._depth_zero.add(name)
        self.stack.append(entry)
        return entry

    def pop(self, entry: list) -> None:
        # ★ perf_counter 是**秒**；全模块统一用毫秒（与 FrameProfiler / 报表同口径）。
        #   不转换会让所有数字小 1000 倍，而测试/人眼都很难发现 "0.006" 是 6 ms。
        dt = (time.perf_counter() - entry[1]) * 1000.0
        if self.stack and self.stack[-1] is entry:
            self.stack.pop()
            if self.stack:
                self.stack[-1][2] += dt
        else:
            # 栈失配（profiler 中途开关 / 异常路径栈未清）：尽力移除本条目，
            # 但**不**把耗时记到别人的 child_sum 上 —— 否则父相排他时间变负。
            try:
                self.stack.remove(entry)
            except ValueError:
                pass
        name = entry[0]
        exclusive = dt - entry[2]
        if exclusive < 0.0:
            # 只可能来自时钟不单调的极端情况；钳零而不是让负数污染百分位
            exclusive = 0.0
        self._cur_excl[name] = self._cur_excl.get(name, 0.0) + exclusive
        self._cur_incl[name] = self._cur_incl.get(name, 0.0) + dt
        if name in self._depth_zero:
            self.top.add(name)

    def add_counter(self, name: str, value: float) -> None:
        self._cur_counters[name] = self._cur_counters.get(name, 0.0) + value

    # ── 帧边界 ──────────────────────────────────────────────
    def flush(self, frame_ms: float | None) -> None:
        """把本帧累积落到样本桶。`frame_ms=None` = 只冲刷，不算帧账。"""
        for name, value in self._cur_excl.items():
            self._slot(self.excl, name).append(value)
        for name, value in self._cur_incl.items():
            self._slot(self.incl, name).append(value)
        for name, value in self._cur_counters.items():
            self._slot(self.counters, name).append(value)

        if frame_ms is not None and frame_ms > 0.0:
            self.frame_ms.append(frame_ms)
            top_sum = 0.0
            for name in self.top:
                top_sum += self._cur_incl.get(name, 0.0)
            unattributed = frame_ms - top_sum
            self.unattributed.append(unattributed if unattributed > 0.0 else 0.0)
            # 最慢的 N 帧带完整分解 —— "偶发卡顿"唯一有效的看法
            if self._worst_frames > 0:
                snapshot = {k: round(v, 3) for k, v in self._cur_excl.items()}
                snapshot["(unattributed)"] = round(
                    unattributed if unattributed > 0.0 else 0.0, 3)
                self.worst.append((frame_ms, snapshot))
                self.worst.sort(key=lambda item: item[0], reverse=True)
                del self.worst[self._worst_frames:]

        self._cur_excl.clear()
        self._cur_incl.clear()
        self._cur_counters.clear()
        self.top.clear()
        self._depth_zero.clear()
        self.flushes += 1


# ════════════════════════════════════════════════════════════════
# 作用域
# ════════════════════════════════════════════════════════════════

class _Scope:
    __slots__ = ("_prof", "_name", "_entry")

    def __init__(self, prof: "PhaseProfiler", name: str) -> None:
        self._prof = prof
        self._name = name
        self._entry: list | None = None

    def __enter__(self):
        self._entry = self._prof._push(self._name)
        return None

    def __exit__(self, exc_type, exc, tb):
        entry = self._entry
        self._entry = None
        # 无论 profiler 此刻是否仍开着都要出栈 —— 否则栈失配会让后续父相
        # 认错孩子（排他时间失真比少一条样本严重得多）。
        if entry is not None:
            try:
                self._prof._pop(entry)
            except Exception:      # noqa: BLE001 — 计时绝不能打断渲染
                pass
        return False


# ════════════════════════════════════════════════════════════════
# 百分位工具（与 FrameProfiler 同口径）
# ════════════════════════════════════════════════════════════════

def _percentiles(values: list[float]) -> dict:
    n = len(values)
    if n == 0:
        return {"n": 0, "mean": 0.0, "p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0}
    ordered = sorted(values)
    total = sum(ordered)
    mean = total / n

    def _at(q: float) -> float:
        return ordered[min(int(q * (n - 1)), n - 1)]

    return {
        "n": n,
        "mean": round(mean, 3),
        "p50": round(_at(0.50), 3),
        "p95": round(_at(0.95), 3),
        "p99": round(_at(0.99), 3),
        "max": round(ordered[-1], 3),
        "sum": round(total, 3),
    }


def _thread_snapshot(state: _ThreadState) -> dict:
    frames = list(state.frame_ms)
    frame_stats = _percentiles(frames)
    unattr_stats = _percentiles(list(state.unattributed))
    mean_frame = frame_stats["mean"]
    out = {
        "flushes": state.flushes,
        "frame": frame_stats,
        "unattributed": unattr_stats,
        "unattributed_share": (round(unattr_stats["mean"] / mean_frame, 4)
                               if mean_frame > 0 else 0.0),
        "phases": {},
        "counters": {},
        "worst_frames": [
            {"frame_ms": round(ms, 3), "phases": dict(parts)}
            for ms, parts in state.worst
        ],
    }
    for name, excl_deque in state.excl.items():
        excl = _percentiles(list(excl_deque))
        incl = _percentiles(list(state.incl.get(name) or ()))
        share = (round(excl["mean"] / mean_frame, 4) if mean_frame > 0 else 0.0)
        out["phases"][name] = {"excl": excl, "incl": incl, "share": share}
    for name, values in state.counters.items():
        vals = list(values)
        if not vals:
            continue
        out["counters"][name] = {
            "n": len(vals),
            "last": round(vals[-1], 3),
            "mean": round(sum(vals) / len(vals), 3),
            "max": round(max(vals), 3),
        }
    return out


class PhaseProfiler:
    """分相计时器（每 Engine 一个，由 `FrameProfiler` 持有）。

    Args:
        enabled:      初始状态。成品默认关（零开销），按需打开。
        window:       每个相的样本上限（帧数）。1000 ≈ 5 s @200 fps。
        worst_frames: 额外保留最慢 N 帧的完整分解（0 = 不保留）。
    """

    def __init__(self, enabled: bool = False, window: int = 1000,
                 worst_frames: int = 8) -> None:
        self.enabled = bool(enabled)
        self.window = int(window)
        self.worst_frames = int(worst_frames)
        self._local = threading.local()
        # 本 profiler 自己的线程状态（每个线程一个）。
        # ★ 不用模块级全局表: EditorHost 与 GameRuntime 各持一个 profiler，
        #   全局表会让 PIE 的相混进编辑器报表，且线程重启后越积越多。
        self._states: list[_ThreadState] = []
        self._states_lock = threading.Lock()

    # ── 线程状态 ────────────────────────────
    def _state(self) -> _ThreadState:
        st = getattr(self._local, "state", None)
        if st is None:
            thread = threading.current_thread()
            st = _ThreadState(thread.name, self.window, self.worst_frames,
                              getattr(thread, "ident", 0) or 0)
            self._local.state = st
            with self._states_lock:
                self._prune_locked()
                self._states.append(st)
        return st

    def _prune_locked(self, keep: int = 8) -> None:
        """线程状态上限（PIE 反复启停会不停造新线程）。

        ★ 只在**满了之后**才丢已结束线程的状态 —— 否则刚跑完的 worker
          的样本会被自己“清理”掉，报表里永远看不到短命线程的成本。
        """
        if len(self._states) < keep:
            return
        alive = {t.ident for t in threading.enumerate()}
        self._states = [s for s in self._states if s.ident in alive]
        if len(self._states) >= keep:
            del self._states[:len(self._states) - keep + 1]

    def _push(self, name: str) -> list:
        return self._state().push(name)

    def _pop(self, entry: list) -> None:
        self._state().pop(entry)

    # ── 公开 API ────────────────────────────────────────────
    def phase(self, name: str):
        """开始一个相（可嵌套）。关闭时返回零成本空对象。"""
        if not self.enabled:
            return _NULL
        return _Scope(self, name)

    def counter(self, name: str, value: float = 1.0) -> None:
        """记一个数值（draw call 数 / 实体数 / 节点数 / 解码帧数…）。

        语义是**每帧累加**：同一帧内多次调用会相加，`end_frame` 时落一个样本。
        """
        if not self.enabled:
            return
        try:
            self._state().add_counter(name, float(value))
        except Exception:      # noqa: BLE001
            pass

    def end_frame(self, frame_ms: float | None = None) -> None:
        """渲染线程每帧调用一次（参数 = 该帧总时长）。

        其它线程用 `end_frame(None)` 冲刷自己的样本但不参与帧占比计算 ——
        逻辑线程的帧边界与渲染帧不同，硬凑会得到错误的占比。
        """
        st = getattr(self._local, "state", None)
        if st is None:
            return
        try:
            st.flush(frame_ms)
        except Exception:      # noqa: BLE001
            pass

    def set_enabled(self, on: bool) -> bool:
        """开关。**打开时会清空样本**（避免半帧数据与旧数据混在一起）。"""
        on = bool(on)
        if on == self.enabled:
            return self.enabled
        self.enabled = on
        if on:
            self.reset()
        return self.enabled

    def reset(self) -> None:
        """清空全部线程的样本（保留线程登记）。"""
        with self._states_lock:
            states = list(self._states)
        for st in states:
            st.excl.clear()
            st.incl.clear()
            st.counters.clear()
            st.frame_ms.clear()
            st.unattributed.clear()
            st.worst.clear()
            st.stack.clear()
            st._cur_excl.clear()
            st._cur_incl.clear()
            st._cur_counters.clear()
            st.top.clear()
            st._depth_zero.clear()
            st.flushes = 0

    # ── 输出 ────────────────────────────────────────────────
    def snapshot(self) -> dict:
        """结构化快照（JSON 友好）。只包含**本 profiler** 登记过的线程。"""
        with self._states_lock:
            self._prune_locked()
            states = list(self._states)
        threads: dict = {}
        for st in states:
            # ★ 同名线程不能互相覆盖: PIE 重启 / 引擎重入会造出同名的新线程，
            #   直接 `{name: ...}` 会让两批样本重叠，报表出现"相均值 > 帧均值"
            #   这种自相矛盾的数字。
            key = st.name if st.name not in threads else f"{st.name}#{st.ident}"
            threads[key] = _thread_snapshot(st)
        return {"enabled": self.enabled, "window": self.window, "threads": threads}

    def report_text(self, top: int = 0) -> str:
        """人读表格 —— 按**排他时间均值**降序，附帧占比与未归因。"""
        snap = self.snapshot()
        lines: list[str] = []
        for thread_name, data in snap["threads"].items():
            if not data["phases"]:
                continue
            frame = data["frame"]
            lines.append(f"── {thread_name} ──")
            lines.append(f"  frame      mean {frame['mean']:7.3f} ms  "
                         f"p50 {frame['p50']:7.3f}  p95 {frame['p95']:7.3f}  "
                         f"p99 {frame['p99']:7.3f}  max {frame['max']:7.3f}  "
                         f"(n={frame['n']})")
            un = data["unattributed"]
            lines.append(f"  unaccounted mean {un['mean']:7.3f} ms  "
                         f"({data['unattributed_share'] * 100:5.1f}% of frame)  "
                         f"p95 {un['p95']:7.3f}")
            rows = sorted(data["phases"].items(),
                          key=lambda kv: kv[1]["excl"]["mean"], reverse=True)
            if top > 0:
                rows = rows[:top]
            lines.append(f"  {'phase':<34} {'excl p50':>9} {'excl mean':>10} {'share':>8} "
                         f"{'p95':>9} {'max':>9} {'incl mean':>10}")
            for name, stats in rows:
                e = stats["excl"]
                i = stats["incl"]
                lines.append(
                    f"  {name:<34} {e['p50']:9.3f} {e['mean']:10.3f} "
                    f"{stats['share'] * 100:7.1f}% "
                    f"{e['p95']:9.3f} {e['max']:9.3f} {i['mean']:10.3f}")
            if data["counters"]:
                lines.append("  counters: " + ", ".join(
                    f"{k}={v['mean']:.1f}" for k, v in sorted(data["counters"].items())))
            if data["worst_frames"]:
                worst = data["worst_frames"][0]
                parts = sorted(worst["phases"].items(), key=lambda kv: kv[1],
                               reverse=True)[:5]
                detail = ", ".join(f"{k}={v}" for k, v in parts)
                lines.append(f"  slowest frame {worst['frame_ms']:.3f} ms → {detail}")
            lines.append("")
        return "\n".join(lines) if lines else "(no phase samples)"
