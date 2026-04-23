import os
import requests
import socket
import time
import re
import json
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Конфигурация
TOKEN = os.environ.get("BOT_TOKEN")
MAX_LATENCY = 2.0  # Максимальный пинг в секундах

# Поддерживаемые протоколы и их порты по умолчанию
DEFAULT_PORTS = {
    'vless': 443,
    'vmess': 443,
    'trojan': 443,
    'ss': 8388,      # Shadowsocks
    'ssr': 8388,     # ShadowsocksR
    'hysteria2': 443,
    'hysteria': 443,
    'tuic': 443,
    'juicity': 443,
    'socks': 1080,
    'http': 8080,
    'https': 443,
    'wireguard': 51820,
}

def extract_host_port(line):
    """
    Извлекает хост и порт из строки подписки.
    Поддерживает форматы:
    - protocol://...@host:port?...
    - protocol://...@host:port#
    - protocol://...@host:port/
    - vmess://base64{...}
    """
    line = line.strip()
    
    # Пропускаем комментарии и пустые строки
    if not line or line.startswith('#'):
        return None, None
    
    # Определяем протокол
    protocol_match = re.match(r'^(\w+)://', line)
    if not protocol_match:
        return None, None
    
    protocol = protocol_match.group(1).lower()
    
    # Обработка VMess (закодирован в base64 JSON)
    if protocol == 'vmess':
        try:
            # Извлекаем base64 часть после vmess://
            base64_part = line[8:]  # Пропускаем 'vmess://'
            # Убираем всё после # (название)
            base64_part = base64_part.split('#')[0]
            
            import base64
            # Добавляем padding если нужно
            padding = 4 - len(base64_part) % 4
            if padding != 4:
                base64_part += '=' * padding
            
            decoded = base64.b64decode(base64_part).decode('utf-8')
            config = json.loads(decoded)
            return config.get('add'), int(config.get('port', 443))
        except:
            # Если не получилось декодировать — пробуем извлечь из строки
            pass
    
    # Стандартный парсинг для остальных протоколов
    # Паттерн: protocol://uuid@host:port или protocol://host:port
    patterns = [
        r'@\[?([a-zA-Z0-9\.\-]+)\]?:(\d+)',  # @host:port или @[host]:port
        r'@([a-zA-Z0-9\.\-]+):(\d+)',         # @host:port
        r'://\[?([a-zA-Z0-9\.\-]+)\]?:(\d+)', # ://host:port без @
        r'://([a-zA-Z0-9\.\-]+):(\d+)',       # ://host:port без @
    ]
    
    for pattern in patterns:
        match = re.search(pattern, line)
        if match:
            host = match.group(1)
            port = int(match.group(2))
            return host, port
    
    # Если порт не найден, но хост есть — используем порт по умолчанию
    host_match = re.search(r'@([a-zA-Z0-9\.\-]+)(?:/|\?|#|$)', line)
    if host_match and protocol in DEFAULT_PORTS:
        return host_match.group(1), DEFAULT_PORTS[protocol]
    
    return None, None

