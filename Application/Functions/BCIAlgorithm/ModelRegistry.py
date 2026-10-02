"""
BCIAlgorithm.ModelRegistry — BCI 模型注册表（spec / trained model）。

条目形态:
    {"kind": "spec",  "algo": "FBCSP", "spec": {...}}    ← InitFBCSP 注册（超参集）
    {"kind": "model", "algo": "FBCSP", "model": {...}}   ← TrainFBCSP 注册（训练/加载产物）

纪律（与设备/epoch 注册表同款）:
    - 模块级注册表 + 线程锁（自由线程引擎, 无 GIL）;
    - 干跑命名空间 "dryrun#" 由评估器层加前缀, 校验服务跑完清理;
    - Runtime 安全网由 BCIAlgorithm.reset_all() 一并清空。
"""

from __future__ import annotations

import threading

_LOCK = threading.Lock()
_REGISTRY: dict[str, dict] = {}


def register_spec(name: str, algo: str, spec: dict) -> tuple[bool, str]:
    """注册算法超参集（覆盖式幂等 — 同名重复注册以最新为准）。"""
    name = (name or "").strip()
    if not name:
        return False, "empty model name"
    with _LOCK:
        _REGISTRY[name] = {"kind": "spec", "algo": algo, "spec": dict(spec)}
    return True, f"spec '{name}' [{algo}] registered"


def set_model(name: str, algo: str, model: dict) -> tuple[bool, str]:
    """登记训练/加载产物模型。"""
    name = (name or "").strip()
    if not name:
        return False, "empty model name"
    with _LOCK:
        _REGISTRY[name] = {"kind": "model", "algo": algo, "model": model}
    return True, f"model '{name}' [{algo}] registered"


def get_entry(name: str) -> tuple[dict | None, str]:
    """读取条目。Returns: (entry | None, detail)。"""
    name = (name or "").strip()
    with _LOCK:
        entry = _REGISTRY.get(name)
        if entry is None:
            known = ", ".join(sorted(_REGISTRY)) or "(none)"
            return None, f"model registry: '{name}' not present (known: {known})"
        return dict(entry), ""


def list_entries() -> list[str]:
    with _LOCK:
        return sorted(_REGISTRY)


def clear_matching(prefix: str) -> int:
    """清空名称带前缀的条目（dry-run 清理用）。返回移除数量。"""
    prefix = prefix or ""
    if not prefix:
        return 0
    with _LOCK:
        victims = [k for k in _REGISTRY if k.startswith(prefix)]
        for k in victims:
            _REGISTRY.pop(k, None)
    return len(victims)


def reset_all() -> int:
    """清空全部条目（Runtime 安全网）。返回移除数量。"""
    with _LOCK:
        n = len(_REGISTRY)
        _REGISTRY.clear()
    return n
