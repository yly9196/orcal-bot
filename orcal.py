import os
import time
import pandas as pd
import numpy as np
from flask import Flask, jsonify, request
from binance.client import Client
from sklearn.ensemble import RandomForestClassifier

app = Flask(__name__)

# התחברות בסיסית לבינאנס (ללא מפתחות - קריאת נתונים ציבוריים בלבד)
binance_client = Client()

# סיסמת האבטחה
ORACLE_SECRET = os.getenv("ORACLE_SECRET", "ApexQuant2026")

# 🧠 הזיכרון של האורקל (Model Cache)
# פה השרת שומר מודלים מאומנים כדי לא לאמן אותם מחדש כל שנייה. מתאפס כל 6 שעות.
model_cache = {}
CACHE_DURATION_SECONDS = 3600 * 6 

def add_technical_features(df):
    """חישוב אינדיקטורים מתקדמים למודל ה-Machine Learning"""
    # חישוב RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi_14'] = 100 - (100 / (1 + rs))
    
    # חישוב ממוצעים נעים והמרחק מהם (חשוב לזיהוי חזרות לממוצע - Mean Reversion)
    df['sma_20'] = df['close'].rolling(window=20).mean()
    df['dist_sma_20'] = (df['close'] - df['sma_20']) / df['sma_20']
    
    # חישוב תנודתיות (אחוזי שינוי)
    df['returns'] = df['close'].pct_change()
    df['vol_change'] = df['volume'].pct_change()
    
    return df

def get_historical_data_with_btc(symbol, limit=1000):
    """שאיבת היסטוריה של המטבע + שילוב הנתונים של ביטקוין להבנת מצב השוק הגלובלי"""
    
    # 1. שאיבת נתוני המטבע המבוקש
    klines = binance_client.futures_klines(symbol=symbol, interval='15m', limit=limit)
    df = pd.DataFrame(klines, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'qav', 'num_trades', 'tbv', 'tqv', 'ignore'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    df = df[['open', 'high', 'low', 'close', 'volume']].astype(float)
    
    df = add_technical_features(df)
    
    # 2. הוספת "אפקט הביטקוין" (BTC Factor)
    if symbol != 'BTCUSDT':
        btc_klines = binance_client.futures_klines(symbol='BTCUSDT', interval='15m', limit=limit)
        btc_df = pd.DataFrame(btc_klines, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'qav', 'num_trades', 'tbv', 'tqv', 'ignore'])
        btc_df['timestamp'] = pd.to_datetime(btc_df['timestamp'], unit='ms')
        btc_df.set_index('timestamp', inplace=True)
        btc_df['btc_returns'] = btc_df['close'].astype(float).pct_change()
        
        # חיבור טבלת הביטקוין לטבלת המטבע שלנו
        df = df.join(btc_df[['btc_returns']], how='left')
    else:
        # אם המטבע הוא ביטקוין, המגמה הגלובלית היא המגמה שלו
        df['btc_returns'] = df['returns'] 
        
    # 3. תווית המטרה (Target): האם הנר הבא היה ירוק?
    df['target'] = (df['returns'].shift(-1) > 0).astype(int)
    
    # ניקוי שורות ריקות שנוצרו מהחישובים
    df.dropna(inplace=True)
    return df

def train_and_predict(symbol):
    """המוח המרכזי: מאמן מודל או שולף מודל מהזיכרון כדי לתת תחזית מיידית"""
    current_time = time.time()
    features = ['returns', 'vol_change', 'rsi_14', 'dist_sma_20', 'btc_returns']
    
    # ⚡ בדיקת הזיכרון (Cache): האם כבר אימנו מודל למטבע הזה ב-6 השעות האחרונות?
    if symbol in model_cache and (current_time - model_cache[symbol]['last_trained']) < CACHE_DURATION_SECONDS:
        model = model_cache[symbol]['model']
        
        # אנחנו צריכים רק את הנרות האחרונים כדי לדעת מה קורה עכשיו (חיסכון עצום בזמן)
        df_latest = get_historical_data_with_btc(symbol, limit=100) 
        
        # שים לב לסוגריים הכפולים כדי למנוע את הודעת השגיאה (UserWarning)
        latest_data = df_latest[features].iloc[[-1]] 
        
        probabilities = model.predict_proba(latest_data)[0]
        return probabilities[1], probabilities[0]

    # 🐌 אם הגענו לפה, המודל לא בזיכרון או שהוא ישן. מאמנים מחדש על היסטוריה עמוקה.
    df = get_historical_data_with_btc(symbol, limit=1000)
    
    X = df[features]
    y = df['target']
    
    # אימון יער אקראי (Random Forest)
    model = RandomForestClassifier(n_estimators=100, random_state=42, max_depth=5)
    model.fit(X, y)
    
    # שמירת המודל לזיכרון של השרת כדי שבפעם הבאה זה יהיה מהיר יותר
    model_cache[symbol] = {
        'model': model,
        'last_trained': current_time,
        'features': features
    }
    
    latest_data = X.iloc[[-1]]
    probabilities = model.predict_proba(latest_data)[0]
    
    return probabilities[1], probabilities[0]

@app.route('/', methods=['GET'])
def health_check():
    return jsonify({"status": "Apex Oracle V2 (Senior Quant) is Online 🧠"}), 200

@app.route('/ask_oracle', methods=['GET'])
def ask_oracle():
    """נקודת הקצה (Endpoint) שאליה הבוט הראשי פונה"""
    provided_secret = request.args.get('secret')
    if provided_secret != ORACLE_SECRET:
        return jsonify({"error": "Unauthorized"}), 401

    symbol = request.args.get('symbol')
    if not symbol:
        return jsonify({"error": "Symbol missing"}), 400

    try:
        prob_up, prob_down = train_and_predict(symbol)
        
        # ייצור המלצה - נדרוש לפחות 55% ביטחון כדי לאשר עסקה
        recommendation = "HOLD"
        if prob_up > 0.55:
            recommendation = "BUY"
        elif prob_down > 0.55:
            recommendation = "SELL"
            
        return jsonify({
            "symbol": symbol,
            "probability_UP": round(prob_up * 100, 2),
            "probability_DOWN": round(prob_down * 100, 2),
            "recommendation": recommendation,
            "cached": (symbol in model_cache) # אינדיקציה האם זה נשלף מהזיכרון
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

