"""Text 节点 — 文字驱动 (SetText, PIE 控制面; 协议: Doc/Dev/text_protocol.md)。"""

from . import _reg, _gen_id, TEXT_COLOR
from ..data_model import NodeTypeDef, PinDef


_reg(NodeTypeDef(
    "SetText", "Set Text", "Text", TEXT_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "Entity", "data", "input", "entity_ref"),
        PinDef(_gen_id(), "Text", "data", "input", "string"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
    ],
    "Set TextDisplay.text and refresh its texture (PIE)",
))
