"""
ThreadRegistry — 线程注册表 + 心跳（线程开发协议 `Doc/Dev/threading_protocol.md` 的运行时侧）。

新线程四步（详见协议）:
    1. 线程入口: ThreadRegistry.register(name, owner="模块", expect_hz=..., note="...")
    2. 循环内:   ThreadRegistry.heartbeat(name)        # 每轮一次（心跳 = 存活证据）
    3. 退出前:   ThreadRegistry.unregister(name)       # finally
    4. 验证:     engine-editor-cli call threads.snapshot
                 python Utils/Dev/thread_probe.py [--watch|--assert-alive|--fail-on-stale]

心跳语义:
    expect_hz > 0 : 周期线程 — age > max(1.0, 3/expect_hz) 秒 → stale（停滞嫌疑）;
    expect_hz = 0 : 事件驱动线程（阻塞 accept/recv/队列 场景）— 只报 age, 永不 stale;
    heartbeat 对未注册名容错（自动注册 owner="<auto>"）——忘记 register 也不丢心跳。

漂移检测:
    snapshot 同时列出 "unregistered": 进程中存活但未注册的命名线程
    （匿名 Thread-N / MainThread 除外）——用本协议把它们收编。
"""

from __future__ import annotations

import threading
import time


class ThreadRegistry:
    """进程级线程注册表（线程安全; 零依赖）。"""

    _lock = threading.Lock()
    _entries: dict[str, dict] = {}

    # ── 注册 / 心跳 / 注销 ──────────────────────────────────

    @classmethod
    def register(cls, name: str, *, owner: str = "", expect_hz: float = 0.0,
                 note: str = "") -> None:
        """注册线程（同名覆盖; 建议在目标线程内部调用, 以记录线程对象供 alive 判定）。"""
        now = time.monotonic()
        with cls._lock:
            cls._entries[name] = {
                "name": name, "owner": owner, "expect_hz": float(expect_hz),
                "note": note, "registered_at": now, "last_beat": now, "beats": 0,
                "thread": threading.current_thread(),
            }

    @classmethod
    def heartbeat(cls, name: str) -> None:
        """心跳 — 每轮循环调用一次。未注册名自动注册（owner="<auto>"）。"""
        now = time.monotonic()
        with cls._lock:
            e = cls._entries.get(name)
            if e is None:
                e = {"name": name, "owner": "<auto>", "expect_hz": 0.0,
                     "note": "heartbeat 自动注册", "registered_at": now,
                     "last_beat": now, "beats": 0,
                     "thread": threading.current_thread()}
                cls._entries[name] = e
            e["last_beat"] = now
            e["beats"] += 1

    @classmethod
    def unregister(cls, name: str) -> None:
        """注销（线程退出前调用; 幂等）。"""
        with cls._lock:
            cls._entries.pop(name, None)

    # ── 快照 ────────────────────────────────────────────────

    @classmethod
    def snapshot(cls) -> dict:
        """诊断快照: {registered: [...], unregistered: [...], stale: [...], count}。"""
        now = time.monotonic()
        with cls._lock:
            items = [(n, dict(e)) for n, e in cls._entries.items()]

        registered: list[dict] = []
        stale: list[str] = []
        for name, e in items:
            age = now - e["last_beat"]
            hz = e["expect_hz"]
            threshold = max(1.0, 3.0 / hz) if hz > 0 else None
            is_stale = threshold is not None and age > threshold
            if is_stale:
                stale.append(name)
            t = e.get("thread")
            registered.append({
                "name": name,
                "owner": e["owner"],
                "expect_hz": hz,
                "beats": e["beats"],
                "age_ms": round(age * 1000.0, 1),
                "stale": is_stale,
                "alive": bool(t.is_alive()) if isinstance(t, threading.Thread) else None,
                "note": e["note"],
            })

        known = {n for n, _ in items}
        unregistered = sorted(
            t.name for t in threading.enumerate()
            if t.name not in known and t.name != "MainThread"
            and not t.name.startswith("Thread-")
        )
        return {"registered": registered, "unregistered": unregistered,
                "stale": sorted(stale), "count": len(registered)}


__all__ = ["ThreadRegistry"]
