"""
BCIAlgorithm.EpochDataset — epoch 数据集注册表（神经工程学口径）。

数据结构:
    EpochDataset = 沿**第一维**堆叠的 epoch 集合（append 语义）:
        X ≈ (n_epochs, channels, samples)   — 每条 epoch 为 (channels, samples)
        变长 epoch 以每条的 samples 记录（磁盘格式: pad + lengths）;
        y = 标签序列（与 epoch 一一对应, 数值型）;
        fs = 采样率（首条 epoch 采集时固定, 后续不一致即报错）。

命名: 单条试次段 = epoch（神经工程学/MNE 惯例）; 集合 = EpochDataset。

纪律（与设备注册表同款）:
    - 模块级注册表 + 线程锁（自由线程引擎, 无 GIL）;
    - 干跑命名空间 "dryrun#" 由评估器层加前缀, 跑完由校验服务清理;
    - Runtime 停止/异常由安全网 `reset_all()` 兜底（GameRuntime/PlayerBootstrap 调用）。

门面 API（节点求值器只调用这些函数, 不抛异常 — 返回 (ok/值, detail)）:
    append_epoch(name, data, label, samples=None, fs=None) → (ok, detail)
    clear_epochs(name)                                      → (ok, detail)
    epoch_stats(name)                                       → (dict | None, detail)
    save_epochs(name, save_dir, dry_run=False)              → (ok, detail)
    load_epochs(name, file_path, mode="replace")            → (ok, detail)
    list_datasets()                                         → list[str]
    reset_all()                                             → int   (Runtime 安全网)
    clear_matching(prefix)                                  → int   (dry-run 清理)
"""

from __future__ import annotations

import os
import re
import threading
from datetime import datetime
from typing import Optional

import numpy as np


# ═══════════════════════════════════════════════════════════════
# 注册表（模块级）
# ═══════════════════════════════════════════════════════════════

_LOCK = threading.Lock()
_REGISTRY: dict[str, dict] = {}
# name → {"X": list[np.ndarray (channels, samples)], "y": list[float],
#          "fs": Optional[int], "channels": int}

_NAME_SAFE = re.compile(r"[^0-9A-Za-z_.-]+")


class EpochDatasetError(ValueError):
    """数据校验失败（通道/采样率冲突、空数据等）。"""


# ═══════════════════════════════════════════════════════════════
# 写入 / 清空
# ═══════════════════════════════════════════════════════════════

def append_epoch(name: str, data, label, samples=None,
                 fs=None) -> tuple[bool, str]:
    """向数据集追加一条 epoch（沿第一维 append）。

    Args:
        data:    ndarray (channels, samples) — 1-D 输入视为单通道 (1, n);
                 数据会被复制（与调用方缓冲脱钩）。
        label:   数值标签（分类用; 统一存 float）。
        samples: 有效样本数（来自 Get*Data.Samples; None = 全长）。
        fs:      采样率（首条固定; None = 未知, 不参与一致性校验）。

    Returns: (ok, detail)
    """
    name = (name or "").strip()
    if not name:
        return False, "empty dataset name"
    try:
        arr = np.asarray(data, dtype=np.float32)
        if arr.ndim == 1:
            arr = arr.reshape(1, -1)
        if arr.ndim != 2 or arr.shape[1] == 0:
            return False, f"bad data shape {arr.shape} — expect (channels, samples)"
        if samples is not None:
            try:
                n = int(samples)
            except (TypeError, ValueError):
                n = -1
            if 0 < n <= arr.shape[1]:
                arr = arr[:, :n]
        fs_int: Optional[int]
        try:
            fs_int = int(round(float(fs))) if fs is not None else None
            if fs_int is not None and fs_int <= 0:
                fs_int = None
        except (TypeError, ValueError):
            fs_int = None
        try:
            lab = float(label)
        except (TypeError, ValueError):
            return False, f"bad label {label!r} — numeric required"
    except Exception as e:  # noqa: BLE001 — 防御性
        return False, f"append failed: {type(e).__name__}: {e}"

    with _LOCK:
        entry = _REGISTRY.get(name)
        if entry is None:
            entry = {"X": [], "y": [], "fs": fs_int, "channels": int(arr.shape[0])}
            _REGISTRY[name] = entry
        elif entry["channels"] != int(arr.shape[0]):
            return False, (f"channel mismatch: dataset '{name}' has "
                           f"{entry['channels']}ch, got {arr.shape[0]}ch")
        if fs_int is not None:
            if entry["fs"] is None:
                entry["fs"] = fs_int
            elif entry["fs"] != fs_int:
                return False, (f"sampling rate mismatch: dataset '{name}' is "
                               f"{entry['fs']}Hz, got {fs_int}Hz")
        entry["X"].append(arr.copy())
        entry["y"].append(lab)
        info = (f"'{name}' epoch #{len(entry['X'])} "
                f"shape=({arr.shape[0]},{arr.shape[1]}) label={lab:g}"
                f" fs={entry['fs'] if entry['fs'] else '?'}Hz")
    return True, info


