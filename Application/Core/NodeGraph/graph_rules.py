"""
节点图 JSON 参考文档 (v0.1.0) — 每次导出 scene 时附带此规则文档。

Agent 通过此文档理解节点图的 JSON 结构和可用节点类型。
"""

_NODE_GRAPH_RULES = """## Node Graph JSON Reference (v0.1.0)

### JSON Structure
The node_graph is a JSON object with these keys:
- "version": "0.1.0"
- "nodes": { "<nid>": {NodeInstance}, ... }  — nid is globally unique int (string key)
- "links": { "<lid>": {LinkInstance}, ... }  — lid is globally unique int (string key)
- "next_id": int — 1 + max(all node/link/pin IDs), ensures no collision on future additions
- "_rules": "<this document>"

### NodeInstance Format
  "id": <int>, "node_type": "<type_name>", "pos": [<x>, <y>],
  "props": {<key>: <value>, ...},  — mode-dependent props (see per-node table)
  "pin_ids": {"<pin_name>": <int>, ...}  — instance-level unique pin IDs

### LinkInstance Format
  "id": <int>, "from_pin": <int> (output pin ID), "to_pin": <int> (input pin ID)

### Pin IDs
Every node has a pin_ids dict mapping logical pin name → instance-unique integer.
All links reference these instance-level IDs, NOT template-level PinDef IDs.
When writing a graph, assign pin IDs sequentially starting from a high base (e.g., nid*10).

### Connection Rules (CRITICAL)
1. exec pins connect exec→exec: output exec pin → input exec pin
2. data pins connect data→data: output data pin → input data pin
3. NEVER connect exec→data or data→exec
4. One output pin can fan out to multiple input pins (both exec and data)
5. An input pin can only receive from ONE output pin
6. Event nodes (OnGameStart/OnFrameUpdate/OnGameStop) have NO input exec pins — they are graph roots
7. device pins connect device→device: Init*Device.device (output) → AddToDevicePool.device (input). These are NOT exec/data pins.
8. A device output pin feeds AT MOST ONE AddToDevicePool (a device belongs to one pool — exclusive membership). Devices never added to a pool stay in the implicit "global" pool.

### Execution Model
- OnGameStart: fires ONCE when the game begins. Use for initialization (set variables, spawn entities).
- OnFrameUpdate: fires EVERY FRAME. Use for per-frame checks (TimeTrigger, input polling).
- OnGameStop: fires ONCE when the game ends. Use for cleanup.
- Exec chain: _walk_exec follows exec output→input links depth-first.
- Data nodes (Constant/Scale, StringConst, PathVar, Compare, ScalarMath, MakeVec3, BreakVec3, VecMath, Random, legacy math):
  NO exec pins. Evaluated LAZILY when their output pin is read via a data link.
- Mixed nodes (VarGet): have BOTH exec_in and data output pins. Exec triggers read; data output
  is then available for downstream data links. When data-read without exec context, lazy-eval works too.
- _blocked pattern: TimeDelay and TimeTrigger set _blocked=True to pause exec chain.
  Branch sets _blocked=True after manually walking the matching branch.
- Variable store: ctx._variables persists across frames. VarSet writes, VarGet reads.
  Variables are NOT cleared between triggers — use them for state (counters, timers).

### Pin Naming Convention
- exec_in / exec_out: execution flow pins
- out_0..out_7: Sequence or TimeTrigger multi-output exec pins
- Data pins have descriptive names: Value, Result, A, B, X, Y, Z, In_0..In_7, etc.
- Pin direction is determined by the node type definition (see tables below)

---

### NODE TYPE REFERENCE

#### Event Nodes (graph roots — no input pins)
| type_name      | output pins                  | notes                            |
|----------------|------------------------------|----------------------------------|
| OnGameStart    | exec (exec)                  | fires once at game start         |
| OnFrameUpdate  | exec (exec), delta (float)   | fires every frame                |
| OnGameStop     | exec (exec)                  | fires once at game stop          |

#### Flow Nodes
| type_name | input pins              | output pins               | props              |
|-----------|-------------------------|---------------------------|--------------------|
| Sequence  | exec_in (exec)          | out_0,out_1,out_2 (exec) | —                  |
| Branch    | exec_in,Condition(bool) | True,False (exec)         | —                  |

#### Math Nodes (pure data — no exec pins)
| type_name      | input pins                    | output pins    | props                        |
|----------------|-------------------------------|----------------|------------------------------|
| ScalarMath     | In_0..In_7 (float)           | Result (float) | operation: sum/sub/mul/div   |
| Compare        | A (float), B (float)          | Result (bool)  | operation: gt/lt/eq/neq/gte/lte |
| MathAdd        | A,B (float)                   | Result (float) | — (legacy, hidden)           |
| MathSubtract   | A,B (float)                   | Result (float) | — (legacy, hidden)           |
| MathMultiply   | A,B (float)                   | Result (float) | — (legacy, hidden)           |
| MathDivide     | A,B (float)                   | Result (float) | — (legacy, hidden)           |
| RandomSetSeed  | exec_in,exec_out,Seed(int)   | (exec_out)     | source: manual/pin/hardware, seed: int  |
| Random         | Min,Max,Mean,StdDev (float)   | Result (float) | distribution: uniform/gaussian/discrete, mode: manual/pin |
| MathRandomUniform  | Min,Max (float)           | Result (float) | — (legacy, hidden)           |
| MathRandomGaussian | Mean,StdDev (float)       | Result (float) | — (legacy, hidden)           |
| MakeVec3       | X,Y,Z (float)                 | Vec3 (vec3)    | —                            |
| BreakVec3      | Vec3 (vec3)                   | X,Y,Z (float)  | —                            |
| VecMath        | A,B (vec3)                    | Result(var)   | operation: add/sub/mul/div/dot/cross/normalize/length |

#### Time Nodes
| type_name      | input pins               | output pins                    | props                  |
|----------------|--------------------------|--------------------------------|------------------------|
| TimeGetElapsed | exec_in (exec)           | exec_out (exec), Elapsed(float)| —                      |
| TimeGetDelta   | exec_in (exec)           | exec_out (exec), Delta(float)  | —                      |
| TimeDelay      | exec_in,Seconds(float)   | exec_out (exec)                | —                      |
| TimeTrigger    | exec_in,Time(float)      | Elapsed(float), out_0..out_7(exec×8) | mode: manual/pin, time: float |
| TimeGetDate    | —                        | DateString (string)            | year,month,day,hour,minute: bool, format: str |

TimeTrigger behavior: fires when ctx.elapsed_time >= threshold. Re-armable: increasing the threshold via variable/pin allows repeated triggering. Tracks _last_fired_threshold in state.

#### Basic Nodes (fundamental value types)
| type_name   | input pins | output pins    | props              |
|-------------|------------|----------------|--------------------|
| Constant    | —         | Result (float) | value: float       |
| StringConst | —         | Value (string) | value: string      |

Constant is labeled "Number" in the UI. StringConst outputs a raw string (no float coercion).

#### Variable Nodes
| type_name | input pins                    | output pins             | props                          |
|-----------|-------------------------------|-------------------------|--------------------------------|
| VarSet    | exec_in,Name(string),Value(var)| exec_out (exec)        | mode: manual/pin, var_name, value |
| VarGet    | exec_in,Name(string)          | exec_out,Value(var)     | var_name                       |

VarSet manual mode: Name from textbox prop, Value from props.value.
VarSet pin mode: Name from upstream link, Value from upstream link.
VarGet: reads ctx.get_var(name) and writes to Value output.

#### Entity Nodes
| type_name             | input pins                                  | output pins          | props            |
|-----------------------|---------------------------------------------|----------------------|------------------|
| EntitySpawn           | exec_in (exec)                              | exec_out,Entity(ref) | template: string |
| EntityDestroy         | exec_in,EntityID(int)                       | exec_out             | —                |
| EntityGet             | exec_in,Name(string)                        | exec_out,Entity(ref) | —                |
| EntityAddMesh         | exec_in,EntityID,MeshID,MaterialID (int)    | exec_out             | —                |
| EntityAddCamera       | exec_in,EntityID (int)                      | exec_out             | —                |
| EntitySetRenderVisible| exec_in,EntityID(int),Visible(bool)         | exec_out             | —                |

EntitySpawn: creates entity from Scene.entities template (dropdown). Recursively spawns children.
EntityRef: type-safe wrapper with is_valid property. Output as entity_ref on data pins.

#### Game Nodes
| type_name    | input pins                  | output pins | notes                    |
|--------------|-----------------------------|-------------|--------------------------|
| CameraSetMain| exec_in,Entity(entity_ref)  | exec_out    | sets scene_camera_id     |
| ExitGame     | exec_in                     | —           | terminal node, no output |

#### Component Nodes
| type_name      | input pins                                    | output pins | props             |
|----------------|-----------------------------------------------|-------------|-------------------|
| ComponentAdd   | exec_in,Entity(ref),Position,Rotation,Scale(vec3),MeshID,MaterialID(int),Visible(bool) | exec_out | mode, component, per-prop enabled |
| ComponentRemove| exec_in,Entity(ref)                           | exec_out | component (dropdown) |
| SetComponent   | exec_in,Entity(ref),Position,Rotation,Scale(vec3),MeshID,MaterialID(int),Visible(bool) | exec_out | mode, component, per-prop enabled |
| GetComponent   | exec_in,Entity(ref)                           | exec_out, Position,Rotation,Scale(vec3),MeshID,MaterialID(int),Visible(bool) | component (dropdown) |

Property pins use _SKIP sentinel: unconnected (pin mode) or unchecked (manual mode) → property not modified.

#### Debug Nodes
| type_name   | input pins           | output pins | props           |
|-------------|----------------------|-------------|-----------------|
| Print       | exec_in,Value(var)   | exec_out    | —               |
| PrintString | exec_in              | exec_out    | message: string |

#### IO Nodes
| type_name    | input pins                              | output pins | props                                      |
|--------------|-----------------------------------------|-------------|--------------------------------------------|
| SerialSend   | exec_in,Value(var) | exec_out | format: string/bytes, port, baud_rate |
| ParallelSend | exec_in,Address(int),Value(var)        | exec_out | mode: manual/pin, address: int (0x3FF8 LPT1, 0x3FF0 LPT2, 0x3FE8 LPT3), value: 1-255 |
| PathVar      | —                                      | Path (string) | browse_mode: directory/file, path: string |
| TextFileWrite| exec_in,FilePath(string),FileName(string),Value(var) | exec_out | mode: manual/pin, write_mode: w/a, delimiter: none/space/newline/tab/comma, file_path, file_name, value |

SerialSend format "string"→UTF-8, "bytes"→float32 LE 4 bytes. Port/BaudRate always read from node props; Value from upstream pin.
ParallelSend always sends uint8 (1-255, 0 reserved for auto-reset after 5ms).
PathVar outputs a directory or file path selected via OS file browser. browse_mode=directory uses select_folder, browse_mode=file uses open_file (.txt/.csv/.log/.json).
TextFileWrite writes str(value) + delimiter to {file_path}/{file_name}.txt. FileName auto-appends .txt suffix. Directory created if missing. write_mode="w" overwrites, "a" appends. Delimiter appended after each write: none="", space=" ", newline="\\n", tab="\\t", comma=",".
FilePath is always handled by widget (Browse button); pin connection overrides widget value.

#### Gtec Nodes (g.HIamp EEG acquisition — IO ▸ Gtec)
| type_name       | input pins | output pins | props |
|-----------------|------------|-------------|-------|
| InitGtecDevice  | exec_in    | exec_out, device(device) | device: HIAMP, device_name, serial (""=auto), template: 64ch/128ch/144ch, sampling_rate: 256/512/600/1200/2400/4800/9600/19200/38400, notch: off/50/60, filter_type: none/highpass/lowpass/bandpass, low_cut, high_cut (0=unset, ignored if not applicable), export_format: npz/csv, save_dir ("."=cwd), buffer_seconds |
| StartGtecRecord | exec_in    | exec_out    | device_name, pool: global/<pool_name> |
| StopGtecRecord  | exec_in    | exec_out    | device_name, pool, save_scope: session/buffer |
| KillGtecDevice  | exec_in    | exec_out    | device_name, pool |
| GetGtecData     | (none, pure data node) | Data (variant ndarray channels×samples), Channels (int), Samples (int), Fs (float) | device_name, pool |

Gtec rules (CRITICAL):
1. InitGtecDevice and KillGtecDevice MUST appear as a pair (validator enforces; editor deletion cascades). Kill binds by device_name; empty name + single Init = auto-bind.
2. Trigger is always enabled (16 digital lines combined into one extra channel) — not configurable.
3. Online filters: cutoff 0 = unset → not applied; fields not matching filter_type are ignored (e.g. low_cut with lowpass). Device filters are discrete presets — unmatched requests are skipped with a log.
4. Window buffer: buffer_seconds × sampling_rate → (channels, N) float32 sliding window; old data is overwritten. GetGtecData returns a non-destructive copy (unfilled region = 0) plus Channels / Samples(valid) / Fs. Array size depends only on Init config.
5. StopGtecRecord saves to Init's save_dir (default "." = cwd): scope=session → everything since Start; scope=buffer → window only. File formats: npz or csv + sidecar .json metadata.
6. Dry-run (MCP validate_graph, max_frames>0): deterministic stub backend — no hardware, no file writes, no threads; reproducible.

#### SigGen Nodes (Virtual Signal Generator — IO ▸ SigGen)
| type_name       | input pins | output pins | props |
|-----------------|------------|-------------|-------|
| InitSigGenDevice | exec_in | exec_out, device(device) | device_name, channels (1..256), sampling_rate (1..38400), frequency (Hz; ≤0 = unset → 10), freq_step (Hz per channel; 0 = same freq), amplitude_uv, noise_uv (0 = clean sine), seed, export_format: npz/csv, save_dir ("."=cwd), buffer_seconds |
| StartSigGenRecord | exec_in | exec_out | device_name, pool: global/<pool_name> |
| StopSigGenRecord | exec_in | exec_out | device_name, pool, save_scope: session/buffer |
| KillSigGenDevice | exec_in | exec_out | device_name, pool |
| GetSigGenData   | (none, pure data node) | Data (variant ndarray channels×samples), Channels (int), Samples (int), Fs (float) | device_name, pool |

SigGen rules (CRITICAL):
1. InitSigGenDevice and KillSigGenDevice MUST appear as a pair (validator + editor deletion cascade; binding identical to Gtec).
2. Pure software sine source — runs on any machine (no hardware). Channel i frequency = f0 + i·step Hz; amplitude in µV float32; optional deterministic Gaussian noise via seed.
3. Buffer / Get / Stop-save semantics identical to Gtec rules 4–6. REAL runs (not dry-run) actually write npz/csv + .json sidecar into save_dir; dry-run writes nothing.
4. Gtec and SigGen share one device session registry — device_name must be unique across families.

#### Device Pool Nodes (IO ▸ Pool)
| type_name        | input pins               | output pins | props |
|------------------|--------------------------|-------------|-------|
| CreateDevicePool | exec_in                  | exec_out    | pool_name ("" → fallback key pool#<nid>) |
| AddToDevicePool  | exec_in, device (device) | exec_out    | pool_name (must match a CreateDevicePool) |
| KillDevicePool   | exec_in                  | exec_out    | pool_name ("" + single Create = auto-bind) |

Device pool rules (CRITICAL):
1. CreateDevicePool ⇄ KillDevicePool MUST appear as a pair (validator + editor deletion cascade; binding by pool_name, like devices).
2. AddToDevicePool.device pin MUST be linked from an Init*Device.device output, and the Add node MUST run on the SAME exec chain, right after that Init (ctx pin values live for one trigger only).
3. A device belongs to exactly ONE pool (exclusive). Re-executing Add with another pool MOVES the device (runtime logs it).
4. Devices not added to any pool stay in the implicit "global" pool; "global" cannot be created or destroyed.
5. Device reference nodes (Start/Stop/Kill/Get) select pool (default "global"); with device_name empty they auto-bind the SOLE device of the selected pool (pool may hold multiple devices → then set device_name).
6. KillDevicePool unregisters the pool only — member devices keep running (each owns its Kill*Device node). Members fall back to "global".
7. Dry-run (validate_graph): pools share the "dryrun#" namespace with sessions and are cleaned up after the run.

#### Pattern 7: Device + Pool (e.g. SigGen solo or multi-device hyper-scanning prep)
```
OnGameStart → CreateDevicePool(pool_name="eeg") → InitSigGenDevice(device_name="SG1")
  → AddToDevicePool(pool_name="eeg", device←InitSigGenDevice.device)
  → StartSigGenRecord(pool="eeg", device_name="")
OnFrameUpdate → GetSigGenData(pool="eeg", device_name="") → ...
OnGameStop → StopSigGenRecord(pool="eeg") → KillSigGenDevice(pool="eeg", device_name="SG1")
  → KillDevicePool(pool_name="eeg")
```
Key: the Add node sits immediately after its Init in the same chain; acquisition/reference nodes pick the pool and leave device_name empty (auto-bind). With several devices in one pool, set device_name explicitly on Start/Stop/Kill/Get.

#### Epoch Dataset Nodes (Epoch — neuroengineering convention)
| type_name   | input pins | output pins | props |
|-------------|------------|-------------|-------|
| EpochAppend | exec_in, Data (variant), Samples (int), Fs (float), Label (float) | exec_out | epochs_name ("" → fallback key epochs#<nid>) |
| EpochCount  | (none, pure data node) | Count (int), Classes (int), Channels (int), Fs (float) | epochs_name |
| EpochClear  | exec_in | exec_out | epochs_name |
| EpochSave   | exec_in | exec_out | epochs_name, save_dir ("."=cwd) |
| EpochLoad   | exec_in | exec_out | epochs_name, file_path (npz), mode: replace/append |

Epoch dataset rules (CRITICAL):
1. One epoch = one trial segment (channels × samples); appends stack along dim0 → dataset ≈ (epochs, channels, samples). EpochAppend trims to the Samples pin (valid length from Get*Data); Data and Label pins MUST be connected (validator enforces).
2. All epochs in one dataset share channels count and fs — fixed by the first append (mismatch → error logged, epoch skipped). Samples=0 appends are skipped with a log.
3. NO Create/Kill pairing (pure in-memory container — unlike devices/pools). Reference nodes (Count/Clear/Save) bind by epochs_name; empty name + exactly one source (Append/Load) on canvas = auto-bind; otherwise static error.
4. Collect-then-train pattern: append during a trial loop → EpochCount.Count → Compare → Branch gates training; EpochSave for persistence; EpochLoad is the offline-dataset entry (mode replace/append).
5. EpochSave writes npz: X padded (epochs, ch, max_len) + lengths + y + fs. Real runs only — dry-run computes the target path and writes nothing; EpochLoad reads files deterministically (works in dry-run).
6. Dry-run: datasets share the "dryrun#" namespace and are purged after validation; GameRuntime/PlayerBootstrap reset datasets as a runtime safety net.

#### BCI Algorithm Nodes (Algorithm — FBCSP / CCA)
| type_name   | input pins | output pins | props |
|-------------|------------|-------------|-------|
| InitFBCSP   | exec_in | exec_out | model_name ("" → model#<nid>), n_components (1..8), classifier: LDA/SVM, bands: [[lo,hi], ...] (packed list; empty = plain CSP) |
| TrainFBCSP  | exec_in | exec_out | model_name, dataset_name, mode: train/load, model_path (load), save_path (opt) |
| TestFBCSP   | Data (variant), Samples (int) | Label (int), Confidence (float) | model_name |
| TestCCA     | Data (variant), Samples (int), Fs (float) | Label (int idx), Score (float), Freq (float) | freqs: [f, ...] (>=2, no upper limit), n_harmonics (1..8) |

BCI algorithm rules (CRITICAL):
1. InitFBCSP registers a spec (hyperparams) under model_name; TrainFBCSP(train) binds the spec + an Epoch dataset (both by name; empty + single canvas source = auto-bind) and registers the trained model under the SAME key; TestFBCSP binds a trained model by name.
2. Training = SYNCHRONIZED WAIT: TrainFBCSP blocks the exec flow while a service thread trains (progress via logs); on completion the SAME exec walk continues downstream exactly once (one-shot, like TimeTrigger). Put it on a repeatedly-triggered chain — an OnGameStart-only chain would stall forever (TimeDelay has the same limitation). Dry-run trains synchronously (deterministic).
3. Training needs EXACTLY 2 classes in the dataset (first append fixes channels/fs). Classifier math: closed-form LDA or linear SVM (scipy.optimize, deterministic) — no sklearn dependency.
4. mode=load bypasses training and registers a model from model_path (offline pipeline entry); save_path (train mode) writes the trained model as npz.
5. TestCCA is training-free: references = sin/cos harmonics of each candidate frequency; Label = argmax canonical correlation (index into freqs), Score = that correlation, Freq = its value. At least 2 frequencies required (no upper limit).
6. bands/freqs are PACKED lists (UI unpacks into rows with +/-; external MCP sets/replaces the whole list atomically). Models and datasets share the "dryrun#" namespace during validation and are purged afterwards.

#### Media Nodes (Media — GIF/image playback)
| type_name | input pins | output pins | props |
|-----------|------------|-------------|-------|
| ShowMedia | exec_in, Entity (entity_ref) | exec_out | — |

ShowMedia rules (CRITICAL):
1. Editor-side editing is only a TEMPLATE (entities/MediaPlayer declare source etc.; the editor never plays). Playback takes effect ONCE the graph drives it at runtime (PIE / standalone player, GameRuntime-only).
2. Target entity: Get Entity (Name) → Entity ref → ShowMedia.Entity; unconnected Entity pin fails the static check (media_pin_unconnected).
3. Drive frequency = wiring frequency: OnFrameUpdate chain = per-frame playback (recommended); OnGameStart = single first-frame push. Unconnected exec_in = warning only (media_exec_unconnected).
4. In PIE, editor entities act as EntitySpawn TEMPLATES (they do not render directly); spawn the instance first, then target it by name — EntityGet resolves the spawned instance.
5. Duplicate drivers for one entity are de-duplicated per engine frame (single advance). Media playback state (clock/frame) is runtime-only — never serialized.

---

### COMMON PATTERNS

#### Pattern 1: Timer + Repeated Action (e.g., send every 1s, 10 times then exit)
```
OnGameStart → VarSet(counter=0, mode=manual) → VarSet(next_time=1.0, mode=manual)
OnFrameUpdate → VarGet("next_time") → TimeTrigger(mode=pin, Time←VarGet.Value)
TimeTrigger.out_0 → SerialSend/ParallelSend → VarGet("counter") → ScalarMath(sum:+1) → VarSet("counter", mode=pin)
  → VarGet("next_time") → ScalarMath(sum:+1) → VarSet("next_time", mode=pin)
  → Branch(exec_in, Condition←Compare(A←ScalarMath.Result, B←Constant(10), gte))
  Branch.True → ExitGame
```
Key: TimeTrigger re-arms because next_time increases each fire. Compare.A uses ScalarMath(counter+1).Result directly (no need for a second VarGet).

#### Pattern 2: OnFrameUpdate per-frame action (no timer)
```
OnFrameUpdate → TimeGetElapsed → Print(Value←TimeGetElapsed.Elapsed)
```

#### Pattern 3: Spawn entity on start
```
OnGameStart → EntitySpawn(template="MyEntity") → ...
```

#### Pattern 4: Conditional branch
```
... → VarGet("some_var") → Compare(A←VarGet.Value, B←Constant(threshold), gte)
  → Branch(Condition←Compare.Result) → True: ... / False: ...
```
Note: Branch needs exec_in from the chain. The Condition is a data link from Compare.Result.
The exec_in usually comes from VarGet.exec_out (the VarGet that fed Compare.A).

#### Pattern 5: Parallel port trigger (EEG/SSVEP)
```
OnFrameUpdate → VarGet("next_time") → TimeTrigger(mode=pin) → ParallelSend(Address=0x3FF8, Value=1)
  → VarGet("counter") → ScalarMath(sum) → VarSet("counter", mode=pin)
  → VarGet("next_time") → ScalarMath(sum) → VarSet("next_time", mode=pin)
  → Branch(Condition←Compare(A←ScalarMath.Result, B←Constant(N), gte)) → ExitGame
```

#### Pattern 6: Write to text file (logging experiment data)
```
OnGameStart → VarSet(trial=1, mode=manual) → VarSet(max_trials=10, mode=manual)
OnFrameUpdate → VarGet("next_time") → TimeTrigger(mode=pin)
  TimeTrigger.out_0 → TextFileWrite(
      mode=pin,
      write_mode="a", delimiter="newline",
      FilePath←PathVar(browse_mode=directory, path="D:/Data/"),
      FileName←StringConst(value="experiment_log"),  // → experiment_log.txt
      Value←VarGet("trial").Value
    )
  → VarGet("trial") → ScalarMath(sum:+1) → VarSet("trial", mode=pin)
  → Branch(Condition←Compare(A←ScalarMath.Result, B←VarGet("max_trials").Value, gte))
  Branch.True → ExitGame
```
Key: TextFileWrite creates the directory and file automatically. FileName "experiment_log" becomes "experiment_log.txt".
Use StringConst for static strings, VarGet for dynamic values (but note VarGet returns float — use StringConst for file names).
PathVar provides a reusable directory path that can fan out to multiple TextFileWrite nodes.

---

### WRITING A GRAPH — STEP BY STEP

1. Plan the exec flow: which event nodes trigger what chains.
2. Assign node IDs starting from 200 (reserve 151-199 for default event nodes).
3. For each node, assign pin IDs. Use a scheme like node_id*10+0, node_id*10+1, ... for clarity.
4. Write nodes dict with correct node_type, pin_ids mapping, and props.
5. Write links dict: exec links first (to establish execution order), then data links.
6. Compute next_id = 1 + max(all node IDs, pin IDs, link IDs).
7. Always include the 3 default event nodes (OnGameStart, OnFrameUpdate, OnGameStop).
8. Pure data nodes (Constant, Compare, ScalarMath, etc.) have NO exec pins — only connect them via data links.
9. Use VarGet/Scale → ScalarMath/Compare → VarSet for arithmetic on variables.
   Use StringConst for static string values, VarGet for numeric values.
   Note: VarGet returns float (even for string var names); use StringConst for file names and paths.
10. For repeated TimeTrigger: feed a variable into TimeTrigger.Time pin, increment that variable after each fire."""
