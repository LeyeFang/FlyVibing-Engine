"""
Flow 节点 — Sequence, Branch。
"""

from . import _reg, _gen_id, _COLOR_FLOW
from ..data_model import NodeTypeDef, PinDef


_reg(NodeTypeDef(
    "Sequence", "Sequence", "Flow",
    _COLOR_FLOW,
    [PinDef(_gen_id(), "exec_in", "exec", "input")]
    + [PinDef(_gen_id(), f"out_{i}", "exec", "output") for i in range(3)],
    "Chain in order",
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
