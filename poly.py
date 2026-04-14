import os
import time
import requests
import asyncio
import threading
import pytz
import json
from datetime import datetime, timedelta
from http.server import SimpleHTTPRequestHandler
from socketserver import TCPServer
from telegram import Bot, ReplyKeyboardMarkup
from supabase import create_client
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType
import feedparser
from cryptography.fernet import Fernet
from collections import deque

# ==========================================
# 🌐 הגדרות אבטחה והצפנה
# ==========================================
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
if ENCRYPTION_KEY:
    try:
        cipher = Fernet(ENCRYPTION_KEY)
        POLY_PRIVATE_KEY_ENCRYPTED = os.getenv("POLY_PRIVATE_KEY_ENCRYPTED")
        POLY_PRIVATE_KEY = cipher.decrypt(POLY_PRIVATE_KEY_ENCRYPTED.encode()).decode()
    except:
        POLY_PRIVATE_KEY = os.getenv("POLY_PRIVATE_KEY")
else:
    POLY_PRIVATE_KEY = os.getenv("POLY_PRIVATE_KEY")  # fallback למצב לא מאובטח

HOST = "https://clob.polymarket.com"
CHAIN_ID = 137

# ==========================================
# 🔑 מפתחות והגדרות מאובטחות (נוסף מהגרסאות הקודמות)
# ==========================================
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN') 
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID') 
GROQ_API_KEY = os.getenv('GROQ_API_KEY') 
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
israel_tz = pytz.timezone('Asia/Jerusalem')
last_summary_hour = -1

# ==========================================
# 🔧 הגדרות ניהול סיכונים
# ==========================================
class RiskConfig:
    INITIAL_BALANCE = 1000  # $1000 USDC להתחלה
    MAX_CONCURRENT_TRADES = 5
    MAX_POSITION_SIZE_PCT = 0.15  # 15% מהיתרה לעסקה
    MAX_DAILY_TRADES = 10
    MIN_CONFIDENCE_SCORE = 7  # מינימום 7/10
    STOP_LOSS_PCT = 0.10  # 10%
    TAKE_PROFIT_PCT = 0.25  # 25%
    MIN_LIQUIDITY_RATIO = 1.2  # 20% יותר נזילות מהגודל
    MAX_TRADE_SIZE = 100  # מקסימום 100 מניות לעסקה
    
class TradeRateLimiter:
    def __init__(self, max_trades_per_hour=10):
        self.trades = deque()
        self.max = max_trades_per_hour
    
    def can_trade(self):
        now = time.time()
        while self.trades and now - self.trades[0] > 3600:
            self.trades.popleft()
        if len(self.trades) < self.max:
            self.trades.append(now)
            return True
        return False

# ==========================================
# 📊 ניהול בסיס נתונים ומצב
# ==========================================
def init_database():
    try:
        supabase.table("poly_config").insert({
            "id": 1,
            "balance": RiskConfig.INITIAL_BALANCE,
            "total_trades": 0,
            "winning_trades": 0,
            "total_profit": 0.0
        }).execute()
    except: pass

def get_balance():
    try:
        res = supabase.table("poly_config").select("balance").eq("id", 1).execute()
        if res.data: return float(res.data[0]['balance'])
    except: pass
    return RiskConfig.INITIAL_BALANCE

def update_balance(new_balance):
    try:
        supabase.table("poly_config").update({"balance": new_balance}).eq("id", 1).execute()
    except: pass

# ==========================================
# ⚙️ שרת מדומה ומערכות עזר (שוחזר)
# ==========================================
def run_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    with TCPServer(("", port), SimpleHTTPRequestHandler) as httpd:
        httpd.serve_forever()

def get_global_news_flash():
    sources = [
        "https://www.reutersagency.com/feed/?best-topics=political-news",
        "https://cointelegraph.com/rss",
        "https://www.zerohedge.com/feed",
        "https://news.google.com/rss/search?q=crypto+polymarket&hl=en-US&gl=US"
    ]
    all_headlines = []
    for url in sources:
        try:
            feed = feedparser.parse(url)
            if feed.entries: all_headlines.append(f"- {feed.entries[0].title}")
        except: continue
    return "\n".join(all_headlines) if all_headlines else "No fresh news found."

# ==========================================
# 🧠 המוח של פולימרקט (שוחזר)
# ==========================================
def analyze_with_groq(prompt):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": "llama3-8b-8192", "messages": [{"role": "user", "content": prompt}], "temperature": 0.4, "max_tokens": 150}
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        return response.json()['choices'][0]['message']['content'].strip()
    except: return "ERROR"

