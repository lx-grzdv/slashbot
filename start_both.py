#!/usr/bin/env python3
"""
Запуск бота и веб-панели в одном процессе.
Общий рабочий каталог — один bot_users.json: чаты, в которых активировали бота,
сразу появляются в веб-интерфейсе без ручного добавления.
"""
import os
import sys
import threading

# Один каталог для данных — и бот, и веб читают/пишут один и тот же bot_users.json
_ROOT = os.path.dirname(os.path.abspath(__file__))
os.environ['SLASHBOT_DATA_DIR'] = _ROOT
os.chdir(_ROOT)
_users_file = os.path.join(_ROOT, "bot_users.json")
print(f"[start_both] Данные: {_users_file}", flush=True)

def run_bot():
    """Запуск бота в отдельном потоке. В новом потоке нет event loop — создаём свой для asyncio."""
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        import bot
        bot.main()
    except Exception as e:
        print(f"[start_both] Ошибка бота: {e}", flush=True)
        import traceback
        traceback.print_exc()
    finally:
        loop.close()

def main():
    port = int(os.environ.get('PORT', 5001))
    # Бот — в фоновом потоке
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    # Небольшая задержка, чтобы бот успел стартовать
    import time
    time.sleep(2)
    # Веб-панель — в основном потоке (слушает PORT для Railway)
    import web_app
    print(f"🌐 Веб-панель: http://0.0.0.0:{port}")
    web_app.app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

if __name__ == '__main__':
    main()
