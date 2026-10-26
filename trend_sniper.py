import yfinance as yf
import pandas as pd
import requests
import os
import json
from datetime import datetime

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')
TRADES_FILE = 'trades.json'

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'HTML'}
    try:
        requests.post(url, data=payload)
        print("Alert sent!")
    except Exception as e:
        print(f"Error sending alert: {e}")

def load_trades():
    if os.path.exists(TRADES_FILE):
        with open(TRADES_FILE, 'r') as f:
            return json.load(f)
    return []

def save_trades(trades):
    with open(TRADES_FILE, 'w') as f:
        json.dump(trades, f, indent=4)

def get_nifty_data():
    try:
        nifty = yf.download('^NSEI', period='1mo', interval='15m') # 15m data for better tracking
        if nifty.empty: return None
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

def main():
    print("Bot started...")
    trades = load_trades()
    df = get_nifty_data()
    
    if df is None:
        send_telegram_message("❌ Data fetch failed!")
        return

    df = calculate_indicators(df)
    latest = df.iloc[-1]
    current_price = latest['Close']
    current_time = latest['Datetime'].strftime('%H:%M')
    
    # 1. Check Existing Trades (SL/TP Hit?)
    for trade in trades:
        if trade['status'] == 'OPEN':
            hit = False
            result = ""
            exit_price = 0
            
            if trade['type'] == 'LONG':
                if current_price <= trade['sl']:
                    hit = True; result = "STOP LOSS HIT ❌"; exit_price = trade['sl']
                elif current_price >= trade['target']:
                    hit = True; result = "TARGET HIT "; exit_price = trade['target']
            elif trade['type'] == 'SHORT':
                if current_price >= trade['sl']:
                    hit = True; result = "STOP LOSS HIT ❌"; exit_price = trade['sl']
                elif current_price <= trade['target']:
                    hit = True; result = "TARGET HIT 🎯"; exit_price = trade['target']
            
            if hit:
                trade['status'] = 'CLOSED'
                trade['exit_price'] = exit_price
                trade['result'] = result
                pts = abs(exit_price - trade['entry'])
                profit = (pts * 50) - 100 # Approx lot size 50 for Nifty, brokerage 100
                msg = f" <b>Trade Closed!</b>\n{result}\nEntry: {trade['entry']}\nExit: {exit_price}\nP&L: ₹{profit}"
                send_telegram_message(msg)

    # 2. Check for New Entry (Only if no open trade today)
    # Simple logic: If last trade is closed or list is empty, look for signal
    last_trade = trades[-1] if trades else None
    can_trade = True
    if last_trade and last_trade['status'] == 'OPEN':
        can_trade = False # Don't take new trade if one is running
        
    # Time filter (10:15 to 14:15)
    # Note: Yahoo finance time is UTC, need to be careful. 
    # For simplicity, we check if 'Datetime' column has time. 
    # Since we run every 15 mins, we check the latest candle.
    
    if can_trade and len(df) > 10:
        # Re-calculate indicators properly for the latest candle
        close = latest['Close']
        ema50 = latest['EMA_50']
        ema200 = latest['EMA_200']
        p5_high = latest['Prev_5_High']
        p5_low = latest['Prev_5_Low']
        
        # Check Time (Approximate for IST 10:15 - 14:15)
        # Yahoo data index 0 is date. Let's assume valid time for now or add check.
        # For robustness, we just check conditions.
        
        if not pd.isna(ema50) and not pd.isna(ema200):
            if close > ema50 and close > ema200 and close > p5_high:
                new_trade = {
                    'type': 'LONG', 'entry': close, 'sl': close - 50, 'target': close + 200,
                    'status': 'OPEN', 'time': current_time
                }
                trades.append(new_trade)
                save_trades(trades)
                send_telegram_message(f"🚨 <b>NEW SETUP!</b>\nLONG @ {close}\nSL: {close-50}\nTarget: {close+200}")
                
            elif close < ema50 and close < ema200 and close < p5_low:
                new_trade = {
                    'type': 'SHORT', 'entry': close, 'sl': close + 50, 'target': close - 200,
                    'status': 'OPEN', 'time': current_time
                }
                trades.append(new_trade)
                save_trades(trades)
                send_telegram_message(f"🚨 <b>NEW SETUP!</b>\nSHORT @ {close}\nSL: {close+50}\nTarget: {close-200}")

    save_trades(trades) # Save any updates
    print("Bot finished.")

if __name__ == '__main__':
    main()
