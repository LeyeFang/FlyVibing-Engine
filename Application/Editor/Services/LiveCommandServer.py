"""
LiveCommandServer — 编辑器实时命令总线（给 agent 的 MCP 热注入通道）。

架构（详见 Doc/Dev/editor_live_protocol.md）:
    socket 线程(仅收 JSON → 入队 → 等待回执)
        → queue.Queue（门缝）
        → 主线程 pump（EditorLayer.OnUpdate 每帧 drain）
        → op 处理器（复用编辑器现有 API：SimulationController / ViewportController / ...）

线程纪律（free-threading 无 GIL，硬约束）:
    - socket 线程只做 JSON 编解码 + 入队 + 等待回执;
    - 一切编辑器状态变更只在主线程 pump() 中执行 —
      与人类点按钮走完全相同的代码路径。

端点: 127.0.0.1:<port>（仅回环; 默认 8977, 可用环境变量 MGE_EDITOR_MCP_PORT 覆盖）。
协议: NDJSON — 一行一条 JSON:
    请求  {"id": 1, "op": "sim.play", "args": {}}
    回执  {"id": 1, "ok": true,  "result": {...}}
          {"id": 1, "ok": false, "error": "..."}
"""

from __future__ import annotations

import json
import os
import queue
import socket
import threading

DEFAULT_PORT = 8977
_ENV_PORT = "MGE_EDITOR_MCP_PORT"
_PUMP_TIMEOUT = 15.0    # 主线程回执等待上限（秒）
_MAX_OPS_PER_FRAME = 16


