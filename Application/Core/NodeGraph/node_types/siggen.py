"""
SigGen 节点 — 虚拟信号发生器 (正弦波信号源; Init / Start / Stop / Kill / Get)。

纯软件设备 (无硬件, 任何机器可跑): 用于设备体系端到端验证 (创建 → 采集 →
保存 → 销毁) 与后续算法节点开发基座。设计对齐设备族五件套:

生命周期约定:
  - InitSigGenDevice ⇄ KillSigGenDevice 强制成对出现 (编辑器删除级联, 静态校验检查配对)
  - StartSigGenRecord / StopSigGenRecord / GetSigGenData 通过 device_name 绑定 Init 会话
  - GetSigGenData 为纯数据节点: 每次求值返回窗口缓冲的非销毁副本 (channels × samples)
"""

from . import _reg, _gen_id, SIGGEN_COLOR
from ..data_model import NodeTypeDef, PinDef


# ── InitSigGenDevice — 创建 + 配置虚拟正弦源, 注册会话 ─────

_reg(NodeTypeDef(
    "InitSigGenDevice", "Init SigGen Device", "SigGen", SIGGEN_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
        # device pin: 接 AddToDevicePool.device (可选; 不接 → 设备留在 global 池)
        PinDef(_gen_id(), "device", "data", "output", "device", True),
    ],
    "Create virtual sine source; device pin → AddToDevicePool (default: global)",
))

# ── StartSigGenRecord — 开始采集 ───────────────────────────

_reg(NodeTypeDef(
    "StartSigGenRecord", "Start SigGen Record", "SigGen", SIGGEN_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
    ],
    "Begin synthesis into window buffer",
))

# ── StopSigGenRecord — 停止 + 保存 ─────────────────────────

_reg(NodeTypeDef(
    "StopSigGenRecord", "Stop SigGen Record", "SigGen", SIGGEN_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
    ],
    "Stop synthesis + save to save_dir",
))

# ── KillSigGenDevice — 停止 + 释放 (与 Init 强制成对) ──────

_reg(NodeTypeDef(
    "KillSigGenDevice", "Kill SigGen Device", "SigGen", SIGGEN_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
    ],
    "Stop + close device (must pair with Init)",
))

# ── GetSigGenData — 非销毁读取窗口缓冲 (纯数据节点) ────────

_reg(NodeTypeDef(
    "GetSigGenData", "Get SigGen Data", "SigGen", SIGGEN_COLOR,
    [
        PinDef(_gen_id(), "Data", "data", "output", "variant"),
        PinDef(_gen_id(), "Channels", "data", "output", "int"),
        PinDef(_gen_id(), "Samples", "data", "output", "int"),
        PinDef(_gen_id(), "Fs", "data", "output", "float"),
    ],
    "Copy of window buffer (channels x samples)",
))
