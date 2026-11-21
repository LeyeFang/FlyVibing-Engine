"""端口台账（PortLedger / ports）往返与守卫测试。

覆盖:
  1. 引擎侧写入/读取/删除（pid 守卫: 不删别人的条目）
  2. 引擎 ↔ 工具仓**同格式**（一侧写、另一侧读；schema 1 字段一致）
  3. `status=starting` 预登记被继承（launch 的意图传给引擎），陈旧条目不继承
  4. 扫描状态机: editor / stale / reserved / free
  5. `choose_port` 跳过「正在启动」的预占端口
  6. `instance.info` / `instance.describe` 两个 op 注册且能写台账
  7. 启动参数 `--purpose/--owner/--tag/--touch/--note` 解析

用法:
    .venv-py314t\\Scripts\\python.exe Test/Application/Editor/test_port_ledger.py
"""
# SERIAL: port (端口台账/预占状态是机器级共享资源)

from __future__ import annotations

import os
import socket
import sys
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
while ROOT and not os.path.exists(os.path.join(ROOT, "startup.bat")):
    parent = os.path.dirname(ROOT)
    if parent == ROOT:
        ROOT = ""
        break
    ROOT = parent
assert ROOT, "repo root not found"
SRC = os.path.join(ROOT, "Utils", "ExtDev", "EditorMcp", "src")
for _p in (ROOT, SRC):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# 台账目录隔离（引擎与工具仓两侧都读这个变量）
_LEDGER_DIR = tempfile.mkdtemp(prefix="fve_ledger_test_")
os.environ["FVE_PORT_LEDGER_DIR"] = _LEDGER_DIR

from Application.Editor.Services import PortLedger                      # noqa: E402
from Application.Editor.StartupOptions import parse_instance_meta        # noqa: E402

_failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'OK' if ok else 'FAIL'}] {name}" + (f"  -- {detail}" if detail and not ok else ""))
    if not ok:
        _failures.append(name)


def _free_ports(count: int) -> list[int]:
    """取若干个当前空闲的回环端口（绑定 0 → 记录 → 立刻关闭）。"""
    socks, ports = [], []
    for _ in range(count):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        socks.append(sock)
        ports.append(sock.getsockname()[1])
    for sock in socks:
        sock.close()
    return ports


