"""FrameCaptureSlot 抓帧信箱（core，无头）。

背景（2026-11-01，社区反馈 C3）:
  扩展作者报告 `probe editor` 恒返回 [0,0,0,0]（1600x900 全透明），看起来像
  "像素采样坏了"。全透明帧其实是**什么都没画上**（上下文刚建 / 窗口未呈现 /
  被遮挡），把它当成"颜色是黑的"报出去只会误导。

本测试锁定:
  1. request → take_pending → publish 的基本往返（宽度/高度/负载）
  2. publish(blank=True) 会在 fetch 里透出 `blank`
  3. 未请求就 fetch = pending；新代覆盖旧代 = superseded
  4. publish_error → state=error + 原因
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

from Application.Core.Renderer.FrameCaptureSlot import FrameCaptureSlot  # noqa: E402

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


def main() -> int:
    print("== FrameCaptureSlot tests ==")

    slot = FrameCaptureSlot()
    check("nothing requested -> pending", slot.fetch()["state"] == "pending")

    gen = slot.request()["generation"]
    check("request increments generation", gen == 1, str(gen))
    pending = slot.take_pending()
    check("take_pending returns the generation", pending == gen, str(pending))
    check("take_pending clears pending", slot.take_pending() is None)
    check("not yet published -> pending", slot.fetch(gen)["state"] == "pending")

    payload = bytes([1, 2, 3, 4]) * 4
    slot.publish(gen, 2, 2, payload)
    ready = slot.fetch(gen)
    check("publish -> ready", ready["ready"] is True, ready["state"])
    check("ready carries size", (ready["width"], ready["height"]) == (2, 2),
          f"{ready['width']}x{ready['height']}")
    check("ready carries payload", ready["payload"] == payload, str(len(ready["payload"])))
    check("normal frame is not blank", ready["blank"] is False, str(ready.get("blank")))

    # 全透明帧: 引擎判 blank → 上层可重试/告警
    gen2 = slot.request()["generation"]
    slot.take_pending()
    slot.publish(gen2, 1600, 900, bytes(1600 * 900 * 4), blank=True)
    blank = slot.fetch(gen2)
    check("blank flag round-trips", blank["blank"] is True, str(blank.get("blank")))
    check("blank frame still carries payload", len(blank["payload"]) == 1600 * 900 * 4)

    # 新代覆盖旧代（superseded 的前提是“新代已发布”）
    gen3 = slot.request()["generation"]
    stale = slot.fetch(gen2)
    check("pending new generation -> old one still readable",
          stale["state"] == "ready" and stale["generation"] == gen2, stale["state"])
    slot.take_pending()
    slot.publish(gen3, 2, 2, b"\x01\x02\x03\x04")
    stale = slot.fetch(gen2)
    check("newer published frame -> superseded", stale["state"] == "superseded", stale["state"])
    check("superseded reports latest", stale.get("latest_generation") == gen3, str(stale))
    latest = slot.fetch(gen3)
    check("latest generation readable", latest["state"] == "ready", latest["state"])

    slot.take_pending()
    slot.publish_error(gen3, "GL context lost")
    err = slot.fetch(gen3)
    check("publish_error -> state=error", err["state"] == "error", str(err))
    check("error carries reason", "GL context lost" in str(err.get("error")), str(err))

    total = _RESULTS["pass"] + _RESULTS["fail"]
    print(f"RESULT: {'OK' if _RESULTS['fail'] == 0 else 'FAIL'} "
          f"({_RESULTS['pass']}/{total})")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
