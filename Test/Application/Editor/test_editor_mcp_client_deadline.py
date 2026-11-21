"""editor-mcp 客户端「强制返回点」守卫（core，无 GUI、无引擎）。

背景（2026-11-16，用户反馈）:
  引擎窗口被最小化 / 主线程被驱动阻塞时，`engine_capture` 会长时间不给结果。
  MCP 的同步工具是在 stdio 事件循环里直接执行的 —— 一次卡住的抓帧不仅自己没结论,
  还会把整个服务器（其它工具、协议层）一起冻住, agent 会话表现为"卡死"。

本测试锁定客户端的返回点纪律（用本进程假引擎，不依赖真实编辑器）:
  1. `send_raw` 对"接受连接但永不回包"的对端, 在 timeout+余量内返回 wedged 结论
  2. `fetch_raw_frame` 的 timeout_s 是**整轮**预算 (不是每次轮询的预算)
  3. 引擎回执 window_state=iconified 时只用短等待窗口, 错误信息可执行
  4. 引擎回执 state=expired (租约到期) → 立即失败, 不再轮询
  5. `capture_png` 整链路有看门狗, 不会无限挂住

运行: python Utils/Dev/test_runner.py --only editor_mcp_client_deadline
"""

# TIER: core

from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
while ROOT and not os.path.exists(os.path.join(ROOT, "startup.bat")):
    _parent = os.path.dirname(ROOT)
    if _parent == ROOT:
        ROOT = ""
        break
    ROOT = _parent
assert ROOT, "repo root not found"
SRC = os.path.join(ROOT, "Utils", "ExtDev", "EditorMcp", "src")
for _p in (ROOT, SRC):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from engine_editor_mcp import client as mcp_client  # noqa: E402
from engine_editor_mcp.client import EngineError, capture_png, fetch_raw_frame, send_raw  # noqa: E402

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


class FakeEngine:
    """最小 NDJSON 假引擎 — 按 mode 决定回什么（永不回 / pending / expired）。"""

    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.port = 0
        self._sock = socket.socket()
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(8)
        self.port = self._sock.getsockname()[1]
        self._running = True
        self._conns: list[socket.socket] = []
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()

    def _accept_loop(self) -> None:
        while self._running:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return
            self._conns.append(conn)
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn: socket.socket) -> None:
        try:
            reader = conn.makefile("rb")
            line = reader.readline()
            if not line:
                return
            req = json.loads(line.decode("utf-8"))
            if self.mode == "silent":
                time.sleep(30)      # 接受连接但永不回包
                return
            result = self._result_for(str(req.get("op")), req.get("args") or {})
            conn.sendall((json.dumps({"id": req.get("id"), "ok": True, "result": result}) + "\n").encode())
        except (OSError, ValueError):
            pass
        # 有意不关连接: 模拟"对端半死"

    def _result_for(self, op: str, args: dict) -> dict:
        if op == "frame.request":
            window_state = "iconified" if self.mode == "iconified" else "normal"
            return {"target": "editor", "generation": 7,
                    "window_state": window_state, "framebuffer": [1600, 900]}
        if op == "frame.fetch":
            if self.mode == "expired":
                return {"target": "editor", "generation": args.get("generation"),
                        "ready": False, "state": "expired", "pending_ms": 10000.0,
                        "error": "渲染线程 10s 内没有产出新帧 — 窗口最小化/被遮挡"}
            return {"target": "editor", "generation": args.get("generation"),
                    "ready": False, "state": "pending"}
        return {"ok": True}

    def close(self) -> None:
        self._running = False
        try:
            self._sock.close()
        except OSError:
            pass
        for conn in self._conns:
            try:
                conn.close()
            except OSError:
                pass


def _with_engine(mode: str):
    """把客户端指向假引擎（通过 env 端口），返回 (engine, restore)。"""
    engine = FakeEngine(mode)
    old = os.environ.get("MGE_EDITOR_MCP_PORT")
    os.environ["MGE_EDITOR_MCP_PORT"] = str(engine.port)

    def restore() -> None:
        engine.close()
        if old is None:
            os.environ.pop("MGE_EDITOR_MCP_PORT", None)
        else:
            os.environ["MGE_EDITOR_MCP_PORT"] = old

    return engine, restore


def _timed(fn):
    start = time.monotonic()
    try:
        value = fn()
        return value, None, time.monotonic() - start
    except Exception as exc:  # noqa: BLE001 — 测试: 记录异常与耗时
        return None, exc, time.monotonic() - start


