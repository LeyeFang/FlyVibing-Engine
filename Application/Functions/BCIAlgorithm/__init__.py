"""
BCIAlgorithm — BCI 算法域目录（Functions 层级; 终端可选拓展体系的一部分）。

目录组织:
  - EpochDataset.py   epoch 数据集注册表（epochs × channels × samples）;
  - ModelRegistry.py  模型注册表（spec / trained model）;
  - FBCSP.py          Filter Bank CSP + 闭式 LDA / 线性 SVM（含模型落盘）;
  - CCA.py            典型相关分析（SSVEP 免训练判别）;
  - Jobs.py           同步等待式训练任务（线程 + 锁槽）。

设计纪律:
  - 节点求值器只调用本包门面函数（(ok, detail) 契约, 不抛异常）;
  - 干跑命名空间 "dryrun#" 与设备层一致, 由校验服务清理;
  - Runtime 停止安全网 reset_all()（同时清空数据集 + 模型注册表）。
"""

from .CCA import predict_cca
from .EpochDataset import (
    append_epoch,
    clear_epochs,
    epoch_stats,
    list_datasets,
    load_epochs,
    save_epochs,
    snapshot_epochs,
)
from .FBCSP import (
    load_fbcsp_model,
    parse_fbcsp_spec,
    predict_fbcsp,
    save_fbcsp_model,
    train_fbcsp,
)
from .Jobs import SyncJob
from .ModelRegistry import (
    get_entry,
    list_entries,
    register_spec,
    set_model,
)


def reset_all() -> int:
    """清空全部算法运行态（epoch 数据集 + 模型注册表）— Runtime 安全网。"""
    from .EpochDataset import reset_all as _epochs_reset
    from .ModelRegistry import reset_all as _models_reset

    return _epochs_reset() + _models_reset()


def clear_matching(prefix: str) -> int:
    """按前缀清理（dry-run 清理用 — 数据集 + 模型同命名空间）。"""
    from .EpochDataset import clear_matching as _epochs_clear
    from .ModelRegistry import clear_matching as _models_clear

    return _epochs_clear(prefix) + _models_clear(prefix)


__all__ = [
    # epoch 数据集
    "append_epoch",
    "clear_epochs",
    "epoch_stats",
    "save_epochs",
    "load_epochs",
    "snapshot_epochs",
    "list_datasets",
    # 模型注册表
    "register_spec",
    "set_model",
    "get_entry",
    "list_entries",
    # 算法
    "parse_fbcsp_spec",
    "train_fbcsp",
    "predict_fbcsp",
    "save_fbcsp_model",
    "load_fbcsp_model",
    "predict_cca",
    "SyncJob",
    # 生命周期
    "reset_all",
    "clear_matching",
]
