#!/usr/bin/env python3
"""
Запуск бота и веб-панели в одном процессе.
Общий рабочий каталог — один bot_users.json: чаты, в которых активировали бота,
сразу появляются в веб-интерфейсе без ручного добавления.
"""
import os
import threading
import time

from app_data import acquire_bot_lock, ensure_data_dir, resolve_data_dir

_ROOT = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = resolve_data_dir(_ROOT)
ensure_data_dir(_DATA_DIR)
os.environ["SLASHBOT_DATA_DIR"] = _DATA_DIR
os.chdir(_ROOT)
_users_file = os.path.join(_DATA_DIR, "bot_users.json")
print(f"[start_both] Данные: {_DATA_DIR}", flush=True)
print(f"[start_both] bot_users.json: {_users_file}", flush=True)

acquire_bot_lock(_DATA_DIR)


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
