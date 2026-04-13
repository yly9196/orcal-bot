import os
import time
import requests
from google import genai
from telegram import Bot

# --- הגדרות ---
TOKEN = "7504901310:AAG2370ybKrt0uplSVqHgadtiI_y6wt9hIM"
CHAT_ID = "5539218542"
# הארנק שלך לסימולציה
WALLET = "0x634fcE54D37B5F12f27110d57188565abE81c58B"

# ה-AI (משתמש במודל 3.1 הפעיל שלך)
AI_KEY = os.getenv("GEMINI_API_KEY")
ai_client = genai.Client(api_key=AI_KEY)
MODEL = 'models/gemini-3.1-pro-preview'

tg_bot = Bot(token=TOKEN)

def get_polymarket_events():
    """מושך אירועים חמים מפולימרקט"""
    try:
        url = "https://clob.polymarket.com/markets"
        r = requests.get(url, params={"active": "true", "limit": 10})
        return r.json()
    except:
        return []

def analyze_and_report():
    print("🔎 סורק אירועים בפולימרקט...")
    events = get_polymarket_events()
    
    for e in events:
        question = e.get('question')
        # מחיר השוק (למשל 0.65 = 65% סיכוי)
        prices = e.get('outcome_prices', [0, 0])
        current_odds = float(prices[0]) * 100 if prices else 0

        if question:
            prompt = f"נתח את האירוע: '{question}'. המחיר בשוק הוא {current_odds}%. האם לפי החדשות של 2026 זה הגיוני? ענה בקצרה: האם כדאי לקנות (BUY) או לא. ענה בעברית."
            try:
                res = ai_client.models.generate_content(model=MODEL, contents=prompt)
                analysis = res.text
                
                # שולח רק אם ה-AI חושב שיש פה 'BUY'
                if "BUY" in analysis.upper():
                    msg = f"🎯 **הזדמנות בפולימרקט (סימולציה)**\n\n📌 שאלה: {question}\n📊 סיכוי שוק: {current_odds:.1f}%\n🧠 ניתוח AI: {analysis}"
                    tg_bot.send_message(chat_id=CHAT_ID, text=msg)
            except:
                continue

if __name__ == "__main__":
    tg_bot.send_message(chat_id=CHAT_ID, text="🤖 בוט פולימרקט Scout עלה לאוויר (Paper Trading)")
    while True:
        analyze_and_report()
        time.sleep(3600) # סורק פעם בשעה
