"""共享 socket 客户端 — 与运行中的编辑器 `LiveCommandServer` 通信。

被三个消费方共用（同一源码，不 import Application — 边界测试守卫）:
  - server.py  — MCP stdio 服务器（full/lite 档工具底层）
  - cli.py     — `engine-editor-cli`（终端调用，零常驻上下文成本）
  - 脚本模式    — `engine-editor-cli exec script.py` 注入的 EngineClient

协议（详见引擎仓库 Doc/Dev/editor_live_protocol.md §3）:
  NDJSON over 127.0.0.1:8977；回执 result.binary_bytes=N ⇒ 行后紧跟 N 字节二进制尾帧。

环境变量:
  MGE_EDITOR_MCP_PORT  引擎命令端口（默认 8977；两侧需一致）
  MGE_MCP_FRAMES_DIR   抓帧根目录（默认 <临时目录>/engine_editor_mcp）
"""

from __future__ import annotations

import io
import json
import os
import shutil
import socket
import tempfile
import time
from typing import Any

DEFAULT_PORT = 8977
_ENV_PORT = "MGE_EDITOR_MCP_PORT"
_ENV_FRAMES_DIR = "MGE_MCP_FRAMES_DIR"
_next_id = [0]

# ── 抓帧临时目录（默认用户临时目录; MGE_MCP_FRAMES_DIR 可覆盖）──
# 策略: 每次 server 启动清空, 防累积（仅入口进程执行 — 见 wipe_frames_dir）。
_FRAMES_ROOT = os.environ.get(_ENV_FRAMES_DIR) or os.path.join(
    tempfile.gettempdir(), "engine_editor_mcp"
)
FRAMES_DIR = os.path.join(_FRAMES_ROOT, "frames")


def wipe_frames_dir() -> None:
    """清空抓帧目录（server 启动时调用 — 仅入口进程执行，import 不清空）。"""
    shutil.rmtree(_FRAMES_ROOT, ignore_errors=True)
    os.makedirs(FRAMES_DIR, exist_ok=True)


def editor_port() -> int:
    try:
        return int(os.environ.get(_ENV_PORT, "") or DEFAULT_PORT)
    except ValueError:
        return DEFAULT_PORT


def send_raw(op: str, args: dict | None = None, timeout: float = 15.0) -> tuple[dict, bytes | None]:
    """向编辑器发送一条命令并等待回执; 就绪帧随二进制尾随负载返回。

    Returns:
        (result_or_error, payload) — 失败时 result 含 "error" 键、payload 为 None。
    """
    _next_id[0] += 1
    req = {"id": _next_id[0], "op": op, "args": args or {}}
    port = editor_port()
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout) as conn:
            conn.sendall((json.dumps(req, ensure_ascii=False) + "\n").encode("utf-8"))
            reader = conn.makefile("rb")
            line = reader.readline()
            if not line:
                return {"error": "编辑器连接被关闭（可能正在退出）"}, None
            resp = json.loads(line.decode("utf-8"))
            if not resp.get("ok"):
                return {"error": resp.get("error") or "unknown editor error"}, None
            result = resp.get("result") or {"ok": True}
            payload = None
            if isinstance(result, dict) and result.get("binary_bytes"):
                n = int(result["binary_bytes"])
                payload = reader.read(n)
                if payload is None or len(payload) != n:
                    return {"error": f"二进制负载不完整（{len(payload or b'')}/{n} bytes）"}, None
            return result, payload
    except ConnectionRefusedError:
        return {"error": f"编辑器未运行（127.0.0.1:{port} 无监听）— 请先启动 startup.bat。"}, None
    except (socket.timeout, TimeoutError):
        return {"error": f"等待编辑器响应超时（{timeout}s）— 编辑器可能未在处理帧。"}, None
    except ValueError as e:
        return {"error": f"无法解析编辑器回执: {e}"}, None
    except OSError as e:
        return {"error": f"连接失败: {e}"}, None


def send(op: str, args: dict | None = None, timeout: float = 15.0) -> dict:
    """薄包装（非图像场景）— 保持 v1 工具的 dict 返回契约。"""
    result, _payload = send_raw(op, args, timeout)
    return result


# ── 抓帧: request → 轮询 fetch → 翻转 → PNG（本进程编码, 不阻塞引擎）──


def encode_and_save(target: str, result: dict, payload: bytes) -> tuple[str, bytes]:
    """RGBA8 裸帧（bottom-up）→ top-down → PNG → 落盘。返回 (path, png_bytes)。"""
    import numpy as np
    from PIL import Image as PILImage

    width = int(result["width"])
    height = int(result["height"])
    arr = np.frombuffer(payload, dtype=np.uint8).reshape(height, width, 4)[::-1]
    png_buf = io.BytesIO()
    PILImage.frombytes("RGBA", (width, height), np.ascontiguousarray(arr).tobytes()).save(png_buf, "PNG")
    png_bytes = png_buf.getvalue()
    ts = time.strftime("%Y%m%d_%H%M%S")
    path = os.path.join(FRAMES_DIR, f"frame_{target}_{ts}_g{result.get('generation')}.png")
    with open(path, "wb") as fp:
        fp.write(png_bytes)
    return path, png_bytes


