"""
变量 / Basic 节点 — VarSet, VarGet, Constant, StringConst。
"""

from . import _reg, _gen_id, VAR_COLOR, BASIC_COLOR
from ..data_model import NodeTypeDef, PinDef


_reg(NodeTypeDef(
    "VarSet", "Set Variable", "Variable", VAR_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "Name", "data", "input", "string"),
        PinDef(_gen_id(), "Value", "data", "input", "variant"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
    ],
    "Write variable",
))

_reg(NodeTypeDef(
    "VarGet", "Get Variable", "Variable", VAR_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "Name", "data", "input", "string"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
        PinDef(_gen_id(), "Value", "data", "output", "variant"),
    ],
    "Read variable",
))

_reg(NodeTypeDef(
    "Constant", "Number", "Basic", BASIC_COLOR,
    [
        PinDef(_gen_id(), "Result", "data", "output", "float"),
    ],
    "A number value",
))

_reg(NodeTypeDef(
    "StringConst", "String Constant", "Basic", BASIC_COLOR,
    [
        PinDef(_gen_id(), "Value", "data", "output", "string"),
    ],
    "A string value",
))
