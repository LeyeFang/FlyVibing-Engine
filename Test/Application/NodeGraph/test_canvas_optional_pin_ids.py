"""Regression: optional-pin healing must not reuse a pin id already in the scene."""
# TIER: core

from __future__ import annotations

import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Application.Core.NodeGraph import NodeCanvas  # noqa: E402

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


def main() -> int:
    # Compare has an optional C pin added after older scenes were saved.
    graph = {
        "version": "0.1.0",
        "next_id": 100,
        "nodes": {
            "1": {
                "id": 1, "node_type": "Compare", "props": {"operation": "gt"},
                "pin_ids": {"A": 2001, "B": 2002, "Result": 2003},
            },
            "2": {
                "id": 2, "node_type": "Constant", "props": {"value": 1},
                "pin_ids": {"Result": 2004},
            },
        },
        "links": {
            "1": {"id": 1, "from_pin": 2004, "to_pin": 2001},
        },
    }
    canvas = NodeCanvas.from_dict(graph)
    ids = [int(pid) for nd in canvas.nodes.values() for pid in nd.pin_ids.values()]
    check("all pin ids unique", len(ids) == len(set(ids)), str(ids))
    check("optional C pin added", "C" in canvas.nodes[1].pin_ids)
    check("optional C id above scene max", canvas.nodes[1].pin_ids["C"] > 2004,
          str(canvas.nodes[1].pin_ids))
    check("link preserved", any(lk.from_pin == 2004 and lk.to_pin == 2001
                                for lk in canvas.links.values()))
    print(f"RESULT: {_RESULTS['pass']}/{_RESULTS['pass'] + _RESULTS['fail']} passed, "
          f"{_RESULTS['fail']} failed")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
