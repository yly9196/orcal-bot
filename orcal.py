import os
import pandas as pd
import numpy as np
from flask import Flask, jsonify, request
from binance.client import Client
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split

app = Flask(__name__)

# אנחנו לא צריכים מפתחות API שלמים כי אנחנו שואבים רק נתונים ציבוריים מהגרפים!
binance_client = Client()

# סיסמה מאובטחת כדי שרק הבוט שלך יוכל לדבר עם האורקל
ORACLE_SECRET = os.getenv("ORACLE_SECRET", "ApexQuant2026")

def get_historical_data(symbol, limit=1000):
    """שואב היסטוריה ובנה פיצ'רים ללמידת מכונה"""
    klines = binance_client.futures_klines(symbol=symbol, interval='15m', limit=limit)
    df = pd.DataFrame(klines, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'quote_av', 'trades', 'tb_base_av', 'tb_quote_av', 'ignore'])
    df = df[['open', 'high', 'low', 'close', 'volume']].astype(float)
    
    # יצירת "פיצ'רים" למודל (RSI בסיסי, שינויי מחיר, ושינויי ווליום)
    df['returns'] = df['close'].pct_change()
    df['vol_change'] = df['volume'].pct_change()
    
    # תווית המטרה (Target): האם הנר *הבא* היה ירוק? (1 = כן, 0 = לא)
    df['target'] = (df['returns'].shift(-1) > 0).astype(int)
    
    df.dropna(inplace=True)
    return df

def train_and_predict(symbol):
    """מאמן את המודל ומחזיר הסתברות"""
    df = get_historical_data(symbol)
    
    # הנתונים שהמודל יסתכל עליהם (X) והתשובה שהוא מנסה לחזות (y)
    features = ['returns', 'vol_change', 'open', 'high', 'low', 'close', 'volume']
    X = df[features]
    y = df['target']
    
    # בניית מודל למידת המכונה (Random Forest)
    model = RandomForestClassifier(n_estimators=100, random_state=42, max_depth=5)
    model.fit(X, y) # אימון המודל על כל ההיסטוריה!
    
    # לוקחים את הנתונים של הרגע הזה ממש כדי לחזות את העתיד הקרוב
    latest_data = X.iloc[-1].values.reshape(1, -1)
    
    # חישוב הסתברות
    probabilities = model.predict_proba(latest_data)[0]
    prob_down = probabilities[0]
    prob_up = probabilities[1]
    
    return prob_up, prob_down

@app.route('/', methods=['GET'])
def health_check():
    return jsonify({"status": "Apex Oracle is Online 🧠"}), 200

@app.route('/ask_oracle', methods=['GET'])
def ask_oracle():
    """הנקודה שאליה הבוט הראשי יפנה כדי לקבל תחזית"""
    provided_secret = request.args.get('secret')
    if provided_secret != ORACLE_SECRET:
        return jsonify({"error": "Unauthorized"}), 401

    symbol = request.args.get('symbol')
    if not symbol:
        return jsonify({"error": "Symbol missing"}), 400

    try:
        prob_up, prob_down = train_and_predict(symbol)
        
        # מחזירים לבוט הראשי תשובה מסודרת
        return jsonify({
            "symbol": symbol,
            "probability_UP": round(prob_up * 100, 2),
            "probability_DOWN": round(prob_down * 100, 2),
            "recommendation": "BUY" if prob_up > 0.60 else "SELL" if prob_down > 0.60 else "HOLD"
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

