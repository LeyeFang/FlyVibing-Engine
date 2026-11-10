"""扩展激活策略守卫 — builtin 恒激活 / local 与用户目录 opt-in / 菜单只列 UI 扩展。

背景（2026-11-10）:
  社区夹具作者报告 "示例注入不到引擎"。根因不是示例机制坏了，而是**扩展默认停用**
  （`extensions.json` 里那条 `false`）。于是把激活策略拆成三层:

    1. builtin = `Application/Functions/**` **且**在 allowlist（`official_extensions.json`
       = `.gitignore` 白名单）→ **恒激活**（`always_on`），不可停用;
       `FVE_EXTENSIONS_BUNDLED=off` 是安全模式（内置扩展把编辑器搞崩时的逃生口）。
    2. local   = 同在 `Application/Functions` 下但不在 allowlist（本地/社区夹具）→ opt-in;
    3. user    = `%APPDATA%/FlyVibingEngine/extensions` → 状态文件 opt-in。

  “在 Functions 里”≠“内置”—— 整个 Functions 目录在 .gitignore 里，只有白名单行放行的
  才随引擎/安装包分发（判定: `ExtensionManager.scope_of()`）。

  同时主菜单 Extensions 收敛为 **UI 面板入口**（只列 `has_ui`），后台扩展的统一管理面
  移到 设置 ▸ Extensions 页。

锁定:
  1. builtin 识别（scope/always_on）+ 扫描即装载，不依赖状态文件;
  2. `disable()` 拒绝 builtin（附带可执行的替代方案文案）; 窗口 X 不排队停用;
  3. local 与用户扩展仍是 opt-in（默认停用 → enable 后 loaded）;
  4. `has_ui` 判据 = capabilities 含 ui 或已注册 ExtensionPanel;
  5. 设置面板注册了 `extensions` 页（管理的唯一入口）;
  6. `FVE_EXTENSIONS_BUNDLED=off` → 退回旧的 opt-in 语义;
  7. 状态文件只记非 builtin 扩展（builtin 的旧条目在扫描时被清理）。

运行: python Utils/Dev/test_runner.py --only extension_activation
"""
# TIER: core

from __future__ import annotations

import json
import os
import sys
import tempfile

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "_path_setup.py")):
    _parent = os.path.dirname(_d)
    if _parent == _d:
        _d = ""
        break
    _d = _parent
if _d:
    sys.path.insert(0, _d)
import _path_setup  # noqa: E402,F401

_RESULTS = {"pass": 0, "fail": 0}

_USER_EXT = (
    "from Application.Core.Extension.ExtensionBase import ExtensionBase\n\n"
    "class OptInExtension(ExtensionBase):\n"
    "    id = 'uext_optin'\n"
    "    name = 'Opt-in'\n"
    "    version = '1.0.0'\n\n"
    "def create_extension():\n"
    "    return OptInExtension()\n"
)


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


def _write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _write_json(path: str, data: dict) -> None:
    _write(path, json.dumps(data, ensure_ascii=False))


