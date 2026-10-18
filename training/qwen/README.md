# Local Qwen video worker

The checked-in `runtime_selection.json` selects **native Qwen3-VL-4B-Instruct**
with `pixel_cap: 3145728`. The packaged implementation is
`native-sequence-refine-v14-room-door-detail`: overlapping video windows,
temporal review of proposed events, and an observation-first room-door path.
This is the existing local inference implementation, not new model training.
Only native 2B and native 4B are registered; unrelated focused and
observation-native experiments are deliberately unavailable.

Recognition remains experimental. Two development recordings were used for
the latest recognition check; that is not an independent accuracy test and
does not establish timestamp accuracy. CPU tests check orchestration and data
contracts using synthetic inputs. Neither those tests nor successful processing
prove correct recognition. No overall accuracy percentage is claimed.

The repository contains no recordings, private model responses, credentials,
or model weights. Installing the dependencies does not launch a worker.

## Install on Windows

Requires Python 3.12, an NVIDIA CUDA GPU with a compatible driver, and enough
disk space for both downloaded weight parts and their assembled files.
The development machine used 6 GB VRAM; the 4B model uses quantized loading,
and some inputs can still exceed memory or processing deadlines. CPU fallback
for inference is deliberately disabled.

From the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File training/qwen/bootstrap.ps1 -DownloadModel -Model 4b
```

This creates `training/.venv`, installs CUDA PyTorch and the inference
dependencies, then downloads official `Qwen/Qwen3-VL-4B-Instruct` files into
`training/qwen/base-4b`. The published downloader pins revision
`ebb281ec70b05090aa6165b016eac8ec08e71b17`, checks upstream weight SHA-256 and
small-file Git checksums, and marks the completed local manifest only after
validation. It does not copy another machine's model files or read project
media. The setup download uses the network; inference subsequently loads local
files only and disables outbound network connections in its process.

To resume the same 4B download:

```powershell
training/.venv/Scripts/python.exe training/qwen/download_model_4b.py
```

An existing `base-4b/snapshot_pin.json` for a different revision is rejected
instead of silently reusing a different model. Keep or move that older snapshot
yourself before downloading the published revision. Do not commit any model
directory or private recording.

The older 2B snapshot remains supported as an explicit option:

```powershell
powershell -ExecutionPolicy Bypass -File training/qwen/bootstrap.ps1 -DownloadModel -Model 2b
```

This downloads official `Qwen/Qwen3-VL-2B-Instruct` revision
`89644892e4d85e24eaac8bacfd4f463576704203` into `training/qwen/base`.
Downloading 2B does not change the selected runtime. To use it, edit the local
selection to `{"engine":"native","model":"2b","pixel_cap":3145728}`.
If the selection file is absent, the legacy native 2B/no-global-cap fallback
applies; the checked-in 4B selection is therefore part of this release.

## Run

Use `START_AIQYN_VISION.ps1` from the repository root for the integrated local
site. The launcher selects the Qwen backend; the service's legacy default is
unchanged for other deployments. Model download is a separate setup action.

For the worker protocol directly:

```powershell
training/.venv/Scripts/python.exe training/qwen/quick_inference.py --worker
```

The first stdout message announces readiness. Each line-delimited JSON request
contains `id`, an absolute local `path`, and optionally `budget_sec`. Each reply
contains the same `id`, `ok`, and either `result` or an explicit error. Model logs
go to stderr. The source validator accepts a single-stream MOV recording up to
180 seconds and 64 MiB. The backend stores uploads locally. Incomplete analysis
or timeouts must remain errors, not successful empty results.

Results include private source evidence and model-generated possible events.
An empty result does not establish compliance. The normative reference helper
is attached outside this model implementation and does not improve perception.

`source_snapshot.json` records hashes of the packaged source and runtime config.
It does not contain model weights or private observation data.