def clear_epochs(name: str) -> tuple[bool, str]:
    """清空（销毁）一个数据集。不存在视为成功（幂等）。"""
    name = (name or "").strip()
    if not name:
        return False, "empty dataset name"
    with _LOCK:
        entry = _REGISTRY.pop(name, None)
    if entry is None:
        return True, f"dataset '{name}' not present (nothing to clear)"
    return True, f"dataset '{name}' cleared (had {len(entry['X'])} epoch(s))"


# ═══════════════════════════════════════════════════════════════
# 查询
# ═══════════════════════════════════════════════════════════════

def epoch_stats(name: str) -> tuple[Optional[dict], str]:
    """数据集统计。Returns: (stats | None, detail)。

    stats = {"count", "classes", "channels", "fs"}（不存在 → None, 原因）。
    """
    name = (name or "").strip()
    with _LOCK:
        entry = _REGISTRY.get(name)
        if entry is None:
            known = ", ".join(sorted(_REGISTRY)) or "(none)"
            return None, f"dataset '{name}' not present (known: {known})"
        count = len(entry["X"])
        classes = len({float(v) for v in entry["y"]}) if entry["y"] else 0
        return ({"count": count, "classes": classes,
                 "channels": entry["channels"],
                 "fs": entry["fs"] or 0}, "")


def list_datasets() -> list[str]:
    with _LOCK:
        return sorted(_REGISTRY)


def snapshot_epochs(name: str) -> tuple[Optional[dict], str]:
    """锁保护快照（训练输入）。

    数组按不可变约定共享引用（append 时已复制入册, 注册表内从不就地修改）—
    训练线程读快照与后续 append 完全隔离, 无竞态。
    Returns: ({"X": [...], "y": [...], "fs", "channels", "count"} | None, detail)。
    """
    name = (name or "").strip()
    with _LOCK:
        entry = _REGISTRY.get(name)
        if entry is None:
            known = ", ".join(sorted(_REGISTRY)) or "(none)"
            return None, f"dataset '{name}' not present (known: {known})"
        if not entry["X"]:
            return None, f"dataset '{name}' is empty — capture epochs first"
        return {"X": list(entry["X"]), "y": list(entry["y"]),
                "fs": entry["fs"], "channels": entry["channels"],
                "count": len(entry["X"])}, ""


# ═══════════════════════════════════════════════════════════════
# 落盘 / 回读（磁盘格式: pad + lengths — 支持变长 epoch）
# ═══════════════════════════════════════════════════════════════

def _plan_path(save_dir: str, name: str) -> str:
    d = (save_dir or "").strip() or "."
    safe = _NAME_SAFE.sub("_", name) or "epochs"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(d, f"{safe}_{stamp}.npz")


