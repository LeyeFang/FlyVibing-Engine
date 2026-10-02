"""
节点图干跑 — L2 层（fake-time 确定性模拟）。

内化自 Utils/User/NodeEditor/node_graph_validator.dry_run_simulation，并升级:
  - 无 print 副作用 — 全部事件走向结构化日志 (收集器)
  - 确定性: 固定 dt (默认 1/60) + 固定随机种子 (默认 0, 重置 evaluators.math 全局 RNG)
  - 取消支持: cancel_event 帧间检查
  - 会话隔离: 干跑中的设备会话 (Gtec/SigGen 等) 统一 "dryrun#" 前缀, 结束后自动清理
  - 进度回调: progress_cb(frame, frames)
"""

from __future__ import annotations

import threading
from collections import Counter
from typing import Any, Callable

from ..canvas import NodeCanvas
from ..evaluator_engine import ExecutionContext, GraphEvaluator
from ..node_types import _TYPES
from .checks import extract_graph_data

DRY_RUN_SESSION_PREFIX = "dryrun#"
DEFAULT_FRAMES = 360          # 6s @ 60fps
DEFAULT_DT = 1.0 / 60.0


class _LogCollector:
    """节点事件收集器 — 替代 DryRunLogger（结构化, 无 print）。"""

    def __init__(self) -> None:
        self.entries: list[dict] = []
        self._frame = 0

    def set_frame(self, frame: int) -> None:
        self._frame = frame

    def __call__(self, node_id: int, node_type: str, action: str, detail: str) -> None:
        self.entries.append({
            "frame": self._frame,
            "node_id": int(node_id),
            "node_type": node_type,
            "action": action,
            "detail": detail,
        })


def _seed_rng(seed: int) -> None:
    """以确定种子重置节点图全局 RNG（evaluators.math）。"""
    try:
        from ..evaluators.math import seed_global_rng

        seed_global_rng(int(seed))
    except Exception:  # noqa: BLE001 — 种子重置失败不阻塞干跑
        pass


def _cleanup_dry_sessions() -> list[str]:
    """清理干跑命名空间下的残留设备会话（真实会话不受影响）。"""
    removed: list[str] = []
    try:
        from Application.Functions.EEGDevice import kill_device, list_sessions

        for name in list_sessions():
            if name.startswith(DRY_RUN_SESSION_PREFIX):
                kill_device(name)
                removed.append(name)
    except Exception:  # noqa: BLE001 — 设备层不可用时忽略
        pass
    return removed


def run_dry_run(
    graph_data: dict,
    *,
    frames: int = DEFAULT_FRAMES,
    dt: float = DEFAULT_DT,
    seed: int = 0,
    progress_cb: Callable[[int, int], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> dict:
    """执行一次干跑模拟（同步；worker 线程由调用方决定）。

    Args:
        graph_data: 裸 graph dict / scene JSON（extract_graph_data 兼容三种格式）。
        frames:     模拟帧数（fake-time）。
        dt:         每帧时间步长（秒）。
        seed:       随机种子（干跑开始前重置全局 RNG）。
        progress_cb: 每 10 帧 + 结束时回调 (frame, frames)。
        cancel_event: 置位后帧间退出。

    Returns:
        {
          "frames_simulated": int,
          "total_events": int,
          "events_by_type": dict,
          "errors": list[str],
          "log": list[dict],          # 结构化事件条目
          "cancelled": bool,
          "exit_game_frame": int | None,
          "killed_sessions": list[str],
        }
    """
    out: dict = {
        "frames_simulated": 0,
        "total_events": 0,
        "events_by_type": {},
        "errors": [],
        "log": [],
        "cancelled": False,
        "exit_game_frame": None,
        "killed_sessions": [],
    }

    graph = extract_graph_data(graph_data)
    if not graph.get("nodes"):
        out["errors"].append("No 'nodes' found in graph data")
        return out

    try:
        canvas = NodeCanvas.from_dict(graph)
    except Exception as e:  # noqa: BLE001
        out["errors"].append(f"Failed to deserialize NodeCanvas: {e}")
        return out

    evaluator = GraphEvaluator(canvas, _TYPES)
    ctx = ExecutionContext()
    ctx.dry_run = True
    collector = _LogCollector()
    ctx.log = collector

    _seed_rng(seed)
    frame_count = max(0, int(frames))
    step = float(dt) if dt and float(dt) > 0 else DEFAULT_DT

    def _trigger(event_type: str) -> Exception | None:
        try:
            evaluator.trigger(event_type, ctx)
            return None
        except Exception as e:  # noqa: BLE001 — 单事件失败记录后继续收尾
            return e

    try:
        # ── OnGameStart ──
        ctx.elapsed_time = 0.0
        ctx.delta_time = 0.0
        err = _trigger("OnGameStart")
        if err is not None:
            out["errors"].append(f"OnGameStart error: {type(err).__name__}: {err}")

        # ── 逐帧 ──
        completed = 0
        scan_from = 0
        exit_frame: int | None = None
        for frame in range(1, frame_count + 1):
            if cancel_event is not None and cancel_event.is_set():
                out["cancelled"] = True
                break

            ctx.elapsed_time += step
            ctx.delta_time = step
            collector.set_frame(frame)

            err = _trigger("OnFrameUpdate")
            if err is not None:
                out["errors"].append(f"Frame {frame} error: {type(err).__name__}: {err}")
                break

            completed = frame

            # ExitGame 检测（增量扫描: 只看新追加的条目）
            for i in range(scan_from, len(collector.entries)):
                ent = collector.entries[i]
                if ent["action"] == "stop" and ent["node_type"] == "ExitGame":
                    exit_frame = frame
                    break
            scan_from = len(collector.entries)
            if exit_frame is not None:
                break

            if progress_cb is not None and (frame % 10 == 0 or frame == frame_count):
                try:
                    progress_cb(frame, frame_count)
                except Exception:  # noqa: BLE001 — 进度回调失败不影响干跑
                    pass

        out["frames_simulated"] = completed
        out["exit_game_frame"] = exit_frame

        # ── OnGameStop（含被取消/失败路径 — 清理语义与真实运行一致） ──
        err = _trigger("OnGameStop")
        if err is not None:
            out["errors"].append(f"OnGameStop error: {type(err).__name__}: {err}")

    finally:
        out["killed_sessions"] = _cleanup_dry_sessions()

    out["total_events"] = len(collector.entries)
    out["events_by_type"] = dict(Counter(e["node_type"] for e in collector.entries))
    out["log"] = collector.entries
    return out
