"""Serial device fingerprinting — USB 描述符采集 + 唯一候选匹配。

设计边界（2026-10-20）:
  - `usb_serial` 唯一且稳定 -> 首选（跨口/跨机）。
  - 无序列号时退回 `vid_pid`，但**只有当前恰好一个候选**才允许自动改绑；
    多候选 -> `ambiguous`，调用方必须显式报错/让人工选择。
  - `location` 只是本机 USB 口位置，只用于诊断，**绝不参与匹配**
    （否则就变成“绑口”而不是“绑设备”）。
  - 没有任何指纹 -> `unmatched`，不猜。
"""

from __future__ import annotations

from typing import Any


def normalize_vid_pid(vid: Any, pid: Any) -> str:
    """`(0x1A86, 0x7523)` -> `"1A86:7523"`; 缺值 -> `""`。"""
    if vid is None or pid is None:
        return ""
    try:
        return f"{int(vid):04X}:{int(pid):04X}"
    except (TypeError, ValueError):
        return ""


def fingerprint(port: dict) -> dict:
    """从 `list_serial_ports()` 的端口条目提取可持久化 hint。"""
    port = port or {}
    hint: dict = {}
    vid_pid = normalize_vid_pid(port.get("vid"), port.get("pid"))
    if vid_pid:
        hint["vid_pid"] = vid_pid
    sn = str(port.get("serial_number") or "").strip()
    if sn:
        hint["usb_serial"] = sn
    for key in ("manufacturer", "product", "interface"):
        val = str(port.get(key) or "").strip()
        if val:
            hint[key] = val
    loc = str(port.get("location") or "").strip()
    if loc:
        hint["location"] = loc          # 仅诊断，不参与 match
    return hint


def _summary(port: dict) -> dict:
    return {
        "device": str(port.get("device") or ""),
        "description": str(port.get("description") or ""),
        "serial_number": str(port.get("serial_number") or ""),
        "vid_pid": normalize_vid_pid(port.get("vid"), port.get("pid")),
        "location": str(port.get("location") or ""),
    }


def _result(candidates: list[dict], reason: str) -> dict:
    if len(candidates) == 1:
        return {"status": "matched", "port": candidates[0],
                "candidates": [_summary(candidates[0])], "reason": reason}
    if len(candidates) > 1:
        return {"status": "ambiguous", "port": None,
                "candidates": [_summary(p) for p in candidates], "reason": reason}
    return {"status": "unmatched", "port": None, "candidates": [],
            "reason": f"no port matches {reason}"}


def match(hint: dict, ports: list[dict]) -> dict:
    """按 hint 在当前端口列表中找唯一设备。

    Returns:
        {status: matched|ambiguous|unmatched, port, candidates, reason}
    """
    hint = hint or {}
    ports = list(ports or [])

    serial = str(hint.get("usb_serial") or "").strip()
    if serial:
        cands = [p for p in ports
                 if str(p.get("serial_number") or "").strip() == serial]
        return _result(cands, "usb_serial")

    vid_pid = str(hint.get("vid_pid") or "").strip().upper()
    if vid_pid:
        cands = [p for p in ports
                 if normalize_vid_pid(p.get("vid"), p.get("pid")) == vid_pid]
        # product 只作为多候选时的收窄条件；Windows 上常为空，不能反过来排除。
        product = str(hint.get("product") or "").strip()
        if len(cands) > 1 and product:
            narrowed = [p for p in cands
                        if str(p.get("product") or "").strip() == product]
            if narrowed:
                cands = narrowed
        return _result(cands, "vid_pid")

    return {"status": "unmatched", "port": None, "candidates": [],
            "reason": "no usb_serial / vid_pid fingerprint in hint"}
