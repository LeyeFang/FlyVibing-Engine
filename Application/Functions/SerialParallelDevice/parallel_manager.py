"""SerialParallelDevice — 并口写入与自动复位逻辑。"""

from __future__ import annotations

import time

from . import state
from .tasks import ParallelTask


# ── 并口复位调度 ──────────────────────────────────────────────

def process_resets(now: float) -> None:
    """处理所有到期的并口复位（写入全零）。"""
    remaining: list[tuple[float, int, int]] = []
    for deadline, addr, count in state._reset_schedule:
        if now >= deadline:
            _write_zero(addr, count)
        else:
            remaining.append((deadline, addr, count))
    state._reset_schedule = remaining


def next_timeout(now: float) -> float:
    """计算下次循环超时（秒）。

    若有待复位任务，返回距离最近截止时间的时间；
    否则返回默认的 50ms 轮询间隔。
    """
    if not state._reset_schedule:
        return 0.05
    next_deadline = min(item[0] for item in state._reset_schedule)
    return max(0.0, next_deadline - now)


def _write_zero(addr: int, count: int) -> None:
    """向并口地址连续写入 count 个零字节。"""
    if state._pp is None:
        return
    for offset in range(count):
        try:
            state._pp.out8(addr + offset, 0)
        except Exception as e:
            print(f"{state._TAG} Parallel reset error @ 0x{addr + offset:04X}: {e}")
            break


def handle_parallel(task: ParallelTask) -> None:
    """处理并口写入任务，非零数据自动调度 5ms 复位。"""
    if state._pp is None:
        print(f"{state._TAG} Drop parallel: InpOut driver not available")
        return

    has_nonzero = any(b != 0 for b in task.data)

    for offset, byte in enumerate(task.data):
        try:
            state._pp.out8(task.address + offset, byte)
        except Exception as e:
            print(f"{state._TAG} Parallel write error @ 0x{task.address + offset:04X}: {e}")
            break

    from .monitor import observe_parallel_write
    observe_parallel_write(task.address, task.data)

    if has_nonzero:
        state._reset_schedule.append(
            (time.perf_counter() + 0.005, task.address, len(task.data))
        )
