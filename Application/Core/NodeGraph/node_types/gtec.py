"""
Gtec 节点 — g.tec g.HIamp 脑电采集 (Init / Start / Stop / Kill / Get)。

配置类选项全部通过节点内联控件 (props) 编辑; 运行时由
Application.Functions.EEGDevice 后端执行 (真实 pygds / MCP 干跑 stub)。

生命周期约定:
  - InitGtecDevice ⇄ KillGtecDevice 强制成对出现 (编辑器删除级联, 静态校验检查配对)
  - StartGtecRecord / StopGtecRecord / GetGtecData 通过 device_name 绑定 Init 会话
  - GetGtecData 为纯数据节点: 每次求值返回窗口缓冲的非销毁副本 (channels × samples)
"""

from . import _reg, _gen_id, GTEC_COLOR
from ..data_model import NodeTypeDef, PinDef


# ── InitGtecDevice — 打开 + 配置设备, 注册会话 ─────────────

_reg(NodeTypeDef(
    "InitGtecDevice", "Init Gtec Device", "Gtec", GTEC_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
    ],
    "Open + configure g.HIamp (template / rate / filters / buffer)",
))

# ── StartGtecRecord — 开始采集 ─────────────────────────────

_reg(NodeTypeDef(
    "StartGtecRecord", "Start Gtec Record", "Gtec", GTEC_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
    ],
    "Begin acquisition into window buffer",
))

# ── StopGtecRecord — 停止 + 保存 ───────────────────────────

_reg(NodeTypeDef(
    "StopGtecRecord", "Stop Gtec Record", "Gtec", GTEC_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
    ],
    "Stop acquisition + save to device folder",
))

# ── KillGtecDevice — 停止 + 释放 (与 Init 强制成对) ────────

_reg(NodeTypeDef(
    "KillGtecDevice", "Kill Gtec Device", "Gtec", GTEC_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
    ],
    "Stop + close device (must pair with Init)",
))

# ── GetGtecData — 非销毁读取窗口缓冲 (纯数据节点) ──────────

_reg(NodeTypeDef(
    "GetGtecData", "Get Gtec Data", "Gtec", GTEC_COLOR,
    [
        PinDef(_gen_id(), "Data", "data", "output", "variant"),
        PinDef(_gen_id(), "Channels", "data", "output", "int"),
        PinDef(_gen_id(), "Samples", "data", "output", "int"),
        PinDef(_gen_id(), "Fs", "data", "output", "float"),
    ],
    "Copy of window buffer (channels x samples)",
))