def fetch_raw_frame(target: str = "editor", timeout_s: float = 6.0) -> dict:
    """抓帧并返回裸帧（不编码 PNG）。

    Returns: {"width", "height", "payload": bytes(RGBA8, bottom-up), "generation"}
    像素采样（probe）与 PNG 落盘（capture）共用此流程。
    """
    result, _ = send_raw("frame.request", {"target": target})
    if "error" in result:
        raise EngineError(result["error"])
    generation = result.get("generation")

    deadline = time.monotonic() + float(timeout_s)
    while time.monotonic() < deadline:
        info, payload = send_raw("frame.fetch", {"target": target, "generation": generation})
        if "error" in info:
            raise EngineError(info["error"])
        if info.get("ready"):
            if payload is None:
                raise EngineError("ready frame without payload")
            return {"width": int(info["width"]), "height": int(info["height"]),
                    "payload": payload, "generation": info.get("generation")}
        state = info.get("state")
        if state == "error":
            raise EngineError(info.get("error") or "engine-side capture failed")
        if state == "superseded":
            raise EngineError(f"capture superseded (latest_generation={info.get('latest_generation')})")
        time.sleep(0.03)
    raise EngineError(f"capture timeout after {timeout_s}s (generation={generation})")


def capture_png(target: str = "editor", timeout_s: float = 6.0) -> tuple[str, bytes]:
    """完整抓帧流程: 裸帧 → 翻转 → PNG 落盘。返回 (path, png_bytes)。"""
    frame = fetch_raw_frame(target, timeout_s)
    return encode_and_save(target, frame, frame["payload"])


# ── 脚本模式客户端（engine-editor-cli exec 注入）──


class EngineError(RuntimeError):
    """编辑器操作失败（传输/引擎侧错误），供脚本模式 raise。"""


class EngineClient:
    """供 `engine-editor-cli exec` 脚本使用的编程接口（同步、无状态）。

    典型脚本:
        eng = engine                       # exec 注入的全局对象
        st = eng.ok("sim.state")           # 失败 raise EngineError
        n = eng.try_send("entity.list")    # 失败返回 {"error": ...}
        path = eng.capture("editor")       # 抓帧 → PNG 路径
    """

    def __init__(self, timeout: float = 15.0) -> None:
        self.timeout = float(timeout)

    def try_send(self, op: str, **args: Any) -> dict:
        """发送 op；永不 raise — 失败返回 {"error": "..."}。"""
        result, _payload = send_raw(op, args or None, self.timeout)
        return result

    def ok(self, op: str, **args: Any) -> dict:
        """发送 op；失败 raise EngineError，成功返回 result dict。"""
        result = self.try_send(op, **args)
        if "error" in result:
            raise EngineError(f"{op}: {result['error']}")
        return result

    def batch(self, calls: list, continue_on_error: bool = False) -> list[dict]:
        """顺序执行多个 op（call 为 (op, args) 或 {"op","args"}）。"""
        results: list[dict] = []
        for call in calls:
            if isinstance(call, dict):
                op, args = str(call.get("op", "")), dict(call.get("args") or {})
            else:
                op, args = str(call[0]), dict(call[1] or {})
            result = self.try_send(op, **args)
            results.append(result)
            if "error" in result and not continue_on_error:
                break
        return results

    def capture(self, target: str = "editor", timeout_s: float = 6.0) -> str:
        """抓帧 → PNG 落盘；返回绝对路径（失败 raise）。"""
        path, _png = capture_png(target, timeout_s)
        return path


# ── agent 共用编排（CLI / lite MCP；无 GUI 即可调用的控制流）──


def execute_calls(calls: list, continue_on_error: bool = False) -> list[dict]:
    """顺序执行多个 op（call 为 (op, args) 或 {"op", "args"}）— 与 MCP engine_batch 同语义。"""
    from . import ops as op_registry

    results: list[dict] = []
    for call in calls or []:
        if isinstance(call, dict):
            op, call_args = str(call.get("op", "")), dict(call.get("args") or {})
        else:
            op, call_args = str(call[0]), dict(call[1] or {})
        name, defaults = op_registry.resolve(op)
        if not name:
            entry: dict = {"error": f"unknown op: {op!r}"}
        else:
            merged = dict(defaults)
            merged.update(call_args)
            merged = op_registry.prepare_args(name, merged)
            entry, _payload = send_raw(name, merged, timeout=op_registry.call_timeout(name))
            unknown = op_registry.unknown_args(name, merged)
            if unknown and "error" not in entry:
                entry = dict(entry)
                entry["_unknown_args"] = unknown
        results.append(entry)
        if "error" in entry and not continue_on_error:
            break
    return results


def validate_graph_orchestrate(
    source: str = "canvas",
    graph: dict | None = None,
    frames: int = 360,
    verbose: bool = True,
    seed: int = 0,
    save_path: str | None = None,
    timeout_s: float = 120.0,
) -> dict:
    """校验编排（start→poll→report）— MCP 工具与 CLI validate 共用（同一引擎内服务）。"""
    args: dict = {"source": source, "frames": frames, "verbose": verbose, "seed": seed}
    if graph is not None:
        args["graph"] = graph
    started, _ = send_raw("graph.validate.start", args)
    if "error" in started:
        return started
    task_id = started.get("task_id")
    if not started.get("started"):
        return {**started, "note": "任务已在运行 — 先 cancel（graph.validate.cancel）或等待完成"}

    deadline = time.monotonic() + float(timeout_s)
    while time.monotonic() < deadline:
        st, _ = send_raw("graph.validate.state", {"task_id": task_id})
        if "error" in st:
            return st
        if st.get("state") != "running":
            break
        time.sleep(0.1)
    else:
        return {
            "state": "running",
            "task_id": task_id,
            "note": f"超出 {timeout_s}s 仍在运行 — 稍后用 graph.validate.report 取回（task_id={task_id}）",
        }

    rargs: dict = {"task_id": task_id}
    if save_path:
        rargs["save_path"] = save_path
    result, _ = send_raw("graph.validate.report", rargs)
    return result
