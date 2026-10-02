"""
校验任务服务 — 单活动任务 / worker 线程 / 报告留存。

约定:
  - 同一时刻只跑一个校验任务（忙则拒绝并返回当前任务信息）;
  - 任务在 worker 线程执行（不占用编辑器主线程 / 逻辑线程）;
  - 报告内存留存最近 _MAX_REPORTS 份（按 task_id 递增）;
  - run_validation() 为同步内部实现（UI/MCP/PlayerBootstrap/测试 共用同一逻辑）。
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from datetime import datetime

from .checks import extract_graph_data, static_check_graph
from .dry_run import DEFAULT_DT, DEFAULT_FRAMES, run_dry_run

_MAX_REPORTS = 5


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


def _graph_meta(graph_data: dict) -> dict:
    """图规模 + 内容哈希（agent 追溯 / 报告对比用）。"""
    graph = extract_graph_data(graph_data)
    nodes = graph.get("nodes") or {}
    links = graph.get("links") or {}
    digest = ""
    try:
        payload = json.dumps(graph, sort_keys=True, ensure_ascii=False, default=str)
        digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]
    except Exception:  # noqa: BLE001
        pass
    return {"nodes": len(nodes), "links": len(links), "hash": f"sha1:{digest}" if digest else ""}


def _default_options(options: dict | None) -> dict:
    opts = {"frames": DEFAULT_FRAMES, "dt": DEFAULT_DT, "seed": 0, "verbose": True}
    if options:
        for key in ("frames", "dt", "seed", "verbose"):
            value = options.get(key)
            if value is not None:
                opts[key] = value
    try:
        opts["frames"] = max(0, int(opts["frames"]))
    except (TypeError, ValueError):
        opts["frames"] = DEFAULT_FRAMES
    try:
        opts["seed"] = int(opts["seed"])
    except (TypeError, ValueError):
        opts["seed"] = 0
    try:
        opts["dt"] = float(opts["dt"]) if float(opts["dt"]) > 0 else DEFAULT_DT
    except (TypeError, ValueError):
        opts["dt"] = DEFAULT_DT
    opts["verbose"] = bool(opts["verbose"])
    return opts


def run_validation(
    graph_data: dict,
    options: dict | None = None,
    *,
    progress_cb=None,
    cancel_event: threading.Event | None = None,
    task_id: int | None = None,
) -> dict:
    """同步执行完整校验（静态 + 干跑）→ 统一报告 dict。

    progress_cb: 回调 {"phase": "static"|"dry_run", "progress": 0.0~1.0}
    """
    opts = _default_options(options)
    started_iso = _now_iso()
    t0 = time.perf_counter()

    # ── L1: 静态检查 ──
    if progress_cb is not None:
        progress_cb({"phase": "static", "progress": 0.0})
    static_entries = static_check_graph(graph_data)
    static_errors = [e for e in static_entries if e["level"] == "error"]
    static_warnings = [e for e in static_entries if e["level"] == "warning"]

    # ── L2: 干跑（有静态错误时跳过 — 与离线链路一致） ──
    state = "done"
    runtime: dict
    if static_errors:
        runtime = {
            "skipped": True,
            "reason": "static errors present — dry-run skipped",
            "errors": [],
            "warnings": [],
            "frames_simulated": 0,
            "total_events": 0,
            "events_by_type": {},
            "cancelled": False,
            "killed_sessions": [],
            "log": [],
        }
    else:
        if progress_cb is not None:
            progress_cb({"phase": "dry_run", "progress": 0.1})

        def _prog(frame: int, frames: int) -> None:
            if progress_cb is not None:
                progress_cb({
                    "phase": "dry_run",
                    "progress": 0.1 + 0.9 * (frame / max(1, frames)),
                })

        dr = run_dry_run(
            graph_data,
            frames=opts["frames"],
            dt=opts["dt"],
            seed=opts["seed"],
            progress_cb=_prog,
            cancel_event=cancel_event,
        )
        runtime = {
            "skipped": False,
            "errors": list(dr.get("errors") or []),
            "warnings": [],
            "frames_simulated": int(dr.get("frames_simulated", 0)),
            "total_events": int(dr.get("total_events", 0)),
            "events_by_type": dict(dr.get("events_by_type") or {}),
            "cancelled": bool(dr.get("cancelled", False)),
            "exit_game_frame": dr.get("exit_game_frame"),
            "killed_sessions": list(dr.get("killed_sessions") or []),
            "log": list(dr.get("log") or []),
        }
        if runtime["cancelled"]:
            state = "cancelled"

    errored = bool(static_errors) or bool(runtime.get("errors"))
    if errored and state != "cancelled":
        state = "done"  # 校验本身完成（ok=False 表达失败）；state 只表达任务生命周期

    report: dict = {
        "task_id": task_id,
        "state": state,
        "ok": (state == "done") and (not errored),
        "options": {
            "frames": opts["frames"],
            "dt": round(opts["dt"], 6),
            "seed": opts["seed"],
            "verbose": opts["verbose"],
        },
        "graph": _graph_meta(graph_data),
        "static": {
            "errors": static_errors,
            "warnings": static_warnings,
        },
        "runtime": runtime,
        "counts": {
            "errors": len(static_errors) + len(runtime.get("errors") or []),
            "warnings": len(static_warnings),
            "log_lines": len(runtime.get("log") or []),
        },
        "timing": {
            "started_iso": started_iso,
            "finished_iso": _now_iso(),
            "duration_ms": round((time.perf_counter() - t0) * 1000.0, 1),
        },
        "log": runtime.get("log") or [],
    }
    return report


class ValidationService:
    """校验任务服务（类级单例通过 get_service() 获取; 线程安全）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._seq = 0
        self._task: dict | None = None          # 当前/最近任务: {task_id, state, phase, progress, started_iso}
        self._reports: "OrderedDict[int, dict]" = OrderedDict()
        self._cancel: threading.Event | None = None
        self._thread: threading.Thread | None = None

    # ── 查询 ────────────────────────────────────────────────

    def state(self, task_id: int | None = None) -> dict:
        """当前任务状态（task_id=None → 最新任务）。"""
        with self._lock:
            task = self._task
            if task is None:
                return {"task_id": None, "state": "idle", "phase": "", "progress": 0.0}
            if task_id is not None and int(task_id) != task["task_id"]:
                report = self._reports.get(int(task_id))
                if report is not None:
                    return {
                        "task_id": report["task_id"],
                        "state": report["state"],
                        "phase": "finished",
                        "progress": 1.0,
                    }
                return {"task_id": int(task_id), "state": "unknown", "phase": "", "progress": 0.0}
            return {
                "task_id": task["task_id"],
                "state": task["state"],
                "phase": task.get("phase", ""),
                "progress": round(float(task.get("progress", 0.0)), 4),
            }

    def report(self, task_id: int | None = None) -> dict | None:
        """已完成的报告（task_id=None → 最新一份）。"""
        with self._lock:
            if task_id is None:
                if not self._reports:
                    return None
                return next(reversed(self._reports.values()))
            return self._reports.get(int(task_id))

    def latest_task_id(self) -> int | None:
        with self._lock:
            if self._task is not None:
                return int(self._task["task_id"])
            if self._reports:
                return int(next(reversed(self._reports)))
            return None

    # ── 控制 ────────────────────────────────────────────────

    def start(self, graph_data: dict, options: dict | None = None) -> dict:
        """启动一次校验任务（worker 线程）。

        Returns: {"started": bool, "busy": bool, "task_id", "state", "note"?}
        """
        with self._lock:
            if self._task is not None and self._task["state"] == "running":
                return {
                    "started": False,
                    "busy": True,
                    "task_id": self._task["task_id"],
                    "state": "running",
                    "note": "a validation task is already running — cancel it first",
                }
            self._seq += 1
            task_id = self._seq
            cancel = threading.Event()
            self._cancel = cancel
            self._task = {
                "task_id": task_id,
                "state": "running",
                "phase": "static",
                "progress": 0.0,
                "started_iso": _now_iso(),
            }
            thread = threading.Thread(
                target=self._work,
                args=(task_id, graph_data, options, cancel),
                name=f"GraphValidation#{task_id}",
                daemon=True,
            )
            self._thread = thread
            thread.start()
        return {"started": True, "busy": False, "task_id": task_id, "state": "running"}

    def cancel(self, task_id: int | None = None) -> dict:
        """请求取消当前任务（帧间生效, 干跑收尾后进入 cancelled 状态）。"""
        with self._lock:
            task = self._task
            if task is None or task["state"] != "running":
                return {"cancelled": False, "note": "no running task"}
            if task_id is not None and int(task_id) != task["task_id"]:
                return {"cancelled": False, "note": f"task {task_id} is not the running task"}
            cancel = self._cancel
        if cancel is not None:
            cancel.set()
        return {"cancelled": True, "task_id": task["task_id"]}

    # ── worker ──────────────────────────────────────────────

    def _update_progress(self, info: dict) -> None:
        with self._lock:
            if self._task is not None and self._task["state"] == "running":
                self._task["phase"] = str(info.get("phase", self._task.get("phase", "")))
                self._task["progress"] = float(info.get("progress", self._task.get("progress", 0.0)))

    def _work(self, task_id: int, graph_data: dict, options: dict | None, cancel: threading.Event) -> None:
        try:
            report = run_validation(
                graph_data,
                options,
                progress_cb=self._update_progress,
                cancel_event=cancel,
                task_id=task_id,
            )
            state = report["state"]
        except Exception as e:  # noqa: BLE001 — worker 崩溃收敛为 failed 报告
            import traceback

            report = {
                "task_id": task_id,
                "state": "failed",
                "ok": False,
                "error": f"{type(e).__name__}: {e}",
                "traceback": traceback.format_exc(),
                "counts": {"errors": 1, "warnings": 0, "log_lines": 0},
            }
            state = "failed"
        with self._lock:
            self._reports[task_id] = report
            while len(self._reports) > _MAX_REPORTS:
                self._reports.popitem(last=False)
            if self._task is not None and self._task["task_id"] == task_id:
                self._task["state"] = state
                self._task["progress"] = 1.0
                self._task["phase"] = "finished"


_SERVICE = ValidationService()


def get_service() -> ValidationService:
    """全局校验服务单例。"""
    return _SERVICE
