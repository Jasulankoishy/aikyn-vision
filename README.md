# aikyn-vision

## Для сдачи Datathon: ссылки, ключ и запуск

**Публичный адрес ещё не зафиксирован. Сначала получите и проверьте его по инструкции ниже. `127.0.0.1` и `localhost` доступны только на компьютере, где запущен сервис, и не подходят для формы жюри.**

| Поле формы | Что указать |
| --- | --- |
| Git Link | https://github.com/Jasulankoishy/aikyn-vision |
| Web interface URL | Полный публичный HTTPS-адрес, полученный после запуска туннеля и проверки сайта. Пока не заполнен. |
| API base URL | Тот же публичный адрес, если сайт и API обслуживаются одним сервером. Без `/#/results` и без `/api/v1/analyze`. Пока не заполнен. |
| API key for the jury | Действующий ключ именно опубликованного экземпляра: для локального Qwen — из `.runtime/quick-local/api-key.txt`; для Docker — значение `APP_API_KEY`. Передать жюри приватно. |
| Team name | Название команды в точности как на официальном сайте. Название продукта не заменяет название команды. |
| Full names and state IDs | ФИО и ИИН участников заполнить непосредственно в форме; в репозиторий не добавлять. |
| Team Leader's Telegram Username | Telegram капитана в формате `@username`. |
| Presentation / Additional materials | Приложить готовые материалы команды; каждый файл до 100 MB по условиям формы. |

Форму отправляет только капитан. Адрес электронной почты выбирается в его Google-аккаунте.

**Any comments — текст для копирования:**

> Aikyn Vision — анализ видео кассовых операций с помощью локальной модели Qwen. Загрузка видео, автоматическое выделение подозрительных эпизодов, таймкоды, исходные кадры и нормативные пояснения. Результаты требуют проверки человеком; ошибки распознавания и пропуски возможны.

### Вариант 1: публичная ссылка на уже работающий локальный Qwen

В корне установленного проекта проверьте состояние:

```powershell
.\START_AIQYN_VISION.ps1 -Action status
```

Дождитесь `ready: true` и проверьте сайт http://127.0.0.1:8080. Если сервис ещё не запущен, сначала выполните установку из раздела запуска ниже и `START_AIQYN_VISION.ps1`.

После установки `cloudflared` откройте отдельный терминал:

```powershell
cloudflared tunnel --url http://127.0.0.1:8080
```

Скопируйте **реальный** адрес `https://…trycloudflare.com` из вывода. Многоточие здесь — обозначение адреса, а не готовая ссылка для формы. Эта команда открывает внешний доступ к работающему сервису; она не запускает и не меняет модель. В публичном интерфейсе введите ключ в настройках, если автоматическое локальное подключение недоступно.

Компьютер, сервис и процесс туннеля должны работать всё время проверки жюри. Quick Tunnel предназначен для временных проверок: при его остановке ссылка перестаёт работать, при новом запуске адрес меняется; гарантии доступности нет. [Официальная инструкция Cloudflare](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/).

### Вариант 2: команды Docker, если запускает другой участник

Этот вариант относится к `docker-compose.yml` в опубликованном репозитории. `C:\Users\werty\...` — путь на компьютере конкретного участника; замените его своим путём к клону, где находится `docker-compose.yml`. Требуется работающий Docker.

**В существующем Compose используется старый анализатор: `ANALYZER_BACKEND=qwen` и CUDA Qwen там автоматически не включаются. Публичная ссылка из Docker сама по себе не означает, что работает проверенный Qwen. Для текущего локального Qwen используйте вариант 1.**

```powershell
Set-Location 'C:\ПУТЬ_К_ВАШЕМУ_КЛОНУ\aikyn-vision'
$env:APP_API_KEY = Read-Host 'Введите приватный ключ этого Docker-экземпляра'
docker compose --profile tunnel up -d --build
docker compose --profile tunnel logs tunnel | Select-String 'trycloudflare'
```

`Set-Location` открывает папку проекта; `APP_API_KEY` задаёт ключ API; `up -d --build` собирает и запускает контейнеры. **Нужен `--profile tunnel`: обычный `docker compose up -d --build` не запускает сервис `tunnel`.** Последняя команда показывает строку с публичным адресом. Второй сервер на уже занятом порту 8080 не запустится; не переключайте работающий экземпляр во время анализа.

### Проверка перед отправкой формы

1. Откройте публичный адрес с другого устройства или через мобильный интернет. В настройках укажите ключ именно этого сервера.
2. Проверьте `GET /readyz` с заголовком `X-API-Key`: ожидаются HTTP 200 и `ready: true`.
3. Загрузите разрешённый тестовый MOV через публичный сайт и дождитесь результата. Проверьте таймкод и открытие исходного видео. Отдельно проверьте контрольный ролик без ожидаемого события.
4. Внесите проверенный публичный адрес в оба поля формы. Если сайт и API размещены отдельно, укажите их разные проверенные адреса. При смене адреса туннеля обновите форму.

**Маршруты API:** `POST /api/v1/analyze` (`multipart/form-data`, поле `file`) и `GET /api/v1/jobs/{job_id}`. Авторизация: заголовок `X-API-Key`. Не вставляйте ключ в URL, README или публичный исходный код. Публикация репозитория на GitHub не разворачивает работающий сервер.

---


Aikyn Vision — video event review interface for Datathon 2026.

## Connected local application

The main upload flow is **browser → Java API → FastAPI → local Qwen worker →
JSON events with source timecodes → browser**. The frontend remains on port
8080. This integration keeps the team's existing legacy backend available;
`scripts/service.py` uses it unless `ANALYZER_BACKEND=qwen` is explicitly set.
The launcher below selects the local Qwen path.

**Recognition is still experimental.** This release selects the local native
Qwen3-VL-4B pipeline, revision `native-sequence-refine-v15-fourteen-categories`,
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
