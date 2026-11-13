"""ExtensionManager — 扩展发现 / 装载 / 启停 / 隔离（L1, M0 骨架）。

架构: Doc/Dev/extension_protocol.md §1-§4
开发规范: Doc/ExtDev/extension_dev_protocol.md

M0 实装范围:
  - 发现: `Application/Functions/**/extension.json` + 用户目录（env
    `FVE_EXTENSIONS_DIR` / 旧 `MGE_EXTENSIONS_DIR`，或 `%APPDATA%/FlyVibingEngine/extensions`）
  - **激活策略（2026-11-10，11-10 修正）**: 只有 **内置**（allowlist =
    `Application/Functions/official_extensions.json` ∪ `.gitignore` 白名单）才 **恒激活**
    （`always_on`，不可停用; `FVE_EXTENSIONS_BUNDLED=off` 为安全模式）;
    `local`（同在 Functions 下但**不在** allowlist 的本地/社区夹具）与 `user`
    （用户目录）都仍 opt-in（状态文件 / 设置页 Extensions 页签）。
    判定集中在一处: `ExtensionManager.scope_of()`。
  - manifest 校验（id / api_version / entry; 非法 → broken 隔离展示）
  - 启停: 持久化到 `%APPDATA%/FlyVibingEngine/editor_state/extensions.json`（env
    `FVE_EXTENSIONS_STATE` / 旧 `MGE_EXTENSIONS_STATE` 可覆盖; 测试沙箱用）
  - ops 贡献: ctx.ops.register → LiveCommandServer 扩展注册表（ext.<id>.* 强制前缀）
  - nodes 贡献: ctx.nodes.register_pack → NodePackRegistry（节点类型/evaluator/控件字段）
  - 异常遏制: 加载失败 → broken（菜单/op 可见错误原因, 不拖垮编辑器）

菜单分工（2026-11-10）: 主菜单 Extensions 只列**有 UI 面板**的扩展（`has_ui`），
  纯后台扩展（ops/nodes/examples/devices）统一在 设置 ▸ Extensions 页管理。

设计未实装（见 dev protocol §13）: threads / jobs / settings /
外部安装(.mgext) / 依赖拓扑（requires 仅解析展示）。
"""

from __future__ import annotations

from Application.Core import AppIdentity

import importlib.util
import json
import os
import re
import sys
import threading
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from Application.Core.Extension.ExtensionBase import ExtensionBase
from Application.Core.Extension.ExtensionContext import ExtensionContext

_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_API_MAJOR = "1"    # 支持 api_version: "1" / "1.x"

# 内置扩展 allowlist（随引擎/安装包分发的那一批）。**不是**「位于 Application/Functions」。
_BUILTIN_MANIFEST = "official_extensions.json"
_GITIGNORE_FILE = ".gitignore"


def _norm_name(name: str) -> str:
    """目录名归一化 —— Windows 大小写不敏感，allowlist 与 .gitignore 必须同一口径。"""
    return os.path.normcase(str(name or "").strip())


def _is_within(path: str, root: str) -> bool:
    """`path` 是否位于 `root` 之下（跨盘符 → False; 不做符号链接解析）。"""
    try:
        target = os.path.abspath(path)
        base = os.path.abspath(root)
        return os.path.commonpath([target, base]) == base
    except (ValueError, OSError):
        return False


def _has_registered_panel(ext_id: str) -> bool:
    """该扩展当前是否注册了 UI 窗口（事实判据 — 无编辑器/无 UI 环境 → False）。"""
    try:
        from Application.Editor.Extensions.ExtensionUI import ExtensionPanel
        from Application.Editor.UI.UIManager import UIManager
        return any(isinstance(panel, ExtensionPanel) and panel.ext_id == ext_id
                   for panel in list(UIManager._panels))
    except Exception:  # noqa: BLE001 — 无 UI 环境（无头/测试）按无面板处理
        return False


# ════════════════════════════════════════════════════════════════
# 数据模型
# ════════════════════════════════════════════════════════════════

@dataclass
class ExtensionInfo:
    id: str = ""
    name: str = ""
    version: str = ""
    api_version: str = ""
    maturity: str = "planned"          # planned | skeleton | partial | stable
    description: str = ""
    entry: str = ""
    capabilities: list = field(default_factory=list)
    requires: list = field(default_factory=list)
    provider: str = ""                # Example 默认签名（manifest provider/signature；空 = @<id>）
    export: bool = True               # 是否随 Project Export 游戏层分发（manifest export:false 可关）
    python: dict = field(default_factory=dict)          # manifest 声明的解释器协议（原始规格）
    python_runtime: dict = field(default_factory=dict)  # 已装载时的解析结果（ctx.python.explain）
    #: manifest `python.runtime` 依赖契约（产物侧；导出强制，见 ExtensionRuntimeDeps）
    runtime_contract: dict = field(default_factory=dict)
    dir: str = ""
    manifest_path: str = ""
    scope: str = "user"               # builtin | local | user（见 ExtensionManager.scope_of）
    bundled: bool = False             # = scope == "builtin"（allowlist 内, 随引擎分发、恒激活）
    always_on: bool = False           # 本次会话被强制激活（bundled 且未被 env 关闭）
    loadable: bool = False             # entry 存在且 manifest 合法
    enabled: bool = False              # 用户启用状态（持久化; bundled 恒为 True）
    loaded: bool = False               # 当前已装载
    error: str = ""                    # broken 原因（空 = 健康）
    ops: list = field(default_factory=list)   # 已注册的 op 名（查询时动态填充）

    def status(self) -> str:
        if self.error:
            return "broken"
        if not self.loadable:
            return "planned"
        return "enabled" if self.loaded else "disabled"

    @property
    def has_ui(self) -> bool:
        """是否向编辑器贡献了 UI 面板（决定它出现在哪一级菜单）。

        两条判据（任一成立即可）:
          1. manifest `capabilities` 声明 `ui`（意图 — 未启用时也能被识别，菜单据此保留入口）;
          2. 当前确实注册了 `ExtensionPanel` 窗口（事实 — 兜住未声明但用了 `ctx.ui` 的扩展）。
        """
        if "ui" in [str(c) for c in (self.capabilities or [])]:
            return True
        return _has_registered_panel(self.id)

    def to_dict(self) -> dict:
        from Application.Editor.Extensions.ExtensionManager import (
            ExtensionManager as _M,
        )
        return {
            "id": self.id, "name": self.name, "version": self.version,
            "api_version": self.api_version, "maturity": self.maturity,
            "description": self.description, "status": self.status(),
            "enabled": self.enabled, "loaded": self.loaded, "loadable": self.loadable,
            "error": self.error, "dir": self.dir, "ops": list(self.ops),
            "capabilities": list(self.capabilities), "requires": list(self.requires),
            "provider": self.provider,
            "export": bool(self.export),
            # scope: builtin（allowlist 内, 恒启用）| local（Functions 下的非白名单夹具）
            #        | user（用户目录）—— 后两者都由此处/设置页 opt-in
            "scope": self.scope or ("builtin" if self.bundled else "user"),
            "always_on": bool(self.always_on),
            "has_ui": bool(self.has_ui),
            # 面板：**视图**状态（与 enabled 是两件事 — 菜单勾选读这个）
            "panel_visible": bool(_M.has_visible_panel(self.id)),
            "panel_state": _M.panel_state(self.id),
            "python": {**({"declared": dict(self.python)} if self.python else {}),
                       **(dict(self.python_runtime) if self.python_runtime else {})},
            # 产物侧依赖契约（`python.runtime`）：导出时**强制**，缺失即导出失败。
            # 面板/节点开发者用它确认"成品里到底会不会有这些包"。
            "runtime": dict(self.runtime_contract) if self.runtime_contract else {},
        }


