import yfinance as yf
import pandas as pd
import requests
import os
from datetime import datetime

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': message,
        'parse_mode': 'HTML'
    }
    try:
        response = requests.post(url, data=payload)
        if response.status_code == 200:
            print("Alert sent!")
        else:
            print(f"Failed: {response.text}")
    except Exception as e:
        print(f"Error: {e}")

def get_nifty_data():
    try:
        nifty = yf.download('^NSEI', period='5d', interval='1h')
        if nifty.empty:
            print("No data from Yahoo Finance")
            return None
        nifty = nifty.reset_index()
        nifty.columns = [col[0] if isinstance(col, tuple) else col for col in nifty.columns]
        print(f"Received {len(nifty)} candles")
        return nifty
    except Exception as e:
        print(f"Error fetching data: {e}")
        return None

def calculate_indicators(df):
    df['EMA_50'] = df['Close'].ewm(span=50, adjust=False).mean()
    df['EMA_200'] = df['Close'].ewm(span=200, adjust=False).mean()
    df['Prev_5_High'] = df['High'].shift(1).rolling(window=5).max()
    df['Prev_5_Low'] = df['Low'].shift(1).rolling(window=5).min()
    return df

def check_signal(df):
    if df is None or len(df) < 10:
        return None
    latest = df.iloc[-1]
    current_time = latest['Datetime'].time()
    entry_start = datetime.strptime('10:15:00', '%H:%M:%S').time()
    entry_end = datetime.strptime('14:15:00', '%H:%M:%S').time()
    if not (entry_start <= current_time <= entry_end):
        print(f"Time {current_time} outside entry window")
        return None
    close = latest['Close']
    ema_50 = latest['EMA_50']
    ema_200 = latest['EMA_200']
    prev_5_high = latest['Prev_5_High']
    prev_5_low = latest['Prev_5_Low']
    if pd.isna(ema_50) or pd.isna(ema_200):
        return None
    if close > ema_50 and close > ema_200 and close > prev_5_high:
        return {'type': 'LONG', 'entry': close, 'sl': close - 50, 'target': close + 200, 'time': current_time}
    elif close < ema_50 and close < ema_200 and close < prev_5_low:
        return {'type': 'SHORT', 'entry': close, 'sl': close + 50, 'target': close - 200, 'time': current_time}
    return None

def main():
    print("Trend Sniper Bot started...")
    df = get_nifty_data()
    if df is None:
        send_telegram_message("Error: Could not fetch Nifty 50 data")
        return
    df = calculate_indicators(df)
    signal = check_signal(df)
    if signal:
        message = f"""
🚨 TREND SNIPER ALERT

📈 Signal: {signal['type']}
 Entry: {signal['entry']:.2f}
🛑 Stop Loss: {signal['sl']:.2f} (50 pts)
 Target: {signal['target']:.2f} (200 pts)
⏰ Time: {signal['time'].strftime('%H:%M')}
📊 RR Ratio: 1:4

️ Reminder: Max 2 losses per day!
        """
        send_telegram_message(message)
    else:
        print("No signal today")

if __name__ == '__main__':
    main()
