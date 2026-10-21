"""自动重绑（T2/T1）测试 — 指纹采集 / 唯一候选 / 歧义拒绝 / dry-run。

运行: python Utils/Dev/test_runner.py --only device_autobind
"""

# TIER: core

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "startup.bat")):
    _d = os.path.dirname(_d)
_ROOT = _d or ""
if _ROOT:
    sys.path.insert(0, _ROOT)

_TMP = tempfile.mkdtemp(prefix="mge_devautobind_")
_REG_FILE = os.path.join(_TMP, "devices.json")
os.environ["MGE_DEVICES_FILE"] = _REG_FILE

from Application.Core import DeviceRegistry as reg                              # noqa: E402
from Application.Functions.SerialParallelDevice import identity                 # noqa: E402

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


def _load_extension_module():
    path = os.path.join(_ROOT, "Application", "Functions", "SerialParallelDevice", "extension.py")
    spec = importlib.util.spec_from_file_location("spd_ext_autobind_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _StubCtx:
    def __init__(self) -> None:
        self.logs: list[str] = []

    def log(self, msg: str) -> None:
        self.logs.append(str(msg))


def _reset_registry() -> None:
    reg._reset_for_tests()
    if os.path.exists(_REG_FILE):
        os.remove(_REG_FILE)


CH340_A = {
    "device": "COM3", "description": "USB-SERIAL CH340", "hwid": "USB VID:PID=1A86:7523",
    "serial_number": "", "vid": 0x1A86, "pid": 0x7523, "location": "1-7",
    "manufacturer": "wch.cn", "product": "", "interface": "",
}
CH340_B = dict(CH340_A, device="COM14", location="1-9")
FTDI_A = {
    "device": "COM8", "description": "USB Serial Port", "hwid": "FTDIBUS",
    "serial_number": "AQ026C00A", "vid": 0x0403, "pid": 0x6001, "location": "2-1",
    "manufacturer": "FTDI", "product": "FT232R USB UART", "interface": "A",
}
FTDI_A_MOVED = dict(FTDI_A, device="COM19", location="3-4")
FTDI_B = dict(FTDI_A, device="COM13", serial_number="AQ026C01A")


def main() -> int:
    print("=" * 60)
    print("device autobind — fingerprint / match / extension ops")
    print("=" * 60)

    # ── 1. 指纹与匹配 ─────────────────────────────────────────
    print("-- 1. identity --")
    h340 = identity.fingerprint(CH340_A)
    check("CH340 无序列号 → 不写 usb_serial", "usb_serial" not in h340, str(h340))
    check("CH340 写 vid_pid", h340.get("vid_pid") == "1A86:7523", str(h340))
    check("CH340 写 location（仅诊断）", h340.get("location") == "1-7", str(h340))
    check("单候选 vid_pid → matched",
          identity.match(h340, [CH340_A])["status"] == "matched")
    amb = identity.match(h340, [CH340_A, CH340_B])
    check("双 CH340 → ambiguous", amb["status"] == "ambiguous", str(amb))
    check("歧义候选数 2", len(amb["candidates"]) == 2, str(amb))
    check("location-only 不匹配",
          identity.match({"location": "1-7"}, [CH340_A])["status"] == "unmatched")
    hftdi = identity.fingerprint(FTDI_A)
    check("FTDI 写 usb_serial", hftdi.get("usb_serial") == "AQ026C00A", str(hftdi))
    check("同序列号换口 → matched（serial 优先）",
          identity.match(hftdi, [FTDI_A_MOVED])["status"] == "matched")
    check("不同序列号 → unmatched",
          identity.match(hftdi, [FTDI_B])["status"] == "unmatched")

    # ── 2. 扩展 op ────────────────────────────────────────────
    print("-- 2. extension ops --")
    ext_mod = _load_extension_module()
    ext = ext_mod.DeviceExtension()
    ctx = _StubCtx()
    ext._ctx = ctx
    ext._settings["baud"] = 9600
    ports: list[dict] = []
    ext._list_ports_now = lambda: list(ports)

    _reset_registry()
    ports[:] = [CH340_A]
    res = ext._op_bind_alias({"name": "lab", "port": "COM3", "baud": 9600})
    entry = reg.get("lab") or {}
    check("bind_alias 采集 hint", entry.get("hint", {}).get("vid_pid") == "1A86:7523",
          str(entry))
    check("bind_alias 返回含 hint", res["entry"].get("hint", {}).get("vid_pid") == "1A86:7523",
          str(res))

    ports[:] = [CH340_A]
    res = ext._op_autobind({"name": "lab"})
    check("当前口在位 → unchanged",
          len(res["unchanged"]) == 1 and not res["bound"], str(res))

    ports[:] = [CH340_B]
    res = ext._op_autobind({})
    check("换口 → auto-bound", len(res["bound"]) == 1
          and res["bound"][0]["to"] == "COM14", str(res))
    check("注册表端口已更新", reg.get("lab")["port"] == "COM14", str(reg.get("lab")))
    check("auto-bound 日志", any("auto-bound" in m for m in ctx.logs), str(ctx.logs))
    check("面板端口跟随旧口 → 换到新口", ext._settings.get("port") == "COM14",
          str(ext._settings.get("port")))

    # 歧义: 两台同型号同时在位，旧端口不在位
    _reset_registry()
    reg.bind("twin", port="COM99", baud=9600)
    reg.set_hint("twin", **identity.fingerprint(CH340_A))
    ports[:] = [CH340_A, CH340_B]
    res = ext._op_autobind({"name": "twin"})
    check("双候选 → ambiguous", len(res["ambiguous"]) == 1, str(res))
    check("歧义不改注册表", reg.get("twin")["port"] == "COM99", str(reg.get("twin")))

    # dry-run 不改注册表
    _reset_registry()
    reg.bind("dry", port="COM3", baud=9600)
    reg.set_hint("dry", **identity.fingerprint(CH340_A))
    ports[:] = [CH340_B]
    res = ext._op_autobind({"name": "dry", "dry_run": True})
    check("dry-run 报告 would-bind", len(res["bound"]) == 1
          and res["bound"][0]["to"] == "COM14", str(res))
    check("dry-run 不改注册表", reg.get("dry")["port"] == "COM3", str(reg.get("dry")))

    # T1: 唯一序列号换口
    _reset_registry()
    ports[:] = [FTDI_A]
    ext._op_bind_alias({"name": "ftdi", "port": "COM8", "baud": 115200})
    ports[:] = [FTDI_A_MOVED]
    res = ext._op_autobind({"name": "ftdi"})
    check("唯一序列号换口 → auto-bound", len(res["bound"]) == 1
          and res["bound"][0]["to"] == "COM19", str(res))
    check("matched_by=usb_serial", res["bound"][0]["matched_by"] == "usb_serial", str(res))

    # 旧绑定无 hint: 当前在位时补录指纹
    _reset_registry()
    reg.bind("legacy", port="COM3", baud=9600)
    ports[:] = [CH340_A]
    res = ext._op_autobind({})
    check("旧绑定补录 hint", (reg.get("legacy") or {}).get("hint", {}).get("vid_pid")
          == "1A86:7523", str(reg.get("legacy")))
    check("旧绑定不换口", reg.get("legacy")["port"] == "COM3", str(reg.get("legacy")))

    # 无指纹 / 无匹配
    _reset_registry()
    reg.bind("ghost", port="COM99", baud=9600)
    ports[:] = [CH340_A]
    res = ext._op_autobind({"name": "ghost"})
    check("无 hint → unmatched", len(res["unmatched"]) == 1, str(res))

    try:
        ext._op_autobind({"name": "missing"})
        check("未绑定 name → ValueError", False)
    except ValueError:
        check("未绑定 name → ValueError", True)

    print("-" * 60)
    ok = _RESULTS["fail"] == 0
    print(f"RESULT: {'OK' if ok else 'FAIL'} ({_RESULTS['pass']}/{_RESULTS['pass'] + _RESULTS['fail']})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
