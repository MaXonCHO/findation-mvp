#!/bin/bash

# Findation Development Server Launcher
# Запускает API и локальный веб-сервер

echo "🚀 Запуск Findation Development Environment"
echo "=================================="

# Проверяем виртуальное окружение
if [ ! -d "../.venv" ]; then
    echo "❌ Виртуальное окружение не найдено!"
    echo "Создай виртуальное окружение:"
    echo "cd .. && python3 -m venv .venv"
    echo "source .venv/bin/activate"
    echo "pip install -r findation_mvp/requirements.txt"
    exit 1
fi

# Активируем виртуальное окружение
echo "📦 Активация виртуального окружения..."
source ../.venv/bin/activate

# Проверяем зависимости
echo "🔍 Проверка зависимостей..."
pip install -r requirements.txt > /dev/null 2>&1

# Запускаем API сервер в фоне
echo "🔧 Запуск API сервера на порту 8000..."
python api.py &
API_PID=$!

# Ждем запуска API
sleep 3

# Проверяем, запустился ли API
if ! kill -0 $API_PID 2>/dev/null; then
    echo "❌ API сервер не запустился!"
    exit 1
fi

# Запускаем веб-сервер для статических файлов
echo "🌐 Запуск веб-сервера на порту 3000..."
python3 start_local_server.py &
WEB_PID=$!

echo ""
echo "✅ Findation Development Environment запущен!"
echo "=================================="
echo "🎯 Luxury Interface: http://localhost:3000/findation_luxury.html"
echo "📱 Pro Interface: http://localhost:3000/findation_pro.html"
echo "🔍 Simple Interface: http://localhost:3000/user_interface.html"
echo "⚙️  API Documentation: http://localhost:8000/docs"
echo "🛑 Нажми Ctrl+C для остановки всех серверов"
echo ""

# Функция для очистки
cleanup() {
    echo ""
    echo "🛑 Остановка серверов..."
    kill $API_PID 2>/dev/null
    kill $WEB_PID 2>/dev/null
    echo "✅ Все серверы остановлены"
    exit 0
}

# Ловим Ctrl+C
trap cleanup INT

# Ждем
wait
