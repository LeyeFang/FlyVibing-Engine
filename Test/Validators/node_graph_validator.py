"""
Node Graph Validator — 无需完整引擎运行即可验证场景 JSON 中节点图的正确性。

两层验证:
  L1 (静态):  JSON 结构检查 — pin_ids 完整性、连线合法性、重复检测
  L2 (干跑):  模拟 N 帧执行 — 打印执行流追踪，跳过所有副作用

用法:
  python -m Test.Validators.node_graph_validator <scene_path> [--frames N] [--verbose]

示例:
  # 仅静态检查
  python -m Test.Validators.node_graph_validator Test/TestProject/MI.scene

  # 静态检查 + 干跑 120 帧 (MI 实验: 60 trials × 2s)
  python -m Test.Validators.node_graph_validator Test/TestProject/MI.scene --frames 120

  # 详细模式 — 逐帧打印每个节点的 pin 值
  python -m Test.Validators.node_graph_validator Test/TestProject/MI.scene --frames 10 --verbose
"""

from __future__ import annotations

import json
import sys
import os

# ── 确保项目根在 sys.path ──
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


def _extract_graph_data(scene_data: dict) -> dict:
    """从 scene JSON 中提取 node_graph 部分。

    支持三种格式:
      1. { "scene": { "node_graph": { "nodes": ..., "links": ... } } }  ← 标准 .scene 文件
      2. { "nodes": ..., "links": ... }                                    ← 裸 graph JSON
      3. { "graph": { "nodes": ..., "links": ... } }                       ← 旧格式
    """
    # 格式 1: scene.node_graph
    scene = scene_data.get("scene", {})
    if isinstance(scene, dict):
        ng = scene.get("node_graph")
        if isinstance(ng, dict) and "nodes" in ng:
            return ng

    # 格式 3: graph
    graph = scene_data.get("graph")
    if isinstance(graph, dict) and "nodes" in graph:
        return graph

    # 格式 2: 裸 graph
    if "nodes" in scene_data:
        return scene_data

    return {}


def validate_static(scene_data: dict) -> list[str]:
    """L1: 静态结构校验 — 返回错误列表 (空列表 = 通过)。"""
    from Application.Editor.UI.controllers.node_editor.node_types import _TYPES

    errors: list[str] = []
    graph = _extract_graph_data(scene_data)
    nodes: dict[str, dict] = graph.get("nodes", {})
    links: dict[str, dict] = graph.get("links", {})

    if not nodes:
        errors.append("No nodes found in graph data")
        return errors

    # ── 收集所有 pin_id → (node_id, pin_name, direction) 映射 ──
    pin_map: dict[int, tuple[str, str, str]] = {}  # pin_id → (nid_str, pin_name, direction)
    all_pin_ids: set[int] = set()

    for nid_str, nd in nodes.items():
        node_type = nd.get("node_type", "")
        if node_type not in _TYPES:
            errors.append(f"Node {nid_str}: unknown type '{node_type}'")
            continue

        type_def = _TYPES[node_type]
        node_pin_ids: dict[str, int] = nd.get("pin_ids", {})

        # 1. 检查必需 pin 是否存在
        for pin_def in type_def.pins:
            if pin_def.name not in node_pin_ids:
                errors.append(
                    f"Node {nid_str}<{node_type}>: missing pin '{pin_def.name}' "
                    f"({pin_def.direction}, {pin_def.kind})"
                )

        # 2. 收集 pin 映射
        for pin_name, pin_id in node_pin_ids.items():
            pid = int(pin_id)
            if pid in all_pin_ids:
                # 找到冲突来源
                for existing_nid, existing_pname, _ in [
                    (n, p, d) for p_id, (n, p, d) in pin_map.items() if p_id == pid
                ]:
                    errors.append(
                        f"Pin ID collision: {pid} used by "
                        f"Node {nid_str}.{pin_name} and Node {existing_nid}.{existing_pname}"
                    )
            all_pin_ids.add(pid)
            # 查找方向
            direction = "unknown"
            for pin_def in type_def.pins:
                if pin_def.name == pin_name:
                    direction = pin_def.direction
                    break
            pin_map[pid] = (nid_str, pin_name, direction)

    # 3. 连线检查
    link_set: set[tuple[int, int]] = set()
    for lid_str, ld in links.items():
        from_pin = int(ld["from_pin"])
        to_pin = int(ld["to_pin"])

        if from_pin not in pin_map:
            errors.append(f"Link {lid_str}: from_pin={from_pin} not found in any node")
        if to_pin not in pin_map:
            errors.append(f"Link {lid_str}: to_pin={to_pin} not found in any node")

        # 方向检查: from 应为 output, to 应为 input
        if from_pin in pin_map and to_pin in pin_map:
            _, _, from_dir = pin_map[from_pin]
            _, _, to_dir = pin_map[to_pin]
            if from_dir == "input":
                errors.append(
                    f"Link {lid_str}: from_pin={from_pin} is input (should be output)"
                )
            if to_dir == "output":
                errors.append(
                    f"Link {lid_str}: to_pin={to_pin} is output (should be input)"
                )

        # 重复连线
        pair = (from_pin, to_pin)
        if pair in link_set:
            errors.append(f"Link {lid_str}: duplicate connection {from_pin}→{to_pin}")
        link_set.add(pair)

    # 4. 孤立节点检查 (跳过事件节点)
    event_types = {"OnGameStart", "OnFrameUpdate", "OnGameStop"}
    connected_pins: set[int] = set()
    for ld in links.values():
        connected_pins.add(int(ld["from_pin"]))
        connected_pins.add(int(ld["to_pin"]))

    for nid_str, nd in nodes.items():
        node_type = nd.get("node_type", "")
        if node_type in event_types:
            continue
        node_pin_ids: dict[str, int] = nd.get("pin_ids", {})
        is_isolated = True
        for pin_id in node_pin_ids.values():
            if int(pin_id) in connected_pins:
                is_isolated = False
                break
        if is_isolated:
            errors.append(
                f"Node {nid_str}<{node_type}>: isolated (no connections) — "
                f"may be dead code or missing links"
            )

    # 5. 必连引脚检查
    required_connections = {
        "Branch": ["Condition"],
    }
    for nid_str, nd in nodes.items():
        node_type = nd.get("node_type", "")
        required = required_connections.get(node_type, [])
        if not required:
            continue
        node_pin_ids: dict[str, int] = nd.get("pin_ids", {})
        for rpin in required:
            rpid = node_pin_ids.get(rpin)
            if rpid is None:
                continue
            if int(rpid) not in connected_pins:
                errors.append(
                    f"Node {nid_str}<{node_type}>: required pin '{rpin}' is not connected"
                )

    return errors


