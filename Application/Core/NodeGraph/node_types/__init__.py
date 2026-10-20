"""
节点编辑器 — 核心节点类型注册表。

核心类型在对应分类文件中通过 _reg() 注册；扩展节点由
`Core/NodeGraph/node_packs.py` 自动发现 `Application/Functions/**/node_pack.py`
后增量注册（2026-10-20 起）。
"""

from __future__ import annotations

from ..data_model import NodeTypeDef, PinDef, _gen_id


# ═══════════════════════════════════════════════════════════════
# 全局注册表
# ═══════════════════════════════════════════════════════════════

_TYPES: dict[str, NodeTypeDef] = {}


def _reg(t: NodeTypeDef) -> NodeTypeDef:
    """注册一个核心节点类型到全局注册表。"""
    _TYPES[t.type_name] = t
    return t


def register_node_type(t: NodeTypeDef) -> NodeTypeDef:
    """动态注册节点类型（扩展节点包入口 — 由 NodePackRegistry 调用）。"""
    _TYPES[t.type_name] = t
    return t


def unregister_node_type(type_name: str) -> bool:
    """移除动态节点类型（内置核心类型不应调用；pack 反注册用）。"""
    return _TYPES.pop(str(type_name), None) is not None


# ═══════════════════════════════════════════════════════════════
# 颜色常量
# ═══════════════════════════════════════════════════════════════

_SUCCESS_GREEN   = (0.471, 0.714, 0.471)
_ERROR_RED       = (0.788, 0.471, 0.471)
_COLOR_EVENT     = (0.420, 0.650, 0.920)
_COLOR_FLOW      = (0.600, 0.600, 0.600)
_BLENDER_ORANGE  = (0.878, 0.416, 0.153)
MATH_COLOR       = (0.420, 0.550, 0.920)
TIME_COLOR       = (0.878, 0.753, 0.314)
ENTITY_COLOR     = (0.314, 0.784, 0.471)
VAR_COLOR        = (0.650, 0.420, 0.920)
VECTOR_COLOR     = (0.314, 0.710, 0.710)
DEBUG_COLOR      = (0.600, 0.600, 0.600)
SCENE_COLOR      = (0.878, 0.416, 0.153)
CAMERA_COLOR     = (0.314, 0.650, 0.920)
COMPONENT_COLOR  = (0.314, 0.710, 0.710)
IO_COLOR         = (0.878, 0.620, 0.314)
BASIC_COLOR      = (0.580, 0.580, 0.620)
MEDIA_COLOR      = (0.870, 0.350, 0.400)
TEXT_COLOR       = (0.420, 0.780, 0.560)


# ═══════════════════════════════════════════════════════════════
# 导入所有子模块以触发 _reg() 注册
# ═══════════════════════════════════════════════════════════════

from . import event      # noqa: E402, F401
from . import flow       # noqa: E402, F401
from . import math       # noqa: E402, F401
from . import time       # noqa: E402, F401
from . import entity     # noqa: E402, F401
from . import game       # noqa: E402, F401
from . import component  # noqa: E402, F401
from . import variable   # noqa: E402, F401
from . import debug      # noqa: E402, F401
from . import io         # noqa: E402, F401
# Serial/Parallel、SigGen/Pool、BCI/Epoch 已迁到扩展 node_pack（2026-10-20）:
#   Application/Functions/{SerialParallelDevice,VirtualDevice,BCIAlgorithm}/node_pack.py
# 不再 import 旧 node_types 文件，避免和动态 pack 重复注册。
from . import media      # noqa: E402, F401
from . import text       # noqa: E402, F401
