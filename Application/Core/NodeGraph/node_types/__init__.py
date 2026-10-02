"""
节点编辑器 — 节点类型注册表。

所有可用节点类型在此定义并注册到 _TYPES。
新增节点类型只需在对应分类文件中添加一个 _reg() 调用。
"""

from __future__ import annotations

from ..data_model import NodeTypeDef, PinDef, _gen_id


# ═══════════════════════════════════════════════════════════════
# 全局注册表
# ═══════════════════════════════════════════════════════════════

_TYPES: dict[str, NodeTypeDef] = {}


def _reg(t: NodeTypeDef) -> NodeTypeDef:
    """注册一个节点类型到全局注册表"""
    _TYPES[t.type_name] = t
    return t


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
GTEC_COLOR       = (0.850, 0.330, 0.620)
SIGGEN_COLOR     = (0.350, 0.780, 0.850)
POOL_COLOR       = (0.930, 0.780, 0.220)
EPOCH_COLOR      = (0.290, 0.680, 0.600)
ALGO_COLOR       = (0.600, 0.360, 0.720)


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
from . import gtec       # noqa: E402, F401
from . import siggen     # noqa: E402, F401
from . import device_pool  # noqa: E402, F401
from . import epoch      # noqa: E402, F401
from . import bci_algorithm  # noqa: E402, F401
