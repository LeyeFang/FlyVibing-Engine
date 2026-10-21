"""
设备别名闭环测试 — 跨机器可迁移的设备身份（无头）。

协议: `Doc/Dev/device_io_protocol.md` §10（两级设备身份）。
锁定:
  1. `Application/Core/DeviceRegistry` — 绑定/解绑/持久化/损坏容错/名称校验/`@` 语法
  2. `SerialParallelDevice.resolve_port` — 物理直通 / `@name` 解析 / 未绑定**显式报错**
  3. 发送与监视路径 — 入队前解析（含 `""` 与"绑定但缺 port"两种显式错误）
  4. `SerialSend` 求值器 — 未配置端口不再假定 `COM1`; 未绑定别名 → 显式告警
  5. 图校验 — props 中未绑定的 `@ref` → warning `device_alias_unresolved`
  6. 扩展 ops — `ext.device.bind_alias` / `bind_nodes`（面板按钮同一实现）

运行: python Utils/Dev/test_runner.py --only device_alias
"""
# TIER: core

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "startup.bat")):
    _d = os.path.dirname(_d)
_ROOT = _d or ""
if _ROOT:
    sys.path.insert(0, _ROOT)

# ── 沙箱: 注册表不得污染真实机器配置 ──
_TMP = tempfile.mkdtemp(prefix="mge_devalias_")
_REG_FILE = os.path.join(_TMP, "devices.json")
os.environ["MGE_DEVICES_FILE"] = _REG_FILE

from Application.Core import DeviceRegistry as reg                              # noqa: E402
from Application.Functions.SerialParallelDevice import (                        # noqa: E402
    api as spd_api, monitor as spd_monitor, serial_manager, state as spd_state)

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


