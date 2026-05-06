# notes-bot

![version](https://img.shields.io/badge/version-0.14.0-blue)

Telegram-бот для персональных заметок: принимает текст, голос, видео, документы,
форварды; транскрибирует медиа, извлекает текст из файлов (txt/md/csv/pdf/docx),
классифицирует через GPT-4o, сохраняет готовые страницы в
[Notion](https://www.notion.so/) (по умолчанию) или [Buildin](https://buildin.ai) —
переключатель `NOTES_PROVIDER=notion|buildin`.

Бот заточен под личный workflow автора: набор workspace'ов, типов заметок и
DB-properties — это **реф-пример**, не «единственный правильный дефолт».
Если форкаешь под себя — отредактируй `bot/domain/workspaces.py` и
`bot/domain/note_types.py` (см. раздел «[Под себя](#под-себя)» ниже).

> Эволюция: отдельные ветки и Conventional-Commits-PR в `main`
> (см. `AGENTS.md`).

## Что умеет (на 0.11.0)

- Принимает **текст, голосовые, аудио, видео, видео-кружочки, документы,
  форварды**.
- Голос/аудио/видео транскрибируется через **AssemblyAI Universal-2** с
  диаризацией спикеров. Сырой транскрипт остаётся в БД (промежуточный шаг),
  в провайдер уходит только готовая заметка после LLM. Без
  `ASSEMBLYAI_API_KEY` — голосовые отключены, бот отвечает «транскрибация
  выключена».
- **Документы** (`txt`, `md`, `csv`, `pdf`, `docx`) — прямой upload или форвард.
  Текст извлекается локально (`pypdf` для PDF, `python-docx` для DOCX, stdlib
  для остальных) и идёт в тот же LLM-pipeline. Лимит — 20 МБ (Telegram bot API).
  Длинные файлы (>40k символов после извлечения) проходят **map-reduce**:
  бьются на куски, каждый кусок суммаризуется отдельным LLM-вызовом, итоговая
  склейка классифицируется как обычно. Зашифрованные/сканированные PDF без
  текстового слоя помечают draft `failed` с понятным сообщением.
- Для форвардов извлекаются метаданные (автор, канал, дата, подпись,
  оригинальный message_id) и подаются в LLM как контекст-prefix
  `[Forwarded] От: …; Когда: …`. Draft помечается `kind=forward`.
- Создаёт черновик в SQLite **до** любой обработки (durability-контракт).
- **Один GPT-4o-вызов**: классифицирует **тип заметки** и **workspace**
  (наборы заданы в реестрах `bot/domain/note_types.py` и
  `bot/domain/workspaces.py` — в текущем реф-сетапе 7 типов: note / task /
  idea / meeting / 1on1 / work / personal, и 5 workspace'ов: personal /
  work / family / growth / ai_path), извлекает properties (Status,
  Priority, DueDate, Tags, Attendees, …) и форматирует тело как markdown
  под template типа. Для `meeting` отдельно различает регулярные синки
  команды через `extras.kind="sync"`: для sync LLM кладёт всю иерархию
  (по людям/зонам/темам) прямо в `markdown_body` через `### subheading` +
  bullets — шаблон passthrough, без дублирующих секций. Для классического
  `meeting` (kind=meeting) — секции Agenda / Decisions / Action items.
  Для `task` описание задачи (контекст, мотивация) пишется в `markdown_body`
  перед `## Чек-лист`. Для `meeting` / `1on1` LLM проставляет дату в
  `properties.Date` и в title в скобках `(YYYY-MM-DD)`. Без
  `OPENAI_API_KEY` — stub-fallback (тип `note`, workspace `personal`,
  тело = исходник).
- Превью с кнопками: `💾 Save` / `✖ Cancel` сверху, `🔁 Type` /
  `📁 Workspace` ниже. Для type=meeting добавляется ряд
  `🔄 Sync ↔ Meeting` для ручного переключения подвида; рядом с типом
  показывается метка `(sync)` если kind=sync. Workspace и тип можно
  переопределить вручную.
- На Save — кладёт в outbox-очередь, фоновой воркер вызывает API провайдера
  (Buildin или Notion в зависимости от `NOTES_PROVIDER`).
- **Routing**: per-(workspace × type) для Buildin (`BUILDIN_DB_<WS>_<TYPE>` →
  `BUILDIN_DB_<TYPE>` → `BUILDIN_DB_DEFAULT`); для Notion та же цепочка
  (`NOTION_DB_<WS>_<TYPE>` → `NOTION_DB_<TYPE>` → `NOTION_DATABASE_ID`) **+
  lazy two-step auto-create** под `NOTION_PARENT_PAGE_<WS>` если ничего не
  задано — бот создаёт wrapper-page (`📝 Заметки` / `✅ Задачи` / …) и
  внутри неё full-page DB при первом hit, кэширует database_id в `notion_dbs`.
  Структура зеркалит Buildin (`parent → 📝 Заметки → DB`). Без токена
  провайдера — stub-режим.
- Markdown тела заметки конвертируется в provider-specific blocks (параграфы,
  заголовки `#`/`##`/`###`, списки `-`/`1.`, цитаты `>`, code-fences ` ``` `).
  Для Buildin длинные заметки (>100 блоков) дописываются чанками по 100
  через `PATCH /v1/blocks/{page_id}/children`.
- На успех — атомарно `idempotency.insert + drafts.delete + outbox.delete`.
  Превью редактируется в «✅ Сохранено в Buildin/Notion».
- На ошибку — экспоненциальный backoff. После `MAX_ATTEMPTS` черновик
  помечается `failed`, остаётся видимым через `/list`.
- При `NOTES_PROVIDER=buildin` бот на старте делает health-check
  (`GET /v1/users/me`) и предупреждает о незаданных
  `BUILDIN_SPACE_<WS>` env'ах.
- Команды: `/start`, `/help`, `/list`, `/retry`.
- На старте: восстановление черновиков, застрявших в `saving` дольше 5 минут.

## Подключение Buildin

### 1. Integration

В Buildin: settings → integrations → создать новую integration. Скопировать
токен → `BUILDIN_TOKEN` в `.env`.

### 2. Spaces (workspace'ы)

В реф-сетапе настроены 5 workspace'ов: `personal`, `work`, `family`,
`growth`, `ai_path` (см. `bot/domain/workspaces.py` — там же поля
`label`, `description`, `space_env`). Если форкаешь под себя — поправь
реестр и env-vars из таблицы ниже соответственно. Под каждый workspace
нужен отдельный Buildin space. Создайте space'ы руками, разрешите для
них integration, скопируйте UUID:

| Workspace | Env var |
|---|---|
| `personal` (Личное) | `BUILDIN_SPACE_PERSONAL` |
| `work` (Работа) | `BUILDIN_SPACE_WORK` |
| `family` (Семья) | `BUILDIN_SPACE_FAMILY` |
| `growth` (Куда расти?) | `BUILDIN_SPACE_GROWTH` |
| `ai_path` (Путь ИИ) | `BUILDIN_SPACE_AI_PATH` |

### 3. Базы (databases)

Внутри каждого space скрипт создаёт отдельную **страницу-обёртку** на каждый
тип заметки. Title берётся из plural-формы реестра типов (в реф-сетапе:
`📝 Заметки`, `✅ Задачи`, `💡 Идеи`, `🤝 Митинги`, `👥 1:1`, `💼 Рабочее`,
`🌱 Личное` — см. `_PLURAL_TITLES` в скрипте) — без префикса воркспейса,
так как имя space'а уже задаёт контекст. Внутри страницы — full-page DB
с тем же title. Структура в Buildin:

```
space «Работа»
├── page «✅ Задачи»
│   └── DB ✅ Задачи
├── page «📝 Заметки»
│   └── DB 📝 Заметки
└── …
```

Можно создать руками (тогда скопируйте UUID DB из URL в `BUILDIN_DB_<WS>_<TYPE>`),
либо запустить автосоздание:

```bash
source .venv/bin/activate
python -m scripts.setup_buildin_dbs >> .env
```

Скрипт уважает уже заданные env'ы — заполняет только пустые slot'ы.
Доп. флаги: `--dry-run` (без сетевых вызовов), `--workspace=<key>`,
`--type=<key>` (только конкретный workspace или тип).

Если у вас остались DB, созданные старой версией скрипта (лежат прямо в
корне space, без page-обёртки), они продолжат работать — env-vars у них
уже заполнены, скрипт их пропускает. Чтобы получить однородную структуру,
удалите соответствующие `BUILDIN_DB_<WS>_<TYPE>` из `.env`, удалите DB в
Buildin UI и перезапустите скрипт.

Кроме перечисленных свойств бот всегда дописывает `CreatedAt` (date) — оно
создаётся скриптом автоматически.

### 4. Переключатель провайдера

`NOTES_PROVIDER=buildin` включает Buildin sink. Дефолт `notion` — для
переключения на Buildin поставьте `NOTES_PROVIDER=buildin`.

## Подключение Notion (default)

### 1. Интеграция

Один Notion workspace на все воркспейсы бота — **один** Internal Integration
на https://www.notion.so/my-integrations → токен в `NOTION_TOKEN`.

Если бот-воркспейсы лежат в **разных Notion workspaces** (top-level
workspaces в Notion, не страницы), на каждый создать свой Internal
Integration и заполнить per-WS токен `NOTION_TOKEN_<WS>` в `.env`. Если
для воркспейса задан `NOTION_TOKEN_<WS>` — он имеет приоритет; иначе
используется глобальный `NOTION_TOKEN`.

```
NOTION_TOKEN=...               # глобальный fallback (один Notion workspace на всё)
NOTION_TOKEN_PERSONAL=...      # опционально — per-WS, если ws в отдельном Notion workspace
NOTION_TOKEN_WORK=...
NOTION_TOKEN_FAMILY=...
NOTION_TOKEN_GROWTH=...
NOTION_TOKEN_AI_PATH=...
```

### 2. Резолв DB id и lazy two-step auto-create

Бот ищет database для пары `(workspace, type)` по цепочке:

```
notion_dbs (SQLite cache)
  → NOTION_DB_<WS>_<TYPE>     (env, например NOTION_DB_WORK_TASK)
  → NOTION_DB_<TYPE>          (per-type, без workspace-разреза)
  → NOTION_DATABASE_ID        (глобальный fallback)
  → two-step auto-create под NOTION_PARENT_PAGE_<WS>:
      pages.create (wrapper-page «📝 Заметки» / «✅ Задачи» / …) →
      databases.create (full-page DB внутри wrapper).
    database_id кэшируется в notion_dbs.
```

Любой первый результат — финальный. Auto-create зеркалит структуру Buildin:
`parent-page → 📝 Заметки → DB`.

### 3. Lazy auto-create (рекомендуется)

Минимальный setup без ручного создания 35 баз. Создаёшь **по одной пустой
top-level странице** в каждом Notion workspace — она будет parent для
воркспейса бота. Расшарить страницу с integration — все вложенные
(wrapper-page и DB) наследуют доступ.

```
(Notion workspace «Личное»)
└── Notes-bot          ← parent-page (расшарена с integration)
    ├── 📝 Заметки     ← wrapper-page (создаст бот при первом hit)
    │   └── DB 📝 Заметки   ← full-page DB (туда летят страницы заметок)
    ├── ✅ Задачи
    │   └── DB ✅ Задачи
    └── …
```

ID каждой parent-страницы (32-hex из URL) → в `.env`:

```
NOTION_PARENT_PAGE_PERSONAL=...
NOTION_PARENT_PAGE_WORK=...
NOTION_PARENT_PAGE_FAMILY=...
NOTION_PARENT_PAGE_GROWTH=...
NOTION_PARENT_PAGE_AI_PATH=...
```

При первом сохранении в `(workspace × type)` бот создаст wrapper-page с
plural-title типа (`📝 Заметки` и т.п.) под parent-страницей, внутри неё —
full-page DB со схемой типа из реестра (`note_types.py`), и закэширует
database_id в SQLite. Структура растёт по факту использования — пустые
комбинации не плодятся. Workspace, для которого `NOTION_PARENT_PAGE_<WS>`
не задан, фолбэкнется на `NOTION_DB_<TYPE>` или `NOTION_DATABASE_ID`.

### 4. Ручное создание баз (опционально)

Если хочется контролировать схему — создавай руками. Schema ниже — реф-пример
из текущего `bot/domain/note_types.py`. Если редактируешь реестр, эта
таблица перестанет соответствовать твоей конфигурации:

| Тип | Env var (per-type) | Required properties (имя — kind) |
|---|---|---|
| `note` | `NOTION_DB_NOTE` | Name (title), Tags (multi_select) |
| `task` | `NOTION_DB_TASK` | Name (title), Status (select), Priority (select), DueDate (date) |
| `idea` | `NOTION_DB_IDEA` | Name (title), Tags (multi_select) |
| `meeting` | `NOTION_DB_MEETING` | Name (title), Attendees (multi_select), Date (date) |
| `1on1` | `NOTION_DB_1ON1` | Name (title), With (rich_text), Date (date) |
| `work` | `NOTION_DB_WORK` | Name (title), Tags (multi_select) |
| `personal` | `NOTION_DB_PERSONAL` | Name (title), Tags (multi_select) |

Per-(workspace × type): `NOTION_DB_<WS>_<TYPE>` (например
`NOTION_DB_WORK_TASK`). Имеет высший приоритет среди env. Бот всегда
дописывает `CreatedAt` (date) — auto-create добавляет это поле сам.

### 5. Шаринг

Для каждой базы / родительской страницы: `…` (меню в правом верхнем углу)
→ **Connections** → выбрать integration. Auto-created DB наследуют доступ
от parent-page. Top-level page расшарена один раз — все вложенные DB и
страницы наследуют.

### 6. ID

Скопировать database / page id из URL (32-символьный hex после workspace)
в соответствующую переменную `.env`. Без `NOTION_TOKEN` бот работает в
stub-режиме (логирует payload).

## OpenAI

`OPENAI_API_KEY` в `.env` — включает реальный GPT-4o. Без ключа — stub
(тип `note`, body = raw input). Модель меняется через `OPENAI_MODEL`
(по умолчанию `gpt-4o`).

## Под себя

Реестры в `bot/domain/` — это setup автора. Бот рассчитан на то, что
форкер их отредактирует под свой workflow. Файлы захардкожены не из-за
архитектурного ограничения, а потому что Python-dataclass'ы — самая
понятная форма для одного человека, который сам себе админ.

**Шаг 1.** `bot/domain/workspaces.py` — добавить/удалить/переименовать
записи в `WORKSPACES`. Поля `Workspace`:
- `key` — ASCII-friendly id (попадает в env-имена и LLM-ответ).
- `label` — UI-строка для TG-кнопок (RU/EN/любой).
- `description` — подсказка для LLM, когда выбрать этот workspace.
- `space_env` — имя env-переменной для UUID Buildin space'а.

**Шаг 2.** `bot/domain/note_types.py` — записи в `TYPES`. Поля `NoteType`:
- `key`, `label`, `description` (как у workspace).
- `db_env` — имя env-переменной для per-type Notion DB id (например
  `NOTION_DB_TASK`). Для Buildin берётся суффикс
  (`NOTION_DB_TASK` → `BUILDIN_DB_<WS>_TASK`).
- `template_id` — ключ ветки в `domain/templates.py`.
- `properties` — список колонок DB. Каждая `NotionProperty`: `name`
  (case-sensitive имя колонки), `kind` (`title|rich_text|select|multi_select|date|checkbox`),
  `llm_hint` (что LLM кладёт), `select_options` (для select/multi_select —
  фиксированный список значений; нужен setup-скрипту).

**Шаг 3.** Если меняется `template_id` — добавить ветку в
`bot/domain/templates.py` (рендер markdown под этот тип).

**Шаг 4.** Адаптировать тесты: `tests/test_workspaces.py` и
`tests/test_note_types.py` (а при правке templates — частично
`tests/test_templates.py`) проверяют конкретный набор ключей. После
кастомизации обновить тесты под новый набор — это разрешённое исключение
(см. `CLAUDE.md`, «исключения, когда тест разрешено менять»).

**Шаг 5.** Перегенерировать DB: удалить устаревшие
`BUILDIN_DB_<WS>_<TYPE>` из `.env`, удалить старые DB в Buildin UI,
запустить:
```bash
source .venv/bin/activate
python -m scripts.setup_buildin_dbs >> .env
```
Скрипт читает реестры — создаст DB под обновлённый набор.

**Шаг 6.** Прогнать `pytest -v` — всё должно быть зелёным.

Бот всегда дописывает в каждую DB колонку `CreatedAt` (date) автоматически —
объявлять её в `properties` не нужно.

## Стек

- Python 3.11+
- aiogram 3.x — Telegram bot framework
- pydantic-settings + python-dotenv — config через `.env`
- aiosqlite — async-драйвер SQLite
- httpx — async HTTP-клиент для Buildin API (тонкий клиент по openapi)
- notion-client — Python SDK Notion API (legacy fallback провайдер)
- openai — GPT-4o classify+format одним вызовом
- assemblyai — Universal-2 транскрибация + диаризация
- pypdf, python-docx — извлечение текста из PDF/DOCX
- pytest + pytest-asyncio — тесты (`reportlab` — dev-only, для генерации
  тестовых PDF в `test_doc_extractor.py`)
- Docker + docker-compose

## Структура проекта

```
bot/
├── main.py                # entry: init_db → buildin_health_check → recover_stuck → outbox worker → polling
├── config.py              # pydantic settings
├── handlers/
│   ├── inputs.py          # text → draft → LLM → preview
│   ├── voice.py           # voice/audio/video/video_note → download → transcribe → LLM → preview
│   ├── documents.py       # document (txt/md/csv/pdf/docx) → download → extract → LLM → preview
│   ├── callbacks.py       # Save / Type / Cancel + клавиатура выбора типа
│   └── commands.py        # /start /help /list /retry
├── middlewares/
│   └── auth.py            # whitelist Telegram user IDs
├── services/
│   ├── llm_processor.py   # GPT-4o classify+format (один вызов) + map-reduce process_long + stub fallback
│   ├── doc_extractor.py   # txt/md/csv/pdf/docx → plain text (pypdf, python-docx, stdlib)
│   ├── notion_client.py   # compat-shim → sinks/notion.py
│   ├── transcriber.py     # AssemblyAI Universal-2 + диаризация (multi-speaker labels)
│   └── sinks/             # провайдеры хранилища заметок
│       ├── __init__.py    # Sink Protocol
│       ├── _properties.py # общий property builder (shape="notion"|"buildin")
│       ├── notion.py      # NotionSink — pages.create через notion-client (default)
│       ├── buildin.py     # BuildinSink — httpx + Buildin API
│       └── factory.py     # get_sink() по NOTES_PROVIDER
├── domain/
│   ├── note_types.py      # 7 типов с properties + db_env + LLM-hints + select_options
│   ├── workspaces.py      # реестр workspaces (personal/work/family/growth/ai_path)
│   └── templates.py       # per-type markdown шаблоны
├── storage/
│   ├── db.py              # aiosqlite-соединение, WAL, миграции
│   ├── drafts.py          # CRUD черновиков
│   ├── outbox.py          # очередь с экспоненциальным backoff
│   ├── idempotency.py     # dedup draft_id → page_id
│   └── save_tx.py         # атомарный commit_save
├── workers/
│   └── outbox_worker.py   # asyncio task: claim_due → save → commit
├── fsm/                   # FSM-стейты (пока пусто, нужен в Increment 3)
└── utils/
    ├── progress.py        # ProgressReporter
    ├── text_chunking.py
    ├── md_blocks.py       # parse_markdown + markdown_to_blocks (Notion) + markdown_to_blocks_buildin
    ├── forward.py         # извлечение метаданных forward + prefix для LLM
    └── errors.py
scripts/
├── setup_buildin_dbs.py   # авто-создание Buildin DB по реестрам
└── backup_db.sh           # online-backup SQLite + ротация (для cron на VPS)
tests/                     # pytest + pytest-asyncio, in-memory SQLite фикстура
data/                      # SQLite БД (volume в compose)
```

## Как развернуть свой

### Локально

```bash
python3.12 -m venv .venv  # python3.11+ тоже подходит
source .venv/bin/activate
pip install -r requirements-dev.txt

cp .env.example .env
# заполнить BOT_TOKEN и ALLOWED_USER_IDS

python -m bot.main
```

### Docker

```bash
cp .env.example .env
docker compose up --build
```

`docker-compose.yml` ставит `restart: unless-stopped`, лимит памяти `512m`
(хватает для документов, проходящих map-reduce), persistent volume
`./data` → `/app/data` (SQLite-файл живёт между рестартами), healthcheck
`SELECT 1` к БД и ротацию логов (10 МБ × 5 файлов).

### VPS (Ubuntu 22.04 / 24.04)

#### 1. Подготовка сервера (один раз)

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git sqlite3 curl ca-certificates

# Docker Engine + compose plugin
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
    https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
    | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io \
    docker-buildx-plugin docker-compose-plugin

sudo usermod -aG docker $USER  # нужен relogin / `newgrp docker`
```

Минимум железа: 1 vCPU, 1 ГБ RAM, 10 ГБ SSD. Комфортно: 2 vCPU, 2 ГБ.

#### 2. Деплой кода

```bash
sudo mkdir -p /opt/notes-bot && sudo chown $USER:$USER /opt/notes-bot
cd /opt/notes-bot
git clone <repo-url> .
mkdir -p data

# .env заполнить локально (см. разделы «Подключение Buildin / Notion»,
# «OpenAI», «AssemblyAI» выше) и залить:
#   scp .env user@vps:/opt/notes-bot/.env
chmod 600 .env

docker compose up -d --build
docker compose logs -f bot
```

`restart: unless-stopped` поднимает контейнер при ребуте VPS автоматически —
ничего настраивать в systemd не нужно.

#### 3. Бэкап SQLite (cron + ротация)

`scripts/backup_db.sh` делает `sqlite3 .backup` (online, безопасно при
работающем боте через WAL), сжимает `gzip` и удаляет старше `KEEP_DAYS`.

```bash
sudo mkdir -p /var/backups/notes-bot
sudo chown $USER:$USER /var/backups/notes-bot

crontab -e
# добавить строкой:
17 3 * * * /opt/notes-bot/scripts/backup_db.sh >> /var/log/notes-bot-backup.log 2>&1
```

Восстановление: остановить контейнер, распаковать дамп на место БД,
запустить заново.

```bash
docker compose stop bot
gunzip -c /var/backups/notes-bot/notes-YYYYMMDD-HHMMSS.db.gz > data/notes.db
docker compose start bot
```

#### 4. Мониторинг (healthchecks.io)

Создать на [healthchecks.io](https://healthchecks.io) check (free до 20),
скопировать ping URL и в `crontab -e`:

```bash
*/5 * * * * docker inspect --format='{{.State.Health.Status}}' \
    $(docker compose -f /opt/notes-bot/docker-compose.yml ps -q bot) 2>/dev/null \
    | grep -q healthy && curl -fsS --retry 3 https://hc-ping.com/<uuid> > /dev/null
```

Контейнер падает / Docker daemon упал / VPS не поднялся — пинги
прекращаются и через 10 минут healthchecks.io шлёт алерт.

#### 5. Обновление до новой версии

```bash
cd /opt/notes-bot
git pull
docker compose up -d --build
docker compose logs --tail=100 -f bot
```

Откат при несовместимой миграции БД: `git checkout <prev-tag>`,
восстановить БД из бэкапа, `docker compose up -d --build`.

#### Troubleshooting

| Симптом | Причина / фикс |
|---|---|
| Бот молчит на сообщения | `ALLOWED_USER_IDS` не содержит твой TG id (`AuthMiddleware` режет). |
| `Run polling for bot` не появляется | Неверный `BOT_TOKEN` или нет outbound https. |
| На старте лог `BUILDIN_SPACE_<X>=` пуст | Не заданы UUID space'ов — заполнить или ограничить роутинг через `BUILDIN_DB_DEFAULT`. |
| Документ >40k символов падает по OOM | Поднять `deploy.resources.limits.memory` в `docker-compose.yml`. |
| `sqlite3: not found` в backup-скрипте | `sudo apt install sqlite3` на хост. |

## Тесты

```bash
source .venv/bin/activate
pytest -v
```

179 тестов на момент 0.11.0 (23 файла):
- `test_config.py`, `test_auth.py` — конфиг и middleware.
- `test_drafts.py`, `test_outbox.py`, `test_idempotency.py`, `test_save_tx.py` —
  storage-слой (in-memory SQLite через фикстуру `fresh_db`).
- `test_outbox_worker.py` — happy path, retry, idempotency после крэша,
  max_attempts.
- `test_note_types.py`, `test_templates.py`, `test_workspaces.py` — реестры.
  ⚠️ Эти тесты завязаны на конкретный реф-сетап и требуют обновления при
  кастомизации (см. раздел [Под себя](#под-себя)).
- `test_llm_processor.py` — stub + real path с моком OpenAI (включая
  workspace classification + fallback на ошибке и неизвестный тип/workspace).
- `test_handlers_inputs.py`, `test_handlers_callbacks.py` — UX-логика
  (выбор типа + workspace).
- `test_md_blocks.py`, `test_md_blocks_buildin.py` — markdown → blocks для
  Notion и Buildin shapes.
- `test_notion_client.py` — Notion sink: stub/real mode, per-type DB routing,
  multi_select, fallback title, failure-injector.
- `test_buildin_sink.py` — Buildin sink (httpx MockTransport): wire shape,
  workspace × type routing, chunking длинных заметок, error mapping,
  health-check `/v1/users/me`.
- `test_workspace_routing.py` — `settings.database_id_for()` для обоих
  провайдеров.
- `test_sink_factory.py` — `get_sink()` переключение по `NOTES_PROVIDER`.
- `test_sinks_properties.py` — общий property builder для обоих shape'ов
  (`shape="notion"|"buildin"`): title/select/multi_select/date/checkbox,
  пустые значения, неизвестные kind.
- `test_transcriber.py` — диаризация render-with-speakers, disabled-flag.
- `test_handlers_voice.py` — happy path с моками download/transcribe/LLM,
  durability при ошибках.
- `test_forward.py` — извлечение метаданных всех типов forward_origin
  (User/HiddenUser/Chat/Channel) + format_prefix + enrich.
- `test_doc_extractor.py` — txt/md/csv/pdf/docx happy-paths, пустой PDF →
  `EmptyDocumentError`, бинарь без mime → `UnsupportedDocumentError`,
  расширение приоритетнее mime.
- `test_handlers_document.py` — happy path с моками download/extract/LLM,
  oversized/audio/unsupported reject, durability при ошибках, forwarded →
  `kind=forward` + enrich-prefix.

## Настройка `.env`

| Переменная | Назначение |
|---|---|
| `BOT_TOKEN` | Токен Telegram-бота от `@BotFather` |
| `ALLOWED_USER_IDS` | Разрешённые TG user IDs через запятую |
| `DATABASE_PATH` | Путь к файлу SQLite (по умолчанию `data/notes.db`) |
| `NOTES_PROVIDER` | `notion` (default) или `buildin` |
| `BUILDIN_TOKEN` | Токен Buildin integration. Пусто → stub-режим |
| `BUILDIN_SPACE_<WS>` | UUID space'а workspace'а (`PERSONAL`, `WORK`, `FAMILY`, `GROWTH`, `AI_PATH`). Нужны для setup-script |
| `BUILDIN_DB_<WS>_<TYPE>` | Per-(workspace × type) DB id. Заполняется setup-script'ом или руками |
| `BUILDIN_DB_<TYPE>` | Per-type fallback DB id (без workspace-разреза) |
| `BUILDIN_DB_DEFAULT` | Финальный fallback DB id |
| `NOTION_TOKEN` | Глобальный токен Internal Integration Notion. Пусто → stub-режим (если нет ни одного `NOTION_TOKEN_<WS>`) |
| `NOTION_TOKEN_<WS>` | Per-workspace токен (если воркспейс лежит в отдельном Notion workspace). Имеет приоритет над `NOTION_TOKEN`. Optional |
| `NOTION_DATABASE_ID` | Default DB id (финальный fallback для всех типов и workspace'ов) |
| `NOTION_DB_<TYPE>` | Per-type DB id: `NOTE`, `TASK`, `IDEA`, `MEETING`, `1ON1`, `WORK`, `PERSONAL`. Все optional |
| `NOTION_DB_<WS>_<TYPE>` | Per-(workspace × type) DB id, например `NOTION_DB_WORK_TASK`. Высший приоритет среди env. Optional |
| `NOTION_PARENT_PAGE_<WS>` | Parent-page id для lazy two-step auto-create (wrapper-page + DB) конкретного workspace. Если задан — бот создаст структуру при первом сохранении в `(<ws> × type)` и закэширует database_id. Optional |
| `OPENAI_API_KEY` | Ключ OpenAI для GPT-4o classify+format. Пусто → stub |
| `OPENAI_MODEL` | Имя модели (по умолчанию `gpt-4o`) |
| `ASSEMBLYAI_API_KEY` | Ключ AssemblyAI для транскрибации. Пусто → voice/audio/video отключены |
| `ASSEMBLYAI_SPEECH_MODEL` | `universal` (default), `nano` или `slam-1` |
| `FORCE_LANGUAGE_CODE` | `ru`, `en`, …  Пусто → autodetect (ненадёжно для <30 сек) |
| `TEMP_DIR` | Временные файлы для скачанных медиа (по умолчанию `/tmp/notes-bot`) |
