import asyncio
import os
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
import ccxt.async_support as ccxt

# --- [НАСТРОЙКИ] ---
# Решаем проблему с Protobuf программно
os.environ["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"

API_TOKEN = 'ТВОЙ_ТОКЕН_БОТА' # Получи у @BotFather

# Настройки для обхода блокировок (User-Agent и таймауты)
EXCHANGE_CONFIG = {
    'enableRateLimit': True,
    'timeout': 30000,
    'headers': {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
}
# --------------------

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

async def get_common_pairs():
    """Функция парсинга общих монет"""
    binance = ccxt.binance(EXCHANGE_CONFIG)
    mexc = ccxt.mexc(EXCHANGE_CONFIG)
    
    try:
        # Загружаем рынки параллельно для скорости
        await asyncio.gather(binance.load_markets(), mexc.load_markets())
        
        # Фильтруем только Spot USDT
        b_pairs = {s for s in binance.symbols if '/USDT' in s and ':' not in s}
        m_pairs = {s for s in mexc.symbols if '/USDT' in s and ':' not in s}
        
        common = sorted(list(b_pairs.intersection(m_pairs)))
        return common
    except Exception as e:
        logging.error(f"Ошибка парсинга: {e}")
        return None
    finally:
        await binance.close()
        await mexc.close()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("Привет! Напиши /parse, чтобы я нашел общие монеты на Binance и MEXC.")

@dp.message(Command("parse"))
async def cmd_parse(message: types.Message):
    status_msg = await message.answer("🔍 Опрашиваю биржи, подожди...")
    
    pairs = await get_common_pairs()
    
    if pairs:
        count = len(pairs)
        # ТГ не даст отправить слишком длинное сообщение, берем первые 80 монет
        list_str = "\n".join(pairs[:80]) 
        response = (f"✅ Найдено общих пар: **{count}**\n\n"
                    f"**Топ монет для работы:**\n`{list_str}`\n\n"
                    f"🔗 _Показаны первые 80 из {count}_")
        await status_msg.edit_text(response, parse_mode="Markdown")
    else:
        await status_msg.edit_text("❌ Не удалось получить данные. Проверь логи сервера или IP региона.")

async def main():
    print("🤖 Бот запущен и ждет команд...")
    await dp.start_polling(bot)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Бот остановлен")
