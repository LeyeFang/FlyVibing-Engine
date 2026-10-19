"""ExtensionManager — 扩展发现 / 装载 / 启停 / 隔离（L1, M0 骨架）。

架构: Doc/Dev/extension_protocol.md §1-§4
开发规范: Doc/ExtDev/extension_dev_protocol.md

M0 实装范围:
  - 发现: 内置 `Application/Functions/**/extension.json` + 用户目录（env `MGE_EXTENSIONS_DIR` 或
    %APPDATA%/MyGameEngine/extensions）
  - manifest 校验（id / api_version / entry; 非法 → broken 隔离展示）
  - 启停: 持久化到 `Application/Editor/Config/extensions.json`（env `MGE_EXTENSIONS_STATE` 可覆盖;
    测试沙箱用）
  - ops 贡献: ctx.ops.register → LiveCommandServer 扩展注册表（ext.<id>.* 强制前缀）
  - 异常遏制: 加载失败 → broken（菜单/op 可见错误原因, 不拖垮编辑器）

设计未实装（见 dev protocol §13）: ui.window / threads / jobs / nodes / settings /
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
    export: bool = True               # 是否随 Project Export 游戏层分发（manifest export:false 可关）
    dir: str = ""
    manifest_path: str = ""
    loadable: bool = False             # entry 存在且 manifest 合法
    enabled: bool = False              # 用户启用状态（持久化）
    loaded: bool = False               # 当前已装载
    error: str = ""                    # broken 原因（空 = 健康）
    ops: list = field(default_factory=list)   # 已注册的 op 名（查询时动态填充）

    def status(self) -> str:
        if self.error:
            return "broken"
        if not self.loadable:
            return "planned"
        return "enabled" if self.loaded else "disabled"

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "version": self.version,
            "api_version": self.api_version, "maturity": self.maturity,
            "description": self.description, "status": self.status(),
            "enabled": self.enabled, "loaded": self.loaded, "loadable": self.loadable,
            "error": self.error, "dir": self.dir, "ops": list(self.ops),
            "capabilities": list(self.capabilities), "requires": list(self.requires),
            "export": bool(self.export),
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


# ════════════════════════════════════════════════════════════════
# 管理器
# ════════════════════════════════════════════════════════════════

class ExtensionManager:
    """扩展管理器（类级单例; 编辑器应用层）。"""

    _infos: dict[str, ExtensionInfo] = {}
    _instances: dict[str, ExtensionBase] = {}
    _scanned: bool = False

    # 挂起停用请求（窗口 X 关闭等可从渲染线程发起 — 实际执行在主线程 pump）
    _pending_disable: set = set()
    _pending_lock = threading.Lock()

    # ── 路径解析（env 可覆盖 → 测试沙箱/自定义部署） ────────────

    @classmethod
    def _engine_root(cls) -> str:
        return str(Path(__file__).resolve().parents[3])   # .../Application/Editor/Extensions → repo root

    @classmethod
    def _user_dir(cls) -> str:
        return AppIdentity.env_get("EXTENSIONS_DIR") or os.path.join(
            os.environ.get("APPDATA", os.path.expanduser("~")), AppIdentity.APP_NAME, "extensions")

    @classmethod
    def _state_path(cls) -> str:
        return AppIdentity.env_get("EXTENSIONS_STATE") or os.path.join(
            cls._engine_root(), "Application", "Editor", "Config", "extensions.json")

    @classmethod
    def _data_dir(cls, ext_id: str) -> str:
        base = AppIdentity.env_get("EXTENSIONS_DATA") or os.path.join(
            cls._engine_root(), "Application", "Editor", "Config", "extensions_data")
        return os.path.join(base, ext_id)

    # ── 状态持久化 ───────────────────────────────────────────────

    @classmethod
    def _read_state(cls) -> dict:
        try:
            with open(cls._state_path(), "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return dict(data.get("enabled", {})) if isinstance(data, dict) else {}
        except FileNotFoundError:
            return {}
        except Exception as e:  # noqa: BLE001 — 损坏状态文件按默认处理
            print(f"[Extensions] state read failed (using defaults): {e!r}")
            return {}

    @classmethod
    def _write_state(cls, enabled: dict) -> None:
        path = cls._state_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"version": 1, "enabled": enabled}, fh, indent=2, ensure_ascii=False)

    # ── 扫描 / 发现 ──────────────────────────────────────────────

    @classmethod
    def ensure_init(cls, force: bool = False) -> None:
        """首次访问自动扫描（幂等; force=True 等价 rescan）。"""
        if force or not cls._scanned:
            cls.scan()

    @classmethod
    def scan(cls) -> None:
        """发现并解析全部扩展; 自动装载已启用者。"""
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

        state = cls._read_state()
        for info in infos.values():
            if info.loadable and state.get(info.id, False):
                info.enabled = True
                cls._load(info)
        print(f"[Extensions] scan: {len(infos)} found"
              f" ({sum(1 for i in infos.values() if i.loadable)} loadable,"
              f" {sum(1 for i in infos.values() if i.error)} broken)")

    @classmethod
    def rescan(cls) -> None:
        """卸载全部已装载扩展并重新扫描（Extensions 菜单 ▸ Rescan）。"""
        for info in cls._infos.values():
            if info.loaded:
                cls._unload(info)
        cls.scan()

    @classmethod
    def _parse_manifest(cls, path: Path) -> ExtensionInfo:
        folder_id = path.parent.name.lower()
        info = ExtensionInfo(id=folder_id, dir=str(path.parent), manifest_path=str(path))
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                raise ValueError("manifest must be a JSON object")
            info.id = str(data.get("id") or folder_id)
            info.name = str(data.get("name") or info.id)
            info.version = str(data.get("version") or "0.0.0")
            info.api_version = str(data.get("api_version") or "")
            info.maturity = str(data.get("maturity") or "planned")
            info.description = str(data.get("description") or "")
            info.entry = str(data.get("entry") or "")
            info.capabilities = list(data.get("capabilities") or [])
            info.requires = list(data.get("requires") or [])
            info.export = bool(data.get("export", True))
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
        """启用扩展（加载 + on_enable; 持久化）。等同 Extensions 菜单勾选。"""
        info = cls._require(ext_id)
        if not info.loadable:
            raise ValueError(
                f"extension '{ext_id}' is not loadable "
                f"(maturity={info.maturity}; see its TODO.md / dev protocol)")
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
        # 启用 = “想看面板” — 重置窗口可见性（X 隐藏后再次勾选即重新打开; dev protocol §7）
        try:
            from Application.Editor.Extensions.ExtensionUI import ExtensionUI
            ExtensionUI.show_all(ext_id)
        except Exception:  # noqa: BLE001 — 无 UI 环境跳过
            pass
        cls._sync_ops(info)
        return info.to_dict()

    @classmethod
    def disable(cls, ext_id: str) -> dict:
        """停用扩展（on_disable → on_unload → 注销其全部 ops; 持久化）。"""
        info = cls._require(ext_id)
        state = cls._read_state()
        state[ext_id] = False
        cls._write_state(state)
        info.enabled = False
        if info.loaded:
            cls._unload(info)
        cls._sync_ops(info)
        return info.to_dict()

    @classmethod
    def toggle(cls, ext_id: str, on: bool) -> dict:
        return cls.enable(ext_id) if on else cls.disable(ext_id)

    # ── 挂起停用（跨线程安全入口 — 窗口 X 关闭等） ──────────────

    @classmethod
    def request_disable(cls, ext_id: str) -> None:
        """请求停用扩展（可从**渲染线程**调用 — 如 close_policy="disable" 的窗口关闭）。

        只入队；实际执行在主线程维护点（LiveCommandServer.pump 每帧 →
        `consume_pending_disables`）— 保证扩展生命周期方法始终在主线程执行。
        """
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

    # ── 装载 / 卸载内部 ──────────────────────────────────────────

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
                          "maturity": info.maturity, "capabilities": list(info.capabilities)},
                extension_dir=info.dir, data_dir=data_dir, engine_root=cls._engine_root())
            ctx.ops = _ExtensionOpRegistrar(info.id)
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
                    ctx.graph = ExtensionGraph
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
        cls._purge_ui(info.id)
        info.loaded = False
        print(f"[Extensions] unloaded: {info.id}")

    @classmethod
    def _purge_ops(cls, ext_id: str) -> None:
        try:
            from Application.Editor.Services.LiveCommandServer import LiveCommandServer
            LiveCommandServer.unregister_extension_ops(ext_id)
        except Exception:  # noqa: BLE001 — 无头环境允许跳过
            pass

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
