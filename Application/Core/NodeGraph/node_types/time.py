"""
时间节点 — TimeGetElapsed, TimeGetDelta, TimeTrigger, TimeGetDate。

2026-10-31: `TimeDelay` 已移除 — 它只在 exec 链被逐帧重入时才推进
（`_exec_visited` 去重 + `_blocked` 截断），从 `OnGameStart` 单次链串入会永久挂起，
且 `props.duration` 不生效（时长只读引脚）。时间推进请用 `TimeTrigger`
（`mode=manual, time=N`）挂在 `OnFrameUpdate` 上。
"""

from . import _reg, _gen_id, TIME_COLOR
from ..data_model import NodeTypeDef, PinDef


_reg(NodeTypeDef(
    "TimeGetElapsed", "Get Time", "Time", TIME_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
        PinDef(_gen_id(), "Elapsed", "data", "output", "float"),
    ],
    "Time since start (or named timer)",
))

_reg(NodeTypeDef(
    "TimeGetDelta", "Get Delta Time", "Time", TIME_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
        PinDef(_gen_id(), "Delta", "data", "output", "float"),
    ],
    "Frame time",
))

_reg(NodeTypeDef(
    "TimeTrigger", "Time Trigger", "Time", TIME_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "Time", "data", "input", "float"),
        PinDef(_gen_id(), "Elapsed", "data", "output", "float"),
    ] + [
        PinDef(_gen_id(), f"out_{i}", "exec", "output") for i in range(8)
    ],
    "",  # 不显示 props 文本以缩减宽度
))

_reg(NodeTypeDef(
    "NewTimer", "New Timer", "Time", TIME_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
        PinDef(_gen_id(), "Name", "data", "input", "string"),
    ],
    "",
))

_reg(NodeTypeDef(
    "SetTimer", "Set Timer", "Time", TIME_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
        PinDef(_gen_id(), "Value", "data", "input", "float"),
    ],
    "",
))

_reg(NodeTypeDef(
    "TimeGetDate", "Get Date", "Time", TIME_COLOR,
    [
        PinDef(_gen_id(), "DateString", "data", "output", "string"),
    ],
    "Current date/time string",
))
