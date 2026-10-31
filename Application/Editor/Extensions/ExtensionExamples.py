"""ExtensionExamples — 扩展贡献的 Example 根目录（`ctx.examples`）。

为什么需要它: `File ▸ Open Example` 以前只扫描官方 `Examples/`、测试夹具和用户
示例目录。扩展自带的示例放在 `Application/Functions/<Ext>/Examples/` 或用户扩展
目录时不可见，作者只能把示例复制到 `%APPDATA%/FlyVibingEngine/examples`，并自己
实现判重/清理/冲突保护。本模块把这件事收敛到宿主：

  - **自动发现**: 扩展加载（enable）时，若 `<extension_dir>/Examples` 存在，宿主
    自动登记该根目录；无需修改 manifest、无需复制文件。
  - **显式扩展**: manifest `capabilities` 含 `"examples"` 时注入 `ctx.examples`，
    可 `register(root)` / `unregister(root)` 追加/移除额外只读根目录。
  - **生命周期**: 扩展 unload/disable 时移除本扩展登记的全部根目录，菜单条目随
    即消失；引擎从不向用户目录复制，因此没有残留和覆盖风险。
  - **签名**: 根目录的默认提供者来自 manifest `provider`（缺省 `@<id>`）；
    `.myproj.provider` / `signature` / `author` 仍优先。重复示例用灰色签名区分。

只读约束: 宿主只把扩展目录当作 Example 源，不写回扩展目录。`ctx.examples` 不是
文件安装器；需要“复制到用户目录”的旧式扩展应改用本能力并删除自己的注入逻辑。
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass

from Application.Core.Signature import COMMUNITY_PROVIDER, normalize_provider


@dataclass(frozen=True)
class ExampleRoot:
    """一个已登记的 Example 根目录。"""

    root: str
    owner: str
    provider: str
    auto: bool = False

    def to_dict(self) -> dict:
        return {
            "root": self.root,
            "owner": self.owner,
            "provider": self.provider,
            "auto": bool(self.auto),
        }


class ExtensionExamplesRegistry:
    """宿主级 Example 根目录注册表（进程内，随扩展生命周期增删）。"""

    _lock = threading.RLock()
    _roots: dict[str, ExampleRoot] = {}

    # ── 内部工具 ────────────────────────────────────────────────

    @staticmethod
    def _abs(path: str) -> str:
        return os.path.abspath(os.path.expanduser(str(path or "").strip()))

    @classmethod
    def _key(cls, root: str) -> str:
        return os.path.normcase(cls._abs(root))

    @classmethod
    def _entry_for_path(cls, path: str) -> ExampleRoot | None:
        """返回包含 `path` 的最长根目录条目（用于签名/归属查询）。"""
        target = cls._abs(path)
        best: ExampleRoot | None = None
        for entry in cls._roots.values():
            root = cls._abs(entry.root)
            try:
                if os.path.commonpath([target, root]) != root:
                    continue
            except ValueError:  # Windows 跨盘符
                continue
            if best is None or len(root) > len(best.root):
                best = entry
        return best

    # ── 注册 / 注销 ─────────────────────────────────────────────

    @classmethod
    def register(cls, root: str, owner: str, provider: str = "",
                 *, auto: bool = False) -> ExampleRoot:
        """登记一个只读 Example 根目录；返回条目。目录必须已存在。"""
        abs_root = cls._abs(root)
        if not abs_root or not os.path.isdir(abs_root):
            raise ValueError(f"example root is not a directory: {root!r}")
        owner = str(owner or "").strip()
        if not owner:
            raise ValueError("example root requires an owner extension id")
        provider = normalize_provider(provider, default=f"@{owner}")
        entry = ExampleRoot(root=abs_root, owner=owner,
                            provider=provider, auto=bool(auto))
        with cls._lock:
            cls._roots[cls._key(abs_root)] = entry
        return entry

    @classmethod
    def unregister(cls, root: str) -> bool:
        """注销任意根目录；返回是否确实移除。"""
        with cls._lock:
            return cls._roots.pop(cls._key(root), None) is not None

    @classmethod
    def unregister_owner(cls, owner: str) -> int:
        """移除某扩展登记的全部根目录；返回移除数量。"""
        owner = str(owner or "").strip()
        if not owner:
            return 0
        with cls._lock:
            keys = [key for key, entry in cls._roots.items() if entry.owner == owner]
            for key in keys:
                cls._roots.pop(key, None)
        return len(keys)

    @classmethod
    def clear(cls) -> None:
        """测试/编辑器关闭时清空注册表。"""
        with cls._lock:
            cls._roots.clear()

    # ── 查询 ────────────────────────────────────────────────────

    @classmethod
    def roots(cls) -> list[dict]:
        """当前全部根目录快照（按登记顺序）。"""
        with cls._lock:
            return [entry.to_dict() for entry in cls._roots.values()]

    @classmethod
    def owner_of_root(cls, root: str) -> str:
        """精确查询某个根目录的登记 owner；未登记返回空串。"""
        with cls._lock:
            entry = cls._roots.get(cls._key(root))
            return entry.owner if entry is not None else ""

    @classmethod
    def provider_for_path(cls, path: str) -> str:
        """路径所属扩展根目录的签名；不属于任何扩展根目录时返回空串。"""
        with cls._lock:
            entry = cls._entry_for_path(path)
            return entry.provider if entry is not None else ""

    @classmethod
    def owner_for_path(cls, path: str) -> str:
        """路径所属扩展 id；不属于任何扩展根目录时返回空串。"""
        with cls._lock:
            entry = cls._entry_for_path(path)
            return entry.owner if entry is not None else ""

    @classmethod
    def contains_path(cls, path: str) -> bool:
        """`path` 是否位于任一已登记的扩展 Example 根目录内。"""
        with cls._lock:
            return cls._entry_for_path(path) is not None


class _ExtensionExamplesRegistrar:
    """`ctx.examples` 门面 — 每个扩展一个实例，绑定 owner 与默认签名。

    - 构造时自动登记 `<extension_dir>/Examples`（若存在）；
    - `register(root, provider=None)` 追加额外只读根目录；
    - `unregister(root)` 只允许撤销本扩展登记的根目录；
    - `unregister_all()` 由 ExtensionManager 在 unload/disable 时调用。
    """

    def __init__(self, owner_id: str, extension_dir: str = "",
                 provider: str = "") -> None:
        self._owner = str(owner_id or "").strip()
        self._extension_dir = str(extension_dir or "")
        self._provider = normalize_provider(
            provider,
            default=f"@{self._owner}" if self._owner else COMMUNITY_PROVIDER)
        self._registered: set[str] = set()
        default_root = self.default_root
        if default_root and os.path.isdir(default_root):
            try:
                self.register(default_root, auto=True)
            except (OSError, ValueError):
                pass

    @property
    def owner(self) -> str:
        return self._owner

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def default_root(self) -> str:
        """扩展自带的 `Examples/` 目录（可能不存在）。"""
        if not self._extension_dir:
            return ""
        return os.path.join(self._extension_dir, "Examples")

    def _resolve(self, root: str) -> str:
        raw = str(root or "").strip()
        if raw and not os.path.isabs(raw) and self._extension_dir:
            raw = os.path.join(self._extension_dir, raw)
        return raw

    def register(self, root: str, provider: str | None = None,
                 *, auto: bool = False) -> dict:
        """登记一个只读 Example 根目录，返回条目快照。"""
        entry = ExtensionExamplesRegistry.register(
            self._resolve(root), self._owner, provider or self._provider, auto=auto)
        self._registered.add(entry.root)
        return entry.to_dict()

    def unregister(self, root: str) -> bool:
        """撤销本扩展的某个根目录；不是本扩展登记的 → False。"""
        abs_root = ExtensionExamplesRegistry._abs(self._resolve(root))
        if abs_root not in self._registered:
            return False
        self._registered.discard(abs_root)
        if ExtensionExamplesRegistry.owner_of_root(abs_root) != self._owner:
            return False
        return ExtensionExamplesRegistry.unregister(abs_root)

    def roots(self) -> list[dict]:
        """本扩展当前登记的根目录。"""
        owned = {ExtensionExamplesRegistry._key(root) for root in self._registered}
        return [entry for entry in ExtensionExamplesRegistry.roots()
                if ExtensionExamplesRegistry._key(entry["root"]) in owned]

    def unregister_all(self) -> int:
        """撤销本扩展登记的全部根目录；返回移除数量。"""
        removed = 0
        for root in list(self._registered):
            if (ExtensionExamplesRegistry.owner_of_root(root) == self._owner
                    and ExtensionExamplesRegistry.unregister(root)):
                removed += 1
        self._registered.clear()
        # 防御: 注册表里可能还有本 owner 的孤儿条目
        removed += ExtensionExamplesRegistry.unregister_owner(self._owner)
        return removed
