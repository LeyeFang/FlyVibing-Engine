"""SerialParallelDevice — 公开 API：启动/停止/发送/写入。"""

from __future__ import annotations

import threading
from queue import Empty

from . import state
from .tasks import SerialTask, ParallelTask
from .serial_manager import close_all
from .io_thread import io_loop
from .protocol import encode


def start() -> None:
    """启动 I/O 线程。幂等 — 重复调用无副作用。"""
    if state._running:
        return
    state._running = True
    state._io_thread = threading.Thread(
        target=io_loop, daemon=True, name="spd-io"
    )
    state._io_thread.start()


def stop() -> None:
    """停止 I/O 线程，关闭所有串口。幂等 — 重复调用无副作用。

    退出前会处理所有待复位，确保并口回到零状态。
    """
    if not state._running:
        return
    state._running = False

    # 清空队列中未发送的数据
    while not state._tx_queue.empty():
        try:
            state._tx_queue.get_nowait()
        except Empty:
            break

    # 等待 I/O 线程退出（线程退出前会自动处理待复位）
    if state._io_thread is not None and state._io_thread.is_alive():
        state._io_thread.join(timeout=2.0)
    state._io_thread = None

    # 关闭所有串口
    close_all()


def send(port: str, baud: int, data: bytes) -> None:
    """入队串口发送 — 非阻塞，立即返回。

    Args:
        port:  串口号，如 "COM2"
        baud:  波特率，如 9600
        data:  要发送的字节数据
    """
    if not state._running:
        print(f"{state._TAG} Not running — dropping serial send to {port}@{baud}")
        return
    state._tx_queue.put_nowait(SerialTask(str(port), int(baud), data))


def write_parallel(address: int, value, fmt: str = "bytes") -> None:
    """入队并口写入 — 非阻塞，立即返回。

    写入非零值后 I/O 线程会在 5ms 后自动写入零（复位）。

    Args:
        address:  I/O 端口基地址，如 0x378 (LPT1 data port)
        value:   要写入的值（数字 or 字符串，由 fmt 决定编码）
        fmt:     编码格式 — "bytes" → float32 LE 4字节, "string" → UTF-8
    """
    if not state._running:
        print(f"{state._TAG} Not running — dropping parallel write to 0x{address:04X}")
        return
    if state._pp is None:
        print(f"{state._TAG} Parallel not available — dropping write to 0x{address:04X}")
        return
    data = encode(value, fmt)
    state._tx_queue.put_nowait(ParallelTask(int(address), data))


def parallel_ready() -> bool:
    """返回并口（InpOut32 驱动）是否可用。"""
    return state._parallel_available


def is_running() -> bool:
    """返回 I/O 线程是否在运行。"""
    return state._running
