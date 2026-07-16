"""
SerialParallelDevice — 串口 + 并口 I/O 模块。

职责:
  - 管理所有串口连接的生命周期 (打开 / 关闭)
  - 管理并口（InpOut32 驱动）的初始化和写入
  - 独立 I/O 线程：消费发送队列，执行实际串口/并口写入
  - 非阻塞内置计时器：并口写入非零值 5ms 后自动复位为零
  - 对上层暴露非阻塞 send() / write_parallel() 接口

不被 Engine / Editor 反向依赖 — 纯库，由 GameRuntime 和 UI Controller 调用。

用法:
    from Application.Functions.SerialParallelDevice import start, stop, send, write_parallel
    start()
    send("COM2", 9600, b"\\x00\\x00\\x80\\x3f")
    write_parallel(0x378, 1.0, "bytes")
    stop()
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from queue import Queue, Empty
from typing import Optional

from .protocol import encode

# ═══════════════════════════════════════════════════════════════
# 并口驱动 (Windows-only, 优雅降级)
# ═══════════════════════════════════════════════════════════════

try:
    from . import _inpout as _pp
    _parallel_available = _pp.driver_open()
except (ImportError, OSError) as e:
    _pp = None
    _parallel_available = False


# ═══════════════════════════════════════════════════════════════
# 模块级状态
# ═══════════════════════════════════════════════════════════════

_io_thread: Optional[threading.Thread] = None
_tx_queue: Queue = Queue()
_lock = threading.Lock()
_ports: dict[str, object] = {}          # "COM2:9600" → pyserial.Serial
_running: bool = False

# 并口自动复位调度: [(deadline, address, byte_count), ...]
_reset_schedule: list[tuple[float, int, int]] = []

_TAG = "[SPD]"


# ═══════════════════════════════════════════════════════════════
# 任务类型
# ═══════════════════════════════════════════════════════════════

@dataclass
class SerialTask:
    """串口发送任务。"""
    port: str
    baud: int
    data: bytes


@dataclass
class ParallelTask:
    """并口写入任务。"""
    address: int        # I/O 端口基地址 (如 0x378)
    data: bytes         # 已编码的字节


# ═══════════════════════════════════════════════════════════════
# 串口管理 (内部)
# ═══════════════════════════════════════════════════════════════

def _port_key(port: str, baud: int) -> str:
    return f"{port}:{baud}"


def _get_or_open_serial(key: str, port: str, baud: int):
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
    """I/O 线程主循环 — 统一消费串口和并口任务。

    内置非阻塞计时器: 并口写入后 5ms 自动复位为零。
    通过动态 timeout 实现精确唤醒，不阻塞其他 I/O。
    """
    global _running, _reset_schedule
    print(f"{_TAG} I/O thread started")
    while _running:
        now = time.perf_counter()

        # ── 处理到期的并口复位 ──
        _process_resets(now)

        # ── 计算下一次唤醒的超时 ──
        timeout = _next_timeout(now)

        # ── 等待任务 ──
        try:
            task = _tx_queue.get(timeout=timeout)
        except Empty:
            continue

        # ── 按类型分发 ──
        if isinstance(task, SerialTask):
            _handle_serial(task)
        elif isinstance(task, ParallelTask):
            _handle_parallel(task)

    # 线程退出前处理所有待复位
    _process_resets(time.perf_counter() + 999.0)
    print(f"{_TAG} I/O thread stopped")


# ── 并口复位 ────────────────────────────────────────────────

def _process_resets(now: float) -> None:
    """处理所有到期的并口复位（写入全零）。"""
    global _reset_schedule
    remaining: list[tuple[float, int, int]] = []
    for deadline, addr, count in _reset_schedule:
        if now >= deadline:
            _parallel_write_zero(addr, count)
        else:
            remaining.append((deadline, addr, count))
    _reset_schedule = remaining


def _next_timeout(now: float) -> float:
    """计算下次循环超时（秒）。

    若有待复位任务，返回距离最近截止时间的时间；
    否则返回默认的 50ms 轮询间隔。
    """
    if not _reset_schedule:
        return 0.05
    next_deadline = min(item[0] for item in _reset_schedule)
    return max(0.0, next_deadline - now)


def _parallel_write_zero(addr: int, count: int) -> None:
    """向并口地址连续写入 count 个零字节。"""
    if _pp is None:
        return
    for offset in range(count):
        try:
            _pp.out8(addr + offset, 0)
        except Exception as e:
            print(f"{_TAG} Parallel reset error @ 0x{addr + offset:04X}: {e}")
            break


# ── 任务处理 ────────────────────────────────────────────────

def _handle_serial(task: SerialTask) -> None:
    """处理串口发送任务。"""
    key = _port_key(task.port, task.baud)
    ser = _get_or_open_serial(key, task.port, task.baud)
    if ser is None:
        print(f"{_TAG} Drop serial: {key} not available")
        return
    try:
        ser.write(task.data)
    except Exception as e:
        print(f"{_TAG} Serial write error {key}: {e}")
        _close_port(key)


def _handle_parallel(task: ParallelTask) -> None:
    """处理并口写入任务，非零数据自动调度 5ms 复位。"""
    if _pp is None:
        print(f"{_TAG} Drop parallel: InpOut driver not available")
        return

    has_nonzero = any(b != 0 for b in task.data)

    for offset, byte in enumerate(task.data):
        try:
            _pp.out8(task.address + offset, byte)
        except Exception as e:
            print(f"{_TAG} Parallel write error @ 0x{task.address + offset:04X}: {e}")
            break

    if has_nonzero:
        _reset_schedule.append(
            (time.perf_counter() + 0.005, task.address, len(task.data))
        )


# ═══════════════════════════════════════════════════════════════
# 测试钩子 (仅测试用，非公开 API)
# ═══════════════════════════════════════════════════════════════

def _test_get_reset_schedule() -> list[tuple[float, int, int]]:
    """[测试] 返回待复位调度的快照副本。"""
    return list(_reset_schedule)


def _test_clear_reset_schedule() -> None:
    """[测试] 清空待复位调度。"""
    global _reset_schedule
    _reset_schedule.clear()


def _test_inject_parallel(mock) -> None:
    """[测试] 注入 mock 并口驱动，替代真实 _pp。传 None 恢复为 None。"""
    global _pp, _parallel_available
    _pp = mock
    _parallel_available = mock is not None


def _test_get_parallel_driver():
    """[测试] 返回当前 _pp 引用。"""
    return _pp


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
    """停止 I/O 线程，关闭所有串口。幂等 — 重复调用无副作用。

    退出前会处理所有待复位，确保并口回到零状态。
    """
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

    # 等待 I/O 线程退出（线程退出前会自动处理待复位）
    if _io_thread is not None and _io_thread.is_alive():
        _io_thread.join(timeout=2.0)
    _io_thread = None

    # 关闭所有串口
    _close_all()


def send(port: str, baud: int, data: bytes) -> None:
    """入队串口发送 — 非阻塞，立即返回。

    Args:
        port:  串口号，如 "COM2"
        baud:  波特率，如 9600
        data:  要发送的字节数据
    """
    if not _running:
        print(f"{_TAG} Not running — dropping serial send to {port}@{baud}")
        return
    _tx_queue.put_nowait(SerialTask(str(port), int(baud), data))


def write_parallel(address: int, value, fmt: str = "bytes") -> None:
    """入队并口写入 — 非阻塞，立即返回。

    写入非零值后 I/O 线程会在 5ms 后自动写入零（复位）。

    Args:
        address:  I/O 端口基地址，如 0x378 (LPT1 data port)
        value:   要写入的值（数字 or 字符串，由 fmt 决定编码）
        fmt:     编码格式 — "bytes" → float32 LE 4字节, "string" → UTF-8
    """
    if not _running:
        print(f"{_TAG} Not running — dropping parallel write to 0x{address:04X}")
        return
    if _pp is None:
        print(f"{_TAG} Parallel not available — dropping write to 0x{address:04X}")
        return
    data = encode(value, fmt)
    _tx_queue.put_nowait(ParallelTask(int(address), data))


def parallel_ready() -> bool:
    """返回并口（InpOut32 驱动）是否可用。"""
    return _parallel_available


def is_running() -> bool:
    """返回 I/O 线程是否在运行。"""
    return _running