# ==========================================
# 🎯 לוגיקת מחירים ונזילות מתוקנת
# ==========================================
def get_correct_prices(market_data):
    """חילוץ חכם של מחירים מפולימרקט, ללא הצפת לוגים"""
    yes_price, no_price = 0.0, 0.0
    
    # ניסיון 1: חיפוש רגיל ב-outcome_prices
    outcome_prices = market_data.get('outcome_prices')
    if outcome_prices and len(outcome_prices) >= 2:
        try:
            yes_price = float(outcome_prices[0])
            no_price = float(outcome_prices[1])
        except: pass
        
    # ניסיון 2: חיפוש עמוק בתוך רשימת ה-tokens
    if yes_price == 0.0 and no_price == 0.0:
        tokens = market_data.get('tokens', [])
        if len(tokens) >= 2:
            try:
                yes_price = float(tokens[0].get('price', 0))
                no_price = float(tokens[1].get('price', 0))
            except: pass
            
    # אם המחירים סוכמים למשהו מאוד חריג (לא הגיוני מתמטית), נחזיר 0
    if yes_price > 0 and no_price > 0:
        if abs((yes_price + no_price) - 1.0) > 0.1:
            return 0.0, 0.0
            
    return yes_price, no_price

def calculate_position_size(balance, confidence_score, market_volatility=1.0):
    if confidence_score < RiskConfig.MIN_CONFIDENCE_SCORE: return 0
    base_pct = RiskConfig.MAX_POSITION_SIZE_PCT
    confidence_bonus = (confidence_score - 7) * 0.0025
    volatility_penalty = max(0.5, min(1.0, 1.0 - (market_volatility * 0.2)))
    total_pct = min(RiskConfig.MAX_POSITION_SIZE_PCT, (base_pct + confidence_bonus) * volatility_penalty)
    position_size = (balance * total_pct)
    return round(max(5.0, min(position_size, RiskConfig.MAX_TRADE_SIZE)), 2)

def check_liquidity(token_id, requested_size):
    try:
        order_book = poly_client.get_order_book(token_id)
        bids = order_book.get('bids', [])
        total_liquidity = sum([float(b.get('size', 0)) for b in bids])
        required_liquidity = requested_size * RiskConfig.MIN_LIQUIDITY_RATIO
        
        if total_liquidity < required_liquidity:
            return False, f"נזילות נמוכה: {total_liquidity:.0f} < {required_liquidity:.0f}"
        
        best_bid = float(bids[0]['price']) if bids else 0
        second_bid = float(bids[1]['price']) if len(bids) > 1 else best_bid
        if best_bid - second_bid > 0.02:
            return False, "פער מחירים גדול מדי"
        return True, "OK"
    except Exception as e: return False, str(e)

def calculate_ev(price, estimated_probability):
    return ((1 - price) * estimated_probability) - (price * (1 - estimated_probability))

def extract_confidence_from_analysis(analysis_text):
    text_lower = analysis_text.lower()
    if "high confidence" in text_lower or "very likely" in text_lower: return 9
    elif "moderate confidence" in text_lower or "somewhat likely" in text_lower: return 7
    elif "low confidence" in text_lower or "uncertain" in text_lower: return 5
    elif "very low" in text_lower or "unlikely" in text_lower: return 3
    return 6

# ==========================================
# 🛑 Stop Loss & Take Profit אוטומטי
# ==========================================
async def check_and_close_trades():
    try:
        res = supabase.table("poly_trades1").select("*").eq("status", "OPEN").execute()
        for trade in res.data:
            try:
                market_response = requests.get(f"https://clob.polymarket.com/markets/{trade['token_id']}").json()
                _, current_no_price = get_correct_prices(market_response)
                current_price = current_no_price if 'NO' in trade.get('side', 'YES') else market_response.get('outcome_prices', [0, 0])[0]
                current_price = float(current_price)
            except: continue
            
            buy_price = float(trade['buy_price'])
            pnl_pct = (current_price - buy_price) / buy_price
            
            if pnl_pct >= RiskConfig.TAKE_PROFIT_PCT:
                await close_trade(trade, "TAKE_PROFIT", current_price, pnl_pct)
            elif pnl_pct <= -RiskConfig.STOP_LOSS_PCT:
                await close_trade(trade, "STOP_LOSS", current_price, pnl_pct)
    except Exception as e: print(f"שגיאה במעקב עסקאות: {e}")

