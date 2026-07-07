# 🚂 Настройка Railway — по шагам

Пошаговая инструкция, чтобы запустить бота на Railway и он работал 24/7 без твоего компьютера.

---

## Что понадобится

- Аккаунт на [GitHub](https://github.com) (если ещё нет).
- Код проекта в репозитории на GitHub (запушен).
- Токен бота от [@BotFather](https://t.me/BotFather) в Telegram.

---

## Шаг 1: Проект в GitHub

1. Если проект ещё не в Git:
   ```bash
   cd /путь/к/slashbot
   git init
   git add .
   git commit -m "Initial commit"
   ```
2. На GitHub создай новый репозиторий (например `slashbot`), не добавляй README (если папка уже с файлами).
3. Подключи его и запушь:
   ```bash
   git remote add origin https://github.com/ТВОЙ_ЛОГИН/slashbot.git
   git branch -M main
   git push -u origin main
   ```

**Важно:** В репозиторий не должен попасть файл с настоящим токеном. Лучше в `config.py` оставить только `os.getenv('BOT_TOKEN', '')` и токен задавать только в Railway (см. ниже). Или убедись, что `config.py` в `.gitignore` и в репо лежит только `config.example.py`.

---

## Шаг 2: Регистрация в Railway

1. Открой [railway.app](https://railway.app).
2. Нажми **Login** → **Login with GitHub**.
3. Разреши Railway доступ к GitHub (можно только к выбранным репозиториям).

---

## Шаг 3: Новый проект из GitHub

1. В Railway нажми **New Project**.
2. Выбери **Deploy from GitHub repo**.
3. Если репозиторий не виден — нажми **Configure GitHub App** и выдай доступ к репозиторию `slashbot` (или ко всем).
4. Выбери репозиторий **slashbot** и подтверди.

Railway подхватит проект, увидит `requirements.txt` и начнёт первый деплой. Пока без токена бот не заработает — добавим его дальше.

---

## Шаг 4: Добавить переменную BOT_TOKEN

1. В проекте Railway открой созданный **сервис** (один блок с названием репозитория).
2. Перейди на вкладку **Variables** (или **Variables** в левом меню сервиса).
3. Нажми **+ New Variable** или **Add Variable**.
4. Укажи:
   - **Variable:** `BOT_TOKEN`
   - **Value:** твой токен от @BotFather (например `8219794012:AAH...`).
5. Сохрани (Enter или кнопка добавления).

После сохранения Railway перезапустит деплой с новой переменной.

---

## Шаг 5: Команда запуска и тип сервиса

В репозитории **Procfile** уже настроен на один сервис «бот + веб»:

```text
web: python start_both.py
```

Railway (Railpack) подхватывает его автоматически. **Start Command** вручную менять не нужно.

| Что | Значение |
|-----|----------|
| Тип сервиса | **Web** (слушает `PORT` для healthcheck) |
| Старт | `python start_both.py` |
| Главный поток | Telegram-бот (`run_polling`) |
| Фоновый поток | Flask-веб-панель на `PORT` (по умолчанию 8080 на Railway) |

Переменные для веб-панели (опционально, но рекомендуется в интернете):

| Variable | Назначение |
|----------|------------|
| `BOT_TOKEN` | Токен от @BotFather (**обязательно**) |
| `WEB_USER` | Логин для Basic Auth веб-панели |
| `WEB_PASSWORD` | Пароль для веб-панели |

Опционально — мемы через OpenAI (см. [MEME_REPLIES.md](MEME_REPLIES.md)):

| Variable | Назначение |
|----------|------------|
| `OPENAI_API_KEY` | Ключ OpenAI — LLM-генерация мемов |
| `MEME_LLM_MODEL` | Модель (по умолчанию `gpt-4o-mini`) |
| `MEME_LLM_CHANCE` | Доля случайных мемов через LLM, `0.85` |
| `OPENAI_BASE_URL` | Только если не стандартный OpenAI API |

Домен веб-панели: **Settings → Networking → Generate Domain**.

Если нужен **только бот без веба** — Start Command: `python bot.py`, тип **Worker** (без порта).

---

## Шаг 6: Проверить деплой

1. На вкладке **Deployments** последний деплой — **Success** / **Active**.
2. В **Logs** должны быть строки (с Volume на `/data`):
   ```
   Mounting volume on: ...
   [start_both] Данные: /data
   [start_both] bot_users.json: /data/bot_users.json
   💾 Каталог данных: /data
   ✅ LLM: gpt-4o-mini @ ... — ok (...)
   ✅ SP9 works: бот — administrator ...
   🤖 Бот @ag_slashbot запущен!
   🌤️ S:P9 послеобеденный мем (ПН-ПТ): в 15:00 МСК
   🌐 Веб-панель: http://0.0.0.0:8080
   ```
3. **Не должно быть** после «Бот запущен» строки `[start_both] Ошибка бота`.
4. В Telegram: `/start` у [@ag_slashbot](https://t.me/ag_slashbot) — бот отвечает.

Если в логах `[start_both] Данные: /app` — см. **Шаг 7** (Volume).

Если в логах ошибка про токен — проверь `BOT_TOKEN` без пробелов.

---

## Шаг 7: Volume `/data` (обязательно для продакшена)

Без Volume `bot_users.json` и история мемов **стираются при redeploy**.

### 7.1. Добавить Volume

1. Сервис **slashbot** → вкладка **Volumes**.
2. **Add Volume**.
3. **Mount Path:** `/data`.
4. Сохрани.

### 7.2. Variable

**Variables** → добавь:

| Variable | Value |
|----------|--------|
| `SLASHBOT_DATA_DIR` | `/data` |

### 7.3. Redeploy и проверка

1. **Deployments** → **Redeploy**.
2. В Logs: `[start_both] Данные: /data`.
3. Напиши боту / в S:P9 → ещё раз Redeploy → `👥 Загружено чатов: N` (не «создается новый»).

**Пошагово с картинками симптомов:** [OPERATIONS.md](OPERATIONS.md) → Volume `/data`.

---

## Шаг 8: (По желанию) Не светить токен в коде

Сейчас в `config.py` может быть запасной токен в `os.getenv('BOT_TOKEN', '...')`. На Railway используется переменная окружения, но в репозитории лучше не хранить реальный токен:

1. В `config.py` оставь только:
   ```python
   BOT_TOKEN = os.getenv('BOT_TOKEN', '')
   ```
2. Убедись, что в GitHub запушен вариант без токена (или что `config.py` в `.gitignore` и в репо только `config.example.py`).

Локально токен можно подставлять через `.env` или вручную в `config.py` (файл не коммитить).

---

## Краткий чеклист

| Шаг | Действие |
|-----|----------|
| 1 | Код в GitHub |
| 2 | Войти на railway.app через GitHub |
| 3 | New Project → Deploy from GitHub repo → выбрать `slashbot` |
| 4 | Variables → `BOT_TOKEN` (+ `WEB_USER` / `WEB_PASSWORD`; `OPENAI_API_KEY`; `SLASHBOT_DATA_DIR=/data`) |
| 5 | **Volumes** → mount `/data` → Redeploy |
| 6 | Procfile уже `web: python start_both.py` — ничего не менять |
| 7 | Deployments + Logs → `Данные: /data`, `🤖 Бот @ag_slashbot запущен!`; `/start` в Telegram |
| 8 | @BotFather → Group Privacy **OFF** для S:P9 (или бот — админ группы) |

Полный ops-гайд: **[OPERATIONS.md](OPERATIONS.md)**.

---

## Если что-то пошло не так

### Сборка: `No GitHub artifact attestations found for python@...`

Railpack ставит Python через **mise**. Для старых версий (например 3.12.7) attestations могут отсутствовать.

**Решение в репозитории:** файл `mise.toml`:

```toml
[settings]
python.github_attestations = false
```

**Альтернатива:** в Railway Variables → `MISE_PYTHON_GITHUB_ATTESTATIONS=false`.

---

### Старт: `Command 'паша' is not a valid bot command`

Telegram принимает в `CommandHandler` только **латиницу**, цифры и `_`. Кириллические команды (`/паша`, `/привет`) нельзя регистрировать через `CommandHandler`.

- `/pasha` — через `CommandHandler("pasha", ...)`
- `/паша` и прочая кириллица — через `handle_any_command` в `bot.py`

---

### Бот молчит, но веб-панель работает: `set_wakeup_fd only works in main thread`

Симптом: в логах есть `🌐 Веб-панель`, но сразу после `🤖 Бот запущен!` — `[start_both] Ошибка бота` и `set_wakeup_fd only works in main thread`.

**Причина:** `application.run_polling()` нельзя вызывать из фонового потока.

**Как устроено сейчас** (`start_both.py`):

- **главный поток** — `bot.main()` (polling);
- **daemon-поток** — Flask на `PORT` (healthcheck Railway).

Не возвращай бота в фоновый поток без `stop_signals=()` в `run_polling`.

---

### Сервис «живой», бот не отвечает

1. Открой **Logs**, не только статус деплоя — Flask может работать, а поток бота упасть.
2. Проверь `BOT_TOKEN` в Variables.
3. Убедись, что задеплоен последний коммит из `main` (Redeploy при необходимости).

---

### Conflict: terminated by other getUpdates request

Два процесса с одним `BOT_TOKEN` одновременно делают polling.

**Что делать:**

1. Останови локальный бот (`Ctrl+C` или `./start_bot.sh` не запускай параллельно с Railway).
2. На Railway: **Settings → Replicas = 1** (в репо есть `railway.toml` с `numReplicas = 1`).
3. При деплое старый контейнер может жить 1–2 мин — бот сам завершится после 8 Conflict подряд.
4. `start_both.py` держит файловую блокировку `.bot.lock` — второй локальный запуск сразу упадёт.

---

### LLM meme failed: HTTP 400

При старте бот пишет `✅ LLM: …` или `⚠️ LLM: HTTP 400 …` с телом ошибки.

| Причина | Решение |
|---------|---------|
| Неверный ключ | Variables → `OPENAI_API_KEY` |
| Неверная модель | `MEME_LLM_MODEL=gpt-4o-mini` |
| Неверный URL | `OPENAI_BASE_URL=https://api.openai.com/v1` (без `/chat/completions` на конце) |
| Модель без temperature | бот повторит запрос без temperature автоматически |

---

### Данные сбрасываются после redeploy

См. **Шаг 7** выше и **[OPERATIONS.md](OPERATIONS.md)** — Volume mount `/data`, Variable `SLASHBOT_DATA_DIR=/data`.

---

### S:P9 works: бот не видит сообщения / нет истории для мемов

При старте смотри лог: `✅ SP9 works: бот — administrator` или предупреждение.

**Исправление (одно из двух):**

1. @BotFather → **Group Privacy → Turn off**
2. Назначить @ag_slashbot **администратором** группы S:P9 works

---

### Прочее

- **"Application failed to respond":** сервис Web без процесса на `PORT`. Используй `start_both.py` или `web_app.py`, не голый `bot.py` на Web-сервисе.
- **Нет репозитория в списке:** GitHub App для Railway → доступ к `slashbot`.
- **Сервис offline / REMOVED:** **Deploy the repo** или push в `main` для автодеплоя.

---

## Текущий прод

| Параметр | Значение |
|----------|----------|
| Репозиторий | [lx-grzdv/slashbot](https://github.com/lx-grzdv/slashbot) |
| Платформа | Railway, проект `abundant-optimism` / сервис `slashbot` |
| Бот в Telegram | [@ag_slashbot](https://t.me/ag_slashbot) |
| Запуск | `Procfile` → `python start_both.py` |

После успешной настройки бот работает на серверах Railway без твоего компьютера.
