#!/usr/bin/env python3
"""
Запуск бота и веб-панели в одном процессе.
Общий рабочий каталог — один bot_users.json: чаты, в которых активировали бота,
сразу появляются в веб-интерфейсе без ручного добавления.
"""
import os
import sys
import threading

def run_bot():
    """Запуск бота в отдельном потоке (блокирующий run_polling)."""
    import bot
    bot.main()

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
