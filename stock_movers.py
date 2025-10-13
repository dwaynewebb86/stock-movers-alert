import yfinance as yf
import pandas as pd
from datetime import datetime, time
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import pytz
import os

# Get configuration from environment variables
SMTP_SERVER = os.environ.get('SMTP_SERVER', 'smtp.gmail.com')
SMTP_PORT = int(os.environ.get('SMTP_PORT', 587))
SENDER_EMAIL = os.environ.get('SENDER_EMAIL')
SENDER_PASSWORD = os.environ.get('SENDER_PASSWORD')
RECIPIENT_EMAIL = os.environ.get('RECIPIENT_EMAIL')

STOCKS = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA', 'META', 'NVDA', 'JPM', 'V', 'WMT',
          'JNJ', 'PG', 'MA', 'HD', 'DIS', 'BAC', 'ADBE', 'NFLX', 'CRM', 'CSCO']

def get_stock_changes():
    """Get stock price changes from market open to 10:00 AM EST"""
    est = pytz.timezone('US/Eastern')
    today = datetime.now(est).date()
    
    market_open = datetime.combine(today, time(9, 30)).replace(tzinfo=est)
    ten_am = datetime.combine(today, time(10, 0)).replace(tzinfo=est)
    
    stock_data = []
    
    for ticker in STOCKS:
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period='1d', interval='1m')
            
            if hist.empty:
                continue
            
            hist.index = hist.index.tz_convert(est)
            morning_data = hist[(hist.index >= market_open) & (hist.index <= ten_am)]
            
            if len(morning_data) < 2:
                continue
            
            open_price = morning_data['Open'].iloc[0]
            ten_am_price = morning_data['Close'].iloc[-1]
            pct_change = ((ten_am_price - open_price) / open_price) * 100
            
            stock_data.append({
                'Ticker': ticker,
                'Open': open_price,
                '10AM Price': ten_am_price,
                'Change': ten_am_price - open_price,
                'Change %': pct_change
            })
            
        except Exception as e:
            print(f"Error processing {ticker}: {e}")
            continue
    
    df = pd.DataFrame(stock_data)
    if not df.empty:
        df['Abs_Change'] = df['Change %'].abs()
        df = df.sort_values('Abs_Change', ascending=False).head(5)
        df = df.drop('Abs_Change', axis=1)
    
    return df

def send_email(stock_data):
    """Send email with top 5 stock changes"""
    
    subject = f"Top 5 Stock Movers - {datetime.now().strftime('%Y-%m-%d')}"
    
    html_body = f"""
    <html>
    <head>
        <style>
            table {{
                border-collapse: collapse;
                width: 100%;
                font-family: Arial, sans-serif;
            }}
            th, td {{
                border: 1px solid #ddd;
                padding: 12px;
                text-align: left;
            }}
            th {{
                background-color: #4CAF50;
                color: white;
            }}
            tr:nth-child(even) {{
                background-color: #f2f2f2;
            }}
            .positive {{
                color: green;
                font-weight: bold;
            }}
            .negative {{
                color: red;
                font-weight: bold;
            }}
        </style>
    </head>
    <body>
        <h2>Top 5 Stock Movers (Market Open to 10:00 AM EST)</h2>
        <p>Date: {datetime.now().strftime('%B %d, %Y')}</p>
        <table>
            <tr>
                <th>Ticker</th>
                <th>Open Price</th>
                <th>10 AM Price</th>
                <th>Change ($)</th>
                <th>Change (%)</th>
            </tr>
    """
    
    for _, row in stock_data.iterrows():
        change_class = 'positive' if row['Change %'] > 0 else 'negative'
        html_body += f"""
            <tr>
                <td><strong>{row['Ticker']}</strong></td>
                <td>${row['Open']:.2f}</td>
                <td>${row['10AM Price']:.2f}</td>
                <td class="{change_class}">${row['Change']:.2f}</td>
                <td class="{change_class}">{row['Change %']:.2f}%</td>
            </tr>
        """
    
    html_body += """
        </table>
    </body>
    </html>
    """
    
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = SENDER_EMAIL
    msg['To'] = RECIPIENT_EMAIL
    
    html_part = MIMEText(html_body, 'html')
    msg.attach(html_part)
    
    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.send_message(msg)
        print("Email sent successfully!")
    except Exception as e:
        print(f"Error sending email: {e}")
        raise

def main():
    print("Fetching stock data...")
    stock_data = get_stock_changes()
    
    if stock_data.empty:
        print("No stock data available. Market may be closed or data unavailable.")
        return
    
    print("\nTop 5 Stock Movers:")
    print(stock_data.to_string(index=False))
    
    print("\nSending email...")
    send_email(stock_data)

if __name__ == "__main__":
    main()
