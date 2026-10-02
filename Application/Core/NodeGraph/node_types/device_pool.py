"""
Device Pool 节点 — 设备池 (IO ▸ Pool)。

设备池 = 设备的分组 / 生命周期 / (未来) 进程组与同步域锚点:
  - CreateDevicePool ⇄ KillDevicePool 强制成对出现 (编辑器删除级联, 静态校验配对)
  - Init*Device 的 device 输出 pin → AddToDevicePool 把该设备加入池
    (未加入任何显式池的设备 → 隐式 global 池)
  - Start/Stop/Kill/Get 设备节点按 pool + device_name 绑定会话:
     device_name 空 → 池内唯一设备自动绑定

执行时序约定 (CRITICAL): AddToDevicePool 必须与对应 Init 在同一条 exec 链上、
紧跟在 Init 之后执行 (ExecutionContext 每 trigger 清 pin 值; 见 graph_rules)。
"""

from . import _reg, _gen_id, POOL_COLOR
from ..data_model import NodeTypeDef, PinDef


# ── CreateDevicePool — 注册设备池 ──────────────────────────

_reg(NodeTypeDef(
    "CreateDevicePool", "Create Device Pool", "Pool", POOL_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
    ],
    "Register a device pool (pool_name; members added via AddToDevicePool)",
))

# ── AddToDevicePool — 把 device pin 上的设备加入池 ──────────

_reg(NodeTypeDef(
    "AddToDevicePool", "Add To Device Pool", "Pool", POOL_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
        PinDef(_gen_id(), "device", "data", "input", "device"),
    ],
    "Add the device from 'device' pin into pool_name (chain right after its Init)",
))

# ── KillDevicePool — 注销池 (与 Create 强制成对) ───────────

_reg(NodeTypeDef(
    "KillDevicePool", "Kill Device Pool", "Pool", POOL_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
    ],
    "Unregister pool; members fall back to global (must pair with Create)",
))
