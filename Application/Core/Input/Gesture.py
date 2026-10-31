"""输入手势判定 — 编辑器与 GameRuntime 共用的 click/drag 阈值。

统一约定:
  * click = 按下后释放，位移 <= CLICK_MOVE_THRESHOLD；
  * drag  = 位移超过阈值；不得再触发 click / 右键菜单。
编辑器（节点图框选、右键菜单）和 RuntimeInputLayer 都使用这里的常量，
避免两套阈值漂移。
"""

from __future__ import annotations

import math

# 屏幕/窗口像素。6px 足以过滤鼠标抖动，又不会把正常点击判成拖拽。
CLICK_MOVE_THRESHOLD = 6.0


def is_click(start: tuple[float, float],
             end: tuple[float, float],
             threshold: float = CLICK_MOVE_THRESHOLD) -> bool:
    """起点→终点位移不超过 threshold 视为 click。"""
    dx = float(end[0]) - float(start[0])
    dy = float(end[1]) - float(start[1])
    return math.hypot(dx, dy) <= float(threshold)


def moved(start: tuple[float, float],
          end: tuple[float, float],
          threshold: float = CLICK_MOVE_THRESHOLD) -> bool:
    """起点→终点位移超过 threshold 视为 drag。"""
    return not is_click(start, end, threshold)
