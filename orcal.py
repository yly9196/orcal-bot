import pandas as pd
import numpy as np
import pandas_ta as ta
from flask import Flask, request, jsonify
from flask_cors import CORS
from sklearn.ensemble import GradientBoostingClassifier
from binance.client import Client
import warnings
warnings.filterwarnings('ignore')

app = Flask(__name__)
CORS(app)

# התחברות לבינאנס למשיכת נתוני שוק
client = Client()

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
    # חישוב אינדיקטורים עבור מודל ה-AI - שדרוג לרמת קרן גידור
    df['returns'] = df['close'].pct_change()
    df['range'] = (df['high'] - df['low']) / df['close']
    df['vol_change'] = df['volume'].pct_change()
    df['rsi'] = ta.rsi(df['close'], length=14)
    df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
    df['adx'] = ta.adx(df['high'], df['low'], df['close'], length=14)['ADX_14']
    
    # חיזוי מגמה: 1 לעלייה, 0 לירידה (דורשים לפחות עלייה קלה כדי לסנן רעשים)
    df['target'] = (df['returns'].shift(-1) > 0.001).astype(int)
    
    df.dropna(inplace=True)
    features = ['returns', 'range', 'vol_change', 'rsi', 'atr', 'adx']
    return df[features], df['target']

@app.route('/ask_oracle', methods=['GET'])
def ask_oracle():
    symbol = request.args.get('symbol', 'BTCUSDT')
    df = get_market_data(symbol=symbol)
    
    if df is None or len(df) < 50:
        return jsonify({"prediction": 0, "status": "error", "msg": "not enough data"})

    X, y = prepare_features(df)
    
    # הרצת מודל מתקדם (Gradient Boosting)
    model = GradientBoostingClassifier(n_estimators=100, learning_rate=0.1, max_depth=3)
    model.fit(X[:-1], y[:-1])
    
    last_features = X.tail(1)
    prediction = int(model.predict(last_features)[0])
    confidence = float(np.max(model.predict_proba(last_features)))
    
    return jsonify({
        "symbol": symbol,
        "prediction": prediction,
        "confidence": confidence,
        "market_strength": float(last_features['adx'].values[0]),
        "version": "Ultra-Pro-V43-OracleCloud"
    })

@app.route('/')
def home():
    return "Oracle AI Server Ultra Pro is Running on Port 10000!"

if __name__ == '__main__':
    # שומרים על פורט 10000 בדיוק כמו שביקשת
    app.run(host='0.0.0.0', port=10000)
