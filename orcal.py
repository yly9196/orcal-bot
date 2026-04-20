import pandas as pd
import numpy as np
import pandas_ta as ta
from flask import Flask, request, jsonify
from flask_cors import CORS
from sklearn.ensemble import GradientBoostingClassifier
from binance.client import Client
import time
import warnings
warnings.filterwarnings('ignore')

app = Flask(__name__)
CORS(app)
client = Client()

# --- מערכת הזיכרון (Cache) של קרן הגידור ---
model_cache = {}
CACHE_TIME_LIMIT = 15 * 60  # 15 דקות בשניות

def get_market_data(symbol="BTCUSDT", interval="1h", limit=200):
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
    df['returns'] = df['close'].pct_change()
    df['range'] = (df['high'] - df['low']) / df['close']
    df['vol_change'] = df['volume'].pct_change()
    df['rsi'] = ta.rsi(df['close'], length=14)
    df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
    df['adx'] = ta.adx(df['high'], df['low'], df['close'], length=14)['ADX_14']
    df['target'] = (df['returns'].shift(-1) > 0.001).astype(int)
    
    df.dropna(inplace=True)
    features = ['returns', 'range', 'vol_change', 'rsi', 'atr', 'adx']
    return df[features], df['target']

@app.route('/ask_oracle', methods=['GET'])
def ask_oracle():
    global model_cache
    symbol = request.args.get('symbol', 'BTCUSDT')
    current_time = time.time()
    
    df = get_market_data(symbol=symbol)
    if df is None or len(df) < 50:
        return jsonify({"prediction": 0, "status": "error", "msg": "not enough data"})

    X, y = prepare_features(df)
    last_features = X.tail(1)
    
    # בדיקה האם המודל קיים בזיכרון והאם עברו פחות מ-15 דקות
    if symbol in model_cache and (current_time - model_cache[symbol]['time']) < CACHE_TIME_LIMIT:
        model = model_cache[symbol]['model']
        # שימוש במודל הקיים לחיזוי מהיר
    else:
        # אימון מחדש (קורה רק פעם ב-15 דקות לכל מטבע)
        print(f"[{symbol}] Training new AI model (15m interval)...")
        model = GradientBoostingClassifier(n_estimators=100, learning_rate=0.1, max_depth=3)
        model.fit(X[:-1], y[:-1])
        model_cache[symbol] = {'model': model, 'time': current_time}
    
    prediction = int(model.predict(last_features)[0])
    confidence = float(np.max(model.predict_proba(last_features)))
    
    return jsonify({
        "symbol": symbol,
        "prediction": prediction,
        "confidence": confidence,
        "market_strength": float(last_features['adx'].values[0]),
        "version": "Ultra-Pro-V44-Cached"
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)

