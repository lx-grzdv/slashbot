# 🚀 Запуск бота без твоего компьютера (24/7 в фоне)

Чтобы бот работал постоянно, его нужно запустить на **сервере** или в **облаке**. Ниже — самые простые варианты.

---

## Вариант 1: Railway (проще всего, есть бесплатный tier)

**Пошаговая настройка:** см. **[RAILWAY_SETUP.md](RAILWAY_SETUP.md)**.

Кратко:
1. Зайди на [railway.app](https://railway.app) и войди через GitHub.
2. **New Project** → **Deploy from GitHub repo** → выбери репозиторий `slashbot`.
3. В настройках проекта:
   - **Variables** → `BOT_TOKEN` (токен от @BotFather); опционально `WEB_USER`, `WEB_PASSWORD`, `OPENAI_API_KEY` (мемы — см. [MEME_REPLIES.md](MEME_REPLIES.md)).
   - **Procfile** уже запускает `python start_both.py` (бот + веб в одном сервисе).
4. Деплой запустится сам. Бот будет работать пока проект на Railway активен.

**Пошагово и разбор ошибок:** **[RAILWAY_SETUP.md](RAILWAY_SETUP.md)**.

**Бесплатно:** ограниченные часы в месяц; для одного бота обычно хватает.

---

## Вариант 2: Render

1. Зайди на [render.com](https://render.com), войди через GitHub.
2. **New** → **Background Worker**.
3. Подключи репозиторий, укажи:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python bot.py`
4. В **Environment** добавь переменную `BOT_TOKEN`.
5. Сохрани — воркер будет крутиться в фоне.

На бесплатном плане воркер может «засыпать» после неактивности; для Telegram-бота это обычно не критично после первого запроса.

---

## Вариант 3: Свой сервер (VPS) — полный контроль

Если есть или планируешь VPS (DigitalOcean, Timeweb, Selectel, свой домашний сервер и т.п.):

### Установка на сервере

```bash
# Клонируй проект (или залей файлы)
git clone <твой-репо> slashbot && cd slashbot

# Виртуальное окружение
python3 -m venv venv
source venv/bin/activate   # на Windows: venv\Scripts\activate

# Зависимости
pip install -r requirements.txt

# Токен — через переменную окружения или в config.py
export BOT_TOKEN="твой_токен"
```

### Запуск в фоне через systemd (рекомендуется)

Создай файл сервиса (например `/etc/systemd/system/slashbot.service`):

```ini
[Unit]
Description=Slashbot Telegram Bot
After=network.target

[Service]
Type=simple
User=твой_пользователь
WorkingDirectory=/путь/к/slashbot
Environment="BOT_TOKEN=твой_токен"
ExecStart=/путь/к/slashbot/venv/bin/python bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Затем:

```bash
sudo systemctl daemon-reload
sudo systemctl enable slashbot
sudo systemctl start slashbot
sudo systemctl status slashbot
```

Бот будет стартовать при загрузке сервера и перезапускаться при падении.

### Альтернатива: screen или tmux (без systemd)

```bash
screen -S slashbot
cd /путь/к/slashbot
source venv/bin/activate
export BOT_TOKEN="твой_токен"
python bot.py
# Нажми Ctrl+A, затем D — сессия останется в фоне
# Вернуться: screen -r slashbot
```

---

## Вариант 4: PythonAnywhere (только для скриптов по расписанию)

[PythonAnywhere](https://www.pythonanywhere.com) удобен для задач по расписанию, но **не подходит** для длительно работающего бота с постоянным подключением (Always-on task платный). Для твоего бота лучше Railway или VPS.

---

## Почему не Vercel?

**Vercel** заточен под **serverless**: каждый запрос — отдельный короткий запуск функции (лимит по времени, обычно до 10–60 секунд). После ответа процесс завершается.

Твой бот — **долгоживущий процесс**: он постоянно опрашивает Telegram (polling) или держит webhook, крутит планировщик (рассылки по пятницам, утренние сообщения и т.д.). Ему нужен один процесс, который работает часами без остановки.

На Vercel такого «вечно работающего воркера» нет: нельзя просто поднять `python bot.py` и оставить его в фоне. Поэтому для этого проекта Vercel **не подходит**. Используй Railway, Render или VPS — там как раз запускается обычный процесс/воркер.

(Веб-интерфейс `web_app.py` теоретически можно вынести на Vercel как serverless API, но тогда бота всё равно нужно крутить отдельно — на Railway/Render/VPS.)

---

## Что важно при деплое

- **Токен:** нигде не коммить `config.py` с реальным токеном. Использовать переменные окружения (`BOT_TOKEN`) или секреты платформы.
- **Файлы данных:** `bot_settings.json`, `bot_users.json`, `meme_state.json` (история чатов для мемов) на Railway/Render создаются в файловой системе воркера; при новом деплое они могут сброситься. **Обязательно** подключи Volume (см. ниже и [RAILWAY_SETUP.md](RAILWAY_SETUP.md)).
- **Веб-интерфейс:** см. раздел ниже.
- **Сборка Python на Railway:** в корне лежит `mise.toml` — отключает проверку GitHub attestations для mise (иначе билд может упасть на старых версиях Python).
- **Один процесс бот+веб:** `start_both.py` — бот в главном потоке (polling), Flask в фоне на `PORT`. Не меняй порядок потоков без необходимости (см. [RAILWAY_SETUP.md](RAILWAY_SETUP.md) → troubleshooting).

---

## Типичные проблемы при деплое

| Симптом | Причина | Решение |
|---------|---------|---------|
| Build Failed: `No GitHub artifact attestations` | mise не ставит Python | `mise.toml` в репо или `MISE_PYTHON_GITHUB_ATTESTATIONS=false` |
| `Command 'паша' is not a valid bot command` | Кириллица в `CommandHandler` | Только латиница в `CommandHandler`; `/паша` — в `handle_any_command` |
| Веб работает, бот молчит | `run_polling` не в main thread | `start_both.py`: бот в главном потоке |
| Сервис Active, бот не отвечает | Поток бота упал, Flask жив | Смотреть **Logs** целиком, не только статус |
| Нет `BOT_TOKEN` | Переменная не задана | Railway → Variables |

Подробнее: **[RAILWAY_SETUP.md](RAILWAY_SETUP.md)**.

---

## Веб-морда в браузере

Веб-интерфейс (управление сообщениями, расписание) — это Flask-приложение `web_app.py`. Открыть его можно так:

### Вариант А: только у себя на компе

1. На своём компьютере в папке проекта: `python web_app.py` (или `./start_web.sh`).
2. В браузере открой: **http://localhost:5001**

Доступ только с твоего ПК. Бот при этом может крутиться на Railway — веб-морда просто шлёт запросы в Telegram через тот же токен.

### Вариант Б: один сервис (бот + веб) — чаты подхватываются автоматически

Чтобы при активации бота в чате (команда `/start` или любое сообщение) этот чат **сразу появлялся** в веб-панели без ручного добавления:

Запускай **бот и веб в одном процессе** — скрипт `start_both.py`. Тогда оба используют один и тот же файл `bot_users.json`.

**На Railway:**

1. Оставь **один** сервис (удали второй, если было два: worker и slashbot).
2. У этого сервиса задай **Start Command:** `python start_both.py`
3. **Variables:** `BOT_TOKEN`, `WEB_USER`, `WEB_PASSWORD` (как раньше).
4. **Settings** → **Networking** → **Generate Domain** — получишь ссылку на веб-панель.

В Telegram кто-то написал боту в чате (или отправил `/start`) → бот записал чат в `bot_users.json` → веб-панель читает тот же файл → чат сразу виден в «Выберите чат». Ручное добавление по ID не нужно.

### Вариант В: два сервиса (бот отдельно, веб отдельно)

Если нужны именно два сервиса (worker + web):

1. **Worker** — Start Command: `python bot.py`, Variable: `BOT_TOKEN`.
2. **Web** — Start Command: `python web_app.py`, Variables: `BOT_TOKEN`, `WEB_USER`, `WEB_PASSWORD`, **Generate Domain**.

Минус: у веб-сервиса свой экземпляр `bot_users.json`, он не видит чаты, которые записал бот. Чаты в панель нужно добавлять вручную (команда `/chat_id` в боте → вставить ID в блок «Добавить чат» на сайте).

**Без пароля:** если `WEB_PASSWORD` не задан, панель открыта всем. В интернете лучше задавать `WEB_USER` и `WEB_PASSWORD`.

---

## Кратко

| Способ    | Сложность | Бесплатно        | Когда выбрать        |
|----------|-----------|------------------|----------------------|
| Railway  | Низкая    | Да (лимиты)      | Быстро поднять бота  |
| Render   | Низкая    | Да (лимиты)      | Аналогично Railway   |
| VPS      | Средняя   | Нет (или свой ПК)| Полный контроль, оба процесса (бот + веб) |
| Vercel   | —         | —                | **Не подходит** — нет долгоживущих процессов |

Для «работал сам на фоне без моего компа» достаточно одного из вариантов выше; самый быстрый старт — **Railway** или **Render**.
