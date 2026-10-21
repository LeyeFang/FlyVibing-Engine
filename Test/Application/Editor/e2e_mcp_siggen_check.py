"""
E2E: SigGen 虚拟信号发生器 — 实机全链路 (建图 → 校验 → PIE → 落盘 → 销毁)。

流程:
  1. scene.create "SigGenE2E" → switch  (隔离画布, 不污染当前场景)
  2. graph.add ×(事件 + SigGen 五件套 + Print) → graph.set_props → graph.link
  3. graph.export 画布 → tmp JSON (实时节点图导出)
  4. editor_graph_validate(source="canvas", 120 帧) → 静态 + 干跑报告 (落盘 .txt)
  5. sim.play (PIE ≈3s: OnGameStart→Init/Start 采集, OnFrameUpdate→Get/Print) → sim.stop
     → OnGameStop→Stop(保存 npz+json)→Kill
  6. 校验保存文件: npz 形状/fs/正弦频率, json 元数据 mode=device
  7. editor.quit (--keep-open 可保留编辑器)

用法（需 startup.bat 运行中）:
    .venv-py314t\\Scripts\\python.exe Test/Application/Editor/e2e_mcp_siggen_check.py [--keep-open]
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "_path_setup.py")):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)
    import _path_setup  # noqa: F401

ROOT = os.path.dirname(_d)

import numpy as np  # noqa: E402

from engine_editor_mcp import mcp_server as m  # noqa: E402

TMP = os.path.join(ROOT, "Utils", "ExtDev", "EditorMcp", "tmp")
OUT_DIR = os.path.join(ROOT, "Test", "Application", "Functions", "_siggen_e2e_out")
DEVICE = "E2E_SG"

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


def _wait_state(target: str, timeout_s: float = 12.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = m._send("sim.state")
        if str(r.get("state") or "") == target:
            return True
        time.sleep(0.2)
    return False


def main() -> int:
    keep_open = "--keep-open" in sys.argv
    print("=" * 62)
    print("  E2E: SigGen (virtual signal generator) — full lifecycle")
    print("=" * 62)

    os.makedirs(TMP, exist_ok=True)
    shutil.rmtree(OUT_DIR, ignore_errors=True)
    os.makedirs(OUT_DIR, exist_ok=True)

    # ── 1. 隔离场景 ──
    r = m._send("scene.create", {"name": "SigGenE2E"}, timeout=30.0)
    create_ok = ("error" not in r) or ("exist" in str(r).lower())
    check("scene.create ok (or exists)", create_ok, str(r)[:200])
    r2 = m._send("scene.switch", {"name": "SigGenE2E"}, timeout=30.0)
    check("scene active", "error" not in r2, str(r2)[:200])

    # ── 2. 建图 (真实签名: add={type,props}; link={from:{node,pin},to:{node,pin}}) ──
    def add(node_type: str, props: dict | None = None) -> int | None:
        r = m._send("graph.add", {"type": node_type, "props": props or {}},
                    timeout=30.0)
        if "error" in r:
            check(f"graph.add {node_type}", False, str(r)[:160])
            return None
        return int(r["node_id"])

    def link(fr: int, fp: str, to: int, tp: str) -> None:
        r = m._send("graph.link", {
            "from": {"node": fr, "pin": fp},
            "to": {"node": to, "pin": tp},
        }, timeout=30.0)
        if "error" in r:
            check(f"link {fr}.{fp} -> {to}.{tp}", False, str(r)[:160])

    r = m._send("graph.list")
    existing: dict[str, int] = {}
    for nd in r.get("nodes") or []:
        existing.setdefault(str(nd.get("type")), int(nd.get("id")))

    ids: dict[str, int] = {}
    for t in ("OnGameStart", "OnFrameUpdate", "OnGameStop"):
        nid = existing.get(t)
        if nid is None:
            nid = add(t)
        if nid is not None:
            ids[t] = nid

    init_props = {
        "device": "VIRTUAL", "device_name": DEVICE, "channels": 4,
        "sampling_rate": 512, "frequency": 10.0, "freq_step": 5.0,
        "amplitude_uv": 50.0, "noise_uv": 0.0, "seed": 0,
        "export_format": "npz", "save_dir": OUT_DIR, "buffer_seconds": 2.0,
    }
    for t, props in (
        ("InitSigGenDevice", init_props),
        ("StartSigGenRecord", {"device_name": DEVICE}),
        ("GetSigGenData", {"device_name": DEVICE}),
        ("Print", {}),
        ("StopSigGenRecord", {"device_name": DEVICE, "save_scope": "session"}),
        ("KillSigGenDevice", {"device_name": DEVICE}),
    ):
        nid = existing.get(t)
        if nid is None:
            nid = add(t, props)
        else:
            # 复用上一轮节点: 重新施加配置 (幂等)
            m._send("graph.set_props", {"node": nid, "props": props}, timeout=30.0)
        if nid is not None:
            ids[t] = nid

    need = ["OnGameStart", "OnFrameUpdate", "OnGameStop", "InitSigGenDevice",
            "StartSigGenRecord", "GetSigGenData", "Print",
            "StopSigGenRecord", "KillSigGenDevice"]
    missing = [t for t in need if t not in ids]
    r = m._send("graph.list")
    check(f"graph built ({len(r.get('nodes') or [])} nodes)", not missing,
          f"missing={missing}")
    if missing:
        print("  abort: graph incomplete")
        print(f"E2E Results: {_RESULTS['pass']}/{_RESULTS['pass'] + _RESULTS['fail']} "
              f"passed, {_RESULTS['fail']} failed")
        return 1

    link(ids["OnGameStart"], "exec", ids["InitSigGenDevice"], "exec_in")
    link(ids["InitSigGenDevice"], "exec_out", ids["StartSigGenRecord"], "exec_in")
    link(ids["OnFrameUpdate"], "exec", ids["Print"], "exec_in")
    link(ids["GetSigGenData"], "Samples", ids["Print"], "Value")
    link(ids["OnGameStop"], "exec", ids["StopSigGenRecord"], "exec_in")
    link(ids["StopSigGenRecord"], "exec_out", ids["KillSigGenDevice"], "exec_in")
    r = m._send("graph.list")
    check(f"links created ({len(r.get('links') or [])})",
          len(r.get("links") or []) >= 6)

    # ── 3. 实时导出画布 ──
    exp_path = os.path.join(TMP, "siggen_e2e_graph.json")
    r = m._send("graph.export", {"path": exp_path}, timeout=30.0)
    check("graph.export saved", "error" not in r and os.path.isfile(exp_path),
          str(r)[:200])

    # ── 4. 引擎内校验 (静态 + 干跑; 底层 ops: start → poll report → save) ──
    report_txt = os.path.join(TMP, "siggen_e2e_validation.txt")
    rs = m._send("graph.validate.start", {"source": "canvas", "frames": 120},
                 timeout=60.0)
    check("validate.start ok", "error" not in rs, str(rs)[:200])
    rep: dict = {}
    rr: dict = {}
    deadline = time.time() + 180.0
    while time.time() < deadline:
        rr = m._send("graph.validate.report", {"save_path": report_txt}, timeout=60.0)
        if "error" not in rr and rr.get("report"):
            rep = rr["report"]
            break
        time.sleep(0.5)
    check("validate report fetched", bool(rep), str(rr)[:200])
    static = rep.get("static") or {}
    runtime = rep.get("runtime") or {}
    print(f"  static: {len(static.get('errors') or [])}E/"
          f"{len(static.get('warnings') or [])}W · runtime: "
          f"{len(runtime.get('errors') or [])}E · frames="
          f"{runtime.get('frames_simulated')} events={runtime.get('total_events')}")
    for e in (static.get("errors") or [])[:5]:
        print(f"    x [s] {e.get('message')}")
    for e in (runtime.get("errors") or [])[:5]:
        print(f"    x [r] {e}")
    check("validate pipeline ok", bool(rep), str(rep)[:200])
    check("validation ok=True", rep.get("ok") is True, f"static={static}")

    # ── 5. PIE 真实运行 (采集 → 停止时保存 → 销毁) ──
    m._send("sim.play", timeout=30.0)
    check("PIE running", _wait_state("Running"), "sim.state != Running")
    time.sleep(3.0)
    m._send("sim.stop", timeout=30.0)
    check("PIE stopped", _wait_state("Stopped"), "sim.state != Stopped")
    time.sleep(0.5)  # 保存收尾

    # ── 6. 校验落盘 ──
    files = sorted(os.listdir(OUT_DIR)) if os.path.isdir(OUT_DIR) else []
    npz_files = [f for f in files if f.endswith(".npz")]
    json_files = [f for f in files if f.endswith(".json")]
    check(f"npz written ({files})", len(npz_files) == 1, str(files))
    check("json sidecar written", len(json_files) == 1, str(files))
    if npz_files:
        with np.load(os.path.join(OUT_DIR, npz_files[0])) as npz:
            data = npz["data"]
            fs = int(npz["fs"])
        check(f"npz shape {data.shape} (expect ~3s@512 x 4ch)",
              data.ndim == 2 and data.shape[1] == 4 and data.shape[0] >= 512,
              str(data.shape))
        check(f"fs = {fs}", fs == 512)
        n = data.shape[0]
        spec = np.abs(np.fft.rfft(data[:, 0] * np.hanning(n)))
        peak = float(np.fft.rfftfreq(n, d=1.0 / fs)[int(np.argmax(spec))])
        check(f"ch0 sine peak ~10Hz (got {peak:.2f})", abs(peak - 10.0) <= 1.5)
    if json_files:
        with open(os.path.join(OUT_DIR, json_files[0]), encoding="utf-8") as fh:
            meta = json.load(fh)
        check("meta mode=device", meta.get("mode") == "device", str(meta.get("mode")))
        check("meta device=VIRTUAL", meta.get("device") == "VIRTUAL")

    # 设备会话应已在 OnGameStop 链 (Kill) 中注销 — 再看画布事件日志尾
    print("  -- done --")

    if not keep_open:
        m._send("editor.quit", timeout=10.0)
        print("  editor.quit sent")

    print("=" * 62)
    total = _RESULTS["pass"] + _RESULTS["fail"]
    print(f"E2E Results: {_RESULTS['pass']}/{total} passed, {_RESULTS['fail']} failed")
    return 1 if _RESULTS["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
