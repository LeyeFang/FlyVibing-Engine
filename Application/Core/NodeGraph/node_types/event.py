"""
Event 节点 — Runtime 生命周期入口。
"""

from . import _reg, _gen_id, _SUCCESS_GREEN, _ERROR_RED, _COLOR_EVENT
from ..data_model import NodeTypeDef, PinDef


_reg(NodeTypeDef(
    "OnGameStart", "On Game Start", "Event",
    _SUCCESS_GREEN,
    [PinDef(_gen_id(), "exec", "exec", "output")],
    "When the game begins",
))

_reg(NodeTypeDef(
    "OnGameStop", "On Game Stop", "Event",
    _ERROR_RED,
    [PinDef(_gen_id(), "exec", "exec", "output")],
    "When the game ends",
))

_reg(NodeTypeDef(
    "OnFrameUpdate", "On Frame Update", "Event",
    _COLOR_EVENT,
    [
        PinDef(_gen_id(), "exec", "exec", "output"),
        PinDef(_gen_id(), "delta", "data", "output", "float"),
    ],
    "Every frame",
))
