import os
import time
import requests
import asyncio
import threading
import pytz
from datetime import datetime
from http.server import SimpleHTTPRequestHandler
from socketserver import TCPServer
from telegram import Bot
from supabase import create_client
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType
import feedparser

# ==========================================
# 🌐 הגדרות L2 של פולימרקט
# ==========================================
POLY_PRIVATE_KEY = os.getenv("POLY_PRIVATE_KEY") 
HOST = "https://clob.polymarket.com"
CHAIN_ID = 137 # רשת Polygon Mainnet

try:
    poly_client = ClobClient(HOST, key=POLY_PRIVATE_KEY, chain_id=CHAIN_ID)
    creds = poly_client.create_or_derive_api_creds()
    poly_client.set_api_creds(creds)
    print("✅ L2 Authentication Successful! The bot can now sign orders.")
except Exception as e:
    print(f"⚠️ Polymarket Auth Error: {e}")

# ==========================================
# 🔑 מפתחות והגדרות מאובטחות
# ==========================================
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN') 
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID') 
GROQ_API_KEY = os.getenv('GROQ_API_KEY') 
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
tg_bot = Bot(token=TOKEN)
israel_tz = pytz.timezone('Asia/Jerusalem')
last_summary_hour = -1

# ==========================================
# ⚙️ מערכות עזר וחדשות עולמיות
# ==========================================

def get_global_news_flash():
    """סריקה של 10 מקורות חדשות מובילים בזמן אמת"""
    sources = [
        "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
        "http://feeds.bbci.co.uk/news/world/rss.xml",
        "https://www.reutersagency.com/feed/?best-topics=political-news",
        "https://cointelegraph.com/rss",
        "https://www.aljazeera.com/xml/rss/all.xml",
        "https://feeds.a.dj.com/rss/RSSWorldNews.xml",
        "https://www.cnbc.com/id/100727362/device/rss/rss.html",
        "https://thehill.com/homenews/feed/",
        "https://www.zerohedge.com/feed",
        "https://news.google.com/rss/search?q=crypto+polymarket&hl=en-US&gl=US&ceid=US:en"
    ]
    
    all_headlines = []
    print("📰 מתחיל איסוף חדשות מ-10 מקורות...")
    for url in sources:
        try:
            feed = feedparser.parse(url)
            if feed.entries:
                all_headlines.append(f"- {feed.entries[0].title}")
        except: continue
    
    return "\n".join(all_headlines) if all_headlines else "No fresh news found."

# ==========================================
# ⚙️ שרת מדומה ומערכות עזר
# ==========================================
def run_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    with TCPServer(("", port), SimpleHTTPRequestHandler) as httpd:
        httpd.serve_forever()

def get_recent_history():
    try:
        res = supabase.table("poly_trades1").select("*").order("created_at", desc=True).limit(5).execute()
        if res.data:
            history_text = "\n".join([f"- {t['question']}: מחיר {t['buy_price']}, סטטוס: {t['status']}" for t in res.data])
            return f"\nהיסטוריית עסקאות אחרונה ללמידה:\n{history_text}"
        return "\nאין היסטוריה קודמת. זו העסקה הראשונה."
    except:
        return ""

def execute_poly_order(token_id, price, size, side="BUY"):
    try:
        order_args = OrderArgs(price=price, size=size, side=side, token_id=token_id)
        signed_order = poly_client.create_order(order_args)
        resp = poly_client.post_order(signed_order, OrderType.FOK) 
        
        if resp and resp.get('success'): return True, resp.get('orderID')
        return False, resp.get('errorMsg', 'Unknown error from CLOB')
    except Exception as e:
        return False, str(e)

# ==========================================
# 🧠 המוח של פולימרקט (Groq Llama-3)
# ==========================================
def analyze_with_groq(prompt):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "llama3-70b-8192", 
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 150
    }
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        return response.json()['choices'][0]['message']['content'].strip()
    except Exception as e:
        print(f"Groq Error: {e}")
        return "ERROR"

async def send_hourly_summary():
    try:
        res_config = supabase.table("poly_config").select("balance").eq("id", 1).execute()
        balance = res_config.data[0]['balance'] if res_config.data else 10000.0
        
        res_trades = supabase.table("poly_trades1").select("*", count="exact").eq("status", "OPEN").execute()
        active_trades = res_trades.count if res_trades.count is not None else 0
        
        msg = f"📊 **סיכום שעתי - פולימרקט**\n\n🏦 יתרה וירטואלית: {balance:.1f}$ USDC\n📈 עסקאות פעילות: {active_trades}\n🕒 זמן: {datetime.now(israel_tz).strftime('%H:00')}\n\nהמערכת ממשיכה לסרוק..."
        await tg_bot.send_message(chat_id=CHAT_ID, text=msg)
    except Exception as e:
        print(f"שגיאה בהפקת דוח שעתי: {e}")