class _ExtensionOpRegistrar:
    """ctx.ops 门面 — 注册 ext.<owner_id>.* 操作（增量扫描通道, 见 dev protocol §9）。"""

    def __init__(self, owner_id: str) -> None:
        self._owner = owner_id

    def register(self, name: str, fn, summary: str = "") -> str:
        """注册一个扩展 op。返回完整 op 名 `ext.<id>.<name>`。"""
        from Application.Editor.Services.LiveCommandServer import LiveCommandServer

        full = f"ext.{self._owner}.{name}"
        LiveCommandServer.register_extension_ops(
            self._owner, {full: fn}, {full: summary or f"extension op ({self._owner})"})
        return full


class _ExtensionNodeRegistrar:
    """ctx.nodes 门面 — 扩展节点包注册（M1）。

    - 内置扩展的 `node_pack.py` 由 NodeGraph 自动发现（无需扩展 enable）；
    - 第三方/运行期 pack 可在这里显式注册，disable/unload 时反注册本次注册的 pack。
    """

    def __init__(self, owner_id: str, extension_dir: str = "") -> None:
        self._owner = owner_id
        self._extension_dir = extension_dir
        self._registered: set[str] = set()

    def register_pack(self, pack: dict) -> dict:
        from Application.Core.NodeGraph.node_packs import NodePackRegistry
        pack = dict(pack or {})
        pack.setdefault("owner", self._owner)
        pack.setdefault("id", f"{self._owner}.{pack.get('name', 'pack')}")
        # 记录来源目录 — 游戏导出按需收集扩展时用；不改变运行期求值。
        if self._extension_dir:
            pack.setdefault("dir", self._extension_dir)
        result = NodePackRegistry.register(pack)
        self._registered.add(str(result["pack"]))
        return result

    def catalog(self) -> list[dict]:
        from Application.Core.NodeGraph.node_packs import NodePackRegistry
        return NodePackRegistry.catalog(self._owner)

    def unregister_all(self) -> list[str]:
        """移除本扩展通过 ctx.nodes 显式注册的节点包。"""
        from Application.Core.NodeGraph.node_packs import NodePackRegistry
        removed: list[str] = []
        for pack_id in sorted(self._registered):
            pack = NodePackRegistry._packs.get(pack_id)
            if pack:
                removed.extend(sorted(pack.get("types") or ()))
                NodePackRegistry.unregister_owner(str(pack.get("owner", self._owner)))
        self._registered.clear()
        return removed


# ════════════════════════════════════════════════════════════════
# 管理器
# ════════════════════════════════════════════════════════════════

