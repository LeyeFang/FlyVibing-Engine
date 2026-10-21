"""
Test: VirtualDevice (SigGen) — 虚拟信号发生器: 配置 / 会话 / 落盘 / 干跑 / 配对
═══════════════════════════════════════════════════════════════

测试范围:
  - SigGenConfig 解析 / 钳位 (channels / rate / frequency / step / amp / noise)
  - 虚拟后端会话生命周期:
      dry-run: init → start → get → stop(不落盘) → kill, 确定性可复现
      REAL   : init → start → get → stop(落盘 npz+json) → kill, 正弦频率/幅度可验证
  - 节点图干跑 (MCP validate_graph 同路径): Init→Start→Get→Stop→Kill 全链路
  - Init/Kill 强制配对: 静态校验错误 + 编辑器删除级联 (含与设备池混合场景)
  - 触发链路: 附加通道事件 (get_trigger_events / meta) + 合成触发 (trigger_every_s)
    + 服务自动拉起透传 (service_module / MGE_EEG_SERVICE_MODULE)

运行: python Test/Application/Functions/test_siggen_device.py
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time

# ── path setup ──
_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, '_path_setup.py')):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)
import _path_setup  # noqa: E402

import numpy as np

from Application.Functions.VirtualDevice import (
    DeviceConfig,
    SigGenConfig,
    close_all,
    get_data,
    get_trigger_events,
    init_session,
    kill_device,
    list_sessions,
    start_record,
    stop_record,
)
from Application.Functions.VirtualDevice.ServiceClient import ServiceBackend
from Application.Core.NodeGraph import NodeCanvas
from Application.Core.NodeGraph.graph_constraints import (
    device_cascade_deletes,
    siggen_cascade_deletes,
    siggen_pairing_errors,
)
from flyvibing_node_editor.graph_builder import GraphBuilder
from flyvibing_node_editor.node_graph_validator import validate_static

_PASS = 0
_FAIL = 0


def check(cond: bool, name: str) -> bool:
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print(f"  [PASS] {name}")
    else:
        _FAIL += 1
        print(f"  [FAIL] {name}")
    return cond


def _peak_freq(signal: np.ndarray, fs: int) -> float:
    """FFT 峰值频率 (Hz) — 用于验证正弦频率。"""
    n = len(signal)
    spec = np.abs(np.fft.rfft(signal * np.hanning(n)))
    freqs = np.fft.rfftfreq(n, d=1.0 / fs)
    return float(freqs[int(np.argmax(spec))])


# ═══════════════════════════════════════════════════════════════
# 1. 配置解析 / 钳位
# ═══════════════════════════════════════════════════════════════

def test_config_semantics():
    print("── SigGenConfig semantics ──")

    cfg = SigGenConfig.from_props({})
    check(cfg.channels == 8 and cfg.sampling_rate == 512, "defaults 8ch @512")
    check(cfg.frequency == 10.0 and cfg.freq_step == 2.0, "default f0=10 dF=2")
    check(cfg.amplitude_uv == 50.0 and cfg.noise_uv == 0.0, "default amp=50 noise=0")
    check(cfg.buffer_capacity() == 5120, f"capacity 10s@512 = {cfg.buffer_capacity()}")
    check(cfg.template == "8ch", "template property '8ch'")
    check("VIRTUAL" in cfg.summary(), "summary contains VIRTUAL")

    cfg = SigGenConfig.from_props({"frequency": -5.0})
    check(cfg.frequency == 10.0, "f0 <=0 → default 10")

    cfg = SigGenConfig.from_props({
        "channels": 0, "sampling_rate": -1,
        "freq_step": -1.0, "amplitude_uv": -3.0, "noise_uv": -2.0,
        "export_format": "docx", "buffer_seconds": -5.0,
    })
    check(cfg.channels == 1, "channels clamped to >=1")
    check(cfg.sampling_rate == 1, "rate clamped to >=1")
    check(cfg.frequency == 0.5, "f0 Nyquist-clamped by rate=1 (=0.5)")
    check(cfg.freq_step == 0.0, "step <0 → 0")
    check(cfg.amplitude_uv == 0.0 and cfg.noise_uv == 0.0, "amp/noise <0 → 0")
    check(cfg.export_format == "npz", "bad format → npz")
    check(cfg.buffer_seconds >= 0.1, "buffer clamped >= 0.1")

    cfg = SigGenConfig.from_props({
        "channels": 9999, "sampling_rate": 99999, "frequency": 100000.0,
    })
    check(cfg.channels == 256, "channels clamped to 256")
    check(cfg.sampling_rate == 38400, "rate clamped to 38400")
    check(cfg.frequency <= cfg.sampling_rate / 2.0, "f0 clamped to Nyquist")


# ═══════════════════════════════════════════════════════════════
# 2. 干跑会话生命周期 (确定性, 不落盘)
# ═══════════════════════════════════════════════════════════════

def _dry_run_once() -> np.ndarray:
    """一次完整干跑会话 → 返回窗口数据 (用于确定性对比)。"""
    close_all()
    cfg = SigGenConfig.from_props({
        "device_name": "SG1", "channels": 4, "sampling_rate": 512,
        "frequency": 10.0, "freq_step": 5.0, "amplitude_uv": 50.0,
        "buffer_seconds": 1.0,
    })
    session, _ = init_session("SG1", cfg, dry_run=True)
    assert session is not None
    start_record("SG1", elapsed_s=0.5)
    result, _ = get_data("SG1", elapsed_s=1.5)
    assert result is not None
    data = result["data"]
    stop_record("SG1", save_scope="session", elapsed_s=1.5)
    kill_device("SG1")
    return data


def test_dry_session_lifecycle():
    print("── Dry-run session lifecycle ──")
    close_all()

    cfg = SigGenConfig.from_props({
        "device_name": "SG1", "channels": 4, "sampling_rate": 512,
        "frequency": 10.0, "freq_step": 5.0, "buffer_seconds": 1.0,
    })
    session, detail = init_session("SG1", cfg, dry_run=True)
    check(session is not None, f"init_session ok ({detail[:60]}...)")
    check("VIRTUAL" in detail, "init detail contains VIRTUAL summary")
    check(list_sessions() == ["SG1"], f"registered: {list_sessions()}")

    ok, _ = start_record("SG1", elapsed_s=0.5)
    check(ok, "start_record ok")

    result, why = get_data("SG1", elapsed_s=1.5)
    check(result is not None, f"get_data ok ({why})")
    if result:
        data = result["data"]
        check(data.shape == (4, 512), f"shape (channels, capacity) = {data.shape}")
        check(data.dtype == np.float32, f"dtype {data.dtype}")
        check(result["samples"] == 512, f"valid samples = {result['samples']}")
        check(result["stub"] is True, "dry-run stub flag True")
        valid = data[0, :512]
        peak0 = _peak_freq(valid, 512)
        check(abs(peak0 - 10.0) <= 1.5, f"ch0 sine peak ≈10Hz (got {peak0})")
        peak1 = _peak_freq(data[1, :512], 512)
        check(abs(peak1 - 15.0) <= 1.5, f"ch1 sine peak ≈15Hz (got {peak1})")
        check(45.0 <= float(np.abs(valid).max()) <= 55.0,
              f"amplitude ~50uV (max {float(np.abs(valid).max()):.1f})")

    ok, detail = stop_record("SG1", save_scope="session", elapsed_s=1.5)
    check(ok and "dry-run" in detail and ".npz" in detail,
          "stop plans npz path without writing")

    ok, _ = kill_device("SG1")
    check(ok and list_sessions() == [], "kill unregisters session")

    ok, detail = start_record("NOPE")
    check(not ok and "not registered" in detail, f"unknown device error: {detail}")
    check(close_all() == 0, "close_all on empty registry = 0")

    a = _dry_run_once()
    b = _dry_run_once()
    check(a.shape == b.shape and np.array_equal(a, b),
          "dry-run deterministic (same array)")


# ═══════════════════════════════════════════════════════════════
# 3. 真实会话生命周期 (落盘验证)
# ═══════════════════════════════════════════════════════════════

def test_live_session_lifecycle():
    print("── Live session lifecycle (write to disk) ──")
    close_all()
    tmp = tempfile.mkdtemp(prefix="siggen_test_")
    try:
        cfg = SigGenConfig.from_props({
            "device_name": "SG2", "channels": 4, "sampling_rate": 512,
            "frequency": 10.0, "freq_step": 5.0, "amplitude_uv": 50.0,
            "save_dir": tmp, "buffer_seconds": 1.0,
        })
        session, detail = init_session("SG2", cfg, dry_run=False)
        check(session is not None, f"live init ok ({detail[:60]}...)")

        start_record("SG2", elapsed_s=0.0)
        result, _ = get_data("SG2", elapsed_s=0.5)
        check(result is not None and result["stub"] is False, "live get_data stub=False")

        ok, detail = stop_record("SG2", save_scope="session", elapsed_s=1.2)
        check(ok and "saved" in detail, f"live stop wrote files ({detail[:80]}...)")

        files = sorted(os.listdir(tmp))
        npz_files = [f for f in files if f.endswith(".npz")]
        json_files = [f for f in files if f.endswith(".json")]
        check(len(npz_files) == 1 and len(json_files) == 1,
              f"npz + json written ({files})")

        if npz_files:
            with np.load(os.path.join(tmp, npz_files[0])) as npz:
                data = npz["data"]
                fs = int(npz["fs"])
                names = list(npz["channel_names"])
            check(data.ndim == 2 and data.shape[1] == 4, f"data shape {data.shape}")
            check(fs == 512, f"fs saved = {fs}")
            check(len(names) == 4, f"channel_names {names}")
            n = data.shape[0]
            check(580 <= n <= 630, f"samples ≈1.2s@512 = {n}")
            p0 = _peak_freq(data[:, 0], fs)
            p1 = _peak_freq(data[:, 1], fs)
            check(abs(p0 - 10.0) <= 1.5, f"live ch0 peak ≈10Hz (got {p0})")
            check(abs(p1 - 15.0) <= 1.5, f"live ch1 peak ≈15Hz (got {p1})")

        if json_files:
            with open(os.path.join(tmp, json_files[0]), encoding="utf-8") as fh:
                meta = json.load(fh)
            check(meta.get("mode") == "device", f"meta mode = {meta.get('mode')}")
            check(meta.get("device") == "VIRTUAL", "meta device = VIRTUAL")
            check(meta.get("channels_acquired") == 4, "meta channels = 4")
            check(meta.get("sampling_rate_hz") == 512, "meta fs = 512")

        ok, _ = kill_device("SG2")
        check(ok and list_sessions() == [], "live kill unregisters")

        # 噪声确定性: seed 相同 → 两次独立落盘数据一致
        def _noisy_run(sub: str) -> np.ndarray:
            d = os.path.join(tmp, sub)
            os.makedirs(d, exist_ok=True)
            close_all()
            c = SigGenConfig.from_props({
                "device_name": "SG3", "channels": 2, "sampling_rate": 512,
                "frequency": 12.0, "freq_step": 0.0, "noise_uv": 5.0, "seed": 42,
                "save_dir": d, "buffer_seconds": 1.0,
            })
            init_session("SG3", c, dry_run=False)
            start_record("SG3", elapsed_s=0.0)
            stop_record("SG3", save_scope="session", elapsed_s=0.8)
            kill_device("SG3")
            fname = [x for x in os.listdir(d) if x.endswith(".npz")][0]
            with np.load(os.path.join(d, fname)) as npz:
                return npz["data"]

        a = _noisy_run("a")
        b = _noisy_run("b")
        check(a.shape == b.shape and np.array_equal(a, b),
              "noise determinism: same seed → identical arrays")
    finally:
        close_all()
        shutil.rmtree(tmp, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════
# 4. 节点图干跑 (MCP validate_graph 同路径)
# ═══════════════════════════════════════════════════════════════

def _build_siggen_graph() -> GraphBuilder:
    g = GraphBuilder()
    GS, FU, GP = g.event_nodes()

    init = g.siggen_init("SIGGEN", channels=4, frequency=10.0, freq_step=5.0,
                         buffer_seconds=1.0)
    start = g.siggen_start("SIGGEN")
    g.link(GS, "exec", init, "exec_in")
    g.chain(init, start)

    # 每帧读取 Samples (触发 GetSigGenData 懒求值) → Print
    getn = g.siggen_get("SIGGEN")
    pr = g.node("Print", ["exec_in", "exec_out", "Value"])
    g.link(FU, "exec", pr, "exec_in")
    g.link(getn, "Samples", pr, "Value")

    stop = g.siggen_stop("SIGGEN", scope="session")
    kill = g.siggen_kill("SIGGEN")
    g.link(GP, "exec", stop, "exec_in")
    g.chain(stop, kill)
    return g


def test_graph_dry_run():
    print("── Graph dry-run (MCP path) ──")
    close_all()

    g = _build_siggen_graph()
    graph = g.build()

    errors = validate_static(graph)
    check(not errors, f"static validation clean ({errors[:2]})")

    report = g.validate(max_frames=30)
    check(report.passed, f"dry-run passed ({report.dry_run})")
    if report.dry_run:
        types = report.dry_run.get("events_by_type", {})
        for t in ("InitSigGenDevice", "StartSigGenRecord", "GetSigGenData",
                  "StopSigGenRecord", "KillSigGenDevice"):
            check(t in types, f"dry-run event: {t} ({types.get(t, 0)}x)")

    check(list_sessions() == [], "dry-run left no registered sessions")


# ═══════════════════════════════════════════════════════════════
# 5. Init/Kill 强制配对: 校验 + 删除级联
# ═══════════════════════════════════════════════════════════════

def test_pairing_validation():
    print("── Init/Kill pairing validation ──")

    # Init 无 Kill → 错误
    g = GraphBuilder()
    GS, _FU, _GP = g.event_nodes()
    g.link(GS, "exec", g.siggen_init("SIGGEN"), "exec_in")
    errors = validate_static(g.build())
    check(any("KillSigGenDevice" in e for e in errors),
          f"init without kill → error ({errors[:1]})")

    # Kill 无 Init → 错误
    g = GraphBuilder()
    GS, _FU, _GP = g.event_nodes()
    g.link(GS, "exec", g.siggen_kill("SIGGEN"), "exec_in")
    errors = validate_static(g.build())
    check(any("InitSigGenDevice" in e for e in errors), "kill without init → error")

    # 名称不匹配 → 错误
    g = GraphBuilder()
    GS, _FU, _GP = g.event_nodes()
    g.link(GS, "exec", g.siggen_init("A"), "exec_in")
    g.link(GS, "exec", g.siggen_kill("B"), "exec_in")
    errors = validate_static(g.build())
    check(any("no matching InitSigGenDevice" in e for e in errors),
          "name mismatch → error")

    # 配对 → 无 SigGen 错误
    g = _build_siggen_graph()
    errors = [e for e in validate_static(g.build()) if "SigGen" in e]
    check(not errors, f"paired graph clean ({errors[:2]})")


def test_deletion_cascade():
    print("── Init/Kill deletion cascade ──")
    canvas = NodeCanvas()
    init_nid = canvas.add_node("InitSigGenDevice", (0, 0))
    kill_nid = canvas.add_node("KillSigGenDevice", (0, 100))
    other_nid = canvas.add_node("Print", (0, 200))
    canvas.nodes[init_nid].props["device_name"] = "SIGGEN"
    canvas.nodes[kill_nid].props["device_name"] = "SIGGEN"
    check(init_nid > 0 and kill_nid > 0, "canvas nodes created")

    # 删 Init → 级联 Kill (无关节点保留)
    expand = siggen_cascade_deletes(canvas, [init_nid])
    check(kill_nid in expand and other_nid not in expand,
          f"delete init → cascade kill {sorted(expand)}")

    # 删 Kill → 级联 Init
    expand = siggen_cascade_deletes(canvas, [kill_nid])
    check(init_nid in expand, f"delete kill → cascade init {sorted(expand)}")

    # Kill 空名 + 仅 1 个 Init → 自动绑定
    canvas2 = NodeCanvas()
    i2 = canvas2.add_node("InitSigGenDevice", (0, 0))
    k2 = canvas2.add_node("KillSigGenDevice", (0, 100))
    canvas2.nodes[i2].props["device_name"] = "SIGGEN"
    expand = siggen_cascade_deletes(canvas2, [k2])
    check(i2 in expand, "empty-name kill auto-binds single init")

    # 两 Init + 空名 Kill → 歧义, 不级联
    canvas3 = NodeCanvas()
    i3a = canvas3.add_node("InitSigGenDevice", (0, 0))
    i3b = canvas3.add_node("InitSigGenDevice", (0, 50))
    k3 = canvas3.add_node("KillSigGenDevice", (0, 100))
    canvas3.nodes[i3a].props["device_name"] = "A"
    canvas3.nodes[i3b].props["device_name"] = "B"
    expand = siggen_cascade_deletes(canvas3, [k3])
    check(expand == {k3}, "ambiguous empty-name kill → no cascade")

    # 静态校验同样判定歧义
    errors = siggen_pairing_errors({
        "1": {"node_type": "InitSigGenDevice", "props": {"device_name": "A"}},
        "2": {"node_type": "InitSigGenDevice", "props": {"device_name": "B"}},
        "3": {"node_type": "KillSigGenDevice", "props": {}},
    })
    check(any("ambiguous" in e for e in errors),
          f"ambiguous binding error ({errors[:1]})")

    # 混合族: 级联只影响同族 (SigGen 与设备池互不干扰)
    canvas4 = NodeCanvas()
    si = canvas4.add_node("InitSigGenDevice", (0, 0))
    sk = canvas4.add_node("KillSigGenDevice", (0, 50))
    pc = canvas4.add_node("CreateDevicePool", (0, 100))
    pk = canvas4.add_node("KillDevicePool", (0, 150))
    for nid, name in ((si, "SG"), (sk, "SG")):
        canvas4.nodes[nid].props["device_name"] = name
    canvas4.nodes[pc].props["pool_name"] = "P1"
    canvas4.nodes[pk].props["pool_name"] = "P1"
    expand = device_cascade_deletes(canvas4, [si])
    check(sk in expand and pc not in expand and pk not in expand,
          f"siggen delete → only siggen cascade {sorted(expand)}")
    expand = device_cascade_deletes(canvas4, [pk])
    check(pc in expand and si not in expand and sk not in expand,
          f"pool delete → only pool cascade {sorted(expand)}")


# ═══════════════════════════════════════════════════════════════
# 6. 触发链路 + 服务自动拉起（ENGINE_GAPS #1-#3 上游化）
# ═══════════════════════════════════════════════════════════════

_STUB_BRAND_MODULE = "Test.Application.Functions._brand_stub_service"
_BRAND_ENV_KEYS = ("MGE_EEG_SERVICE", "MGE_EEG_SERVICE_PYTHON",
                   "MGE_EEG_SERVICE_MODULE")


def _clear_brand_env() -> dict:
    """暂存并清空品牌服务 env（测试沙箱）→ 返回原值（供还原）。"""
    keep = {k: os.environ.get(k) for k in _BRAND_ENV_KEYS}
    for k in keep:
        os.environ.pop(k, None)
    return keep


def _restore_brand_env(keep: dict) -> None:
    for k, v in keep.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def test_trigger_config():
    print("── Trigger config semantics ──")
    cfg = SigGenConfig.from_props({})
    check(cfg.trigger_every_s == 0.0, "trigger default off (0)")
    check("trig=" not in cfg.summary(), "summary omits trig when off")

    cfg = SigGenConfig.from_props({"trigger_every_s": 0.5})
    check(cfg.trigger_every_s == 0.5, "trigger_every_s parsed 0.5")
    check("trig=0.5s" in cfg.summary(), "summary shows trig when on")

    check(SigGenConfig.from_props({"trigger_every_s": -1}).trigger_every_s == 0.0,
          "negative trigger → 0")
    check(SigGenConfig.from_props({"trigger_every_s": 999}).trigger_every_s == 60.0,
          "trigger clamped to 60")

    dcfg = DeviceConfig.from_props({})
    check(dcfg.service_module == "", "service_module default ''")
    dcfg = DeviceConfig.from_props({"service_module": "pkg.mod",
                                    "service_python": "C:/py.exe"})
    check(dcfg.service_module == "pkg.mod" and dcfg.service_python == "C:/py.exe",
          "service_module parsed via props")


def test_trigger_events_dry():
    print("── Trigger events (dry-run synthetic) ──")
    close_all()
    cfg = SigGenConfig.from_props({
        "device_name": "T1", "channels": 4, "sampling_rate": 512,
        "buffer_seconds": 4.0, "trigger_every_s": 0.5,
    })
    session, detail = init_session("T1", cfg, dry_run=True)
    check(session is not None, f"init ok ({detail[:60]}...)")
    start_record("T1", elapsed_s=0.0)
    result, why = get_data("T1", elapsed_s=2.0)
    check(result is not None and result["data"].shape == (4, 2048)
          and result["samples"] == 1024,
          f"2s @512 → 1024 valid / ring (4, 2048) ({why})")

    events, why = get_trigger_events("T1")
    check(events is not None and events["total"] == 4,
          f"4 events in 2s ({None if events is None else events['total']}, {why})")
    if events and events["total"] == 4:
        samples = [e["sample"] for e in events["events"]]
        codes = [e["code"] for e in events["events"]]
        check(samples == [0, 256, 512, 768], f"event samples {samples}")
        check(codes == [1, 2, 3, 4], f"codes cycle 1..4 {codes}")
        check(all(abs(e["t_s"] - e["sample"] / 512.0) < 1e-9
                  for e in events["events"]), "t_s == sample / fs")

    inc, _ = get_trigger_events("T1", start=2)
    check(inc is not None and [e["code"] for e in inc["events"]] == [3, 4],
          "incremental cursor (start=2 → codes [3, 4])")
    check(session.sample_count == 1024, f"sample_count = {session.sample_count}")
    kill_device("T1")

    # 无触发配置 → 无附加列 / 无事件（默认零行为变化）
    cfg2 = SigGenConfig.from_props({
        "device_name": "T2", "channels": 4, "sampling_rate": 512,
        "buffer_seconds": 4.0,
    })
    session2, _ = init_session("T2", cfg2, dry_run=True)
    start_record("T2", elapsed_s=0.0)
    get_data("T2", elapsed_s=1.0)
    ev2, _ = get_trigger_events("T2")
    check(ev2 is not None and ev2["total"] == 0, "no trigger column → 0 events")
    check(session2.sample_count == 512, "sample_count still counts without column")
    kill_device("T2")
    check(close_all() == 0, "registry empty after cleanup")


def test_trigger_scope_upgrade():
    print("── Trigger scope (watch → record upgrade) ──")
    close_all()
    cfg = SigGenConfig.from_props({
        "device_name": "T3", "channels": 2, "sampling_rate": 512,
        "buffer_seconds": 4.0, "trigger_every_s": 0.5,
    })
    session, _ = init_session("T3", cfg, dry_run=True)
    start_record("T3", elapsed_s=0.0, record=False)      # Watch
    get_data("T3", elapsed_s=1.0)
    ok, detail = start_record("T3", elapsed_s=1.0, record=True)   # 升级录制
    check(ok, f"watch -> record upgrade ({detail})")
    get_data("T3", elapsed_s=2.0)

    full, _ = get_trigger_events("T3")
    check(full is not None and full["total"] == 4,
          f"stream total 4 events ({None if full is None else full['total']})")
    scope = session.trigger_events_for_scope("session")
    check([e["code"] for e in scope] == [3, 4],
          f"session scope = recorded segment ({[e['code'] for e in scope]})")
    buf = session.trigger_events_for_scope("buffer")
    check(len(buf) == 4, f"buffer scope = whole window ({len(buf)})")
    kill_device("T3")


def test_trigger_events_live_save():
    print("── Trigger events + save (service mode, npz/json parity) ──")
    close_all()
    tmp = tempfile.mkdtemp(prefix="siggen_trigger_")
    try:
        cfg = SigGenConfig.from_props({
            "device_name": "T4", "channels": 4, "sampling_rate": 512,
            "buffer_seconds": 4.0, "trigger_every_s": 0.5, "save_dir": tmp,
        })
        session, detail = init_session("T4", cfg, dry_run=False)
        check(session is not None, f"live init ok ({detail[:60]}...)")
        start_record("T4", elapsed_s=0.0)
        get_data("T4", elapsed_s=2.0)
        ok, sdetail = stop_record("T4", save_scope="session", elapsed_s=2.0)
        check(ok and "saved" in sdetail, f"stop saved ({sdetail[:70]}...)")

        npz_files = [f for f in os.listdir(tmp) if f.endswith(".npz")]
        json_files = [f for f in os.listdir(tmp) if f.endswith(".json")]
        check(len(npz_files) == 1 and len(json_files) == 1, "npz + json written")
        if npz_files and json_files:
            with np.load(os.path.join(tmp, npz_files[0])) as npz:
                arr = npz["data"]
                names = [str(x) for x in npz["channel_names"]]
            with open(os.path.join(tmp, json_files[0]), encoding="utf-8") as fh:
                meta = json.load(fh)
            check(arr.shape == (1024, 5), f"data shape (1024, 5) ({arr.shape})")
            check(names[-1] == "TRIG", f"last channel name TRIG ({names[-1]})")
            check(meta.get("channels_saved") == 5, "meta channels_saved = 5")
            ev = meta.get("trigger_events") or []
            check(meta.get("trigger_events_count") == 4 and len(ev) == 4,
                  f"meta events = 4 (count={meta.get('trigger_events_count')})")
            check([e["code"] for e in ev] == [1, 2, 3, 4],
                  f"codes 1..4 ({[e['code'] for e in ev]})")
            col = arr[:, 4]
            nz = np.nonzero(col)[0]
            starts = [int(s) for s in nz[np.concatenate([[True], np.diff(nz) > 1])]]
            check(starts == [e["sample"] for e in ev],
                  f"npz pulse starts == event samples ({starts})")
            check(all(float(col[e["sample"]]) == float(e["code"]) for e in ev),
                  "npz code == event code")
            check(len(nz) == 20, f"pulse samples = 4 pulses x 5 (@10ms) ({len(nz)})")
        kill_device("T4")
    finally:
        close_all()
        shutil.rmtree(tmp, ignore_errors=True)


def test_autolaunch_selection():
    print("── Auto-launch route selection (no spawn) ──")
    keep = _clear_brand_env()
    try:
        b = ServiceBackend.connect_brand(python_exe="C:/py.exe", module="pkg.mod")
        check(b._spawn and b._module == "pkg.mod" and b._python_exe == "C:/py.exe",
              "python + module → spawn scheduled")
        b = ServiceBackend.connect_brand(python_exe="C:/py.exe")
        check(not b._spawn and b._endpoint == "127.0.0.1:47810",
              "python only → default endpoint (unchanged)")
        b = ServiceBackend.connect_brand(module="pkg.mod")
        check(not b._spawn and b._endpoint == "127.0.0.1:47810",
              "module only (no python) → default endpoint (unchanged)")
        os.environ["MGE_EEG_SERVICE_MODULE"] = "pkg.env"
        b = ServiceBackend.connect_brand(python_exe="C:/py.exe")
        check(b._spawn and b._module == "pkg.env", "env module fallback works")
        os.environ.pop("MGE_EEG_SERVICE_MODULE", None)
        os.environ["MGE_EEG_SERVICE"] = "127.0.0.1:47999"
        b = ServiceBackend.connect_brand(python_exe="C:/py.exe", module="pkg.mod")
        check(not b._spawn and b._endpoint == "127.0.0.1:47999",
              "explicit MGE_EEG_SERVICE wins (connect, no spawn)")
    finally:
        _restore_brand_env(keep)


def test_autolaunch_spawn_e2e():
    print("── Auto-launch e2e (stub brand service, spawn + hello + data) ──")
    keep = _clear_brand_env()
    backend = None
    proc = None
    try:
        cfg = SigGenConfig.from_props({
            "channels": 2, "sampling_rate": 256, "frequency": 12.0,
            "freq_step": 0.0, "buffer_seconds": 1.0,
        })
        backend = ServiceBackend.connect_brand(python_exe=sys.executable,
                                               module=_STUB_BRAND_MODULE)
        t0 = time.time()
        backend.configure(cfg)      # 触发 spawn → hello → init
        elapsed = time.time() - t0
        proc = backend._proc
        check(proc is not None and proc.poll() is None,
              f"brand stub spawned & alive (pid={None if proc is None else proc.pid})")
        check(backend._mode == "pump", f"hello mode = {backend._mode}")
        check(elapsed < 30.0, f"auto-launch + handshake {elapsed:.1f}s (<30s)")

        blocks: list = []
        backend.start(blocks.append)
        backend.pump(0.0, blocks.append)
        backend.pump(0.5, blocks.append)
        backend.stop()
        total = sum(int(b.shape[0]) for b in blocks)
        check(total == 128, f"data flows from spawned service (128 @256Hz, got {total})")
    finally:
        if backend is not None:
            backend.close()
        _restore_brand_env(keep)
    check(proc is not None and proc.poll() is not None, "service process exited on close")


def test_autolaunch_facade_route():
    print("── Auto-launch via facade (DeviceConfig.service_module) ──")
    keep = _clear_brand_env()
    proc = None
    try:
        close_all()
        cfg = DeviceConfig(
            device="EXTERNAL", device_name="AUTO1", sampling_rate=512,
            save_dir=".", buffer_seconds=1.0,
            service_python=sys.executable, service_module=_STUB_BRAND_MODULE)
        session, detail = init_session("AUTO1", cfg, dry_run=False)
        check(session is not None, f"facade auto-launch init ({detail[:70]}...)")
        if session is not None:
            b = session.backend
            proc = getattr(b, "_proc", None)
            check(type(b).__name__ == "ServiceBackend" and b._spawn
                  and b._module == _STUB_BRAND_MODULE,
                  "routed to spawned brand service (module passthrough)")
            start_record("AUTO1", elapsed_s=0.0)
            r, why = get_data("AUTO1", elapsed_s=0.5)
            check(r is not None and int(r["samples"]) == 256,
                  f"data via spawned service ({None if r is None else r['samples']} samples, {why[:30]})")
            ok, _ = kill_device("AUTO1")
            check(ok, "kill_device ok")
    finally:
        close_all()
        _restore_brand_env(keep)
    check(proc is not None and proc.poll() is not None, "spawned process exited")


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("VirtualDevice (SigGen) — Unit Tests")
    print("=" * 60)

    test_config_semantics()
    test_dry_session_lifecycle()
    test_live_session_lifecycle()
    test_graph_dry_run()
    test_pairing_validation()
    test_deletion_cascade()
    test_trigger_config()
    test_trigger_events_dry()
    test_trigger_scope_upgrade()
    test_trigger_events_live_save()
    test_autolaunch_selection()
    test_autolaunch_spawn_e2e()
    test_autolaunch_facade_route()

    print()
    print("=" * 60)
    total = _PASS + _FAIL
    print(f"Results: {_PASS}/{total} passed, {_FAIL} failed")
    if _FAIL > 0:
        print("SOME TESTS FAILED")
        sys.exit(1)
    else:
        print("ALL TESTS PASSED")
