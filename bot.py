import random
import asyncio
import warnings
import datetime as dt
from telegram import Update, Bot
from telegram.warnings import PTBUserWarning
# В v20 days уже в формате cron (1=пн, 5=пт) — подавляем предупреждение
warnings.filterwarnings("ignore", message=".*days.*parameter.*cron", category=PTBUserWarning)
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.request import HTTPXRequest
import os
try:
    from config import BOT_TOKEN
except ModuleNotFoundError:
    # На Railway и т.п. config.py может отсутствовать (в .gitignore) — берём из env
    BOT_TOKEN = os.getenv('BOT_TOKEN', '')
import pytz
import json

# Файл для хранения настроек
SETTINGS_FILE = "bot_settings.json"
USERS_FILE = "bot_users.json"  # Файл для хранения списка пользователей

# Глобальные переменные для хранения настроек
SCHEDULED_CHAT_ID = None
SCHEDULED_TIME = dt.time(hour=16, minute=0)  # По умолчанию 16:00
SCHEDULED_TIMEZONE = pytz.timezone('Europe/Moscow')  # По умолчанию Москва
APPLICATION = None  # Ссылка на приложение для перезапуска задач
CHAT_IDS = set()  # Множество ID всех чатов (личных и групповых)

def load_users():
    """Загружает список чатов из файла"""
    global CHAT_IDS
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, 'r', encoding='utf-8') as f:
                users_data = json.load(f)
                # Поддержка старого формата (user_ids) и нового (chat_ids)
                chat_list = users_data.get('chat_ids', users_data.get('user_ids', []))
                CHAT_IDS = set(chat_list)
                print(f"👥 Загружено чатов: {len(CHAT_IDS)}")
        except Exception as e:
            print(f"⚠️ Ошибка при загрузке чатов: {e}")
            CHAT_IDS = set()
    else:
        print("👥 Файл чатов не найден, создается новый")
        CHAT_IDS = set()

def save_users():
    """Сохраняет список чатов в файл"""
    try:
        users_data = {
            'chat_ids': list(CHAT_IDS)
        }
        with open(USERS_FILE, 'w', encoding='utf-8') as f:
            json.dump(users_data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"⚠️ Ошибка при сохранении чатов: {e}")
        return False

def add_chat(chat_id, chat_type="unknown", chat_title="Unknown"):
    """Добавляет чат в базу для рассылки"""
    global CHAT_IDS
    if chat_id not in CHAT_IDS:
        CHAT_IDS.add(chat_id)
        save_users()
        print(f"➕ Добавлен новый чат: {chat_id} | Тип: {chat_type} | Название: {chat_title}")
    return True

def load_settings():
    """Загружает настройки из файла"""
    global SCHEDULED_CHAT_ID, SCHEDULED_TIME, SCHEDULED_TIMEZONE
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                settings = json.load(f)
                SCHEDULED_CHAT_ID = settings.get('scheduled_chat_id')
                
                # Загружаем время
                time_str = settings.get('scheduled_time', '13:38')
                hour, minute = map(int, time_str.split(':'))
                SCHEDULED_TIME = dt.time(hour=hour, minute=minute)
                
                # Загружаем часовой пояс
                timezone_str = settings.get('scheduled_timezone', 'Europe/Moscow')
                SCHEDULED_TIMEZONE = pytz.timezone(timezone_str)
                
                print(f"📂 Настройки загружены:")
                print(f"   Chat ID: {SCHEDULED_CHAT_ID}")
                print(f"   Время: {SCHEDULED_TIME.strftime('%H:%M')}")
                print(f"   Часовой пояс: {timezone_str}")
        except Exception as e:
            print(f"⚠️ Ошибка при загрузке настроек: {e}")
    else:
        print("📂 Файл настроек не найден, используются настройки по умолчанию")

def save_settings():
    """Сохраняет настройки в файл"""
    try:
        settings = {
            'scheduled_chat_id': SCHEDULED_CHAT_ID,
            'scheduled_time': SCHEDULED_TIME.strftime('%H:%M'),
            'scheduled_timezone': str(SCHEDULED_TIMEZONE)
        }
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
        print(f"💾 Настройки сохранены:")
        print(f"   Chat ID: {SCHEDULED_CHAT_ID}")
        print(f"   Время: {SCHEDULED_TIME.strftime('%H:%M')}")
        print(f"   Часовой пояс: {SCHEDULED_TIMEZONE}")
        return True
    except Exception as e:
        print(f"⚠️ Ошибка при сохранении настроек: {e}")
        return False

