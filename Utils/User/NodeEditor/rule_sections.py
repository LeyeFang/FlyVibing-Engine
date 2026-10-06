"""rules.md 分节读取 — 渐进披露（MCP get_rules / CLI rules 共用）。

设计: 全文读入按 markdown 标题切块; outline 只列目录+规模（省 token）;
section(title) 精确取节 — 支持子标题（如 "Gtec"）; 取 h2 标题则得到整族内容。
纯标准库, 不依赖 mcp / Application。
"""

from __future__ import annotations

import os
import re

RULES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rules.md")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")


def load_rules(path: str | None = None) -> str:
    """读取 rules.md 全文。"""
    with open(path or RULES_PATH, "r", encoding="utf-8") as fh:
        return fh.read()


def _split(text: str) -> list[dict]:
    """按标题切块 — 每项: {level, title, chars, body}（body 含标题行, 至下一个同级/更高级标题）。"""
    lines = text.splitlines(keepends=True)
    headings: list[tuple[int, str, int]] = []
    for idx, line in enumerate(lines):
        m = _HEADING_RE.match(line.rstrip("\r\n"))
        if m:
            headings.append((len(m.group(1)), m.group(2), idx))
    out: list[dict] = []
    for i, (level, title, line_no) in enumerate(headings):
        end = len(lines)
        for nxt_level, _t, nxt_line in headings[i + 1:]:
            if nxt_level <= level:
                end = nxt_line
                break
        body = "".join(lines[line_no:end])
        out.append({"level": level, "title": title, "chars": len(body), "body": body})
    return out


def sections() -> list[dict]:
    return _split(load_rules())


def outline(text: str | None = None) -> str:
    """目录: 各节标题 + 字符量 + 取节用法（不含正文 — 代替整篇注入上下文）。"""
    raw = text if text is not None else load_rules()
    secs = _split(raw)
    lines = [
        f"# rules.md 目录（全文 {len(raw)} 字符 / {len(secs)} 节）"
        " — 按需取节，不要把全文塞进上下文",
        "",
    ]
    for s in secs:
        if s["level"] == 1:
            continue
        lines.append(f"{'  ' * (s['level'] - 2)}- {s['title']}（{s['chars']} 字符）")
    lines += [
        "",
        '用法: get_rules(section="<标题>") 取节（子标题可单独取, 如 "Gtec"）; section="all" 全文',
        'CLI : python -m Utils.User.NodeEditor.cli rules "<标题>"（--out 落盘只回摘要）',
    ]
    return "\n".join(lines)


def section(title: str, text: str | None = None) -> str | None:
    """按标题取节（忽略大小写; 先精确匹配后包含匹配）。找不到返回 None。"""
    raw = text if text is not None else load_rules()
    key = title.strip().casefold()
    secs = _split(raw)
    for s in secs:
        if s["title"].strip().casefold() == key:
            return s["body"]
    for s in secs:
        if key in s["title"].strip().casefold():
            return s["body"]
    return None


def section_titles(text: str | None = None) -> list[str]:
    """全部 h2+ 标题（供未知节名时给建议）。"""
    raw = text if text is not None else load_rules()
    return [s["title"] for s in _split(raw) if s["level"] >= 2]
