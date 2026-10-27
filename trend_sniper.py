import os
import json
import requests
import pyotp
import yfinance as yf
import pandas as pd
from datetime import datetime, time as dt_time, timedelta

try:
    from smartapi import SmartConnect
except ImportError:
    from SmartApi import SmartConnect

AO_CLIENT_ID = os.environ.get('AO_CLIENT_ID')
AO_PASSWORD = os.environ.get('AO_PASSWORD')
AO_TOTP_SECRET = os.environ.get('AO_TOTP_SECRET')
AO_API_KEY = os.environ.get('AO_API_KEY')
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

TRADES_FILE = 'trades.json'
PAPER_TRADING = True
LOT_SIZE = 65
BROKERAGE_PER_TRADE = 50
STARTING_CAPITAL = 50000
MAX_DAILY_LOSSES = 2

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
        if not AO_CLIENT_ID or not AO_PASSWORD or not AO_TOTP_SECRET or not AO_API_KEY:
            print("Angel One credentials missing!")
            send_telegram_message("Angel One credentials missing in GitHub Secrets!")
            return None
        obj = SmartConnect(api_key=AO_API_KEY)
        totp = pyotp.TOTP(AO_TOTP_SECRET).now()
        data = obj.generateSession(AO_CLIENT_ID, AO_PASSWORD, totp)
        jwt_token = data.get('data', {}).get('jwtToken', 'N/A')
        print(f"Angel One login success! Token: {str(jwt_token)[:20]}...")
        send_telegram_message(f"Angel One Login Success!\nMode: {'PAPER' if PAPER_TRADING else 'LIVE'}\nTime: {datetime.now().strftime('%H:%M')}")
        return obj
    except Exception as e:
        error_msg = str(e)[:300]
        print(f"Angel One login failed: {error_msg}")
        send_telegram_message(f"Angel One Login Failed!\nError: {error_msg}")
        return None

def get_nifty_data():
    try:
        nifty = yf.download('^NSEI', period='1mo', interval='15m', progress=False)
        if nifty.empty:
            print("No data received from Yahoo Finance")
            return None
        nifty = nifty.reset_index()
        nifty.columns = [col[0] if isinstance(col, tuple) else col for col in nifty.columns]
        if 'Datetime' not in nifty.columns and 'Date' in nifty.columns:
            nifty.rename(columns={'Date': 'Datetime'}, inplace=True)
        return nifty
    except Exception as e:
        print(f"Data fetch error: {e}")
        return None

def calculate_indicators(df):
    df['EMA_50'] = df['Close'].ewm(span=50, adjust=False).mean()
    df['EMA_200'] = df['Close'].ewm(span=200, adjust=False).mean()
    df['Prev_5_High'] = df['High'].shift(1).rolling(window=5).max()
    df['Prev_5_Low'] = df['Low'].shift(1).rolling(window=5).min()
    return df

def load_trades():
    if os.path.exists(TRADES_FILE):
        try:
            with open(TRADES_FILE, 'r') as f:
                return json.load(f)
        except:
            return []
    return []

def save_trades(trades):
    with open(TRADES_FILE, 'w') as f:
        json.dump(trades, f, indent=4)

def check_open_trades(trades, current_price, current_time_str):
    updated = False
    for trade in trades:
        if trade.get('status') != 'OPEN':
            continue
        hit = False
        result = ""
        exit_price = 0
        if trade['type'] == 'LONG':
            if current_price <= trade['sl']:
                hit = True
                result = "STOP LOSS HIT"
                exit_price = trade['sl']
            elif current_price >= trade['target']:
                hit = True
                result = "TARGET HIT"
                exit_price = trade['target']
        elif trade['type'] == 'SHORT':
            if current_price >= trade['sl']:
                hit = True
                result = "STOP LOSS HIT"
                exit_price = trade['sl']
            elif current_price <= trade['target']:
                hit = True
                result = "TARGET HIT"
                exit_price = trade['target']
        if hit:
            trade['status'] = 'CLOSED'
            trade['exit_price'] = exit_price
            trade['result'] = result
            trade['exit_time'] = current_time_str
            pts = abs(exit_price - trade['entry'])
            profit = (pts * LOT_SIZE) - BROKERAGE_PER_TRADE
            if result == "STOP LOSS HIT":
                profit = -profit
            msg = f"Trade Closed!\n{result}\nType: {trade['type']}\nEntry: {trade['entry']:.2f}\nExit: {exit_price:.2f}\nP&L: Rs.{profit:.2f}\nTime: {current_time_str}"
            send_telegram_message(msg)
            print(f"Trade closed: {result} | P&L: Rs.{profit:.2f}")
            updated = True
    return updated