# Список прикольных ответов на команды
FUN_RESPONSES = [
    "Вау! 🤩 Отличная команда!",
    "Круто! 🚀 Ты знаешь, что делаешь!",
    "Супер! 💫 Эта команда просто огонь!",
    "Отлично! 🎯 Попал в точку!",
    "Потрясающе! 🌟 Ты молодец!",
    "Классно! 🎪 Продолжай в том же духе!",
    "Замечательно! 🎨 Творческий подход!",
    "Великолепно! 🎭 Театрально!",
    "Превосходно! 🎵 Музыкально!",
    "Фантастически! 🎪 Цирково!"
]

# Список агрессивных ответов для отваживания спамеров
AGGRESSIVE_RESPONSES = [
    "🤬 НЕ БЕСПОКОЙ МЕНЯ! Я занят важными делами!",
    "😤 ОТСТАНЬ! У меня есть дела поважнее!",
    "🤯 ХВАТИТ СПАМИТЬ! Я не отвечаю на всякую ерунду!",
    "😡 ПРЕКРАТИ! Меня раздражают такие сообщения!",
    "🤮 ОТВАЛИ! Не мешай мне работать!",
    "😠 НЕ ПРИСТАВАЙ! Я не буду отвечать на глупости!",
    "🤬 ЗАМОЛЧИ! Хватит меня доставать!",
    "😤 ОТСТАНЬ ОТ МЕНЯ! Я занят!",
    "🤯 НЕ БЕСПОКОЙ! У меня нет времени на ерунду!",
    "😡 ПРЕКРАТИ СПАМИТЬ! Меня это бесит!"
]

# Список интересных фактов (для нормальных пользователей)
INTERESTING_FACTS = [
    "🐙 Осьминоги имеют три сердца и голубую кровь!",
    "🌙 Луна удаляется от Земли на 3.8 см каждый год!",
    "🐝 Пчелы могут распознавать человеческие лица!",
    "🦋 Бабочки пробуют еду ногами!",
    "🐧 Пингвины могут прыгать на высоту до 2 метров!",
    "🦒 У жирафов такой же размер шеи, как у человека!",
    "🐬 Дельфины дают друг другу имена!",
    "🦎 Хамелеоны могут двигать глазами независимо друг от друга!",
    "🐨 Коалы спят 18-22 часа в день!",
    "🦜 Попугаи могут жить до 80 лет!"
]

# Список эмодзи для команд
COMMAND_EMOJIS = [
    "🎯", "🚀", "💫", "🌟", "🎪", "🎨", "🎭", "🎵", "🎪", "🎊",
    "🔥", "⚡", "💎", "🎲", "🎈", "🎁", "🎉", "🎊", "✨", "🌈"
]

# Список прикольных действий
FUN_ACTIONS = [
    "выполняю магический ритуал! ✨",
    "запускаю ракету! 🚀",
    "включаю режим супергероя! 🦸",
    "активирую крутые способности! ⚡",
    "запускаю танцевальную программу! 💃",
    "включаю режим ниндзя! 🥷",
    "активирую космический режим! 🛸",
    "запускаю режим детектива! 🕵️",
    "включаю режим повара! 👨‍🍳",
    "активирую режим художника! 🎨"
]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /start"""
    # Добавляем чат в базу для рассылки
    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type
    chat_title = update.effective_chat.title if hasattr(update.effective_chat, 'title') else f"Личный чат с {update.effective_user.first_name}"
    add_chat(chat_id, chat_type, chat_title)
    
    welcome_message = """
🤖 Привет! Я Классный парень - бот с интересными фактами!

✨ Я отвечаю фактами только на "хорошие" команды!

✅ Хорошие команды:
/привет /hello /hi
/факт /fact
/интересно /interesting
/круто /cool
/магия /magic
/наука /science
/животные /animals
/природа /nature

🔗 Специальные команды:
/kukumroom - Ссылка на комнату Whereby
/kuku - Ссылка на комнату Whereby
/kuku2 - Ссылка на комнату Whereby 2

🤖 Управление ботом:
/set_bot_name <имя> - Изменить имя бота
/set_bot_description <описание> - Изменить описание бота
/bot_info - Показать информацию о боте

⏰ Управление расписанием:
/set_schedule - Настроить сообщение по будням (пн-пт)
/set_time HH:MM - Изменить время отправки
/set_timezone <пояс> - Изменить часовой пояс
/status_schedule - Проверить статус
/stop_schedule - Отключить расписание

