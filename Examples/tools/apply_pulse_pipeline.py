"""把 1 Hz 脉冲流水线写入**当前场景**（可重复运行 = 覆写已有节点）。

用法（编辑器运行中；参数用 `key=value`，与 `engine-editor-cli call` 风格一致）：

    engine-editor-cli exec Examples/tools/apply_pulse_pipeline.py serial port=@mydevice
    engine-editor-cli exec Examples/tools/apply_pulse_pipeline.py parallel address=0x3FF8
    engine-editor-cli exec Examples/tools/apply_pulse_pipeline.py serial port=COM5 period=0.5 max=5
    engine-editor-cli exec Examples/tools/apply_pulse_pipeline.py serial port=COM5 overwrite=1
    engine-editor-cli exec Examples/tools/apply_pulse_pipeline.py serial dry_run=1

（`--port COM5` / `--overwrite` 写法也接受，但 CLI 会把 `--xxx` 当成自己的选项
在部分 shell 下报错，推荐用 `key=value`。）

语义：

- 第一次运行 → 创建整套节点（core 链 + **一个** SerialSend/ParallelSend）和连线。
- 再次运行 → 按节点 description 里的 `[pulse:<tag>:<slot>]` 标记**找到同一批节点**，
  只更新参数，不会复制出第二份；你在面板里改过的属性（模板属性除外）保留。
- `overwrite=1` → 用模板值覆盖所有模板属性（把面板改动整体压回模板）。
- `template=<实体名>` → 流水线会在 OnGameStart 生成该模板（默认 `Cross`）；
  你自己的场景没有十字模板时用 `template=none`（跳过 EntitySpawn，少一个节点），
  这时实体的生成交给场景里你自己的节点。
- 想彻底删除：在 Node Editor 里选中流水线节点按 Del（当前没有 live 删除 op）。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pulse_pipeline as pp  # noqa: E402

_USAGE = __doc__


def _split_opt(token):
    """Accept both `key=value` and `--key value` / `--flag`. Returns (key, value, consumed_next)."""
    if "=" in token:
        key, value = token.split("=", 1)
        return key.lstrip("-"), value, False
    return token.lstrip("-"), None, True


def _parse(argv):
    if not argv:
        print(_USAGE)
        raise SystemExit(2)
    kind = argv[0]
    opts = {
        "kind": kind,
        "tag": pp.DEFAULT_TAG,
        "port": pp.DEFAULT_PORT,
        "baud": pp.DEFAULT_BAUD,
        "fmt": pp.DEFAULT_FORMAT,
        "address": pp.DEFAULT_ADDRESS,
        "period": pp.DEFAULT_PERIOD,
        "max_value": pp.DEFAULT_MAX,
        "template": "Cross",
        "overwrite": False,
        "dry_run": False,
    }
    flags = ("overwrite", "dry-run", "dry_run")
    explicit: set[str] = set()
    i = 1
    while i < len(argv):
        token = argv[i]
        name, value, needs_value = _split_opt(token)
        name = name.replace("-", "_")
        if needs_value and name in flags:
            opts["dry_run" if name.startswith("dry") else "overwrite"] = True
            i += 1
            continue
        if needs_value:
            if i + 1 >= len(argv):
                raise ValueError(f"missing value for {token}")
            value = argv[i + 1]
            i += 1
        i += 1
        if name in ("port", "tag", "template"):
            opts[name] = value
        elif name == "baud":
            opts["baud"] = int(value)
        elif name in ("format", "fmt"):
            opts["fmt"] = value
            name = "format"
        elif name == "address":
            opts["address"] = int(value, 0)
        elif name in ("period", "interval"):
            opts["period"] = float(value)
            name = "period"
        elif name in ("max", "max_value", "upper"):
            opts["max_value"] = int(value)
            name = "max_value"
        elif name in ("overwrite", "dry_run", "dry"):
            opts["overwrite" if name == "overwrite" else "dry_run"] = str(value).strip() not in ("0", "false", "no", "")
            name = "overwrite" if name == "overwrite" else "dry_run"
        else:
            raise ValueError(f"unknown option: {name}")
        explicit.add(name)
    opts["explicit"] = explicit
    return opts


def main(argv):
    opts = _parse(argv)
    result = pp.apply(engine, **opts)
    print(pp.summary_line(result))
    for item in result["created"]:
        print(f"  + created {item['slot']:<11} {item.get('type', '')} #{item.get('node_id', '?')}")
    for item in result["updated"]:
        print(f"  ~ updated {item['slot']:<11} #{item.get('node_id', '?')} {item['props']}")
    if result["skipped"]:
        for item in result["skipped"]:
            print(f"  ! skipped {item}")
    if result["dry_run"]:
        print("  (dry-run: nothing written)")
    else:
        print("  下一步: graph.validate / sim.play 验证；改动会随场景保存而持久化。")


main(sys.argv[1:])