def main() -> int:
    print("== editor-mcp client deadline guards ==")
    print(f"  knobs: FRAME_CALL_TIMEOUT={mcp_client.FRAME_CALL_TIMEOUT} "
          f"ICONIFIED_GRACE_S={mcp_client.ICONIFIED_GRACE_S} "
          f"WATCHDOG_MARGIN={mcp_client.WATCHDOG_MARGIN}")

    # ── 1. send_raw: 对端永不回包 → 强制返回 ──
    print("── 1. send_raw watchdog (silent peer) ──")
    _, restore = _with_engine("silent")
    try:
        (res, _payload), exc, elapsed = _timed(lambda: send_raw("settings.get", {}, timeout=1.0))
        check("silent peer -> returns a dict", exc is None and isinstance(res, dict), repr(exc))
        check("reports a timeout-ish error", "error" in (res or {}), str(res))
        check(f"bounded by timeout+margin ({elapsed:.2f}s < 3.0s)", elapsed < 3.0, f"{elapsed:.2f}s")

        # capture_png 整链路同样有返回点
        (_value, exc, elapsed) = _timed(lambda: capture_png("editor", timeout_s=1.0))
        check("capture_png raises EngineError", isinstance(exc, EngineError), repr(exc))
        check(f"capture_png bounded ({elapsed:.2f}s < 6.0s)", elapsed < 6.0, f"{elapsed:.2f}s")
    finally:
        restore()

    # 看门狗本体: 即使 socket 层自己不返回（驱动/系统挂起）, 也必须按时交结论
    print("── 1b. watchdog fires when the socket layer never returns ──")
    original_exchange = mcp_client._exchange

    def _never_returns(req, port, timeout):
        time.sleep(30)
        return {"ok": True}, None

    mcp_client._exchange = _never_returns
    try:
        (res, _payload), exc, elapsed = _timed(lambda: send_raw("settings.get", {}, timeout=0.5))
        check("wedged call still returns", exc is None and isinstance(res, dict), repr(exc))
        check("marks error_code=wedged", (res or {}).get("error_code") == "wedged", str(res))
        check("explains forced give-up", "强制放弃" in str((res or {}).get("error")), str(res))
        check(f"gives up after timeout+margin ({elapsed:.2f}s < 2.5s)", elapsed < 2.5, f"{elapsed:.2f}s")
    finally:
        mcp_client._exchange = original_exchange

    # ── 2. fetch_raw_frame: pending 永不到来 → 整轮预算 ──
    print("── 2. fetch_raw_frame total budget (always pending) ──")
    _, restore = _with_engine("pending")
    try:
        (_value, exc, elapsed) = _timed(lambda: fetch_raw_frame("editor", timeout_s=1.5))
        check("pending -> EngineError", isinstance(exc, EngineError), repr(exc))
        check(f"uses whole budget only once ({elapsed:.2f}s in 1.5..3.0s)", 1.5 <= elapsed < 3.0,
              f"{elapsed:.2f}s")
        check("message names last_state", "last_state=pending" in str(exc), str(exc))
    finally:
        restore()

    # ── 3. 最小化窗口: 短等待窗口 + 可执行结论 ──
    print("── 3. iconified window (fail fast) ──")
    _, restore = _with_engine("iconified")
    try:
        (_value, exc, elapsed) = _timed(lambda: fetch_raw_frame("editor", timeout_s=6.0))
        check("iconified -> EngineError", isinstance(exc, EngineError), repr(exc))
        check(f"grace window only ({elapsed:.2f}s <= ~2.5s)", elapsed <= 2.8, f"{elapsed:.2f}s")
        check("message says minimized", "最小化" in str(exc), str(exc))
        check("message says restore window", "还原窗口" in str(exc), str(exc))
    finally:
        restore()

    # ── 4. 引擎侧租约到期 → 立即失败 ──
    print("── 4. engine-side lease expired ──")
    _, restore = _with_engine("expired")
    try:
        (_value, exc, elapsed) = _timed(lambda: fetch_raw_frame("editor", timeout_s=6.0))
        check("expired -> EngineError", isinstance(exc, EngineError), repr(exc))
        check(f"fails immediately ({elapsed:.2f}s < 1.5s)", elapsed < 1.5, f"{elapsed:.2f}s")
        check("surfaces engine reason", "没有产出新帧" in str(exc), str(exc))
    finally:
        restore()

    total = _RESULTS["pass"] + _RESULTS["fail"]
    print(f"RESULT: {'OK' if _RESULTS['fail'] == 0 else 'FAIL'} "
          f"({_RESULTS['pass']}/{total})")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
