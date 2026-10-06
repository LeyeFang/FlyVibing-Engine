"""
Media 节点 — 动态媒体播放驱动（GIF/图像）。

约定（协议 `Doc/Dev/media_protocol.md`）:
  - **编辑器侧编辑只是模板**; 播放必须由图内本节点正确接线才生效;
  - 目标实体: Get Entity (Name) → Entity(entity_ref) → ShowMedia.Entity;
  - 驱动频率 = 接线频率: 挂 OnFrameUpdate 链 → 逐帧播放（推荐, 图入口规则见 rules.md）。
"""

from . import _reg, _gen_id, MEDIA_COLOR
from ..data_model import NodeTypeDef, PinDef


# ── ShowMedia — 驱动实体 MediaPlayer 播放（运行时）─────────

_reg(NodeTypeDef(
    "ShowMedia", "Show Media", "Media", MEDIA_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
        PinDef(_gen_id(), "Entity", "data", "input", "entity_ref"),
    ],
    "Play GIF/image on entity's MediaPlayer — wire under OnFrameUpdate",
))
