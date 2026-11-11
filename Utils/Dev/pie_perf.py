"""pie_perf — PIE 帧率实测与解耦对照（1.2 帧同步实验）。

对运行中的编辑器（默认 127.0.0.1:8977）执行::

    project.open? → sim.play [lockstep] → 采样 pie_fps → perf.phases → sim.stop

**为什么需要它**
    解耦 PIE 渲染（与编辑器帧同步脱钩）的收益必须能一键复现，否则下次讨论又
    回到"感觉快了"。本工具把 before/after 的每一次测量都变成同一套数字：
    PIE 帧分布 + 编辑器帧分布 + 各相排他时间，落 JSON 便于对比。

**典型用法**

    # 单次：解耦（默认）跑 10 s
    python Utils/Dev/pie_perf.py --project <x.myproj> --seconds 10

    # A/B 对照：lockstep → 解耦，两次各 10 s，并排打印
    python Utils/Dev/pie_perf.py --project <x.myproj> --seconds 10 --ab

    # 批量跑一批工程（每个工程一次解耦测量）
    python Utils/Dev/pie_perf.py --projects-dir <dir> --seconds 8

    # 原样保存/对比
    python Utils/Dev/pie_perf.py --ab --json out.json

**看图注意**
    `pie_fps` 是 PIE 渲染线程自己的帧率；`editor_fps` 是编辑器渲染线程的。
    解耦后两者应当**互相独立** —— 编辑器仍按自己的节奏（面板可见时 ~30 fps），
    PIE 则按它的真实工作量走。若 `pie_fps` 仍被编辑器钉住，说明 sync_wait 没消掉。

退出码: 0 正常; 2 引擎未连接/协议错误; 3 测量无效（PIE 未起来 / 没采到帧）。
零依赖（stdlib only）— 开发者侧工具（Utils/Dev），不随产品分发。
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time

EXIT_OK, EXIT_CONN, EXIT_ASSERT = 0, 2, 3
DEFAULT_PORT = 8977


# ── 通道（与 thread_probe 同风格：裸 NDJSON，不依赖工具仓包）─────

class Client:
    def __init__(self, port: int, timeout: float = 60.0) -> None:
        self.port = int(port)
        self.timeout = float(timeout)
        self._id = 0

    def call(self, op: str, args: dict | None = None,
             timeout: float | None = None) -> dict:
        self._id += 1
        req = {"id": self._id, "op": op, "args": args or {}}
        with socket.create_connection(("127.0.0.1", self.port),
                                      timeout=timeout or self.timeout) as s:
            s.sendall((json.dumps(req, ensure_ascii=False) + "\n").encode("utf-8"))
            line = s.makefile("r", encoding="utf-8", newline="\n").readline()
        if not line:
            raise ConnectionError("empty response（编辑器可能正在退出）")
        resp = json.loads(line)
        if not resp.get("ok"):
            raise RuntimeError(str(resp.get("error")))
        return resp.get("result") or {}


# ── 测量 ────────────────────────────────────────────────────────

def _pie_phases(client: Client) -> dict:
    """取 PIE 的分相快照（键名带 #ident，取渲染线程）。"""
    res = client.call("perf.phases", {"target": "pie"}) or {}
    snap = ((res.get("profiles") or {}).get("pie") or {}).get("snapshot") or {}
    for thread, data in (snap.get("threads") or {}).items():
        if thread.startswith("render:") and data.get("frame", {}).get("n"):
            return {"thread": thread, **data}
    return {}


def _editor_phases(client: Client) -> dict:
    res = client.call("perf.phases", {"target": "editor"}) or {}
    snap = ((res.get("profiles") or {}).get("editor") or {}).get("snapshot") or {}
    for thread, data in (snap.get("threads") or {}).items():
        if thread.startswith("render:") and data.get("frame", {}).get("n"):
            return {"thread": thread, **data}
    return {}


def measure(client: Client, seconds: float, lockstep: bool,
            label: str = "") -> dict:
    """跑一段 PIE 并采集帧率/分相。返回一次测量的结构化结果。"""
    state = client.call("sim.state")
    if state.get("state") != "Stopped":
        client.call("sim.stop")
        _wait_state(client, "Stopped", 15.0)

    played = client.call("sim.play", {"force": True, "lockstep": lockstep})
    if not played.get("requested"):
        return {"label": label, "ok": False, "error": played.get("error", "play refused")}
    if not _wait_state(client, "Running", 20.0):
        st = client.call("sim.state")
        return {"label": label, "ok": False,
                "error": f"PIE did not reach Running: {st.get('last_error') or st.get('state')}"}

    # 让 PIE 起稳（首帧 / 资源上传 / 图初始化），然后清样本开始计时
    time.sleep(1.5)
    client.call("perf.profile", {"on": True, "reset": True, "target": "all"})
    t0 = time.perf_counter()
    samples: list[float] = []
    while time.perf_counter() - t0 < seconds:
        time.sleep(0.5)
        st = client.call("sim.state")
        fps = st.get("pie_fps")
        if isinstance(fps, (int, float)) and fps > 0:
            samples.append(float(fps))
    elapsed = time.perf_counter() - t0

    pie = _pie_phases(client)
    editor = _editor_phases(client)
    final = client.call("sim.state")
    client.call("sim.stop")
    _wait_state(client, "Stopped", 20.0)

    return {
        "label": label or ("lockstep" if lockstep else "decoupled"),
        "ok": bool(pie),
        "lockstep": bool(lockstep),
        "seconds": round(elapsed, 2),
        "pie_fps_sampled": round(sum(samples) / len(samples), 1) if samples else 0.0,
        "pie": _compact(pie),
        "editor": _compact(editor),
        "sync": final.get("sync"),
        "fps_samples": [round(v, 1) for v in samples],
    }


