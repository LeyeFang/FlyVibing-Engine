"""
EEGDevice — 设备层门面 (品牌目录化: Gtec / VirtualDevice / eCon; 进程 + 协议通信)。

品牌目录 (Functions/EEGDevice/): 品牌 = 独立进程文件应用 (后端 + 服务入口 + 环境)。
节点求值器只调用本模块的公开 API; 后端路由 (_make_backend):
  - 干跑 (dry_run=True)  → 进程内确定性后端 (GtecStub / Virtual dry) — 零进程零副作用
  - 真实 (dry_run=False) → 品牌服务模式 (默认):
        device=VIRTUAL → VirtualDevice 服务 (引擎自动拉起; pump 模式, 确定性)
        其余           → Gtec 服务连接 (外部启动; push 模式; MGE_GTEC_SERVICE)
  - 逃生门: MGE_EEG_TRANSPORT=inproc → 进程内真实后端 (开发/调试)

公开 API:
    init_session(name, cfg, dry_run)          → (session | None, detail)
    start_record(name, elapsed_s, pool)       → (ok, detail)
    stop_record(name, scope, elapsed_s, pool) → (ok, detail)
    kill_device(name, pool)                   → (ok, detail)
    get_data(name, elapsed_s, pool)           → (result | None, detail)
    close_all()                               → int        (Runtime 停止保护)
    list_sessions()                           → list[str]

设备池 API:
    create_pool(name, meta)                   → (ok, detail)   幂等注册
    destroy_pool(name)                        → (ok, detail)   成员回落 global
    add_to_pool(pool, session)                → (ok, detail)   排他成员制 (换池=移动)
    pool_of(session) / pool_members(pool)     → str / list[str]
    list_pools()                              → list[dict]     (含隐式 global)
    reset_pools()                             → int

说明:
  - 名称解析: 空名称 + 唯一会话 → 自动绑定; 否则要求显式名称
  - init_session 对同名会话先 kill 旧实例（重复 PIE / 重建图的保护）
  - 真实后端不可用（pygds 缺失 / 无设备）时 init 失败返回 detail, 不抛异常
"""

from __future__ import annotations

import os
from typing import Optional

from .Device import (
    DEVICE_CHOICES,
    EXPORT_FORMATS,
    GLOBAL_POOL,
    MAX_BUFFER_SAMPLES,
    MAX_RECORD_BYTES,
    SUPPORTED_RATES,
    TEMPLATE_CHOICES,
    DeviceBackend,
    GtecConfig,
    RecordingSession,
    SaveResult,
    add_to_pool,
    channel_names_for,
    close_all,
    create_pool,
    destroy_pool,
    get_session,
    list_pools,
    list_sessions,
    pool_members,
    pool_of,
    register_session,
    reset_pools,
    resolve_session,
    unregister_session,
)
from .VirtualDevice import SigGenConfig

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
    "GLOBAL_POOL",
    "create_pool",
    "destroy_pool",
    "add_to_pool",
    "pool_of",
    "pool_members",
    "list_pools",
    "reset_pools",
]


# ═══════════════════════════════════════════════════════════════
# 内部
# ═══════════════════════════════════════════════════════════════

def _make_backend(cfg, dry_run: bool) -> DeviceBackend:
    """按设备族 + 运行模式路由后端。

    干跑: 进程内确定性合成 (stub / virtual dry) — 无进程、零副作用, 干跑可复现。
    真实: 默认品牌服务模式 (独立进程 + 协议通信);
          环境变量 MGE_EEG_TRANSPORT=inproc 时退回进程内后端 (开发/调试逃生门)。
    """
    device = getattr(cfg, "device", "HIAMP")

    if dry_run:
        if device == "VIRTUAL":
            from .VirtualDevice import VirtualSigGenBackend

            return VirtualSigGenBackend(dry_run=True)
        from .Gtec import GtecStubBackend

        return GtecStubBackend()

    if os.environ.get("MGE_EEG_TRANSPORT", "").strip().lower() == "inproc":
        if device == "VIRTUAL":
            from .VirtualDevice import VirtualSigGenBackend

            return VirtualSigGenBackend(dry_run=False)
        from .Gtec import GtecHiampBackend

        return GtecHiampBackend()

    from .ServiceClient import ServiceBackend

    if device == "VIRTUAL":
        return ServiceBackend.spawn_virtual()
    return ServiceBackend.connect_gtec()


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


def start_record(name: str, elapsed_s: float = 0.0, pool: Optional[str] = None):
    """开始采集（重复调用无害）。pool: 空名称时的池作用域（None=全注册表）。"""
    session, why = resolve_session(name, pool=pool)
    if session is None:
        return False, why
    if session.state == "recording":
        return True, f"'{session.name}' already recording"
    try:
        session.start(elapsed_s)
    except Exception as e:
        return False, f"start failed: {e}"
    return True, f"'{session.name}' recording started"


def stop_record(name: str, save_scope: str = "session", elapsed_s: float = 0.0,
                pool: Optional[str] = None):
    """停止采集并按配置目录保存数据。pool: 空名称时的池作用域（None=全注册表）。"""
    session, why = resolve_session(name, pool=pool)
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


def kill_device(name: str, pool: Optional[str] = None):
    """停止并释放设备（不保存数据）。pool: 空名称时的池作用域（None=全注册表）。"""
    session, why = resolve_session(name, pool=pool)
    if session is None:
        return False, why
    try:
        session.kill()
    except Exception as e:
        unregister_session(session.name)
        return False, f"kill failed: {e}"
    unregister_session(session.name)
    return True, f"'{session.name}' device closed (data discarded)"


def get_data(name: str, elapsed_s: float = 0.0, pool: Optional[str] = None):
    """非销毁读取窗口缓冲副本。pool: 空名称时的池作用域（None=全注册表）。"""
    session, why = resolve_session(name, pool=pool)
    if session is None:
        return None, why
    try:
        return session.get_data(elapsed_s=elapsed_s), ""
    except Exception as e:
        return None, f"get_data failed: {e}"
