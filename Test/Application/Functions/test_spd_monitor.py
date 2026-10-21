"""SerialParallelDevice 监视能力测试（无硬件 — 纯状态与缓冲语义）。

锁定内容（官方示例扩展的数据通道 — Application/Functions/SerialParallelDevice/monitor.py）:
  1. list_serial_ports 结构安全（无硬件 → 可能 []）; PARALLEL_ADDRS 含 trigger 口
  2. watch 状态机: start/stop/watch_state
  3. 收发观察回调: TX/RX/PX 计数 + 事件 hex/ascii 格式
  4. 快照新→旧序 + 环形缓冲上限
  5. 错误记录 last_error
  6. 未运行态 send 安全丢弃（不排队、不炸、无 TX 事件）

运行: python Utils/Dev/test_runner.py --only spd_monitor
"""
# TIER: core

from __future__ import annotations

import os
import sys

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "_path_setup.py")):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)
    import _path_setup  # noqa: E402

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


def main() -> int:
    print("=" * 60)
    print("SerialParallelDevice monitor — state/buffer/format (headless)")
    print("=" * 60)

    from Application.Functions.SerialParallelDevice import (
        PARALLEL_ADDRS, is_running, list_serial_ports, monitor_snapshot,
        parallel_status, send, start_watch, stop_watch, watch_state)
    from Application.Functions.SerialParallelDevice import monitor as mon

    try:
        # ── 1. 枚举与静态结构 ────────────────────────────────
        print("── enumeration ──")
        ports = list_serial_ports()
        check("list_serial_ports → list[dict]",
              isinstance(ports, list)
              and all(isinstance(p, dict) and "device" in p for p in ports),
              str(ports)[:120])
        check("PARALLEL_ADDRS 含 trigger 口 0x3FF8", 0x3FF8 in PARALLEL_ADDRS)
        ps = parallel_status()
        check("parallel_status 结构", "available" in ps and "addrs" in ps)

        # ── 2. watch 状态机 ──────────────────────────────────
        print("── watch state machine ──")
        check("初始 watch inactive", watch_state()["active"] is False)
        w1 = start_watch("COM_TEST", 9600)
        check("start_watch → active/port/baud",
              w1["active"] and w1["port"] == "COM_TEST" and w1["baud"] == 9600, str(w1))
        w2 = stop_watch()
        check("stop_watch → inactive", w2["active"] is False)

        # ── 3. 观察回调与事件格式 ────────────────────────────
        print("── observe callbacks ──")
        mon.observe_serial_tx("COM_TEST", 9600, b"hello")
        mon.observe_serial_rx(b"\x01\x02\x0d\x0a")
        mon.observe_parallel_write(0x3FF8, b"\x00\x00\x80\x3f")
        snap = monitor_snapshot(50)
        events = snap["events"]
        kinds = [e["kind"] for e in events]
        check("事件含 TX/RX/PX", "TX" in kinds and "RX" in kinds and "PX" in kinds,
              str(kinds[:12]))
        stats = snap["stats"]
        check("统计计数递增",
              stats["tx_count"] >= 1 and stats["rx_count"] >= 1
              and stats["parallel_writes"] >= 1, str(stats))
        tx_ev = next(e for e in events if e["kind"] == "TX")
        check("TX 事件 hex/ascii 格式",
              tx_ev["hex"].startswith("68 65 6c 6c 6f") and tx_ev["text"] == "hello",
              str(tx_ev))
        rx_ev = next(e for e in events if e["kind"] == "RX")
        check("RX ascii 预览非可打印 → '.'", rx_ev["text"] == "....", str(rx_ev))

        # ── 4. 快照序 + 环形缓冲上限 ─────────────────────────
        print("── snapshot / ring buffer ──")
        check("事件新→旧序", events[0]["t"] >= events[-1]["t"],
              f"{events[0]['t']} vs {events[-1]['t']}")
        for _ in range(600):
            mon.observe_serial_rx(b"x")
        big = monitor_snapshot(10000)
        check("环形缓冲上限 500", len(big["events"]) <= 500, str(len(big["events"])))

        # ── 5. 错误记录 ──────────────────────────────────────
        mon.observe_error("unit-test error")
        check("last_error 记录",
              monitor_snapshot(5)["stats"]["last_error"] == "unit-test error")

        # ── 6. 未运行态 send 安全丢弃 ────────────────────────
        before = monitor_snapshot(1)["stats"]["tx_count"]
        send("COM_TEST", 9600, b"drop")
        after = monitor_snapshot(1)["stats"]["tx_count"]
        check("未运行 send 安全丢弃（无 TX 事件）",
              before == after and is_running() is False)
    finally:
        stop_watch()

    total = _RESULTS["pass"] + _RESULTS["fail"]
    status = "OK" if _RESULTS["fail"] == 0 else "FAIL"
    print()
    print(f"RESULT: {status} ({_RESULTS['pass']}/{total})")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