def _load_extension_module():
    """按文件路径加载官方示例扩展（与 ExtensionManager 同法, 不做包安装）."""
    path = os.path.join(_ROOT, "Application", "Functions", "SerialParallelDevice", "extension.py")
    spec = importlib.util.spec_from_file_location("spd_ext_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _StubCtx:
    def __init__(self, graph=None) -> None:
        self.logs: list[str] = []
        self.data_dir = _TMP
        self.graph = graph
        self.ops = None
        self.ui = None

    def log(self, msg: str) -> None:
        self.logs.append(str(msg))


class _StubGraph:
    """最小图门面（记录 set_props 调用）。"""

    def __init__(self, nodes: dict) -> None:
        self._nodes = {int(k): dict(v) for k, v in nodes.items()}   # id → {"type","props"}
        self.writes: list[tuple] = []

    def available(self) -> bool:
        return True

    def nodes(self):
        return [{"id": nid, "type": v["type"], "props": dict(v["props"])}
                for nid, v in self._nodes.items()]

    def find(self, prop, equals=None, prefix=None):
        out = []
        for item in self.nodes():
            val = item["props"].get(prop)
            if equals is not None and val != equals:
                continue
            if prefix is not None and not (isinstance(val, str) and val.startswith(prefix)):
                continue
            out.append(item)
        return out

    def set_props(self, node_id, fields):
        self.writes.append((int(node_id), dict(fields)))
        self._nodes[int(node_id)]["props"].update(dict(fields))
        return dict(self._nodes[int(node_id)]["props"])


def main() -> int:
    print("=" * 60)
    print("device alias loop — registry / resolution / evaluator / validation / ext ops")
    print("=" * 60)
    if os.path.exists(_REG_FILE):
        os.remove(_REG_FILE)
    reg._reset_for_tests()

    # ── 1. 注册表 ──────────────────────────────────────────────
    print("-- 1. DeviceRegistry --")
    reg.load(force=True)
    check("初始为空", reg.all() == {}, str(reg.all()))
    entry = reg.bind("mibox", transport="serial", port="COM5", baud=115200)
    check("bind 写入端点", entry.get("port") == "COM5" and entry.get("baud") == 115200)
    check("describe 可读", reg.describe("mibox") == "@mibox -> COM5 @115200",
          reg.describe("mibox"))
    reg._reset_for_tests()
    reg.load(force=True)
    check("持久化往返", reg.get("mibox") is not None and reg.get("mibox")["port"] == "COM5")
    try:
        reg.bind("bad name!", port="COM1")
        check("非法名称 → ValueError", False)
    except ValueError:
        check("非法名称 → ValueError", True)
    reg.set_hint("mibox", usb_serial="AB12")
    check("hint 合并", reg.get("mibox").get("hint", {}).get("usb_serial") == "AB12")
    with open(_REG_FILE, "w", encoding="utf-8") as fh:
        fh.write("{broken json")
    reg._reset_for_tests()
    check("损坏文件容错（空表, 不抛）", reg.load(force=True) == {})
    reg.bind("mibox", transport="serial", port="COM5", baud=115200)
    check("is_ref/parse_ref", reg.is_ref("@mibox") and reg.parse_ref("@mibox") == "mibox"
          and not reg.is_ref("COM5"))

    # ── 2. 解析 ────────────────────────────────────────────────
    print("-- 2. resolve_port --")
    check("物理端口直通", serial_manager.resolve_port("COM9") == "COM9")
    check("@name → 物理端口", serial_manager.resolve_port("@mibox") == "COM5")
    try:
        serial_manager.resolve_port("@nope")
        check("未绑定 → DeviceUnresolved", False)
    except reg.DeviceUnresolved as e:
        check("未绑定 → DeviceUnresolved（含绑定提示）", "bind" in str(e).lower(), str(e))
    try:
        serial_manager.resolve_port("")
        check("空端口 → ValueError", False)
    except ValueError:
        check("空端口 → ValueError", True)
    reg.bind("noport", transport="serial")
    try:
        serial_manager.resolve_port("@noport")
        check("绑定但缺 port → DeviceUnresolved", False)
    except reg.DeviceUnresolved:
        check("绑定但缺 port → DeviceUnresolved", True)

    # ── 3. 发送/监视路径（入队前解析） ─────────────────────────
    print("-- 3. send / watch resolve before queue --")
    spd_state._running = True                     # 只需队列行为, 不启真线程
    try:
        spd_api.send("@mibox", 115200, b"\x01")
        task = spd_state._tx_queue.get_nowait()
        port_attr = getattr(task, "port", None)
        check("send('@mibox') 入队为物理端口", port_attr == "COM5", f"got {port_attr!r}")
    finally:
        spd_state._running = False
        while not spd_state._tx_queue.empty():
            spd_state._tx_queue.get_nowait()
    try:
        spd_api.send("@nope", 115200, b"\x01")
        check("send('@nope') → 显式抛错（不静默）", False)
    except reg.DeviceUnresolved:
        check("send('@nope') → 显式抛错（不静默）", True)
    try:
        spd_monitor.start_watch("@nope", 115200)
        check("start_watch('@nope') → 显式抛错", False)
    except reg.DeviceUnresolved:
        check("start_watch('@nope') → 显式抛错", True)
    ws = spd_monitor.start_watch("@mibox", 115200)
    check("start_watch('@mibox') 记录物理端口", ws.get("port") == "COM5", str(ws))
    spd_monitor.stop_watch()

    # ── 4. 求值器: 未配置端口 / 未绑定别名 → 显式告警 ──────────
    print("-- 4. SerialSend evaluator --")
    from Application.Core.NodeGraph import _TYPES
    from Application.Functions.SerialParallelDevice import node_pack as io_eval

    class _TypeDef:
        pass
    type_def = _TYPES["SerialSend"]

    def _mk_g(props: dict):
        inst = type("I", (), {"node_type": "SerialSend", "props": dict(props),
                              "pin_ids": {}})()
        canvas = type("C", (), {"nodes": {1: inst}})()
        return type("G", (), {"_canvas": canvas, "_types": {"SerialSend": type_def},
                              "_read_input": lambda self, *a, **k: None})()

    logs: list = []

    class _Ctx:
        dry_run = True

        @staticmethod
        def emit_log(nid, kind, action, text):
            logs.append((nid, kind, action, text))

    io_eval._eval_serial_send(1, _Ctx(), _mk_g({}))
    check("空端口 → 显式 error 日志（不再假定 COM1）",
          any("no port configured" in t for _n, _k, _a, t in logs), str(logs))

    logs.clear()
    ctx_live = type("CtxLive", (), {"dry_run": False,
                                    "emit_log": staticmethod(
                                        lambda nid, kind, action, text:
                                        logs.append((nid, kind, action, text)))})()
    io_eval._eval_serial_send(1, ctx_live, _mk_g({"port": "@nope", "baud_rate": 9600}))
    check("未绑定别名 → 显式 error 日志",
          any("not bound" in t for _n, _k, _a, t in logs), str(logs))

    # ── 5. 图校验: 未绑定引用 → warning ───────────────────────
    print("-- 5. static validation warning --")
    from Application.Core.NodeGraph.validation.checks import static_check_graph
    pins = {p.name: 900 + i for i, p in enumerate(type_def.pins)}
    graph_data = {"nodes": {"7": {"node_type": "SerialSend", "pin_ids": dict(pins),
                                 "props": {"port": "@nope"}}}, "links": {}}
    codes = [e["code"] for e in static_check_graph(graph_data)]
    check("未绑定 @ref → device_alias_unresolved",
          "device_alias_unresolved" in codes, str(codes))
    graph_ok = {"nodes": {"7": {"node_type": "SerialSend", "pin_ids": dict(pins),
                               "props": {"port": "@mibox"}}}, "links": {}}
    codes_ok = [e["code"] for e in static_check_graph(graph_ok)]
    check("已绑定 @ref → 无该告警", "device_alias_unresolved" not in codes_ok, str(codes_ok))
    check("物理端口直写不触发别名校验",
          "device_alias_unresolved" not in [e["code"] for e in static_check_graph(
              {"nodes": {"7": {"node_type": "SerialSend", "pin_ids": dict(pins),
                               "props": {"port": "COM5"}}}, "links": {}})])

    # ── 6. 扩展 ops（面板按钮同一实现） ──────────────────────
    print("-- 6. ext.device.bind_alias / bind_nodes --")
    ext_mod = _load_extension_module()
    ext = ext_mod.DeviceExtension()
    stub_graph = _StubGraph({5: {"type": "SerialSend", "props": {"port": "COM5"}},
                             6: {"type": "SerialSend", "props": {"port": "COM7"}}})
    ctx = _StubCtx(graph=stub_graph)
    ext._ctx = ctx
    ext._settings["port"] = "COM5"
    ext._settings["baud"] = 115200

    res = ext._op_bind_alias({"name": "lab"})
    check("bind_alias 用面板当前端口", res["entry"]["port"] == "COM5", str(res))
    check("bind_alias 同步面板端口", ext._settings.get("port") == "COM5",
          str(ext._settings))
    try:
        ext._op_bind_alias({})
        check("bind_alias 缺 name → ValueError", False)
    except ValueError:
        check("bind_alias 缺 name → ValueError", True)

    dry = ext._op_bind_nodes({"name": "lab", "dry_run": True})
    check("bind_nodes dry_run 只报告", dry["would_migrate"] == [5] and not stub_graph.writes,
          str(dry))
    res2 = ext._op_bind_nodes({"name": "lab"})
    check("bind_nodes 迁移裸端口节点", res2["migrated"] == [5], str(res2))
    check("节点 props 已改为别名",
          stub_graph._nodes[5]["props"]["port"] == "@lab", str(stub_graph._nodes[5]))
    check("未匹配节点不受影响", stub_graph._nodes[6]["props"]["port"] == "COM7")

    try:
        ext._op_bind_nodes({"name": "ghost"})
        check("bind_nodes 未绑定别名 → ValueError(提示 bind_alias)", False)
    except ValueError as e:
        check("bind_nodes 未绑定别名 → ValueError(提示 bind_alias)",
              "bind_alias" in str(e), str(e))

    ext._op_bind_alias({"name": "lab", "unbind": True})
    check("unbind 生效", reg.get("lab") is None)

    # status 汇总（含别名视图）
    ext._op_bind_alias({"name": "lab2", "port": "COM5", "baud": 115200})
    st = ext._op_status({})
    check("status 含 devices 视图",
          any(d.get("alias") == "@lab2" for d in st.get("devices", [])), str(st.get("devices")))

    # ── 收尾 ──
    reg._reset_for_tests()
    if os.path.exists(_REG_FILE):
        os.remove(_REG_FILE)
    os.environ.pop("MGE_DEVICES_FILE", None)

    total = _RESULTS["pass"] + _RESULTS["fail"]
    status = "OK" if _RESULTS["fail"] == 0 else "FAIL"
    print("-" * 60)
    print(f"RESULT: {status} ({_RESULTS['pass']}/{total})")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
