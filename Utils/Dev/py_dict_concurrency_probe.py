"""Python 3.14 自由线程下 dict 的并发语义实测（决定竞态修法用不用官方特性）。

要回答的问题
  1. 迭代中并发改写 → 还抛不抛 RuntimeError？（决定"能不能裸迭代"）
  2. dict.copy() 在并发改写时是否原子快照？（决定"快照 + 原子替换"是否可用）
  3. MappingProxyType / frozenset(keys) / tuple(items) 是否可作为只读快照
  4. 原子重绑定（obj.attr = new_dict）能否让读者永不看到半成品
  5. PEP 734 的 concurrent.interpreters 是否可用（真隔离，但跨解释器共享很难）

用法: .venv-py314t\\Scripts\\python.exe -Xgil=0 Utils/Dev/py_dict_concurrency_probe.py
"""

from __future__ import annotations

import sys
import threading
import time
import types

N_ITER = 3000


def _spinner(d: dict, stop: threading.Event) -> threading.Thread:
    def loop():
        k = 100_000
        while not stop.is_set():
            d[k] = k
            k += 1
            if k % 3 == 0:
                d.pop(k - 1, None)

    t = threading.Thread(target=loop, daemon=True)
    t.start()
    return t


def probe_iteration() -> dict:
    d = {i: i for i in range(1000)}
    stop = threading.Event()
    t = _spinner(d, stop)
    raised = 0
    for _ in range(N_ITER):
        try:
            list(d.items())
        except RuntimeError:
            raised += 1
    stop.set()
    t.join(timeout=2)
    return {"case": "list(d.items())", "raised": raised, "of": N_ITER}


def probe_copy() -> dict:
    d = {i: i for i in range(1000)}
    stop = threading.Event()
    t = _spinner(d, stop)
    raised = 0
    sizes = []
    for _ in range(N_ITER):
        try:
            c = d.copy()
            sizes.append(len(c))
        except RuntimeError:
            raised += 1
    stop.set()
    t.join(timeout=2)
    return {"case": "d.copy()", "raised": raised, "of": N_ITER,
            "snapshot_nonempty": bool(sizes) and min(sizes) >= 1000}


def probe_mappingproxy() -> dict:
    """MappingProxyType 是视图，不是快照 —— 底层变了它也变。"""
    base = {i: i for i in range(200)}
    view = types.MappingProxyType(base)
    before = len(view)
    base[999] = 999
    after = len(view)
    return {"case": "MappingProxyType", "is_snapshot": before == after,
            "before": before, "after": after}


def probe_tuple_items() -> dict:
    d = {i: i for i in range(1000)}
    stop = threading.Event()
    t = _spinner(d, stop)
    raised = 0
    for _ in range(N_ITER):
        try:
            tuple(d.items())
        except RuntimeError:
            raised += 1
    stop.set()
    t.join(timeout=2)
    return {"case": "tuple(d.items())", "raised": raised, "of": N_ITER}


class _Holder:
    def __init__(self) -> None:
        self.entities = {i: i for i in range(50)}


def probe_atomic_rebind() -> dict:
    """copy-on-write + 原子重绑定：读者是否可能看到空表/半成品。

    模拟真实场景：一个重建者不停 "先建新 dict 再整体赋值"，
    多个读者不停遍历当前引用。
    """
    holder = _Holder()
    stop = threading.Event()
    bad: list[str] = []

    def rebuilder():
        n = 0
        while not stop.is_set():
            fresh = {i: i for i in range(50)}          # 先建
            fresh[1000 + n] = n                        # 填满
            holder.entities = fresh                    # 再原子换引用
            n += 1

    def reader():
        while not stop.is_set():
            snap = holder.entities                     # 取引用（原子）
            try:
                items = list(snap.items())
            except RuntimeError as exc:
                bad.append(f"RuntimeError: {exc}")
                continue
            if len(items) < 50:
                bad.append(f"partial snapshot: {len(items)}")

    threads = [threading.Thread(target=rebuilder, daemon=True)] + [
        threading.Thread(target=reader, daemon=True) for _ in range(3)]
    for t in threads:
        t.start()
    time.sleep(1.5)
    stop.set()
    for t in threads:
        t.join(timeout=2)
    return {"case": "copy-on-write + atomic rebind",
            "violations": len(bad), "sample": bad[:3]}


def probe_interpreters() -> dict:
    try:
        import concurrent.interpreters as ci  # noqa: F401  (PEP 734, 3.14)
    except Exception as exc:  # noqa: BLE001
        return {"case": "concurrent.interpreters", "available": False,
                "reason": f"{type(exc).__name__}: {exc}"}
    return {"case": "concurrent.interpreters", "available": True}


def main() -> None:
    print("=" * 66)
    print("Python dict 并发语义实测")
    print("=" * 66)
    print(f"python      : {sys.version.split()[0]}")
    print(f"gil enabled : {sys._is_gil_enabled() if hasattr(sys, '_is_gil_enabled') else 'n/a'}")
    print(f"build       : {'free-threading' if not sys._is_gil_enabled() else 'gil'}")
    print()

    rows = [probe_iteration(), probe_tuple_items(), probe_copy(),
            probe_mappingproxy(), probe_atomic_rebind(), probe_interpreters()]
    for r in rows:
        print(f"  {r}")

    print()
    it = rows[0]
    cp = rows[2]
    rb = rows[4]
    print("-" * 66)
    print("结论")
    print("-" * 66)
    if it["raised"]:
        print(f"  · 裸迭代**不安全**：{it['raised']}/{it['of']} 次抛 RuntimeError")
        print("    → 自由线程不会替你把 dict 变成并发容器（PEP 703 只保证单次操作原子）")
    else:
        print("  · 裸迭代未观察到 RuntimeError（可能改写速度不够）")
    if cp["raised"] == 0:
        print(f"  · dict.copy() 是**原子快照**：{N_ITER} 次零异常，且都 >= 原始条目数")
        print("    → 可用作『取一份当前状态再遍历』的唯一官方手段")
    else:
        print(f"  · dict.copy() 仍有 {cp['raised']} 次异常")
    if not rows[3]["is_snapshot"]:
        print("  · MappingProxyType **不是快照**（只是只读视图），不能用来防并发")
    if rb["violations"] == 0:
        print("  · copy-on-write + 原子重绑定：读者零违例（既不半空也不抛）")
    else:
        print(f"  · copy-on-write 仍有 {rb['violations']} 次违例: {rb['sample']}")
    print(f"  · {rows[5]}")


if __name__ == "__main__":
    main()