📝 Текстовые сообщения:
• Напиши "Закинул" → Я отвечу: "Ты классный, помни это"
• Напиши "Заход" → Через 60 секунд отправлю: "Заход на завод"

❌ На остальные команды я отвечаю агрессивно!

💡 Важно: В группах я вижу все сообщения только если:
- Privacy Mode выключен в @BotFather, или
- Я назначен администратором группы

/help - Показать полную справку
    """
    await update.message.reply_text(welcome_message)

async def handle_any_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Универсальный обработчик для любых команд"""
    # Добавляем чат в базу для рассылки
    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type
    chat_title = update.effective_chat.title if hasattr(update.effective_chat, 'title') else f"Личный чат с {update.effective_user.first_name}"
    add_chat(chat_id, chat_type, chat_title)
    
    command = update.message.text[1:]  # Убираем слеш в начале
    
    # Список "хороших" команд, на которые отвечаем фактами
    good_commands = [
        'start', 'help', 'привет', 'hello', 'hi', 'факт', 'fact', 
        'интересно', 'interesting', 'круто', 'cool', 'магия', 'magic',
        'наука', 'science', 'животные', 'animals', 'природа', 'nature',
        'kukumroom', 'kuku', 'kuku2',
        # Команды управления расписанием
        'set_schedule', 'stop_schedule', 'status_schedule', 'set_time', 'set_timezone',
        # Команды управления ботом
        'set_bot_name', 'set_bot_description', 'bot_info', 'test_message'
    ]
    
    # Проверяем, является ли команда "хорошей"
    if command.lower() in good_commands:
        # Выбираем случайный интересный факт
        fact = random.choice(INTERESTING_FACTS)
        await update.message.reply_text(fact)
    else:
        # Выбираем случайный агрессивный ответ
        aggressive_response = random.choice(AGGRESSIVE_RESPONSES)
        await update.message.reply_text(aggressive_response)

async def kukumroom_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /kukumroom"""
    await update.message.reply_text("Куку — @https://whereby.com/kukumroom ")

async def kuku_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /kuku"""
    await update.message.reply_text("Куку — https://whereby.com/kukumroom")

async def kuku2_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /kuku2"""
    await update.message.reply_text("А вот - https://whereby.com/sp999999")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /help"""
    help_text = """
🤖 Как пользоваться ботом "Классный парень":

✨ Я отвечаю фактами только на "хорошие" команды!

✅ Хорошие команды (получат факт):
/привет /hello /hi
/факт /fact
/интересно /interesting
/круто /cool
/магия /magic
/наука /science
/животные /animals
/природа /nature

❌ Плохие команды (получат агрессивный ответ):
/пицца /космос /деньги /счастье
/что-угодно /любая-команда
/тест /спам /глупости

⚠️ Я строгий бот! Не спамьте!

📝 Текстовые сообщения:
• Напиши "Закинул" → Я отвечу: "Ты классный, помни это"
• Напиши "Заход" → Через 60 секунд отправлю: "Заход на завод"

⏰ Управление расписанием:
/set_schedule - Включить сообщение "Че как там по макетам" по будням (пн-пт) в этот чат
/set_time HH:MM - Изменить время отправки (например: /set_time 16:00)
/set_timezone <пояс> - Изменить часовой пояс (например: /set_timezone Europe/Moscow)
/status_schedule - Проверить статус расписания
/stop_schedule - Отключить запланированные сообщения

🔗 Специальные команды:
/start - Начать работу с ботом
/help - Показать это сообщение
/kukumroom - Ссылка на комнату Whereby
/kuku - Ссылка на комнату Whereby
/kuku2 - Ссылка на комнату Whereby 2

🤖 Управление ботом:
/set_bot_name <имя> - Изменить имя бота (отображается в списке участников)
/set_bot_description <описание> - Изменить описание бота
/bot_info - Показать информацию о боте

💡 Где я работаю:
✅ В личных сообщениях - всегда вижу все
✅ В группах - если Privacy Mode выключен в @BotFather
✅ В группах - если я администратор

Попробуй хорошую команду! /привет
    """
    await update.message.reply_text(help_text)

async def set_schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /set_schedule - включает расписание для текущего чата"""
    global SCHEDULED_CHAT_ID
    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type
    chat_title = update.effective_chat.title if hasattr(update.effective_chat, 'title') else "Личный чат"
    
    SCHEDULED_CHAT_ID = chat_id
    
    if save_settings():
        timezone_name = str(SCHEDULED_TIMEZONE).split('/')[-1] if '/' in str(SCHEDULED_TIMEZONE) else str(SCHEDULED_TIMEZONE)
        message = f"""✅ Расписание настроено!

