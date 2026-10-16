"""
VirtualDevice.ServiceClient — 引擎侧服务后端: 品牌进程 + 协议通信 (DeviceBackend 实现)。

路由 (门面 VirtualDevice._make_backend, 真实模式默认):
  - VirtualDevice → spawn_virtual(): 引擎自动拉起 (sys.executable, 引擎本体环境);
  - 外部品牌       → connect_brand():  显式 MGE_EEG_SERVICE → 连接外部服务;
                    否则给出 (cfg.service_python / MGE_EEG_SERVICE_PYTHON) python +
                    品牌服务模块时 → 自动拉起 (自有环境进程, 动态端口);
                    都没有 → 连接默认端点。

数据模式 (服务 hello 声明):
  - pump: 虚拟/合成后端 — pump 命令同步返回块 (与进程内语义完全一致, 确定性);
  - push: 真实硬件 — start 后接收线程路由 block 消息 → on_block。

线程与锁 (自由线程引擎, 无 GIL):
  - 所有发送经 _send_lock; 接收 = 单读者 (push 模式路由器线程, 或 pump 模式同步直收);
  - push 模式下所有消息 (含响应) 经 _reader + rid 路由表分发, 禁止混用直收;
  - 接收线程绝不触碰 ctx/evaluator — 只回调 on_block (会话环形缓冲自带锁)。
"""

from __future__ import annotations

import dataclasses
import os
import queue
import socket
import subprocess
import sys
import tempfile
import threading
import time
from typing import Callable, Optional

from .Device import DeviceBackend
from .ServiceProtocol import recv_message, send_message

_DEFAULT_BRAND_ENDPOINT = "127.0.0.1:47810"
DEFAULT_BRAND_ENDPOINT = _DEFAULT_BRAND_ENDPOINT      # 公开别名（探针/文档用）
_CONNECT_TIMEOUT_S = 20.0          # 自动拉起时的等待窗口（服务启动 + SDK 导入）
_CONNECT_TIMEOUT_S_EXTERNAL = 3.0  # 外部/默认地址：连接拒绝时快速失败，不让用户干等
_SERVICE_LOG_PREFIX = "mge_eeg_service_"


class ServiceError(RuntimeError):
    """服务通信 / 远端执行失败。"""


def probe_brand_service(endpoint: Optional[str] = None, timeout: float = 1.5) -> dict:
    """探测品牌服务（不建会话）: TCP 连接 + hello 握手。

    Returns: {endpoint, source(arg|env|default), reachable, brand, mode, version,
              detail, auto_launch, python}
    """
    env_ep = os.environ.get("MGE_EEG_SERVICE", "").strip()
    arg_ep = str(endpoint or "").strip()
    ep = arg_ep or env_ep or _DEFAULT_BRAND_ENDPOINT
    py = os.environ.get("MGE_EEG_SERVICE_PYTHON", "").strip()
    out = {"endpoint": ep, "source": "arg" if arg_ep else ("env" if env_ep else "default"),
           "reachable": False, "brand": None, "mode": None, "version": None,
           "detail": "", "auto_launch": bool(py), "python": py or None}
    host, _, port_s = ep.partition(":")
    try:
        with socket.create_connection((host or "127.0.0.1", int(port_s or "0")),
                                      timeout=timeout) as sock:
            send_message(sock, {"cmd": "hello", "rid": 1})
            sock.settimeout(timeout)
            reply = recv_message(sock)
    except OSError as e:
        out["detail"] = f"not listening / connect failed: {e}"
        return out
    except Exception as e:  # noqa: BLE001 — 损坏响应等
        out["detail"] = f"handshake error: {e!r}"
        return out
    if isinstance(reply, dict) and reply.get("ok"):
        out.update(reachable=True, brand=reply.get("brand"), mode=reply.get("mode"),
                   version=reply.get("version"), detail="service ok")
    elif isinstance(reply, dict):
        out.update(reachable=True,
                   detail=f"unexpected responder on port (brand={reply.get('brand')!r})")
    else:
        out.update(reachable=True, detail="unexpected responder on port")
    return out


def _repo_root() -> str:
    """Application/Functions/VirtualDevice/ServiceClient.py → 仓库根目录。"""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, "..", "..", ".."))


