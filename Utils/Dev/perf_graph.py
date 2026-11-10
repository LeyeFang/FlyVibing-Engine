"""perf_graph — 节点图 / 编辑器 / 导出成品 的性能剖面（分割测量，可作回归门槛）。

三档，互不依赖，按需选一档跑：

  graph   离线图求值（假时间干跑，不碰网络/GPU）
          A 反序列化 B 静态检查 C 干跑 D 节点类型归因 E print 成本 F cProfile 热点
  live    活体帧统计（编辑器 / PIE）：renderer.snapshot 连续采样 p1_low / 帧时 std
  cpu     进程 CPU 占用（ctypes GetProcessTimes，免 psutil）：idle vs PIE

为什么需要它（2026-11-10 实测背景）
    `FrameProfiler` 只给 fps / p1_low / std 三个数 —— 能看出"慢"，看不出
    "花在哪"。本工具补上归因层：`graph` 档把图求值拆到"每个节点类型 + 每个
    热点函数"，据此定位到 `canvas.find_pin_node` 的 O(nodes×pins) 线性扫描
    （占 MI-SSSEP 图求值 60%+），索引化后 3.44 → 0.22 ms/帧。

用法
    .venv-py314t\\Scripts\\python.exe Utils/Dev/perf_graph.py graph
    .venv-py314t\\Scripts\\python.exe Utils/Dev/perf_graph.py graph --frames 600 --profile
    .venv-py314t\\Scripts\\python.exe Utils/Dev/perf_graph.py graph --json perf.json
    .venv-py314t\\Scripts\\python.exe Utils/Dev/perf_graph.py graph --baseline perf.json
    .venv-py314t\\Scripts\\python.exe Utils/Dev/perf_graph.py live --target pie --seconds 12
    .venv-py314t\\Scripts\\python.exe Utils/Dev/perf_graph.py cpu --mode pie --seconds 8

门槛模式
    --baseline 给上次的 --json 产物；任一场景 ms/帧 或 wall 超过
    `baseline×(1+--max-regress%)` 即 FAIL（退出码 3），可直接挂 CI。

退出码: 0 正常; 2 参数/连接错误; 3 回归门槛失败。
"""

from __future__ import annotations

import argparse
import builtins
import contextlib
import ctypes
import cProfile
import io
import json
import os
import pstats
import socket
import statistics
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

DEVNULL = open(os.devnull, "w", encoding="utf-8")
_NOOP = lambda *a, **k: None  # noqa: E731


def _quiet():
    return contextlib.redirect_stdout(DEVNULL)


class _SilencePrint:
    """把 builtins.print 换成空操作（量化热路径 print 的代价）。"""

    def __enter__(self):
        self._orig = builtins.print
        builtins.print = _NOOP

    def __exit__(self, *exc):
        builtins.print = self._orig
        return False


def pct(values, q):
    if not values:
        return 0.0
    s = sorted(values)
    return s[min(int(q * (len(s) - 1)), len(s) - 1)]


# ═══════════════════════════════════════════════════════════════
# 场景发现
# ═══════════════════════════════════════════════════════════════

def discover_scenes(pattern: str | None) -> list[Path]:
    """默认：主线 Examples + 所有扩展自带 Examples 下的 *.scene。"""
    if pattern:
        base = Path(pattern)
        if not base.is_absolute():
            base = (REPO / base)
        return sorted(base.glob("**/*.scene")) if base.is_dir() else [base]
    found: list[Path] = []
    for root in (REPO / "Examples", ):
        found.extend(sorted(root.glob("*/scenes/*.scene")))
    funcs = REPO / "Application" / "Functions"
    if funcs.is_dir():
        for ext in sorted(p for p in funcs.iterdir() if p.is_dir()):
            found.extend(sorted((ext / "Examples").glob("*/scenes/*.scene")))
    return found


