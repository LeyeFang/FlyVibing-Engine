"""
IO 节点 — PathVar, TextFileWrite, SaveData。

SerialSend / ParallelSend 已于 2026-10-20 迁到设备扩展
`Application/Functions/SerialParallelDevice/node_pack.py`（type 名保持兼容）。

SaveData 与 TextFileWrite 职责分离:
  - TextFileWrite: 面向人读的文本日志 (str(value) + 分隔符, .txt);
  - SaveData:      面向算法/后处理的通用数据 (npy/npz/csv/json + meta),
                   信号处理/设备/epoch 扩展统一走这里。

★ 落点（2026-11-11）: 三个节点都有 `relative_to`（output / project / cwd）。
  相对路径**默认落在输出根**（成品 `output/`、PIE `<工程>/output`），
  不再按进程 CWD 解析 —— 旧行为会把文件写进成品目录，装到只读位置直接失败。
  见 `Application/Core/FileSystem/DataPaths.py`。
"""

from . import _reg, _gen_id, IO_COLOR
from ..data_model import NodeTypeDef, PinDef


_reg(NodeTypeDef(
    "PathVar", "Path", "IO", IO_COLOR,
    [
        PinDef(_gen_id(), "Path", "data", "output", "string"),
    ],
    "Directory or file path",
))

_reg(NodeTypeDef(
    "TextFileWrite", "Write Text File", "IO", IO_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
        PinDef(_gen_id(), "FilePath", "data", "input", "string"),
        PinDef(_gen_id(), "FileName", "data", "input", "string"),
        PinDef(_gen_id(), "Value", "data", "input", "variant"),
    ],
    "Write content to a text file",
))

_reg(NodeTypeDef(
    "SaveData", "Save Data", "IO", IO_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
        PinDef(_gen_id(), "Data", "data", "input", "variant"),
        PinDef(_gen_id(), "FilePath", "data", "input", "string"),
        PinDef(_gen_id(), "FileName", "data", "input", "string"),
        PinDef(_gen_id(), "Path", "data", "output", "string"),
        PinDef(_gen_id(), "MetaPath", "data", "output", "string"),
        PinDef(_gen_id(), "Rows", "data", "output", "int"),
        PinDef(_gen_id(), "Cols", "data", "output", "int"),
        PinDef(_gen_id(), "Samples", "data", "output", "int"),
        PinDef(_gen_id(), "Written", "data", "output", "int"),
        PinDef(_gen_id(), "Ok", "data", "output", "int"),
    ],
    "Save arrays/tables/data to npy/npz/csv/json (+ meta)",
))
