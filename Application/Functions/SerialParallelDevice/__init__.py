"""
SerialParallelDevice — 串口并行 I/O 模块。

职责:
  - 管理所有串口连接的生命周期 (打开 / 关闭)
  - 独立 I/O 线程：消费发送队列，执行实际串口写入
  - 对上层暴露非阻塞 send() 接口

不被 Engine / Editor 反向依赖 — 纯库，由 GameRuntime 和 UI Controller 调用。

用法:
    from Application.Functions.SerialParallelDevice import start, stop, send
    start()
    send("COM2", 9600, b"\\x00\\x00\\x80\\x3f")
    stop()
"""

from __future__ import annotations

import threading
from queue import Queue, Empty
from typing import Optional


# ═══════════════════════════════════════════════════════════════
# 模块级状态
# ═══════════════════════════════════════════════════════════════

_io_thread: Optional[threading.Thread] = None
_tx_queue: Queue = Queue()
_lock = threading.Lock()
_ports: dict[str, object] = {}          # "COM2:9600" → pyserial.Serial
_running: bool = False

_TAG = "[SPD]"


# ═══════════════════════════════════════════════════════════════
# 端口管理 (内部)
# ═══════════════════════════════════════════════════════════════

def _port_key(port: str, baud: int) -> str:
    return f"{port}:{baud}"


def _get_or_open(key: str, port: str, baud: int):
    """获取或打开串口。返回 pyserial.Serial 或 None。"""
    with _lock:
        ser = _ports.get(key)
        if ser is not None:
            try:
                if ser.is_open:
                    return ser
            except Exception:
                pass
            _ports.pop(key, None)

        try:
            import serial
            ser = serial.Serial(port, baud, timeout=0.1)
            _ports[key] = ser
            print(f"{_TAG} Opened {key}")
            return ser
        except Exception as e:
            print(f"{_TAG} Failed to open {key}: {e}")
            return None


def _close_port(key: str) -> None:
    """关闭并移除单个端口。"""
    with _lock:
        ser = _ports.pop(key, None)
        if ser is not None:
            try:
                ser.close()
                print(f"{_TAG} Closed {key}")
            except Exception as e:
                print(f"{_TAG} Error closing {key}: {e}")


def _close_all() -> None:
    """关闭所有端口。"""
    with _lock:
        for key in list(_ports.keys()):
            ser = _ports.pop(key, None)
            if ser is not None:
                try:
                    ser.close()
                except Exception:
                    pass
    _ports.clear()


# ═══════════════════════════════════════════════════════════════
# I/O 线程
# ═══════════════════════════════════════════════════════════════

def _io_loop() -> None:
    """I/O 线程主循环 — 消费发送队列，写入串口。"""
    global _running
    print(f"{_TAG} I/O thread started")
    while _running:
        try:
            port, baud, data = _tx_queue.get(timeout=0.05)
        except Empty:
            continue

        key = _port_key(port, baud)
        ser = _get_or_open(key, port, baud)
        if ser is None:
            print(f"{_TAG} Drop: {key} not available")
            continue

        try:
            ser.write(data)
        except Exception as e:
            print(f"{_TAG} Write error {key}: {e}")
            _close_port(key)
    print(f"{_TAG} I/O thread stopped")


# ═══════════════════════════════════════════════════════════════
# 公开 API
# ═══════════════════════════════════════════════════════════════

def start() -> None:
    """启动 I/O 线程。幂等 — 重复调用无副作用。"""
    global _running, _io_thread
    if _running:
        return
    _running = True
    _io_thread = threading.Thread(target=_io_loop, daemon=True, name="spd-io")
    _io_thread.start()


def stop() -> None:
    """停止 I/O 线程，关闭所有串口。幂等 — 重复调用无副作用。"""
    global _running, _io_thread
    if not _running:
        return
    _running = False

    # 清空队列中未发送的数据
    while not _tx_queue.empty():
        try:
            _tx_queue.get_nowait()
        except Empty:
            break

    # 等待 I/O 线程退出
    if _io_thread is not None and _io_thread.is_alive():
        _io_thread.join(timeout=1.0)
    _io_thread = None

    # 关闭所有串口
    _close_all()


def send(port: str, baud: int, data: bytes) -> None:
    """入队发送 — 非阻塞，立即返回。

    Args:
        port:  串口号，如 "COM2"
        baud:  波特率，如 9600
        data:  要发送的字节数据
    """
    if not _running:
        print(f"{_TAG} Not running — dropping send to {port}@{baud}")
        return
    _tx_queue.put_nowait((str(port), int(baud), data))


def is_running() -> bool:
    """返回 I/O 线程是否在运行。"""
    return _running
