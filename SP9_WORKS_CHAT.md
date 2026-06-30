# S:P9 works — быстрый отправитель

Зафиксированный чат:

- `title`: `S:P9 works`
- `chat_id`: `-1002413642408`

## Отправка сообщения (через Telegram Bot API)

1) Задай токен в переменную окружения:

```bash
export BOT_TOKEN="вставь_сюда_токен_бота"
```

2) Отправь сообщение:

```bash
curl -sS -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
  -d "chat_id=-1002413642408" \
  --data-urlencode "text=Синкуемся?"
```

## Проверка названия чата по ID

```bash
curl -sS "https://api.telegram.org/bot${BOT_TOKEN}/getChat?chat_id=-1002413642408"
```

## Полезно

- Не коммить реальный токен в репозиторий.
- Если нужно отправлять часто, можно сделать отдельный скрипт и читать `BOT_TOKEN` из env.
