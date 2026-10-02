"""
EEGDevice — 设备层门面 (真实 / 空跑双后端; 含虚拟信号发生器)。

节点求值器只调用本模块的公开 API; 后端路由:
  - device=VIRTUAL → VirtualSigGenBackend (纯软件正弦源; dry_run 控制落盘)
  - dry_run=True   → GtecStubBackend (确定性合成数据; MCP 干跑验证走此路径)
  - dry_run=False  → GtecHiampBackend (pygds; 需 GDS 服务 + 空闲设备)

公开 API:
    init_session(name, cfg, dry_run)          → (session | None, detail)
    start_record(name, elapsed_s)             → (ok, detail)
    stop_record(name, scope, elapsed_s)       → (ok, detail)
    kill_device(name)                         → (ok, detail)
    get_data(name, elapsed_s)                 → (result | None, detail)
    close_all()                               → int        (Runtime 停止保护)
    list_sessions()                           → list[str]

说明:
  - 名称解析: 空名称 + 唯一会话 → 自动绑定; 否则要求显式名称
  - init_session 对同名会话先 kill 旧实例（重复 PIE / 重建图的保护）
  - 真实后端不可用（pygds 缺失 / 无设备）时 init 失败返回 detail, 不抛异常
"""

from __future__ import annotations

from typing import Optional

from .Device import (
    DEVICE_CHOICES,
    EXPORT_FORMATS,
    MAX_BUFFER_SAMPLES,
    MAX_RECORD_BYTES,
    SUPPORTED_RATES,
    TEMPLATE_CHOICES,
    DeviceBackend,
    GtecConfig,
    RecordingSession,
    SaveResult,
    channel_names_for,
    close_all,
    get_session,
    list_sessions,
    register_session,
    resolve_session,
    unregister_session,
)
from .SigGen import SigGenConfig

__all__ = [
    "GtecConfig",
    "SigGenConfig",
    "RecordingSession",
    "SaveResult",
    "DeviceBackend",
    "DEVICE_CHOICES",
    "TEMPLATE_CHOICES",
    "SUPPORTED_RATES",
    "EXPORT_FORMATS",
    "MAX_BUFFER_SAMPLES",
    "MAX_RECORD_BYTES",
    "channel_names_for",
    "init_session",
    "start_record",
    "stop_record",
    "kill_device",
    "get_data",
    "close_all",
    "list_sessions",
    "resolve_session",
    "get_session",
]


# ═══════════════════════════════════════════════════════════════
# 内部
# ═══════════════════════════════════════════════════════════════

def _make_backend(cfg, dry_run: bool) -> DeviceBackend:
    """按配置的设备族路由后端 (VIRTUAL → 虚拟信号发生器; 其余 → Gtec 真实/空跑)。"""
    if getattr(cfg, "device", "HIAMP") == "VIRTUAL":
        from .SigGen import VirtualSigGenBackend

        return VirtualSigGenBackend(dry_run=dry_run)
    if dry_run:
        from .GtecStub import GtecStubBackend

        return GtecStubBackend()
    from .Gtec import GtecHiampBackend

    return GtecHiampBackend()


# ═══════════════════════════════════════════════════════════════
# 公开 API
# ═══════════════════════════════════════════════════════════════

def init_session(name: str, cfg: GtecConfig, dry_run: bool = False):
    """创建并注册一个设备会话（真实或空跑）。

    Returns: (session | None, detail) — detail 为配置摘要或失败原因。
    """
    name = (name or "").strip() or "gtec"
    old = get_session(name)
    if old is not None:
        try:
            old.kill()
        except Exception as e:
            print(f"[Device] replacing session '{name}': kill old failed: {e}")
        unregister_session(name)

    backend = _make_backend(cfg, dry_run)
    session = RecordingSession(name, cfg, backend)
    try:
        backend.configure(cfg)
    except Exception as e:
        try:
            backend.close()
        except Exception:
            pass
        return None, f"init failed: {e}"

    session.backend_info = backend.info()
    register_session(session)
    mode = "stub (dry-run)" if dry_run else "device"
    note = f" | filter note: {cfg.effective_filters()['note']}" if cfg.effective_filters()["note"] else ""
    return session, f"'{name}' ready [{mode}] {cfg.summary()}{note}"


def start_record(name: str, elapsed_s: float = 0.0):
    """开始采集（重复调用无害）。Returns: (ok, detail)。"""
    session, why = resolve_session(name)
    if session is None:
        return False, why
    if session.state == "recording":
        return True, f"'{session.name}' already recording"
    try:
        session.start(elapsed_s)
    except Exception as e:
        return False, f"start failed: {e}"
    return True, f"'{session.name}' recording started"


def stop_record(name: str, save_scope: str = "session", elapsed_s: float = 0.0):
    """停止采集并按配置目录保存数据。Returns: (ok, detail)。"""
    session, why = resolve_session(name)
    if session is None:
        return False, why
    if session.state != "recording":
        return False, f"'{session.name}' is not recording (state={session.state})"
    try:
        result = session.stop(save_scope=save_scope, elapsed_s=elapsed_s)
    except Exception as e:
        return False, f"stop failed: {e}"

    where = " → ".join(result.paths) if result.paths else "(save failed — see console)"
    if result.written:
        detail = (f"'{session.name}' stopped; saved {result.samples} samples "
                  f"({result.duration_s:.2f}s, scope={save_scope}) → {where}")
    else:
        detail = (f"'{session.name}' stopped [dry-run: not written]; "
                  f"would save {result.samples} samples ({result.duration_s:.2f}s, "
                  f"scope={save_scope}) → {where}")
    return True, detail


def kill_device(name: str):
    """停止并释放设备（不保存数据）。Returns: (ok, detail)。"""
    session, why = resolve_session(name)
    if session is None:
        return False, why
    try:
        session.kill()
    except Exception as e:
        unregister_session(session.name)
        return False, f"kill failed: {e}"
    unregister_session(session.name)
    return True, f"'{session.name}' device closed (data discarded)"


def get_data(name: str, elapsed_s: float = 0.0):
    """非销毁读取窗口缓冲副本。Returns: (result | None, detail)。"""
    session, why = resolve_session(name)
    if session is None:
        return None, why
    try:
        return session.get_data(elapsed_s=elapsed_s), ""
    except Exception as e:
        return None, f"get_data failed: {e}"
