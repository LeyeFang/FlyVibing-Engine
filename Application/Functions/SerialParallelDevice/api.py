"""SerialParallelDevice — 公开 API：启动/停止/发送/写入。

所有权模型（单线程 + 租约，见 state.py）:
  - 硬件只有一套 → **永远只有一条 spd-io 线程**;
  - `start(owner)` / `stop(owner)` 操作的是**租约**，不是线程;
  - `owner="runtime"`（GameRuntime / 成品）优先; PIE 运行期间编辑器释放租约不会停线程（交权）;
  - `owner="editor"`（编辑器面板手动调试）按需持租约，PIE 停止后线程仍存活。
"""

from __future__ import annotations

import threading
from queue import Empty

from . import state
from .tasks import SerialTask, ParallelTask
from .serial_manager import close_all
from .io_thread import io_loop
from .protocol import encode


# 已知并口地址 — 启动时统一复位到 0
_KNOWN_PARALLEL_ADDRS = (0x3FF8, 0x3FF0, 0x3FE8)


class DeviceNotReady(RuntimeError):
    """I/O 线程未运行 / 并口驱动不可用 — 严格模式下抛出（面板/op 显示给用户）。"""


def _norm_owner(owner: str) -> str:
    """归一 owner 名（未知值归入 editor — 交互方默认是编辑器）。"""
    who = str(owner or "").strip().lower()
    return "runtime" if who == "runtime" else "editor"


def start(owner: str = "editor") -> None:
    """获取 I/O 线程租约（幂等）— 线程不存在时顺便拉起。

    启动后立即复位所有已知并口地址到 0，确保端口处于已知安全状态，
    避免上次运行残留的非零值被误认为有效 trigger。

    Args:
        owner: "runtime"（GameRuntime/成品）或 "editor"（编辑器面板/ops）。
               两者可同时持有; "runtime" 优先（PIE 运行期间编辑器无法停掉线程）。
    """
    who = _norm_owner(owner)
    with state._lock:
        state._leases.add(who)
        # runtime 优先: 运行中即接管报告权
        if "runtime" in state._leases:
            state._owner = "runtime"
        else:
            state._owner = "editor"
    if state._running:
        return
    state._running = True
    state._io_thread = threading.Thread(
        target=io_loop, daemon=True, name="spd-io"
    )
    state._io_thread.start()

    # ★ 启动时复位所有已知并口地址到 0
    if state._pp is not None:
        for addr in _KNOWN_PARALLEL_ADDRS:
            state._tx_queue.put_nowait(ParallelTask(addr, b'\x00'))


def stop(owner: str = "editor") -> None:
    """释放 I/O 线程租约（幂等）。

    仅当**没有任何租约**时才真正停线程、清队列、关串口:
      - PIE 停止时调用 `stop("runtime")`; 编辑器仍持租约 → 线程继续运行（面板调试不断）。
      - 面板关闭/扩展停用时调用 `stop("editor")`; runtime 仍持租约 → **不停线程**（交权）。

    Args:
        owner: 释放谁持有的租约（"runtime" / "editor"）。
    """
    who = _norm_owner(owner)
    with state._lock:
        state._leases.discard(who)
        if state._leases:
            state._owner = "runtime" if "runtime" in state._leases else "editor"
            return                                  # 另一个 owner 仍持有 → 不停
        state._owner = "none"
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


def stop_all() -> None:
    """释放全部租约（进程退出/关工程时使用）— 确保端口一定被关闭。"""
    with state._lock:
        state._leases.clear()
    stop("editor")


def send(port: str, baud: int, data: bytes, *, strict: bool = False) -> bool:
    """入队串口发送 — 非阻塞，立即返回。

    Args:
        port:  串口号（`"COM2"`）或**逻辑设备名**（`"@mibox"` — 机器侧绑定, 见协议 §10）
        baud:  波特率，如 9600
        data:  要发送的字节数据
        strict: True 时线程未运行抛 `DeviceNotReady`（面板/op 用）;
                False（默认）时仅打印并返回 False（节点评估器路径）。

    Returns:
        True = 已入队; False = I/O 线程未运行。

    Raises:
        DeviceUnresolved / ValueError — `@name` 未绑定或端口为空（解析在入队前完成, 便于
        调用方（节点/面板/op）拿到**显式错误**而不是静默发错端口）。
    """
    from .serial_manager import resolve_port
    port = resolve_port(port)           # @name → 物理端口（未绑定 → 显式抛错）
    if not state._running:
        msg = f"I/O thread not running — serial send to {port}@{baud} dropped"
        if strict:
            raise DeviceNotReady(msg)
        print(f"{state._TAG} {msg}")
        return False
    state._tx_queue.put_nowait(SerialTask(str(port), int(baud), data))
    return True


def write_parallel(address: int, value, fmt: str = "bytes", *,
                   strict: bool = False) -> bool:
    """入队并口写入 — 非阻塞，立即返回。

    写入非零值后 I/O 线程会在 `state._reset_delay`（默认 5ms）后自动写入零（复位）。

    Args:
        address:  I/O 端口基地址，如 0x378 (LPT1 data port)
        value:    要写入的值（数字 or 字符串，由 fmt 决定编码）
        fmt:      编码格式
                    "byte"   → uint8 单字节 (1–255) — **设备触发码用这个**
                    "bytes"  → float32 LE 4 字节（占 base..base+3，注意 LPT 控制/状态寄存器）
                    "string" → UTF-8 + "\n"
        strict:   True 时失败抛 `DeviceNotReady`（面板/op 用 — 禁止静默丢弃）;
                  False（默认）时仅打印并返回 False（节点评估器路径 — 不打断图执行）。

    Returns:
        True = 已入队; False = 未入队（线程未运行 / 驱动不可用）。
    """
    if not state._running:
        msg = f"I/O thread not running — parallel write to 0x{address:04X} dropped"
        if strict:
            raise DeviceNotReady(msg)
        print(f"{state._TAG} {msg}")
        return False
    if state._pp is None:
        msg = f"parallel driver (InpOut) unavailable — write to 0x{address:04X} dropped"
        if strict:
            raise DeviceNotReady(msg)
        print(f"{state._TAG} {msg}")
        return False
    data = encode(value, fmt)
    state._tx_queue.put_nowait(ParallelTask(int(address), data))
    return True


def set_reset_delay(ms: float) -> float:
    """设置并口自动复位延迟（毫秒; 0 < ms <= 1000）。返回生效值（秒）。

    写入非零值后 `ms` 毫秒自动清零 — 触发脉冲宽度由此决定。
    延迟只在 spd-io 线程内执行，所以线程不在 = 不会复位。
    """
    seconds = max(0.001, min(1.0, float(ms) / 1000.0))
    state._reset_delay = seconds
    return seconds


def reset_delay_ms() -> float:
    """当前并口自动复位延迟（毫秒）。"""
    return round(float(state._reset_delay) * 1000.0, 3)


def io_owner() -> str:
    """当前 I/O 线程 owner: "runtime"（PIE/成品）| "editor"（面板）| "none"。"""
    with state._lock:
        return state._owner if state._leases else "none"

def parallel_ready() -> bool:
    """返回并口（InpOut32 驱动）是否可用。"""
    return state._parallel_available


def is_running() -> bool:
    """返回 I/O 线程是否在运行。"""
    return state._running
