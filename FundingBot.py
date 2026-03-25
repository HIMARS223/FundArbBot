import ccxt
import pandas as pd
import time
import telebot
from telebot import types
import threading
import os
import asyncio
import json
from aiohttp import web

# --- НАСТРОЙКИ БЕЗОПАСНОСТИ ---
TG_TOKEN = os.getenv("BOT_TOKEN")
if not TG_TOKEN:
    print("❌ ОШИБКА: Переменная BOT_TOKEN не найдена!")
    exit(1)

bot = telebot.TeleBot(TG_TOKEN)

# --- РАБОТА С НАСТРОЙКАМИ (JSON) ---
SETTINGS_FILE = "user_settings.json"

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_settings(data):
    # Превращаем ключи в строки для JSON
    clean_data = {str(k): v for k, v in data.items()}
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(clean_data, f)

user_data = load_settings()

print(f"⚙️ Инициализация бирж...")
ex_config = {'enableRateLimit': True, 'options': {'defaultType': 'future'}}
ex_map = {
    'binance': ccxt.binance(ex_config),
    'mexc': ccxt.mexc({'enableRateLimit': True, 'options': {'defaultType': 'swap'}}),
    'kucoin': ccxt.kucoinfutures({'enableRateLimit': True}),
    'gateio': ccxt.gateio({'enableRateLimit': True, 'options': {'defaultType': 'swap'}}),
    'bingx': ccxt.bingx({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
}

# --- ВЕБ-СЕРВЕР ---
async def handle(request):
    return web.Response(text="Bot is alive!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

# --- ЛОГИКА СКАНЕРА ---
def get_scan(lead_name, depo):
    lead_ex = ex_map[lead_name]
    try:
        lead_ex.load_markets()
        tickers = lead_ex.fetch_tickers()
        lead_list = []
        
        for symbol, info in tickers.items():
            if '/USDT' in symbol:
                # Фикс ошибки 'v' - проверяем все возможные ключи объема
                volume = info.get('quoteVolume') or info.get('baseVolume') or info.get('v') or 0
                rate = info.get('fundingRate') or info.get('info', {}).get('fundingRate')
                
                if rate is not None:
                    r_val = float(rate) * 100
                    if r_val != 0:
                        lead_list.append({'sym': symbol, 'r': r_val, 'v': float(volume)})
        
        if not lead_list: return "❌ Нет данных с лид-биржи."
        
        df = pd.DataFrame(lead_list)
        # Фильтр объема (15к)
        df = df[df['v'] > 15000].sort_values(by='r').head(35)
        target_symbols = df['sym'].tolist()
    except Exception as e:
        return f"❌ Ошибка {lead_name.upper()}: {str(e)}"

    results = []
    for symbol in target_symbols:
        rates_only = {}
        for name, ex in ex_map.items():
            try:
                if symbol not in ex.markets: continue
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
        time.sleep(0.5)
    return results

def format_report(data, depo):
    if isinstance(data, str): return data
    top_res = sorted(data, key=lambda x: x['S1_val'], reverse=True)[:5]
    if not top_res: return "🧐 Аномалий не найдено."
    
    response = f"<b>🚀 ОТЧЕТ (Депозит: ${depo})</b>\n\n"
    for i, res in enumerate(top_res, 1):
        response += f"{i}. 🪙 <b>{res['Symbol']}</b>\n"
        response += f"💰 <b>Профит:</b> <code>+${res['S1_profit']}</code> (Спред: {res['S1_val']}%)\n"
        response += f"   └ <i>{res['S1_pair']}</i>\n"
        all_rates = ", ".join([f"{k}: {v}%" for k, v in res['all'].items()])
        response += f"📝 {all_rates}\n───────────────────\n"
    return response

# --- КЛАВИАТУРА ---
def get_kb(cid):
    cid_str = str(cid)
    d = user_data.get(cid_str, {'enabled': False, 'interval_min': 480, 'lead': 'mexc', 'depo': 1000})
    st = "✅ ВКЛ" if d['enabled'] else "❌ ВЫКЛ"
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("🔄 Чек сейчас", f"📊 Лид: {d['lead'].upper()}")
    markup.add(f"Авто: {st}", f"⚙️ {d['interval_min']}м", f"💰 ${d['depo']}")
    return markup

@bot.message_handler(commands=['start'])
def start(message):
    cid = str(message.chat.id)
    if cid not in user_data:
        user_data[cid] = {'enabled': False, 'interval_min': 480, 'lead': 'mexc', 'depo': 1000, 'last_check': time.time()}
        save_settings(user_data)
    bot.send_message(message.chat.id, "Бот готов. Ошибка Gate исправлена!", reply_markup=get_kb(cid))

@bot.message_handler(func=lambda m: True)
def handle_text(message):
    cid = str(message.chat.id)
    if cid not in user_data: start(message); return
    txt = message.text

    if txt == "🔄 Чек сейчас":
        bot.send_message(message.chat.id, f"⌛ Скан через {user_data[cid]['lead'].upper()}...")
        res = get_scan(user_data[cid]['lead'], user_data[cid]['depo'])
        bot.send_message(message.chat.id, format_report(res, user_data[cid]['depo']), parse_mode='HTML')
    elif "📊 Лид:" in txt:
        user_data[cid]['lead'] = 'gateio' if user_data[cid]['lead'] == 'mexc' else 'mexc'
        save_settings(user_data)
        bot.send_message(message.chat.id, f"Лид: {user_data[cid]['lead'].upper()}", reply_markup=get_kb(cid))
    elif "Авто:" in txt:
        user_data[cid]['enabled'] = not user_data[cid]['enabled']
        save_settings(user_data)
        bot.send_message(message.chat.id, "Авто-чек изменен", reply_markup=get_kb(cid))
    elif "⚙️" in txt:
        s = bot.send_message(message.chat.id, "Минуты:")
        bot.register_next_step_handler(s, lambda m: set_val(m, 'interval_min'))
    elif "💰" in txt:
        s = bot.send_message(message.chat.id, "Депозит ($):")
        bot.register_next_step_handler(s, lambda m: set_val(m, 'depo'))

def set_val(m, key):
    try:
        user_data[str(m.chat.id)][key] = int(m.text)
        save_settings(user_data)
        bot.send_message(m.chat.id, "✅ Сохранено", reply_markup=get_kb(m.chat.id))
    except: bot.send_message(m.chat.id, "⚠️ Число плиз")

# --- ТАЙМЕР ---
def loop():
    while True:
        now = time.time()
        for cid, s in user_data.items():
            if s.get('enabled') and (now - s.get('last_check', 0) >= s.get('interval_min', 480) * 60):
                try:
                    res = get_scan(s['lead'], s['depo'])
                    bot.send_message(int(cid), format_report(res, s['depo']), parse_mode='HTML')
                    user_data[cid]['last_check'] = now
                except: pass
        time.sleep(30)

async def main():
    threading.Thread(target=loop, daemon=True).start()
    await start_web_server()
    bot.infinity_polling()

if __name__ == "__main__":
    asyncio.run(main())
