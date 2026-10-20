#!/bin/bash

cd "$(dirname "$0")" || exit 1

if [ -d "venv" ]; then
    source venv/bin/activate
fi

echo "🖥️  Обзор доски S:P9"
echo "Сначала выбери область с доской, затем область с All workspace updates."
echo

python3 board_review.py --capture
STATUS=$?

echo
if [ "$STATUS" -eq 0 ]; then
    echo "Готово."
else
    echo "Обзор не создан. Смотри ошибку выше."
fi
read -r -p "Нажми Enter, чтобы закрыть окно…"
exit "$STATUS"
