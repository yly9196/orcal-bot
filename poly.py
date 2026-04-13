import os
import time
import requests
import asyncio
from google import genai
from telegram import Bot

# --- הגדרות ---
TOKEN = "7504901310:AAG2370ybKrt0uplSVqHgadtiI_y6wt9hIM"
CHAT_ID = "5539218542"

# ה-AI (משתמש במפתח מה-Environment)
AI_KEY = os.getenv("GEMINI_API_KEY")
ai_client = genai.Client(api_key=AI_KEY)
MODEL = 'models/gemini-3.1-pro-preview'

tg_bot = Bot(token=TOKEN)

def get_polymarket_events():
    """מושך אירועים חמים מפולימרקט בצורה בטוחה"""
    try:
        url = "https://clob.polymarket.com/markets"
        r = requests.get(url, params={"active": "true", "limit": 10})
        data = r.json()
        # וודוא שאנחנו מקבלים רשימה של מילונים
        if isinstance(data, list):
            return data
        return []
    except Exception as e:
        print(f"API Error: {e}")
        return []

async def analyze_and_report():
    print("🔎 סורק אירועים בפולימרקט...")
    events = get_polymarket_events()
    
    for e in events:
        if not isinstance(e, dict): continue # דילוג אם זה לא מילון
        
        question = e.get('question')
        prices = e.get('outcome_prices', [0, 0])
        
        try:
            current_odds = float(prices[0]) * 100 if prices else 0
        except:
            current_odds = 0

        if question:
            prompt = f"נתח את האירוע: '{question}'. המחיר בשוק הוא {current_odds}%. האם לפי החדשות זה הגיוני? ענה בקצרה: האם כדאי לקנות (BUY) או לא. ענה בעברית."
            try:
                res = ai_client.models.generate_content(model=MODEL, contents=prompt)
                analysis = res.text
                
                # שולח רק אם יש המלצת קנייה
                if "BUY" in analysis.upper():
                    msg = f"🎯 **הזדמנות בפולימרקט (סימולציה)**\n\n📌 שאלה: {question}\n📊 סיכוי שוק: {current_odds:.1f}%\n🧠 ניתוח AI: {analysis}"
                    await tg_bot.send_message(chat_id=CHAT_ID, text=msg)
            except Exception as ai_err:
                print(f"AI Error: {ai_err}")

async def main():
    # הודעת פתיחה (עם await)
    await tg_bot.send_message(chat_id=CHAT_ID, text="🤖 בוט פולימרקט Scout V1.1 עלה לאוויר")
    while True:
        await analyze_and_report()
        await asyncio.sleep(3600) # סריקה פעם בשעה

if __name__ == "__main__":
    asyncio.run(main())
