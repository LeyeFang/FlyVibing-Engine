"""
Debug 节点 — Print, PrintString。
"""

from . import _reg, _gen_id, DEBUG_COLOR
from ..data_model import NodeTypeDef, PinDef


_reg(NodeTypeDef(
    "Print", "Print", "Debug", DEBUG_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "Value", "data", "input", "variant"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
    ],
    "Print value",
))

_reg(NodeTypeDef(
    "PrintString", "Print String", "Debug", DEBUG_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
    ],
    "Print message",
))
