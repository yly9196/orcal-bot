import os
import time
import requests
import asyncio
import threading
from datetime import datetime
from http.server import SimpleHTTPRequestHandler
from socketserver import TCPServer
from google import genai
from telegram import Bot
from supabase import create_client
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType

# --- הגדרות L2 של פולימרקט ---
# חובה: המפתח הפרטי של ארנק הפוליגון שלך (להכניס רק דרך Render Env Vars!)
POLY_PRIVATE_KEY = os.getenv("POLY_PRIVATE_KEY") 
HOST = "https://clob.polymarket.com"
CHAIN_ID = 137 # רשת Polygon Mainnet

try:
    # אתחול הלקוח שמדבר עם הבלוקצ'יין
    poly_client = ClobClient(HOST, key=POLY_PRIVATE_KEY, chain_id=CHAIN_ID)
    
    # זה משפט המחץ: יצירת מפתחות ה-API הנגזרים שמאפשרים לבוט לחתום אוטומטית
    creds = poly_client.create_or_derive_api_creds()
    poly_client.set_api_creds(creds)
    print("✅ L2 Authentication Successful! The bot can now sign orders.")
except Exception as e:
    print(f"⚠️ Polymarket Auth Error: {e}")

# --- הגדרות ---
TOKEN = "7504901310:AAG2370ybKrt0uplSVqHgadtiI_y6wt9hIM"
CHAT_ID = "5539218542"
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
AI_KEY = os.getenv("GEMINI_API_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
ai_client = genai.Client(api_key=AI_KEY)
MODEL = 'models/gemini-3.1-pro-preview'
tg_bot = Bot(token=TOKEN)

last_summary_hour = -1

def run_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    with TCPServer(("", port), SimpleHTTPRequestHandler) as httpd:
        httpd.serve_forever()

def get_recent_history():
    """שולף את 5 העסקאות האחרונות לצורך למידה"""
    try:
        res = supabase.table("poly_trades1").select("*").order("created_at", desc=True).limit(5).execute()
        if res.data:
            history_text = "\n".join([f"- {t['question']}: מחיר {t['buy_price']}, סטטוס: {t['status']}" for t in res.data])
            return f"\nהיסטוריית עסקאות אחרונה ללמידה:\n{history_text}"
        return "\nאין היסטוריה קודמת. זו העסקה הראשונה."
    except:
        return ""

async def send_hourly_summary():
    """שולח דוח מנכ"ל שעתי על מצב התיק הווירטואלי"""
    try:
        res_config = supabase.table("poly_config").select("balance").eq("id", 1).execute()
        balance = res_config.data[0]['balance'] if res_config.data else 10000.0
        
        res_trades = supabase.table("poly_trades1").select("*", count="exact").eq("status", "OPEN").execute()
        active_trades = res_trades.count if res_trades.count is not None else 0
        
        msg = f"📊 **סיכום שעתי - תיק פולימרקט**\n\n"
        msg += f"🏦 יתרה וירטואלית: {balance:.1f}$ USDC\n"
        msg += f"📈 עסקאות פעילות בסימולציה: {active_trades}\n"
        msg += f"🕒 זמן דיווח: {datetime.now().strftime('%H:00')}\n"
        msg += f"\nהמערכת ממשיכה לסרוק חדשות וללמוד מהביצועים."
        
        await tg_bot.send_message(chat_id=CHAT_ID, text=msg)
    except Exception as e:
        print(f"שגיאה בהפקת דוח שעתי: {e}")

async def analyze_and_trade():
    print(f"🔎 [{time.strftime('%H:%M:%S')}] סורק הזדמנויות ולומד מהיסטוריה...")
    
    # משיכת נתונים ללמידה מהעסקאות הקודמות
    history_context = get_recent_history()
    
    # בדיקת יתרה נוכחית מהקונפיג
    res_config = supabase.table("poly_config").select("balance").execute()
    balance = res_config.data[0]['balance'] if res_config.data else 10000.0
    
    # משיכת שווקים פעילים מה-CLOB
    url = "https://clob.polymarket.com/markets"
    events = requests.get(url, params={"active": "true", "limit": 10}).json()
    
    for e in events:
        if not isinstance(e, dict): continue
        question = e.get('question')
        
        # --- שדרוג: שליפת token_id לחתימה ---
        tokens = e.get('tokens', [])
        if not tokens: continue
        token_id = tokens[0].get('token_id') # YES token לרוב באינדקס 0
        
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
            try:
                res = ai_client.models.generate_content(model=MODEL, contents=prompt)
                analysis = res.text
                
                # אם ה-AI אישר ויש מספיק יתרה
                if "BUY" in analysis.upper() and balance >= 500:
                    trade_amount = 500 # כאן אפשר לשלב את מחשבון קלי למטה
                    
                    # --- המעבר ללייב: חתימה ושליחת פקודה ל-CLOB ---
                    success, result = execute_poly_order(token_id, price, trade_amount)
                    
                    if success:
                        balance -= trade_amount
                        
                        # שמירה לזיכרון ב-Supabase עם מזהה הפקודה האמיתי
                        supabase.table("poly_trades1").insert({
                            "question": question, 
                            "token_id": token_id,
                            "buy_price": price, 
                            "amount": trade_amount, 
                            "status": "OPEN",
                            "order_id": result # orderID שחזר מפולימרקט
                        }).execute()
                        
                        # עדכון היתרה בקונפיג
                        supabase.table("poly_config").upsert({"id": 1, "balance": balance}).execute()

                        msg = f"⚡ **עסקה חיה בוצעה (חתימת L2)!**\n\n📌 {question}\n💰 מחיר קנייה: {price*100:.1f}%\n🆔 מזהה פקודה: `{result}`\n🧠 **תובנת למידה:**\n{analysis}"
                        await tg_bot.send_message(chat_id=CHAT_ID, text=msg)
                    else:
                        print(f"❌ שגיאת חתימה/ביצוע עבור {question}: {result}")
                        
            except Exception as ex:
                print(f"Error analyzing {question}: {ex}")
                continue

async def main():
    global last_summary_hour
    threading.Thread(target=run_dummy_server, daemon=True).start()
    await tg_bot.send_message(chat_id=CHAT_ID, text="🧠 בוט פולימרקט V1.5 באוויר - מצב למידה פעיל")

def execute_poly_order(token_id, price, size, side="BUY"):
    """
    חותם על פקודת הימור באמצעות המפתח הפרטי ושולח אותה ל-Orderbook של פולימרקט
    """
    try:
        # אריזת הפקודה עם הנתונים הנדרשים
        order_args = OrderArgs(
            price=price, # מחיר ההימור (למשל 0.60 עבור 60%)
            size=size,   # כמות המניות (כמה דולרים להשקיע)
            side=side,
            token_id=token_id, # ה-ID הייחודי של תשובת ה-"YES" או ה-"NO" בשוק הזה
        )
        
        # חתימה קריפטוגרפית (L2 Signature)
        signed_order = poly_client.create_order(order_args)
        
        # ירייה לשרת. FOK (Fill-Or-Kill) אומר: בצע הכל עכשיו, או תבטל.
        resp = poly_client.post_order(signed_order, OrderType.FOK) 
        
        if resp and resp.get('success'):
            return True, resp.get('orderID')
        return False, resp.get('errorMsg', 'Unknown error from CLOB')
        
    except Exception as e:
        print(f"L2 Signature Error: {e}")
        return False, str(e)
    
    while True:
        now = datetime.now()
        
        # בדיקת דוח שעתי
        if now.minute == 0 and now.hour != last_summary_hour:
            await send_hourly_summary()
            last_summary_hour = now.hour
            
        await analyze_and_trade()
        await asyncio.sleep(600) # סריקה כל 10 דקות

if __name__ == "__main__":
    asyncio.run(main())