class ServiceBackend(DeviceBackend):
    """品牌服务后端 — 引擎侧代理 (进程在别处跑, 数据走协议)。"""

    is_stub = False

    def __init__(self, brand: str, *, spawn: bool = False, module: str = "",
                 endpoint: Optional[str] = None, python_exe: str = "") -> None:
        self.brand = brand
        self._spawn = spawn
        self._module = module
        self._endpoint = endpoint
        self._python_exe = str(python_exe or "").strip()
        self._proc: Optional[subprocess.Popen] = None
        self._log_path: Optional[str] = None
        self._sock: Optional[socket.socket] = None
        self._send_lock = threading.Lock()
        self._rid = 0
        self._rid_lock = threading.Lock()
        self._reader: Optional[threading.Thread] = None
        self._reader_stop = threading.Event()
        self._router: dict = {}              # rid → queue.Queue
        self._router_lock = threading.Lock()
        self._mode = "pump"
        self._on_block: Optional[Callable] = None
        self._closed = False

    # ── 构造 ───────────────────────────────────────────────

    @classmethod
    def spawn_virtual(cls) -> "ServiceBackend":
        """VirtualDevice: 引擎自动拉起 (引擎本体环境; pump 模式)。"""
        return cls("virtual", spawn=True,
                   module="Application.Functions.VirtualDevice.service")

    @classmethod
    def connect_brand(cls, python_exe: Optional[str] = None,
                      module: str = "") -> "ServiceBackend":
        """外部品牌: 显式 MGE_EEG_SERVICE → 连接外部服务（设该项时不再自动拉起）;
        否则给出 (参数 / env MGE_EEG_SERVICE_PYTHON) python + 品牌服务模块时 →
        自动拉起自有环境服务; 都没有 → 连接默认端点（期望外部手动启动）。"""
        endpoint = os.environ.get("MGE_EEG_SERVICE", "").strip()
        if endpoint:
            return cls("external", spawn=False, endpoint=endpoint)
        exe = str(python_exe or "").strip() \
            or os.environ.get("MGE_EEG_SERVICE_PYTHON", "").strip()
        if exe and module:
            return cls("external", spawn=True, module=module, python_exe=exe)
        return cls("external", spawn=False, endpoint=_DEFAULT_BRAND_ENDPOINT)

    # ── DeviceBackend 协议 ────────────────────────────────

    def configure(self, cfg) -> None:
        self._ensure_connected()
        fields = dataclasses.asdict(cfg)
        resp = self._request("init", fields=fields, timeout=120.0)
        if not resp.get("ok"):
            raise ServiceError(f"{self.brand} service init failed: "
                               f"{resp.get('detail', 'unknown')}")

    def start(self, on_block: Callable, user_block_ms: float = 100.0) -> None:
        self._on_block = on_block
        if self._mode == "push":
            self._start_reader()
        resp = self._request("start", user_block_ms=float(user_block_ms),
                             timeout=30.0)
        if not resp.get("ok"):
            raise ServiceError(f"service start failed: {resp.get('detail')}")

    def pump(self, elapsed_s: float, on_block: Callable) -> None:
        if self._mode == "push":
            return   # 真实硬件: 数据由推送线程给 (与进程内真实后端 pump=no-op 语义一致)
        resp = self._request("pump", elapsed=float(elapsed_s), timeout=30.0)
        if resp.get("ok"):
            for blk in resp.get("blocks") or []:
                on_block(blk)

    def stop(self) -> None:
        try:
            resp = self._request("stop", timeout=120.0)
        except (ServiceError, OSError):
            return   # 容错: 断开/超时由 close() 收尾
        if not resp.get("ok"):
            print(f"[Device] service stop detail: {resp.get('detail')}")

    def kill(self) -> None:
        try:
            self._request("kill", timeout=60.0)
        except Exception:  # noqa: BLE001 — 断开场景尽力而为
            pass
        self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._request("shutdown", timeout=5.0)   # 两种模式皆可路由/直收
        except Exception:  # noqa: BLE001
            pass
        self._reader_stop.set()
        if self._sock is not None:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        if self._reader is not None:
            self._reader.join(timeout=3.0)
            self._reader = None
        if self._proc is not None:
            try:
                self._proc.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
            self._proc = None

    def info(self) -> dict:
        try:
            resp = self._request("info", timeout=10.0)
            if resp.get("ok"):
                info = dict(resp.get("info") or {})
                info.setdefault("backend", f"ServiceBackend({self.brand})")
                info["service"] = True
                return info
        except Exception:  # noqa: BLE001
            pass
        return {"backend": f"ServiceBackend({self.brand})", "service": True,
                "stub": False}

    def get_impedance(self, electrode_type: str = "passive", tms_box: bool = False) -> list:
        """电极阻抗测量（控制命令 — push/pump 两模式均可路由; 单位 Ω, NaN 保持）。"""
        resp = self._request("impedance", electrode_type=str(electrode_type),
                             tms_box=bool(tms_box), timeout=120.0)
        if not resp.get("ok"):
            raise ServiceError(f"impedance failed: {resp.get('detail', 'unknown')}")
        return list(resp.get("values_ohm") or [])

    # ── 连接与进程 ─────────────────────────────────────────

    def _ensure_connected(self) -> None:
        if self._sock is not None:
            return
        if self._spawn:
            self._spawn_service()
        host, port = self._parse_endpoint(self._endpoint)
        deadline = time.time() + (_CONNECT_TIMEOUT_S if self._spawn else _CONNECT_TIMEOUT_S_EXTERNAL)
        while time.time() < deadline and self._sock is None:
            remain = max(0.2, deadline - time.time())
            try:
                # 单次尝试不超出剩余预算（部分机器对关闭端口是超时而非拒绝）
                self._sock = socket.create_connection((host, port),
                                                      timeout=min(2.0, remain))
            except OSError:
                if self._proc is not None and self._proc.poll() is not None:
                    break   # 子进程已死 — 不再等待
                time.sleep(0.05)
        if self._sock is None:
            detail = f"cannot connect {self.brand} service @ {host}:{port}"
            if self._proc is not None and self._proc.poll() is not None:
                detail += f" (service exited code={self._proc.returncode})"
            if self._spawn:
                detail += (f"\nauto-launch command: {self._python_exe or sys.executable} "
                           f"-m {self._module} --port {port}")
                detail += ("\n提示: 'Svc python' / MGE_EEG_SERVICE_PYTHON 需指向品牌自有环境的 Python"
                           "（且该 python 需能访问本仓库）")
            elif self.brand == "external":
                detail += ("\n外部品牌服务未运行（引擎连不上品牌服务进程 —— 与设备是否被 "
                           "厂商软件占用无关。\n"
                           "  A) 自动拉起: 面板 'Svc python' 或环境变量 MGE_EEG_SERVICE_PYTHON "
                           "指向品牌自有环境 python.exe + 品牌服务模块, 再次 Open\n"
                           "  B) 手动启动: <该 python> -m <品牌服务模块> --port 47810\n"
                           "  自定义地址: MGE_EEG_SERVICE=host:port（设了该项时按它连接, 不自动拉起）")
            tail = self._read_log_tail()
            if tail:
                detail += f"\n--- service log tail ---\n{tail}"
            raise ServiceError(detail)

        hello = self._request("hello", timeout=10.0)
        if not hello.get("ok"):
            raise ServiceError(f"hello failed: {hello.get('detail')}")
        if str(hello.get("brand")) != self.brand:
            raise ServiceError(f"brand mismatch: expected '{self.brand}', "
                               f"got '{hello.get('brand')}'")
        self._mode = str(hello.get("mode", "pump"))

    def _spawn_service(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        self._log_path = os.path.join(
            tempfile.gettempdir(), f"{_SERVICE_LOG_PREFIX}{self.brand}_{port}.log")
        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        exe = self._python_exe or sys.executable
        cmd = [exe, "-m", self._module, "--port", str(port)]
        with open(self._log_path, "wb") as log:
            try:
                self._proc = subprocess.Popen(
                    cmd, cwd=_repo_root(), stdout=log,
                    stderr=subprocess.STDOUT, creationflags=creationflags)
            except OSError as e:
                raise ServiceError(
                    f"cannot spawn {self.brand} service: {e}\n"
                    f"  python: {exe!r}\n"
                    f"  （'Svc python' / MGE_EEG_SERVICE_PYTHON 需指向真实存在的 python.exe）") from e
        self._endpoint = f"127.0.0.1:{port}"

    @staticmethod
    def _parse_endpoint(endpoint: Optional[str]) -> tuple:
        if not endpoint:
            raise ServiceError("missing service endpoint")
        host, _, port_s = endpoint.partition(":")
        return host or "127.0.0.1", int(port_s or "0")

    def _read_log_tail(self, n_lines: int = 20) -> str:
        if not self._log_path or not os.path.isfile(self._log_path):
            return ""
        try:
            with open(self._log_path, "r", encoding="utf-8",
                      errors="replace") as fh:
                lines = fh.read().splitlines()
            return "\n".join(lines[-n_lines:])
        except OSError:
            return ""

    # ── 请求 / 路由 ────────────────────────────────────────

    def _next_rid(self) -> int:
        with self._rid_lock:
            self._rid += 1
            return self._rid

    def _request(self, cmd: str, timeout: float = 30.0, **kwargs) -> dict:
        sock = self._sock
        if sock is None:
            raise ServiceError(f"not connected (cmd={cmd})")
        rid = self._next_rid()
        msg = {"cmd": cmd, "rid": rid}
        msg.update(kwargs)

        if self._reader is not None and self._reader.is_alive():
            q: "queue.Queue" = queue.Queue(maxsize=1)
            with self._router_lock:
                self._router[rid] = q
            try:
                send_message(sock, msg, self._send_lock)
                try:
                    return q.get(timeout=timeout)
                except queue.Empty:
                    raise ServiceError(f"'{cmd}' timed out after {timeout}s")
            finally:
                with self._router_lock:
                    self._router.pop(rid, None)

        # 直收模式 (reader 未启动: hello / init / pump / 非 push 会话)
        with self._send_lock:
            send_message(sock, msg)
            deadline = time.time() + timeout
            while True:
                remain = deadline - time.time()
                if remain <= 0:
                    raise ServiceError(f"'{cmd}' timed out after {timeout}s")
                sock.settimeout(remain)
                reply = recv_message(sock)
                if reply is None:
                    raise ServiceError(
                        f"connection closed while awaiting '{cmd}'")
                if not isinstance(reply, dict):
                    continue
                if reply.get("rid") == rid:
                    return reply
                if reply.get("type") == "block" and self._on_block is not None:
                    self._on_block(reply.get("data"))   # 防御性: 正常流程不会走到

    # ── push 模式接收线程 ──────────────────────────────────

    def _start_reader(self) -> None:
        if self._reader is not None:
            return
        self._reader_stop.clear()
        self._reader = threading.Thread(
            target=self._reader_loop, name=f"eeg-{self.brand}-service",
            daemon=True)
        self._reader.start()

    def _reader_loop(self) -> None:
        sock = self._sock
        if sock is None:
            return
        sock.settimeout(None)   # 阻塞读; 退出靠 socket shutdown/EOF (避免半帧超时)
        from Application.Core.ThreadRegistry import ThreadRegistry

        _reg = f"eeg-{self.brand}-service"
        ThreadRegistry.register(_reg, owner="VirtualDevice.ServiceClient", expect_hz=0.0,
                                note="阻塞 recv; 静默期心跳不推进=正常")
        try:
            while not self._reader_stop.is_set():
                try:
                    msg = recv_message(sock)
                except (OSError, ConnectionError, EOFError):
                    break
                if msg is None:
                    break
                ThreadRegistry.heartbeat(_reg)
                if not isinstance(msg, dict):
                    continue
                if msg.get("type") == "block":
                    cb = self._on_block
                    if cb is not None:
                        cb(msg.get("data"))
                    continue
                rid = msg.get("rid")
                if isinstance(rid, int):
                    with self._router_lock:
                        q = self._router.get(rid)
                    if q is not None:
                        try:
                            q.put_nowait(msg)
                        except queue.Full:
                            pass
        finally:
            ThreadRegistry.unregister(_reg)
