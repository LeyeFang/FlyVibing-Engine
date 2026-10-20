"""
IO 节点 — PathVar, TextFileWrite。

SerialSend / ParallelSend 已于 2026-10-20 迁到设备扩展
`Application/Functions/SerialParallelDevice/node_pack.py`（type 名保持兼容）。
"""

from . import _reg, _gen_id, IO_COLOR
from ..data_model import NodeTypeDef, PinDef


_reg(NodeTypeDef(
    "PathVar", "Path", "IO", IO_COLOR,
    [
        PinDef(_gen_id(), "Path", "data", "output", "string"),
    ],
    "Directory or file path",
))

_reg(NodeTypeDef(
    "TextFileWrite", "Write Text File", "IO", IO_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
        PinDef(_gen_id(), "FilePath", "data", "input", "string"),
        PinDef(_gen_id(), "FileName", "data", "input", "string"),
        PinDef(_gen_id(), "Value", "data", "input", "variant"),
    ],
    "Write content to a text file",
))
