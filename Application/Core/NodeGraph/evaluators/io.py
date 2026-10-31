"""
Evaluators: IO 节点 (PathVar, TextFileWrite, SaveData)。

SerialSend / ParallelSend 的求值器已于 2026-10-20 迁到设备扩展 node_pack。
PathVar — 输出文件/目录路径字符串。
TextFileWrite — 将内容写入文本文件，支持 Manual / Pin 双模式，w/a 模式，分隔符。
SaveData — 通用数据落盘 (npy/npz/csv/json)，与 TextFileWrite 的文本日志职责分离。
"""

from __future__ import annotations

import csv
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from ..evaluator_engine import ExecutionContext, GraphEvaluator, register_evaluator


# ── 辅助：读取 data input pin 的值（不做类型转换）─────────────

def _read_input_raw(node_id: int, pin_name: str, ctx: ExecutionContext,
                    g: GraphEvaluator, default: Any = None) -> Any:
    """读取指定 data input pin 的值，若未连接则返回 default（不做 float 强转）。"""
    inst = g._canvas.nodes[node_id]
    nd = g._types[inst.node_type]
    for p in nd.pins:
        if p.name == pin_name and p.direction == "input":
            inst_pin_id = inst.pin_ids.get(p.name)
            if inst_pin_id is not None:
                val = g._read_input(inst_pin_id, ctx)
                if val is not None:
                    return val
    return default


# ── 辅助：写入 output pin（不做类型转换）──────────────────

