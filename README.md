# FlyVibingEngine

**Language:** English | [简体中文](Doc/README.zh-CN.md)

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.14](https://img.shields.io/badge/python-3.14%20free--threaded-3776AB.svg)](https://www.python.org/)
[![Platform: Windows](https://img.shields.io/badge/platform-Windows-0078D4.svg)](#requirements)

FlyVibingEngine is a Python game engine and visual editor for building, previewing, and running experimental paradigms. It combines scene and entity editing, node-graph authoring, a play-in-editor mode, and a standalone runtime with a self-contained export pipeline.

The engine is designed for experimental work rather than general-purpose game production. Projects are plain, version-controllable files; behavior is expressed as inspectable graphs; device I/O and signal-processing modules are first-class; and exported builds carry their own Python runtime and dependencies.

> The authoring and automation toolchain is maintained separately: [FlyVibing-User-And-Developer-Utils](https://github.com/LeyeFang/FlyVibing-User-And-Developer-Utils).

## Features

- **Scene editor** — entity hierarchy, component inspector, transform gizmos, resource browser, project management, and configurable UI language and font size.
- **Node-graph authoring** — execution and data-flow graphs with node aliases, reusable node groups, structural validation, dry-run validation, and static execution-flow inspection.
- **Play in Editor (PIE)** — run, pause, and stop the current scene without leaving the editor. The same runtime is used by packaged builds.
- **Experimental I/O** — serial/parallel device abstraction with simulated backends, virtual devices, signal-processing nodes, epoch datasets, and FBCSP/CCA algorithms.
- **Dynamic content** — image/GIF playback through runtime texture updates, dynamic text rendering, and material/shader pipelines.
- **Extension system** — a tiered extension model (declarative, hook-based, out-of-process) with built-in modules under `Application/Functions/`.
- **Self-contained distribution** — exports bundle the runtime and an offline wheelhouse; the result launches through `run_game.cmd` on a clean machine.
- **Automation surface** — a loopback TCP command server exposes editor operations to CLI and MCP clients for scripted or assisted workflows.
- **Free-threaded runtime** — CPython 3.14 with the GIL disabled.

## Requirements

| Role | Requirements |
|---|---|
| End users | Windows 10/11. The installer ships the engine, Python runtime, and all dependencies; no Python or package manager is required. |
| Developers | [uv](https://docs.astral.sh/uv/) and a Python 3.14 free-threaded environment, provisioned by `Utils\Dev\setup_env.bat` into `.venv-py314t`. |
| Automation clients | Python 3.10+ for the separate [toolchain packages](https://github.com/LeyeFang/FlyVibing-User-And-Developer-Utils). The editor must be running for live operations. |

## Quick start

### Install (end users)

Run the separately distributed `FlyVibingEngine-Setup-*.exe` installer, then launch the editor from the Start menu or desktop shortcut.

### Run from source

```powershell
git clone https://github.com/LeyeFang/MyGameEngine-Python.git
cd MyGameEngine-Python
Utils\Dev\setup_env.bat
startup.bat
```

`setup_env.bat` installs Python 3.14t through uv and synchronizes dependencies from `Utils\Dev\uv-py314t.lock`. `startup.bat` prefers `.venv-py314t` and falls back to the bundled runtime in an installed build.

### Run a project without the editor

```powershell
Utils\User\player.bat path\to\project.myproj
```

Projects can also be exported from the editor through **File ▸ Export**. The exported package includes the runtime, an offline wheelhouse, and `run_game.cmd`.

## Repository layout

| Path | Contents |
|---|---|
| `Application/` | Engine, editor, and runtime source (`Core/`, `Editor/`, `Runtime/`, `Functions/`) |
| `Application/Functions/` | Built-in modules and extensions: device I/O, signal processing, BCI algorithms, virtual devices |
| `Resource/` | Fonts, icons, materials, meshes, shaders, textures, and prefabs; `wheels/` contains the offline dependency manifests and bootstrap wheel |
| `Utils/Dev/` | Development environment, test runner, wheel collection, runtime preparation, and installer build |
| `Utils/User/` | Files shipped with exported games (`player.bat`) |
| `Doc/Dev/` | Internal development protocols and architecture contracts |
| `Doc/ExtDev/` | Extension development specification |
| `Doc/User/` | User-facing guides, including editor automation |

## Related repositories

| Repository | Scope |
|---|---|
| **MyGameEngine-Python** (this repository) | Engine, editor, runtime, built-in modules, engine development tools |
| [**FlyVibing-User-And-Developer-Utils**](https://github.com/LeyeFang/FlyVibing-User-And-Developer-Utils) | Authoring and automation toolchain: `editor-mcp`, `node-editor`, `extension-kit`, and agent skills |

To work on both repositories side by side:

```powershell
git clone https://github.com/LeyeFang/FlyVibing-User-And-Developer-Utils.git ..\FlyVibing-User-And-Developer-Utils
Utils\Dev\link_tools.bat
pip install -e ..\FlyVibing-User-And-Developer-Utils\packages\editor-mcp
```

## Editor automation

While the editor is running, a loopback command server listens on `127.0.0.1:8977`. The toolchain repository provides:

- `engine-editor-cli` — terminal client with no persistent context cost;
- `engine-editor-mcp` — MCP server with a lite profile (5 tools) and a full compatibility profile;
- `flyvibing-node-editor` — offline graph construction, validation, and scene injection.

Set up a workspace with the skill and MCP configuration in one step:

```powershell
engine-editor-cli setup --workspace C:\path\to\your-project
```

See [`Doc/User/editor_mcp_guide.md`](Doc/User/editor_mcp_guide.md) for the user guide and [`Doc/Dev/editor_live_protocol.md`](Doc/Dev/editor_live_protocol.md) for the protocol.

## Documentation

| Audience | Entry point |
|---|---|
| Engine developers | [`Doc/Dev/README.md`](Doc/Dev/README.md) — development protocols and document map |
| Extension authors | [`Doc/ExtDev/README.md`](Doc/ExtDev/README.md) — self-contained extension guide |
| Experiment authors | [`Doc/User/editor_mcp_guide.md`](Doc/User/editor_mcp_guide.md) and the [toolchain tutorial](https://github.com/LeyeFang/FlyVibing-User-And-Developer-Utils/blob/main/docs/TUTORIAL.md) |
| Toolchain maintainers | [Toolchain README](https://github.com/LeyeFang/FlyVibing-User-And-Developer-Utils) |

## Development

| Task | Command |
|---|---|
| Install or repair the environment | `Utils\Dev\setup_env.bat` |
| Run core regression tests | `.venv-py314t\Scripts\python.exe Utils\Dev\test_runner.py --tier core` |
| Rebuild the offline wheelhouse | `.venv-py314t\Scripts\python.exe Utils\Dev\collect_wheels.py` |
| Prepare the bundled runtime image | `.venv-py314t\Scripts\python.exe Utils\Dev\prepare_runtime.py` |
| Build the Windows installer | `.venv-py314t\Scripts\python.exe Utils\Dev\Installer\build_installer.py` |

Development follows the protocols in `Doc/Dev/`. Changes should pass the relevant tests and update the corresponding protocol document.

## Contributing

Issues and pull requests are welcome. For changes that affect editor behavior, node types, device integration, or packaging, read the matching document in `Doc/Dev/` first and update it with the implementation.

## License

[MIT](LICENSE) © 2026 Leye Fang
