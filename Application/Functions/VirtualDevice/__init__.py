"""
VirtualDevice — 设备层门面（虚拟信号发生器设备族的完整模块; 进程 + 协议通信）。

模块布局 (Application/Functions/VirtualDevice/): 单目录自包含设备模块 —
  面板 extension.py / 显示 virtual_display.py / 示波器 virtual_scope.py
  会话核心 Device.py / 服务协议 ServiceProtocol+Host+Client.py
  后端 SigGen.py / 服务入口 service.py
节点求值器只调用本模块的公开 API; 后端路由 (_make_backend):
  - 干跑 (dry_run=True)  → 进程内确定性 stub 后端 — 零进程零副作用
  - 真实 (dry_run=False) → 服务进程模式 (默认; VIRTUAL 服务, 引擎自动拉起, pump 模式, 确定性)
  - 逃生门: MGE_EEG_TRANSPORT=inproc → 进程内真实后端 (开发/调试)
  - 外部品牌设备        → 经同一服务协议接入 (MGE_EEG_SERVICE 显式端点; 后端未随
                          仓库分发时显式报错, 绝不静默回退)

公开 API:
    init_session(name, cfg, dry_run)          → (session | None, detail)
    start_record(name, elapsed_s, pool, record) → (ok, detail)   record=False = 仅监视
    stop_record(name, scope, elapsed_s, pool, save) → (ok, detail)   save=False = 弃录
    kill_device(name, pool)                   → (ok, detail)
    get_data(name, elapsed_s, pool)           → (result | None, detail)
    measure_impedance(name, electrode_type, tms_box, pool) → (result | None, detail)
    get_trigger_events(name, start, pool)      → (dict | None, detail)  触发事件快照
    probe_brand_service(endpoint)              → dict   (品牌服务连通性探测, 不建会话)
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
  - 真实后端不可用（后端缺失 / 无设备）时 init 失败返回 detail, 不抛异常
"""

from __future__ import annotations

import os
from typing import Optional