📍 Чат: {chat_title}
🆔 Chat ID: {chat_id}
⏰ Время: {SCHEDULED_TIME.strftime('%H:%M')} ({timezone_name}) - по будням (пн-пт)
💬 Сообщение: "Че как там по макетам"

Сообщение будет отправляться каждый будний день в указанное время в этот чат.

Для изменения времени: /set_time
Для изменения часового пояса: /set_timezone
Для отключения: /stop_schedule"""
        await update.message.reply_text(message)
    else:
        await update.message.reply_text("❌ Ошибка при сохранении настроек. Попробуйте еще раз.")

async def stop_schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /stop_schedule - отключает расписание"""
    global SCHEDULED_CHAT_ID
    
    if SCHEDULED_CHAT_ID is None:
        await update.message.reply_text("ℹ️ Расписание не настроено. Используйте /set_schedule для настройки.")
        return
    
    old_chat_id = SCHEDULED_CHAT_ID
    SCHEDULED_CHAT_ID = None
    
    if save_settings():
        message = f"""✅ Расписание отключено!

Запланированные сообщения больше не будут отправляться.
Предыдущий Chat ID: {old_chat_id}

Для включения используйте /set_schedule"""
        await update.message.reply_text(message)
    else:
        await update.message.reply_text("❌ Ошибка при сохранении настроек. Попробуйте еще раз.")

async def status_schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /status_schedule - показывает статус расписания"""
    if SCHEDULED_CHAT_ID is None:
        message = """ℹ️ Статус расписания:

🔴 Расписание не настроено

Для настройки отправьте команду /set_schedule в том чате, куда нужно отправлять сообщения."""
    else:
        current_chat_id = update.effective_chat.id
        is_current_chat = (current_chat_id == SCHEDULED_CHAT_ID)
        
        # Получаем информацию о часовом поясе
        timezone_name = str(SCHEDULED_TIMEZONE).split('/')[-1] if '/' in str(SCHEDULED_TIMEZONE) else str(SCHEDULED_TIMEZONE)
        
        message = f"""ℹ️ Статус расписания:

🟢 Расписание активно

🆔 Настроенный Chat ID: {SCHEDULED_CHAT_ID}
📍 Текущий чат: {"✅ Да, это этот чат" if is_current_chat else "❌ Нет, другой чат"}
⏰ Время: {SCHEDULED_TIME.strftime('%H:%M')} ({timezone_name}) - по будням (пн-пт)
💬 Сообщение: "Че как там по макетам"

Для изменения времени: /set_time
Для изменения часового пояса: /set_timezone
Для отключения: /stop_schedule"""
    
    await update.message.reply_text(message)

async def set_time_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /set_time - настройка времени отправки"""
    global SCHEDULED_TIME
    
    if len(context.args) != 1:
        await update.message.reply_text(
            """⏰ Настройка времени отправки:

Использование: /set_time HH:MM

Примеры:
/set_time 13:38 - каждый день в 13:38
/set_time 09:00 - каждый день в 9:00
/set_time 18:30 - каждый день в 18:30

Текущее время: {}""".format(SCHEDULED_TIME.strftime('%H:%M'))
        )
        return
    
    try:
        time_str = context.args[0]
        hour, minute = map(int, time_str.split(':'))
        
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            await update.message.reply_text("❌ Неверное время! Часы: 0-23, минуты: 0-59")
            return
        
        SCHEDULED_TIME = dt.time(hour=hour, minute=minute)
        
        if save_settings():
            # Перезапускаем задачу с новым временем
            if APPLICATION:
                restart_scheduled_job(APPLICATION)
            
            timezone_name = str(SCHEDULED_TIMEZONE).split('/')[-1] if '/' in str(SCHEDULED_TIMEZONE) else str(SCHEDULED_TIMEZONE)
            message = f"""✅ Время обновлено!

⏰ Новое время: {SCHEDULED_TIME.strftime('%H:%M')} ({timezone_name})
📅 Сообщение будет отправляться каждый будний день (пн-пт) в указанное время

Для изменения часового пояса: /set_timezone"""
            await update.message.reply_text(message)
        else:
            await update.message.reply_text("❌ Ошибка при сохранении настроек")
            
    except ValueError:
        await update.message.reply_text("❌ Неверный формат времени! Используйте HH:MM (например: 13:38)")

