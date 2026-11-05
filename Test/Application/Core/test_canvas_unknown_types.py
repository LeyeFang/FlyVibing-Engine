"""画布未注册节点：重判定与就地补全（core，无头）。

背景（ISSUE 2026-11-03 §4.1）:
  扩展被停用后打开场景 → `ext.<id>.*` 节点被记为 unknown。用户按 PIE 预检提示
  `extension.enable` 之后，画布缓存的 unknown 集合并不会自动失效 ——
  实测必须重载场景才能恢复，于是"照着 hint 做还是起不来"。

本测试锁定:
  1. `from_dict` 把未注册类型记进 `unknown_node_types`
  2. 类型注册后 `refresh_unknown_types()` 立即清空（预检不再误报）
  3. `rehydrate_unknown()` 返回"从 unknown 恢复"的节点 id，并补齐缺失引脚
  4. `clear()` 一并清空 unknown 记录
"""

# TIER: core

from __future__ import annotations

import os
import sys

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

from Application.Core.NodeGraph import _TYPES  # noqa: E402
from Application.Core.NodeGraph.canvas import NodeCanvas  # noqa: E402
from Application.Core.NodeGraph.data_model import NodeTypeDef, PinDef  # noqa: E402

_RESULTS = {"pass": 0, "fail": 0}
_FAKE = "TestOnly.FakeNode"


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


def _scene_data(pins: dict) -> dict:
    return {
        "nodes": {
            "9001": {
                "id": 9001,
                "node_type": _FAKE,
                "props": {},
                "pin_ids": dict(pins),
                "pos": [10.0, 20.0],
            }
        },
        "links": {},
        "node_groups": {},
    }


def main() -> int:
    print("== canvas unknown rehydrate tests ==")
    old_def = _TYPES.pop(_FAKE, None)
    try:
        # ── 1. 未注册类型 → 记入 unknown，节点仍保留 ──
        canvas = NodeCanvas.from_dict(_scene_data({}))
        check("unknown type recorded", list(canvas.unknown_node_types) == [_FAKE],
              str(canvas.unknown_node_types))
        check("unknown node kept", 9001 in canvas.nodes)
        check("unknown node has no pins yet", canvas.nodes[9001].pin_ids == {},
              str(canvas.nodes[9001].pin_ids))

        # 第二块画布也先在“未注册”状态下建好（后面用它验证 rehydrate）
        canvas2 = NodeCanvas.from_dict(_scene_data({}))
        check("fresh canvas sees unknown too",
              list(canvas2.unknown_node_types) == [_FAKE], str(canvas2.unknown_node_types))

        # ── 2. 类型注册后重判定 → 不再是 unknown ──
        _TYPES[_FAKE] = NodeTypeDef(
            type_name=_FAKE,
            label="Fake",
            category="Test",
            accent_color=(1.0, 1.0, 1.0),
            pins=[
                PinDef(id=1, name="exec_in", kind="exec", direction="input"),
                PinDef(id=2, name="Value", kind="data", direction="output",
                       data_type="float"),
            ],
        )
        check("refresh clears unknown after registration",
              canvas.refresh_unknown_types() == {}, str(canvas.unknown_node_types))

        # ── 3. rehydrate: 已打开的画布就地恢复（无需重载场景） ──
        recovered = canvas2.rehydrate_unknown()
        check("rehydrate reports previously-unknown node", recovered == [9001], str(recovered))
        check("rehydrate fills pins",
              set(canvas2.nodes[9001].pin_ids) == {"exec_in", "Value"},
              str(canvas2.nodes[9001].pin_ids))
        check("rehydrate clears unknown set", canvas2.unknown_node_types == {},
              str(canvas2.unknown_node_types))

        # ── 4. clear 一并清空 unknown 记录 ──
        canvas3 = NodeCanvas.from_dict(_scene_data({}))
        _TYPES.pop(_FAKE, None)
        canvas3.refresh_unknown_types()
        check("unknown re-detected", bool(canvas3.unknown_node_types))
        canvas3.clear()
        check("clear resets unknown set", canvas3.unknown_node_types == {},
              str(canvas3.unknown_node_types))
    finally:
        if old_def is not None:
            _TYPES[_FAKE] = old_def
        else:
            _TYPES.pop(_FAKE, None)

    total = _RESULTS["pass"] + _RESULTS["fail"]
    print(f"RESULT: {'OK' if _RESULTS['fail'] == 0 else 'FAIL'} "
          f"({_RESULTS['pass']}/{total})")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
