"""SerialParallelDevice — 模块级共享状态。

所有 I/O 线程相关状态集中管理于此，避免循环导入。
"""

from __future__ import annotations

import threading
from collections import deque
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

# ── I/O 线程所有权租约 (★ 单线程 + 多租约; 不是每个 owner 一条线程) ──
#
# 硬件只有一套（同一个 InpOut 驱动、同一批串口句柄、同一份复位调度），
# 因此**永远只有一条 spd-io 线程**; 谁需要它谁持租约:
#   "runtime" — GameRuntime (PIE / 成品) 启动即持租约, 优先级最高
#   "editor"  — 编辑器面板 (手动调试: watch / send / write_parallel) 按需持租约
# 线程存活 = 租约集合非空; 任一 owner 释放只移除自己的租约。
# PIE 运行期间编辑器释放租约不会停线程（交权给 runtime）。
_leases: set[str] = set()
_LEASE_OWNERS = ("editor", "runtime")
_owner: str = "none"                    # 报告用当前优先 owner: "runtime" | "editor" | "none"

# 并口自动复位调度: [(deadline, address, byte_count), ...]
_reset_schedule: list[tuple[float, int, int]] = []

# 并口写入后自动复位延迟（秒）— 由 api.set_reset_delay() 修改; 面板可调
_reset_delay: float = 0.005

# ── 监视器状态（扩展面板消费 — 见 monitor.py） ───────────────
# io_thread 单线程写; 快照读取由 _lock 保护。
_monitor: dict = {"active": False, "port": "", "baud": 115200,
                  "opened": False, "next_retry": 0.0}
_events: deque = deque(maxlen=500)       # (perf_ts, kind, bytes, note)
_stats: dict = {"tx_count": 0, "tx_bytes": 0, "rx_count": 0, "rx_bytes": 0,
                "parallel_writes": 0, "last_error": ""}

_TAG = "[SPD]"
