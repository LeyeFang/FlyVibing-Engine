"""NodePackRegistry — 扩展节点包（节点类型 + 求值器 + 控件字段）的单一注册入口。

职责:
  - 把扩展提供的节点声明注册到 `node_types._TYPES` / `evaluator_engine._EVALUATORS`；
  - 保存声明式控件字段（供 Node Editor 通用控件渲染，不需要扩展 import Editor）；
  - 维护 Add 菜单的扩展分区；
  - 发现并加载内置扩展的 `node_pack.py`（`Application/Functions/**/node_pack.py`）。

边界:
  - 本模块位于 Core/NodeGraph，禁止 import Editor / imgui（边界测试守卫）；
  - 扩展 `node_pack.py` 必须是纯声明 + 可选 evaluator，不得 import Editor；
  - 内置 pack 自动发现不依赖扩展 enable 状态（节点类型是项目可加载性的一部分）。
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import Any

from Application.Core import AppIdentity

from .data_model import NodeTypeDef, PinDef, _gen_id
from .evaluator_engine import register_evaluator, unregister_evaluator
from .node_types import register_node_type, unregister_node_type


class NodePackError(ValueError):
    """节点包声明非法或与现有类型冲突。"""


def _pin_from_spec(spec: dict) -> PinDef:
    name = str(spec.get("name", "")).strip()
    if not name:
        raise NodePackError("pin requires a name")
    kind = str(spec.get("kind", "data"))
    direction = str(spec.get("direction", "input"))
    if kind not in ("exec", "data"):
        raise NodePackError(f"pin {name!r}: kind must be exec/data, got {kind!r}")
    if direction not in ("input", "output"):
        raise NodePackError(f"pin {name!r}: direction must be input/output, got {direction!r}")
    return PinDef(
        _gen_id(), name, kind, direction,
        str(spec.get("data_type", "exec" if kind == "exec" else "variant")),
        bool(spec.get("optional", False)),
    )


class NodePackRegistry:
    """类级注册表（编辑器与运行时共用）。"""

    _packs: dict[str, dict] = {}
    _type_owner: dict[str, str] = {}
    _fields: dict[str, list[dict]] = {}
    _auto_discovered: bool = False

    # ── 注册 ────────────────────────────────────────────────────

    @classmethod
    def register(cls, pack: dict) -> dict:
        """注册一个节点包。重复注册同 owner + 同类型为幂等。

        pack 结构:
          {
            "id": "device", "name": "Device (Serial/Parallel)", "owner": "device",
            "nodes": [{
              "type": "SerialSend", "label": "Serial Send", "category": "IO",
              "color": (0.878, 0.620, 0.314), "props_text": "...",
              "pins": [{"name":"exec_in","kind":"exec","direction":"input"}],
              "fields": [{"key":"port","label":"Port","kind":"serial_port"}],
              "evaluator": callable | None
            }],
            "menu": [("Device", [("Serial", [("Serial Send","SerialSend")])])]
          }
        """
        if not isinstance(pack, dict):
            raise NodePackError("pack must be a dict")
        pack_id = str(pack.get("id", "")).strip()
        owner = str(pack.get("owner") or pack_id).strip()
        if not pack_id or not owner:
            raise NodePackError("pack requires non-empty 'id'/'owner'")
        nodes = pack.get("nodes") or []
        if not isinstance(nodes, list):
            raise NodePackError(f"pack {pack_id!r}: nodes must be a list")

        existing_types = set(cls._packs.get(pack_id, {}).get("types") or ())
        prepared = []
        for node in nodes:
            if not isinstance(node, dict):
                raise NodePackError(f"pack {pack_id!r}: node must be a dict")
            type_name = str(node.get("type") or node.get("type_name") or "").strip()
            if not type_name:
                raise NodePackError(f"pack {pack_id!r}: node requires 'type'")
            # 同一 pack 重复注册：保留原类型，不重复登记/覆盖求值器。
            if type_name in existing_types:
                continue
            current = cls._type_owner.get(type_name)
            if current is not None:
                if current != owner:
                    raise NodePackError(
                        f"node type {type_name!r} already owned by {current!r}; "
                        f"pack {pack_id!r} cannot override it"
                    )
                # 同 owner 的另一个 pack 已登记：按幂等处理，不重复注册。
                continue
            label = str(node.get("label") or type_name)
            category = str(node.get("category") or "Extension")
            color = node.get("color") or (0.55, 0.55, 0.55)
            pins = [_pin_from_spec(p) for p in (node.get("pins") or [])]
            if not pins:
                raise NodePackError(f"node type {type_name!r} requires at least one pin")
            fields_spec = node.get("fields")
            if fields_spec is not None and not isinstance(fields_spec, list):
                raise NodePackError(f"node type {type_name!r}: fields must be a list")
            fields = []
            for spec in fields_spec or []:
                if not isinstance(spec, dict):
                    raise NodePackError(f"node type {type_name!r}: each field must be a dict")
                if not str(spec.get("key") or "").strip():
                    raise NodePackError(f"node type {type_name!r}: field requires 'key'")
                fields.append(dict(spec))
            prepared.append((type_name, NodeTypeDef(
                type_name, label, category, tuple(color), pins,
                str(node.get("props_text") or ""),
            ), node, fields))

        # 校验全部通过后再落地，避免半注册。
        registered_types = set(existing_types)
        for type_name, type_def, node, fields in prepared:
            register_node_type(type_def)
            cls._type_owner[type_name] = owner
            registered_types.add(type_name)
            evaluator = node.get("evaluator")
            if evaluator is not None:
                register_evaluator(type_name, evaluator)
            if fields:
                cls._fields[type_name] = fields

        cls._packs[pack_id] = {
            "id": pack_id,
            "name": str(pack.get("name") or pack_id),
            "owner": owner,
            "menu": list(pack.get("menu") or []),
            "types": registered_types,
        }
        return {"pack": pack_id, "owner": owner, "types": sorted(registered_types)}

    @classmethod
    def unregister_owner(cls, owner: str) -> list[str]:
        """移除某 owner 的全部节点包（扩展 disable/unload 保险丝）。"""
        removed: list[str] = []
        for pack_id, pack in list(cls._packs.items()):
            if pack.get("owner") != owner:
                continue
            for type_name in sorted(pack.get("types") or ()):
                unregister_node_type(type_name)
                unregister_evaluator(type_name)
                cls._fields.pop(type_name, None)
                cls._type_owner.pop(type_name, None)
                removed.append(type_name)
            cls._packs.pop(pack_id, None)
        return removed

    # ── 查询（agent / UI 共用）──────────────────────────────────

    @classmethod
    def is_registered(cls, type_name: str) -> bool:
        return type_name in cls._type_owner

    @classmethod
    def owner_of(cls, type_name: str) -> str:
        if type_name in cls._type_owner:
            return cls._type_owner[type_name]
        from .node_types import _TYPES
        return "core" if type_name in _TYPES else ""

    @classmethod
    def fields_for(cls, type_name: str) -> list[dict]:
        """声明式控件字段（扩展节点在 Node Editor 卡片内自动渲染）。"""
        return list(cls._fields.get(type_name) or [])

    @classmethod
    def packs(cls) -> list[dict]:
        """已注册 pack 的摘要（owner/name/types；agent 发现与诊断用）。"""
        return [
            {"id": p["id"], "name": p["name"], "owner": p["owner"],
             "types": sorted(p.get("types") or ())}
            for p in cls._packs.values()
        ]

    @classmethod
    def catalog(cls, owner: str | None = None) -> list[dict]:
        """全部/指定 owner 的节点类型描述（含引脚，agent 发现入口）。"""
        from .node_types import _TYPES

        out: list[dict] = []
        for type_name, nd in sorted(_TYPES.items()):
            type_owner = cls._type_owner.get(type_name, "core")
            if owner is not None and type_owner != owner:
                continue
            out.append({
                "type": type_name,
                "label": nd.label,
                "category": nd.category,
                "owner": type_owner,
                "props_text": nd.props_text,
                "fields": cls.fields_for(type_name),
                "pins": [
                    {"name": p.name, "kind": p.kind, "direction": p.direction,
                     "data_type": p.data_type, "optional": bool(p.optional)}
                    for p in nd.pins
                ],
            })
        return out

    @classmethod
    def menu_sections(cls) -> list[tuple[str, list]]:
        """扩展 Add 菜单分区（按标题合并，避免两个扩展各建一个同名顶级页）。"""
        merged: dict[str, list] = {}
        order: list[str] = []
        for pack in cls._packs.values():
            for title, items in (pack.get("menu") or []):
                title = str(title)
                if title not in merged:
                    merged[title] = []
                    order.append(title)
                merged[title].extend(list(items or []))
        return [(title, merged[title]) for title in order]

    # ── 内置 pack 自动发现 ──────────────────────────────────────

    @classmethod
    def discover_builtin(cls) -> list[dict]:
        """扫描 `Application/Functions/**/node_pack.py` 并注册。

        独立于扩展 enable 状态: 节点类型是图可加载性的一部分；扩展面板/ops 才受
        启用状态控制。导入失败只告警，不阻断编辑器/运行时启动。
        """
        if cls._auto_discovered:
            return []
        cls._auto_discovered = True
        app_root = Path(__file__).resolve().parents[2]         # .../Application
        roots = [app_root / "Functions"]
        user_root = AppIdentity.env_get("EXTENSIONS_DIR") or os.path.join(
            os.environ.get("APPDATA", os.path.expanduser("~")),
            AppIdentity.APP_NAME, "extensions")
        roots.append(Path(user_root))
        results: list[dict] = []
        seen: set[str] = set()
        for root in roots:
            if not root.is_dir():
                continue
            for path in sorted(root.glob("**/node_pack.py")):
                if "__pycache__" in path.parts:
                    continue
                key = str(path.resolve())
                if key in seen:
                    continue
                seen.add(key)
                try:
                    results.append(cls._load_pack_file(path))
                except Exception as e:  # noqa: BLE001 — 单扩展坏包不拖垮全图
                    print(f"[NodePacks] WARNING: {path}: {type(e).__name__}: {e}")
        return results

    @classmethod
    def _load_pack_file(cls, path: Path) -> dict:
        owner = path.parent.name.lower()
        mod_name = f"mge_nodepack_{owner}_{abs(hash(str(path.resolve()))) % 100000}"
        if mod_name in sys.modules:
            module = sys.modules[mod_name]
        else:
            spec = importlib.util.spec_from_file_location(mod_name, str(path))
            if spec is None or spec.loader is None:
                raise NodePackError(f"cannot load node pack: {path}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = module
            pack_dir = str(path.parent)
            if pack_dir not in sys.path:
                sys.path.insert(0, pack_dir)
            spec.loader.exec_module(module)
        factory = getattr(module, "register", None) or getattr(module, "get_pack", None)
        if factory is None:
            raise NodePackError("node_pack.py must define register() or get_pack()")
        pack = factory()
        if not isinstance(pack, dict):
            raise NodePackError("register()/get_pack() must return a dict")
        pack.setdefault("owner", owner)
        return cls.register(pack)

    @classmethod
    def load_all(cls) -> list[dict]:
        """公开入口（NodeGraph 包初始化时调用；幂等）。"""
        return cls.discover_builtin()


__all__ = ["NodePackError", "NodePackRegistry"]