async def set_timezone_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /set_timezone - настройка часового пояса"""
    global SCHEDULED_TIMEZONE
    
    if len(context.args) != 1:
        available_timezones = [
            "Europe/Moscow (МСК)",
            "Europe/London (Лондон)",
            "Europe/Berlin (Берлин)", 
            "America/New_York (Нью-Йорк)",
            "America/Los_Angeles (Лос-Анджелес)",
            "Asia/Tokyo (Токио)",
            "Asia/Shanghai (Шанхай)",
            "UTC (Всемирное время)"
        ]
        
        current_tz = str(SCHEDULED_TIMEZONE).split('/')[-1] if '/' in str(SCHEDULED_TIMEZONE) else str(SCHEDULED_TIMEZONE)
        
        message = f"""🌍 Настройка часового пояса:

Использование: /set_timezone <название>

Доступные часовые пояса:
{chr(10).join(f'• {tz}' for tz in available_timezones)}

Примеры:
/set_timezone Europe/Moscow
/set_timezone Europe/London  
/set_timezone UTC

Текущий часовой пояс: {current_tz}"""
        
        await update.message.reply_text(message)
        return
    
    try:
        timezone_str = context.args[0]
        
        # Проверяем, что часовой пояс существует
        pytz.timezone(timezone_str)
        SCHEDULED_TIMEZONE = pytz.timezone(timezone_str)
        
        if save_settings():
            # Перезапускаем задачу с новым часовым поясом
            if APPLICATION:
                restart_scheduled_job(APPLICATION)
            
            timezone_name = str(SCHEDULED_TIMEZONE).split('/')[-1] if '/' in str(SCHEDULED_TIMEZONE) else str(SCHEDULED_TIMEZONE)
            message = f"""✅ Часовой пояс обновлен!

🌍 Новый часовой пояс: {timezone_name}
⏰ Время отправки: {SCHEDULED_TIME.strftime('%H:%M')} ({timezone_name})

Для изменения времени: /set_time"""
            await update.message.reply_text(message)
        else:
            await update.message.reply_text("❌ Ошибка при сохранении настроек")
            
    except pytz.exceptions.UnknownTimeZoneError:
        await update.message.reply_text("❌ Неизвестный часовой пояс! Используйте /set_timezone без параметров для списка доступных.")

async def set_bot_name_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /set_bot_name - устанавливает имя бота"""
    if len(context.args) < 1:
        await update.message.reply_text(
            """🤖 Установка имени бота:
            
Использование: /set_bot_name <новое_имя>

Примеры:
/set_bot_name Классный парень
/set_bot_name SlashBot
/set_bot_name Мой крутой бот

⚠️ Имя будет отображаться в списке участников группы"""
        )
        return
    
    new_name = " ".join(context.args)
    
    try:
        # Создаем объект бота для вызова API
        bot = Bot(token=BOT_TOKEN)
        
        # Устанавливаем новое имя
        await bot.set_my_name(new_name)
        
        await update.message.reply_text(f"✅ Имя бота изменено на: {new_name}")
        print(f"✅ Имя бота изменено на: {new_name}")
        
    except Exception as e:
        error_msg = f"❌ Ошибка при изменении имени бота: {str(e)}"
        await update.message.reply_text(error_msg)
        print(error_msg)

async def set_bot_description_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /set_bot_description - устанавливает описание бота"""
    if len(context.args) < 1:
        await update.message.reply_text(
            """📝 Установка описания бота:
            
Использование: /set_bot_description <новое_описание>

Примеры:
/set_bot_description Бот с интересными фактами
/set_bot_description Помощник для работы
/set_bot_description Крутой бот для группы