class ExtensionManager:
    """扩展管理器（类级单例; 编辑器应用层）。"""

    _infos: dict[str, ExtensionInfo] = {}
    _instances: dict[str, ExtensionBase] = {}
    _node_facades: dict[str, _ExtensionNodeRegistrar] = {}
    _example_facades: dict[str, object] = {}
    _python_facades: dict[str, object] = {}     # ext id → ExtensionPython（子进程托管/诊断）
    # 最近一次 enable 就地恢复的节点（op 回执用）
    last_rehydrated_nodes: list = []
    # 最近一次 disable 后画布上变成“未注册类型”的节点数（面板 X=停用 的边界提示）
    last_disable_unresolved: int = 0
    _scanned: bool = False
    _builtin_cache: frozenset | None = None   # 内置目录名缓存（scan/rescan 重算）

    # 挂起停用请求（窗口 X 关闭等可从渲染线程发起 — 实际执行在主线程 pump）
    _pending_disable: set = set()
    _pending_lock = threading.Lock()

    # ── 路径解析（env 可覆盖 → 测试沙箱/自定义部署） ────────────

    @classmethod
    def _engine_root(cls) -> str:
        return str(Path(__file__).resolve().parents[3])   # .../Application/Editor/Extensions → repo root

    @classmethod
    def _extensions_root(cls) -> str:
        """引擎扩展根（`Application/Functions`）。

        **注意**：放在这里的扩展**不一定**是内置的。本地/社区夹具
        也常驻该目录（目录整体在 .gitignore 里），它们不进安装包，仍按 opt-in 管理。
        """
        return os.path.join(cls._engine_root(), "Application", "Functions")

    # ── 内置判定（allowlist ∪ .gitignore 白名单）─────────────────

    @classmethod
    def builtin_allowlist(cls) -> dict:
        """内置扩展 allowlist（`Application/Functions/official_extensions.json`）。

        返回 `{"dirs": set, "ids": set, "source": str, "ok": bool}`；文件缺失
        → `ok=False`（不崩，届时内置集合只来自 .gitignore 白名单）。
        """
        path = os.path.join(cls._extensions_root(), _BUILTIN_MANIFEST)
        dirs: set = set()
        ids: set = set()
        ok = True
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            entries = data.get("extensions") if isinstance(data, dict) else None
            for entry in entries or []:
                if not isinstance(entry, dict):
                    continue
                if entry.get("dir"):
                    dirs.add(_norm_name(entry["dir"]))
                if entry.get("id"):
                    ids.add(str(entry["id"]).strip().lower())
        except FileNotFoundError:
            ok = False
        except Exception as e:  # noqa: BLE001 — allowlist 坏了不拖垮扩展体系
            ok = False
            print(f"[Extensions] allowlist read failed ({path}): {e!r}")
        return {"dirs": dirs, "ids": ids, "source": path, "ok": ok}

    @classmethod
    def gitignore_builtin_dirs(cls) -> set:
        """`.gitignore` 白名单行（`!Application/Functions/<Dir>/`）→ 目录名集合。

        这是「内置」的第二信号：能被那行白名单放行入库/进安装包的目录，就是主线的一部分。
        与 allowlist 必须一致 —— 守卫测试 `test_extension_builtin_scope` 在两者漂移时失败。
        """
        path = os.path.join(cls._engine_root(), _GITIGNORE_FILE)
        out: set = set()
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    text = line.strip()
                    if not text.startswith("!") or not text.endswith("/"):
                        continue          # 只认「目录」白名单（`!.../<Dir>/`）
                    target = text[1:].replace("\\", "/").strip().strip("/")
                    parts = target.split("/")
                    if (len(parts) == 3 and parts[0] == "Application"
                            and parts[1] == "Functions"):
                        out.add(_norm_name(parts[2]))
        except OSError:
            pass
        return out

    @classmethod
    def builtin_dirs(cls) -> set:
        """内置扩展目录名 = allowlist ∪ .gitignore 白名单（缓存到下一次 scan）。"""
        cached = cls._builtin_cache
        if cached is not None:
            return set(cached)
        dirs = set(cls.builtin_allowlist()["dirs"]) | cls.gitignore_builtin_dirs()
        cls._builtin_cache = frozenset(dirs)
        return dirs

    @classmethod
    def scope_of(cls, directory: str, ext_id: str = "") -> str:
        """扩展目录 → scope: `builtin` | `local` | `user`。

        - **builtin**: 位于 `Application/Functions` **且**在 allowlist/.gitignore 白名单内
          → 随引擎分发，恒激活、不可停用；
        - **local**  : 位于 `Application/Functions` 但**不在** 白名单（本地/社区夹具）
          → 与用户扩展同一套 opt-in，可在 设置 ▸ Extensions 启停；
        - **user**   : 用户目录（`%APPDATA%/FlyVibingEngine/extensions`）。
        """
        directory = str(directory or "")
        if not _is_within(directory, cls._extensions_root()):
            return "user"
        name = _norm_name(os.path.basename(os.path.normpath(directory)))
        if name in cls.builtin_dirs():
            return "builtin"
        if ext_id and str(ext_id).strip().lower() in cls.builtin_allowlist()["ids"]:
            return "builtin"     # 目录名被改过，但 id 仍在 allowlist 内
        return "local"

    @classmethod
    def bundled_activation(cls) -> bool:
        """内置扩展是否强制激活（默认 True）。

        `FVE_EXTENSIONS_BUNDLED=off`（旧 `MGE_` 前缀同样生效）关闭 —— 给测试沙箱和
        "某个内置扩展把编辑器搞崩了" 的排查场景留一条生路。
        """
        raw = str(AppIdentity.env_get("EXTENSIONS_BUNDLED", "on") or "on").strip().lower()
        return raw not in ("0", "off", "false", "no", "disabled")

    @classmethod
    def _user_dir(cls) -> str:
        return AppIdentity.env_get("EXTENSIONS_DIR") or os.path.join(
            os.environ.get("APPDATA", os.path.expanduser("~")), AppIdentity.APP_NAME, "extensions")

    @classmethod
    def _state_path(cls) -> str:
        return AppIdentity.env_get("EXTENSIONS_STATE") or os.path.join(
            AppIdentity.data_dir("editor_state"), "extensions.json")

    @classmethod
    def _data_dir(cls, ext_id: str) -> str:
        base = AppIdentity.env_get("EXTENSIONS_DATA") or AppIdentity.data_dir("extensions_data")
        return os.path.join(base, ext_id)

    # ── 状态持久化 ───────────────────────────────────────────────

    @classmethod
    def _read_state_full(cls) -> dict:
        """状态文件 → `{"enabled": {...}, "python": {...}, "panels": {...}}`。

        `panels`（2026-11-13）: 每个扩展**面板是否应显示**的持久意图。
        它和 `enabled` 是两件事 —— 前者是视图，后者是生命周期；菜单勾选读前者。
        """
        try:
            # `utf-8-sig`: 用户会用记事本/VSCode 手改这个文件，Windows 记事本默认
            # 写 UTF-8 **带 BOM** —— 按纯 utf-8 读会在 BOM 上抛 JSONDecodeError，
            # 然后静默回落到默认（= 所有扩展开关归零，2026-11-13 实测踩到）。
            with open(cls._state_path(), "r", encoding="utf-8-sig") as fh:
                data = json.load(fh)
        except FileNotFoundError:
            return {"enabled": {}, "python": {}, "panels": {}}
        except Exception as e:  # noqa: BLE001 — 损坏状态文件按默认处理
            print(f"[Extensions] state read failed (using defaults): {e!r}")
            return {"enabled": {}, "python": {}, "panels": {}}
        if not isinstance(data, dict):
            return {"enabled": {}, "python": {}, "panels": {}}
        python = data.get("python") or {}
        panels = data.get("panels") or {}
        return {
            "enabled": dict(data.get("enabled") or {}),
            "python": {str(k): str(v) for k, v in python.items() if str(v).strip()}
            if isinstance(python, dict) else {},
            "panels": {str(k): bool(v) for k, v in panels.items()}
            if isinstance(panels, dict) else {},
        }

    @classmethod
    def _read_state(cls) -> dict:
        return cls._read_state_full()["enabled"]

    @classmethod
    def _write_state(cls, enabled: dict, python: dict | None = None,
                     panels: dict | None = None) -> None:
        path = cls._state_path()
        full = cls._read_state_full()
        if python is None:
            python = full["python"]
        if panels is None:
            panels = full["panels"]
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"version": 2, "enabled": enabled, "python": python,
                       "panels": panels},
                      fh, indent=2, ensure_ascii=False)

    # ── 解释器覆盖（`extension.python` op）───────────────────────

    @classmethod
    def python_overrides(cls) -> dict:
        """全部解释器覆盖（ext id → exe；不含环境变量/manifest 的解析）。"""
        return dict(cls._read_state_full()["python"])

    @classmethod
    def set_python_override(cls, ext_id: str, path: str) -> dict:
        """设置/清除某扩展的解释器覆盖（立即生效，不需重启）。

        path 为空 = 清除覆盖（回落到 env → manifest → 引擎解释器）。
        """
        info = cls._require(ext_id)
        full = cls._read_state_full()
        value = str(path or "").strip()
        if value:
            full["python"][ext_id] = value
        else:
            full["python"].pop(ext_id, None)
        cls._write_state(full["enabled"], full["python"])
        facade = cls._python_facades.get(info.id)
        if facade is not None:
            facade.apply_override(value)
        return cls.python_status(ext_id)

    @classmethod
    def python_status(cls, ext_id: str, probe: bool = True) -> dict:
        """某扩展的解释器状态（未装载时给声明 + 覆盖，不猜运行期字段）。"""
        cls.ensure_init()
        info = cls._require(ext_id)
        facade = cls._python_facades.get(info.id)
        if facade is None:
            # 未装载也能回答「会选哪个解释器」——临时解析（不 spawn、不落盘）
            try:
                from Application.Core.Extension.ExtensionPython import ExtensionPython
                facade = ExtensionPython(
                    info.id, extension_dir=info.dir, data_dir=cls._data_dir(info.id),
                    engine_root=cls._engine_root(), spec=info.python,
                    override=cls.python_overrides().get(info.id, ""))
            except Exception:  # noqa: BLE001 — 解析失败按声明返回
                facade = None
        if facade is not None:
            data = facade.explain(probe=probe and bool(facade.exists()))
        else:
            declared = dict(info.python or {})
            data = {"mode": declared.get("mode", "engine"),
                    "source": "declared", "executable": "",
                    "declared": declared, "problems": [], "children": 0}
        return {
            "id": info.id,
            "loaded": bool(info.loaded),
            "override": cls.python_overrides().get(info.id, ""),
            "python": data,
        }

    # ── 扫描 / 发现 ──────────────────────────────────────────────

    @classmethod
    def ensure_init(cls, force: bool = False) -> None:
        """首次访问自动扫描（幂等; force=True 等价 rescan）。"""
        if force or not cls._scanned:
            cls.scan()

    @classmethod
    def scan(cls) -> None:
        """发现并解析全部扩展; 自动装载已启用者。"""
        cls._builtin_cache = None          # allowlist / .gitignore 可能刚被改过
        root = Path(cls._engine_root())
        paths: list[Path] = []
        funcs = root / "Application" / "Functions"
        if funcs.is_dir():
            paths += sorted(funcs.glob("**/extension.json"))
        user = Path(cls._user_dir())
        if user.is_dir():
            paths += sorted(user.glob("*/extension.json"))

        infos: dict[str, ExtensionInfo] = {}
        for p in paths:
            info = cls._parse_manifest(p)
            if info.id in infos:
                print(f"[Extensions] duplicate id '{info.id}' ignored: {info.manifest_path} "
                      f"(first: {infos[info.id].manifest_path})")
                continue
            infos[info.id] = info

        cls._infos = infos
        cls._scanned = True

        # ── 激活策略（2026-11-10 起）─────────────────────────────
        #   **内置**（allowlist 内 `official_extensions.json` + `.gitignore` 白名单）
        #   → 恒激活：它们随引擎/安装包分发，“装好即用”的一部分；
        #     local（Functions 下但不内置）与 user（用户目录）→ 仍由状态文件 opt-in。
        #     判定见 `scope_of()`；白名单外的本地夹具属于 local，不受恒激活影响。
        state = cls._read_state()
        force_bundled = cls.bundled_activation()
        for info in infos.values():
            if not info.loadable:
                continue
            if info.bundled and force_bundled:
                info.always_on = True
                info.enabled = True
                cls._load(info)
            elif state.get(info.id, False):
                info.enabled = True
                cls._load(info)
        # ★ 面板恢复（2026-11-13）: 「启用」不等于「显示」。以前 scan 里只 `_load`
        #   从不 `show_all`，于是**状态文件里 enabled 的扩展每次启动都只有面板注册、
        #   没有面板可见** —— 而 Extensions 菜单勾的是 enabled → 用户看到「勾着却没
        #   面板」。现在把「面板是否显示」作为独立持久意图（state["panels"]）恢复，
        #   菜单勾选读的是同一件事（`has_visible_panel`），两条腿永远一致。
        #   细节见 `_restore_panel_intents`。
        cls._restore_panel_intents(infos)
        # ★ 状态文件只应记录「非内置」扩展：内置恒激活，留着的旧条目会误导
        #   （"device: false" 但实际是开着的）。仅在恒激活模式下清理 —— 安全模式下
        #   状态文件仍是内置扩展的权威开关，不能动。
        if force_bundled:
            stale = [ext_id for ext_id in state
                     if (infos.get(ext_id) is not None and infos[ext_id].bundled)]
            if stale:
                for ext_id in stale:
                    state.pop(ext_id, None)
                cls._write_state(state)
                print(f"[Extensions] state pruned (built-in is always-on): {sorted(stale)}")
        print(f"[Extensions] scan: {len(infos)} found"
              f" ({sum(1 for i in infos.values() if i.loadable)} loadable,"
              f" {sum(1 for i in infos.values() if i.error)} broken,"
              f" {sum(1 for i in infos.values() if i.always_on)} built-in always-on,"
              f" {sum(1 for i in infos.values() if i.scope == 'local')} local)"
              f" — built-in activation {force_bundled}"
              f"{'' if force_bundled else ' (FVE_EXTENSIONS_BUNDLED=off)'}")

    @classmethod
    def rescan(cls) -> None:
        """卸载全部已装载扩展并重新扫描（Extensions 菜单 ▸ Rescan）。"""
        for info in cls._infos.values():
            if info.loaded:
                cls._unload(info)
        cls.scan()

    @classmethod
    def _restore_panel_intents(cls, infos: dict) -> None:
        """把持久意图落到窗口可见性上（scan 激活阶段后调用）— 菜单勾选/视图同步的地基。

        按**窗口名**而不是按扩展: 用户昨天开着 Device Monitor，今天还是开着。

        三种情形：

        * `panels[name] is True`  → 打开（上次就开着）;
        * `panels[name] is False` → 保持隐藏（用户上次关掉的，别自己回来）;
        * **没有记录**（首次出现）→ 由窗口注册时声明的 `show_on_enable` 决定，
          但**只对非内置扩展**生效：内置扩展恒激活，"首次运行"和"用户早先关掉了"
          在状态文件里无法区分，自动弹窗等于覆盖用户的明确选择（也让 e2e 场景的
          默认布局漂移）。用户自己装的扩展则正是刚点过「启用」的那一个，
          值得享受和 `enable()` 一样的待遇（否则就是 issue 报告的那个现象:
          勾着却没面板）。

        写入一律走 `panel.visible` setter（唯一咽喉），因此这里不直接碰状态文件。
        """
        panels = cls._read_state_full()["panels"]
        try:
            from Application.Editor.Extensions.ExtensionUI import ExtensionPanel
            from Application.Editor.UI.UIManager import UIManager
        except Exception:  # noqa: BLE001 — 无 UI 环境
            return
        loaded = {i.id: i for i in infos.values() if i.loaded and i.has_ui}
        if not loaded:
            return
        shown: list[str] = []
        for panel in list(UIManager._panels):
            if not isinstance(panel, ExtensionPanel):
                continue
            info = loaded.get(panel.ext_id)
            if info is None:
                continue
            want = panels.get(panel.name)
            if want is None:
                want = bool(panel.show_on_enable) and not bool(info.bundled)
            if bool(panel.visible) == bool(want):
                continue
            panel.visible = bool(want)    # setter 落盘（首跑顺带记录意图，之后稳定）
            if want:
                shown.append(panel.name)
        if shown:
            print(f"[Extensions] panel state restored: {sorted(shown)}")

    @classmethod
    def _parse_manifest(cls, path: Path) -> ExtensionInfo:
        folder_id = path.parent.name.lower()
        info = ExtensionInfo(id=folder_id, dir=str(path.parent), manifest_path=str(path))
        # ★ 内置 = allowlist（`official_extensions.json` ∪ `.gitignore` 白名单）**且**位于
        #   Application/Functions —— 不是“放进该目录就算内置”：不在白名单的本地
        #   夹具也常驻那里（目录整体已 gitignore），它们不进安装包，仍按 opt-in 管理。
        info.scope = cls.scope_of(str(path.parent))
        info.bundled = info.scope == "builtin"
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                raise ValueError("manifest must be a JSON object")
            info.id = str(data.get("id") or folder_id)
            info.name = str(data.get("name") or info.id)
            # allowlist 也按 id 登记（目录名可改）—— 真实 id 解析后再确认一次
            if info.scope != "builtin":
                info.scope = cls.scope_of(str(path.parent), info.id)
                info.bundled = info.scope == "builtin"
            info.version = str(data.get("version") or "0.0.0")
            info.api_version = str(data.get("api_version") or "")
            info.maturity = str(data.get("maturity") or "planned")
            info.description = str(data.get("description") or "")
            info.entry = str(data.get("entry") or "")
            info.capabilities = list(data.get("capabilities") or [])
            info.requires = list(data.get("requires") or [])
            info.provider = str(data.get("provider") or data.get("signature") or "")
            info.export = bool(data.get("export", True))
            raw_python = data.get("python")
            if isinstance(raw_python, str):
                info.python = {"mode": raw_python.strip().lower()}
            elif isinstance(raw_python, dict):
                info.python = dict(raw_python)
            elif raw_python not in (None, ""):
                raise ValueError("manifest python must be a string or an object")
            # 产物侧依赖契约（`python.runtime`）—— 与导出器共用**同一个**解析实现，
            # 所以在编辑器里 `extension.list` 看到的问题就是导出时会挡下来的问题。
            try:
                from Application.Core.Extension import (
                    ExtensionRuntimeDeps as _RuntimeDeps,
                )
                info.runtime_contract = _RuntimeDeps.parse(
                    data, ext_id=info.id, ext_dir=str(path.parent),
                    data_dir=cls._data_dir(info.id),
                    engine_root=cls._engine_root(),
                ).to_dict()
            except Exception as e:  # noqa: BLE001 — 契约问题不阻断扫描（导出会挡）
                info.runtime_contract = {"problems": [f"{type(e).__name__}: {e}"]}
            if not _ID_RE.match(info.id):
                raise ValueError(f"invalid id {info.id!r} (expect [a-z][a-z0-9_]*)")
            if not info.api_version or not info.api_version.startswith(_API_MAJOR):
                raise ValueError(
                    f"api_version mismatch: manifest={info.api_version!r}, engine supports {_API_MAJOR}.x")
            if info.entry:
                entry_file = info.entry.split(":", 1)[0] or "extension.py"
                if not (path.parent / entry_file).is_file():
                    raise ValueError(f"entry file not found: {entry_file}")
                info.loadable = True
        except Exception as e:  # noqa: BLE001 — 任何 manifest 问题 → broken 隔离
            info.error = f"{type(e).__name__}: {e}"
        return info

    # ── 启停 ─────────────────────────────────────────────────────

    @classmethod
    def enable(cls, ext_id: str) -> dict:
        """启用扩展（加载 + on_enable; 持久化）。对应 设置 ▸ Extensions 的「启用」。

        注意与**视图**的区别（2026-11-13）: 主菜单 Extensions 的勾选框表示“面板可见”，
        不再等于“已启用”。关闭面板请用 `hide_panels`/`toggle_panels`，那不会卸载扩展。

        内置扩展（allowlist 内）恒激活：这里只保证"已装载 + 面板显示"
        （用户点它通常是"把我刚才关掉的面板叫回来"），不写状态文件。
        """
        info = cls._require(ext_id)
        if not info.loadable:
            raise ValueError(
                f"extension '{ext_id}' is not loadable "
                f"(maturity={info.maturity}; see its TODO.md / dev protocol)")
        if info.always_on:
            if not info.loaded:
                cls._load(info)
            cls.show_panels(ext_id)          # 恒激活扩展不写 enabled, 但要记面板意图
            cls._sync_ops(info)
            return info.to_dict()
        info.enabled = True
        state = cls._read_state()
        state[ext_id] = True
        cls._write_state(state)
        if not info.loaded:
            cls._load(info)
        if info.loaded:
            try:
                cls._instances[ext_id].on_enable()
            except Exception as e:  # noqa: BLE001
                traceback.print_exc()
                info.error = f"on_enable: {type(e).__name__}: {e}"
        # 启用 = “想看面板” — 重置窗口可见性（X 隐藏后再次启用即重新打开; dev protocol §7）
        try:
            cls.show_panels(ext_id)          # 内含持久化: panels[id] = True
        except Exception:  # noqa: BLE001 — 无 UI 环境跳过
            pass
        cls._sync_ops(info)
        # 已打开的画布就地补全此前“未知”的节点（ISSUE 2026-11-03）:
        # 只 enable 不重载场景的话，画布仍缓存着 unknown，预检会继续拦截 —— 用户会以为
        # hint 是错的。这里在加载成功后立刻补 pin 并重算 unknown 集合。
        if info.loaded:
            try:
                cls._rehydrate_canvas()
            except Exception:  # noqa: BLE001 — 无编辑器/无面板环境跳过
                traceback.print_exc()
        return info.to_dict()

    @classmethod
    def _rehydrate_canvas(cls) -> list:
        """让当前画布重新解析此前未注册的节点类型（返回恢复的节点 id）。"""
        from Application.Editor.UI.UIManager import UIManager
        panel = UIManager.find("Node Editor")
        canvas = getattr(panel, "_canvas", None) if panel is not None else None
        if canvas is None or not hasattr(canvas, "rehydrate_unknown"):
            return []
        recovered = canvas.rehydrate_unknown()
        if recovered:
            cls.last_rehydrated_nodes = list(recovered)
            print(f"[Extensions] rehydrated {len(recovered)} previously-unknown "
                  f"node(s): {recovered[:8]}")
        else:
            cls.last_rehydrated_nodes = []
        return recovered

    @classmethod
    def disable(cls, ext_id: str) -> dict:
        """停用扩展（on_disable → on_unload → 注销其全部 ops; 持久化）。

        **内置**扩展（allowlist 内，随引擎/安装包分发）拒绝停用 —— "取消勾选"会连带让
        示例/面板消失且下次升级又回来。要从本地移除请把它移出 `Application/Functions`
        或改用 `FVE_EXTENSIONS_BUNDLED=off` 启动（安全模式）。
        `local`（Functions 下的非白名单夹具）与 `user` 扩展可以正常停用。
        """
        info = cls._require(ext_id)
        if info.always_on:
            raise ValueError(
                f"extension '{ext_id}' is built into the engine "
                f"({info.dir}) and is always enabled; remove it from Application/Functions "
                f"or start with FVE_EXTENSIONS_BUNDLED=off")
        state = cls._read_state()
        state[ext_id] = False
        cls._write_state(state)
        info.enabled = False
        if info.loaded:
            cls._unload(info)
        # ★ 边界提示（ISSUE 2026-11-03 §4.3）: 关面板→停用扩展（close_policy="disable"）
        #   或手动 disable 时，画布上该扩展的节点会变成未注册类型（PIE 会被预检拦住）。
        #   宿主不拦截这个选择，但必须说出来，而不是让人下次 Play 才发现。
        cls.last_disable_unresolved = cls._count_canvas_nodes_owned(ext_id)
        if cls.last_disable_unresolved:
            print(f"[Extensions] WARNING: disabled '{ext_id}' while "
                  f"{cls.last_disable_unresolved} node(s) in the open graph use it — "
                  f"those nodes are no longer evaluated (sim.play will refuse; "
                  f"auto_fix=true re-enables)")
        cls._sync_ops(info)
        return info.to_dict()

    @classmethod
    def _count_canvas_nodes_owned(cls, ext_id: str) -> int:
        """当前画布上引用 `ext.<id>.*` 的节点数（无画布/无面板 → 0）。"""
        try:
            from Application.Editor.UI.UIManager import UIManager
            panel = UIManager.find("Node Editor")
            canvas = getattr(panel, "_canvas", None) if panel is not None else None
            nodes = getattr(canvas, "nodes", None) or {}
            prefix = f"ext.{ext_id}."
            return sum(1 for inst in nodes.values()
                       if str(getattr(inst, "node_type", "") or "").startswith(prefix))
        except Exception:  # noqa: BLE001 — 无头环境
            return 0

    @classmethod
    def toggle(cls, ext_id: str, on: bool) -> dict:
        return cls.enable(ext_id) if on else cls.disable(ext_id)

    # ── 面板可见性（视图状态 — 与 enabled 分离，见文件头「状态分工」） ──

    @classmethod
    def show_panels(cls, ext_id: str) -> int:
        """把某扩展的主窗口置为可见；返回显示数量（无 UI/无环境 → 0）。

        这里不需要做什么持久化 —— `ExtensionPanel.visible` 的 setter 按窗口记下意图
        （唯一写入点），所以也没有 persist 开关可拨。
        """
        try:
            from Application.Editor.Extensions.ExtensionUI import ExtensionUI
            before = cls._visible_panel_count(ext_id)
            ExtensionUI.show_all(ext_id)
            return cls._visible_panel_count(ext_id) or before
        except Exception:  # noqa: BLE001 — 无 UI 环境
            return 0

    @classmethod
    def hide_panels(cls, ext_id: str) -> int:
        """隐藏某扩展的全部窗口（**不停用**）；返回隐藏的窗口数。

        对称于 `show_panels`。菜单“取消勾选”走这里 —— 面板消失但扩展仍装载、
        ops/nodes 仍然可用（要真正停用请去 设置 ▸ Extensions 或 `extension.disable`）。
        """
        try:
            from Application.Editor.Extensions.ExtensionUI import ExtensionUI
            return ExtensionUI.hide_all(ext_id)
        except Exception:  # noqa: BLE001 — 无 UI 环境
            return 0

    @classmethod
    def panel_state(cls, ext_id: str) -> dict:
        """某扩展各窗口的 `{name: {"visible": bool, "intent": bool|None}}`（诊断用）。"""
        out: dict = {}
        try:
            from Application.Editor.Extensions.ExtensionUI import ExtensionPanel
            from Application.Editor.UI.UIManager import UIManager
            panels = cls._read_state_full()["panels"]
            for p in list(UIManager._panels):
                if isinstance(p, ExtensionPanel) and p.ext_id == ext_id:
                    out[p.name] = {"visible": bool(p.visible),
                                   "intent": panels.get(p.name)}
        except Exception:  # noqa: BLE001 — 无 UI 环境
            return out
        return out

    @classmethod
    def has_visible_panel(cls, ext_id: str) -> bool:
        """当前是否至少有一个该扩展的窗口可见 —— **菜单勾选框的唯一数据源**。"""
        return cls._visible_panel_count(ext_id) > 0

    @classmethod
    def toggle_panels(cls, ext_id: str) -> bool:
        """菜单点击入口：可见 → 隐藏; 不可见 → （必要时装载）并显示。返回点击后的可见性。

        这样"勾选框 = 面板是否显示"永远成立，不会出现"勾着但没面板"：
        - 面板可见 → 取消勾选 = `hide_panels`（扩展仍启用）;
        - 面板不可见 → 勾上 = `enable`（已启用则跳过）+ `show_panels`。
        """
        if cls.has_visible_panel(ext_id):
            cls.hide_panels(ext_id)
            return False
        info = cls._infos.get(str(ext_id))
        if info is None:
            return False
        if not info.loaded:
            if not info.loadable:
                print(f"[Extensions] '{ext_id}' is not loadable ({info.status()}): "
                      f"{info.error or 'entry missing'}")
                return False
            # enable() 内部已 show_all + 持久化 intent
            cls.enable(ext_id)
            return cls.has_visible_panel(ext_id)
        cls.show_panels(ext_id)
        return cls.has_visible_panel(ext_id)

    @classmethod
    def panel_intent(cls, name: str) -> bool | None:
        """持久化的“窗口应显示”意图（**按窗口名**）; `None` = 从未显式设过（首跑→隐藏）。

        按窗口而不是按扩展记：Device Manager / Serial Monitor 这类附属窗口也要恢复。
        """
        return cls._read_state_full()["panels"].get(str(name))

    @classmethod
    def set_panel_intent(cls, name: str, visible: bool) -> None:
        """记录窗口意图（写 `extensions.json` 的 `panels` 段，不动 `enabled`）。

        写入入口只有一个: `ExtensionPanel.visible` 的 setter —— 所以菜单/View 菜单/
        `ui.panel` op/用户 X/隔离器 全部自动同步，不存在忘调用的路径。
        """
        full = cls._read_state_full()
        panels = dict(full["panels"])
        key = str(name)
        if panels.get(key) is bool(visible):
            return
        panels[key] = bool(visible)
        cls._write_state(full["enabled"], full["python"], panels)

    @staticmethod
    def _visible_panel_count(ext_id: str) -> int:
        try:
            from Application.Editor.Extensions.ExtensionUI import ExtensionPanel
            from Application.Editor.UI.UIManager import UIManager
            return sum(1 for p in list(UIManager._panels)
                       if isinstance(p, ExtensionPanel) and p.ext_id == ext_id and p.visible)
        except Exception:  # noqa: BLE001
            return 0

    # ── 挂起停用（跨线程安全入口 — 窗口 X 关闭等） ──────────────

    @classmethod
    def request_disable(cls, ext_id: str) -> None:
        """请求停用扩展（可从**渲染线程**调用 — 如 close_policy="disable" 的窗口关闭）。

        只入队；实际执行在主线程维护点（LiveCommandServer.pump 每帧 →
        `consume_pending_disables`）— 保证扩展生命周期方法始终在主线程执行。

        内置扩展直接拒绝入队（它们不可停用；窗口 X 只隐藏面板）。
        """
        info = cls._infos.get(str(ext_id))
        if info is not None and info.always_on:
            print(f"[Extensions] '{ext_id}' is bundled/always-on — "
                  f"closing its panel does not disable it")
            return
        with cls._pending_lock:
            cls._pending_disable.add(str(ext_id))
        print(f"[Extensions] disable requested: {ext_id} (applied by main-thread pump)")

    @classmethod
    def consume_pending_disables(cls) -> list[str]:
        """执行挂起的停用请求（主线程维护点 — LiveCommandServer.pump 每帧调用）。

        Returns: 实际完成停用的扩展 id 列表。
        """
        with cls._pending_lock:
            ids = sorted(cls._pending_disable)
            cls._pending_disable.clear()
        done: list[str] = []
        for ext_id in ids:
            try:
                cls.disable(ext_id)
                done.append(ext_id)
            except Exception:  # noqa: BLE001 — 单个失败不影响其余
                traceback.print_exc()
        return done

    @classmethod
    def unload_all(cls) -> None:
        """卸载全部已装载扩展（编辑器关闭时调用; 不改变持久化启用状态）。"""
        for info in list(cls._infos.values()):
            if info.loaded:
                cls._unload(info)

    # ── 装载 / 卸载内部（ctx.nodes 注入见 _load）────────────────

    @classmethod
    def _load(cls, info: ExtensionInfo) -> None:
        try:
            entry_file, _, attr = (info.entry or "extension.py:create_extension").partition(":")
            entry_path = os.path.join(info.dir, entry_file or "extension.py")
            mod_name = f"mge_ext_{info.id}"
            spec = importlib.util.spec_from_file_location(mod_name, entry_path)
            if spec is None or spec.loader is None:
                raise ImportError(f"cannot load extension entry: {entry_path}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = module
            if info.dir not in sys.path:
                sys.path.insert(0, info.dir)   # 允许扩展 import 同目录模块（M0; 打包期再收窄）
            spec.loader.exec_module(module)
            factory = getattr(module, attr or "create_extension", None)
            if factory is None:
                raise AttributeError(f"entry factory not found: {attr or 'create_extension'}")
            instance = factory()
            if not isinstance(instance, ExtensionBase):
                raise TypeError(f"entry factory must return ExtensionBase, got {type(instance).__name__}")
            if instance.id != info.id:
                print(f"[Extensions] WARNING: '{info.id}' instance.id={instance.id!r} mismatch — using manifest id")

            # capabilities ↔ 基类一致性（语言层强制的第二道闸 — dev protocol §7）
            if "ui" in (info.capabilities or []):
                from Application.Core.Extension.ExtensionBase import UIExtensionBase
                if not isinstance(instance, UIExtensionBase):
                    raise TypeError(
                        f"capabilities declares 'ui' but {type(instance).__name__} does not "
                        f"inherit UIExtensionBase (see Doc/ExtDev/extension_dev_protocol.md §7)")

            data_dir = cls._data_dir(info.id)
            os.makedirs(data_dir, exist_ok=True)
            ctx = ExtensionContext(
                extension_id=info.id, name=info.name, version=info.version,
                manifest={"id": info.id, "name": info.name, "version": info.version,
                          "maturity": info.maturity, "provider": info.provider,
                          "capabilities": list(info.capabilities)},
                extension_dir=info.dir, data_dir=data_dir, engine_root=cls._engine_root())
            ctx.ops = _ExtensionOpRegistrar(info.id)
            # ctx.python: 解释器协议（manifest `python` 声明 → 解析/自检/子进程托管）。
            # 总是注入（默认 = 引擎解释器），扩展不需要自己猜 sys.executable。
            try:
                from Application.Core.Extension.ExtensionPython import ExtensionPython
                facade = ExtensionPython(
                    info.id, extension_dir=info.dir, data_dir=data_dir,
                    engine_root=cls._engine_root(), spec=info.python,
                    override=cls.python_overrides().get(info.id, ""))
                ctx.python = facade
                cls._python_facades[info.id] = facade
            except Exception:  # noqa: BLE001 — 协议实现异常不拖垮扩展加载
                traceback.print_exc()
                ctx.python = None
            if "nodes" in [str(c) for c in (info.capabilities or [])]:
                ctx.nodes = _ExtensionNodeRegistrar(info.id, info.dir)
                cls._node_facades[info.id] = ctx.nodes
            # ctx.examples: 扩展自带 Examples/ 自动登记；显式声明 "examples"
            # 才注入 register/unregister 门面（协议 §6.2）。
            try:
                from Application.Editor.Extensions.ExtensionExamples import _ExtensionExamplesRegistrar
                caps = [str(c) for c in (info.capabilities or [])]
                if "examples" in caps or os.path.isdir(os.path.join(info.dir, "Examples")):
                    facade = _ExtensionExamplesRegistrar(info.id, info.dir, info.provider)
                    cls._example_facades[info.id] = facade
                    if "examples" in caps:
                        ctx.examples = facade
            except Exception:  # noqa: BLE001 — 示例目录异常不拖垮扩展加载
                traceback.print_exc()
            try:
                from Application.Editor.Extensions.ExtensionUI import ExtensionUI
                ctx.ui = ExtensionUI(info.id, instance)
            except Exception:  # noqa: BLE001 — 无 UI 环境允许为空
                ctx.ui = None
            # ctx.graph: 受限图访问（**需显式声明** capabilities 含 "graph" —
            # 面板 ↔ 场景节点 的官方示范通道, 见 ExtensionGraph.py）
            if "graph" in [str(c) for c in (info.capabilities or [])]:
                try:
                    from Application.Editor.Extensions.ExtensionGraph import ExtensionGraph
                    ctx.graph = ExtensionGraph(info.id)
                except Exception:  # noqa: BLE001 — 无编辑器环境允许为空
                    ctx.graph = None

            instance.on_load(ctx)
            cls._instances[info.id] = instance
            info.loaded = True
            info.error = ""
            print(f"[Extensions] loaded: {info.id} v{info.version} (maturity={info.maturity})")
        except Exception as e:  # noqa: BLE001 — 加载失败 → broken 隔离, 不拖垮编辑器
            traceback.print_exc()
            info.error = f"load: {type(e).__name__}: {e}"
            info.loaded = False
            cls._instances.pop(info.id, None)
            cls._purge_ops(info.id)
            cls._purge_nodes(info.id)
            cls._purge_examples(info.id)
            cls._purge_ui(info.id)

    @classmethod
    def _unload(cls, info: ExtensionInfo) -> None:
        inst = cls._instances.pop(info.id, None)
        if inst is not None:
            try:
                inst.on_disable()
            except Exception:  # noqa: BLE001
                traceback.print_exc()
            try:
                inst.on_unload()
            except Exception:  # noqa: BLE001
                traceback.print_exc()
        cls._purge_ops(info.id)
        cls._purge_nodes(info.id)
        cls._purge_examples(info.id)
        cls._purge_ui(info.id)
        cls._purge_python(info.id)
        info.loaded = False
        info.python_runtime = {}
        print(f"[Extensions] unloaded: {info.id}")

    @classmethod
    def _purge_python(cls, ext_id: str) -> None:
        """卸载：终止扩展通过 ctx.python.spawn 拉起的子进程（扩展自己 Popen 的不在其内）。"""
        facade = cls._python_facades.pop(ext_id, None)
        if facade is not None:
            try:
                facade.close()
            except Exception:  # noqa: BLE001 — 回收失败不拖垮其余清理
                traceback.print_exc()

    @classmethod
    def _purge_ops(cls, ext_id: str) -> None:
        try:
            from Application.Editor.Services.LiveCommandServer import LiveCommandServer
            LiveCommandServer.unregister_extension_ops(ext_id)
        except Exception:  # noqa: BLE001 — 无头环境允许跳过
            pass

    @classmethod
    def _purge_nodes(cls, ext_id: str) -> None:
        """移除扩展通过 ctx.nodes 显式注册的 pack（内置自动发现 pack 保留）。"""
        facade = cls._node_facades.pop(ext_id, None)
        if facade is not None:
            try:
                facade.unregister_all()
            except Exception:  # noqa: BLE001 — 卸载失败不拖垮其余清理
                traceback.print_exc()

    @classmethod
    def _purge_examples(cls, ext_id: str) -> None:
        """移除扩展示例根目录 — 与 ctx.nodes / ctx.ui 同一套卸载生命周期。"""
        facade = cls._example_facades.pop(ext_id, None)
        try:
            if facade is not None:
                facade.unregister_all()
            else:
                from Application.Editor.Extensions.ExtensionExamples import ExtensionExamplesRegistry
                ExtensionExamplesRegistry.unregister_owner(ext_id)
        except Exception:  # noqa: BLE001 — 卸载失败不拖垮其余清理
            traceback.print_exc()

    @classmethod
    def _purge_ui(cls, ext_id: str) -> None:
        """移除扩展注册的全部 UI 窗口（保险丝 — 与 _purge_ops 对称）。"""
        try:
            from Application.Editor.Extensions.ExtensionUI import ExtensionUI
            ExtensionUI.purge(ext_id)
        except Exception:  # noqa: BLE001 — 无头环境允许跳过
            pass

    # ── 查询 ─────────────────────────────────────────────────────

    @classmethod
    def _require(cls, ext_id: str) -> ExtensionInfo:
        cls.ensure_init()
        info = cls._infos.get(ext_id)
        if info is None:
            raise ValueError(f"unknown extension: {ext_id!r} (known: {', '.join(sorted(cls._infos))})")
        return info

    @classmethod
    def get(cls, ext_id: str) -> ExtensionInfo | None:
        cls.ensure_init()
        return cls._infos.get(ext_id)

    @classmethod
    def list_infos(cls) -> list[dict]:
        """全部扩展信息（含增量扫描到的 op 名; 供 Extensions 菜单 / extension.list op）。"""
        cls.ensure_init()
        out = []
        for info in sorted(cls._infos.values(), key=lambda i: i.id):
            cls._sync_ops(info)
            facade = cls._python_facades.get(info.id)
            info.python_runtime = facade.explain() if facade is not None else {}
            out.append(info.to_dict())
        return out

    @classmethod
    def _sync_ops(cls, info: ExtensionInfo) -> None:
        """回填单个扩展当前挂载的 op 名（来源 = LiveCommandServer 增量注册表）。"""
        ops: list = []
        try:
            from Application.Editor.Services.LiveCommandServer import LiveCommandServer
            ops = sorted(op for op, meta in LiveCommandServer.extension_ops_snapshot().items()
                         if meta.get("owner") == info.id)
        except Exception:  # noqa: BLE001
            pass
        info.ops = ops
