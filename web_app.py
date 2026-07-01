import os
from dotenv import load_dotenv
load_dotenv()
# Токен только из env (локально — .env или export; Railway — Variables)
BOT_TOKEN = os.getenv('BOT_TOKEN', '')

from flask import Flask, render_template, request, jsonify, Response
from telegram import Bot
from telegram.request import HTTPXRequest
import json
from datetime import datetime, timedelta
import asyncio
from functools import wraps
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.cron import CronTrigger
from typing import Optional
import pytz

app = Flask(__name__)

# Секретный доступ: если заданы WEB_USER и WEB_PASSWORD — веб-морда закрыта паролем
WEB_USER = os.environ.get('WEB_USER', '')
WEB_PASSWORD = os.environ.get('WEB_PASSWORD', '')

def _check_auth():
    """Проверка Basic Auth. Если WEB_PASSWORD не задан — доступ без пароля (локально)."""
    if not WEB_PASSWORD:
        return True
    auth = request.authorization
    if not auth or not auth.username or not auth.password:
        return False
    expected_user = WEB_USER or 'admin'
    return auth.username == expected_user and auth.password == WEB_PASSWORD

def _auth_response():
    return Response(
        'Требуется вход. Укажите логин и пароль.',
        401,
        {'WWW-Authenticate': 'Basic realm="Web panel"'}
    )

@app.before_request
def require_auth():
    if _check_auth():
        return None
    return _auth_response()

def _make_bot():
    """Создаёт экземпляр Bot с увеличенным пулом соединений. Отдельный экземпляр на запрос избегает Pool timeout при множественных asyncio.run()."""
    request = HTTPXRequest(
        connection_pool_size=16,
        pool_timeout=30.0,
        connect_timeout=30.0,
        read_timeout=30.0,
        write_timeout=30.0,
    )
    return Bot(token=BOT_TOKEN, request=request)

# Файлы для хранения данных (каталог задаётся из start_both через SLASHBOT_DATA_DIR)
_DATA_DIR = os.environ.get('SLASHBOT_DATA_DIR', os.path.dirname(os.path.abspath(__file__)))
USERS_FILE = os.path.join(_DATA_DIR, "bot_users.json")
SCHEDULED_MESSAGES_FILE = os.path.join(_DATA_DIR, "scheduled_messages.json")
BOT_SETTINGS_FILE = os.path.join(_DATA_DIR, "bot_settings.json")

# Планировщик для отложенных сообщений
scheduler = BackgroundScheduler(timezone=pytz.timezone('Europe/Moscow'))
scheduler.start()

def load_chats():
    """Загружает список чатов"""
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, 'r', encoding='utf-8') as f:
                users_data = json.load(f)
                return users_data.get('chat_ids', [])
        except Exception as e:
            print(f"Ошибка при загрузке чатов: {e}")
            return []
    return []

def add_chat_id(cid: int) -> bool:
    """Добавляет chat_id в список (для веб-панели). Возвращает True если добавлен или уже был."""
    try:
        cid = int(cid)
        chat_ids = load_chats()
        if cid not in chat_ids:
            chat_ids.append(cid)
        with open(USERS_FILE, 'w', encoding='utf-8') as f:
            json.dump({'chat_ids': chat_ids}, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"Ошибка при сохранении чата: {e}")
        return False

