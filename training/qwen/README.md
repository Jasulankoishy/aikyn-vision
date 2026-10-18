# Local Qwen video worker

This source package runs the native **Qwen3-VL-2B-Instruct** pipeline used by the
backend worker when local Qwen analysis is explicitly enabled. Installing this
package does not activate Qwen, modify runtime settings, or launch a worker.
It does not include training data, recordings, model weights,
generated reports, private machine answers, or credentials. Experimental
observation-first, balanced-answer and 4B engines are not enabled or registered.

The pipeline samples the supplied local recording, checks overlapping intervals,
and revisits proposed events at higher sampling density. Findings and timecodes
are model-generated possibilities. Recognition remains imperfect; processing a
recording successfully is not proof that every violation was detected, and an
empty result does not establish compliance. No accuracy percentage is claimed.
The packaged native baseline omits the failed v11 room-door A–D sequence gate
and retains the preceding v10 dense-context behavior. Its recognition quality
has not passed validation. Ready infrastructure does not mean validated
recognition. This package does not present the baseline as an accuracy
improvement, and the 2B model has not been finetuned for these recordings.

## Install on Windows

Requires Python 3.12, an NVIDIA CUDA GPU with a compatible driver, and sufficient
disk space for the official model snapshot. The development machine used 6 GB
VRAM; large inputs can still exceed memory or the processing deadline. CPU
fallback is deliberately disabled.

Run from the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File training/qwen/bootstrap.ps1 -DownloadModel
```

This creates `training/.venv`, installs CUDA PyTorch and inference dependencies,
then downloads the official Hugging Face snapshot to `training/qwen/base`.
Downloading uses the network and does not read or upload project media. The
model is pinned to revision `89644892e4d85e24eaac8bacfd4f463576704203` of
`Qwen/Qwen3-VL-2B-Instruct`; weight checksums are verified. Interrupted downloads
can be resumed by rerunning the download command:

```powershell
training/.venv/Scripts/python.exe training/qwen/download_model.py
```

After setup, inference loads local files only and disables outbound network
connections within the inference process. Do not commit the downloaded snapshot
or local recordings.

## Run

The backend must invoke the worker with the Python interpreter from
`training/.venv`; the worker implements a line-delimited JSON stdin/stdout
protocol. Model logs go to stderr.

```powershell
training/.venv/Scripts/python.exe training/qwen/quick_inference.py --worker
```

The first stdout message announces readiness. Each request contains `id`, an
absolute local `path`, and optionally `budget_sec` (up to 240 seconds). A reply
contains the same `id`, `ok`, and either `result` or an explicit error. The current
source validator accepts a single-stream MOV recording up to 180 seconds and
64 MiB. The backend is responsible for accepting and storing uploads locally.

For a direct local check, choose a new output directory:

```powershell
training/.venv/Scripts/python.exe training/qwen/quick_inference.py --videos C:/local/video.mov --output C:/local/new-analysis
```

Results include evidence images and must remain local. An incomplete run is an
error, not a "no violations" verdict.

`runtime_selection.py` permits only the native 2B engine. Optional local
`runtime_selection.json` may set `pixel_cap`; the default remains `null`, which
preserves the native engine's existing per-call pixel budgets. An optional
3145728 cap can reduce memory use but changes the model input and requires its
own evaluation; it is not configured automatically. Other engines or model names fail explicitly instead of silently
switching behavior. `source_snapshot.json` records the copied source hashes.
