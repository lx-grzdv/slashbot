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
