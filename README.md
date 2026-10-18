# aikyn-vision
Aikyn Vision — video event review interface for Datathon 2026.

## Connected local application

The main upload flow is **browser → Java API → FastAPI → local Qwen worker →
JSON events with source timecodes → browser**. The frontend remains on port
8080. This integration keeps the team's existing legacy backend available;
`scripts/service.py` uses it unless `ANALYZER_BACKEND=qwen` is explicitly set.
The launcher below selects the local Qwen path.

**Recognition is still experimental.** This release selects the local native
Qwen3-VL-4B pipeline, revision `native-sequence-refine-v14-room-door-detail`,
with a 3,145,728-pixel input cap. It retains local temporal review and adds the
room-door observation path. Other experimental engines are not registered.
Recent recognition checks covered two development recordings; they do not
establish dataset accuracy or timestamp accuracy. False positives and missed
events remain possible. A ready server or passing contract test does not mean
that video findings are accurate. No finetuning or accuracy percentage is claimed.

### First setup on Windows

Requires Python 3.12, Java 21+, an NVIDIA GPU with a CUDA-compatible driver,
and local model files. No videos or credentials are distributed with this repo.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-api.txt
Set-Location backend
.\mvnw.cmd -Dmaven.compiler.proc=full package -DskipTests
Set-Location ..
.\training\qwen\bootstrap.ps1 -DownloadModel -Model 4b
.\START_AIQYN_VISION.ps1 -Action preflight
.\START_AIQYN_VISION.ps1
.\START_AIQYN_VISION.ps1 -Action status
```

Downloading the official model is a separate setup step; the startup script
does not download weights or train a model. See [model setup](training/qwen/README.md).
Wait for `ready: true`, then open **http://127.0.0.1:8080**. The launcher creates
a private API key in `.runtime/quick-local/api-key.txt`. If automatic local
connection is unavailable, leave the server address empty in the website's
settings and paste that key. Never publish this file.

Upload a MOV file (maximum 64 MiB and 180 seconds). The API returns a job ID,
then the frontend polls for completion and shows possible events and timecodes.
Incomplete processing and timeouts return errors, not a successful clean result.
Only one analysis runs at a time; retry a request receiving HTTP 429 later.

```powershell
.\START_AIQYN_VISION.ps1 -Action stop
```

The launcher is Windows-only and manages only its own recorded processes.
Stop a previous launch before starting another copy on ports 8080/8001.
The existing Docker/legacy workflow is unchanged; CUDA Qwen is not automatically
enabled inside the old Docker containers.

`training/annotation` contains optional review-page sources from the UI update.
They require the separately prepared local dataset/review service and are not
part of the new-file upload flow. No private dataset is embedded in the repo.

### Validation

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-test.txt
.\.venv\Scripts\python.exe -m pytest scripts/tests training/qwen -q
Set-Location frontend
node --test tests/api-contract.test.cjs
Set-Location ..
```

The publication includes Python bridge and model-orchestration tests, targeted
Java contract tests and frontend API tests. They use synthetic inputs and do not
measure recognition accuracy. The two-recording development check is not an
independent accuracy evaluation. Real model weights and private recordings remain
local. The prepared package has not been installed from scratch on a second
computer.

### Regulatory explanations

Each existing candidate receives curated legal context after evidence validation.
The [14-category catalogue](docs/regulatory-catalog.md) includes documents,
paragraphs, official links and conditions; the [JSON catalogue](rules/regulatory_reference_catalog.json)
is available for the team. Source text was checked on 2026-10-18. The catalogue
does not create detections or claim that all 14 categories are recognized.
Internal-policy and unknown-content cases remain explicitly unestablished.
The existing frontend displays the explanation and applicable conditional reference.
