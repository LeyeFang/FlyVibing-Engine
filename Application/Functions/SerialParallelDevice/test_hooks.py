"""SerialParallelDevice — 测试钩子（仅供测试用，非公开 API）。"""

from __future__ import annotations

from . import state


def get_reset_schedule() -> list[tuple[float, int, int]]:
    """[测试] 返回待复位调度的快照副本。"""
    return list(state._reset_schedule)


def clear_reset_schedule() -> None:
    """[测试] 清空待复位调度。"""
    state._reset_schedule.clear()


def inject_parallel(mock) -> None:
    """[测试] 注入 mock 并口驱动，替代真实 _pp。传 None 恢复为 None。"""
    state._pp = mock
    state._parallel_available = mock is not None


def get_parallel_driver():
    """[测试] 返回当前 _pp 引用。"""
    return state._pp