⚠️ Описание будет отображаться в профиле бота"""
        )
        return
    
    new_description = " ".join(context.args)
    
    try:
        # Создаем объект бота для вызова API
        bot = Bot(token=BOT_TOKEN)
        
        # Устанавливаем новое описание
        await bot.set_my_description(new_description)
        
        await update.message.reply_text(f"✅ Описание бота изменено на: {new_description}")
        print(f"✅ Описание бота изменено на: {new_description}")
        
    except Exception as e:
        error_msg = f"❌ Ошибка при изменении описания бота: {str(e)}"
        await update.message.reply_text(error_msg)
        print(error_msg)

async def get_bot_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /bot_info - показывает информацию о боте"""
    try:
        # Создаем объект бота для вызова API
        bot = Bot(token=BOT_TOKEN)
        
        # Получаем информацию о боте
        bot_info = await bot.get_me()
        
        message = f"""🤖 Информация о боте:

🆔 ID: {bot_info.id}
👤 Имя: {bot_info.first_name}
📝 Username: @{bot_info.username if bot_info.username else 'не установлен'}
✅ Может присоединяться к группам: {'Да' if bot_info.can_join_groups else 'Нет'}
✅ Может читать сообщения: {'Да' if bot_info.can_read_all_group_messages else 'Нет'}
✅ Поддерживает inline-запросы: {'Да' if bot_info.supports_inline_queries else 'Нет'}

💡 Для изменения имени используйте: /set_bot_name
💡 Для изменения описания используйте: /set_bot_description"""
        
        await update.message.reply_text(message)
        
    except Exception as e:
        error_msg = f"❌ Ошибка при получении информации о боте: {str(e)}"
        await update.message.reply_text(error_msg)
        print(error_msg)

async def test_message_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /test_message - тестирует отправку сообщения в текущий чат"""
    try:
        chat_id = update.effective_chat.id
        await update.message.reply_text("🧪 Тестовое сообщение отправлено успешно!")
        print(f"✅ Тестовое сообщение отправлено в чат {chat_id}")
    except Exception as e:
        error_msg = f"❌ Ошибка при отправке тестового сообщения: {str(e)}"
        await update.message.reply_text(error_msg)
        print(error_msg)

async def send_delayed_message(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправляет отложенное сообщение 'Заход на завод'"""
    job = context.job
    await context.bot.send_message(
        chat_id=job.chat_id,
        text="Заход на завод"
    )

async def send_scheduled_maket_message(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправляет сообщение 'Че как там по макетам' по будням в настроенное время"""
    if SCHEDULED_CHAT_ID:
        try:
            await context.bot.send_message(
                chat_id=SCHEDULED_CHAT_ID,
                text="Че как там по макетам"
            )
            print(f"✅ Отправлено запланированное сообщение в чат {SCHEDULED_CHAT_ID}")
        except Exception as e:
            print(f"❌ Ошибка при отправке запланированного сообщения в чат {SCHEDULED_CHAT_ID}: {e}")
    else:
        print("⚠️ SCHEDULED_CHAT_ID не настроен")

async def send_friday_broadcast(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправляет сообщение во все чаты (личные и групповые) по пятницам в 17:50 МСК"""
    message_text = "Эх, а скоро дудосинг..."
    success_count = 0
    error_count = 0
    
    print(f"📢 Начало пятничной рассылки во все чаты ({len(CHAT_IDS)} шт.)")
    
    for chat_id in CHAT_IDS:
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=message_text
            )
            success_count += 1
            print(f"✅ Отправлено в чат {chat_id}")
        except Exception as e:
            error_count += 1
            print(f"❌ Ошибка при отправке в чат {chat_id}: {e}")
    
    print(f"📊 Рассылка завершена: успешно={success_count}, ошибок={error_count}")

