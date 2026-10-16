"""节点编辑器 — 各节点类型的内联控件 (Widget) 包。

注册表模式：widget 函数通过 @register 装饰器注册（注册表在 core.py），
panel.py 调用 draw_node_widgets(nid, inst, canvas) 自动分发。
子模块在末尾统一导入 —— import 即注册，新增节点类型只需在对应子模块加 @register 函数：
  flow_io       通用/流程节点（IO·逻辑·计时·变量·常量）
  entity_comp   实体/组件节点
  device_siggen / device_pool   IO 设备节点
  epoch         Epoch 数据集节点
  algorithm     BCI Algorithm（FBCSP/CCA）节点
  media         动态媒体节点（ShowMedia — PIE 播放驱动）
  text          文字节点（SetText）
"""

from __future__ import annotations

from .core import (  # noqa: F401 — 对外兼容面 (panel.py 只需 draw_node_widgets)
    draw_node_widgets,
    register,
    _ne_combo,
)

# ── 导入即注册（不要删除）──
from . import flow_io  # noqa: F401,E402
from . import entity_comp  # noqa: F401,E402
from . import device_common  # noqa: F401,E402
from . import device_siggen  # noqa: F401,E402
from . import device_pool  # noqa: F401,E402
from . import epoch  # noqa: F401,E402
from . import algorithm  # noqa: F401,E402
from . import media  # noqa: F401,E402
from . import text  # noqa: F401,E402
