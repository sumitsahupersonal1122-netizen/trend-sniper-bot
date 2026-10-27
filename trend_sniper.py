import os
import json
import requests
import pyotp
from smartapi import SmartConnect
import yfinance as yf
import pandas as pd
from datetime import datetime, time as dt_time, timedelta

# === SECRETS FROM GITHUB ===
AO_CLIENT_ID = os.environ.get('AO_CLIENT_ID')
AO_PASSWORD = os.environ.get('AO_PASSWORD')
AO_TOTP_SECRET = os.environ.get('AO_TOTP_SECRET')
AO_API_KEY = os.environ.get('AO_API_KEY')
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

TRADES_FILE = 'trades.json'
PAPER_TRADING = True  # TRUE = Sirf alert, koi real order nahi
LOT_SIZE = 65
BROKERAGE_PER_TRADE = 50

def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram credentials missing")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'HTML'}
    try:
        requests.post(url, data=payload)
        print("Telegram alert sent!")
    except Exception as e:
        print(f"Telegram error: {e}")

def login_angel_one():
    try:
        obj = SmartConnect(api_key=AO_API_KEY)
        totp = pyotp.TOTP(AO_TOTP_SECRET).now()
        data = obj.generateSession(AO_CLIENT_ID, AO_PASSWORD, totp)
        print(f"Angel One login success! Token: {data.get('data', {}).get('jwtToken', 'N/A')[:20]}...")
        return obj
    except Exception as e:
        print(f"Angel One login failed: {e}")
        send_telegram_message(f"⚠️ Angel One Login Failed!\nError: {str(e)[:200]}")
        return None

def get_nifty_data():
    try:
        nifty = yf.download('^NSEI', period='1mo', interval='15m')
        if nifty.empty:
            return None
        nifty = nifty.reset_index()
        nifty.columns = [col[0] if isinstance(col, tuple) else col for col in nifty.columns]
        return nifty
    except Exception as e:
        print(f"Data error: {e}")
        return None

def calculate_indicators(df):
    df['EMA_50'] = df['Close'].ewm(span=50, adjust=False).mean()
    df['EMA_200'] = df['Close'].ewm(span=200, adjust=False).mean()
    df['Prev_5_High'] = df['High'].shift(1).rolling(window=5).max()
    df['Prev_5_Low'] = df['Low'].shift(1).rolling(window=5).min()
    return df

def load_trades():
    if os.path.exists(TRADES_FILE):
        with open(TRADES_FILE, 'r') as f:
            return json.load(f)
    return []

def save_trades(trades):
    with open(TRADES_FILE, 'w') as f:
        json.dump(trades, f, indent=4)

def check_open_trades(trades, current_price):
    for trade in trades:
        if trade['status'] == 'OPEN':
            hit = False
            result = ""
            exit_price = 0
            if trade['type'] == 'LONG':
                if current_price <= trade['sl']:
                    hit = True; result = "STOP LOSS HIT ❌"; exit_price = trade['sl']
                elif current_price >= trade['target']:
                    hit = True; result = "TARGET HIT 🎯"; exit_price = trade['target']
            elif trade['type'] == 'SHORT':
                if current_price >= trade['sl']:
                    hit = True; result = "STOP LOSS HIT "; exit_price = trade['sl']
                elif current_price <= trade['target']:
                    hit = True; result = "TARGET HIT 🎯"; exit_price = trade['target']
            if hit:
                trade['status'] = 'CLOSED'
                trade['exit_price'] = exit_price
                trade['result'] = result
                pts = abs(exit_price - trade['entry'])
                profit = (pts * LOT_SIZE) - BROKERAGE_PER_TRADE
                msg = f"📊 <b>Trade Closed!</b>\n{result}\nEntry: {trade['entry']}\nExit: {exit_price}\nP&L: ₹{profit:.2f}"
                send_telegram_message(msg)

def main():
    print("=== Trend Sniper Bot Started ===")
    print(f"Mode: {'PAPER TRADING' if PAPER_TRADING else 'LIVE TRADING'}")
    
    # Login to Angel One
    obj = login_angel_one()
    if obj is None:
        print("Cannot proceed without login")
        return
    
    # Get data
    df = get_nifty_data()
    if df is None:
        send_telegram_message(" Data fetch failed!")
        return
    
    df = calculate_indicators(df)
    latest = df.iloc[-1]
    current_price = latest['Close']
    current_time = latest['Datetime'].strftime('%H:%M') if 'Datetime' in df.columns else datetime.now().strftime('%H:%M')
    
    print(f"Current Nifty: {current_price} at {current_time}")
    
    # Load trades
    trades = load_trades()
    
    # Check open trades
    check_open_trades(trades, current_price)
    
    # Check for new signal (only in time window)
    last_trade = trades[-1] if trades else None
    can_trade = True
    if last_trade and last_trade['status'] == 'OPEN':
        can_trade = False
    
    if can_trade and len(df) > 10:
        close = latest['Close']
        ema50 = latest['EMA_50']
        ema200 = latest['EMA_200']
        p5_high = latest['Prev_5_High']
        p5_low = latest['Prev_5_Low']
        
        if not pd.isna(ema50) and not pd.isna(ema200):
            if close > ema50 and close > ema200 and close > p5_high:
                new_trade = {
                    'type': 'LONG', 'entry': close, 'sl': close - 50, 'target': close + 200,
                    'status': 'OPEN', 'time': current_time
                }
                trades.append(new_trade)
                save_trades(trades)
                msg = f"🚨 <b>NEW SETUP (PAPER)!</b>\nLONG @ {close}\nSL: {close-50}\nTarget: {close+200}\nTime: {current_time}"
                send_telegram_message(msg)
                print(f"LONG signal at {close}")
                
            elif close < ema50 and close < ema200 and close < p5_low:
                new_trade = {
                    'type': 'SHORT', 'entry': close, 'sl': close + 50, 'target': close - 200,
                    'status': 'OPEN', 'time': current_time
                }
                trades.append(new_trade)
                save_trades(trades)
                msg = f"🚨 <b>NEW SETUP (PAPER)!</b>\nSHORT @ {close}\nSL: {close+50}\nTarget: {close-200}\nTime: {current_time}"
                send_telegram_message(msg)
                print(f"SHORT signal at {close}")
    
    save_trades(trades)
    print("=== Bot Finished ===")

if __name__ == '__main__':
    main()
