# Конфигурация бота
# Скопируй этот файл как config.py и подставь свой токен от @BotFather
import os

BOT_TOKEN = os.getenv('BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')

# Опционально: мемные реплики через OpenAI (иначе — шаблоны из фраз чата)
# OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')
# MEME_LLM_MODEL = os.getenv('MEME_LLM_MODEL', 'gpt-4o-mini')
