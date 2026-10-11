"""SerialParallelDevice — I/O 线程主循环与任务分发。"""

from __future__ import annotations

import time
from queue import Empty

from . import state
from .tasks import SerialTask, ParallelTask
from .serial_manager import port_key, get_or_open_serial, close_port
from .parallel_manager import process_resets, next_timeout, handle_parallel


def io_loop() -> None:
    """I/O 线程主循环 — 统一消费串口和并口任务。

    内置非阻塞计时器: 并口写入后 5ms 自动复位为零。
    通过动态 timeout 实现精确唤醒，不阻塞其他 I/O。
    """
    from Application.Core.ThreadRegistry import ThreadRegistry

    print(f"{state._TAG} I/O thread started")
    _reg = "spd-io"
    ThreadRegistry.register(_reg, owner="SerialParallelDevice", expect_hz=0.0,
                            note="队列驱动; 空闲不推进心跳=正常")
    try:
        while state._running:
            ThreadRegistry.heartbeat(_reg)
            now = time.perf_counter()

            # ── 处理到期的并口复位 ──
            process_resets(now)

            # ── 监视端口 poll（RX 读取 — 收发同线程串行, 无并发访问） ──
            _poll_monitor()

            # ── 计算下一次唤醒的超时 ──
            timeout = next_timeout(now)

            # ── 等待任务 ──
            try:
                task = state._tx_queue.get(timeout=timeout)
            except Empty:
                continue

            # ── 按类型分发 ──
            if isinstance(task, SerialTask):
                _handle_serial(task)
            elif isinstance(task, ParallelTask):
                handle_parallel(task)

        # 线程退出前处理所有待复位
        process_resets(time.perf_counter() + 999.0)
        print(f"{state._TAG} I/O thread stopped")
    finally:
        ThreadRegistry.unregister(_reg)


def _handle_serial(task: SerialTask) -> None:
    """处理串口发送任务。"""
    key = port_key(task.port, task.baud)
    ser = get_or_open_serial(key, task.port, task.baud)
    if ser is None:
        print(f"{state._TAG} Drop serial: {key} not available")
        return
    try:
        ser.write(task.data)
        from .monitor import observe_serial_tx
        observe_serial_tx(task.port, task.baud, task.data)
    except Exception as e:
        print(f"{state._TAG} Serial write error {key}: {e}")
        from .monitor import observe_error
        observe_error(f"write {key}: {e}")
        close_port(key)


def _poll_monitor() -> None:
    """监视端口轮询 — 确保打开 + 读取全部待收字节（io_loop 每轮 ≤50ms）。"""
    mon = state._monitor
    if not mon.get("active"):
        return
    port = str(mon.get("port") or "")
    if not port:
        return
    baud = int(mon.get("baud", 115200))
    key = port_key(port, baud)
    ser = get_or_open_serial(key, port, baud)
    if ser is None:
        # 打开失败节流（无硬件/端口不存在时不刷屏）; 每 2s 重试一次
        now = time.perf_counter()
        if now < mon.get("next_retry", 0.0):
            return
        mon["next_retry"] = now + 2.0
        if mon.get("opened"):
            mon["opened"] = False
        from .monitor import observe_error
        observe_error(f"open failed: {key}")
        return
    if not mon.get("opened"):
        mon["opened"] = True
        from .monitor import _log_event
        _log_event("SYS", b"", f"opened {key}")
    try:
        waiting = ser.in_waiting
        if waiting:
            data = ser.read(waiting)
            if data:
                from .monitor import observe_serial_rx
                observe_serial_rx(data)
    except Exception as e:
        print(f"{state._TAG} Monitor read error {key}: {e}")
        from .monitor import observe_error
        observe_error(f"read {key}: {e}")
        close_port(key)