def main() -> int:
    print("=" * 60)
    print("Extension activation — builtin always-on / local+user opt-in (headless)")
    print("=" * 60)

    from Application.Editor.Extensions.ExtensionManager import ExtensionManager
    from Application.Editor.UI.panels.SettingsPanel import SettingsPanel

    tmp = tempfile.mkdtemp(prefix="mge_ext_activation_")
    user_dir = os.path.join(tmp, "user_ext")
    saved_env = {k: os.environ.get(k) for k in
                 ("FVE_EXTENSIONS_DIR", "MGE_EXTENSIONS_DIR",
                  "FVE_EXTENSIONS_STATE", "MGE_EXTENSIONS_STATE",
                  "FVE_EXTENSIONS_DATA", "MGE_EXTENSIONS_DATA",
                  "FVE_DEVICES_FILE", "MGE_DEVICES_FILE",
                  "FVE_EXTENSIONS_BUNDLED", "MGE_EXTENSIONS_BUNDLED")}
    try:
        for key in saved_env:
            os.environ.pop(key, None)
        os.environ["FVE_EXTENSIONS_DIR"] = user_dir
        os.environ["FVE_EXTENSIONS_STATE"] = os.path.join(tmp, "state.json")
        os.environ["FVE_EXTENSIONS_DATA"] = os.path.join(tmp, "data")
        # device 扩展的 on_load 会碰设备注册表 — 必须落在沙箱
        os.environ["FVE_DEVICES_FILE"] = os.path.join(tmp, "devices.json")

        # ── 1. builtin 恒激活（不写状态文件、不需要 enable）──
        print("── builtin auto-activation ──")
        ExtensionManager.ensure_init(force=True)
        infos = {i["id"]: i for i in ExtensionManager.list_infos()}
        bundled_ids = [eid for eid, i in infos.items() if i.get("scope") == "builtin"]
        check("builtin extensions discovered", bool(bundled_ids), str(sorted(infos)))
        root = os.path.abspath(ExtensionManager._extensions_root()).replace("\\", "/")
        check("builtin dirs live under Application/Functions",
              all(str(infos[eid]["dir"]).replace("\\", "/").startswith(root)
                  for eid in bundled_ids),
              str([infos[eid]["dir"] for eid in bundled_ids]))
        allow = ExtensionManager.builtin_allowlist()["ids"]
        check("builtin ids all come from the allowlist",
              set(bundled_ids) <= allow,
              f"not allowlisted: {sorted(set(bundled_ids) - allow)}")
        local_ids = [eid for eid, i in infos.items() if i.get("scope") == "local"]
        check("Functions fixtures outside the allowlist are local, not always_on",
              all(infos[eid]["always_on"] is False for eid in local_ids),
              str({eid: infos[eid]["always_on"] for eid in local_ids}))
        loadable_bundled = [eid for eid in bundled_ids if infos[eid]["loadable"]]
        check("builtin loadable ones are always_on",
              loadable_bundled and all(infos[eid]["always_on"] for eid in loadable_bundled),
              str({eid: infos[eid]["always_on"] for eid in loadable_bundled}))
        check("builtin loadable ones are loaded without opt-in",
              bool(loadable_bundled) and all(infos[eid]["loaded"] for eid in loadable_bundled),
              str({eid: infos[eid]["loaded"] for eid in loadable_bundled}))
        state_file = os.environ["FVE_EXTENSIONS_STATE"]
        check("builtin activation does not write the state file",
              not os.path.exists(state_file), state_file)

        # ── 2. 不可停用（受控拒绝 + 不排队）──
        print("── builtin cannot be disabled ──")
        victim = "device" if "device" in loadable_bundled else loadable_bundled[0]
        try:
            ExtensionManager.disable(victim)
            check("disable(builtin) refused", False, "no exception")
        except ValueError as e:
            check("disable(builtin) refused", "built" in str(e), str(e))
        check("builtin still loaded after refused disable",
              ExtensionManager.get(victim).loaded is True)
        ExtensionManager.request_disable(victim)
        check("close-policy disable is not queued for builtin",
              victim not in ExtensionManager._pending_disable)

        # ── 3. has_ui 判据（菜单可见性）──
        print("── has_ui / menu scope ──")
        ui_ids = {eid for eid, i in infos.items() if i.get("has_ui")}
        check("capability ui → has_ui", "device" in ui_ids, str(sorted(ui_ids)))
        headless = [eid for eid in bundled_ids
                    if "ui" not in [str(c) for c in infos[eid]["capabilities"]]]
        check("headless builtin extensions are not has_ui",
              all(eid not in ui_ids for eid in headless), str(headless))
        menu_ids = {eid for eid, i in infos.items() if i.get("has_ui") and i.get("loadable")}
        check("menu set excludes headless extensions",
              not (menu_ids & set(headless)), str(sorted(menu_ids)))

        # ── 4. 用户扩展仍 opt-in ──
        print("── user extension stays opt-in ──")
        _write_json(os.path.join(user_dir, "uext_optin", "extension.json"), {
            "id": "uext_optin", "name": "Opt-in", "version": "1.0.0",
            "api_version": "1", "maturity": "skeleton",
            "entry": "extension.py:create_extension"})
        _write(os.path.join(user_dir, "uext_optin", "extension.py"), _USER_EXT)
        ExtensionManager.rescan()
        infos = {i["id"]: i for i in ExtensionManager.list_infos()}
        check("user extension discovered", "uext_optin" in infos, str(sorted(infos)))
        check("user extension is scope=user", infos["uext_optin"]["scope"] == "user")
        check("user extension starts disabled (opt-in)",
              infos["uext_optin"]["always_on"] is False
              and infos["uext_optin"]["status"] == "disabled",
              str(infos["uext_optin"]))
        check("user extension enable → loaded",
              ExtensionManager.enable("uext_optin")["loaded"] is True)
        check("user extension disable → allowed",
              ExtensionManager.disable("uext_optin")["loaded"] is False)

        # ── 4b. 状态文件只该记非 builtin 扩展（builtin 的旧条目被清理）──
        print("── state pruning ──")
        # 模拟旧策略留下的脏条目：builtin 写了 false，user 写了 false
        _write_json(state_file, {"version": 2,
                                 "enabled": {victim: False, "uext_optin": False},
                                 "python": {}})
        ExtensionManager.rescan()
        with open(state_file, "r", encoding="utf-8") as fh:
            pruned = json.load(fh)
        check("builtin entry pruned from state file",
              victim not in pruned.get("enabled", {}), str(pruned))
        check("user entry preserved in state file",
              "uext_optin" in pruned.get("enabled", {}), str(pruned))
        check("builtin stays always-on after prune",
              ExtensionManager.get(victim).always_on is True
              and ExtensionManager.get(victim).loaded is True)
        check("user extension still opt-in after prune",
              ExtensionManager.get("uext_optin").loaded is False)

        # ── 5. 设置页是管理入口 ──
        print("── settings page ──")
        page_ids = [p.id for p in SettingsPanel.pages()]
        check("settings registers the extensions page", "extensions" in page_ids,
              str(page_ids))
        page = next(p for p in SettingsPanel.pages() if p.id == "extensions")
        check("extensions page is core-owned", page.owner == "core", page.owner)

        # ── 6. 安全模式：FVE_EXTENSIONS_BUNDLED=off ──
        print("── safe mode ──")
        os.environ["FVE_EXTENSIONS_BUNDLED"] = "off"
        ExtensionManager.rescan()
        off_infos = {i["id"]: i for i in ExtensionManager.list_infos()}
        check("builtin activation disabled by env",
              all(off_infos[eid]["always_on"] is False for eid in loadable_bundled),
              str({eid: off_infos[eid]["always_on"] for eid in loadable_bundled}))
        check("builtin not auto-loaded in safe mode",
              all(off_infos[eid]["loaded"] is False for eid in loadable_bundled),
              str({eid: off_infos[eid]["loaded"] for eid in loadable_bundled}))
        check("builtin disable allowed in safe mode (old semantics)",
              ExtensionManager.disable(victim)["loaded"] is False)
    finally:
        try:
            ExtensionManager.unload_all()
        except Exception:  # noqa: BLE001 — 清理失败不掩盖断言结果
            pass
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    total = _RESULTS["pass"] + _RESULTS["fail"]
    status = "OK" if _RESULTS["fail"] == 0 else "FAIL"
    print()
    print(f"RESULT: {status} ({_RESULTS['pass']}/{total})")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
