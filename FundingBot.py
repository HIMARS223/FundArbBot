import asyncio
import os
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
import ccxt.async_support as ccxt

# --- [НАСТРОЙКИ] ---
os.environ["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"
API_TOKEN = '8701958512:AAHn1_Eq1MDIaeU7F6wuxTBXX33mgRkXzXM'

# Глобальные объекты бирж (создаем один раз)
EXCHANGE_CONFIG = {
    'enableRateLimit': True, 
    'timeout': 20000,
    'headers': {'User-Agent': 'Mozilla/5.0...'}
}
binance = ccxt.binance(EXCHANGE_CONFIG)
mexc = ccxt.mexc(EXCHANGE_CONFIG)

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# Хранилище общих пар
common_pairs = []

async def get_common_pairs():
    """Функция парсинга общих монет (один раз при старте)"""
    global common_pairs
    if common_pairs: return common_pairs # Если уже спарсили, возвращаем кэш

    print("📡 Загружаем рынки...")
    try:
        await asyncio.gather(binance.load_markets(), mexc.load_markets())
        b_pairs = {s for s in binance.symbols if '/USDT' in s and ':' not in s}
        m_pairs = {s for s in mexc.symbols if '/USDT' in s and ':' not in s}
        common_pairs = sorted(list(b_pairs.intersection(m_pairs)))
        return common_pairs
    except Exception as e:
        logging.error(f"Ошибка загрузки рынков: {e}")
        return []

async def check_spread(symbol):
    """Запрос цен и расчет спреда для ОДНОЙ пары"""
    try:
        # Запрашиваем стаканы (Order Book) параллельно для скорости
        # Нам нужны лучшие цены: ask (покупка) и bid (продажа)
        b_ticker, m_ticker = await asyncio.gather(
            binance.fetch_ticker(symbol),
            mexc.fetch_ticker(symbol)
        )
        
        results = []

        # Направление 1: Купить B, Продать M
        b_ask = b_ticker['ask']
        m_bid = m_ticker['bid']
        if b_ask and m_bid:
            spread1 = ((m_bid - b_ask) / b_ask) * 100
            if spread1 > 0.01: # Фильтруем только положительный спред
                results.append((symbol, "Binance", "MEXC", b_ask, m_bid, spread1))

        # Направление 2: Купить M, Продать B
        m_ask = m_ticker['ask']
        b_bid = b_ticker['bid']
        if m_ask and b_bid:
            spread2 = ((b_bid - m_ask) / m_ask) * 100
            if spread2 > 0.01:
                results.append((symbol, "MEXC", "Binance", m_ask, b_bid, spread2))
        
        return results

    except Exception as e:
        #logging.error(f"Ошибка запроса цен {symbol}: {e}")
        return []

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("Я готов! Напиши `/scan` для поиска спреда между Binance и MEXC.\n*(Кэш общих пар загрузится при первом запуске)*", parse_mode="Markdown")

@dp.message(Command("scan"))
async def cmd_scan(message: types.Message):
    global common_pairs
    status_msg = await message.answer("🔄 Запускаю сканер... Это может занять около 30 сек.")
    
    # Гарантируем, что пары загружены
    if not common_pairs:
        await status_msg.edit_text("⏳ Загружаю список общих пар (первый запуск)...")
        pairs = await get_common_pairs()
        if not pairs:
            await status_msg.edit_text("❌ Ошибка загрузки рынков. Проверь прокси/IP.")
            return

    found_spreads = []
    
    # Чтобы не получить бан за спам запросами, сканируем только первые 20 пар
    # И делаем небольшую паузу между запросами
    pairs_to_scan = common_pairs[:20] 
    
    for i, symbol in enumerate(pairs_to_scan):
        await status_msg.edit_text(f"📊 Сканирую {i+1}/{len(pairs_to_scan)}: **{symbol}**", parse_mode="Markdown")
        spread_info = await check_spread(symbol)
        if spread_info:
            found_spreads.extend(spread_info)
        await asyncio.sleep(0.5) # Пауза 500мс между запросами

    # Сортируем по размеру спреда (от большего к меньшему)
    found_spreads.sort(key=lambda x: x[5], reverse=True)

    if found_spreads:
        response = "🚀 **НАЙДЕНЫ СПРЕДЫ**:\n\n"
        for s in found_spreads[:10]: # Показываем топ-10 спредов
            sym, b_ex, s_ex, b_p, s_p, spr = s
            # Формируем красивое сообщение
            response += (f"🪙 **#{sym.replace('/USDT', '')}** — `{spr:.2f}%` \n"
                        f"🛒 Купить [{b_ex}]: `{b_p}`\n"
                        f"💰 Продать [{s_ex}]: `{s_p}`\n"
                        f"📊 Чистый профит (прим): ~{spr-0.2:.2f}%\n"
                        f"-------------------\n")
        await status_msg.edit_text(response, parse_mode="Markdown")
    else:
        await status_msg.edit_text("💡 Сканирование завершено. Хороших спредов (>0.01%) не найдено.")

async def main():
    print("🤖 Сканер цен запущен!")
    await dp.start_polling(bot)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Сканер остановлен")