def graph_of(path: Path) -> dict:
    """取 .scene 里的 node_graph（兼容裸 graph 与 {"scene": ...} 包装）。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    scene = data.get("scene") if isinstance(data.get("scene"), dict) else data
    return scene.get("node_graph") or {}


def _rel(path: Path) -> Path:
    """尽量给相对仓库根的路径（外部路径原样返回）。"""
    try:
        return path.resolve().relative_to(REPO)
    except ValueError:
        return path


# ═══════════════════════════════════════════════════════════════
# graph 档
# ═══════════════════════════════════════════════════════════════

def run_graph(args) -> int:
    from Application.Core.NodeGraph import (
        NodeCanvas, GraphEvaluator, _TYPES, _EVALUATORS,
    )
    from Application.Core.NodeGraph.validation.checks import static_check_graph
    from Application.Core.NodeGraph.validation.dry_run import run_dry_run

    scenes = discover_scenes(args.scene or args.dir)
    if not scenes:
        print("没有找到 .scene（用 --dir/--scene 指定）")
        return 2

    # ── 逐类型 / 逐帧计时（运行时包装，不改引擎代码）──
    state = {"type_ms": {}, "type_calls": {}, "type_err": {}, "frame_ms": []}

    for type_name, fn in list(_EVALUATORS.items()):
        if getattr(fn, "_perf_wrapped", False):
            continue

        def _wrap(nid, ctx, g, _fn=fn, _t=type_name):
            t0 = time.perf_counter()
            try:
                _fn(nid, ctx, g)
            except BaseException:
                state["type_err"][_t] = state["type_err"].get(_t, 0) + 1
                raise
            finally:
                state["type_ms"][_t] = (state["type_ms"].get(_t, 0.0)
                                        + (time.perf_counter() - t0) * 1000.0)
                state["type_calls"][_t] = state["type_calls"].get(_t, 0) + 1

        _wrap._perf_wrapped = True
        _EVALUATORS[type_name] = _wrap

    if not getattr(GraphEvaluator.trigger, "_perf_wrapped", False):
        _orig_trigger = GraphEvaluator.trigger

        def _trigger(self, event_type, ctx, _orig=_orig_trigger):
            t0 = time.perf_counter()
            try:
                return _orig(self, event_type, ctx)
            finally:
                state["frame_ms"].append((time.perf_counter() - t0) * 1000.0)

        _trigger._perf_wrapped = True
        GraphEvaluator.trigger = _trigger

    def _reset():
        for key in ("type_ms", "type_calls", "type_err"):
            state[key].clear()
        state["frame_ms"].clear()

    frames = int(args.frames)
    dt = float(args.dt)
    results: list[dict] = []

    # ★ 预热：第一个被测场景会吃掉惰性 import / 分支预测 / 分配器增长等一次性成本
    #   （实测 ~1 s / 300 帧），不预热会把“第一张图”误报成慢 10 倍。
    warm = graph_of(scenes[0]) if scenes else {}
    if warm.get("nodes"):
        with _quiet():
            run_dry_run(warm, frames=max(30, frames // 10), dt=dt, seed=args.seed)
        _reset()

    for scene in scenes:
        graph = graph_of(scene)
        if not graph.get("nodes"):
            continue
        name = scene.parent.parent.name
        print(f"[graph] {name}", flush=True)

        t0 = time.perf_counter()
        canvas = NodeCanvas.from_dict(graph)
        deser_ms = (time.perf_counter() - t0) * 1000.0
        types: dict[str, int] = {}
        for inst in canvas.nodes.values():
            types[inst.node_type] = types.get(inst.node_type, 0) + 1
        unknown = sorted(t for t in types if t not in _TYPES)
        pins = sum(len(inst.pin_ids) for inst in canvas.nodes.values())

        t0 = time.perf_counter()
        static = static_check_graph(graph)
        static_ms = (time.perf_counter() - t0) * 1000.0

        _reset()
        with _quiet():
            t0 = time.perf_counter()
            out = run_dry_run(graph, frames=frames, dt=dt, seed=args.seed)
            dry_ms = (time.perf_counter() - t0) * 1000.0
        done = int(out.get("frames_simulated", 0)) or 1

        # print 成本 A/B（同图 1/4 帧数）
        small = max(60, frames // 4)
        with _quiet():
            t0 = time.perf_counter()
            run_dry_run(graph, frames=small, dt=dt, seed=args.seed)
            base_ms = (time.perf_counter() - t0) * 1000.0
        with _SilencePrint(), _quiet():
            t0 = time.perf_counter()
            run_dry_run(graph, frames=small, dt=dt, seed=args.seed)
            noprint_ms = (time.perf_counter() - t0) * 1000.0

        results.append({
            "scene": str(_rel(scene)),
            "name": name,
            "kb": round(len(json.dumps(graph, ensure_ascii=False).encode()) / 1024.0, 1),
            "nodes": len(canvas.nodes), "links": len(canvas.links), "pins": pins,
            "types": dict(sorted(types.items(), key=lambda kv: -kv[1])),
            "unknown_types": unknown,
            "deser_ms": round(deser_ms, 2),
            "static_ms": round(static_ms, 2),
            "static_errors": sum(1 for e in static if e["level"] == "error"),
            "static_warnings": sum(1 for e in static if e["level"] == "warning"),
            "dry_ms": round(dry_ms, 1),
            "frames": done,
            "ms_per_frame": round(dry_ms / done, 3),
            "frame_ms": [round(x, 3) for x in state["frame_ms"]],
            "type_ms": {k: round(v, 2) for k, v in
                        sorted(state["type_ms"].items(), key=lambda kv: -kv[1])},
            "type_calls": dict(sorted(state["type_calls"].items(), key=lambda kv: -kv[1])),
            "print_ms": round(base_ms - noprint_ms, 1),
            "print_frames": small,
            "events": int(out.get("total_events", 0)),
            "dry_errors": (out.get("errors") or [])[:5],
        })

    if not results:
        print("没有可测的图（场景里没有 node_graph）")
        return 2

    # ── 报告 ──
    print(f"\n=== 汇总 (frames={frames}, dt={dt:.5f}) ===")
    print(f"{'example':<38}{'KB':>7}{'nodes':>6}{'links':>7}{'pins':>6}"
          f"{'deser':>8}{'static':>8}{'dry ms':>9}{'ms/frame':>10}")
    for r in results:
        print(f"{r['name']:<38}{r['kb']:>7.1f}{r['nodes']:>6}{r['links']:>7}{r['pins']:>6}"
              f"{r['deser_ms']:>8.2f}{r['static_ms']:>8.2f}{r['dry_ms']:>9.1f}"
              f"{r['ms_per_frame']:>10.3f}")

    print("\n=== 帧耗时 (ms, OnGameStart + N×OnFrameUpdate) ===")
    for r in results:
        fm = r["frame_ms"]
        print(f"{r['name']:<38} mean={statistics.mean(fm):7.3f} p50={pct(fm, .5):7.3f} "
              f"p95={pct(fm, .95):7.3f} p99={pct(fm, .99):7.3f} max={max(fm):7.3f}")

    print(f"\n=== print 成本 A/B (同图 {results[0]['print_frames']} 帧) ===")
    for r in results:
        print(f"{r['name']:<38} {r['print_ms']:>8.1f} ms  "
              f"({r['print_ms'] / r['print_frames']:>6.3f} ms/帧)")

    print("\n=== 节点类型 Top (占图求值耗时) ===")
    for r in results:
        total = sum(r["type_ms"].values()) or 1.0
        print(f"[{r['name']}] total={total:8.1f} ms / {r['frames']} 帧"
              f"  ({total / r['frames']:.3f} ms/帧)")
        for t, ms in list(r["type_ms"].items())[:6]:
            print(f"    {t:<32}{ms:>9.1f} ms {100.0 * ms / total:>5.1f}%  "
                  f"calls={r['type_calls'].get(t, 0)}")

    for r in results:
        if r["unknown_types"]:
            print(f"\n! {r['name']}: 未注册节点类型（扩展未启用）: {r['unknown_types']}")
        if r["dry_errors"]:
            print(f"! {r['name']}: dry-run errors: {r['dry_errors']}")
        if r["static_errors"]:
            print(f"! {r['name']}: 静态检查 {r['static_errors']} error(s)")

    # ── cProfile：只做最大的一张图 ──
    if args.profile:
        biggest = max(results, key=lambda r: r["nodes"])
        prof = cProfile.Profile()
        with _quiet():
            prof.enable()
            run_dry_run(graph_of(REPO / biggest["scene"]), frames=max(60, frames // 4),
                        dt=dt, seed=args.seed)
            prof.disable()
        buf = io.StringIO()
        pstats.Stats(prof, stream=buf).sort_stats("tottime").print_stats(20)
        text = buf.getvalue()
        print(f"\n=== cProfile tottime Top ({biggest['name']}) ===")
        print(text)
        if args.profile is not True and str(args.profile):
            Path(str(args.profile)).write_text(text, encoding="utf-8")
            print(f"(已写入 {args.profile})")

    payload = {"tier": "graph", "frames": frames, "dt": dt,
               "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "scenes": results}
    if args.json:
        Path(args.json).write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
        print(f"\n(已写入 {args.json})")

    return _gate(args, results, key="ms_per_frame")


# ═══════════════════════════════════════════════════════════════
# 回归门槛
# ═══════════════════════════════════════════════════════════════

def _gate(args, results: list[dict], key: str) -> int:
    if not args.baseline:
        return 0
    try:
        base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"[gate] 读不了 baseline: {exc}")
        return 2
    old = {r["name"]: r for r in (base.get("scenes") or [])}
    limit = 1.0 + float(args.max_regress) / 100.0
    bad: list[str] = []
    print(f"\n=== 回归门槛 (±{args.max_regress}%) ===")
    for r in results:
        prev = old.get(r["name"])
        if not prev:
            print(f"  {r['name']:<38} (新场景, 无基线)")
            continue
        now_v = float(r.get(key) or 0.0)
        old_v = float(prev.get(key) or 0.0)
        delta = now_v - old_v
        ratio = (now_v / old_v) if old_v > 0 else 0.0
        # 噪声地坂: 绝对差 < 0.05 ms/帧 视为“没变”（避免 0.13→0.18 这种小值抖动误报）
        noisy = abs(delta) < 0.05
        ok = ratio <= limit or noisy
        tag = "OK " if ok else "SLOW"
        print(f"  [{tag}] {r['name']:<38} {old_v:.3f} → {now_v:.3f}  x{ratio:.2f}"
              + ("  (噪声内)" if noisy and ratio > limit else ""))
        if not ok:
            bad.append(r["name"])
    if bad:
        print(f"[gate] FAIL: {', '.join(bad)}")
        return 3
    print("[gate] PASS")
    return 0


# ═══════════════════════════════════════════════════════════════
# live / cpu 档（需要运行中的编辑器）
# ═══════════════════════════════════════════════════════════════

class Bus:
    """命令总线客户端（每行一个 JSON；与 engine-editor-cli 同一协议）。"""

    def __init__(self, port: int) -> None:
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=600)
        self.f = self.sock.makefile("rw", encoding="utf-8", newline="\n")
        self.n = 0

    def call(self, op: str, **args) -> dict:
        self.n += 1
        self.f.write(json.dumps({"id": self.n, "op": op, "args": args}) + "\n")
        self.f.flush()
        line = self.f.readline()
        if not line:
            raise RuntimeError("command bus closed")
        return json.loads(line)

    def result(self, op: str, **args) -> dict:
        return self.call(op, **args).get("result") or {}


def _pid_of(port: int) -> int:
    try:
        return int(Bus(port).result("instance.info").get("instance", {}).get("pid") or 0)
    except (OSError, ValueError):
        return 0


def run_live(args) -> int:
    try:
        bus = Bus(args.port)
    except OSError as exc:
        print(f"连不上编辑器 {args.port}: {exc}")
        return 2

    snap = bus.result("renderer.snapshot")
    print(f"backend={snap.get('backend')} viewport={snap.get('viewport')} "
          f"counts={snap.get('counts')}")
    if args.target == "pie":
        play = bus.call("sim.play")
        print("sim.play:", play.get("ok"), play.get("error") or play.get("result"))
        if not play.get("ok"):
            return 2

    print(f"\n{'t(s)':>6}{'frames':>8}{'p1_low_ms':>12}{'fps':>8}{'std_ms':>9}")
    rows: list[tuple[float, float, float]] = []
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < args.seconds:
        st = (bus.result("renderer.snapshot").get("stats") or {})
        dt = time.perf_counter() - t0
        if st:
            p1 = float(st.get("p1_low_ms") or 0.0)
            rows.append((dt, p1, float(st.get("frame_time_std_ms") or 0.0)))
            print(f"{dt:6.2f}{st.get('window_frames', 0):8}{p1:12.2f}"
                  f"{st.get('p1_low_fps', 0.0):8.1f}{st.get('frame_time_std_ms', 0.0):9.2f}")
        time.sleep(args.interval)

    if rows:
        p1s = [r[1] for r in rows]
        stds = [r[2] for r in rows]
        med = statistics.median(p1s)
        print(f"\np1_low: median={med:.2f} min={min(p1s):.2f} max={max(p1s):.2f} "
              f"=> ~{1000.0 / med if med else 0:.1f} fps | std median={statistics.median(stds):.2f}")

    if args.target == "pie":
        print("sim.stop:", bus.call("sim.stop").get("ok"))
    return 0


# ── 进程 CPU（ctypes，Windows）────────────────────────────────

class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", ctypes.c_uint32),
                ("dwHighDateTime", ctypes.c_uint32)]


def _cpu_seconds(pid: int) -> float:
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    h = k32.OpenProcess(0x0400 | 0x0010, False, pid)      # QUERY_INFORMATION | VM_READ
    if not h:
        raise OSError(f"OpenProcess({pid}) failed")
    try:
        _c, _e, k, u = _FILETIME(), _FILETIME(), _FILETIME(), _FILETIME()
        if not k32.GetProcessTimes(h, ctypes.byref(_c), ctypes.byref(_e),
                                   ctypes.byref(k), ctypes.byref(u)):
            raise OSError("GetProcessTimes failed")
        to_s = lambda ft: (ft.dwHighDateTime << 32 | ft.dwLowDateTime) / 1e7
        return to_s(k) + to_s(u)
    finally:
        k32.CloseHandle(h)


def run_cpu(args) -> int:
    if os.name != "nt":
        print("cpu 档仅支持 Windows（GetProcessTimes）")
        return 2
    pid = args.pid or _pid_of(args.port)
    if not pid:
        print("拿不到 pid（--pid 或确保编辑器在跑）")
        return 2
    bus = None
    try:
        bus = Bus(args.port)
    except OSError:
        pass
    if args.mode == "pie" and bus is not None:
        print("sim.play:", bus.call("sim.play").get("ok"))
        if not bus.result("sim.state").get("runtime_alive"):
            time.sleep(1.0)

    c0 = _cpu_seconds(pid)
    time.sleep(2.0)                     # 预热
    c1 = _cpu_seconds(pid)
    t0 = time.perf_counter()
    time.sleep(args.seconds)
    c2 = _cpu_seconds(pid)
    wall = time.perf_counter() - t0
    print(f"pid={pid} mode={args.mode} wall={wall:.2f}s cpu={c2 - c1:.2f}s "
          f"=> {100.0 * (c2 - c1) / wall:.1f}% of one core "
          f"(warmup {c1 - c0:.2f} cpu/s)")
    if args.mode == "pie" and bus is not None:
        print("sim.stop:", bus.call("sim.stop").get("ok"))
    return 0


# ═══════════════════════════════════════════════════════════════

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="perf_graph", description="节点图 / 编辑器 / 成品 性能剖面",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sub = ap.add_subparsers(dest="tier", required=True)

    g = sub.add_parser("graph", help="离线图求值剖面（假时间干跑）")
    g.add_argument("--dir", default=None, help="场景根目录（递归找 *.scene）")
    g.add_argument("--scene", default=None, help="单个 .scene 文件")
    g.add_argument("--frames", type=int, default=600, help="干跑帧数（默认 600）")
    g.add_argument("--dt", type=float, default=1.0 / 60.0, help="假时间步长")
    g.add_argument("--seed", type=int, default=0)
    g.add_argument("--profile", nargs="?", const=True, default=False,
                   help="顺带跑 cProfile（可给输出路径）")
    g.add_argument("--json", default=None, help="结果写 JSON（可作 --baseline）")
    g.add_argument("--baseline", default=None, help="上次 --json 产物，做回归门槛")
    g.add_argument("--max-regress", type=float, default=10.0,
                   help="允许的退化百分比（默认 10）")
    g.set_defaults(func=run_graph)

    lv = sub.add_parser("live", help="活体帧统计采样（编辑器 / PIE）")
    lv.add_argument("--port", type=int, default=8977)
    lv.add_argument("--target", choices=("editor", "pie"), default="editor")
    lv.add_argument("--seconds", type=float, default=8.0)
    lv.add_argument("--interval", type=float, default=0.5)
    lv.set_defaults(func=run_live)

    cp = sub.add_parser("cpu", help="进程 CPU 占用（Windows）")
    cp.add_argument("--port", type=int, default=8977)
    cp.add_argument("--pid", type=int, default=0)
    cp.add_argument("--mode", choices=("idle", "pie"), default="idle")
    cp.add_argument("--seconds", type=float, default=8.0)
    cp.set_defaults(func=run_cpu)

    args = ap.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