def _write_output_raw(node_id: int, pin_name: str, value: Any,
                      ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """将任意值写入指定 data output pin（不做 float 强转）。"""
    inst = g._canvas.nodes[node_id]
    nd = g._types[inst.node_type]
    for p in nd.pins:
        if p.name == pin_name and p.direction == "output":
            inst_pin_id = inst.pin_ids.get(p.name)
            if inst_pin_id is not None:
                ctx.set_pin(inst_pin_id, value)


# ── PathVar ────────────────────────────────────────────────

def _eval_path_var(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """PathVar — 输出一个文件/目录路径字符串（纯数据节点，懒求值）。"""
    inst = g._canvas.nodes[node_id]
    path = str(inst.props.get("path", ""))
    _write_output_raw(node_id, "Path", path, ctx, g)

register_evaluator("PathVar", _eval_path_var)


# ── TextFileWrite ──────────────────────────────────────────

_DELIMITER_MAP = {
    "none":   "",
    "space":  " ",
    "newline": "\n",
    "tab":    "\t",
    "comma":  ",",
}


def _eval_text_file_write(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """TextFileWrite — 将内容写入文本文件。

    Manual 模式: FilePath / FileName / Value 全部从控件读取。
    Pin 模式:    FilePath / FileName / Value 全部从上游连线读取（props fallback）。

    WriteMode (w/a) 和 Delimiter 始终从 props 读取，不受 mode 影响。
    文件不存在时自动创建（无论 w 还是 a 模式）。
    FileName 自动补 .txt 后缀。
    """
    inst = g._canvas.nodes[node_id]
    mode = inst.props.get("mode", "manual")
    write_mode = inst.props.get("write_mode", "w")
    delimiter_key = inst.props.get("delimiter", "none")
    delim = _DELIMITER_MAP.get(delimiter_key, "")

    # ── FilePath ──
    file_path = _read_input_raw(node_id, "FilePath", ctx, g, None)
    if file_path is None or (isinstance(file_path, str) and not file_path.strip()):
        file_path = str(inst.props.get("file_path", ""))
    file_path = str(file_path).strip()

    # ── FileName ──
    if mode == "manual":
        file_name = str(inst.props.get("file_name", "output.txt"))
    else:
        file_name = _read_input_raw(node_id, "FileName", ctx, g, "")
        if file_name is None or (isinstance(file_name, str) and not file_name.strip()):
            file_name = str(inst.props.get("file_name", "output.txt"))
    file_name = str(file_name).strip()

    # ── 自动补 .txt 后缀 ──
    if not file_name.endswith(".txt"):
        file_name += ".txt"

    # ── Value ──
    if mode == "manual":
        value = inst.props.get("value", "")
    else:
        value = _read_input_raw(node_id, "Value", ctx, g, "")
        if value is None:
            value = ""

    # ── 写入内容: Python print() 语义 → str(value) ──
    content = str(value)

    # ── 构造完整路径 ──
    if file_path:
        os.makedirs(file_path, exist_ok=True)
        full_path = os.path.join(file_path, file_name)
    else:
        # 无目录 → 当前工作目录
        full_path = file_name

    # ── 写入 ──
    if ctx.dry_run:
        ctx.emit_log(node_id, "TextFileWrite", "write",
                     f"mode={write_mode}, path={full_path}, "
                     f"content={content[:80]}{'...' if len(content)>80 else ''}, "
                     f"delim={delimiter_key}")
        return

    try:
        with open(full_path, write_mode, encoding="utf-8") as f:
            f.write(content + delim)
        print(f"[TextFileWrite] {write_mode} {len(content)} chars → {full_path}"
              f"  delim={delimiter_key}")
    except OSError as e:
        print(f"[TextFileWrite] ERROR: {e}")

register_evaluator("TextFileWrite", _eval_text_file_write)


# ═══════════════════════════════════════════════════════════════
# SaveData — 通用数据落盘
# ═══════════════════════════════════════════════════════════════

_SAVE_EXT = {"npy": ".npy", "npz": ".npz", "csv": ".csv", "json": ".json"}
_CSV_DELIM = {
    "comma": ",", "tab": "\t", "space": " ", "semicolon": ";",
    ",": ",", "\\t": "\t", " ": " ", ";": ";",
}


@dataclass
class SaveDataResult:
    """SaveData 的返回值 — 可直接用于测试/扩展调用。"""
    ok: bool
    path: str = ""
    meta_path: str = ""
    rows: int = 0
    cols: int = 0
    samples: int = 0
    written: int = 0
    detail: str = ""


def _as_bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() not in ("", "0", "false", "no", "off")


def _jsonable(value: Any) -> Any:
    """把 numpy/元组/其他常见对象转成 JSON 可序列化结构。"""
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _decode_manual_value(raw: Any) -> Any:
    """Manual 模式下的 value：JSON 文本尽量解析，否则保留字符串。"""
    if not isinstance(raw, str):
        return raw
    text = raw.strip()
    if not text:
        return ""
    if text[0] in "[{\"0123456789-+tfn" or text in ("true", "false", "null"):
        try:
            return json.loads(text)
        except (ValueError, TypeError):
            pass
    return raw


def _safe_tag(tag: Any) -> str:
    text = str(tag or "").strip()
    if not text:
        return ""
    keep = []
    for ch in text:
        keep.append(ch if (ch.isalnum() or ch in "-_.") else "_")
    return "".join(keep).strip("._")


def _shape_info(data: Any) -> tuple[int, int, int, Any, Any]:
    """返回 (rows, cols, samples, shape, dtype)。"""
    if isinstance(data, dict):
        arrays: dict[str, np.ndarray] = {}
        for key, value in data.items():
            try:
                arrays[str(key)] = np.asarray(value)
            except Exception:
                arrays[str(key)] = np.asarray(str(value))
        if not arrays:
            return 0, 0, 0, {}, {}
        lengths = [int(a.shape[0]) if a.ndim > 0 else 1 for a in arrays.values()]
        rows = max(lengths) if lengths else 0
        return (
            rows, len(arrays), rows,
            {k: list(a.shape) for k, a in arrays.items()},
            {k: str(a.dtype) for k, a in arrays.items()},
        )
    if isinstance(data, (list, tuple)) and data and isinstance(data[0], dict):
        rows = len(data)
        cols = len(data[0]) if data[0] else 0
        return rows, cols, rows, [rows, cols], "object"
    try:
        arr = np.asarray(data)
    except Exception:
        return 1, 1, 1, [], type(data).__name__
    if arr.ndim == 0:
        return 1, 1, 1, [], str(arr.dtype)
    if arr.ndim == 1:
        return int(arr.shape[0]), 1, int(arr.shape[0]), list(arr.shape), str(arr.dtype)
    rows = int(arr.shape[0])
    cols = int(arr.shape[1])
    if arr.ndim > 2:
        cols = int(np.prod(arr.shape[1:]))
    return rows, cols, rows, list(arr.shape), str(arr.dtype)


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    n = 2
    while True:
        candidate = path.with_name(f"{path.stem}_{n}{path.suffix}")
        if not candidate.exists():
            return candidate
        n += 1


def _prepare_path(file_path: Any, file_name: Any, fmt: str, *,
                  unique: bool, tag: str) -> Path:
    base = str(file_name or "data").strip() or "data"
    name_path = Path(base)
    if name_path.suffix.lower() in _SAVE_EXT.values():
        name_path = name_path.with_suffix("")

    directory = Path(str(file_path or "").strip()) if str(file_path or "").strip() else Path(".")
    if name_path.is_absolute():
        target = name_path
    else:
        target = directory / name_path

    if unique:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        suffix = f"_{stamp}"
        safe_tag = _safe_tag(tag)
        if safe_tag:
            suffix += f"_{safe_tag}"
        target = target.with_name(f"{target.stem}{suffix}")

    target = target.with_suffix(_SAVE_EXT[fmt])
    return _unique_path(target) if unique else target


def _write_csv(path: Path, data: Any, *, delimiter: str, header: str,
               mode: str) -> None:
    """CSV: dict→列; list[dict]→表; 1D→单列; 2D+→行。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = (mode == "w") or (mode == "a" and not path.exists())
    header_cols: list[str] = []
    rows: list[list[Any]] = []

    if isinstance(data, dict):
        keys = [str(k) for k in data.keys()]
        cols = [np.asarray(v).reshape(-1) if np.asarray(v).ndim > 0
                else np.asarray([v]) for v in data.values()]
        n = max((len(c) for c in cols), default=0)
        rows = [[str(c[i]) if i < len(c) else "" for c in cols] for i in range(n)]
        header_cols = keys
    elif isinstance(data, (list, tuple)) and data and isinstance(data[0], dict):
        header_cols = [str(k) for k in data[0].keys()]
        rows = [[str(row.get(k, "")) for k in data[0].keys()] for row in data]
    else:
        arr = np.asarray(data)
        if arr.ndim == 0:
            rows = [[str(arr.item())]]
        elif arr.ndim == 1:
            rows = [[str(v)] for v in arr.tolist()]
        else:
            flat = arr.reshape(arr.shape[0], -1)
            rows = [[str(v) for v in row] for row in flat.tolist()]
            if header:
                header_cols = [h.strip() for h in header.split(delimiter)]
                if len(header_cols) != flat.shape[1]:
                    header_cols = []

    if header:
        parsed_header = [h.strip() for h in header.split(delimiter)]
        if not header_cols or len(parsed_header) == len(header_cols):
            header_cols = parsed_header

    with open(path, mode, newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, delimiter=delimiter)
        if write_header and header_cols:
            writer.writerow(header_cols)
        writer.writerows(rows)


def _write_json(path: Path, data: Any, *, indent: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(_jsonable(data), fh, ensure_ascii=False, indent=max(0, indent))


def save_data(data: Any, file_path: Any = "", file_name: Any = "data", *,
              fmt: str = "npz", key: str = "data", compress: bool = True,
              unique: bool = True, tag: str = "", save_meta: bool = True,
              csv_delimiter: str = "comma", csv_header: str = "",
              csv_mode: str = "w", json_indent: int = 2,
              elapsed_s: float = 0.0, dry_run: bool = False) -> SaveDataResult:
    """通用数据保存 — 供 SaveData 节点与扩展直接调用。

    支持 npz (多数组/单数组)、npy、csv、json。返回实际路径与行列/样本数；
    dry_run 时只计算路径，不创建目录/文件。
    """
    fmt = str(fmt or "npz").strip().lower()
    if fmt not in _SAVE_EXT:
        return SaveDataResult(False, detail=f"unsupported format: {fmt}")
    if data is None:
        return SaveDataResult(False, detail="no data")
    if fmt == "npy" and isinstance(data, dict):
        return SaveDataResult(False, detail="npy expects a single array; use npz for dict")

    try:
        path = _prepare_path(file_path, file_name, fmt, unique=unique, tag=tag)
    except Exception as e:
        return SaveDataResult(False, detail=f"path error: {e}")

    rows, cols, samples, shape, dtype = _shape_info(data)
    # 侧车带完整数据文件名，避免同 stem 不同格式互相覆盖 (foo.npz.meta.json)。
    write_meta = _as_bool(save_meta, True)
    meta_path = (path.with_name(f"{path.name}.meta.json") if write_meta else None)
    detail = f"format={fmt}, rows={rows}, cols={cols}, path={path}"

    if dry_run:
        return SaveDataResult(True, str(path), str(meta_path or ""), rows, cols,
                              samples, 0, f"dry-run: {detail}")

    try:
        path.parent.mkdir(parents=True, exist_ok=True)

        if fmt == "npz":
            payload = data if isinstance(data, dict) else {str(key or "data"): data}
            payload = {str(k): np.asarray(v) for k, v in payload.items()}
            if compress:
                np.savez_compressed(path, **payload)
            else:
                np.savez(path, **payload)
        elif fmt == "npy":
            arr = np.asarray(data)
            np.save(path, arr, allow_pickle=False)
        elif fmt == "csv":
            delim = _CSV_DELIM.get(str(csv_delimiter), ",")
            mode = "a" if str(csv_mode).lower() == "a" else "w"
            _write_csv(path, data, delimiter=delim, header=csv_header, mode=mode)
        else:  # json
            _write_json(path, data, indent=int(json_indent))

        if write_meta:
            meta = {
                "source": "MyGameEngine.NodeEditor",
                "format": fmt,
                "data_file": path.name,
                "path": str(path),
                "files": [str(path)],
                "key": str(key or "data"),
                "rows": rows,
                "cols": cols,
                "samples": samples,
                "samples_saved": samples,
                "shape": shape,
                "dtype": dtype,
                "unique": bool(unique),
                "tag": str(tag or ""),
                "elapsed_s": float(elapsed_s or 0.0),
                "saved_iso": datetime.now().astimezone().isoformat(timespec="seconds"),
            }
            _write_json(meta_path, meta, indent=2)

        print(f"[SaveData] {fmt} {rows}x{cols} -> {path}")
        return SaveDataResult(True, str(path), str(meta_path or ""), rows, cols,
                              samples, 1, detail)
    except Exception as e:
        print(f"[SaveData] ERROR: {e}")
        return SaveDataResult(False, str(path), str(meta_path or ""), rows, cols,
                              samples, 0, f"{type(e).__name__}: {e}")


def _eval_save_data(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """SaveData 节点求值器。

    Data 始终优先读上游 pin；未连接时回退 props["value"]（手动 JSON/标量）。
    mode=manual 时 FileName 从控件读取；mode=pin 时优先读 FileName pin。
    """
    inst = g._canvas.nodes[node_id]
    mode = inst.props.get("mode", "manual")

    file_path = _read_input_raw(node_id, "FilePath", ctx, g, None)
    if file_path is None or (isinstance(file_path, str) and not file_path.strip()):
        file_path = str(inst.props.get("file_path", ""))

    if mode == "pin":
        file_name = _read_input_raw(node_id, "FileName", ctx, g, "")
        if file_name is None or (isinstance(file_name, str) and not file_name.strip()):
            file_name = str(inst.props.get("file_name", "data"))
    else:
        file_name = str(inst.props.get("file_name", "data"))

    data = _read_input_raw(node_id, "Data", ctx, g, None)
    if data is None:
        data = _decode_manual_value(inst.props.get("value", ""))

    try:
        json_indent = int(inst.props.get("json_indent", 2))
    except (TypeError, ValueError):
        json_indent = 2

    result = save_data(
        data,
        file_path=file_path,
        file_name=file_name,
        fmt=str(inst.props.get("format", "npz")),
        key=str(inst.props.get("key", "data")),
        compress=_as_bool(inst.props.get("compress", True), True),
        unique=_as_bool(inst.props.get("unique", True), True),
        tag=str(inst.props.get("tag", "")),
        save_meta=_as_bool(inst.props.get("save_meta", True), True),
        csv_delimiter=str(inst.props.get("csv_delimiter", "comma")),
        csv_header=str(inst.props.get("csv_header", "")),
        csv_mode=str(inst.props.get("csv_mode", "w")),
        json_indent=json_indent,
        elapsed_s=float(getattr(ctx, "elapsed_time", 0.0)),
        dry_run=bool(ctx.dry_run),
    )

    _write_output_raw(node_id, "Path", result.path if result.ok else "", ctx, g)
    _write_output_raw(node_id, "MetaPath", result.meta_path if result.ok else "", ctx, g)
    _write_output_raw(node_id, "Rows", int(result.rows), ctx, g)
    _write_output_raw(node_id, "Cols", int(result.cols), ctx, g)
    _write_output_raw(node_id, "Samples", int(result.samples), ctx, g)
    _write_output_raw(node_id, "Written", int(result.written), ctx, g)
    _write_output_raw(node_id, "Ok", 1 if result.ok else 0, ctx, g)

    ctx.emit_log(node_id, "SaveData", "data_save" if result.ok else "error",
                 result.detail or "save failed")


register_evaluator("SaveData", _eval_save_data)
