import os
import time
import pandas as pd
import numpy as np
from flask import Flask, jsonify, request
from binance.client import Client
from sklearn.ensemble import RandomForestClassifier

app = Flask(__name__)
binance_client = Client()
ORACLE_SECRET = os.getenv("ORACLE_SECRET", "ApexQuant2026")

# 🧠 זיכרון המודלים (מונע אימון מחדש כל 30 שניות)
model_cache = {}
CACHE_DURATION_SECONDS = 3600 * 6 

def add_advanced_features(df):
    """הוספת אינדיקטורים טכניים כדי שהמודל יבין מגמות"""
    # חישוב RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    df['rsi'] = 100 - (100 / (1 + (gain / loss)))
    
    # ממוצעים ומרחקים (זיהוי קפיצות חדות מדי)
    df['ema_9'] = df['close'].ewm(span=9).mean()
    df['sma_50'] = df['close'].rolling(window=50).mean()
    df['dist_ema'] = (df['close'] - df['ema_9']) / df['ema_9']
    
    # תנודתיות ורצועות
    df['std'] = df['close'].rolling(window=20).std()
    
    # אחוזי שינוי וזינוקי ווליום
    df['returns'] = df['close'].pct_change()
    df['vol_surge'] = df['volume'] / df['volume'].rolling(20).mean()
    
    return df

def get_market_context(symbol, limit=500):
    """שאיבת נתוני המטבע והקורלציה שלו לביטקוין"""
    # 1. נתוני המטבע
    klines = binance_client.futures_klines(symbol=symbol, interval='15m', limit=limit)
    df = pd.DataFrame(klines, columns=['ts', 'o', 'h', 'l', 'c', 'v', 'ct', 'qa', 'nt', 'tb', 'tq', 'i'])
    df = df[['o', 'h', 'l', 'c', 'v']].astype(float)
    df.columns = ['open', 'high', 'low', 'close', 'volume']
    df = add_advanced_features(df)
    
    # 2. קורלציה לביטקוין (מנוע גידור סיכונים)
    btc = binance_client.futures_klines(symbol='BTCUSDT', interval='15m', limit=limit)
    btc_df = pd.DataFrame(btc, columns=['ts', 'o', 'h', 'l', 'c', 'v', 'ct', 'qa', 'nt', 'tb', 'tq', 'i'])
    btc_close = btc_df['c'].astype(float)
    df['btc_corr'] = df['close'].rolling(window=30).corr(btc_close)
    df['btc_returns'] = btc_close.pct_change()
    
    # מטרת הלימוד: האם הנר הבא ירוק?
    df['target'] = (df['returns'].shift(-1) > 0).astype(int)
    return df.dropna()

def train_and_predict(symbol):
    features = ['rsi', 'dist_ema', 'vol_surge', 'btc_corr', 'btc_returns']
    curr_time = time.time()
    
    # אם יש מודל טרי בזיכרון - משתמשים בו לשליפה מהירה
    if symbol in model_cache and (curr_time - model_cache[symbol]['ts']) < CACHE_DURATION_SECONDS:
        model = model_cache[symbol]['m']
        df = get_market_context(symbol, limit=100) # מוריד רק קצת נרות
        latest_data = df[features].iloc[[-1]]
        probs = model.predict_proba(latest_data)[0]
        return probs[1], probs[0], df['btc_corr'].iloc[-1]

    # אם אין - מאמן מודל כבד וחדש
    df = get_market_context(symbol)
    model = RandomForestClassifier(n_estimators=150, max_depth=7, random_state=42)
    model.fit(df[features], df['target'])
    
    model_cache[symbol] = {'m': model, 'ts': curr_time}
    latest_data = df[features].iloc[[-1]]
    probs = model.predict_proba(latest_data)[0]
    return probs[1], probs[0], df['btc_corr'].iloc[-1]

@app.route('/', methods=['GET'])
def health_check():
    return jsonify({"status": "Apex Oracle V2 (Senior Quant) is Online 🧠"}), 200

@app.route('/ask_oracle', methods=['GET'])
def ask_oracle():
    if request.args.get('secret') != ORACLE_SECRET: 
        return jsonify({"error": "Unauthorized"}), 401
    
    symbol = request.args.get('symbol')
    if not symbol:
        return jsonify({"error": "Symbol missing"}), 400

    try:
        up, down, corr = train_and_predict(symbol)
        
        rec = "HOLD"
        # מחמירים בתנאים: עליה בהסתברות, וגם בודקים שהמטבע לא רק "מחקה" את הביטקוין בצורה עיוורת
        if up > 0.55:
            rec = "BUY"
        elif down > 0.55:
            rec = "SELL"
        
        return jsonify({
            "symbol": symbol,
            "recommendation": rec, 
            "probability_UP": round(up*100,2),
            "probability_DOWN": round(down*100,2), 
            "correlation_btc": round(corr,2),
            "cached": (symbol in model_cache)
        }), 200
        
    except Exception as e: 
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))

