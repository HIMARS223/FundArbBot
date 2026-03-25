import asyncio
import logging
import os
import json
from aiogram import Bot
import ccxt.async_support as ccxt
from aiohttp import web

# --- НАСТРОЙКИ (Берем из среды) ---
API_TOKEN = os.getenv('BOT_TOKEN') # Скрытый токен
CHAT_ID = os.getenv('CHAT_ID')     # Твой ID (тоже лучше скрыть)

if not API_TOKEN:
    print("❌ ОШИБКА: Переменная BOT_TOKEN не найдена!")
    exit(1)

THRESHOLD = 1.2  
SLEEP_BETWEEN_SYMBOLS = 0.2 

bot = Bot(token=API_TOKEN)
logging.basicConfig(level=logging.INFO)

# --- ВЕБ-СЕРВЕР (Для облачных хостингов) ---
async def handle(request):
    return web.Response(text="Arbitrage Bot is running...")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    # Автоматический выбор порта (Render дает свой, иначе 10000)
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"🌐 Веб-сервер запущен на порту {port}")

# --- ЛОГИКА АРБИТРАЖА ---
async def get_common_symbols(ex1, ex2):
    await ex1.load_markets()
    await ex2.load_markets()
    symbols1 = [s for s in ex1.symbols if '/USDT' in s and ':' not in s]
    symbols2 = [s for s in ex2.symbols if '/USDT' in s and ':' not in s]
    return list(set(symbols1).intersection(symbols2))

async def check_pair(ex1, ex2, symbol):
    try:
        t1, t2 = await asyncio.gather(
            ex1.fetch_ticker(symbol),
            ex2.fetch_ticker(symbol)
        )
        # Спред 1: Покупка Bybit, продажа MEXC
        spread1 = ((t2['bid'] - t1['ask']) / t1['ask']) * 100
        # Спред 2: Покупка MEXC, продажа Bybit
        spread2 = ((t1['bid'] - t2['ask']) / t2['ask']) * 100

        if spread1 > THRESHOLD:
            await send_alert(symbol, "Bybit", "MEXC", t1['ask'], t2['bid'], spread1)
        if spread2 > THRESHOLD:
            await send_alert(symbol, "MEXC", "Bybit", t2['ask'], t1['bid'], spread2)
    except:
        pass

async def send_alert(symbol, buy_ex, sell_ex, buy_p, sell_p, spread):
    text = (f"🚀 **Найден спред: {spread:.2f}%**\n"
            f"💎 Пара: #{symbol.replace('/USDT', '')}\n\n"
            f"🛒 Купить [{buy_ex}]: `{buy_p}`\n"
            f"💰 Продать [{sell_ex}]: `{sell_p}`\n"
            f"📊 Чистый профит (прим): ~{spread-0.2:.2f}%")
    try:
        await bot.send_message(CHAT_ID, text, parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Ошибка отправки в ТГ: {e}")

async def scanner_loop():
    bybit = ccxt.bybit({'enableRateLimit': True})
    mexc = ccxt.mexc({'enableRateLimit': True})
    
    print("🔄 Загрузка общих пар...")
    symbols = await get_common_symbols(bybit, mexc)
    print(f"✅ Найдено {len(symbols)} пар. Мониторинг запущен.")

    while True:
        for symbol in symbols:
            await check_pair(bybit, mexc, symbol)
            await asyncio.sleep(SLEEP_BETWEEN_SYMBOLS)
        
        print("♻️ Круг завершен. Рестарт через 10 сек...")
        await asyncio.sleep(10)

async def main():
    # Запуск сервера и сканера одновременно
    await asyncio.gather(
        start_web_server(),
        scanner_loop()
    )

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
