"""
IO 节点 — SerialSend, ParallelSend, PathVar, TextFileWrite。
"""

from . import _reg, _gen_id, IO_COLOR
from ..data_model import NodeTypeDef, PinDef


_reg(NodeTypeDef(
    "SerialSend", "Serial Send", "IO", IO_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
        PinDef(_gen_id(), "Port", "data", "input", "string"),
        PinDef(_gen_id(), "BaudRate", "data", "input", "int"),
        PinDef(_gen_id(), "Value", "data", "input", "variant"),
    ],
    "Send signal via serial port",
))

_reg(NodeTypeDef(
    "ParallelSend", "Parallel Send", "IO", IO_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
        PinDef(_gen_id(), "Address", "data", "input", "int"),
        PinDef(_gen_id(), "Value", "data", "input", "variant"),
    ],
    "Send uint8 via LPT port",
))

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