def _compact(thread_data: dict) -> dict:
    """只留对比需要的字段（JSON 小、表格好排）。"""
    if not thread_data:
        return {}
    frame = thread_data.get("frame") or {}
    un = thread_data.get("unattributed") or {}
    phases = {}
    for name, st in (thread_data.get("phases") or {}).items():
        e = st.get("excl") or {}
        phases[name] = {"mean": e.get("mean", 0.0), "p95": e.get("p95", 0.0),
                        "share": st.get("share", 0.0)}
    return {
        "thread": thread_data.get("thread", ""),
        "frame": {k: frame.get(k) for k in ("n", "mean", "p50", "p95", "p99", "max")},
        "fps": round(1000.0 / frame["mean"], 1) if frame.get("mean") else 0.0,
        "unattributed": un.get("mean", 0.0),
        "phases": phases,
    }


def _wait_state(client: Client, want: str, timeout: float) -> bool:
    end = time.perf_counter() + timeout
    while time.perf_counter() < end:
        try:
            if client.call("sim.state").get("state") == want:
                return True
        except Exception:  # noqa: BLE001 — 启动/停止期间连接可能短暂失败
            pass
        time.sleep(0.2)
    return False


# ── 输出 ────────────────────────────────────────────────────────

def print_result(r: dict) -> None:
    if not r.get("ok"):
        print(f"  [{r.get('label')}] 测量失败: {r.get('error')}")
        return
    pie, ed = r["pie"], r["editor"]
    pf, ef = pie.get("frame") or {}, ed.get("frame") or {}
    print(f"  [{r['label']}] {r['seconds']:.1f}s  "
          f"mode={'lockstep' if r['lockstep'] else 'decoupled'}")
    if pf.get("n"):
        print(f"    PIE     {pie.get('fps'):7.1f} fps  "
              f"mean {pf['mean']:7.3f}  p50 {pf['p50']:7.3f}  "
              f"p95 {pf['p95']:7.3f}  max {pf['max']:7.3f} ms  (n={pf['n']})")
    if ef.get("n"):
        print(f"    EDITOR  {ed.get('fps'):7.1f} fps  "
              f"mean {ef['mean']:7.3f}  p95 {ef['p95']:7.3f}  ms  (n={ef['n']})")
    sync = r.get("sync") or {}
    if sync:
        print(f"    FrameSync ticks={sync.get('ticks')} waits={sync.get('waits')}")
    pie_phases = pie.get("phases") or {}
    if pie_phases:
        top = sorted(pie_phases.items(), key=lambda kv: -kv[1]["mean"])[:6]
        print("    PIE phases: " + ", ".join(
            f"{k}={v['mean']:.2f}ms({v['share'] * 100:.0f}%)" for k, v in top))
    ed_phases = ed.get("phases") or {}
    if ed_phases:
        top = sorted(ed_phases.items(), key=lambda kv: -kv[1]["mean"])[:5]
        print("    ED  phases: " + ", ".join(
            f"{k}={v['mean']:.2f}ms" for k, v in top))
    print()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="PIE 帧率实测与解耦对照")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--project", default="", help="先打开该 .myproj")
    ap.add_argument("--projects-dir", default="",
                    help="批量：目录下每个 **/*.myproj 各测一次（解耦）")
    ap.add_argument("--seconds", type=float, default=10.0)
    ap.add_argument("--ab", action="store_true",
                    help="对照：lockstep → decoupled 各测一次")
    ap.add_argument("--json", default="", help="结果落盘路径")
    ap.add_argument("--force", action="store_true",
                    help="sim.play force=true（跳过预检；默认已开）")
    args = ap.parse_args(argv)

    client = Client(args.port)
    try:
        client.call("sim.state")
    except (OSError, ConnectionError) as exc:
        print(f"[pie_perf] 编辑器未运行（127.0.0.1:{args.port}）: {exc}", file=sys.stderr)
        return EXIT_CONN
    except RuntimeError as exc:
        print(f"[pie_perf] 协议错误: {exc}", file=sys.stderr)
        return EXIT_CONN

    projects: list[str] = []
    if args.projects_dir:
        for dirpath, _dirs, files in os.walk(args.projects_dir):
            for f in sorted(files):
                if f.endswith(".myproj"):
                    projects.append(os.path.join(dirpath, f))
    elif args.project:
        projects = [args.project]
    else:
        projects = [""]     # 用编辑器当前工程

    results: list[dict] = []
    for proj in projects:
        if proj:
            opened = client.call("project.open", {"path": os.path.abspath(proj)},
                                 timeout=180.0)
            print(f"== {opened.get('name') or os.path.basename(proj)} "
                  f"({len(opened.get('scenes') or [])} scene(s)) ==")
        else:
            print("== 当前工程 ==")
        name = os.path.splitext(os.path.basename(proj))[0] if proj else "current"
        if args.ab:
            for lockstep in (True, False):
                r = measure(client, args.seconds, lockstep,
                            label=f"{name}/{'lockstep' if lockstep else 'decoupled'}")
                results.append(r)
                print_result(r)
        else:
            r = measure(client, args.seconds, False, label=f"{name}/decoupled")
            results.append(r)
            print_result(r)

    bad = [r for r in results if not r.get("ok")]
    if args.json:
        path = os.path.abspath(args.json)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                       "port": args.port, "results": results}, fh,
                      ensure_ascii=False, indent=1)
        print(f"[pie_perf] 结果 → {path}")
    return EXIT_OK if not bad else EXIT_ASSERT


if __name__ == "__main__":
    raise SystemExit(main())
