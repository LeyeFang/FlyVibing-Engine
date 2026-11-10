"""PortLedger — 本机开发实例的端口台账（谁占了端口 / 为什么 / 会碰什么）。

问题:
  端口被占时，后来者（另一个 agent、另一个编辑器）只能看到「连不上」，无法判断
  占用者是谁、在做什么、会不会读写同一个工程；于是只能硬撞端口，冲突暴露得太晚
  （两个 agent 抢同一个工程 / 同一个 PIE 窗口）。

做法:
  每个开发实例启动时在共享目录写一份 JSON（`<tmp>/engine_editor_mcp/ports/<port>.json`），
  端口释放 / 进程退出时删除。读取方（`engine-editor-cli ports` / `launch`）据此区分
  「空闲 / 已登记 / 未登记占用」，并直接读到占用者的**目的**与**涉及内容**。

容器格式 v1（引擎与工具仓各有一份读写实现，字段必须一致；往返校验见
`Test/Application/Editor/test_port_ledger.py`）:

    {"schema": 1, "port": 8978, "kind": "editor", "status": "ready"|"starting",
     "pid": 12345, "started_at": ISO8601, "updated_at": ISO8601,
     "purpose": "一句话目的（给后来者看）", "owner": "agent:xxx / user",
     "tags": ["ui", "pie"],
     "project": 绝对路径, "project_name": str, "scene": str,
     "touches": ["可能被写入的目录/文件 — 后来者据此避免同目录并发"],
     "notes": "给后来者的提醒（如：别在此实例跑全量测试）",
     "engine_root": 绝对路径, "engine_version": str, "log_path": str}

纪律:
  - **只写/删自己的条目**：删除前校验 pid，不误删别人的台账；
  - 写入走临时文件 + `os.replace`（读者永不见半截 JSON）；
  - 目录可用 `FVE_PORT_LEDGER_DIR` / `MGE_PORT_LEDGER_DIR` 覆盖（测试隔离），
    `FVE_PORT_LEDGER=0` 关闭写入；
  - 进程崩溃留下的条目由读取方按「端口是否仍在监听」判为 stale，不阻塞选端口。
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime
from pathlib import Path

from Application.Core.AppIdentity import env_get

SCHEMA = 1

_ENV_DIR = "PORT_LEDGER_DIR"
_ENV_OFF = "PORT_LEDGER"
_SUBDIR = "engine_editor_mcp"
_PORTS_SUBDIR = "ports"

_lock = threading.Lock()
_state: dict = {"port": 0, "entry": {}}       # 本进程当前登记的条目
_meta: dict = {}                              # 启动参数带来的人工描述（未落盘前）


# ── 路径与开关 ──────────────────────────────────────────────


def ledger_enabled() -> bool:
    raw = (env_get(_ENV_OFF) or "").strip().lower()
    return raw not in ("0", "false", "off", "no")


def ledger_dir() -> Path:
    """台账目录（`FVE_PORT_LEDGER_DIR` 可覆盖；默认在系统临时目录下）。"""
    override = (env_get(_ENV_DIR) or "").strip()
    base = Path(override) if override else Path(tempfile.gettempdir()) / _SUBDIR
    return base / _PORTS_SUBDIR


def entry_path(port: int) -> Path:
    return ledger_dir() / f"{int(port)}.json"


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _engine_root() -> str:
    try:
        return str(Path(__file__).resolve().parents[3])
    except (IndexError, OSError):
        return ""


def _engine_version() -> str:
    """`pyproject.toml` 的 version（读不到就空串 — 台账不因版本信息缺失而失败）。"""
    try:
        text = (Path(_engine_root()) / "pyproject.toml").read_text(encoding="utf-8")
        for line in text.splitlines():
            if line.strip().startswith("version"):
                _, _, value = line.partition("=")
                return value.strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


# ── 单条读写（供引擎与测试使用）────────────────────────────


def _read_file(path: Path) -> dict | None:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        return None
    return data


def read(port: int) -> dict | None:
    """读某个端口的台账条目（无/损坏/版本不符 → None）。"""
    return _read_file(entry_path(port))


def write(entry: dict) -> Path | None:
    """原子写一条台账（调用方负责填 port/pid/schema）。"""
    if not ledger_enabled():
        return None
    payload = dict(entry)
    payload["schema"] = SCHEMA
    payload.setdefault("updated_at", _now())
    target = entry_path(int(payload["port"]))
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=f".{target.name}.", dir=str(target.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, target)
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except OSError:
        return None
    return target


def remove(port: int, pid: int | None = None) -> bool:
    """删除某端口台账；给了 pid 时只删属于该进程的条目（不误删别人）。"""
    path = entry_path(port)
    if pid is not None:
        current = _read_file(path)
        if current is None or int(current.get("pid") or 0) not in (0, int(pid)):
            return False
    try:
        path.unlink()
        return True
    except OSError:
        return False


# ── 本进程生命周期 ──────────────────────────────────────────


def configure(**fields) -> dict:
    """记录启动参数带来的描述（`--purpose` / `--owner` / `--tag`）。

    未注册端口前先存内存；注册时并入条目（显式传入的字段优先）。
    """
    for key, value in fields.items():
        if value not in (None, "", [], ()):
            _meta[key] = value
    return dict(_meta)


def register(port: int, **extra) -> dict | None:
    """登记本进程的端口（编辑器启动 / 测试）。返回写入的条目。"""
    port = int(port or 0)
    if port <= 0:
        return None
    # 只继承「launcher 预登记」的条目（status=starting）: 那是本次启动的意图;
    # 崩溃残留的旧条目一律不继承，否则会在新实例上显示上一个实例的目的。
    previous = read(port) or {}
    if previous.get("status") != "starting":
        previous = {}
    project = _current_project()
    entry = {
        "port": port,
        "kind": "editor",
        "status": "ready",
        "pid": os.getpid(),
        "started_at": previous.get("started_at") or _now(),
        "purpose": previous.get("purpose", ""),
        "owner": previous.get("owner", ""),
        "tags": list(previous.get("tags") or []),
        "touches": list(previous.get("touches") or []),
        "notes": previous.get("notes", ""),
        # 环境变量是「跨进程传递启动意图」的正规通道（launcher 设置、引擎读取）
        "engine_root": _engine_root(),
        "engine_version": _engine_version(),
    }
    env_purpose = (env_get("INSTANCE_PURPOSE") or "").strip()
    env_owner = (env_get("INSTANCE_OWNER") or "").strip()
    env_tags = (env_get("INSTANCE_TAGS") or "").strip()
    if env_purpose:
        entry["purpose"] = env_purpose
    if env_owner:
        entry["owner"] = env_owner
    if env_tags:
        entry["tags"] = [t.strip() for t in env_tags.split(",") if t.strip()]
    for key in ("purpose", "owner", "tags", "touches", "notes"):
        if _meta.get(key):
            entry[key] = _meta[key]
    if project:
        entry.update(project)
    entry.update({k: v for k, v in extra.items() if v not in (None, "")})
    if not entry.get("purpose"):
        entry["purpose"] = _default_purpose(entry)
    with _lock:
        _state["port"] = port
        _state["entry"] = entry
    write(entry)
    return entry


def update(**fields) -> dict | None:
    """更新本进程条目（工程打开 / 场景切换 / 目的改写）。未登记则忽略。"""
    with _lock:
        entry = dict(_state.get("entry") or {})
        port = int(_state.get("port") or 0)
    if not entry or port <= 0:
        return None
    entry.update({k: v for k, v in fields.items() if v is not None})
    with _lock:
        _state["entry"] = entry
    return entry if write(entry) else None


def unregister() -> bool:
    """删除本进程条目（编辑器退出 / 服务停止）。"""
    with _lock:
        port = int(_state.get("port") or 0)
        _state["port"] = 0
        _state["entry"] = {}
    if port <= 0:
        return False
    return remove(port, pid=os.getpid())


def current() -> dict | None:
    """本进程当前登记的内容（未登记 → None）。只读副本。"""
    with _lock:
        entry = dict(_state.get("entry") or {})
    return entry or None


# ── 描述辅助 ────────────────────────────────────────────────


def _current_project() -> dict:
    """当前工程 / 场景（编辑器未打开工程时为空 — 不阻塞登记）。"""
    info: dict = {}
    try:
        from Application.Editor.ProjectManager import ProjectManager
        if ProjectManager.is_open():
            info["project"] = str(ProjectManager.get_project_path() or "")
            info["project_name"] = str(ProjectManager.get_project_name() or "")
    except Exception:  # noqa: BLE001 — 无头环境 / 工程模块不可用
        return {}
    try:
        from Application.Editor.UI.controllers.SceneBrowserController import (
            SceneBrowserController,
        )
        active = SceneBrowserController.get_active_scene_name()
        if active:
            info["scene"] = str(active)
    except Exception:  # noqa: BLE001
        pass
    return {k: v for k, v in info.items() if v}


def _default_purpose(entry: dict) -> str:
    name = entry.get("project_name") or "未打开工程"
    return f"编辑器实例（{name}）"


__all__ = [
    "SCHEMA",
    "configure",
    "current",
    "entry_path",
    "ledger_dir",
    "ledger_enabled",
    "read",
    "register",
    "remove",
    "unregister",
    "update",
    "write",
]
