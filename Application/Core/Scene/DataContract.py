"""
DataContract — 数据契约协议 & 类型注册表。

为 Scene 序列化 / NodeCanvas 同步 / Component 存储提供统一接口，
消除 hasattr / isinstance 硬编码类型分派。

设计模式:
  - DataContract (抽象基类): 定义 serialize() → dict / deserialize(cls, data) → obj 标准接口
  - DataclassContract (混入):    @dataclass 的即插即用实现 (Enum/tuple 自动转换)
  - Registry (注册表):           类型名 → 反序列化构造器, 替代 hardcode component_factories
  - format_value / parse_value:  通用工具, 对任意对象自动选择序列化路径

使用:
  class MyType(DataclassContract):
      field_a: float = 0
      field_b: str = ""

  register_contract("MyType", MyType)

  data = format_value(my_instance)
  restored = parse_value("MyType", data)
"""

from __future__ import annotations

import dataclasses
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Optional


# ═══════════════════════════════════════════════════════════════
# 协议
# ═══════════════════════════════════════════════════════════════

class DataContract(ABC):
    """可序列化对象的标准契约。

    实现此接口的类型可被 format_value / parse_value 自动处理。
    """

    @abstractmethod
    def serialize(self) -> dict:
        """转为纯 dict（可 JSON 导出）。"""
        ...

    @classmethod
    @abstractmethod
    def deserialize(cls, data: dict) -> DataContract:
        """从 dict 重建实例。"""
        ...


# ═══════════════════════════════════════════════════════════════
# @dataclass 混入
# ═══════════════════════════════════════════════════════════════

class DataclassContract(DataContract):
    """@dataclass 组件即插即用混入。

    自动通过 dataclasses.asdict / cls(**data) 实现序列化/反序列化。
    子类有 Enum 字段时自动 value↔enum 转换，tuple 字段自动 list↔tuple。
    """

    def serialize(self) -> dict:
        return _json_safe(dataclasses.asdict(self))

    @classmethod
    def deserialize(cls, data: dict) -> DataclassContract:
        from dataclasses import fields

        converted = dict(data)
        for fld in fields(cls):
            if fld.name not in converted:
                continue
            val = converted[fld.name]
            # Enum: str → enum member
            if isinstance(val, str) and isinstance(fld.type, type) and issubclass(fld.type, Enum):
                try:
                    converted[fld.name] = fld.type(val)
                except (ValueError, KeyError):
                    pass
            # tuple: list → tuple
            elif isinstance(val, list) and fld.type == tuple:
                converted[fld.name] = tuple(val)
        return cls(**converted)


# ═══════════════════════════════════════════════════════════════
# 注册表
# ═══════════════════════════════════════════════════════════════

_contracts: dict[str, type[DataContract]] = {}


def register_contract(name: str, cls: type[DataContract]) -> None:
    """注册可序列化类型 (供 parse_value 类型查找)。"""
    _contracts[name] = cls


def get_contract(name: str) -> Optional[type[DataContract]]:
    """按名称查找已注册的类型。"""
    return _contracts.get(name)


# ═══════════════════════════════════════════════════════════════
# 通用工具
# ═══════════════════════════════════════════════════════════════

def format_value(obj: Any) -> Any:
    """将任意对象转为 JSON 安全表示。

    分派顺序: DataContract → Enum → tuple → dict/list (递归) → 原值。
    """
    if isinstance(obj, DataContract):
        return obj.serialize()
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, tuple):
        return list(obj)
    if isinstance(obj, dict):
        return {k: format_value(v) for k, v in obj.items()}
    if isinstance(obj, (list, set)):
        return [format_value(v) for v in obj]
    return obj


def parse_value(type_name: str, data: dict) -> Optional[Any]:
    """按类型名从注册表查找构造器并反序列化。

    Returns:
        反序列化后的对象，或 None (未注册)。
    """
    cls = get_contract(type_name)
    if cls is None:
        return None
    return cls.deserialize(data)


def _json_safe(obj: Any) -> Any:
    """递归转换: Enum → value, tuple → list, set → list。
    与 format_value 的区別是 不处理 DataContract (由 DataclassContract.serialize 内部已递归)。
    """
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, tuple):
        return list(obj)
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, set)):
        return [_json_safe(v) for v in obj]
    return obj
