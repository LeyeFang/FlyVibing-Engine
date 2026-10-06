"""thread_probe — 引擎实机线程探针（线程开发协议: Doc/Dev/threading_protocol.md）。

对运行中的编辑器 (默认 127.0.0.1:8977) 调用 `threads.snapshot` 并展示:
  注册线程 / 停滞(stale) / 未注册漂移(unregistered)。

用法:
  python Utils/Dev/thread_probe.py                     # 单次快照
  python Utils/Dev/thread_probe.py --watch --hz 4      # 持续监视 (Ctrl+C 停止)
  python Utils/Dev/thread_probe.py --assert-alive render:EditorHost,logic:GameRuntime
  python Utils/Dev/thread_probe.py --fail-on-stale     # stale 非空 → 退出码 3

退出码: 0 正常; 2 引擎未连接/协议错误; 3 断言失败(--assert-alive/--fail-on-stale)。
零依赖 (stdlib only) — 开发者侧工具 (Utils/Dev), 不随产品分发。
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import time

EXIT_OK, EXIT_CONN, EXIT_ASSERT = 0, 2, 3


def fetch_snapshot(port: int, timeout: float = 5.0) -> dict:
    """一次 threads.snapshot（NDJSON 单请求单响应）。"""
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as s:
        s.sendall((json.dumps({"id": 1, "op": "threads.snapshot"}) + "\n").encode("utf-8"))
        line = s.makefile("r", encoding="utf-8", newline="\n").readline()
    if not line:
        raise ConnectionError("empty response")
    resp = json.loads(line)
    if not resp.get("ok"):
        raise RuntimeError(str(resp.get("error")))
    return resp.get("result") or {}


def print_snapshot(snap: dict, t0: float) -> None:
    age = time.perf_counter() - t0
    stale = snap.get("stale") or []
    mark = "  !STALE" if stale else ""
    print(f"[{age:7.2f}s] threads count={snap.get('count', 0)} stale={len(stale)}{mark}")
    print("  NAME                            OWNER                     HZ    BEATS     AGE(ms)  ALIVE")
    print("  ------------------------------  ------------------------  ----  --------  -------  -----")
    for t in snap.get("registered", []):
        flag = " *" if t.get("stale") else ""
        print(f"  {t['name']:<30}  {t['owner']:<24}  {t['expect_hz']:>4.0f}  {t['beats']:>8}"
              f"  {t['age_ms']:>7.1f}  {str(t.get('alive')):<5}{flag}")
    unreg = snap.get("unregistered") or []
    if unreg:
        print(f"  unregistered: {', '.join(unreg)}")


def _check(snap: dict, assert_names: list[str], fail_on_stale: bool) -> int:
    reg = {t["name"]: t for t in snap.get("registered", [])}
    if assert_names:
        missing = [n for n in assert_names if n not in reg]
        if missing:
            print(f"ASSERT FAIL: missing threads: {', '.join(missing)}")
            return EXIT_ASSERT
        print(f"assert-alive OK: {', '.join(assert_names)}")
    if fail_on_stale and (snap.get("stale") or []):
        print(f"ASSERT FAIL: stale threads: {', '.join(snap['stale'])}")
        return EXIT_ASSERT
    return EXIT_OK


def main() -> int:
    ap = argparse.ArgumentParser(description="引擎实机线程探针 (threads.snapshot)")
    ap.add_argument("--port", type=int, default=8977)
    ap.add_argument("--watch", action="store_true", help="持续监视")
    ap.add_argument("--hz", type=float, default=2.0, help="watch 刷新频率")
    ap.add_argument("--assert-alive", default="", help="逗号分隔线程名; 缺失→退出码 3")
    ap.add_argument("--fail-on-stale", action="store_true", help="stale 非空→退出码 3")
    ns = ap.parse_args()

    t0 = time.perf_counter()
    assert_names = [n.strip() for n in ns.assert_alive.split(",") if n.strip()]

    try:
        if not ns.watch:
            snap = fetch_snapshot(ns.port)
            print_snapshot(snap, t0)
            return _check(snap, assert_names, ns.fail_on_stale)
        while True:
            snap = fetch_snapshot(ns.port)
            print_snapshot(snap, t0)
            rc = _check(snap, assert_names, ns.fail_on_stale)
            if rc != EXIT_OK:
                return rc
            time.sleep(max(0.05, 1.0 / max(ns.hz, 0.1)))
    except KeyboardInterrupt:
        print("\n[watch] stopped")
        return EXIT_OK
    except (ConnectionError, OSError) as e:
        print(f"engine not reachable on 127.0.0.1:{ns.port}: {e}")
        return EXIT_CONN
    except (RuntimeError, json.JSONDecodeError) as e:
        print(f"protocol error: {e}")
        return EXIT_CONN


if __name__ == "__main__":
    sys.exit(main())
