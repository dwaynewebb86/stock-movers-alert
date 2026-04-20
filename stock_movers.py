import yfinance as yf
import pandas as pd
from datetime import datetime, time
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import pytz
import os
import requests

# Get configuration from environment variables
SMTP_SERVER = os.environ.get('SMTP_SERVER', 'smtp.gmail.com')
SMTP_PORT = int(os.environ.get('SMTP_PORT', 587))
SENDER_EMAIL = os.environ.get('SENDER_EMAIL')
SENDER_PASSWORD = os.environ.get('SENDER_PASSWORD')
RECIPIENT_EMAIL = os.environ.get('RECIPIENT_EMAIL')


def get_sp500_tickers():
    """Get current S&P 500 tickers from Wikipedia"""
    try:
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        tables = pd.read_html(url)
        df = tables[0]
        tickers = df['Symbol'].tolist()

        # yfinance uses '-' instead of '.' for tickers like BRK.B
        tickers = [ticker.replace('.', '-') for ticker in tickers]
        return tickers
    except Exception as e:
        print(f"Error getting S&P 500 tickers: {e}")
        return []


def get_most_active_tickers():
    """Get Yahoo Finance most active tickers"""
    try:
        url = "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"
        params = {
            "scrIds": "most_actives",
            "count": 100
        }

        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        quotes = data['finance']['result'][0]['quotes']
        tickers = [quote['symbol'] for quote in quotes if 'symbol' in quote]
        return tickers
    except Exception as e:
        print(f"Error getting most active tickers: {e}")
        return []


def get_dynamic_stocks():
    """Combine S&P 500 and most active stocks into a smaller, stable list"""
    sp500 = get_sp500_tickers()
    active = get_most_active_tickers()

    combined = list(set(sp500 + active))
    combined.sort()

    # Limit size for reliability
    limited = combined[:250]

    print(f"Loaded {len(sp500)} S&P 500 tickers")
    print(f"Loaded {len(active)} most active tickers")
    print(f"Using {len(limited)} tickers after limiting")

    return limited


def chunk_list(items, chunk_size=75):
    """Split a list into smaller chunks"""
    for i in range(0, len(items), chunk_size):
        yield items[i:i + chunk_size]


def get_stock_changes():
    """Get stock price changes from market open to 9:40 AM EST using chunked batch downloads"""
    est = pytz.timezone('US/Eastern')
    today = datetime.now(est).date()

    # Use the same time style as your original script
    market_open = datetime.combine(today, time(9, 30)).replace(tzinfo=est)
    nine_forty_am = datetime.combine(today, time(9, 40)).replace(tzinfo=est)

    stocks = get_dynamic_stocks()

    if not stocks:
        print("No stock tickers available.")
        return pd.DataFrame()

    stock_data = []

    print(f"Processing {len(stocks)} tickers in chunks...")

    for stock_chunk in chunk_list(stocks, 75):
        try:
            print(f"Downloading chunk of {len(stock_chunk)} tickers...")

            data = yf.download(
                tickers=stock_chunk,
                period="1d",
                interval="1m",
                group_by="ticker",
                auto_adjust=False,
                prepost=False,
                threads=True,
                progress=False
            )

            if data.empty:
                print("Chunk returned no data.")
                continue

            for ticker in stock_chunk:
                try:
                    if isinstance(data.columns, pd.MultiIndex):
                        if ticker not in data.columns.get_level_values(0):
                            continue
                        ticker_data = data[ticker].dropna()
                    else:
                        ticker_data = data.dropna()

                    if ticker_data.empty:
                        continue

                    if ticker_data.index.tz is None:
                        ticker_data.index = ticker_data.index.tz_localize('UTC').tz_convert(est)
                    else:
                        ticker_data.index = ticker_data.index.tz_convert(est)

                    morning_data = ticker_data[
                        (ticker_data.index >= market_open) & (ticker_data.index <= nine_forty_am)
                    ]

                    if len(morning_data) < 2:
                        continue

                    open_price = morning_data['Open'].iloc[0]
                    current_price = morning_data['Close'].iloc[-1]

                    if pd.isna(open_price) or pd.isna(current_price) or open_price == 0:
                        continue

                    pct_change = ((current_price - open_price) / open_price) * 100

                    stock_data.append({
                        'Ticker': ticker,
                        'Open': open_price,
                        '9:40 AM Price': current_price,
                        'Change': current_price - open_price,
                        'Change %': pct_change
                    })

                except Exception as e:
                    print(f"Error processing {ticker}: {e}")
                    continue

        except Exception as e:
            print(f"Error downloading chunk: {e}")
            continue

    df = pd.DataFrame(stock_data)
    return df


