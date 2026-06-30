#!/usr/bin/env python3
"""
Запуск бота и веб-панели в одном процессе.
Общий рабочий каталог — один bot_users.json: чаты, в которых активировали бота,
сразу появляются в веб-интерфейсе без ручного добавления.
"""
import os
import threading
import time

# Один каталог для данных — и бот, и веб читают/пишут один и тот же bot_users.json
_ROOT = os.path.dirname(os.path.abspath(__file__))
os.environ['SLASHBOT_DATA_DIR'] = _ROOT
os.chdir(_ROOT)
_users_file = os.path.join(_ROOT, "bot_users.json")
print(f"[start_both] Данные: {_users_file}", flush=True)


def run_web(port: int) -> None:
    import web_app
    print(f"🌐 Веб-панель: http://0.0.0.0:{port}", flush=True)
    web_app.app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)


def main():
    port = int(os.environ.get('PORT', 5001))
    # Flask в фоне — Railway healthcheck на PORT; бот в главном потоке (run_polling + сигналы)
    web_thread = threading.Thread(target=run_web, args=(port,), daemon=True)
    web_thread.start()
    time.sleep(1)
    import bot
    bot.main()


if __name__ == '__main__':
    main()