async def send_morning_broadcast(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправляет утреннее сообщение во все чаты по будням (пн-пт) в 10:30 МСК"""
    message_text = "Бодрейшего утра, посоны! Держите ссыль https://whereby.com/kukumroom "
    success_count = 0
    error_count = 0
    
    print(f"☀️ Начало утренней рассылки во все чаты ({len(CHAT_IDS)} шт.)")
    
    for chat_id in CHAT_IDS:
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=message_text
            )
            success_count += 1
            print(f"✅ Отправлено в чат {chat_id}")
        except Exception as e:
            error_count += 1
            print(f"❌ Ошибка при отправке в чат {chat_id}: {e}")
    
    print(f"📊 Утренняя рассылка завершена: успешно={success_count}, ошибок={error_count}")

def restart_scheduled_job(application):
    """Перезапускает задачу расписания с новыми настройками"""
    job_queue = application.job_queue
    if job_queue is None:
        print("⚠️ JobQueue не инициализирована. Установите зависимости python-telegram-bot[job-queue] и перезапустите бота")
        return
    
    # Удаляем старую задачу
    try:
        jobs = job_queue.get_jobs_by_name('daily_maket_reminder')
        for job in jobs:
            job.schedule_removal()
        print("🗑️ Старая задача расписания удалена")
    except:
        pass
    
    # Создаем новую задачу с обновленными настройками
    if SCHEDULED_CHAT_ID:
        job_queue.run_daily(
            send_scheduled_maket_message,
            time=SCHEDULED_TIME,
            days=(1, 2, 3, 4, 5),  # Только будни (пн-пт)
            name='daily_maket_reminder',
            chat_id=SCHEDULED_CHAT_ID,
            data=None
        )
        print(f"🔄 Задача расписания перезапущена: {SCHEDULED_TIME.strftime('%H:%M')} ({SCHEDULED_TIMEZONE}) для чата {SCHEDULED_CHAT_ID}")
    else:
        print("⚠️ Не удалось перезапустить задачу: SCHEDULED_CHAT_ID не настроен")

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик текстовых сообщений для отслеживания слов 'Заход' и 'Закинул'"""
    if update.message and update.message.text:
        message_text = update.message.text
        chat_id = update.effective_chat.id
        chat_type = update.effective_chat.type
        chat_title = update.effective_chat.title if hasattr(update.effective_chat, 'title') else f"Личный чат с {update.effective_user.first_name}"
        
        # Добавляем чат в базу для рассылки
        add_chat(chat_id, chat_type, chat_title)
        
        print(f"📨 Получено сообщение: {message_text}")
        print(f"   Chat ID: {chat_id} | Тип: {chat_type} | Название: {chat_title}")
        
        # Проверяем, содержит ли сообщение слово "Закинул"
        if "Закинул" in message_text or "закинул" in message_text:
            print(f"✅ Обнаружено слово 'Закинул'! Отправляю ответ")
            await update.message.reply_text("Ты классный, помни это")
        
        # Проверяем, содержит ли сообщение слово "Заход"
        if "Заход" in message_text or "заход" in message_text:
            print(f"✅ Обнаружено слово 'Заход'! Планирую отправку сообщения через 60 секунд в чат {chat_id}")
            
            # Планируем отправку сообщения через 60 секунд (1 минута)
            context.job_queue.run_once(
                send_delayed_message,
                60,
                chat_id=chat_id,
                name=f"zaход_{chat_id}"
            )
        
        # Проверяем, содержит ли сообщение слово "гуд"
        if "гуд" in message_text.lower():
            print(f"✅ Обнаружено слово 'гуд'! Отправляю ответ")
            await update.message.reply_text("я знал, что ты лучший")

def main() -> None:
    """Основная функция для запуска бота"""
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN" or BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ Ошибка: BOT_TOKEN не настроен!")
        print("Задайте переменную окружения BOT_TOKEN (например в Railway: Variables → BOT_TOKEN)")
        import sys
        sys.exit(1)
    
    print("=" * 60)
    print("🚀 ЗАПУСК БОТА")
    print("=" * 60)
    print(f"📌 Токен: {BOT_TOKEN[:10]}...{BOT_TOKEN[-5:]}")
    print("=" * 60)
    
    # Загружаем настройки из файла
    load_settings()
    
    # Загружаем список пользователей
    load_users()
    
    # Создаем приложение с поддержкой JobQueue (увеличенные таймауты для нестабильной сети)
    request = HTTPXRequest(connect_timeout=30.0, read_timeout=30.0, write_timeout=30.0, pool_timeout=30.0)
    application = Application.builder().token(BOT_TOKEN).request(request).build()
    
    # Сохраняем ссылку на приложение для перезапуска задач
    global APPLICATION
    APPLICATION = application
    
    # Добавляем обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("kukumroom", kukumroom_command))
    application.add_handler(CommandHandler("kuku", kuku_command))
    application.add_handler(CommandHandler("kuku2", kuku2_command))
    application.add_handler(CommandHandler("set_schedule", set_schedule_command))
    application.add_handler(CommandHandler("stop_schedule", stop_schedule_command))
    application.add_handler(CommandHandler("status_schedule", status_schedule_command))
    application.add_handler(CommandHandler("set_time", set_time_command))
    application.add_handler(CommandHandler("set_timezone", set_timezone_command))
    application.add_handler(CommandHandler("set_bot_name", set_bot_name_command))
    application.add_handler(CommandHandler("set_bot_description", set_bot_description_command))
    application.add_handler(CommandHandler("bot_info", get_bot_info_command))
    application.add_handler(CommandHandler("test_message", test_message_command))
    
    # Добавляем обработчик текстовых сообщений для отслеживания слова "Заход"
    # Он будет срабатывать на любые текстовые сообщения (кроме команд)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    
    # Добавляем универсальный обработчик для любых команд В САМОМ КОНЦЕ
    # Он будет срабатывать на любую команду, которая не обработана выше
    application.add_handler(MessageHandler(filters.Regex(r'^/'), handle_any_command))
    
    # Настраиваем расписание для ежедневной отправки сообщения "Че как там по макетам"
    job_queue = application.job_queue
    if job_queue is None:
        print("⚠️ JobQueue не инициализирована. Пропускаю настройку задач. Убедитесь, что установлен пакет python-telegram-bot[job-queue]")
        print("   pip install 'python-telegram-bot[job-queue]'\n")
        print("Продолжаю запуск без планировщика задач...")
        print("=")
        print("")
        print("🤖 Бот 'Классный парень' запущен! Нажмите Ctrl+C для остановки.")
        print("📝 Жду сообщения...")
        print("")
        application.run_polling()
        return
    
    # Запускаем задачу по будням в настроенное время только если есть настроенный чат
    if SCHEDULED_CHAT_ID:
        job_queue.run_daily(
            send_scheduled_maket_message,
            time=SCHEDULED_TIME,
            days=(1, 2, 3, 4, 5),  # Только будни (пн-пт)
            name='daily_maket_reminder',
            chat_id=SCHEDULED_CHAT_ID,
            data=None
        )
    
    # Настраиваем рассылку по пятницам в 17:50 МСК
    friday_time = dt.time(hour=17, minute=50)  # 17:50
    job_queue.run_daily(
        send_friday_broadcast,
        time=friday_time,
        days=(5,),  # 5 = пятница (0 - воскресенье, 1 - понедельник... 6 - суббота)
        name='friday_broadcast',
        data=None
    )
    
    # Настраиваем утреннюю рассылку по будням в 10:30 МСК
    morning_time = dt.time(hour=10, minute=30)  # 10:30
    job_queue.run_daily(
        send_morning_broadcast,
        time=morning_time,
        days=(1, 2, 3, 4, 5),  # Понедельник-пятница (1-5)
        name='morning_broadcast',
        data=None
    )
    
    print("🤖 Бот 'Классный парень' запущен! Нажмите Ctrl+C для остановки.")
    print("📝 Жду сообщения...")
    print()
    print("⏰ УПРАВЛЕНИЕ РАСПИСАНИЕМ:")
    if SCHEDULED_CHAT_ID:
        timezone_name = str(SCHEDULED_TIMEZONE).split('/')[-1] if '/' in str(SCHEDULED_TIMEZONE) else str(SCHEDULED_TIMEZONE)
        print(f"   🟢 Расписание АКТИВНО")
        print(f"   📍 Chat ID: {SCHEDULED_CHAT_ID}")
        print(f"   ⏰ Время: {SCHEDULED_TIME.strftime('%H:%M')} ({timezone_name}) - по будням (пн-пт)")
        print(f"   💬 Сообщение: 'Че как там по макетам'")
        print(f"   ℹ️  Команды: /status_schedule, /set_time, /set_timezone, /stop_schedule")
    else:
        print("   🔴 Расписание НЕ НАСТРОЕНО")
        print("   ℹ️  Для настройки:")
        print("      1. Откройте чат, куда нужно отправлять сообщения")
        print("      2. Отправьте команду /set_schedule")
    print()
    print("📢 АВТОМАТИЧЕСКИЕ РАССЫЛКИ:")
    print(f"   ☀️ УТРЕННЯЯ (ПН-ПТ): каждый будний день в 10:30 МСК")
    print(f"      💬 Сообщение: 'Бодрейшего утра, посоны! Держите ссыль https://whereby.com/kukumroom'")
    print(f"   🎉 ПЯТНИЧНАЯ: каждую пятницу в 17:50 МСК")
    print(f"      💬 Сообщение: 'Эх, а скоро дудосинг...'")
    print(f"   👥 Чатов в базе: {len(CHAT_IDS)}")
    print("=" * 60)
    
    # Запускаем бота (с повторными попытками при временных сетевых ошибках)
    import telegram.error
    max_retries = 3
    for attempt in range(max_retries):
        try:
            application.run_polling(drop_pending_updates=True)
            break
        except (telegram.error.TimedOut, telegram.error.NetworkError, OSError) as e:
            if attempt < max_retries - 1:
                wait = 10 * (attempt + 1)
                print(f"\n⚠️ Ошибка сети ({e}). Повтор через {wait} сек... (попытка {attempt + 1}/{max_retries})")
                import time
                time.sleep(wait)
            else:
                print("\n❌ Не удалось подключиться к Telegram API после нескольких попыток.")
                print("   Проверьте интернет, VPN и доступ к api.telegram.org")
                raise

if __name__ == '__main__':
    print("🚀 Запуск бота...")
    main()
