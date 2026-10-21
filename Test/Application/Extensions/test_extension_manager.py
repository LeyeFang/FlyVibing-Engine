"""
Extension 体系测试 — ExtensionManager 发现/启停/隔离 + 扩展 op 增量扫描（无 GL）。

锁定内容（协议: Doc/Dev/extension_dev_protocol.md §5/§9/§12）:
  1. 发现: 内置 Application/Functions/** 默认扩展 manifest（sigproc/bci/device）
  2. manifest 校验: api_version 不匹配 / entry 缺失 → broken 隔离
  3. 启停: enable → ext.sigproc.info 注册可调 → disable → 注销; 持久化往返
  4. 无 entry 的计划扩展: enable 被拒绝（受控错误）
  5. 用户目录扫描（env MGE_EXTENSIONS_DIR 沙箱）+ 重复 id 保留先者
  6. 异常遏制: on_load 抛异常 → broken 且不影响其它扩展
  7. 开关与隔离不变式: 扩展 op 不进入核心注册表（守卫见 test_action_contract 53 计数）

沙箱: MGE_EXTENSIONS_STATE / MGE_EXTENSIONS_DATA / MGE_EXTENSIONS_DIR / MGE_DEVICES_FILE → 临时目录。
运行: python Utils/Dev/test_runner.py --only extension_manager
"""
# TIER: core

from __future__ import annotations

import os
import sys
import tempfile
import json

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "_path_setup.py")):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)
    import _path_setup  # noqa: E402

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


_GOOD_EXT = '''\
from Application.Core.Extension.ExtensionBase import ExtensionBase

class UserOkExtension(ExtensionBase):
    id = "uext_ok"
    name = "User OK"
    version = "0.1.0"

    def on_load(self, ctx):
        ctx.ops.register("ping", lambda args: {"pong": True}, summary="ping")


def create_extension() -> UserOkExtension:
    return UserOkExtension()
'''


