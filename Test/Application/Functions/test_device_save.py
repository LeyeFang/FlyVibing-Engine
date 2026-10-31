"""Device save without Stop — path uniqueness / pump / graph node / dry-run.

Covers:
  1. `_plan_base_path` never overwrites a same-second save.
  2. `save_record` pumps first, keeps the session recording, and writes a
     mid-recording take (npz + json) whose row count matches the reported
     sample count.
  3. Two mid-recording saves produce two files and a growing sample count.
  4. `SaveDeviceData` is available to the graph and runs in dry-run without
     writing files.
  5. Dry-run stub reports `written=0` but still returns planned paths.

TIER: core
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "_path_setup.py")):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)
    import _path_setup  # noqa: F401

import numpy as np

from Application.Functions.VirtualDevice import (
    SaveResult,
    SigGenConfig,
    close_all,
    get_data,
    init_session,
    kill_device,
    list_sessions,
    register_session,
    save_record,
    start_record,
    stop_record,
    unregister_session,
)
from Application.Functions.VirtualDevice.Device import _plan_base_path
from flyvibing_node_editor.graph_builder import GraphBuilder
from flyvibing_node_editor.node_graph_validator import validate_static

_PASS = 0
_FAIL = 0


def check(cond: bool, name: str, detail: str = "") -> bool:
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print(f"  [PASS] {name}")
    else:
        _FAIL += 1
        print(f"  [FAIL] {name}" + (f"  ({detail})" if detail else ""))
    return cond


def _read_npz(path: str):
    with np.load(path) as npz:
        return {
            "data": npz["data"],
            "fs": int(npz["fs"]),
            "channel_names": list(npz["channel_names"]),
        }


def _read_meta(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def test_unique_paths() -> None:
    print("── unique save paths ──")
    tmp = tempfile.mkdtemp(prefix="device_save_path_")
    try:
        first = _plan_base_path(tmp, "DEV 1", tag="take 1")
        check("tag is sanitized into filename", "take_1" in os.path.basename(first), first)
        with open(f"{first}.npz", "wb") as fh:
            fh.write(b"x")
        second = _plan_base_path(tmp, "DEV 1", tag="take 1")
        check("existing same-timestamp path gets a suffix",
              second != first and second.endswith("_2"), f"{first} / {second}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_mid_record_save() -> None:
    print("── mid-record save (live inproc) ──")
    close_all()
    tmp = tempfile.mkdtemp(prefix="device_save_live_")
    old_transport = os.environ.get("MGE_EEG_TRANSPORT")
    os.environ["MGE_EEG_TRANSPORT"] = "inproc"
    try:
        cfg = SigGenConfig.from_props({
            "device_name": "SAVE_NODE", "channels": 4, "sampling_rate": 512,
            "frequency": 10.0, "buffer_seconds": 1.0, "save_dir": tmp,
        })
        session, detail = init_session("SAVE_NODE", cfg, dry_run=False)
        check(session is not None, f"init live inproc ({detail[:80]})")
        ok, _ = start_record("SAVE_NODE", elapsed_s=0.0)
        check(ok and session.state == "recording", "recording started")

        ok, detail, info = save_record(
            "SAVE_NODE", save_scope="session", elapsed_s=0.6, tag="mid1")
        check(ok and bool(info.get("written")), f"save #1 written ({detail[:100]})")
        check(int(info.get("samples", 0)) > 0, f"save #1 samples = {info.get('samples')}")
        check(session.state == "recording", "save does not stop recording")
        check(len(info.get("paths") or []) == 2, f"two paths: {info.get('paths')}")

        data_path = next((p for p in info.get("paths", []) if p.endswith(".npz")), "")
        meta_path = str(info.get("meta_path") or "")
        check(bool(data_path and os.path.isfile(data_path)), f"npz exists: {data_path}")
        check(bool(meta_path and os.path.isfile(meta_path)), f"json exists: {meta_path}")

        npz = _read_npz(data_path)
        samples1 = int(info["samples"])
        check(npz["data"].shape == (samples1, 4),
              f"rows == reported samples: {npz['data'].shape} vs {samples1}")
        check(npz["fs"] == 512 and len(npz["channel_names"]) == 4,
              f"fs/channel_names: {npz['fs']} / {npz['channel_names']}")
        meta = _read_meta(meta_path)
        check(meta.get("samples_saved") == samples1, f"meta samples {meta.get('samples_saved')}")
        check(meta.get("save_scope") == "session" and meta.get("tag") == "mid1",
              f"meta scope/tag: {meta.get('save_scope')} / {meta.get('tag')}")
        check(int(meta.get("trigger_events_count", -1)) == 0,
              f"no trigger column -> 0 events ({meta.get('trigger_events_count')})")

        before = int(session.sample_count)
        result, why = get_data("SAVE_NODE", elapsed_s=0.8)
        check(result is not None, f"get_data after save ({why})")
        after = int(session.sample_count)
        check(after > before, f"sample_count still grows: {before} -> {after}")

        ok, detail, info2 = save_record(
            "SAVE_NODE", save_scope="session", elapsed_s=0.8, tag="mid2")
        check(ok and bool(info2.get("written")), f"save #2 written ({detail[:100]})")
        check(info2.get("paths") != info.get("paths"),
              f"two saves use distinct paths: {info2.get('paths')}")
        check(int(info2.get("samples", 0)) > samples1,
              f"save #2 has more samples: {info2.get('samples')} > {samples1}")
        npz2 = _read_npz(next(p for p in info2["paths"] if p.endswith(".npz")))
        check(npz2["data"].shape[0] == int(info2["samples"]),
              f"save #2 rows: {npz2['data'].shape[0]}")

        files = sorted(os.listdir(tmp))
        check(len([f for f in files if f.endswith(".npz")]) == 2,
              f"two npz files remain ({files})")
        stop_record("SAVE_NODE", save=False, elapsed_s=0.8)
        kill_device("SAVE_NODE")
    finally:
        close_all()
        if old_transport is None:
            os.environ.pop("MGE_EEG_TRANSPORT", None)
        else:
            os.environ["MGE_EEG_TRANSPORT"] = old_transport
        shutil.rmtree(tmp, ignore_errors=True)


def test_dry_run_save() -> None:
    print("── dry-run save (no disk writes) ──")
    close_all()
    tmp = tempfile.mkdtemp(prefix="device_save_dry_")
    try:
        cfg = SigGenConfig.from_props({
            "device_name": "SAVE_DRY", "channels": 2, "sampling_rate": 512,
            "buffer_seconds": 1.0, "save_dir": tmp,
        })
        session, _ = init_session("SAVE_DRY", cfg, dry_run=True)
        check(session is not None, "dry session created")
        start_record("SAVE_DRY", elapsed_s=0.0)
        ok, detail, info = save_record(
            "SAVE_DRY", save_scope="session", elapsed_s=0.5, tag="dry")
        check(ok and info.get("written") is False,
              f"dry-run written=False ({detail[:80]})")
        check(int(info.get("samples", 0)) > 0, f"dry-run still calculates samples: {info.get('samples')}")
        check(info.get("paths") and not any(os.path.exists(p) for p in info["paths"]),
              f"dry-run does not write paths: {info.get('paths')}")
        check(not os.listdir(tmp), f"save dir remains empty ({os.listdir(tmp)})")
        stop_record("SAVE_DRY", save=False, elapsed_s=0.5)
        kill_device("SAVE_DRY")
    finally:
        close_all()
        shutil.rmtree(tmp, ignore_errors=True)


def test_legacy_save_signature() -> None:
    print("── legacy session.save(scope) fallback ──")

    class _OldSession:
        name = "OLD_SESSION"
        state = "recording"
        sample_count = 0

        def __init__(self) -> None:
            self.calls: list[tuple[str, float | str]] = []

        def get_data(self, elapsed_s: float = 0.0):
            self.calls.append(("get_data", float(elapsed_s)))
            self.sample_count = int(float(elapsed_s) * 512)
            return {"samples": self.sample_count}

        def save(self, scope: str = "session"):
            self.calls.append(("save", scope))
            return SaveResult(paths=["old.npz", "old.json"], written=False,
                             samples=self.sample_count,
                             duration_s=self.sample_count / 512.0)

    fake = _OldSession()
    register_session(fake)
    try:
        ok, _detail, info = save_record("OLD_SESSION", elapsed_s=0.3)
        check(ok and info.get("samples") == 153,
              f"legacy save got pumped samples ({info.get('samples')})")
        check(("get_data", 0.3) in fake.calls and ("save", "session") in fake.calls,
              f"legacy fallback called get_data then save ({fake.calls})")
    finally:
        unregister_session("OLD_SESSION")


def test_agent_op() -> None:
    print("── device.save agent op ──")
    from Application.Editor.Services.LiveCommandServer import LiveCommandServer

    close_all()
    tmp = tempfile.mkdtemp(prefix="device_save_op_")
    try:
        cfg = SigGenConfig.from_props({
            "device_name": "SAVE_OP", "channels": 2, "sampling_rate": 512,
            "buffer_seconds": 1.0, "save_dir": tmp,
        })
        init_session("SAVE_OP", cfg, dry_run=True)
        start_record("SAVE_OP", elapsed_s=0.0)
        result = LiveCommandServer._op_device_save({
            "device": "SAVE_OP", "save_scope": "session", "elapsed_s": 0.5,
            "tag": "op", "pump": True,
        })
        check(result.get("ok") is True, f"op ok ({result.get('detail')})")
        for key in ("paths", "meta_path", "samples", "written", "scope"):
            check(key in result, f"op returns {key}")
        check(result.get("written") is False and result.get("samples", 0) > 0,
              f"op dry-run written=0 samples>0 ({result.get('samples')})")
        check(result.get("scope") == "session", f"op scope = {result.get('scope')}")
        stop_record("SAVE_OP", save=False, elapsed_s=0.5)
        kill_device("SAVE_OP")
    finally:
        close_all()
        shutil.rmtree(tmp, ignore_errors=True)


def test_graph_node() -> None:
    print("── SaveDeviceData graph node / dry-run ──")
    close_all()
    tmp = tempfile.mkdtemp(prefix="device_save_graph_")
    try:
        g = GraphBuilder()
        GS, _FU, _GP = g.event_nodes()
        init = g.siggen_init("SAVE_GRAPH", channels=2, buffer_seconds=1.0, save_dir=tmp)
        start = g.siggen_start("SAVE_GRAPH")
        save = g.node("SaveDeviceData",
                      ["exec_in", "exec_out", "Path", "MetaPath", "Samples",
                       "Duration", "Written", "Ok"],
                      {"device_name": "SAVE_GRAPH", "save_scope": "session",
                       "tag": "graph", "pump": True})
        stop = g.siggen_stop("SAVE_GRAPH", scope="session")
        kill = g.siggen_kill("SAVE_GRAPH")
        g.link(GS, "exec", init, "exec_in")
        g.chain(init, start, save, stop, kill)

        graph = g.build()
        errors = validate_static(graph)
        check(not errors, f"static validation clean ({errors[:2]})")
        report = g.validate(max_frames=30)
        check(report.passed, f"graph dry-run passed ({report.dry_run})")
        if report.dry_run:
            types = report.dry_run.get("events_by_type", {})
            check("SaveDeviceData" in types,
                  f"SaveDeviceData executed in dry-run ({types.get('SaveDeviceData', 0)}x)")
        check(not os.listdir(tmp), f"graph dry-run left no files ({os.listdir(tmp)})")
        check(not any(name.startswith("dryrun#SAVE_GRAPH") for name in list_sessions()),
              "graph dry-run cleaned its session")
    finally:
        close_all()
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    print("=" * 60)
    print("Device save without Stop — paths / pump / node / dry-run")
    print("=" * 60)
    test_unique_paths()
    test_mid_record_save()
    test_dry_run_save()
    test_legacy_save_signature()
    test_agent_op()
    test_graph_node()
    total = _PASS + _FAIL
    print()
    print(f"RESULT: {'OK' if _FAIL == 0 else 'FAIL'} ({_PASS}/{total})")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
