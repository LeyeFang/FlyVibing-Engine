"""
Game 节点 — 游戏级操作 (CameraSetMain, ExitGame)。
"""

from . import _reg, _gen_id, CAMERA_COLOR
from ..data_model import NodeTypeDef, PinDef


_reg(NodeTypeDef(
    "CameraSetMain", "Set Main Camera", "Game", CAMERA_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "Entity", "data", "input", "entity_ref"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
    ],
    "Set active render camera",
))

_reg(NodeTypeDef(
    "ExitGame", "Exit Game", "Game", CAMERA_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
    ],
    "Stop GameRuntime",
))
