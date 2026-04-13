import os
import time
import requests
import asyncio
import threading
from http.server import SimpleHTTPRequestHandler
from socketserver import TCPServer
from google import genai
from telegram import Bot

# --- הגדרות ---
TOKEN = "7504901310:AAG2370ybKrt0uplSVqHgadtiI_y6wt9hIM"
CHAT_ID = "5539218542"
AI_KEY = os.getenv("GEMINI_API_KEY")
ai_client = genai.Client(api_key=AI_KEY)
MODEL = 'models/gemini-3.1-pro-preview'
tg_bot = Bot(token=TOKEN)

# --- שרת דמיוני כדי להשתיק את Render ולאפשר ל-Uptime Robot לעבוד ---
def run_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    try:
        with TCPServer(("", port), SimpleHTTPRequestHandler) as httpd:
            print(f"📡 שרת דמיוני מאזין בפורט {port}")
            httpd.serve_forever()
    except Exception as e:
        print(f"שרת דמיוני נכשל (לא קריטי): {e}")

def get_polymarket_events():
    """מושך אירועים חמים מפולימרקט"""
    try:
        url = "https://clob.polymarket.com/markets"
        # מושך את 10 האירועים הפעילים ביותר
        r = requests.get(url, params={"active": "true", "limit": 10})
        data = r.json()
        return data if isinstance(data, list) else []
    except Exception as e:
        print(f"שגיאת API בפולימרקט: {e}")
        return []

async def analyze_and_report():
    print(f"🔎 [{time.strftime('%H:%M:%S')}] סורק אירועים והזדמנויות...")
    events = get_polymarket_events()
    
    for e in events:
        if not isinstance(e, dict): continue
        
        question = e.get('question')
        prices = e.get('outcome_prices', [0, 0])
        
        try:
            current_odds = float(prices[0]) * 100 if prices else 0
        except:
            current_odds = 0

        if question:
            # ה-AI סורק חדשות בזמן אמת ומנתח
            prompt = f"""
            נתח את האירוע הבא מפולימרקט: '{question}'. 
            המחיר הנוכחי בשוק משקף סיכוי של {current_odds:.1f}%.
            חפש חדשות מהדקות האחרונות וקבע:
            1. האם הסיכוי האמיתי גבוה משמעותית ממחיר השוק?
            2. אם כן, רשום 'BUY' והסבר למה. אם לא, רשום 'SKIP'.
            ענה בקצרה ובעברית.
            """
            try:
                res = ai_client.models.generate_content(model=MODEL, contents=prompt)
                analysis = res.text
                
                # שולח התראה רק אם יש המלצת קנייה ברורה
                if "BUY" in analysis.upper():
                    msg = f"🎯 **הזדמנות פולימרקט מזוהה!**\n\n📌 שאלה: {question}\n📊 סיכוי שוק: {current_odds:.1f}%\n🧠 ניתוח AI:\n{analysis}"
                    await tg_bot.send_message(chat_id=CHAT_ID, text=msg)
                    print(f"✅ נשלחה התראה על: {question}")
            except Exception as ai_err:
                print(f"שגיאת AI: {ai_err}")
                continue

async def main():
    # הפעלת השרת הדמיוני ב-Thread נפרד
    threading.Thread(target=run_dummy_server, daemon=True).start()
    
    await tg_bot.send_message(chat_id=CHAT_ID, text="🚀 בוט פולימרקט V1.3 באוויר!\nסריקה חדשותית מופעלת בכל 10 דקות.")
    
    while True:
        await analyze_and_report()
        print("😴 ממתין 10 דקות לסריקה הבאה...")
        await asyncio.sleep(600) # 10 דקות

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("הבוט נעצר.")