def is_within_trading_time(current_time):
    return dt_time(10, 15) <= current_time <= dt_time(14, 15)

def get_today_losses(trades):
    today = datetime.now().date()
    count = 0
    for trade in trades:
        if trade.get('status') == 'CLOSED' and trade.get('result', '').startswith('STOP LOSS'):
            try:
                trade_date = datetime.fromisoformat(trade.get('exit_time', '')).date() if trade.get('exit_time') else None
                if trade_date == today:
                    count += 1
            except:
                pass
    return count

def main():
    print("=" * 50)
    print("Trend Sniper Bot Started")
    print(f"Mode: {'PAPER TRADING' if PAPER_TRADING else 'LIVE TRADING'}")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)
    print("\n[1] Logging into Angel One...")
    obj = login_angel_one()
    if obj is None:
        print("Cannot proceed without login")
        return
    print("\n[2] Fetching Nifty 50 data...")
    df = get_nifty_data()
    if df is None or df.empty:
        send_telegram_message("Nifty data fetch failed!")
        return
    print(f"Received {len(df)} candles")
    print("\n[3] Calculating indicators...")
    df = calculate_indicators(df)
    latest = df.iloc[-1]
    current_price = latest['Close']
    if 'Datetime' in df.columns:
        current_dt = latest['Datetime']
        if hasattr(current_dt, 'strftime'):
            current_time_str = current_dt.strftime('%H:%M')
            current_time = current_dt.time() if hasattr(current_dt, 'time') else dt_time(10, 15)
        else:
            current_time_str = datetime.now().strftime('%H:%M')
            current_time = datetime.now().time()
    else:
        current_time_str = datetime.now().strftime('%H:%M')
        current_time = datetime.now().time()
    print(f"Current Nifty: {current_price:.2f} at {current_time_str}")
    trades = load_trades()
    print(f"\n[4] Loaded {len(trades)} trades from diary")
    print("\n[5] Checking open trades...")
    check_open_trades(trades, current_price, current_time_str)
    can_trade = True
    has_open_trade = any(t.get('status') == 'OPEN' for t in trades)
    today_losses = get_today_losses(trades)
    if has_open_trade:
        print("Already have an open trade - skipping new signal")
        can_trade = False
    elif today_losses >= MAX_DAILY_LOSSES:
        print(f"Daily loss limit reached ({today_losses}/{MAX_DAILY_LOSSES})")
        can_trade = False
    elif not is_within_trading_time(current_time):
        print(f"Outside trading window ({current_time_str})")
        can_trade = False
    if can_trade and len(df) > 10:
        print("\n[6] Checking for new signal...")
        close = latest['Close']
        ema50 = latest['EMA_50']
        ema200 = latest['EMA_200']
        p5_high = latest['Prev_5_High']
        p5_low = latest['Prev_5_Low']
        print(f"Close: {close:.2f} | EMA50: {ema50:.2f} | EMA200: {ema200:.2f}")
        print(f"Prev5High: {p5_high:.2f} | Prev5Low: {p5_low:.2f}")
        signal = None
        if not pd.isna(ema50) and not pd.isna(ema200) and not pd.isna(p5_high) and not pd.isna(p5_low):
            if close > ema50 and close > ema200 and close > p5_high:
                signal = 'LONG'
            elif close < ema50 and close < ema200 and close < p5_low:
                signal = 'SHORT'
        if signal:
            print(f"\nNEW {signal} SIGNAL DETECTED!")
            entry_price = close
            sl = entry_price - 50 if signal == 'LONG' else entry_price + 50
            target = entry_price + 200 if signal == 'LONG' else entry_price - 200
            new_trade = {
                'type': signal,
                'entry': entry_price,
                'sl': sl,
                'target': target,
                'status': 'OPEN',
                'entry_time': current_time_str,
                'exit_time': None,
                'exit_price': None,
                'result': None
            }
            trades.append(new_trade)
            save_trades(trades)
            mode_tag = "(PAPER)" if PAPER_TRADING else "(LIVE)"
            msg = f"NEW SETUP {mode_tag}!\nType: {signal}\nEntry: {entry_price:.2f}\nSL: {sl:.2f} (50 pts)\nTarget: {target:.2f} (200 pts)\nTime: {current_time_str}\n\nPaper Trading Mode - Do not trade with real money yet!"
            send_telegram_message(msg)
            print(f"Signal saved: {signal} @ {entry_price:.2f}")
        else:
            print("No valid signal at this time")
    save_trades(trades)
    print("\n" + "=" * 50)
    print("Bot Finished Successfully")
    print("=" * 50)

if __name__ == '__main__':
    main()