class LiveCommandServer:
    """编辑器命令总线（类级单例; 随编辑器生命周期启停）。"""

    _sock: socket.socket | None = None
    _thread: threading.Thread | None = None
    _queue: "queue.Queue[dict] | None" = None
    _ops: dict[str, object] = {}
    port: int = 0
    _running: bool = False

    # ════════════════════════════════════════════════════════════
    # 生命周期（主线程调用）
    # ════════════════════════════════════════════════════════════

    @classmethod
    def start(cls, port: int | None = None) -> bool:
        """启动监听（幂等）。port=None → 环境变量或默认 8977; port=0 → 系统分配（测试用）。"""
        if cls._running:
            return True
        if port is None:
            try:
                port = int(os.environ.get(_ENV_PORT, "") or DEFAULT_PORT)
            except ValueError:
                port = DEFAULT_PORT

        cls._queue = queue.Queue()
        cls._register_ops()

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
            sock.listen(4)
        except OSError as e:
            print(f"[Live] WARNING: cannot bind 127.0.0.1:{port} ({e}) — command server disabled")
            try:
                sock.close()
            except OSError:
                pass
            return False

        cls.port = sock.getsockname()[1]
        cls._sock = sock
        cls._running = True
        cls._thread = threading.Thread(
            target=cls._accept_loop, name="LiveCommandServer", daemon=True
        )
        cls._thread.start()
        print(
            f"[Live] Editor command server on 127.0.0.1:{cls.port} "
            f"(NDJSON) — ops: {', '.join(sorted(cls._ops))}"
        )
        return True

    @classmethod
    def stop(cls) -> None:
        """停止监听（编辑器关闭时调用; 幂等）。"""
        cls._running = False
        sock, cls._sock = cls._sock, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    # ════════════════════════════════════════════════════════════
    # socket 线程（绝不触碰编辑器状态）
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _accept_loop(cls) -> None:
        while cls._running and cls._sock is not None:
            try:
                cls._sock.settimeout(0.5)
                conn, _addr = cls._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(
                target=cls._handle_client, args=(conn,), daemon=True
            ).start()

    @classmethod
    def _handle_client(cls, conn: socket.socket) -> None:
        try:
            reader = conn.makefile("r", encoding="utf-8", newline="\n")
            for line in reader:
                line = line.strip()
                if not line:
                    continue
                resp = cls._dispatch_line(line)
                conn.sendall((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))
        except (OSError, ValueError):
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass

    @classmethod
    def _dispatch_line(cls, line: str) -> dict:
        """解析一条请求 → 入队 → 等待主线程回执 → 组装响应。"""
        try:
            req = json.loads(line)
            if not isinstance(req, dict):
                raise ValueError("request must be a JSON object")
            rid = req.get("id")
            op = str(req.get("op") or "")
            args = req.get("args") or {}
            if not isinstance(args, dict):
                raise ValueError("args must be a JSON object")
        except ValueError as e:
            return {"id": None, "ok": False, "error": f"invalid request: {e}"}

        if cls._queue is None or not cls._running:
            return {"id": rid, "ok": False, "error": "server not running"}

        work = {"id": rid, "op": op, "args": args, "event": threading.Event()}
        cls._queue.put(work)
        if not work["event"].wait(timeout=_PUMP_TIMEOUT):
            return {"id": rid, "ok": False, "error": "timeout waiting for editor main thread"}
        if work.get("ok"):
            return {"id": rid, "ok": True, "result": work.get("result")}
        return {"id": rid, "ok": False, "error": work.get("error")}

    # ════════════════════════════════════════════════════════════
    # 主线程 pump（EditorLayer.OnUpdate 每帧调用）
    # ════════════════════════════════════════════════════════════

    @classmethod
    def pump(cls, max_ops: int = _MAX_OPS_PER_FRAME) -> None:
        """取队列中的命令在本线程执行（每帧限量，保证帧率）。"""
        q = cls._queue
        if q is None:
            return
        for _ in range(max_ops):
            try:
                work = q.get_nowait()
            except queue.Empty:
                return
            try:
                handler = cls._ops.get(work["op"])
                if handler is None:
                    raise ValueError(
                        f"unknown op: '{work['op']}' "
                        f"(available: {', '.join(sorted(cls._ops))})"
                    )
                work["result"] = handler(work["args"])
                work["ok"] = True
            except Exception as e:  # noqa: BLE001
                work["ok"] = False
                work["error"] = f"{type(e).__name__}: {e}"
            tag = "ok" if work.get("ok") else f"ERR {work.get('error')}"
            print(f"[Live] id={work['id']} op={work['op']} → {tag}")
            work["event"].set()

    # ════════════════════════════════════════════════════════════
    # op 处理器（全部在主线程执行; 复用编辑器现有 API）
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _register_ops(cls) -> None:
        cls._ops = {
            "sim.play": cls._op_sim_play,
            "view.set_mode": cls._op_view_set_mode,
            "editor.quit": cls._op_editor_quit,
        }

    @staticmethod
    def _op_sim_play(args: dict) -> dict:
        """Run 按钮语义 — 请求 PIE 启动（主线程帧末由 SimulationController 消费）。"""
        from Application.Editor.UI.controllers.SimulationController import (
            SimulationController,
            SimulationState,
        )

        if SimulationController.get_state() != SimulationState.STOPPED:
            return {
                "requested": False,
                "state": SimulationController.get_state_label(),
                "note": "already running/paused",
            }
        SimulationController.play()
        return {"requested": True, "state": "pending_start"}

    @staticmethod
    def _op_view_set_mode(args: dict) -> dict:
        """切 2D 视图（正交俯视）/ 3D 透视 — 视图工具栏按钮语义。"""
        from Application.Editor.UI.controllers.ViewportController import ViewportController

        mode = str(args.get("mode", "2d")).lower()
        if mode == "2d":
            ViewportController.switch_to_2d()
        elif mode == "3d":
            ViewportController.switch_to_3d()
        else:
            raise ValueError(f"unsupported mode: {mode!r} (expected '2d' or '3d')")
        return {"mode": mode, "label": ViewportController.get_mode_label()}

    @staticmethod
    def _op_editor_quit(args: dict) -> dict:
        """关闭引擎 — 窗口关闭按钮语义（优先走 GLFW 正常关闭流程）。"""
        from Application.Editor.EditorHost import EditorHost

        window = None
        try:
            window = EditorHost.get_window()
        except Exception:  # noqa: BLE001
            window = None
        glfw_win = getattr(window, "glfw_window", None) if window is not None else None
        if glfw_win is not None:
            import glfw

            glfw.set_window_should_close(glfw_win, True)
            return {"closing": True, "via": "window_close_request"}
        EditorHost.run_state = False
        return {"closing": True, "via": "run_state"}
