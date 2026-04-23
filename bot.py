import os
import requests
import socket
import time
import re
import json
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from flask import Flask, request
import asyncio
import threading

# Flask приложение для вебхука
app = Flask(__name__)

# Конфигурация
TOKEN = os.environ.get("BOT_TOKEN")
PORT = int(os.environ.get("PORT", 10000))
RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", "")  # Render добавит сам
MAX_LATENCY = 2.0

DEFAULT_PORTS = {
    'vless': 443, 'vmess': 443, 'trojan': 443,
    'ss': 8388, 'ssr': 8388, 'hysteria2': 443,
    'hysteria': 443, 'tuic': 443, 'juicity': 443,
    'socks': 1080, 'http': 8080, 'https': 443, 'wireguard': 51820,
}

def extract_host_port(line):
    line = line.strip()
    if not line or line.startswith('#'):
        return None, None
    
    protocol_match = re.match(r'^(\w+)://', line)
    if not protocol_match:
        return None, None
    
    protocol = protocol_match.group(1).lower()
    
    if protocol == 'vmess':
        try:
            base64_part = line[8:]
            base64_part = base64_part.split('#')[0]
            import base64
            padding = 4 - len(base64_part) % 4
            if padding != 4:
                base64_part += '=' * padding
            decoded = base64.b64decode(base64_part).decode('utf-8')
            config = json.loads(decoded)
            return config.get('add'), int(config.get('port', 443))
        except:
            pass
    
    patterns = [
        r'@\[?([a-zA-Z0-9\.\-]+)\]?:(\d+)',
        r'@([a-zA-Z0-9\.\-]+):(\d+)',
        r'://\[?([a-zA-Z0-9\.\-]+)\]?:(\d+)',
        r'://([a-zA-Z0-9\.\-]+):(\d+)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, line)
        if match:
            return match.group(1), int(match.group(2))
    
    host_match = re.search(r'@([a-zA-Z0-9\.\-]+)(?:/|\?|#|$)', line)
    if host_match and protocol in DEFAULT_PORTS:
        return host_match.group(1), DEFAULT_PORTS[protocol]
    
    return None, None

def check_server(host, port):
    try:
        try:
            ip = socket.gethostbyname(host)
        except:
            return None
        
        start = time.time()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        result = sock.connect_ex((ip, port))
        latency = time.time() - start
        sock.close()
        
        if result == 0:
            return latency
        return None
    except:
        return None

def clean_subscription(content, max_latency):
    lines = content.strip().split('\n')
    clean_lines = []
    working = 0
    dead = 0
    unsupported = 0
    total = 0
    
    for line in lines:
        original_line = line
        line = line.strip()
        
        if not line or line.startswith('#'):
            clean_lines.append(original_line)
            continue
        
        if not re.match(r'^\w+://', line):
            clean_lines.append(original_line)
            continue
        
        total += 1
        host, port = extract_host_port(line)
        
        if host and port:
            latency = check_server(host, port)
            if latency and latency <= max_latency:
                clean_lines.append(original_line)
                working += 1
            else:
                dead += 1
        else:
            clean_lines.append(original_line)
            unsupported += 1
    
    result = '\n'.join(clean_lines)
    return result, working, dead, unsupported, total

# --- Telegram Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *VPN Subscription Cleaner*\n\n"
        "Отправь мне ссылку на подписку — я проверю все сервера и верну чистый файл.\n\n"
        "📋 *Протоколы:* VLESS, VMess, Trojan, SS, SSR, Hysteria, TUIC, WireGuard\n"
        "⚡️ *Макс. пинг:* 2000 мс",
        parse_mode='Markdown'
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    
    if not text.startswith('http://') and not text.startswith('https://'):
        await update.message.reply_text("❌ Отправь ссылку (http:// или https://)")
        return
    
    status_msg = await update.message.reply_text("⏳ Скачиваю...")
    
    try:
        response = requests.get(text, timeout=15, headers={'User-Agent': 'VPN-Cleaner/1.0'})
        response.raise_for_status()
        
        await status_msg.edit_text("🔍 Проверяю сервера...")
        
        clean_content, working, dead, unsupported, total = clean_subscription(response.text, MAX_LATENCY)
        
        stats = f"📊 Всего: {total}\n✅ Рабочих: {working}\n❌ Удалено: {dead}"
        if unsupported > 0:
            stats += f"\n⚠️ Пропущено: {unsupported}"
        
        if working == 0:
            await status_msg.edit_text(f"{stats}\n\nВсе сервера не прошли проверку.", parse_mode='Markdown')
            return
        
        filename = f"clean_{int(time.time())}.txt"
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(clean_content)
        
        await status_msg.delete()
        
        with open(filename, 'rb') as f:
            await update.message.reply_document(
                document=f,
                filename="clean_subscription.txt",
                caption=stats,
                parse_mode='Markdown'
            )
        
        os.remove(filename)
        
    except Exception as e:
        await status_msg.edit_text(f"❌ Ошибка: {str(e)[:200]}", parse_mode='Markdown')

# --- Flask + Webhook ---

@app.route(f'/{TOKEN}', methods=['POST'])
def webhook():
    """Принимает обновления от Telegram"""
    update = Update.de_json(request.get_json(force=True), telegram_app.bot)
    asyncio.run(telegram_app.process_update(update))
    return 'OK'

@app.route('/')
def index():
    return 'Bot is running'

# --- Запуск ---

telegram_app = None

def main():
    global telegram_app
    
    if not TOKEN:
        print("❌ BOT_TOKEN не задан!")
        return
    
    telegram_app = Application.builder().token(TOKEN).build()
    telegram_app.add_handler(CommandHandler("start", start))
    telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Устанавливаем вебхук
    if RENDER_URL:
        webhook_url = f"{RENDER_URL}/{TOKEN}"
        asyncio.run(telegram_app.bot.set_webhook(url=webhook_url))
        print(f"✅ Вебхук установлен: {webhook_url}")
    
    # Запускаем Flask
    app.run(host='0.0.0.0', port=PORT)

if __name__ == "__main__":
    main()