async def close_trade(trade, reason, exit_price, pnl_pct):
    try:
        order_args = OrderArgs(price=exit_price, size=trade['size'], side="SELL", token_id=trade['token_id'])
        signed_order = poly_client.create_order(order_args)
        resp = poly_client.post_order(signed_order, OrderType.FOK)
        
        if resp and resp.get('success'):
            supabase.table("poly_trades1").update({"status": "CLOSED", "exit_price": exit_price, "exit_reason": reason, "pnl_pct": pnl_pct, "closed_at": datetime.now().isoformat()}).eq("id", trade['id']).execute()
            balance = get_balance()
            pnl_amount = (exit_price - trade['buy_price']) * trade['size']
            new_balance = balance + pnl_amount
            update_balance(new_balance)
            
            icon = "✅" if pnl_pct > 0 else "❌"
            await tg_bot.send_message(chat_id=CHAT_ID, text=f"{icon} *עסקה נסגרה*\n\n📌 {trade['question']}\nסיבה: {reason}\nPnL: {pnl_pct:.1%} (${pnl_amount:.2f})\nיתרה חדשה: ${new_balance:.2f}")
    except Exception as e: print(f"שגיאה בסגירת עסקה: {e}")

# ==========================================
# 🎯 ביצוע עסקה (Risk Managed)
# ==========================================
async def execute_trade_with_risk_management(token_id, question, price, side, confidence_score, balance):
    if not trade_limiter.can_trade(): return False
    
    res = supabase.table("poly_trades1").select("*", count="exact").eq("status", "OPEN").execute()
    if res.count >= RiskConfig.MAX_CONCURRENT_TRADES: return False
    
    position_size = calculate_position_size(balance, confidence_score)
    if position_size < 5: return False
    
    liquid_ok, liquid_msg = check_liquidity(token_id, position_size)
    if not liquid_ok: return False
    
    try:
        order_args = OrderArgs(price=price, size=position_size, side=side, token_id=token_id)
        signed_order = poly_client.create_order(order_args)
        resp = poly_client.post_order(signed_order, OrderType.FOK)
        
        if resp and resp.get('success'):
            supabase.table("poly_trades1").insert({
                "question": question, "token_id": token_id, "buy_price": price, "size": position_size,
                "side": side, "status": "OPEN", "confidence_score": confidence_score, "created_at": datetime.now().isoformat()
            }).execute()
            
            new_balance = balance - (price * position_size)
            update_balance(new_balance)
            
            await tg_bot.send_message(chat_id=CHAT_ID, text=f"🎯 *הימור בוצע (V3.0 Risk Managed)!*\n\n📌 **שוק:** {question}\n💵 **מחיר:** {price*100:.1f}¢\n📦 **כמות:** {position_size} מניות\n🎯 **ביטחון:** {confidence_score}/10\n💰 **השקעה:** ${price * position_size:.2f}\n📊 **יתרה:** ${new_balance:.2f}")
            return True
        return False
    except: return False

# ==========================================
# 📊 דשבורד חי (שוחזר ותוקן)
# ==========================================
async def send_hourly_summary():
    try:
        balance = get_balance()
        res_trades = supabase.table("poly_trades1").select("*", count="exact").eq("status", "OPEN").execute()
        active_trades = res_trades.count if res_trades.count is not None else 0
        
        msg = f"📊 **סיכום שעתי - פולימרקט**\n\n🏦 יתרה נוכחית: ${balance:.2f}\n📈 עסקאות פעילות: {active_trades}\n🕒 זמן: {datetime.now(israel_tz).strftime('%H:00')}\n\nהמערכת סורקת עם ניהול סיכונים מתקדם..."
        await tg_bot.send_message(chat_id=CHAT_ID, text=msg)
    except Exception as e: print(f"שגיאה בסיכום שעתי: {e}")

async def send_live_dashboard():
    balance = get_balance()
    res_open = supabase.table("poly_trades1").select("*").eq("status", "OPEN").execute()
    res_closed = supabase.table("poly_trades1").select("*").eq("status", "CLOSED").execute()
    
    total_invested = sum([t['buy_price'] * t['size'] for t in res_open.data])
    current_value = total_invested # Placeholder - ideally fetch live prices
    
    closed_trades = len(res_closed.data)
    winning_trades = len([t for t in res_closed.data if t.get('pnl_pct', 0) > 0])
    win_rate = (winning_trades / closed_trades * 100) if closed_trades > 0 else 0
    
    avg_conf = 0
    scores = [t['confidence_score'] for t in res_open.data + res_closed.data if t.get('confidence_score')]
    if scores: avg_conf = round(sum(scores) / len(scores), 1)

    dashboard = f"""📊 *LIVE DASHBOARD - PolyBot V3.0*
━━━━━━━━━━━━━━━━━━━
💰 יתרה פנויה: ${balance:.2f}
🎯 עסקאות פתוחות: {len(res_open.data)}
💵 הון מושקע: ${total_invested:.2f}
📈 ערך מוערך: ${current_value:.2f}

📊 סטטיסטיקה היסטורית:
🏆 Win Rate: {win_rate:.1f}%
🎯 סך עסקאות נסגרו: {closed_trades}
⭐ ממוצע ביטחון AI: {avg_conf} /10"""
    await tg_bot.send_message(chat_id=CHAT_ID, text=dashboard)

