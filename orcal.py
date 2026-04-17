import pandas as pd
import numpy as np
from flask import Flask, request, jsonify
from flask_cors import CORS
from sklearn.ensemble import RandomForestClassifier
from binance.client import Client

app = Flask(__name__)
CORS(app)

# התחברות לבינאנס למשיכת נתוני שוק
client = Client()

def get_market_data(symbol="BTCUSDT", interval="1h", limit=100):
    try:
        klines = client.get_klines(symbol=symbol, interval=interval, limit=limit)
        df = pd.DataFrame(klines, columns=['time', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'qav', 'num_trades', 'taker_base', 'taker_quote', 'ignore'])
        df['close'] = df['close'].astype(float)
        df['volume'] = df['volume'].astype(float)
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        return df
    except Exception as e:
        print(f"Error fetching data: {e}")
        return None

def prepare_features(df):
    # חישוב אינדיקטורים עבור מודל ה-AI
    df['returns'] = df['close'].pct_change()
    df['range'] = (df['high'] - df['low']) / df['close']
    df['vol_change'] = df['volume'].pct_change()
    
    # חיזוי מגמה: 1 לעלייה, 0 לירידה
    df['target'] = (df['returns'].shift(-1) > 0).astype(int)
    
    df.dropna(inplace=True)
    features = ['returns', 'range', 'vol_change']
    return df[features], df['target']

# שים לב שכאן שינינו ל-ask_oracle כדי שיתאים לבוט הראשי
@app.route('/ask_oracle', methods=['GET'])
def ask_oracle():
    symbol = request.args.get('symbol', 'BTCUSDT')
    df = get_market_data(symbol=symbol)
    
    if df is None or len(df) < 50:
        return jsonify({"prediction": 0, "status": "error", "msg": "not enough data"})

    X, y = prepare_features(df)
    
    # הרצת מודל היער האקראי (Random Forest V42)
    model = RandomForestClassifier(n_estimators=100, max_depth=5)
    model.fit(X[:-1], y[:-1])
    
    last_features = X.tail(1)
    prediction = int(model.predict(last_features)[0])
    
    return jsonify({
        "symbol": symbol,
        "prediction": prediction,
        "confidence": float(np.max(model.predict_proba(last_features))),
        "version": "V42-Oracle-OracleCloud"
    })

@app.route('/')
def home():
    return "Oracle AI Server V42 is Running on Oracle Cloud Frankfurt!"

if __name__ == '__main__':
    # הרצה על הפורט שהגדרנו בחומת האש
    app.run(host='0.0.0.0', port=10000)