def send_email(stock_data):
    """Send email with top 25 gainers and bottom 25 losers"""
    top_25 = stock_data.sort_values('Change %', ascending=False).head(25)
    bottom_25 = stock_data.sort_values('Change %', ascending=True).head(25)

    subject = f"Stock Movers Report - {datetime.now().strftime('%Y-%m-%d')}"

    html_body = f"""
    <html>
    <head>
        <style>
            body {{
                font-family: Arial, sans-serif;
            }}
            table {{
                border-collapse: collapse;
                width: 100%;
                margin-bottom: 30px;
            }}
            th, td {{
                border: 1px solid #ddd;
                padding: 10px;
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
        <h2>Top 25 Gainers (Market Open to 9:40 AM EST)</h2>
        <p>Date: {datetime.now().strftime('%B %d, %Y')}</p>
        <table>
            <tr>
                <th>Ticker</th>
                <th>Open Price</th>
                <th>9:40 AM Price</th>
                <th>Change ($)</th>
                <th>Change (%)</th>
            </tr>
    """

    for _, row in top_25.iterrows():
        html_body += f"""
            <tr>
                <td><strong>{row['Ticker']}</strong></td>
                <td>${row['Open']:.2f}</td>
                <td>${row['9:40 AM Price']:.2f}</td>
                <td class="positive">${row['Change']:.2f}</td>
                <td class="positive">{row['Change %']:.2f}%</td>
            </tr>
        """

    html_body += """
        </table>

        <h2>Bottom 25 Losers (Market Open to 9:40 AM EST)</h2>
        <table>
            <tr>
                <th>Ticker</th>
                <th>Open Price</th>
                <th>9:40 AM Price</th>
                <th>Change ($)</th>
                <th>Change (%)</th>
            </tr>
    """

    for _, row in bottom_25.iterrows():
        html_body += f"""
            <tr>
                <td><strong>{row['Ticker']}</strong></td>
                <td>${row['Open']:.2f}</td>
                <td>${row['9:40 AM Price']:.2f}</td>
                <td class="negative">${row['Change']:.2f}</td>
                <td class="negative">{row['Change %']:.2f}%</td>
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


def send_no_data_email():
    """Send email when no stock data is available"""
    subject = f"Stock Movers Alert - No Data Available - {datetime.now().strftime('%Y-%m-%d')}"

    html_body = """
    <html>
    <body style="font-family: Arial, sans-serif;">
        <h2 style="color: #ff9800;">⚠️ No Stock Data Available</h2>
        <p>The stock movers script ran but could not retrieve data.</p>

        <p><strong>Possible reasons:</strong></p>
        <ul>
            <li>Market is closed (weekend or holiday)</li>
            <li>Script ran outside the 9:30-9:40 AM window</li>
            <li>Data provider issue</li>
            <li>GitHub Actions timing delay</li>
        </ul>

        <p style="color: #666; font-size: 12px;">
            If this happens on a weekday during market hours, check the GitHub Actions logs.
        </p>
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
        print("No-data notification email sent successfully!")
    except Exception as e:
        print(f"Error sending no-data email: {e}")


def main():
    print("Fetching stock data...")
    stock_data = get_stock_changes()

    if stock_data.empty:
        print("No stock data available. Market may be closed or data unavailable.")
        send_no_data_email()
        return

    top_25 = stock_data.sort_values('Change %', ascending=False).head(25)
    bottom_25 = stock_data.sort_values('Change %', ascending=True).head(25)

    print("\nTop 25 Gainers:")
    print(top_25.to_string(index=False))

    print("\nBottom 25 Losers:")
    print(bottom_25.to_string(index=False))

    print("\nSending email...")
    send_email(stock_data)


if __name__ == "__main__":
    main()