from .Device import (
    DEVICE_CHOICES,
    EXPORT_FORMATS,
    GLOBAL_POOL,
    IMPEDANCE_ELECTRODE_TYPES,
    IMPEDANCE_THRESHOLDS_KOHM,
    MAX_BUFFER_SAMPLES,
    MAX_RECORD_BYTES,
    SUPPORTED_RATES,
    TEMPLATE_CHOICES,
    DeviceBackend,
    DeviceConfig,
    RecordingSession,
    SaveResult,
    add_to_pool,
    channel_names_for,
    classify_impedance,
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
from .SigGen import SigGenConfig, VirtualSigGenBackend
from .ServiceClient import probe_brand_service

__all__ = [
    "DeviceConfig",
    "SigGenConfig",
    "VirtualSigGenBackend",
    "RecordingSession",
    "SaveResult",
    "DeviceBackend",
    "DEVICE_CHOICES",
    "TEMPLATE_CHOICES",
    "SUPPORTED_RATES",
    "EXPORT_FORMATS",
    "MAX_BUFFER_SAMPLES",
    "MAX_RECORD_BYTES",
    "IMPEDANCE_ELECTRODE_TYPES",
    "IMPEDANCE_THRESHOLDS_KOHM",
    "classify_impedance",
    "channel_names_for",
    "init_session",
    "start_record",
    "stop_record",
    "measure_impedance",
    "get_trigger_events",
    "probe_brand_service",
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

    干跑: 进程内确定性 stub — 无进程、零副作用, 干跑可复现。
    真实: 默认品牌服务模式 (独立进程 + 协议通信);
          环境变量 MGE_EEG_TRANSPORT=inproc 时退回进程内后端 (开发/调试逃生门)。
    无对应品牌后端 (未随仓库分发的品牌) → 显式报错，绝不静默回退。
    """
    device = str(getattr(cfg, "device", "VIRTUAL")).upper()

    if dry_run:
        from .SigGen import VirtualSigGenBackend

        return VirtualSigGenBackend(dry_run=True)

    if os.environ.get("MGE_EEG_TRANSPORT", "").strip().lower() == "inproc":
        if device == "VIRTUAL":
            from .SigGen import VirtualSigGenBackend

            return VirtualSigGenBackend(dry_run=False)
        raise ValueError(f"no in-process backend for device family {device!r}")

    from .ServiceClient import ServiceBackend

    if device == "VIRTUAL":
        return ServiceBackend.spawn_virtual()
    return ServiceBackend.connect_brand(
        python_exe=getattr(cfg, "service_python", "") or None,
        module=getattr(cfg, "service_module", "") or "")


# ═══════════════════════════════════════════════════════════════
# 公开 API
# ═══════════════════════════════════════════════════════════════

def init_session(name: str, cfg: DeviceConfig, dry_run: bool = False):
    """创建并注册一个设备会话（真实或空跑）。

    Returns: (session | None, detail) — detail 为配置摘要或失败原因。
    """
    name = (name or "").strip() or "eeg"
    old = get_session(name)
    if old is not None:
        try:
            old.kill()
        except Exception as e:
            print(f"[Device] replacing session '{name}': kill old failed: {e}")
        unregister_session(name)

    try:
        backend = _make_backend(cfg, dry_run)
    except Exception as e:  # 未支持设备族 / 后端缺失 — 履行“init 失败返回 detail”契约
        return None, f"init failed: {e}"
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


def start_record(name: str, elapsed_s: float = 0.0, pool: Optional[str] = None,
                 record: bool = True):
    """开始流式采集（重复调用无害）。pool: 空名称时的池作用域（None=全注册表）。

    record=True  → 录制（含监视）; record=False → 仅监视（不累积全量录制, 不落盘）。
    监视中再调 record=True → 从当前时刻起录制（升级; 已过去的监视段不保存）。
    """
    session, why = resolve_session(name, pool=pool)
    if session is None:
        return False, why
    if session.state == "recording":
        return True, f"'{session.name}' already recording"
    if session.state == "monitoring":
        if not record:
            return True, f"'{session.name}' already monitoring"
        try:
            session.begin_recording(elapsed_s)
        except Exception as e:
            return False, f"record failed: {e}"
        return True, f"'{session.name}' recording started (from monitoring)"
    try:
        session.start(elapsed_s, record=record)
    except Exception as e:
        return False, f"start failed: {e}"
    return True, f"'{session.name}' {'recording' if record else 'monitoring'} started"


def stop_record(name: str, save_scope: str = "session", elapsed_s: float = 0.0,
                pool: Optional[str] = None, save: bool = True):
    """停止流式采集（recording → 按 scope 保存; 监视/显式 save=False 不落盘）。

    pool: 空名称时的池作用域（None=全注册表）。
    """
    session, why = resolve_session(name, pool=pool)
    if session is None:
        return False, why
    if session.state not in ("recording", "monitoring"):
        return False, f"'{session.name}' is not streaming (state={session.state})"
    was_recording = session.state == "recording"
    do_save = bool(save) and was_recording
    try:
        result = session.stop(save_scope=save_scope, elapsed_s=elapsed_s, save=do_save)
    except Exception as e:
        return False, f"stop failed: {e}"
    if not was_recording:
        return True, f"'{session.name}' monitoring stopped (nothing recorded)"
    if not do_save:
        return True, (f"'{session.name}' stopped; recording discarded "
                      f"({result.samples} samples, {result.duration_s:.2f}s)")

    where = " → ".join(result.paths) if result.paths else "(save failed — see console)"
    if result.written:
        detail = (f"'{session.name}' stopped; saved {result.samples} samples "
                  f"({result.duration_s:.2f}s, scope={save_scope}) → {where}")
    else:
        detail = (f"'{session.name}' stopped [dry-run: not written]; "
                  f"would save {result.samples} samples ({result.duration_s:.2f}s, "
                  f"scope={save_scope}) → {where}")
    return True, detail


def get_trigger_events(name: str, start: int = 0, pool: Optional[str] = None):
    """触发事件（附加通道沿变提取 — 线程安全快照; start = 起始下标）。"""
    session, why = resolve_session(name, pool=pool)
    if session is None:
        return None, why
    return session.get_trigger_events(start), ""


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


def measure_impedance(name: str, electrode_type: str = "passive",
                      tms_box: bool = False, pool: Optional[str] = None):
    """测量电极阻抗（设备空闲操作 — 采集中返回失败）。

    Returns: (result | None, detail) — result 见 RecordingSession.measure_impedance。
    """
    session, why = resolve_session(name, pool=pool)
    if session is None:
        return None, why
    try:
        return session.measure_impedance(electrode_type, tms_box), ""
    except Exception as e:
        return None, f"impedance failed: {e}"
