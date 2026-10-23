"""
Flow 节点 — Sequence, Branch, GroupStart/GroupEnd（组内部 exec 接口）。
"""

from . import _reg, _gen_id, _COLOR_FLOW
from ..data_model import NodeTypeDef, PinDef


_reg(NodeTypeDef(
    "Sequence", "Sequence", "Flow",
    _COLOR_FLOW,
    [PinDef(_gen_id(), "exec_in", "exec", "input")]
    + [PinDef(_gen_id(), f"out_{i}", "exec", "output") for i in range(5)],
    "Fan-out to 4 exec chains",
))

_reg(NodeTypeDef(
    "Branch", "Branch", "Flow",
    _COLOR_FLOW,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "Condition", "data", "input", "bool"),
        PinDef(_gen_id(), "True", "exec", "output"),
        PinDef(_gen_id(), "False", "exec", "output"),
    ],
    "If / Else",
))

# ── 组入口/出口 — 随组创建/删除的内部节点 ──────────────────
# 组框本身在 imgui-node-editor 中不能挂 pin；用两个真实节点承载组级
# exec 接口。它们只是普通节点，因此可以从起点自由拖线到组内任意成员。
_GROUP_IO_COLOR = (0.480, 0.760, 0.520)

_reg(NodeTypeDef(
    "GroupStart", "Group Start", "Group",
    _GROUP_IO_COLOR,
    [PinDef(_gen_id(), "exec_out", "exec", "output")],
    "Group entry: connect exec_out to any member node",
))

_reg(NodeTypeDef(
    "GroupEnd", "Group End", "Group",
    _GROUP_IO_COLOR,
    [PinDef(_gen_id(), "exec_in", "exec", "input")],
    "Group exit: connect any member node here",
))
