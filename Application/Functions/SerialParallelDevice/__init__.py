"""
SerialParallelDevice — 串口 + 并口 I/O 模块。

职责:
  - 管理所有串口连接的生命周期 (打开 / 关闭)
  - 管理并口（InpOut32 驱动）的初始化和写入
  - 独立 I/O 线程：消费发送队列，执行实际串口/并口写入
  - 非阻塞内置计时器：并口写入非零值 5ms 后自动复位为零
  - 对上层暴露非阻塞 send() / write_parallel() 接口

不被 Engine / Editor 反向依赖 — 纯库，由 GameRuntime 和 UI Controller 调用。

子模块:
  - tasks             : SerialTask / ParallelTask 数据类
  - state             : 模块级共享状态（驱动引用、端口字典、队列）
  - serial_manager    : 串口打开/关闭/生命周期
  - parallel_manager  : 并口写入 + 5ms 自动复位调度
  - io_thread         : I/O 线程主循环 + 任务分发
  - api               : start / stop / send / write_parallel 公开 API
  - test_hooks        : 测试注入钩子
  - protocol          : 数据编码/解码

用法:
    from Application.Functions.SerialParallelDevice import start, stop, send, write_parallel
    start()
    send("COM2", 9600, b"\\x00\\x00\\x80\\x3f")
    write_parallel(0x378, 1.0, "bytes")
    stop()
"""

from __future__ import annotations

# ── 公开 API ────────────────────────────────────────────────
from .api import (
    start,
    stop,
    send,
    write_parallel,
    parallel_ready,
    is_running,
)

# ── 任务类型（供高级用户直接构造） ──────────────────────────
from .tasks import SerialTask, ParallelTask

# ── 向后兼容: 测试钩子 (旧名下划线前缀) ─────────────────────
from .test_hooks import (
    get_reset_schedule       as _test_get_reset_schedule,
    clear_reset_schedule     as _test_clear_reset_schedule,
    inject_parallel          as _test_inject_parallel,
    get_parallel_driver      as _test_get_parallel_driver,
)

__all__ = [
    "start",
    "stop",
    "send",
    "write_parallel",
    "parallel_ready",
    "is_running",
    "SerialTask",
    "ParallelTask",
]
