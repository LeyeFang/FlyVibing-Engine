"""SerialParallelDevice — 监视能力（端口枚举 / 收发事件流 / 统计）。

供扩展面板（`Application/Functions/SerialParallelDevice/extension.py` — 官方示例）与
agent（`ext.device.monitor_snapshot` op）消费。

设计要点:
  - **收发单线程化**: 实际打开/读取由既有 `spd-io` 线程执行
    （TX 由任务队列驱动; RX 由 io_loop 每轮 poll — 循环基频 ≤50ms），
    读写在同线程内串行 — 无并发访问同一 Serial 对象问题;
  - 事件环形缓冲 (maxlen=500): 跨线程快照由 `state._lock` 保护;
  - 打开失败节流 (2s): 无硬件/端口不存在时不刷屏。

事件 kind: "TX" 串口发送 | "RX" 串口接收 | "PX" 并口写入 | "SYS" 系统（watch 启停/错误）
"""

from __future__ import annotations

import time

from . import state

# 并口候选地址（面板 L1 选择集; 3FF8/3FF0/3FE8 = 常见 trigger 口, 378/278 = LPT）
PARALLEL_ADDRS: list[int] = [0x3FF8, 0x3FF0, 0x3FE8, 0x378, 0x278]

_OPEN_RETRY_INTERVAL = 2.0


# ── 事件记录（内部 — io_thread / 发送路径调用） ────────────────

def _log_event(kind: str, data: bytes = b"", note: str = "") -> None:
    with state._lock:
        state._events.append((time.perf_counter(), kind, data, note))


def observe_serial_tx(port: str, baud: int, data: bytes) -> None:
    """串口发送成功回调（io_thread）。"""
    with state._lock:
        state._stats["tx_count"] += 1
        state._stats["tx_bytes"] += len(data)
    _log_event("TX", data, f"{port}@{baud}")


def observe_serial_rx(data: bytes) -> None:
    """串口接收回调（io_thread poll）。"""
    with state._lock:
        state._stats["rx_count"] += 1
        state._stats["rx_bytes"] += len(data)
    _log_event("RX", data)


def observe_parallel_write(address: int, data: bytes) -> None:
    """并口写入回调（parallel_manager）。"""
    with state._lock:
        state._stats["parallel_writes"] += 1
    _log_event("PX", data, f"0x{address:04X}")


def observe_error(msg: str) -> None:
    """错误记录（串口打开/读写失败等）。"""
    with state._lock:
        state._stats["last_error"] = str(msg)
    _log_event("SYS", b"", f"error: {msg}")


# ── 查询 / 控制（面板与 ops 调用） ─────────────────────────────

def list_serial_ports() -> list[dict]:
    """枚举本机串口（pyserial.tools.list_ports; 失败/缺库 → []）。"""
    try:
        from serial.tools import list_ports
        return [{"device": p.device or "",
                 "description": p.description or "",
                 "hwid": p.hwid or ""}
                for p in list_ports.comports()]
    except Exception:
        return []


def start_watch(port: str, baud: int) -> dict:
    """开始监视指定串口（实际打开交给 spd-io 线程; 幂等 — 重复调用替换参数）。

    `port` 可为物理端口或**逻辑设备名** `@mibox`（协议 §12）—— 解析失败会显式抛错
    （`DeviceUnresolved` / `ValueError`），便于面板与 op 立刻给出可操作提示。
    """
    from .serial_manager import resolve_port
    port = resolve_port(port)           # @name → 物理端口（未绑定 → 显式抛错）
    with state._lock:
        state._monitor.update(active=True, port=str(port), baud=int(baud),
                              opened=False, next_retry=0.0)
    _log_event("SYS", b"", f"watch start: {port}@{baud}")
    return watch_state()


def stop_watch() -> dict:
    """停止监视（不关闭底层端口 — 由既有生命周期管理）。"""
    with state._lock:
        was = state._monitor.get("port", "")
        state._monitor.update(active=False, opened=False, port="")
    if was:
        _log_event("SYS", b"", f"watch stop: {was}")
    return watch_state()


def watch_state() -> dict:
    """监视状态快照: {active, port, baud, opened}。"""
    with state._lock:
        m = state._monitor
        return {"active": bool(m.get("active")), "port": m.get("port", ""),
                "baud": int(m.get("baud", 115200)), "opened": bool(m.get("opened"))}


def parallel_status() -> dict:
    """并口状态: 驱动可用性 + 候选地址表。"""
    return {"available": bool(state._parallel_available),
            "addrs": list(PARALLEL_ADDRS)}


def monitor_snapshot(max_events: int = 200) -> dict:
    """线程安全快照 — 面板帧内 / agent op 拉取。

    Returns:
        {"watch": {...}, "stats": {...}, "events": [新→旧 列表]}
        事件条目: {t, kind, hex, text, note}
    """
    with state._lock:
        events = list(state._events)[-max(0, int(max_events)):]
        stats = dict(state._stats)
        watch = {"active": bool(state._monitor.get("active")),
                 "port": state._monitor.get("port", ""),
                 "baud": int(state._monitor.get("baud", 115200)),
                 "opened": bool(state._monitor.get("opened"))}
    out = [{"t": round(t, 3), "kind": kind,
            "hex": data.hex(" ") if data else "",
            "text": _ascii_preview(data), "note": note}
           for (t, kind, data, note) in reversed(events)]
    return {"watch": watch, "stats": stats, "events": out}


def _ascii_preview(data: bytes) -> str:
    return "".join(chr(b) if 32 <= b < 127 else "." for b in data)