def load_scheduled_messages():
    """Загружает список запланированных сообщений"""
    if os.path.exists(SCHEDULED_MESSAGES_FILE):
        try:
            with open(SCHEDULED_MESSAGES_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Ошибка при загрузке запланированных сообщений: {e}")
            return []
    return []

def save_scheduled_messages(messages):
    """Сохраняет список запланированных сообщений"""
    try:
        with open(SCHEDULED_MESSAGES_FILE, 'w', encoding='utf-8') as f:
            json.dump(messages, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"Ошибка при сохранении запланированных сообщений: {e}")
        return False

def get_system_schedules(selected_chat_id: Optional[int] = None):
    """Возвращает системные расписания, определенные в самом боте.
    Если передан selected_chat_id — фильтрует по выбранному чату.
    """
    system_items = []

    # 1) Ежедневное сообщение "Че как там по макетам" по будням в указанном чате
    try:
        if os.path.exists(BOT_SETTINGS_FILE):
            with open(BOT_SETTINGS_FILE, 'r', encoding='utf-8') as f:
                s = json.load(f)
                scheduled_chat_id = s.get('scheduled_chat_id')
                scheduled_time = s.get('scheduled_time', '16:00')
                timezone = s.get('scheduled_timezone', 'Europe/Moscow')

                # Показываем только если этот системный чат совпадает с выбранным (если выбран)
                if scheduled_chat_id and (selected_chat_id is None or int(selected_chat_id) == int(scheduled_chat_id)):
                    system_items.append({
                        'id': 'sys_daily_maket',
                        'system': True,
                        'name': 'Че как там по макетам',
                        'chat_id': int(scheduled_chat_id),
                        'message': 'Че как там по макетам',
                        'is_recurring': True,
                        'recurring_pattern': {
                            'days': [1, 2, 3, 4, 5],
                            'time': scheduled_time,
                            'timezone': timezone
                        }
                    })
    except Exception as e:
        print(f"Ошибка при чтении системного расписания: {e}")

    # 2) Пятничная рассылка (пятница 17:50) — для всех чатов
    if selected_chat_id is not None:
        system_items.append({
            'id': f'sys_friday_{selected_chat_id}',
            'system': True,
            'name': 'Пятничная рассылка',
            'chat_id': int(selected_chat_id),
            'message': 'Эх, а скоро дудосинг...',
            'is_recurring': True,
            'recurring_pattern': {
                'days': [5],
                'time': '17:50',
                'timezone': 'Europe/Moscow'
            }
        })

    return system_items

async def send_telegram_message(chat_id, text):
    """Отправляет сообщение в Telegram. Возвращает (success, error_message)."""
    bot = _make_bot()
    try:
        await bot.send_message(chat_id=chat_id, text=text)
        print(f"✅ Сообщение отправлено в чат {chat_id}")
        return True, None
    except Exception as e:
        error_text = str(e)
        print(f"❌ Ошибка при отправке сообщения в чат {chat_id}: {error_text}")
        return False, error_text

def send_message_sync(chat_id, text):
    """Синхронная обертка для отправки сообщения"""
    asyncio.run(send_telegram_message(chat_id, text))

async def get_chat_info(bot, chat_id):
    """Получает информацию о чате"""
    try:
        chat = await bot.get_chat(chat_id)
        if chat.type == 'private':
            return {
                'id': chat_id,
                'title': f"{chat.first_name or ''} {chat.last_name or ''}".strip() or f"User {chat_id}",
                'type': 'private'
            }
        else:
            return {
                'id': chat_id,
                'title': chat.title or f"Chat {chat_id}",
                'type': chat.type
            }
    except Exception as e:
        print(f"Ошибка при получении информации о чате {chat_id}: {e}")
        return {
            'id': chat_id,
            'title': f"Chat {chat_id}",
            'type': 'unknown'
        }

@app.route('/')
def index():
    """Главная страница"""
    return render_template('index.html')

@app.route('/api/chats', methods=['POST'])
def add_chat():
    """Добавляет чат по ID в список (для веб-панели). Тело: {"chat_id": 123456789}"""
    data = request.json or {}
    cid = data.get('chat_id')
    if cid is None:
        return jsonify({'success': False, 'error': 'Укажите chat_id'}), 400
    try:
        cid = int(cid)
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'chat_id должен быть числом'}), 400
    if add_chat_id(cid):
        return jsonify({'success': True, 'message': 'Чат добавлен'})
    return jsonify({'success': False, 'error': 'Не удалось сохранить'}), 500

@app.route('/api/chats', methods=['GET'])
def get_chats():
    """Возвращает список чатов"""
    chat_ids = load_chats()
    bot = _make_bot()

    async def fetch_all():
        result = []
        for cid in chat_ids:
            result.append(await get_chat_info(bot, cid))
        return result

    chats = asyncio.run(fetch_all())
    return jsonify({'chats': chats})

