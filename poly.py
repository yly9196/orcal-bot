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

# --- שרת דמיוני כדי להשתיק את Render ---
def run_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    with TCPServer(("", port), SimpleHTTPRequestHandler) as httpd:
        print(f"📡 Dummy server listening on port {port}")
        httpd.serve_forever()

def get_polymarket_events():
    try:
        url = "https://clob.polymarket.com/markets"
        r = requests.get(url, params={"active": "true", "limit": 10})
        data = r.json()
        return data if isinstance(data, list) else []
    except:
        return []

async def analyze_and_report():
    print("🔎 סורק אירועים בפולימרקט...")
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
            prompt = f"נתח את האירוע: '{question}'. המחיר בשוק הוא {current_odds}%. האם זה הגיוני? ענה בקצרה: האם כדאי לקנות (BUY) או לא. ענה בעברית."
            try:
                res = ai_client.models.generate_content(model=MODEL, contents=prompt)
                analysis = res.text
                if "BUY" in analysis.upper():
                    msg = f"🎯 **הזדמנות בפולימרקט (סימולציה)**\n\n📌 שאלה: {question}\n📊 סיכוי שוק: {current_odds:.1f}%\n🧠 ניתוח AI: {analysis}"
                    await tg_bot.send_message(chat_id=CHAT_ID, text=msg)
            except:
                continue

async def main():
    # הפעלת השרת הדמיוני ברקע
    threading.Thread(target=run_dummy_server, daemon=True).start()
    
    await tg_bot.send_message(chat_id=CHAT_ID, text=f"🤖 בוט פולימרקט Scout V1.2 באוויר!")
    while True:
        await analyze_and_report()
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
