#!/bin/bash

cd "$(dirname "$0")"

echo "🛑 Останавливаем все старые экземпляры бота..."
pkill -9 -f "python.*start_both.py" 2>/dev/null || true
pkill -9 -f "python.*bot.py" 2>/dev/null || true
sleep 3
# Проверяем, что ничего не осталось (иначе будет Conflict в Telegram)
if pgrep -f "python.*(start_both|bot).py" >/dev/null; then
    echo "⚠️  Ещё остались процессы бота, ждём..."
    sleep 3
    pkill -9 -f "python.*(start_both|bot).py" 2>/dev/null || true
    sleep 2
fi

echo "✅ Запускаем бота с автоматическим перезапуском..."
echo "💡 Для остановки нажмите Ctrl+C"
echo ""

# Бесконечный цикл для автоматического перезапуска
while true; do
    python3 bot.py
    EXIT_CODE=$?
    
    # Если вышли по Ctrl+C (код 130), прерываем цикл
    if [ $EXIT_CODE -eq 130 ]; then
        echo ""
        echo "👋 Бот остановлен пользователем"
        break
    fi
    
    # Если произошла ошибка, перезапускаем через 5 секунд
    echo ""
    echo "⚠️  Процесс завершился с кодом: $EXIT_CODE"
    echo "🔄 Перезапуск через 5 секунд..."
    sleep 5
    echo "=" 
    echo ""
done