def main() -> int:
    from engine_editor_mcp import ports as tool_ports
    from engine_editor_mcp.launcher import choose_port

    print("-- 1. 引擎侧读写 --")
    port_a = _free_ports(1)[0]
    entry = PortLedger.register(port_a, purpose="单测：引擎写入", owner="agent:test",
                                tags=["ui"], touches=["Examples/UIShowcase"])
    check("register 返回条目", bool(entry) and entry["port"] == port_a)
    on_disk = PortLedger.read(port_a)
    check("落盘可读", bool(on_disk) and on_disk["purpose"] == "单测：引擎写入")
    check("schema=1", on_disk.get("schema") == 1)
    check("status=ready", on_disk.get("status") == "ready")
    check("started_at 是 ISO", "T" in str(on_disk.get("started_at")))
    check("update 合并字段", bool(PortLedger.update(notes="别跑全量测试"))
          and PortLedger.read(port_a)["notes"] == "别跑全量测试")
    check("pid 不符不删除", PortLedger.remove(port_a, pid=1) is False)
    check("pid 相符才删除", PortLedger.remove(port_a, pid=os.getpid()) is True)
    check("删除后读不到", PortLedger.read(port_a) is None)

    print("-- 2. 引擎 ↔ 工具仓同格式 --")
    port_b = _free_ports(1)[0]
    PortLedger.register(port_b, purpose="往返：引擎→工具", owner="agent:test")
    tool_view = tool_ports.read_entry(port_b)
    check("工具侧读到引擎条目", bool(tool_view) and tool_view["purpose"] == "往返：引擎→工具")
    check("工具侧认得 schema", tool_view.get("schema") == tool_ports.SCHEMA)

    port_c = _free_ports(1)[0]
    tool_ports.register(port_c, kind="editor", status="starting",
                        purpose="往返：工具→引擎", owner="agent:other", tags=["pie"])
    engine_view = PortLedger.read(port_c)
    check("引擎侧读到工具条目", bool(engine_view) and engine_view["purpose"] == "往返：工具→引擎")
    check("引擎侧认得 starting 状态", engine_view.get("status") == "starting")

    print("-- 3. 预登记继承 / 陈旧条目不继承 --")
    PortLedger.register(port_c)
    inherited = PortLedger.read(port_c)
    check("starting 条目的 purpose 被继承", inherited.get("purpose") == "往返：工具→引擎")
    check("register 后状态为 ready", inherited.get("status") == "ready")
    check("tags 被继承", inherited.get("tags") == ["pie"])
    PortLedger.unregister()

    port_d = _free_ports(1)[0]
    tool_ports.register(port_d, kind="editor", status="ready", purpose="上个实例的旧目的")
    fresh = PortLedger.register(port_d)
    check("陈旧条目（ready）不被继承", fresh.get("purpose") != "上个实例的旧目的",
          str(fresh.get("purpose")))
    PortLedger.unregister()

    print("-- 4. 扫描状态机 --")
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    live_port = listener.getsockname()[1]
    PortLedger.register(live_port, purpose="扫描：在监听")
    try:
        rows = {row["port"]: row for row in tool_ports.scan(live_port, live_port)}
        check("监听中的端口 → editor", rows.get(live_port, {}).get("state") == "editor")
        check("报告台账摘要", "扫描：在监听" in rows.get(live_port, {}).get("summary", ""))
    finally:
        listener.close()
        PortLedger.unregister()

    stale_port = _free_ports(1)[0]
    PortLedger.register(stale_port, purpose="扫描：残留")
    PortLedger.unregister()
    tool_ports.register(stale_port, kind="editor", status="ready", purpose="扫描：残留")
    rows = {row["port"]: row for row in tool_ports.scan(stale_port, stale_port)}
    check("端口空闲但有条目 → stale", rows.get(stale_port, {}).get("state") == "stale")
    tool_ports.remove_entry(stale_port)

    reserved_port = _free_ports(1)[0]
    tool_ports.register(reserved_port, kind="editor", status="starting", purpose="正在启动")
    rows = {row["port"]: row for row in tool_ports.scan(reserved_port, reserved_port)}
    check("starting + 空闲 → reserved", rows.get(reserved_port, {}).get("state") == "reserved")

    print("-- 5. choose_port 跳过预占 --")
    pick = choose_port("auto", start=reserved_port, end=reserved_port + 40)
    check("自动端口避开 reserved", pick != reserved_port, f"picked {pick}")
    check("自动端口本身空闲", tool_ports.is_port_free(pick))
    tool_ports.remove_entry(reserved_port)

    print("-- 6. instance.* op --")
    from Application.Editor.Services.LiveCommandServer import LiveCommandServer

    LiveCommandServer._register_ops()
    names = set(LiveCommandServer._ops)
    check("instance.info 已注册", "instance.info" in names)
    check("instance.describe 已注册", "instance.describe" in names)

    op_port = _free_ports(1)[0]
    PortLedger.register(op_port, purpose="op 前")
    LiveCommandServer.port = op_port
    described = LiveCommandServer._op_instance_describe(
        {"purpose": "op 后：SetUIText 验证", "tags": "ui,pie"})
    check("describe 写回台账",
          PortLedger.read(op_port)["purpose"] == "op 后：SetUIText 验证")
    check("describe 接受逗号串 tags", PortLedger.read(op_port)["tags"] == ["ui", "pie"])
    check("describe 返回 changed", described.get("changed") == ["purpose", "tags"])
    info = LiveCommandServer._op_instance_info({})
    check("info 带台账字段", info["instance"].get("purpose") == "op 后：SetUIText 验证")
    check("info 带状态字段", "state" in info["instance"])
    check("info 指向台账文件", info["ledger_path"].endswith(f"{op_port}.json"))
    PortLedger.unregister()
    LiveCommandServer.port = 0

    print("-- 7. 启动参数（实例自述） --")
    meta = parse_instance_meta(["--port", "8988", "--purpose", "PIE 验证",
                                "--owner", "agent:codebuddy",
                                "--tag", "ui", "--tag", "pie",
                                "--touch", "Examples/UIShowcase", "--note", "别跑全量"])
    check("purpose 解析", meta.get("purpose") == "PIE 验证")
    check("owner 解析", meta.get("owner") == "agent:codebuddy")
    check("tag 可重复", meta.get("tags") == ["ui", "pie"])
    check("touch 可重复", meta.get("touches") == ["Examples/UIShowcase"])
    check("note 解析", meta.get("notes") == "别跑全量")
    check("无自述参数 → 空", parse_instance_meta(["--port", "8988"]) == {})

    print()
    if _failures:
        print(f"RESULT: FAILED ({len(_failures)}) — " + ", ".join(_failures))
        return 1
    print("RESULT: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
