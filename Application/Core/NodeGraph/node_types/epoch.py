"""
Epoch 节点 — epoch 数据集（神经工程学口径: epochs × channels × samples）。

EpochDataset = 沿**第一维** append 的 epoch 集合（MNE "Epochs" 语义）:
一条 epoch = 一个试次段 (channels, samples); 堆叠后 ≈ (epochs, channels, samples)。

生命周期约定:
  - 纯内存容器（无 Create/Kill 配对 — 与设备资源的配对哲学不同）;
  - 引用节点（Count/Clear/Save）按 epochs_name 绑定画布源（Append/Load）;
    空名 + 画布唯一源 → 自动绑定（与设备族绑定规则同款）;
  - 干跑: "dryrun#" 命名空间隔离, 跑完由校验服务清理。
"""

from . import _reg, _gen_id, EPOCH_COLOR
from ..data_model import NodeTypeDef, PinDef


# ── EpochAppend — 追加一条 epoch（dim0 = epochs）────────────

_reg(NodeTypeDef(
    "EpochAppend", "Append Epoch", "Epoch", EPOCH_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
        PinDef(_gen_id(), "Data", "data", "input", "variant"),
        PinDef(_gen_id(), "Samples", "data", "input", "int"),
        PinDef(_gen_id(), "Fs", "data", "input", "float"),
        PinDef(_gen_id(), "Label", "data", "input", "float"),
    ],
    "Append one epoch (channels x samples) + label — link Get*Data outputs",
))

# ── EpochCount — 数据集统计（纯数据节点）────────────────────

_reg(NodeTypeDef(
    "EpochCount", "Count Epochs", "Epoch", EPOCH_COLOR,
    [
        PinDef(_gen_id(), "Count", "data", "output", "int"),
        PinDef(_gen_id(), "Classes", "data", "output", "int"),
        PinDef(_gen_id(), "Channels", "data", "output", "int"),
        PinDef(_gen_id(), "Fs", "data", "output", "float"),
    ],
    "Dataset stats — gate training with Count (pure data node)",
))

# ── EpochClear — 清空数据集 ────────────────────────────────

_reg(NodeTypeDef(
    "EpochClear", "Clear Epochs", "Epoch", EPOCH_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
    ],
    "Clear a dataset (idempotent)",
))

# ── EpochSave — 落盘 npz（pad + lengths）───────────────────

_reg(NodeTypeDef(
    "EpochSave", "Save Epoch Dataset", "Epoch", EPOCH_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
    ],
    "Save dataset as npz — dry-run computes path only",
))

# ── EpochLoad — 从 npz 载入（离线数据集入口）───────────────

_reg(NodeTypeDef(
    "EpochLoad", "Load Epoch Dataset", "Epoch", EPOCH_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
    ],
    "Load dataset from npz (mode: replace/append)",
))