# ═══════════════════════════════════════════════════════════════
# L2: 干跑模拟
# ═══════════════════════════════════════════════════════════════

class DryRunLogger:
    """收集干跑日志的结构化记录器。"""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.events: list[dict] = []  # 每条 log 一行

    def __call__(self, node_id: int, node_type: str, action: str, detail: str) -> None:
        entry = {
            "node_id": node_id,
            "node_type": node_type,
            "action": action,
            "detail": detail,
        }
        self.events.append(entry)
        if self.verbose:
            print(f"  [TRACE] #{node_id}<{node_type}> {action} | {detail}")

    def summary(self) -> str:
        """按 action 类型分组统计。"""
        from collections import Counter
        actions = Counter(e["action"] for e in self.events)
        types = Counter(e["node_type"] for e in self.events)
        lines = [
            f"  Total side-effect events: {len(self.events)}",
            f"  By action: {dict(actions)}",
            f"  By node_type: {dict(types)}",
        ]
        return "\n".join(lines)


def dry_run_simulation(
    scene_data: dict,
    max_frames: int = 60,
    verbose: bool = False,
    real_time: bool = False,
    target_fps: float = 60.0,
) -> dict:
    """L2: 干跑模拟 — 构建 GraphEvaluator，设置 dry_run=True，模拟 N 帧。

    Args:
        scene_data:   已加载的 scene JSON dict。
        max_frames:   最大模拟帧数。
        verbose:      是否逐节点打印执行追踪。
        real_time:    True=真实时间模式 (time.sleep 维持帧率), False=fake 时间模式。
        target_fps:   真实时间模式下的目标帧率 (默认 60)。

    Returns:
        {
            "frames_simulated": int,
            "total_events": int,
            "events_by_type": dict,
            "errors": list[str],
            "perf": dict | None,  # 仅 real_time 模式下返回
        }
    """
    import time as _time_mod

    from Application.Editor.UI.controllers.node_editor.node_types import _TYPES
    from Application.Editor.UI.controllers.node_editor.canvas import NodeCanvas
    from Application.Editor.UI.controllers.node_editor.evaluator_engine import (
        GraphEvaluator,
        ExecutionContext,
    )

    logger = DryRunLogger(verbose=verbose)
    errors: list[str] = []

    # ── 1. 从 scene JSON 提取 graph 数据并构建 NodeCanvas ──
    graph_data = _extract_graph_data(scene_data)
    if "nodes" not in graph_data:
        errors.append("No 'nodes' found in scene graph data")
        return {
                "frames_simulated": 0,
                "total_events": 0,
                "events_by_type": {},
                "errors": errors,
                "perf": None,
            }

    try:
        canvas = NodeCanvas.from_dict(graph_data)
    except Exception as e:
        errors.append(f"Failed to deserialize NodeCanvas: {e}")
        return {
            "frames_simulated": 0,
            "total_events": 0,
            "events_by_type": {},
            "errors": errors,
            "perf": None,
        }

    # ── 2. 构建 GraphEvaluator + ExecutionContext (dry_run) ──
    evaluator = GraphEvaluator(canvas, _TYPES)
    ctx = ExecutionContext()
    ctx.dry_run = True
    ctx.log = logger

    # 时间参数
    if real_time:
        simulated_dt = 1.0 / target_fps
        target_frame_s = 1.0 / target_fps
        frame_times: list[float] = []  # 每帧的 wall-clock 耗时 (ms)
    else:
        simulated_dt = 1.0 / 60.0

    # ── Header ──
    mode_label = "Real-Time" if real_time else "Fake-Time"
    fps_label = f"@{target_fps:.0f}fps" if real_time else "@~60fps"
    print(f"\n{'='*60}")
    print(f"  Dry-Run Simulation ({mode_label}) — max {max_frames} frames {fps_label}")
    print(f"  Nodes: {len(canvas.nodes)}  Links: {len(canvas.links)}")
    print(f"{'='*60}")

    # ── 3. 触发 OnGameStart ──
    print("\n── OnGameStart ──")
    ctx.elapsed_time = 0.0
    ctx.delta_time = 0.0
    try:
        _t0 = _time_mod.perf_counter()
        evaluator.trigger("OnGameStart", ctx)
        _startup_ms = (_time_mod.perf_counter() - _t0) * 1000.0
        if real_time:
            print(f"  [Perf] OnGameStart: {_startup_ms:.2f} ms")
    except Exception as e:
        errors.append(f"OnGameStart error: {e}")
        if verbose:
            import traceback
            traceback.print_exc()

    # ── 4. 逐帧模拟 OnFrameUpdate ──
    exit_requested = False
    for frame in range(1, max_frames + 1):
        ctx.elapsed_time += simulated_dt
        ctx.delta_time = simulated_dt

        if verbose and frame % 60 == 0:
            print(f"\n── Frame {frame} (t={ctx.elapsed_time:.1f}s) ──")

        # 真实时间: 记录帧开始时刻, 帧结束后 sleep
        frame_start = _time_mod.perf_counter() if real_time else 0.0

        try:
            evaluator.trigger("OnFrameUpdate", ctx)
        except Exception as e:
            errors.append(f"Frame {frame} error: {e}")
            if verbose:
                import traceback
                traceback.print_exc()
            break

        # 真实时间: 记录耗时并 sleep 剩余时间
        if real_time:
            elapsed = _time_mod.perf_counter() - frame_start
            frame_times.append(elapsed * 1000.0)  # ms
            # sleep 以维持目标帧率
            sleep_needed = target_frame_s - elapsed
            if sleep_needed > 0:
                _time_mod.sleep(sleep_needed)

        # 检测 ExitGame 是否被触发
        for evt in logger.events:
            if evt["action"] == "stop" and evt["node_type"] == "ExitGame":
                exit_requested = True
                break

        if exit_requested:
            print(f"\n  [ExitGame] triggered at frame {frame} (t={ctx.elapsed_time:.1f}s)")
            break

    # ── 5. 触发 OnGameStop ──
    print("\n── OnGameStop ──")
    try:
        evaluator.trigger("OnGameStop", ctx)
    except Exception as e:
        errors.append(f"OnGameStop error: {e}")

    # ── 汇总 ──
    print(f"\n{logger.summary()}")

    # ── 性能统计 (仅 real_time 模式) ──
    perf = None
    if real_time and frame_times:
        import statistics
        frame_times_sorted = sorted(frame_times)
        n = len(frame_times_sorted)
        perf = {
            "frames_measured": n,
            "min_ms": min(frame_times_sorted),
            "max_ms": max(frame_times_sorted),
            "avg_ms": sum(frame_times_sorted) / n,
            "median_ms": statistics.median(frame_times_sorted),
            "p99_ms": frame_times_sorted[int(n * 0.99)] if n > 1 else frame_times_sorted[0],
        }
        print(f"\n  ── Frame Performance ({n} frames) ──")
        print(f"  Min:    {perf['min_ms']:8.3f} ms")
        print(f"  Max:    {perf['max_ms']:8.3f} ms")
        print(f"  Avg:    {perf['avg_ms']:8.3f} ms")
        print(f"  Median: {perf['median_ms']:8.3f} ms")
        print(f"  P99:    {perf['p99_ms']:8.3f} ms")

    from collections import Counter
    return {
        "frames_simulated": frame,
        "total_events": len(logger.events),
        "events_by_type": dict(Counter(e["node_type"] for e in logger.events)),
        "errors": errors,
        "perf": perf,
    }


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Node Graph Validator — static checks + dry-run simulation"
    )
    parser.add_argument(
        "scene_path",
        help="Path to .scene JSON file (e.g. Test/TestProject/MI.scene)",
    )
    parser.add_argument(
        "--frames", "-n",
        type=int,
        default=0,
        help="Run dry-run simulation for N frames (0 = static check only)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose mode — print per-node execution traces",
    )
    parser.add_argument(
        "--static-only", "-s",
        action="store_true",
        help="Static check only (skip dry-run even if --frames is set)",
    )
    parser.add_argument(
        "--real-time", "-r",
        action="store_true",
        help="Real-time mode — use time.sleep() between frames to measure real performance "
             "(default: fake-time with simulated delta). Useful for profiling BCI/device nodes.",
    )
    parser.add_argument(
        "--fps",
        type=float,
        default=60.0,
        help="Target FPS in real-time mode (default: 60). Lower values give more idle time "
             "between frames; higher values stress-test the evaluator throughput.",
    )
    args = parser.parse_args()

    # ── 加载 scene JSON ──
    scene_path = args.scene_path
    if not os.path.isabs(scene_path):
        scene_path = os.path.join(_project_root, scene_path)

    if not os.path.exists(scene_path):
        print(f"ERROR: File not found: {scene_path}")
        sys.exit(1)

    with open(scene_path, "r", encoding="utf-8") as f:
        scene_data = json.load(f)

    # ═══════════════════════════════════════════════════════
    # L1: 静态检查
    # ═══════════════════════════════════════════════════════
    print(f"\n{'='*60}")
    print(f"  L1: Static Validation — {os.path.basename(scene_path)}")
    print(f"{'='*60}")

    static_errors = validate_static(scene_data)
    if static_errors:
        print(f"\n  FAILED — {len(static_errors)} issue(s):\n")
        for err in static_errors:
            print(f"    ✗ {err}")
    else:
        print(f"\n  ✓ PASSED — no static issues found")

    # ═══════════════════════════════════════════════════════
    # L2: 干跑模拟
    # ═══════════════════════════════════════════════════════
    dry_run_errors: list[str] = []
    if args.frames > 0 and not args.static_only:
        result = dry_run_simulation(
            scene_data,
            max_frames=args.frames,
            verbose=args.verbose,
            real_time=args.real_time,
            target_fps=args.fps,
        )
        dry_run_errors = result.get("errors", [])
        if dry_run_errors:
            print(f"\n  Dry-run errors ({len(dry_run_errors)}):")
            for err in dry_run_errors:
                print(f"    ✗ {err}")
        else:
            print(f"\n  ✓ Dry-run completed — {result['frames_simulated']} frames, "
                  f"{result['total_events']} side-effect events")

    # ── 最终退出码 ──
    total_errors = len(static_errors) + len(dry_run_errors)
    if total_errors > 0:
        print(f"\n{'='*60}")
        print(f"  RESULT: {total_errors} issue(s) total — FIX BEFORE PIE")
        print(f"{'='*60}")
        sys.exit(1)
    else:
        print(f"\n{'='*60}")
        print(f"  RESULT: All checks passed ✓")
        print(f"{'='*60}")
        sys.exit(0)


if __name__ == "__main__":
    main()
