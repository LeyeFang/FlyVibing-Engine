"""
BCI 算法节点 — FBCSP / CCA（Algorithm 分类）。

必要超参模式:
  - InitFBCSP: 必选超参内联（n_components / classifier）;
    动态超参组 = bands（打包 list [[lo,hi],...]; UI 解包成行 +/−; 空 = 普通 CSP）;
  - TestCCA:   动态超参组 = freqs（≥2 不限上限）; 必选 = n_harmonics。

训练语义（TrainFBCSP）:
  - 同步等待: 训练期间节点 _blocked（下游暂停）; 完成当帧继续下行（恰好一次）;
  - 必须挂在可重复触发的链上（OnGameStart 链会永久卡住 — 与 TimeDelay 同理）;
  - 干跑: 同步训练（确定性）; 真实: SyncJob 服务线程 + 进度日志。
"""

from . import _reg, _gen_id, ALGO_COLOR
from ..data_model import NodeTypeDef, PinDef


# ── InitFBCSP — 注册超参集（spec）──────────────────────────

_reg(NodeTypeDef(
    "InitFBCSP", "Init FBCSP", "Algorithm", ALGO_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
    ],
    "Register FBCSP spec (n_components / classifier / bands [+]) — bands empty = plain CSP",
))

# ── TrainFBCSP — 训练/加载（同步等待）──────────────────────

_reg(NodeTypeDef(
    "TrainFBCSP", "Train FBCSP", "Algorithm", ALGO_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
    ],
    "Train (blocks until done) or load a model; keep on a repeatedly-triggered chain",
))

# ── TestFBCSP — 数据进标签出（纯数据节点）──────────────────

_reg(NodeTypeDef(
    "TestFBCSP", "Test FBCSP", "Algorithm", ALGO_COLOR,
    [
        PinDef(_gen_id(), "Data", "data", "input", "variant"),
        PinDef(_gen_id(), "Samples", "data", "input", "int"),
        PinDef(_gen_id(), "Label", "data", "output", "int"),
        PinDef(_gen_id(), "Confidence", "data", "output", "float"),
    ],
    "Signal in → Label out (trained model by model_name)",
))

# ── TestCCA — SSVEP 免训练判别（纯数据节点）────────────────

_reg(NodeTypeDef(
    "TestCCA", "Test CCA", "Algorithm", ALGO_COLOR,
    [
        PinDef(_gen_id(), "Data", "data", "input", "variant"),
        PinDef(_gen_id(), "Samples", "data", "input", "int"),
        PinDef(_gen_id(), "Fs", "data", "input", "float"),
        PinDef(_gen_id(), "Label", "data", "output", "int"),
        PinDef(_gen_id(), "Score", "data", "output", "float"),
        PinDef(_gen_id(), "Freq", "data", "output", "float"),
    ],
    "CCA (training-free): Data+Fs → Label(idx)/Score/Freq — freq groups [+], >=2",
))