def save_epochs(name: str, save_dir: str = ".", dry_run: bool = False) -> tuple[bool, str]:
    """保存数据集为 npz（X pad + lengths + y + fs）。

    dry_run=True（干跑）: 只计算目标路径, 不落盘（与设备 stub 同一哲学）。
    """
    name = (name or "").strip()
    with _LOCK:
        entry = _REGISTRY.get(name)
        if entry is None:
            known = ", ".join(sorted(_REGISTRY)) or "(none)"
            return False, f"dataset '{name}' not present (known: {known})"
        if not entry["X"]:
            return False, f"dataset '{name}' is empty — nothing to save"
        xs = [x.copy() for x in entry["X"]]
        ys = list(entry["y"])
        fs = entry["fs"]
        channels = entry["channels"]

    lengths = np.asarray([x.shape[1] for x in xs], dtype=np.int64)
    max_len = int(lengths.max())
    pad = np.zeros((len(xs), channels, max_len), dtype=np.float32)
    for i, x in enumerate(xs):
        pad[i, :, : x.shape[1]] = x

    path = _plan_path(save_dir, name)
    if dry_run:
        return True, (f"'{name}' dry-run: would save {len(xs)} epoch(s) "
                      f"({channels}x≤{max_len}) → {path}")

    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        np.savez_compressed(path, X=pad, lengths=lengths,
                            y=np.asarray(ys, dtype=np.float64),
                            fs=np.asarray(fs or 0, dtype=np.int64))
    except OSError as e:
        return False, f"save failed: {e}"
    return True, (f"'{name}' saved {len(xs)} epoch(s) ({channels}x≤{max_len}, "
                  f"fs={fs or '?'}) → {path}")


def load_epochs(name: str, file_path: str, mode: str = "replace") -> tuple[bool, str]:
    """从 npz 载入数据集。mode: replace（默认, 覆盖同名） / append（并入同名）。"""
    name = (name or "").strip()
    file_path = (file_path or "").strip()
    if not name:
        return False, "empty dataset name"
    if not file_path:
        return False, "file_path is empty — set the npz path to load"
    if not os.path.isfile(file_path):
        return False, f"file not found: {file_path}"
    mode = mode if mode in ("replace", "append") else "replace"
    try:
        with np.load(file_path) as data:
            X = np.asarray(data["X"], dtype=np.float32)
            lengths = np.asarray(data["lengths"], dtype=np.int64)
            y = np.asarray(data["y"], dtype=np.float64)
            fs = int(data["fs"]) if "fs" in data else 0
    except Exception as e:  # noqa: BLE001 — 文件格式错误统一报 detail
        return False, f"load failed: {type(e).__name__}: {e}"

    if X.ndim != 3 or len(lengths) != X.shape[0] or len(y) != X.shape[0]:
        return False, (f"bad npz layout: X{X.shape} lengths{lengths.shape} "
                       f"y{y.shape}")
    if mode == "replace":
        with _LOCK:
            _REGISTRY.pop(name, None)

    added = 0
    for i in range(X.shape[0]):
        ok, detail = append_epoch(name, X[i][:, : int(lengths[i])], float(y[i]),
                                  fs=fs or None)
        if not ok:
            return False, f"load (row {i}) failed: {detail}"
        added += 1
    return True, f"'{name}' loaded {added} epoch(s) from {file_path} (mode={mode})"


# ═══════════════════════════════════════════════════════════════
# 生命周期（安全网 / dry-run 清理）
# ═══════════════════════════════════════════════════════════════

def reset_all() -> int:
    """清空所有数据集（Runtime 停止/异常保护）。返回移除数量。"""
    with _LOCK:
        n = len(_REGISTRY)
        _REGISTRY.clear()
    return n


def clear_matching(prefix: str) -> int:
    """清空名称带前缀的数据集（dry-run 清理用）。返回移除数量。"""
    prefix = prefix or ""
    if not prefix:
        return 0
    with _LOCK:
        victims = [k for k in _REGISTRY if k.startswith(prefix)]
        for k in victims:
            _REGISTRY.pop(k, None)
    return len(victims)
