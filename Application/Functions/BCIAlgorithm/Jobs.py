"""
BCIAlgorithm.Jobs — 同步等待式训练任务（线程 + 锁保护的进度/结果槽）。

语义（见 Doc/Dev/bci_algorithm_protocol.md）:
  - worker 线程只写任务槽（进度/结果/错误）— 绝不触碰 ctx/evaluator（自由线程纪律）;
  - 评估器在主 exec 遍历中轮询任务槽: running → 保持 _blocked; done → 取结果并继续下行;
    error → 报错（不重试, 一次错误一次日志）;
  - 干跑（ctx.dry_run）不走线程 — 训练同步执行（确定性）。

本模块只依赖 stdlib（服务/算法两侧可复用）。
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional


class SyncJob:
    """同步等待式任务: 线程跑 fn(set_progress) → 结果/错误进锁保护槽。"""

    def __init__(self, name: str = "job") -> None:
        self.name = name
        self._lock = threading.Lock()
        self.status = "running"      # running | done | error
        self.progress = 0.0          # 0..1
        self.result = None
        self.error = ""
        self.t_started = time.perf_counter()
        self.t_finished: Optional[float] = None

    # ── worker 侧 ──────────────────────────────────────────

    def set_progress(self, p: float) -> None:
        with self._lock:
            self.progress = max(0.0, min(1.0, float(p)))

    def finish(self, result) -> None:
        with self._lock:
            self.result = result
            self.progress = 1.0
            self.status = "done"
            self.t_finished = time.perf_counter()

    def fail(self, error: str) -> None:
        with self._lock:
            self.error = str(error)
            self.status = "error"
            self.t_finished = time.perf_counter()

    # ── 评估器侧 ───────────────────────────────────────────

    def snapshot(self) -> dict:
        """锁保护快照: {status, progress, error, elapsed}。"""
        with self._lock:
            end = self.t_finished if self.t_finished is not None else time.perf_counter()
            return {"status": self.status, "progress": self.progress,
                    "error": self.error, "elapsed": end - self.t_started}

    # ── 启动 ───────────────────────────────────────────────

    @classmethod
    def run_async(cls, fn: Callable, name: str = "job") -> "SyncJob":
        """后台线程执行 fn(job.set_progress)；返回值 finish / 异常 fail。"""
        job = cls(name)

        def _runner() -> None:
            from Application.Core.ThreadRegistry import ThreadRegistry

            _reg = f"bci-{name}"
            ThreadRegistry.register(_reg, owner="SyncJob", expect_hz=0.0,
                                    note="训练任务; 阻塞等待不推进心跳=正常")
            try:
                job.finish(fn(job.set_progress))
            except Exception as e:  # noqa: BLE001 — 任务异常转槽（服务线程绝不崩图）
                job.fail(f"{type(e).__name__}: {e}")
            finally:
                ThreadRegistry.unregister(_reg)

        threading.Thread(target=_runner, name=f"bci-{name}", daemon=True).start()
        return job
