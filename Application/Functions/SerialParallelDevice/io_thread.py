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
    except Exception as e:
        print(f"{state._TAG} Serial write error {key}: {e}")
        close_port(key)