def _write(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


def main() -> int:
    print("=" * 60)
    print("Extension manager — discovery/enable/disable/containment (headless)")
    print("=" * 60)

    from Application.Editor.Extensions.ExtensionManager import ExtensionManager
    from Application.Editor.Services.LiveCommandServer import LiveCommandServer

    # ── 沙箱环境 ──────────────────────────────────────────────
    tmp = tempfile.mkdtemp(prefix="mge_ext_test_")
    user_dir = os.path.join(tmp, "user_ext")
    state_path = os.path.join(tmp, "extensions_state.json")
    data_dir = os.path.join(tmp, "ext_data")
    devices_path = os.path.join(tmp, "devices.json")
    saved_env = {k: os.environ.get(k) for k in
                 ("MGE_EXTENSIONS_DIR", "MGE_EXTENSIONS_STATE", "MGE_EXTENSIONS_DATA",
                  "MGE_DEVICES_FILE")}
    os.environ["MGE_EXTENSIONS_DIR"] = user_dir
    os.environ["MGE_EXTENSIONS_STATE"] = state_path
    os.environ["MGE_EXTENSIONS_DATA"] = data_dir
    # device 扩展 on_enable 会跑 ext.device.autobind → 必须落在沙箱注册表上
    os.environ["MGE_DEVICES_FILE"] = devices_path

    # 用户目录测试扩展: 合法一个 / 坏 api_version 一个 / 加载即炸一个 / 重复 id 一个
    _write(os.path.join(user_dir, "uext_ok", "extension.json"), json.dumps({
        "id": "uext_ok", "name": "User OK", "version": "1.0.0", "api_version": "1",
        "maturity": "skeleton", "entry": "extension.py:create_extension"}))
    _write(os.path.join(user_dir, "uext_ok", "extension.py"), _GOOD_EXT)
    _write(os.path.join(user_dir, "uext_planned", "extension.json"), json.dumps({
        "id": "uext_planned", "name": "User Planned", "version": "1.0.0",
        "api_version": "1", "maturity": "planned"}))
    _write(os.path.join(user_dir, "uext_bad", "extension.json"), json.dumps({
        "id": "uext_bad", "name": "User Bad", "version": "1.0.0", "api_version": "99",
        "maturity": "skeleton", "entry": "extension.py:create_extension"}))
    _write(os.path.join(user_dir, "uext_boom", "extension.json"), json.dumps({
        "id": "uext_boom", "name": "User Boom", "version": "1.0.0", "api_version": "1",
        "maturity": "skeleton", "entry": "extension.py:create_extension"}))
    _write(os.path.join(user_dir, "uext_boom", "extension.py"),
           "def create_extension():\n    raise RuntimeError('boom')\n")
    _write(os.path.join(user_dir, "uext_dup", "extension.json"), json.dumps({
        "id": "sigproc", "name": "Dup Sigproc", "version": "9.9.9", "api_version": "1",
        "maturity": "skeleton", "entry": "extension.py:create_extension"}))
    _write(os.path.join(user_dir, "uext_dup", "extension.py"), _GOOD_EXT)
    # capabilities 含 ui 但未继承 UIExtensionBase → 加载必须失败隔离
    _write(os.path.join(user_dir, "uext_ui_missing", "extension.json"), json.dumps({
        "id": "uext_ui_missing", "name": "UI Missing", "version": "1.0.0", "api_version": "1",
        "maturity": "skeleton", "capabilities": ["ops", "ui"],
        "entry": "extension.py:create_extension"}))
    _write(os.path.join(user_dir, "uext_ui_missing", "extension.py"),
           "from Application.Core.Extension.ExtensionBase import ExtensionBase\n\n"
           "class UiMissingExtension(ExtensionBase):\n"
           "    id = 'uext_ui_missing'\n\n"
           "def create_extension():\n"
           "    return UiMissingExtension()\n")

    try:
        # ── 1. 发现 ──────────────────────────────────────────
        print("── discovery ──")
        ExtensionManager.ensure_init(force=True)
        infos = {i["id"]: i for i in ExtensionManager.list_infos()}
        for eid in ("sigproc", "bci", "device", "uext_ok", "uext_bad", "uext_boom"):
            check(f"discovered: {eid}", eid in infos)
        check("sigproc loadable (skeleton)", infos["sigproc"]["loadable"] is True
              and infos["sigproc"]["maturity"] == "skeleton")
        check("bci / device 已可装载",
              infos["bci"]["maturity"] == "partial" and infos["bci"]["loadable"] is True
              and infos["device"]["loadable"] is True)

        # ── 2. manifest 校验与隔离 ───────────────────────────
        print("── validation / containment ──")
        check("api_version 不匹配 → broken", infos["uext_bad"]["status"] == "broken"
              and "api_version" in infos["uext_bad"]["error"], infos["uext_bad"]["error"])
        check("bci 可装载但尚未启用", infos["bci"]["status"] == "disabled")

        # ── 5. 重复 id 保留先者 ──────────────────────────────
        check("重复 id 保留内置先者 (uext_dup 被忽略)",
              "uext_dup" not in infos and "sigproc" in infos
              and infos["sigproc"]["dir"].replace("\\", "/").endswith("Application/Functions/SignalProcess"))

        # ── 3. 启停 + 扩展 op 扫描 ───────────────────────────
        print("── enable / ops scan ──")
        r = ExtensionManager.enable("sigproc")
        check("enable sigproc → loaded", r["loaded"] is True and r["status"] == "enabled", str(r))
        ops = LiveCommandServer.extension_ops_snapshot()
        check("ext.sigproc.info 已增量注册", "ext.sigproc.info" in ops, str(sorted(ops)))
        snap = LiveCommandServer._ext_ops["ext.sigproc.info"]({})
        check("ext.sigproc.info 可调 (owner 正确)",
              snap.get("extension") == "sigproc", str(snap))
        check("扩展 op 不进核心注册表",
              "ext.sigproc.info" not in LiveCommandServer._ops)

        r = ExtensionManager.disable("sigproc")
        check("disable sigproc → op 注销",
              r["loaded"] is False and "ext.sigproc.info" not in LiveCommandServer.extension_ops_snapshot())
        with open(state_path, encoding="utf-8") as fh:
            state = json.load(fh)
        check("启用状态持久化 (disable → false)", state["enabled"].get("sigproc") is False)

        # ── 3a. BCI extension shell (owner: node pack + evaluators) ──
        r = ExtensionManager.enable("bci")
        check("enable bci → loaded", r["loaded"] is True, str(r))
        ops = LiveCommandServer.extension_ops_snapshot()
        check("ext.bci.status 已增量注册", "ext.bci.status" in ops, str(sorted(ops)))
        bci_snap = LiveCommandServer._ext_ops["ext.bci.status"]({})
        check("ext.bci.status 返回节点包",
              bci_snap.get("extension") == "bci" and "InitFBCSP" in bci_snap.get("nodes", []),
              str(bci_snap))
        ExtensionManager.disable("bci")

        # ── 3b. 持久化往返（模拟重启）────────────────────────
        ExtensionManager.enable("sigproc")
        ExtensionManager._infos = {}
        ExtensionManager._instances = {}
        ExtensionManager._scanned = False
        ExtensionManager.ensure_init()   # 重新扫描 → 自动装载已启用
        info = ExtensionManager.get("sigproc")
        check("重启重扫后自动装载 (state=true)", info.loaded is True
              and "ext.sigproc.info" in LiveCommandServer.extension_ops_snapshot())
        ExtensionManager.disable("sigproc")

        # ── 4. 计划扩展 enable 拒绝 ──────────────────────────
        try:
            ExtensionManager.enable("uext_planned")
            check("enable 计划扩展 → 受控拒绝", False, "no exception")
        except ValueError as e:
            check("enable 计划扩展 → 受控拒绝", "not loadable" in str(e), str(e))

        # ── 6. 加载即炸 → broken 隔离 ────────────────────────
        print("── load containment ──")
        r = ExtensionManager.enable("uext_boom")
        check("on_load 崩溃 → broken 且不抛出",
              r["loaded"] is False and "boom" in (r["error"] or ""), str(r))
        r = ExtensionManager.enable("uext_ok")
        check("崩溃扩展不影响其它扩展 (uext_ok enabled)",
              r["loaded"] is True and "ext.uext_ok.ping" in LiveCommandServer.extension_ops_snapshot())

        # ── 6b. device 官方示例装载冒烟（含 ctx.ui 窗口注册） ──
        print("── device demo smoke ──")
        r = ExtensionManager.enable("device")
        check("device 扩展装载 (官方示例)", r["loaded"] is True, str(r))
        ops_now = LiveCommandServer.extension_ops_snapshot()
        check("ext.device.* ops 已注册",
              "ext.device.status" in ops_now and "ext.device.monitor_snapshot" in ops_now,
              str(sorted(ops_now)))
        st = LiveCommandServer._ext_ops["ext.device.status"]({})
        check("ext.device.status 可调 (io_running 字段)",
              isinstance(st, dict) and "io_running" in st and "watch" in st, str(st)[:160])
        check("device 冒烟不污染真实注册表 (MGE_DEVICES_FILE 沙箱)",
              os.environ.get("MGE_DEVICES_FILE") == devices_path, devices_path)
        from Application.Editor.UI.UIManager import UIManager
        check("监视面板窗口已注册 (ctx.ui.register_window)",
              UIManager.find("Serial/Parallel Monitor") is not None)
        ExtensionManager.disable("device")
        check("device 卸载 → 窗口与 ops 同时清理",
              "ext.device.status" not in LiveCommandServer.extension_ops_snapshot()
              and UIManager.find("Serial/Parallel Monitor") is None)

        # ── 6c. capabilities ui ↔ UIExtensionBase 校验（语言层第二道闸） ──
        r = ExtensionManager.enable("uext_ui_missing")
        check("capabilities 含 ui 但未继承 UIExtensionBase → broken",
              r["loaded"] is False and "UIExtensionBase" in (r["error"] or ""), str(r))

        # ── 7. unload_all ───────────────────────────────────
        print("── unload_all ──")
        ExtensionManager.unload_all()
        check("unload_all 清空全部扩展 op",
              not LiveCommandServer.extension_ops_snapshot(),
              str(sorted(LiveCommandServer.extension_ops_snapshot())))
    finally:
        # ── 环境与单例状态恢复 ───────────────────────────────
        try:
            ExtensionManager.unload_all()
        except Exception:
            pass
        LiveCommandServer._ext_ops.clear()
        LiveCommandServer._ext_ops_owner.clear()
        LiveCommandServer._ext_ops_summary.clear()
        ExtensionManager._infos = {}
        ExtensionManager._instances = {}
        ExtensionManager._scanned = False
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    total = _RESULTS["pass"] + _RESULTS["fail"]
    status = "OK" if _RESULTS["fail"] == 0 else "FAIL"
    print()
    print(f"RESULT: {status} ({_RESULTS['pass']}/{total})")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
