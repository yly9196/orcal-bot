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
    print(f"🔎 [{now_str}] סורק הזדמנויות ב-Polymarket...")
    
    history_context = get_recent_history()
    
    try:
        res_config = supabase.table("poly_config").select("balance").eq("id", 1).execute()
        balance = res_config.data[0]['balance'] if res_config.data else 10000.0
    except: balance = 10000.0
    
    try:
        url = "https://clob.polymarket.com/markets"
        # ⚠️ התיקון הקריטי: חילוץ הרשימה מתוך מפתח ה-data
        response = requests.get(url, params={"active": "true", "limit": 10}).json()
        events = response.get('data', []) if isinstance(response, dict) else response
    except Exception as e:
        print(f"Error fetching markets: {e}")
        return
    
    for e in events:
        if not isinstance(e, dict): continue
        question = e.get('question')
        tokens = e.get('tokens', [])
        if not tokens: continue
        token_id = tokens[0].get('token_id') 
        
        prices = e.get('outcome_prices', [0, 0])
        price = float(prices[0]) if prices else 0

        if question and price > 0 and token_id:
            prompt = f"""
            אתה אנליסט פולימרקט בעל יכולת למידה עמוקה.
            {history_context}
            
            האירוע הנוכחי: '{question}'
            מחיר שוק (הסתברות): {price*100:.1f}%
            
            בהתבסס על ההיסטוריה שלך וחדשות עדכניות, האם זו הזדמנות BUY?
            ענה בפורמט:
            החלטה: [BUY/SKIP]
            הסבר למידה: [למה זה דומה או שונה מהצלחות קודמות?]
            """
            
            analysis = analyze_with_groq(prompt)
            
            # אם יש אישור קנייה ויתרה מספקת
            if analysis != "ERROR" and "BUY" in analysis.upper() and balance >= 50:
                trade_amount = 50 # מוגדר ל-50 דולר לעסקה בסימולציה/טסט
                
                success, result = execute_poly_order(token_id, price, trade_amount)
                
                if success:
                    balance -= trade_amount
                    try:
                        supabase.table("poly_trades1").insert({
                            "question": question, "token_id": token_id,
                            "buy_price": price, "amount": trade_amount, 
                            "status": "OPEN", "order_id": result 
                        }).execute()
                        supabase.table("poly_config").upsert({"id": 1, "balance": balance}).execute()
                    except: pass

                    msg = f"⚡ **עסקה חיה בפולימרקט (L2)!**\n\n📌 {question}\n💰 מחיר: {price*100:.1f}%\n💵 השקעה: ${trade_amount}\n🆔 מזהה: `{result}`\n\n🧠 **תובנת למידה:**\n{analysis}"
                    await tg_bot.send_message(chat_id=CHAT_ID, text=msg)
                else:
                    print(f"❌ שגיאת ביצוע עבור {question}: {result}")

# ==========================================
# 🚀 הלולאה הראשית
# ==========================================
async def main():
    global last_summary_hour
    threading.Thread(target=run_dummy_server, daemon=True).start()
    await tg_bot.send_message(chat_id=CHAT_ID, text="🧠 PolyBot V2.0 (Groq Llama-3 + L2 Live) באוויר!")
    
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
    try: asyncio.run(main())
    except KeyboardInterrupt: print("Bot stopped.")