@app.route('/api/send', methods=['POST'])
def send_message():
    """Отправляет сообщение немедленно"""
    data = request.json
    chat_id = data.get('chat_id')
    message = data.get('message')
    
    if not chat_id or not message:
        return jsonify({'success': False, 'error': 'Не указан чат или сообщение'}), 400
    
    try:
        success, error_message = asyncio.run(send_telegram_message(int(chat_id), message))
        if success:
            return jsonify({'success': True, 'message': 'Сообщение отправлено'})
        else:
            return jsonify({'success': False, 'error': error_message or 'Ошибка при отправке'}), 500
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/schedule', methods=['POST'])
def schedule_message():
    """Планирует отправку сообщения"""
    data = request.json
    chat_id = data.get('chat_id')
    message = data.get('message')
    send_time = data.get('send_time')  # ISO format datetime string
    is_recurring = data.get('is_recurring', False)
    recurring_pattern = data.get('recurring_pattern', {})  # {'days': [1,2,3,4,5], 'time': '10:00'}
    
    if not chat_id or not message:
        return jsonify({'success': False, 'error': 'Не указан чат или сообщение'}), 400
    
    try:
        scheduled_messages = load_scheduled_messages()
        
        # Генерируем уникальный ID
        message_id = f"msg_{int(datetime.now().timestamp() * 1000)}"
        
        scheduled_data = {
            'id': message_id,
            'chat_id': int(chat_id),
            'message': message,
            'send_time': send_time,
            'is_recurring': is_recurring,
            'created_at': datetime.now().isoformat()
        }
        
        if is_recurring:
            # Создаем регулярную задачу
            scheduled_data['recurring_pattern'] = recurring_pattern
            
            days_of_week = ','.join(map(str, recurring_pattern.get('days', [1,2,3,4,5])))
            time_parts = recurring_pattern.get('time', '10:00').split(':')
            hour = int(time_parts[0])
            minute = int(time_parts[1])
            
            trigger = CronTrigger(
                day_of_week=days_of_week,
                hour=hour,
                minute=minute,
                timezone=pytz.timezone('Europe/Moscow')
            )
            
            scheduler.add_job(
                send_message_sync,
                trigger=trigger,
                args=[int(chat_id), message],
                id=message_id,
                name=f"Recurring message to {chat_id}"
            )
        else:
            # Создаем одноразовую задачу
            send_datetime = datetime.fromisoformat(send_time.replace('Z', '+00:00'))
            
            trigger = DateTrigger(
                run_date=send_datetime,
                timezone=pytz.timezone('Europe/Moscow')
            )
            
            scheduler.add_job(
                send_message_sync,
                trigger=trigger,
                args=[int(chat_id), message],
                id=message_id,
                name=f"Scheduled message to {chat_id}"
            )
        
        scheduled_messages.append(scheduled_data)
        save_scheduled_messages(scheduled_messages)
        
        return jsonify({
            'success': True, 
            'message': 'Сообщение запланировано',
            'message_id': message_id
        })
    except Exception as e:
        print(f"Ошибка при планировании сообщения: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/scheduled', methods=['GET'])
def get_scheduled():
    """Возвращает список запланированных сообщений"""
    try:
        messages = load_scheduled_messages()

        # Фильтрация по выбранному чату, если передан ?chat_id=
        chat_id_param = request.args.get('chat_id')
        if chat_id_param:
            try:
                cid = int(chat_id_param)
                messages = [m for m in messages if int(m.get('chat_id', -1)) == cid]
            except:
                pass

        # Добавляем системные расписания (read-only)
        system_items = get_system_schedules(int(chat_id_param)) if chat_id_param else []

        return jsonify({'messages': messages + system_items})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/scheduled/<message_id>', methods=['DELETE'])
def delete_scheduled(message_id):
    """Удаляет запланированное сообщение"""
    try:
        messages = load_scheduled_messages()
        messages = [m for m in messages if m['id'] != message_id]
        save_scheduled_messages(messages)
        
        # Удаляем задачу из планировщика
        try:
            scheduler.remove_job(message_id)
        except:
            pass
        
        return jsonify({'success': True, 'message': 'Сообщение удалено'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/scheduled/<message_id>', methods=['PUT'])
def update_scheduled(message_id):
    """Редактирует запланированное сообщение. Поддерживает как пользовательские, так и системные записи.
    Для системных: 
      - sys_daily_maket: можно изменить chat_id и time (HH:MM)
      - sys_friday_*: можно изменить time
    """
    try:
        payload = request.json or {}
        # Пользовательские задачи в файле
        messages = load_scheduled_messages()
        updated = False

        for m in messages:
            if m.get('id') == message_id:
                # Разрешаем менять текст, время и паттерн
                if 'message' in payload:
                    m['message'] = payload['message']
                if m.get('is_recurring') and 'recurring_pattern' in payload:
                    m['recurring_pattern'] = payload['recurring_pattern']
                if 'send_time' in payload:
                    m['send_time'] = payload['send_time']
                if 'chat_id' in payload:
                    m['chat_id'] = int(payload['chat_id'])
                save_scheduled_messages(messages)
                updated = True
                break

        if updated:
            return jsonify({'success': True, 'message': 'Задача обновлена'})

        # Системные задачи
        if message_id == 'sys_daily_maket':
            # Обновляем bot_settings.json
            settings = {}
            if os.path.exists(BOT_SETTINGS_FILE):
                with open(BOT_SETTINGS_FILE, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
            # Допустимые поля: scheduled_chat_id, scheduled_time
            if 'chat_id' in payload:
                settings['scheduled_chat_id'] = int(payload['chat_id'])
            if 'time' in payload:
                settings['scheduled_time'] = payload['time']
            # Часовой пояс сохраняем прежним
            if 'scheduled_timezone' not in settings:
                settings['scheduled_timezone'] = 'Europe/Moscow'
            with open(BOT_SETTINGS_FILE, 'w', encoding='utf-8') as f:
                json.dump(settings, f, ensure_ascii=False, indent=2)
            return jsonify({'success': True, 'message': 'Системное расписание обновлено'})

        if message_id.startswith('sys_friday_'):
            # Эти системные шаблоны фиксированы в коде; позволим менять только время в интерфейсе
            # Ничего устойчивого сохранять некуда, поэтому возвращаем success и
            # в будущем можно вынести в отдельный конфиг. Пока — no-op для совместимости UI.
            return jsonify({'success': True, 'message': 'Системная запись обновлена (временное поведение)'})

        return jsonify({'success': False, 'error': 'Задача не найдена'}), 404
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    print("🌐 Запуск веб-интерфейса...")
    print(f"📍 Откройте в браузере: http://localhost:{port}" if port == 5001 else f"📍 Слушаю порт {port} (Railway)")
    app.run(host='0.0.0.0', port=port, debug=(port == 5001))