# ==========================================
# 🧠 ניתוח ראשית (שילוב לוגיקה)
# ==========================================
async def analyze_and_trade():
    today = datetime.now().date().isoformat()
    res_today = supabase.table("poly_trades1").select("*").gte("created_at", today).execute()
    if len(res_today.data) >= RiskConfig.MAX_DAILY_TRADES: return
    
    current_news = get_global_news_flash()
    balance = get_balance()
    
    try:
        response = requests.get("https://clob.polymarket.com/markets", params={"active": "true", "limit": 30}).json()
        events = response.get('data', [])
    except: return
    
    for event in events:
        question = event.get('question')
        if not question: continue
        
        yes_price, no_price = get_correct_prices(event)
        price = yes_price
        
        # 🔥 התיקון: מדלגים בשקט לחלוטין על שווקים "מתים" או פתורים
        if price <= 0.0 or price >= 1.0:
            continue
            
        side = "BUY"
        
        prompt = f"""אתה אנליסט פולימרקט מקצועי.
        חדשות: {current_news[:500]}
        שוק: {question}
        מחיר (YES): {price*100:.1f}%
        
        החלט אם יש פה הזדמנות ערך חיובי.
        החלטה: [BUY/SKIP]
        ביטחון: [1-10]
        הסבר: [קצר]"""
        
        analysis = analyze_with_groq(prompt)
        if "BUY" in analysis.upper():
            conf = extract_confidence_from_analysis(analysis)
            ev = calculate_ev(price, conf / 10)
            if ev > 0.05:
                await execute_trade_with_risk_management(event['tokens'][0]['token_id'], question, price, side, conf, balance)

# ==========================================
# 🚀 האזנה לטלגרם והרצה
# ==========================================
async def handle_telegram_updates():
    last_id = 0
    while True:
        try:
            updates = await tg_bot.get_updates(offset=last_id, timeout=10)
            for update in updates:
                last_id = update.update_id + 1
                if not update.message: continue
                text = update.message.text
                if text == '📊 דוח סטטוס פולי': await send_hourly_summary()
                elif text == '🔄 סרוק עכשיו': 
                    await update.message.reply_text("🔎 סורק...")
                    await analyze_and_trade()
                elif text == '📈 דשבורד חי': await send_live_dashboard()
                elif text == '💰 יתרה': await update.message.reply_text(f"💰 יתרה נוכחית: ${get_balance():.2f}")
        except: pass
        await asyncio.sleep(2)

trade_limiter = TradeRateLimiter()
poly_client = None
tg_bot = None

def main():
    global poly_client, tg_bot
    try:
        poly_client = ClobClient(HOST, key=POLY_PRIVATE_KEY, chain_id=CHAIN_ID)
        creds = poly_client.create_or_derive_api_creds()
        poly_client.set_api_creds(creds)
    except Exception as e: print(f"❌ Auth Err: {e}")
    
    tg_bot = Bot(token=TOKEN)
    init_database()
    threading.Thread(target=run_dummy_server, daemon=True).start()
    asyncio.run(main_loop())

async def main_loop():
    global last_summary_hour
    keyboard = [['📊 דוח סטטוס פולי', '🔄 סרוק עכשיו'], ['📈 דשבורד חי', '💰 יתרה']]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await tg_bot.send_message(chat_id=CHAT_ID, text="🧠 PolyBot V3.0 (Risk Managed) Online!", reply_markup=reply_markup)
    
    asyncio.create_task(handle_telegram_updates())
    last_dash_hour = -1
    
    while True:
        try:
            now = datetime.now(israel_tz)
            if now.minute == 0 and now.hour != last_summary_hour:
                await send_hourly_summary()
                last_summary_hour = now.hour
            
            if now.hour % 4 == 0 and now.minute == 0 and now.hour != last_dash_hour:
                await send_live_dashboard()
                last_dash_hour = now.hour
            
            if now.minute % 10 == 0: await analyze_and_trade()
            await check_and_close_trades()
        except: pass
        await asyncio.sleep(60)

if __name__ == "__main__":
    main()
