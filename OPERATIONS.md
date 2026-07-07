# Эксплуатация @ag_slashbot — прод, данные, мемы

Краткий справочник для Railway и чата **S:P9 works**. Первичная настройка — [RAILWAY_SETUP.md](RAILWAY_SETUP.md), деплой — [DEPLOY.md](DEPLOY.md).

---

## Содержание

1. [Архитектура на Railway](#архитектура-на-railway)
2. [Volume `/data` — пошагово](#volume-data--пошагово)
3. [Group Privacy и S:P9 works](#group-privacy-и-sp9-works)
4. [Расписание в S:P9 works](#расписание-в-sp9-works)
5. [Файлы данных](#файлы-данных)
6. [Логи при успешном старте](#логи-при-успешном-старте)
7. [Troubleshooting](#troubleshooting)
8. [Переменные окружения](#переменные-окружения)

---

## Архитектура на Railway

| Компонент | Файл | Назначение |
|-----------|------|------------|
| Старт | `start_both.py` | Бот (polling) + Flask на `PORT` |
| Procfile | `web: python start_both.py` | Команда для Railway |
| Данные | `app_data.py` | Каталог `/data`, lock `.bot.lock` |
| Бот | `bot.py` | Telegram, JobQueue, рассылки |
| Мемы | `meme_replies.py` | LLM, история, `meme_state.json` |
| Один инстанс | `railway.toml` | `numReplicas = 1` |

**Важно:** не запускай локально `bot.py` / `start_both.py`, пока бот крутится на Railway — будет `Conflict: getUpdates`.

---

## Volume `/data` — пошагово

Без Volume файлы живут в `/app` и **стираются при каждом redeploy**.

### 1. Открой сервис

Railway → Project → сервис **slashbot**.

### 2. Добавь Volume

1. Вкладка **Volumes** (или **Settings** → Volumes).
2. **Add Volume** / **+ New Volume**.
3. **Mount Path:** `/data` (без слэша в конце).
4. Размер 1 GB достаточно.
5. Сохрани.

### 3. Variable (рекомендуется)

**Variables** → **+ New Variable**:

| Variable | Value |
|----------|--------|
| `SLASHBOT_DATA_DIR` | `/data` |

Код и без неё ищет writable `/data`, но явная переменная надёжнее.

### 4. Redeploy

**Deployments** → **Redeploy** → дождись **Success** / **Active**.

### 5. Проверка

В **Logs** должно быть:

```text
Mounting volume on: /var/lib/containers/railwayapp/...
[start_both] Данные: /data
[start_both] bot_users.json: /data/bot_users.json
💾 Каталог данных: /data
```

**Плохо** (Volume не используется):

```text
[start_both] Данные: /app
👥 Файл чатов не найден, создается новый
```

После каждого redeploy снова «файл не найден» — mount не `/data` или старый деплой.

### 6. Persistence-тест

1. Напиши что-нибудь в S:P9 works или `/start` боту в личку.
2. **Redeploy**.
3. В логах: `👥 Загружено чатов: 1` (не «создается новый»).
4. Если была переписка: `💾 История чатов загружена: 1 чат(ов)`.

---

## Group Privacy и S:P9 works

Плановые мемы и история чата требуют, чтобы бот **видел обычные сообщения** в группе.

### @BotFather

1. `/mybots` → @ag_slashbot → **Bot Settings** → **Groups and Channels**.
2. **Allow Groups** — **ON** (синий).
3. **Group Privacy** — **OFF** (переключатель **слева**, без текста «Receive only messages that mention…»).

### Альтернатива

Назначить @ag_slashbot **администратором** группы S:P9 works.

### Проверка при старте

Бот сам проверяет статус в группе:

```text
✅ SP9 works: бот — administrator, видит все сообщения группы
```

или

```text
⚠️ SP9 works: бот НЕ администратор группы
```

### Проверка в runtime

Напиши в S:P9 **без @** — в Logs Railway:

```text
📨 Получено сообщение: ...
```

Если видны только `/meme` и «Синкуемся?» — Privacy всё ещё мешает.

Подробнее: [SP9_WORKS_CHAT.md](SP9_WORKS_CHAT.md).

---

## Расписание в S:P9 works

| Время (МСК) | Дни | Что |
|-------------|-----|-----|
| **12:00** | ПН–ПТ | «Синкуемся?» |
| **15:00** | ПН–ПТ | Послеобеденный мем (история чата + фокус «полусон / макеты») |
| **18:00** | ПН–ПТ | Вечерний мем |
| **18:00** | Пятница | Отдельный промпт «на выходные / дудосинг» |

Дополнительно (все группы):

| Время | Дни | Что |
|-------|-----|-----|
| **17:50** | Пятница | «Эх, а скоро дудосинг…» во все чаты из `bot_users.json` |
| **3 ч тишины** | Группы | Кринж-мем (проверка каждые 20 мин) |

Логи плановых мемов:

```text
🌤️ SP9 scheduled meme (afternoon) в чат -1002413642408: ...
🌆 SP9 scheduled meme (evening) в чат ...
🍻 SP9 scheduled meme (evening_friday) в чат ...
```

Отключить плановые мемы: `SP9_SCHEDULED_MEME_ENABLED=0`.

Подробнее: [MEME_REPLIES.md](MEME_REPLIES.md).

---

## Файлы данных

Каталог: `SLASHBOT_DATA_DIR` (на Railway — `/data`).

| Файл | Содержимое |
|------|------------|
| `bot_users.json` | Список `chat_id` для рассылок и веб-панели |
| `bot_settings.json` | Расписание `/set_schedule` |
| `meme_state.json` | История сообщений, активность чатов (для мемов) |
| `scheduled_messages.json` | Отложенные сообщения веб-панели |
| `.bot.lock` | Блокировка второго локального процесса |

В `.gitignore` — не коммитить.

---

## Логи при успешном старте

```text
Mounting volume on: ...
[start_both] Данные: /data
[start_both] bot_users.json: /data/bot_users.json
💾 Каталог данных: /data
💾 История чатов загружена: N чат(ов)   # или «файл не найден» при первом запуске
✅ LLM: gpt-4o-mini @ https://api.openai.com/v1 — ok (...)
✅ SP9 works: бот — administrator, видит все сообщения группы
🤖 Бот @ag_slashbot запущен!
📢 АВТОМАТИЧЕСКИЕ РАССЫЛКИ:
   🕛 S:P9 works (ПН-ПТ): в 12:00 МСК
   🌤️ S:P9 послеобеденный мем (ПН-ПТ): в 15:00 МСК
   🌆 S:P9 вечерний мем (ПН-ПТ): в 18:00 МСК (в пятницу — напутствие на выходные)
   🤫 ТИШИНА В ГРУППЕ: мем после 3 ч без сообщений
```

---

## Troubleshooting

| Симптом | Решение |
|---------|---------|
| `Conflict: getUpdates` | Один инстанс: останови локальный бот, Replicas=1, подожди redeploy |
| `[start_both] Данные: /app` | Volume mount `/data`, Variable `SLASHBOT_DATA_DIR=/data`, redeploy |
| `👥 Файл чатов не найден` после redeploy | Volume не подключён или пишет в `/app` |
| `⚠️ LLM: HTTP 400` | Проверь `OPENAI_API_KEY`, `MEME_LLM_MODEL`, `OPENAI_BASE_URL` |
| Нет `📨 Получено сообщение` в группе | Group Privacy OFF или бот — админ |
| Нет плановых мемов в логах | Старый деплой; нужен коммит с scheduled memes |
| `❌ Другой экземпляр slashbot уже запущен` | Второй `start_both.py` локально — закрой |

Полный список: [RAILWAY_SETUP.md](RAILWAY_SETUP.md) → «Если что-то пошло не так».

---

## Переменные окружения

### Обязательно

| Variable | Описание |
|----------|----------|
| `BOT_TOKEN` | Токен от @BotFather |

### Railway + данные

| Variable | Значение | Описание |
|----------|----------|----------|
| `SLASHBOT_DATA_DIR` | `/data` | Каталог persistent-файлов |

### Веб-панель

| Variable | Описание |
|----------|----------|
| `WEB_USER` | Basic Auth логин |
| `WEB_PASSWORD` | Basic Auth пароль |

### Мемы (OpenAI)

| Variable | По умолчанию |
|----------|--------------|
| `OPENAI_API_KEY` | — |
| `MEME_LLM_MODEL` | `gpt-4o-mini` |
| `MEME_LLM_CHANCE` | `0.85` |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` |

### S:P9 works

| Variable | По умолчанию |
|----------|--------------|
| `SP9_WORKS_CHAT_ID` | `-1002413642408` |
| `SP9_SCHEDULED_MEME_ENABLED` | `1` |
| `SP9_AFTERNOON_MEME_HOUR` | `15` |
| `SP9_EVENING_MEME_HOUR` | `18` |

Полный список: [MEME_REPLIES.md](MEME_REPLIES.md), [config.example.py](config.example.py).

---

## Связанные документы

| Документ | О чём |
|----------|--------|
| [RAILWAY_SETUP.md](RAILWAY_SETUP.md) | Первичная настройка Railway |
| [DEPLOY.md](DEPLOY.md) | Деплой 24/7, веб-панель |
| [SP9_WORKS_CHAT.md](SP9_WORKS_CHAT.md) | Чат S:P9 works |
| [MEME_REPLIES.md](MEME_REPLIES.md) | Мемы, LLM, `/meme` |
| [PASHA_PERSONA.md](PASHA_PERSONA.md) | Реакции Паши |
