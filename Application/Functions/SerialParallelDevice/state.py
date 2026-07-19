"""SerialParallelDevice — 模块级共享状态。

所有 I/O 线程相关状态集中管理于此，避免循环导入。
"""

from __future__ import annotations

import threading
from queue import Queue
from typing import Optional


# ── 并口驱动 (Windows-only, 优雅降级) ────────────────────────

try:
    from . import _inpout as _pp
    _parallel_available = _pp.driver_open()
except (ImportError, OSError):
    _pp = None
    _parallel_available = False


# ── 运行时状态 ───────────────────────────────────────────────

_io_thread: Optional[threading.Thread] = None
_tx_queue: Queue = Queue()
_lock = threading.Lock()
_ports: dict[str, object] = {}          # "COM2:9600" → pyserial.Serial
_running: bool = False

# 并口自动复位调度: [(deadline, address, byte_count), ...]
_reset_schedule: list[tuple[float, int, int]] = []

_TAG = "[SPD]"
