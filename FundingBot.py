import ccxt
import pandas as pd
import time
import telebot
from telebot import types
import threading
import os
import asyncio
from aiohttp import web

# --- НАСТРОЙКИ БЕЗОПАСНОСТИ ---
# Берем токен из переменных окружения (на Render: Settings -> Env Vars -> Add BOT_TOKEN)
TG_TOKEN = os.getenv("BOT_TOKEN")
if not TG_TOKEN:
    print("❌ ОШИБКА: Переменная BOT_TOKEN не найдена!")
    exit(1)

bot = telebot.TeleBot(TG_TOKEN)

# Хранилище настроек (в оперативной памяти, сбросится при перезагрузке Render)
user_data = {}

print(f"⚙️ Инициализация бирж (Токен скрыт)...")
ex_config = {'enableRateLimit': True, 'options': {'defaultType': 'future'}}
ex_map = {
    'binance': ccxt.binance(ex_config),
    'mexc': ccxt.mexc({'enableRateLimit': True, 'options': {'defaultType': 'swap'}}),
    'kucoin': ccxt.kucoinfutures({'enableRateLimit': True}),
    'gateio': ccxt.gateio({'enableRateLimit': True, 'options': {'defaultType': 'swap'}}),
    'bingx': ccxt.bingx({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
}

# --- ВЕБ-СЕРВЕР ДЛЯ ALIVE-СТАТУСА (RENDER) ---
async def handle(request):
    return web.Response(text="Bot is running and scanning funding...")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"🌐 Web server active on port {port}")

# --- ОСНОВНАЯ ЛОГИКА СКАНЕРА ---
def get_scan(lead_name, depo):
    lead_ex = ex_map[lead_name]
    try:
        lead_ex.load_markets()
        tickers = lead_ex.fetch_tickers()
        lead_list = []
        for symbol, info in tickers.items():
            if '/USDT' in symbol:
                rate = info.get('fundingRate') or info.get('info', {}).get('fundingRate')
                vol = info.get('quoteVolume') or info.get('baseVolume') or 0
                if rate is not None:
                    r_val = float(rate) * 100
                    if r_val != 0:
                        lead_list.append({'sym': symbol, 'r': r_val, 'v': float(vol)})
        
        df = pd.DataFrame(lead_list)
        df = df[df['v'] > 15000].sort_values(by='r').head(30)
        target_symbols = df['sym'].tolist()
    except Exception as e:
        return f"❌ Ошибка {lead_name.upper()}: {e}"

    results = []
    for symbol in target_symbols:
        rates_only = {}
        for name, ex in ex_map.items():
            try:
                if symbol not in ex.markets: ex.load_markets()
                f_data = ex.fetch_funding_rate(symbol)
                rate = f_data.get('fundingRate')
                if rate is not None:
                    val = round(float(rate) * 100, 6)
                    if val != 0.0: rates_only[name.capitalize()] = val
            except: continue
        
        num_ex = len(rates_only)
        if num_ex >= 2:
            s = sorted(rates_only.items(), key=lambda x: x[1], reverse=True)
            s1_val = round(abs(s[0][1] - s[-1][1]), 4)
            res = {
                'Symbol': symbol,
                'S1_val': s1_val,
                'S1_profit': round((depo * (s1_val / 100)), 2),
                'S1_pair': f"{s[0][0]} / {s[-1][0]}",
                'all': rates_only
            }
            results.append(res)
        time.sleep(0.6) # Увеличенная задержка для защиты от РК
    return results

def format_report(data, depo):
    if isinstance(data, str): return data
    top_res = sorted(data, key=lambda x: x['S1_val'], reverse=True)[:5]
    if not top_res: return "🧐 Аномалий не найдено."
    
    response = f"<b>🚀 ФАНДИНГ ОТЧЕТ (Депозит: ${depo})</b>\n\n"
    for i, res in enumerate(top_res, 1):
        response += f"{i}. 🪙 <b>{res['Symbol']}</b>\n"
        response += f"💰 <b>Профит:</b> <code>+${res['S1_profit']}</code> (Спред: {res['S1_val']}%)\n"
        response += f"   └ <i>{res['S1_pair']}</i>\n"
        all_rates = ", ".join([f"{k}: {v}%" for k, v in res['all'].items()])
        response += f"📝 {all_rates}\n───────────────────\n"
    return response

# --- ИНТЕРФЕЙС ---
def get_kb(cid):
    d = user_data.get(cid, {'enabled': False, 'interval_min': 480, 'lead': 'mexc', 'depo': 1000})
    st = "✅ ВКЛ" if d['enabled'] else "❌ ВЫКЛ"
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("🔄 Чек сейчас", f"📊 Лид: {d['lead'].upper()}")
    markup.add(f"Авто: {st}", f"⚙️ {d['interval_min']}м", f"💰 ${d['depo']}")
    return markup

@bot.message_handler(commands=['start'])
def start(message):
    cid = message.chat.id
    if cid not in user_data:
        user_data[cid] = {'enabled': False, 'interval_min': 480, 'lead': 'mexc', 'depo': 1000, 'last_check': time.time()}
    bot.send_message(cid, "Бот запущен на Render! Токен скрыт.", reply_markup=get_kb(cid))

@bot.message_handler(func=lambda m: True)
def handle_text(message):
    cid = message.chat.id
    if cid not in user_data: start(message)
    txt = message.text

    if txt == "🔄 Чек сейчас":
        bot.send_message(cid, "⌛ Ищу жир...")
        res = get_scan(user_data[cid]['lead'], user_data[cid]['depo'])
        bot.send_message(cid, format_report(res, user_data[cid]['depo']), parse_mode='HTML')
    elif "📊 Лид:" in txt:
        user_data[cid]['lead'] = 'gateio' if user_data[cid]['lead'] == 'mexc' else 'mexc'
        bot.send_message(cid, f"Лид изменен на {user_data[cid]['lead'].upper()}", reply_markup=get_kb(cid))
    elif "Авто:" in txt:
        user_data[cid]['enabled'] = not user_data[cid]['enabled']
        bot.send_message(cid, "Авто-чек обновлен", reply_markup=get_kb(cid))
    elif "⚙️" in txt:
        s = bot.send_message(cid, "Минуты авто-чека:")
        bot.register_next_step_handler(s, lambda m: set_val(m, 'interval_min'))
    elif "💰" in txt:
        s = bot.send_message(cid, "Сумма позиции ($):")
        bot.register_next_step_handler(s, lambda m: set_val(m, 'depo'))

def set_val(m, key):
    try:
        user_data[m.chat.id][key] = int(m.text)
        bot.send_message(m.chat.id, "✅ Ок", reply_markup=get_kb(m.chat.id))
    except: bot.send_message(m.chat.id, "⚠️ Нужно число")

# --- ТАЙМЕР И ЗАПУСК ---
def loop():
    while True:
        now = time.time()
        for cid, s in user_data.items():
            if s['enabled'] and (now - s['last_check'] >= s['interval_min'] * 60):
                try:
                    res = get_scan(s['lead'], s['depo'])
                    bot.send_message(cid, format_report(res, s['depo']), parse_mode='HTML')
                    user_data[cid]['last_check'] = now
                except: pass
        time.sleep(30)

async def main():
    threading.Thread(target=loop, daemon=True).start()
    loop_ev = asyncio.get_event_loop()
    loop_ev.create_task(start_web_server())
    print("🚀 Бот в работе!")
    bot.infinity_polling()

if __name__ == "__main__":
    asyncio.run(main())