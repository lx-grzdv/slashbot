# Конфигурация бота
# Скопируй этот файл как config.py и подставь свой токен от @BotFather
import os

BOT_TOKEN = os.getenv('BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')

# Опционально: мемные реплики через OpenAI (см. MEME_REPLIES.md)
# Без OPENAI_API_KEY — только шаблоны из фраз чата.
#
# OPENAI_API_KEY=sk-...
# MEME_LLM_MODEL=gpt-4o-mini          # модель (по умолчанию gpt-4o-mini)
# MEME_LLM_CHANCE=0.85                # доля случайных мемов через LLM (0–1)
# MEME_LLM_TIMEOUT_SEC=12             # таймаут запроса к API
# OPENAI_BASE_URL=https://api.openai.com/v1   # если не стандартный OpenAI
# SILENCE_MEME_HOURS=3                  # мем в группе после N часов тишины
# SILENCE_MEME_CHECK_MIN=20             # проверка тишины каждые N минут
# SILENCE_MEME_ENABLED=1                # 0 — выключить
# SP9_SCHEDULED_MEME_ENABLED=1          # плановые мемы в S:P9 works (15:00 и 18:00 МСК)
# SP9_AFTERNOON_MEME_HOUR=15
# SP9_EVENING_MEME_HOUR=18
