"""
Input 数据节点 — IsKeyDown / IsMouseButtonDown / GetMousePosition。

这些是纯数据节点（无 exec 引脚），懒求值时读取 ExecutionContext.input
（RuntimeNodeLayer 每帧注入的 RuntimeInputFrame 快照）。
"""

from . import _reg, _gen_id, INPUT_COLOR
from ..data_model import NodeTypeDef, PinDef


_reg(NodeTypeDef(
    "IsKeyDown", "Is Key Down", "Input", INPUT_COLOR,
    [
        PinDef(_gen_id(), "Down", "data", "output", "int"),
    ],
    "Whether a key is currently held (props: key)",
))

_reg(NodeTypeDef(
    "IsMouseButtonDown", "Is Mouse Button Down", "Input", INPUT_COLOR,
    [
        PinDef(_gen_id(), "Down", "data", "output", "int"),
    ],
    "Whether a mouse button is currently held (props: button)",
))

_reg(NodeTypeDef(
    "GetMousePosition", "Get Mouse Position", "Input", INPUT_COLOR,
    [
        PinDef(_gen_id(), "X", "data", "output", "int"),
        PinDef(_gen_id(), "Y", "data", "output", "int"),
    ],
    "Current mouse position in window/framebuffer pixels",
))
