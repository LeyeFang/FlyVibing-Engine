"""
EEGDevice.ServiceHost — 品牌服务进程侧宿主 (纯 stdlib + 后端注入)。

职责:
  - 监听本机端口, 接受单个客户端连接 (引擎或调试客户端);
  - 按协议处理命令: hello / init / start / pump / stop / kill / info / shutdown;
  - push 模式: 后端采集线程 → on_block → 加锁写 socket (与响应同通道, 顺序保证);
  - 客户端断开 → 进程退出 (引擎崩溃时连接关闭 → 服务自动清理, 不驻留)。

品牌接入 (service.py 提供两个工厂):
  - create_backend()            → DeviceBackend 实例 (真实后端);
  - cfg_from_fields(fields)     → 由引擎侧配置字段重建配置对象。

数据模式 (mode):
  - "pump": 合成/可控后端 — 块由 pump 命令同步生成并随响应返回 (确定性, 与进程内一致);
  - "push": 真实硬件 — start 后采集线程持续推送 block 消息。

兼容性: 本模块可能运行于低于引擎的 Python (Gtec 自有环境) — 保持 3.9 语法。
"""

from __future__ import annotations

import socket
import threading
import traceback

from .ServiceProtocol import recv_message, send_message

VERSION = "1.0"

_SHUTDOWN = object()   # 哨兵: shutdown 命令返回它即退出主循环


class ServiceHost:
    """单客户端服务宿主。serve_forever() 阻塞直到客户端断开或 shutdown。"""

    def __init__(self, brand: str, mode: str, create_backend, cfg_from_fields,
                 host: str = "127.0.0.1", port: int = 0) -> None:
        assert mode in ("pump", "push"), f"unknown mode {mode!r}"
        self.brand = brand
        self.mode = mode
        self._create_backend = create_backend
        self._cfg_from_fields = cfg_from_fields
        self._host = host
        self._port = port
        self._backend = None
        self._conn = None            # type: socket.socket | None
        self._send_lock = threading.Lock()
        self._seq = 0

    # ── 生命周期 ────────────────────────────────────────────

    def serve_forever(self) -> None:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((self._host, self._port))
        srv.listen(1)
        self._port = srv.getsockname()[1]
        print(f"[EEGService:{self.brand}] ready {self._host}:{self._port} "
              f"mode={self.mode}", flush=True)
        try:
            conn, addr = srv.accept()
        finally:
            srv.close()
        self._conn = conn
        print(f"[EEGService:{self.brand}] client {addr[0]} connected", flush=True)
        try:
            self._serve_connection(conn)
        finally:
            self._teardown_backend()
            try:
                conn.close()
            except OSError:
                pass
            print(f"[EEGService:{self.brand}] exit", flush=True)

    def _serve_connection(self, conn: socket.socket) -> None:
        while True:
            try:
                msg = recv_message(conn)
            except (OSError, ConnectionError, EOFError):
                break
            if msg is None:
                break
            if not isinstance(msg, dict):
                continue
            resp = self._handle(msg)
            if resp is _SHUTDOWN:
                send_message(conn, {"ok": True, "rid": msg.get("rid"),
                                    "detail": "bye"}, self._send_lock)
                break
            send_message(conn, resp, self._send_lock)

    # ── 命令处理 ────────────────────────────────────────────

    def _handle(self, msg: dict) -> dict:
        cmd = str(msg.get("cmd", ""))
        rid = msg.get("rid")
        try:
            if cmd == "hello":
                return {"ok": True, "rid": rid, "brand": self.brand,
                        "mode": self.mode, "version": VERSION, "is_stub": False}
            if cmd == "shutdown":
                return _SHUTDOWN     # 任意状态下都可收尾 (未 init 亦可)
            if cmd == "init":
                if self._backend is not None:
                    raise RuntimeError("session already initialized (init once)")
                cfg = self._cfg_from_fields(dict(msg.get("fields") or {}))
                backend = self._create_backend()
                try:
                    backend.configure(cfg)
                except Exception:
                    try:
                        backend.close()
                    finally:
                        raise
                self._backend = backend
                return {"ok": True, "rid": rid,
                        "detail": f"'{self.brand}' backend configured"}
            if self._backend is None:
                if cmd == "kill":
                    return {"ok": True, "rid": rid, "detail": "nothing to close"}
                raise RuntimeError("not initialized — send init first")
            if cmd == "start":
                self._backend.start(self._emit_block)
                return {"ok": True, "rid": rid,
                        "detail": "recording (service side)"}
            if cmd == "pump":
                blocks: list = []
                self._backend.pump(float(msg.get("elapsed", 0.0)), blocks.append)
                return {"ok": True, "rid": rid, "blocks": blocks}
            if cmd == "stop":
                self._backend.stop()
                return {"ok": True, "rid": rid, "detail": "stopped (service side)"}
            if cmd == "kill":
                self._backend.stop()
                self._backend.close()
                self._backend = None
                return {"ok": True, "rid": rid, "detail": "closed"}
            if cmd == "info":
                return {"ok": True, "rid": rid, "info": self._backend.info()}
            return {"ok": False, "rid": rid, "detail": f"unknown cmd '{cmd}'"}
        except Exception as e:  # noqa: BLE001 — 服务端绝不崩, 错误回传客户端
            return {"ok": False, "rid": rid,
                    "detail": f"{type(e).__name__}: {e}",
                    "trace": traceback.format_exc(limit=8)}

    # ── push 模式: 采集线程 → socket ────────────────────────

    def _emit_block(self, block) -> None:
        conn = self._conn
        if conn is None:
            return
        self._seq += 1
        try:
            send_message(conn, {"type": "block", "seq": self._seq, "data": block},
                         self._send_lock)
        except OSError:
            pass   # 客户端断开: 由主循环收尾

    def _teardown_backend(self) -> None:
        backend = self._backend
        self._backend = None
        if backend is None:
            return
        try:
            backend.stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            backend.close()
        except Exception:  # noqa: BLE001
            pass


def run_service(brand, mode, create_backend, cfg_from_fields, argv=None) -> int:
    """service.py 通用入口: --host/--port 解析 + serve_forever。"""
    import argparse

    ap = argparse.ArgumentParser(description=f"MyGameEngine EEG service — {brand}")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=0)
    args = ap.parse_args(argv)
    print(f"[EEGService:{brand}] starting (host={args.host} port={args.port})",
          flush=True)
    host = ServiceHost(brand, mode, create_backend, cfg_from_fields,
                       host=args.host, port=args.port)
    host.serve_forever()
    return 0