async def analyze_and_trade():
    now_str = datetime.now(israel_tz).strftime('%H:%M:%S')
    print(f"🔎 [{now_str}] סורק שווקים ומצליב עם 10 מקורות חדשות...")
    
    current_news = get_global_news_flash()
    history_context = get_recent_history()
    
    try:
        url = "https://clob.polymarket.com/markets"
        response = requests.get(url, params={"active": "true", "limit": 15}).json()
        events = response.get('data', [])
    except: return
    
    for e in events:
        question = e.get('question')
        tokens = e.get('tokens', [])
        if not tokens: continue
        
        token_id = tokens[0].get('token_id')
        prices = e.get('outcome_prices', [0, 0])
        price = float(prices[0]) if prices else 0

        if question and price > 0:
            prompt = f"""
            אתה אנליסט פולימרקט בכיר.
            
            חדשות אחרונות מהעולם (10 מקורות):
            {current_news}
            
            {history_context}
            
            השוק לבדיקה: '{question}'
            מחיר נוכחי: {price*100:.1f}% (הסתברות)
            
            משימה:
            האם בהתבסס על החדשות הטריות ביותר, המחיר בשוק משקף את המציאות?
            אם החדשות תומכות באירוע והמחיר עדיין נמוך - זה BUY.
            אם החדשות סותרות או שאין קשר ישיר - זה SKIP.
            
            ענה בפורמט:
            החלטה: [BUY/SKIP]
            הסבר: [קישור קצר בין כותרת ספציפית לשוק]
            """
            
            analysis = analyze_with_groq(prompt)
            
            if "BUY" in analysis.upper():
                print(f"🎯 זיהוי הזדמנות עבור: {question}")
                
                # התיקון: שליחת הפקודה ושמירה במסד הנתונים
                size_to_buy = "10" # כמות מניות לקנייה (10 מניות)
                success, order_id_or_err = execute_poly_order(token_id, price, size=size_to_buy, side="BUY")
                
                if success:
                    try:
                        supabase.table("poly_trades1").insert({
                            "question": question,
                            "buy_price": price,
                            "size": float(size_to_buy),
                            "status": "OPEN",
                            "analysis_reason": analysis
                        }).execute()
                    except Exception as db_err:
                        print(f"DB Error: {db_err}")
                        
                    await tg_bot.send_message(
                        chat_id=CHAT_ID, 
                        text=f"🎯 *הימור חדש בוצע (PolyBot)!*\n\n"
                             f"📌 **שוק:** {question}\n"
                             f"💵 **מחיר קנייה:** {price*100:.1f}¢\n"
                             f"📦 **כמות מניות:** {size_to_buy}\n"
                             f"🧠 **סיבת ה-AI:**\n{analysis}",
                        parse_mode="Markdown"
                    )
                else:
                    print(f"❌ שגיאה בביצוע פקודה לפולימרקט: {order_id_or_err}")

async def handle_telegram_updates():
    last_update_id = 0
    print("📡 PolyBot Telegram Listener Started...")
    
    from telegram import ReplyKeyboardMarkup
    keyboard = [['📊 דוח סטטוס פולי', '🔄 סרוק עכשיו']]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    while True:
        try:
            updates = await tg_bot.get_updates(offset=last_update_id, timeout=10)
            for update in updates:
                last_update_id = update.update_id + 1
                if not update.message: continue
                
                text = update.message.text
                if text == '📊 דוח סטטוס פולי':
                    await send_hourly_summary()
                elif text == '🔄 סרוק עכשיו':
                    await update.message.reply_text("🔎 מריץ סריקה ידנית עכשיו...")
                    await analyze_and_trade()
                elif text == '/start':
                    await update.message.reply_text("ברוך הבא ל-PolyBot! השתמש בלחצנים למטה:", reply_markup=reply_markup)
                    
        except Exception as e:
            pass # התעלמות משגיאות קטנות ברשת
        
        await asyncio.sleep(2)

# ==========================================
# 🚀 הלולאה הראשית
# ==========================================
async def main():
    global last_summary_hour
    
    threading.Thread(target=run_dummy_server, daemon=True).start()
    
    from telegram import ReplyKeyboardMarkup
    keyboard = [['📊 דוח סטטוס פולי', '🔄 סרוק עכשיו']]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await tg_bot.send_message(chat_id=CHAT_ID, text="🧠 PolyBot V2.0 מוכן לפעולה!", reply_markup=reply_markup)
    
    asyncio.create_task(handle_telegram_updates())
    
    while True:
        try:
            now = datetime.now(israel_tz)
            
            if now.minute == 0 and now.hour != last_summary_hour:
                await send_hourly_summary()
                last_summary_hour = now.hour
                
            if now.minute % 10 == 0:
                await analyze_and_trade()
                
        except Exception as e:
            print(f"Main Loop Error: {e}")
            
        await asyncio.sleep(60)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped.")