def check_server(host, port):
    """Проверяет TCP соединение и возвращает задержку"""
    try:
        # Резолвим DNS отдельно для точного замера
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
    """Очищает подписку от мёртвых и медленных серверов"""
    lines = content.strip().split('\n')
    clean_lines = []
    working = 0
    dead = 0
    unsupported = 0
    total = 0
    
    for line in lines:
        original_line = line
        line = line.strip()
        
        # Сохраняем комментарии и пустые строки
        if not line or line.startswith('#'):
            clean_lines.append(original_line)
            continue
        
        # Проверяем, является ли строка VPN-ссылкой
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
                print(f"✅ [{int(latency*1000)}ms] {host}:{port}")
            else:
                dead += 1
                print(f"❌ [DEAD/SLOW] {host}:{port}")
        else:
            # Не смогли извлечь хост:порт — сохраняем как есть
            clean_lines.append(original_line)
            unsupported += 1
            print(f"⚠️ [UNKNOWN] {line[:80]}...")
    
    result = '\n'.join(clean_lines)
    return result, working, dead, unsupported, total

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    await update.message.reply_text(
        "👋 *VPN Subscription Cleaner*\n\n"
        "Отправь мне ссылку на подписку — я проверю все сервера и верну чистый файл "
        "только с рабочими узлами.\n\n"
        "📋 *Поддерживаемые протоколы:*\n"
        "• VLESS\n"
        "• VMess\n"
        "• Trojan\n"
        "• Shadowsocks (SS)\n"
        "• ShadowsocksR (SSR)\n"
        "• Hysteria / Hysteria2\n"
        "• TUIC\n"
        "• Juicity\n"
        "• HTTP/HTTPS/SOCKS\n"
        "• WireGuard\n\n"
        "⚡️ *Максимальный пинг:* 2000 мс\n\n"
        "Просто пришли ссылку, и я всё сделаю!",
        parse_mode='Markdown'
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка входящих сообщений со ссылками"""
    text = update.message.text.strip()
    
    # Проверяем, что это ссылка
    if not text.startswith('http://') and not text.startswith('https://'):
        await update.message.reply_text(
            "❌ Отправь корректную ссылку на подписку "
            "(начинается с http:// или https://)"
        )
        return
    
    # Отправляем статус
    status_msg = await update.message.reply_text(
        "⏳ *Скачиваю подписку...*",
        parse_mode='Markdown'
    )
    
    try:
        # Скачиваем подписку
        response = requests.get(text, timeout=15, headers={
            'User-Agent': 'VPN-Subscription-Cleaner/1.0'
        })
        response.raise_for_status()
        
        await status_msg.edit_text(
            "🔍 *Проверяю сервера...*\n"
            "Это может занять до минуты в зависимости от количества узлов.",
            parse_mode='Markdown'
        )
        
        # Очищаем
        clean_content, working, dead, unsupported, total = clean_subscription(
            response.text, MAX_LATENCY
        )
        
        # Формируем статистику
        stats = (
            f"📊 *Статистика:*\n"
            f"• Всего серверов: {total}\n"
            f"• ✅ Рабочих: {working}\n"
            f"• ❌ Удалено: {dead}\n"
        )
        if unsupported > 0:
            stats += f"• ⚠️ Пропущено (неизвестный формат): {unsupported}\n"
        
        if working == 0:
            await status_msg.edit_text(
                f"{stats}\n"
                f"К сожалению, все сервера не прошли проверку. "
                f"Попробуй позже или проверь ссылку.",
                parse_mode='Markdown'
            )
            return
        
        # Сохраняем во временный файл
        timestamp = int(time.time())
        filename = f"clean_sub_{timestamp}.txt"
        
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(clean_content)
        
        # Отправляем файл
        await status_msg.delete()
        
        with open(filename, 'rb') as f:
            await update.message.reply_document(
                document=f,
                filename=f"clean_subscription.txt",
                caption=stats,
                parse_mode='Markdown'
            )
        
        # Удаляем временный файл
        os.remove(filename)
        
    except requests.exceptions.Timeout:
        await status_msg.edit_text(
            "❌ Таймаут при скачивании. Сервер с подпиской не отвечает.",
            parse_mode='Markdown'
        )
    except requests.exceptions.HTTPError as e:
        await status_msg.edit_text(
            f"❌ Ошибка HTTP: {e.response.status_code}",
            parse_mode='Markdown'
        )
    except requests.exceptions.RequestException as e:
        await status_msg.edit_text(
            f"❌ Ошибка при скачивании:\n`{str(e)[:200]}`",
            parse_mode='Markdown'
        )
    except Exception as e:
        await status_msg.edit_text(
            f"❌ Неизвестная ошибка:\n`{str(e)[:200]}`",
            parse_mode='Markdown'
        )

def main():
    """Запуск бота"""
    if not TOKEN:
        print("❌ Ошибка: Не задан BOT_TOKEN!")
        print("Добавь переменную окружения BOT_TOKEN и перезапусти.")
        return
    
    print("🤖 Запуск VPN Subscription Cleaner Bot...")
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("✅ Бот запущен. Ожидаю сообщения...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
