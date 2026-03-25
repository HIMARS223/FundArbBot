import asyncio
import os
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
import ccxt.async_support as ccxt

# --- [КОНФИГ] ---
os.environ["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"
API_TOKEN = 'ТВОЙ_ТОКЕН'

EXCHANGE_CONFIG = {
    'enableRateLimit': True,
    'headers': {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
}

bot = Bot(token=API_TOKEN)
dp = Dispatcher()
binance = ccxt.binance(EXCHANGE_CONFIG)
mexc = ccxt.mexc(EXCHANGE_CONFIG)

async def get_all_spreads():
    try:
        # 1. Загружаем рынки (если еще не загружены)
        await asyncio.gather(binance.load_markets(), mexc.load_markets())
        
        # 2. Находим ВСЕ общие пары USDT
        b_pairs = {s for s in binance.symbols if '/USDT' in s and ':' not in s}
        m_pairs = {s for s in mexc.symbols if '/USDT' in s and ':' not in s}
        common = list(b_pairs.intersection(m_pairs))

        # 3. ПОЛУЧАЕМ ВСЕ ЦЕНЫ ОДНИМ МАХОМ (fetch_tickers)
        # Это в сотни раз быстрее, чем цикл
        print(f"📡 Запрашиваю цены для {len(common)} монет...")
        b_tickers, m_tickers = await asyncio.gather(
            binance.fetch_tickers(common),
            mexc.fetch_tickers(common)
        )

        spreads = []

        for symbol in common:
            if symbol in b_tickers and symbol in m_tickers:
                bt = b_tickers[symbol]
                mt = m_tickers[symbol]

                # Проверяем наличие цен (ask/bid)
                if not (bt['ask'] and bt['bid'] and mt['ask'] and mt['bid']):
                    continue

                # Направление: Купить на Binance -> Продать на MEXC
                s1 = ((mt['bid'] - bt['ask']) / bt['ask']) * 100
                if s1 > 0.1: # Порог 0.1%
                    spreads.append({'sym': symbol, 'buy': 'Binance', 'sell': 'MEXC', 'price_b': bt['ask'], 'price_s': mt['bid'], 'val': s1})

                # Направление: Купить на MEXC -> Продать на Binance
                s2 = ((bt['bid'] - mt['ask']) / mt['ask']) * 100
                if s2 > 0.1:
                    spreads.append({'sym': symbol, 'buy': 'MEXC', 'sell': 'Binance', 'price_b': mt['ask'], 'price_s': bt['bid'], 'val': s2})

        # Сортируем: самые жирные спреды вверху
        spreads.sort(key=lambda x: x['val'], reverse=True)
        return spreads

    except Exception as e:
        logging.error(f"Ошибка сканера: {e}")
        return []

@dp.message(Command("scan"))
async def cmd_scan(message: types.Message):
    msg = await message.answer("🔍 Сканирую весь рынок (Binance + MEXC)...")
    
    all_found = await get_all_spreads()
    
    if not all_found:
        await msg.edit_text("☹️ Хороших спредов (>0.1%) сейчас нет.")
        return

    # Формируем отчет (Топ-15 самых выгодных)
    response = f"🚀 **Найдено спредов: {len(all_found)}**\n\n"
    for s in all_found[:15]:
        line = (f"💰 `{s['val']:.2f}%` | **{s['sym'].split('/')[0]}**\n"
                f"   {s['buy']} → {s['sell']}\n"
                f"   курс: `{s['price_b']}` → `{s['price_s']}`\n")
        response += line + "—" * 10 + "\n"

    # Лимит сообщения в ТГ — 4096 символов, обрезаем если надо
    await msg.edit_text(response[:4090], parse_mode="Markdown")

async def main():
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
