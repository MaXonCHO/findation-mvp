#!/usr/bin/env python3
"""
Локальный веб-сервер для тестирования Findation
Запускает сервер на порту 3000 для статических файлов
"""

import http.server
import socketserver
import webbrowser
import os
from urllib.parse import urlparse

class CustomHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()
        self.end_headers()

def start_server():
    PORT = 3000
    DIRECTORY = "/Users/lovelnpvlv/Documents/СкинКод2/findation_mvp"
    
    # Переходим в директорию
    os.chdir(DIRECTORY)
    
    # Создаем сервер
    Handler = CustomHTTPRequestHandler
    httpd = socketserver.TCPServer(("", PORT), Handler)
    
    print(f"🚀 Findation локальный сервер запущен!")
    print(f"📍 Директория: {DIRECTORY}")
    print(f"🌐 URL: http://localhost:{PORT}")
    print(f"🎯 Luxury Interface: http://localhost:{PORT}/findation_luxury.html")
    print(f"📱 Pro Interface: http://localhost:{PORT}/findation_pro.html")
    print(f"🔍 Simple Interface: http://localhost:{PORT}/user_interface.html")
    print(f"⚙️  API Docs: http://localhost:8000/docs")
    print(f"🛑 Нажми Ctrl+C для остановки")
    print()
    
    # Автоматически открываем браузер
    try:
        webbrowser.open(f"http://localhost:{PORT}/findation_luxury.html")
    except:
        pass
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 Сервер остановлен")
        httpd.server_close()

if __name__ == "__main__":
    start_server()
