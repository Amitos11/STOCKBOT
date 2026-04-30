"""
Discovery Agent — Streamlit App (v4)
=====================================
ממשק וובי שמריץ סריקה של ~75 מניות, מדרג Top 10 לפי ציון משוקלל,
מציג גרף נר חודשי, סנטימנט נאיבי לחדשות, ומשגר דוחות למייל וטלגרם.

הפעלה:
    pip install streamlit yfinance pandas plotly
    streamlit run app.py
"""

import csv
import html as html_lib
import json
import math
import os
import smtplib
import urllib.parse
import urllib.request
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

# ============================================================
# CONFIG
# ============================================================

GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "4328fe6014ea4ec9b2e638f1c6489c1c")
# OpenAI — לא הטמעה ברירת מחדל. או env var, או הקלדה ב-sidebar.
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

TICKERS = [
    "NVDA", "AAPL", "MSFT", "GOOG", "META", "AMZN", "TSLA", "AVGO", "ORCL", "NFLX",
    "AMD", "MU", "QCOM", "INTC", "SMCI", "AMAT", "LRCX", "MRVL", "ASML",
    "PLTR", "CRWD", "NET", "DDOG", "SNOW", "MDB", "ZS", "OKTA", "S", "ESTC",
    "JNJ", "UNH", "MRK", "ABBV", "LLY", "ISRG", "REGN", "VRTX",
    "COST", "WMT", "HD", "LULU", "ULTA", "ELF", "CMG",
    "JPM", "V", "MA", "BAC", "GS", "HOOD", "SOFI", "COIN",
    "LMT", "RTX", "GE", "CAT", "XOM", "CVX",
    "TEVA", "CHKP", "NICE", "MNDY", "WIX", "MBLY", "GLBE", "ESLT",
    "CYBR", "INMD", "NVMI", "AUDC", "GILT",
    "POLI.TA", "LUMI.TA", "DSCT.TA", "MZTF.TA", "FIBI.TA", "ICL.TA", "AZRG.TA",
]

DEFAULT_WEIGHT_GROWTH = 40
DEFAULT_WEIGHT_PROFITABILITY = 30
DEFAULT_WEIGHT_VALUATION = 30

OUTPUT_DIR = Path(__file__).resolve().parent
HISTORY_CSV = OUTPUT_DIR / "history.csv"


# ============================================================
# SENTIMENT (keyword-based, NOT real AI/NLP)
# ============================================================

POSITIVE_KEYWORDS = [
    "growth", "beat", "beats", "up ", "rise", "rises", "rising", "surge", "surges",
    "gain", "gains", "raised", "raises", "jumps", "soars", "soared", "rally",
    "outperform", "upgrade", "record", "tops", "smash", "rebound", "boom",
]
NEGATIVE_KEYWORDS = [
    "drop", "drops", "miss", "misses", "fall", "falls", "fell", "decline",
    "declines", "loss", "losses", "down ", "plunge", "plunges", "slumps",
    "sinks", "underperform", "downgrade", "cut", "cuts", "warning", "weak",
    "concern", "concerns", "crash", "tumble", "tumbles",
]


def label_sentiment(title):
    """סיווג נאיבי לפי מילות מפתח. לא AI — רק התאמת מחרוזות."""
    if not title:
        return ("neutral", "⚪")
    text = " " + title.lower() + " "
    pos = sum(1 for w in POSITIVE_KEYWORDS if w in text)
    neg = sum(1 for w in NEGATIVE_KEYWORDS if w in text)
    if pos > neg:
        return ("positive", "🟢")
    if neg > pos:
        return ("negative", "🔴")
    return ("neutral", "⚪")


# ============================================================
# UTILITIES
# ============================================================

def safe_float(v):
    if v is None:
        return None
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def fmt_pct(val, decimals=1):
    f = safe_float(val)
    if f is None:
        return "N/A"
    return f"{f * 100:+.{decimals}f}%"


def fmt_day_pct(val):
    """אחוז שינוי יומי עם נקודה צבעונית — ירוקה לעלייה, אדומה לירידה.
    val כבר באחוזים (1.23 = 1.23%), בלי להכפיל ב-100."""
    f = safe_float(val)
    if f is None:
        return "—"
    emoji = "🟢" if f >= 0 else "🔴"
    sign = "+" if f >= 0 else ""
    return f"{emoji} {sign}{f:.2f}%"


def fmt_day_pct_color(val):
    """אותו דבר אבל עם תגי :green[]/:red[] של Streamlit לטקסט צבעוני
    (משמש בכותרות אקורדיון ומדדים שתומכים ב-markdown צבעוני).
    val כבר באחוזים."""
    f = safe_float(val)
    if f is None:
        return ""
    color = "green" if f >= 0 else "red"
    arrow = "▲" if f >= 0 else "▼"
    sign = "+" if f >= 0 else ""
    return f":{color}[{arrow} {sign}{f:.2f}%]"


def fmt_num(val, decimals=2):
    f = safe_float(val)
    if f is None:
        return "N/A"
    return f"{f:.{decimals}f}"


def fmt_market_cap(mkt_cap, symbol):
    f = safe_float(mkt_cap)
    if f is None:
        return "N/A"
    if symbol.endswith(".TA"):
        nis_b = f / 1e9
        usd_b = f / 3.7 / 1e9
        return f"₪{nis_b:.1f}B (~${usd_b:.1f}B)"
    if f >= 1e12:
        return f"${f / 1e12:.2f}T"
    if f >= 1e9:
        return f"${f / 1e9:.1f}B"
    if f >= 1e6:
        return f"${f / 1e6:.0f}M"
    return f"${f:,.0f}"


def fmt_price(price, symbol, currency=""):
    f = safe_float(price)
    if f is None:
        return "N/A"
    if symbol.endswith(".TA") or currency == "ILA":
        return f"₪{f / 100:.2f}"
    if currency == "ILS":
        return f"₪{f:.2f}"
    return f"${f:.2f}"


def fmt_big_money(value, currency="USD"):
    """פורמט למספרים גדולים — $1.5B, ₪50M וכו'."""
    f = safe_float(value)
    if f is None:
        return "N/A"
    if currency in ("ILS", "ILA"):
        sym = "₪"
    elif currency == "EUR":
        sym = "€"
    elif currency == "GBP":
        sym = "£"
    else:
        sym = "$"
    abs_f = abs(f)
    sign = "-" if f < 0 else ""
    if abs_f >= 1e12:
        return f"{sign}{sym}{abs_f / 1e12:.2f}T"
    if abs_f >= 1e9:
        return f"{sign}{sym}{abs_f / 1e9:.2f}B"
    if abs_f >= 1e6:
        return f"{sign}{sym}{abs_f / 1e6:.1f}M"
    if abs_f >= 1e3:
        return f"{sign}{sym}{abs_f / 1e3:.1f}K"
    return f"{sign}{sym}{abs_f:,.0f}"


REC_LABEL_MAP = {
    "strong_buy": "Strong Buy",
    "buy": "Buy",
    "hold": "Hold",
    "underperform": "Underperform",
    "sell": "Sell",
    "strong_sell": "Strong Sell",
}


def fmt_recommendation(rec_key):
    if not rec_key:
        return "—"
    return REC_LABEL_MAP.get(rec_key.lower(), rec_key.title())


def get_logo_url(row):
    """מחלץ דומיין מהשדה website ובונה URL של Clearbit. None אם לא קיים."""
    website = (row.get("website") or "").strip()
    if not website:
        return None
    domain = website.replace("https://", "").replace("http://", "").replace("www.", "")
    domain = domain.split("/")[0].split("?")[0].strip().lower()
    if not domain or "." not in domain:
        return None
    return f"https://logo.clearbit.com/{domain}"


def render_stock_card(row, rank):
    """כרטיס מניה כ-HTML — לוגו, ציון, מחיר, פיל יומי, מדדים מהירים."""
    score = row.get("score", 0)
    score_color = "#22c55e" if score >= 60 else ("#eab308" if score >= 40 else "#ef4444")

    day_change = row.get("day_change") or 0
    is_up = day_change >= 0
    pill_color = "#22c55e" if is_up else "#ef4444"
    pill_bg = "rgba(34,197,94,0.12)" if is_up else "rgba(239,68,68,0.12)"
    pill_arrow = "▲" if is_up else "▼"

    logo_url = get_logo_url(row)
    initial = (row.get("symbol", "?") or "?")[0]
    if logo_url:
        logo_html = (
            f'<div class="stock-logo-wrap">'
            f'<div class="stock-logo-fallback" style="background:linear-gradient(135deg,{score_color},#334155)">{initial}</div>'
            f'<img src="{logo_url}" class="stock-logo" onerror="this.style.display=\'none\'" />'
            f'</div>'
        )
    else:
        logo_html = (
            f'<div class="stock-logo-wrap">'
            f'<div class="stock-logo-fallback" style="background:linear-gradient(135deg,{score_color},#334155)">{initial}</div>'
            f'</div>'
        )

    name = (row.get("name") or "")[:32]
    sector = (row.get("sector") or "—")[:24]
    price_str = fmt_price(row["price"], row["symbol"], row.get("currency", ""))
    pe_str = fmt_num(row.get("pe_ratio"), 1)
    mc_str = row.get("market_cap_display") or "—"
    eps_yoy = fmt_pct(row.get("earnings_growth"))

    return f"""
    <div class="stock-card">
        <div class="stock-card-rank">#{rank}</div>
        <div class="stock-card-head">
            {logo_html}
            <div class="stock-card-meta">
                <div class="stock-card-symbol">{row['symbol']}</div>
                <div class="stock-card-name">{name}</div>
                <div class="stock-card-sector">{sector}</div>
            </div>
            <div class="stock-card-score" style="color:{score_color}">
                <div class="score-num">{score:.0f}</div>
                <div class="score-label">/ 100</div>
            </div>
        </div>
        <div class="stock-card-price-row">
            <div class="stock-card-price">{price_str}</div>
            <div class="day-pill" style="color:{pill_color}; background:{pill_bg}">
                {pill_arrow} {fmt_pct(day_change)}
            </div>
        </div>
        <div class="stock-card-stats">
            <div class="stat"><div class="stat-label">P/E</div><div class="stat-value">{pe_str}</div></div>
            <div class="stat"><div class="stat-label">EPS YoY</div><div class="stat-value">{eps_yoy}</div></div>
            <div class="stat"><div class="stat-label">Mkt Cap</div><div class="stat-value">{mc_str}</div></div>
        </div>
    </div>
    """


# ============================================================
# DATA FETCHING
# ============================================================

def fetch_deep(symbol):
    row = {
        "scan_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "symbol": symbol,
    }
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info or {}
    except Exception as e:
        row["error"] = f"fetch failed: {str(e)[:60]}"
        return row

    price = safe_float(info.get("currentPrice")) or safe_float(info.get("regularMarketPrice"))
    if not price:
        row["error"] = "no price data"
        return row

    row["name"] = info.get("shortName") or info.get("longName") or ""
    row["price"] = price
    row["currency"] = info.get("currency", "")
    row["sector"] = info.get("sector", "")
    row["industry"] = info.get("industry", "")
    row["website"] = (info.get("website") or "").strip()
    row["market_cap"] = safe_float(info.get("marketCap"))
    row["market_cap_display"] = fmt_market_cap(row["market_cap"], symbol)
    row["pe_ratio"] = safe_float(info.get("trailingPE"))
    row["forward_pe"] = safe_float(info.get("forwardPE"))
    row["peg_ratio"] = safe_float(info.get("pegRatio"))
    row["earnings_growth"] = safe_float(info.get("earningsQuarterlyGrowth"))
    row["revenue_growth"] = safe_float(info.get("revenueGrowth"))
    row["operating_margin"] = safe_float(info.get("operatingMargins"))
    row["profit_margin"] = safe_float(info.get("profitMargins"))
    row["roe"] = safe_float(info.get("returnOnEquity"))
    row["debt_to_equity"] = safe_float(info.get("debtToEquity"))
    row["current_ratio"] = safe_float(info.get("currentRatio"))

    # מספרים פיננסיים TTM (12 חודשים אחרונים)
    row["financial_currency"] = info.get("financialCurrency") or info.get("currency") or "USD"
    row["total_revenue"] = safe_float(info.get("totalRevenue"))
    row["gross_profits"] = safe_float(info.get("grossProfits"))
    row["ebitda"] = safe_float(info.get("ebitda"))
    row["net_income_ttm"] = safe_float(info.get("netIncomeToCommon"))
    _om = safe_float(info.get("operatingMargins"))
    _tr = safe_float(info.get("totalRevenue"))
    row["op_income_ttm"] = (_om * _tr) if (_om is not None and _tr is not None) else None

    # תחזיות אנליסטים (12 חודשים) — דעות חיצוניות, לא תחזית מובטחת
    row["target_mean_price"] = safe_float(info.get("targetMeanPrice"))
    row["target_high_price"] = safe_float(info.get("targetHighPrice"))
    row["target_low_price"] = safe_float(info.get("targetLowPrice"))
    row["num_analysts"] = info.get("numberOfAnalystOpinions")
    row["recommendation_key"] = info.get("recommendationKey", "")
    row["recommendation_mean"] = safe_float(info.get("recommendationMean"))

    # אחוז שינוי יומי — מחושב מ-((מחיר נוכחי - סגירת אתמול) / סגירת אתמול) × 100
    # כדי להבטיח עקביות. כל הערכים כאן כבר באחוזים (1.23 = 1.23%).
    prev_close = safe_float(info.get("regularMarketPreviousClose")) or safe_float(info.get("previousClose"))
    if prev_close and prev_close > 0 and price:
        row["day_change"] = (price - prev_close) / prev_close * 100
    else:
        # נופלים חזרה לערך של yfinance — כבר באחוזים, לא צריך הכפלה
        row["day_change"] = safe_float(info.get("regularMarketChangePercent"))
    row["fifty_two_week_high"] = safe_float(info.get("fiftyTwoWeekHigh"))
    row["fifty_two_week_low"] = safe_float(info.get("fiftyTwoWeekLow"))

    row["next_earnings"] = ""
    try:
        cal = ticker.calendar
        if isinstance(cal, dict):
            ed = cal.get("Earnings Date")
            if ed:
                if isinstance(ed, list) and ed:
                    ed = ed[0]
                row["next_earnings"] = ed.strftime("%Y-%m-%d") if hasattr(ed, "strftime") else str(ed)[:10]
    except Exception:
        pass

    return row


def fetch_news_yfinance(symbol, n=2):
    try:
        ticker = yf.Ticker(symbol)
        news = ticker.news or []
        result = []
        for item in news[:n]:
            content = item.get("content", item)
            title = content.get("title") or item.get("title") or ""
            link = ""
            cu = content.get("canonicalUrl") or {}
            if isinstance(cu, dict):
                link = cu.get("url", "")
            link = link or content.get("link") or item.get("link") or ""
            if title:
                result.append({
                    "title": title.strip(),
                    "link": link,
                    "source": "Yahoo",
                    "published": "",
                })
        return result
    except Exception:
        return []


def fetch_newsapi(query, n=3, language="en"):
    if not NEWSAPI_KEY:
        return []
    try:
        params = {
            "q": query,
            "sortBy": "publishedAt",
            "pageSize": n,
            "language": language,
            "apiKey": NEWSAPI_KEY,
        }
        url = "https://newsapi.org/v2/everything?" + urllib.parse.urlencode(params)
        with urllib.request.urlopen(url, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("status") != "ok":
            return []
        return [
            {
                "title": (a.get("title") or "").strip(),
                "link": a.get("url", ""),
                "source": (a.get("source") or {}).get("name", ""),
                "published": (a.get("publishedAt") or "")[:10],
            }
            for a in (data.get("articles") or [])[:n]
            if a.get("title")
        ]
    except Exception:
        return []


def fetch_news_for_stock(symbol, name, n=2):
    if NEWSAPI_KEY:
        clean_name = (name or "").replace(",", "").replace(".", "").strip()
        query = f'"{clean_name}"' if clean_name else symbol.replace(".TA", "")
        articles = fetch_newsapi(query, n=n)
        if articles:
            return articles
    return fetch_news_yfinance(symbol, n=n)


def fetch_macro_headlines():
    if not NEWSAPI_KEY:
        return {"monetary": [], "geopolitical": []}
    monetary = fetch_newsapi(
        '"federal reserve" OR "interest rates" OR "central bank" OR "inflation"',
        n=3,
    )
    geopolitical = fetch_newsapi(
        '"geopolitics" OR "Middle East" OR "Iran" OR "tariffs" OR "trade war"',
        n=3,
    )
    return {"monetary": monetary, "geopolitical": geopolitical}


def _fetch_quarterly_financials(symbol):
    """מביא את הרבעון האחרון: הכנסה, רווח תפעולי, רווח נקי. דורש קריאה
    נוספת ל-yfinance, לכן משמש רק להעשרת Top 10 וניתוח חופשי."""
    try:
        ticker = yf.Ticker(symbol)
        qis = ticker.quarterly_income_stmt
        if qis is None or qis.empty:
            return {}
        latest_col = qis.columns[0]
        result = {
            "q_date": (
                latest_col.strftime("%Y-%m-%d")
                if hasattr(latest_col, "strftime")
                else str(latest_col)[:10]
            ),
        }

        def _get(row_names):
            for name in row_names:
                if name in qis.index:
                    return safe_float(qis.loc[name, latest_col])
            return None

        result["q_revenue"] = _get(["Total Revenue", "TotalRevenue", "Revenue"])
        result["q_operating_income"] = _get(
            ["Operating Income", "OperatingIncome", "Total Operating Income"]
        )
        result["q_net_income"] = _get(
            ["Net Income", "Net Income Common Stockholders", "NetIncome"]
        )
        return result
    except Exception:
        return {}


def _fetch_price_history_summary(symbol):
    """מסכם 30 ימי מחירי סגירה לסטטיסטיקות שעוזרות ל-AI לתאר מגמה.
    החזרה: מחרוזת תיאור באנגלית להחדרה ל-prompt."""
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="1mo")
        if hist.empty:
            return ""
        closes = [float(c) for c in hist["Close"].tolist() if c == c]  # filter NaN
        if len(closes) < 5:
            return ""
        first = closes[0]
        last = closes[-1]
        high = max(closes)
        low = min(closes)
        change_pct = (last - first) / first * 100 if first else 0
        mid = len(closes) // 2
        older_avg = sum(closes[:mid]) / max(1, mid)
        recent_avg = sum(closes[mid:]) / max(1, len(closes) - mid)
        last_5 = closes[-5:]
        momentum = "upward" if recent_avg > older_avg else "downward"
        return (
            f"30-day price history ({len(closes)} trading days): "
            f"range {low:.2f}-{high:.2f}, total change {change_pct:+.1f}%. "
            f"First-half avg: {older_avg:.2f}, second-half avg: {recent_avg:.2f} "
            f"({momentum} momentum). "
            f"Last 5 closes: {', '.join(f'{c:.2f}' for c in last_5)}. "
            f"Current price as % of high: {(last/high*100):.0f}%, "
            f"as % of low: {(last/low*100):.0f}%."
        )
    except Exception:
        return ""


def get_ai_insights(stock_data, news_headlines, api_key):
    """שולח ל-GPT-4o-mini נתוני מניה + חדשות + היסטוריית מחיר + Forward P/E.
    מחזיר tuple: (insight_text, error_or_None). הפלט בנוי בשתי סקציות."""
    if not api_key:
        return None, "אין מפתח OpenAI"

    try:
        from openai import OpenAI
    except ImportError:
        return None, "התקן: pip install openai"

    try:
        client = OpenAI(api_key=api_key)

        symbol = stock_data.get("symbol", "?")
        name = stock_data.get("name", "")
        sector = stock_data.get("sector", "")
        pe = stock_data.get("pe_ratio")
        forward_pe = stock_data.get("forward_pe")
        eps_g = stock_data.get("earnings_growth")
        rev_g = stock_data.get("revenue_growth")
        op_m = stock_data.get("operating_margin")
        roe = stock_data.get("roe")
        de = stock_data.get("debt_to_equity")
        history_summary = stock_data.get("price_history_summary", "")

        metrics = []
        if pe is not None:
            metrics.append(f"Trailing P/E: {pe:.1f}")
        if forward_pe is not None:
            metrics.append(f"Forward P/E: {forward_pe:.1f}")
        if eps_g is not None:
            metrics.append(f"EPS YoY: {eps_g * 100:+.0f}%")
        if rev_g is not None:
            metrics.append(f"Revenue YoY: {rev_g * 100:+.0f}%")
        if op_m is not None:
            metrics.append(f"Op Margin: {op_m * 100:.0f}%")
        if roe is not None:
            metrics.append(f"ROE: {roe * 100:.0f}%")
        if de is not None:
            metrics.append(f"D/E: {de:.0f}")

        news_text = ""
        if news_headlines:
            news_text = "\nRecent headlines:\n" + "\n".join(
                f"- {(n.get('title') or '')[:120]}" for n in news_headlines[:3]
            )

        history_text = f"\n{history_summary}" if history_summary else ""

        user_msg = (
            f"Stock: {symbol} ({name}) — Sector: {sector}\n"
            f"Metrics: {', '.join(metrics) if metrics else 'limited data'}"
            f"{history_text}"
            f"{news_text}\n\n"
            "Produce the analysis with the three-section structure described in the system prompt."
        )

        system_msg = (
            "You are a financial data analyst writing concise stock analyses in Hebrew.\n"
            "Output MUST use this EXACT three-section structure with the emoji headers:\n\n"
            "📈 ניתוח טכני / מומנטום:\n"
            "<2 sentences describing the 30-day price trend (upward/downward/sideways), "
            "approximate range, where current price sits within that range, and momentum "
            "direction. Use observational language only — describe what the data SHOWS.>\n\n"
            "📊 הערכת שווי קדימה:\n"
            "<2 sentences comparing Trailing P/E to Forward P/E. If Forward < Trailing, "
            "explain analysts expect earnings growth (so the company looks 'cheaper' on a "
            "forward basis). If Forward > Trailing, the opposite. If similar, note stability. "
            "Connect to news context if relevant.>\n\n"
            "🔥 תחומים חמים / מנועי צמיחה:\n"
            "<2 sentences identifying sector tailwinds or industry trends the company is "
            "currently positioned within (e.g., 'AI infrastructure demand', 'energy "
            "transition', 'aging population', 'cloud migration'). Describe POSITIONING, "
            "not predictions. If no obvious trends apply, write 'אין מנועי צמיחה "
            "סקטוריאליים בולטים מעבר לעסק הליבה'.>\n\n"
            "STRICT RULES — VIOLATIONS WILL BREAK THE OUTPUT:\n"
            "- NEVER use 'buy', 'sell', 'should', 'recommend', 'target price'\n"
            "- NEVER call price levels 'entry zones', 'exit zones', 'support to buy at', "
            "'resistance to sell at'\n"
            "- NEVER predict future prices or specific revenue numbers\n"
            "- Use observational/descriptive language only ('the data shows', "
            "'the trend has been', 'the company is positioned in', 'metrics suggest')\n"
            "- Maximum 2 sentences per section\n"
            "- Always Hebrew\n"
            "- Always include all three emoji-prefixed section headers exactly as shown"
        )

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=500,
            temperature=0.3,
        )

        return response.choices[0].message.content.strip(), None
    except Exception as e:
        return None, f"שגיאה: {str(e)[:120]}"


def fetch_management(symbol):
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info or {}
        officers = info.get("companyOfficers") or []
    except Exception:
        return {"ceo": None, "cfo": None}

    ceo = None
    cfo = None
    for o in officers:
        if not isinstance(o, dict):
            continue
        title = (o.get("title") or "").lower()
        rec = {
            "name": o.get("name") or "",
            "title": o.get("title") or "",
            "age": o.get("age"),
            "year_born": o.get("yearBorn"),
        }
        if not ceo and ("ceo" in title or "chief executive" in title):
            ceo = rec
        elif not cfo and ("cfo" in title or "chief financial" in title):
            cfo = rec
    return {"ceo": ceo, "cfo": cfo}


# ============================================================
# SCORING (accepts weight params)
# ============================================================

def score_growth(row, weight=DEFAULT_WEIGHT_GROWTH):
    eps = row.get("earnings_growth")
    rev = row.get("revenue_growth")
    eps_norm = max(0, min(1, eps / 0.5)) if eps is not None else None
    rev_norm = max(0, min(1, rev / 0.3)) if rev is not None else None
    available = [s for s in (eps_norm, rev_norm) if s is not None]
    if not available:
        return 0
    return (sum(available) / len(available)) * weight


def score_profitability(row, weight=DEFAULT_WEIGHT_PROFITABILITY):
    om = row.get("operating_margin")
    roe = row.get("roe")
    om_norm = max(0, min(1, om / 0.25)) if om is not None else None
    roe_norm = max(0, min(1, roe / 0.25)) if roe is not None else None
    available = [s for s in (om_norm, roe_norm) if s is not None]
    if not available:
        return 0
    return (sum(available) / len(available)) * weight


def score_valuation(row, weight=DEFAULT_WEIGHT_VALUATION):
    pe = row.get("pe_ratio")
    if pe is None or pe <= 0:
        return 0
    if pe <= 10:
        norm = 1.0
    elif pe <= 20:
        norm = 1.0 - (pe - 10) * 0.05
    elif pe <= 40:
        norm = 0.5 - (pe - 20) * 0.0225
    else:
        norm = max(0, 0.05 - (pe - 40) * 0.001)
    return norm * weight


def has_min_data(row):
    if row.get("error"):
        return False
    if row.get("pe_ratio") is None:
        return False
    if row.get("earnings_growth") is None and row.get("revenue_growth") is None:
        return False
    return True


# ============================================================
# INSIGHTS
# ============================================================

def generate_insight(row):
    parts = []
    eps = row.get("earnings_growth")
    rev = row.get("revenue_growth")
    om = row.get("operating_margin")
    pe = row.get("pe_ratio")
    de = row.get("debt_to_equity")

    if eps is not None and eps > 0.5:
        parts.append(f"רווחים +{eps * 100:.0f}% YoY")
    elif eps is not None and eps > 0.2:
        parts.append(f"צמיחת רווחים יציבה ({eps * 100:.0f}%)")

    if rev is not None and rev > 0.3:
        parts.append(f"הכנסות +{rev * 100:.0f}% YoY")
    elif rev is not None and rev > 0.15:
        parts.append(f"הכנסות צומחות ({rev * 100:.0f}%)")

    if om is not None and om > 0.30:
        parts.append(f"מרווח תפעולי גבוה ({om * 100:.0f}%) — כוח תמחור")
    elif om is not None and om > 0.20:
        parts.append(f"רווחיות תפעולית סולידית ({om * 100:.0f}%)")

    if pe is not None and 0 < pe < 12:
        parts.append(f"P/E נמוך ({pe:.1f}) — תמחור צנוע")
    elif pe is not None and 0 < pe < 20:
        parts.append(f"P/E סביר ({pe:.1f})")

    if de is not None and de < 50:
        parts.append("מאזן נקי מחובות")

    if not parts:
        parts.append("מאפיינים מאוזנים")

    return " • ".join(parts[:3])


# ============================================================
# OUTPUT BUILDERS (Email & Telegram)
# ============================================================

def _fmt_management_line(mgmt):
    if not mgmt:
        return ""
    parts = []
    if mgmt.get("ceo") and mgmt["ceo"].get("name"):
        ceo = mgmt["ceo"]
        age_str = f" ({ceo['age']})" if ceo.get("age") else ""
        parts.append(f"CEO: {ceo['name']}{age_str}")
    if mgmt.get("cfo") and mgmt["cfo"].get("name"):
        cfo = mgmt["cfo"]
        age_str = f" ({cfo['age']})" if cfo.get("age") else ""
        parts.append(f"CFO: {cfo['name']}{age_str}")
    return " • ".join(parts) if parts else ""


def build_telegram_message(top10):
    today = datetime.now().strftime("%d/%m/%Y")
    lines = [f"🎯 Top 10 Discovery — {today}"]
    for i, row in enumerate(top10, 1):
        score = row.get("score", 0)
        sector = (row.get("sector") or "")[:18]
        next_e = row.get("next_earnings", "")
        next_e_str = f"  📅 {next_e}" if next_e else ""
        price_str = fmt_price(row["price"], row["symbol"], row.get("currency", ""))
        pe_str = fmt_num(row.get("pe_ratio"), 1)
        mc_str = row.get("market_cap_display", "")
        mgmt_str = _fmt_management_line(row.get("management"))
        lines.append("")
        lines.append(f"{i}. {row['symbol']} ({sector}) — {score:.0f}/100{next_e_str}")
        lines.append(f"   {row['name'][:38]}")
        lines.append(f"   {row.get('insight', '')}")
        lines.append(f"   {price_str} | P/E {pe_str} | {mc_str}")
        if mgmt_str:
            lines.append(f"   👥 {mgmt_str}")
    return "\n".join(lines)


def build_macro_telegram_message(macro):
    if not macro or (not macro.get("monetary") and not macro.get("geopolitical")):
        return ""
    lines = ["🌍 כותרות מאקרו עולמיות"]
    if macro.get("monetary"):
        lines.append("\n💵 מוניטרי / כלכלה:")
        for a in macro["monetary"]:
            _, emoji = label_sentiment(a["title"])
            src = f" ({a['source']})" if a.get("source") else ""
            date = f" {a['published']}" if a.get("published") else ""
            lines.append(f"  {emoji} {a['title'][:120]}{src}{date}")
    if macro.get("geopolitical"):
        lines.append("\n🌐 גיאופוליטי:")
        for a in macro["geopolitical"]:
            _, emoji = label_sentiment(a["title"])
            src = f" ({a['source']})" if a.get("source") else ""
            date = f" {a['published']}" if a.get("published") else ""
            lines.append(f"  {emoji} {a['title'][:120]}{src}{date}")
    return "\n".join(lines)


def _build_management_html(mgmt):
    if not mgmt or (not mgmt.get("ceo") and not mgmt.get("cfo")):
        return ""
    parts = []
    for role_label, person in (("CEO", mgmt.get("ceo")), ("CFO", mgmt.get("cfo"))):
        if not person or not person.get("name"):
            continue
        name = html_lib.escape(person["name"])
        age = f", בן {person['age']}" if person.get("age") else ""
        parts.append(f"<b>{role_label}:</b> {name}{age}")
    if not parts:
        return ""
    return f'<div style="margin-top:6px; color:#555; font-size:11px">👥 {" • ".join(parts)}</div>'


def _build_macro_html(macro):
    if not macro or (not macro.get("monetary") and not macro.get("geopolitical")):
        return ""

    def headlines_block(label, articles):
        if not articles:
            return ""
        items = ""
        for a in articles:
            _, emoji = label_sentiment(a["title"])
            title = html_lib.escape(a["title"][:140])
            link = html_lib.escape(a.get("link", ""))
            src = html_lib.escape(a.get("source", ""))
            date = html_lib.escape(a.get("published", ""))
            meta = f' <span style="color:#999; font-size:11px">— {src} {date}</span>' if src else ""
            if link:
                items += f'<li>{emoji} <a href="{link}" style="color:#3b82f6; text-decoration:none">{title}</a>{meta}</li>'
            else:
                items += f"<li>{emoji} {title}{meta}</li>"
        return f'<h4 style="margin:10px 0 4px 0">{label}</h4><ul style="margin:0; padding-right:20px">{items}</ul>'

    return f"""
    <h2 style="color:#3b82f6; margin-top:32px">🌍 כותרות מאקרו עולמיות</h2>
    <div style="font-size:13px">
      {headlines_block("💵 מוניטרי / כלכלה", macro.get("monetary", []))}
      {headlines_block("🌐 גיאופוליטי", macro.get("geopolitical", []))}
    </div>
    """


def build_html_email(top10, all_valid, macro=None):
    today = datetime.now().strftime("%d/%m/%Y %H:%M")

    rows_html = ""
    for i, row in enumerate(top10, 1):
        score = row.get("score", 0)
        bar_w = int(score)
        color = "#22c55e" if score >= 60 else ("#eab308" if score >= 40 else "#ef4444")

        news_items = ""
        for n in row.get("news", []):
            _, emoji = label_sentiment(n["title"])
            title = html_lib.escape(n["title"][:90])
            link = html_lib.escape(n["link"])
            if link:
                news_items += f'<li>{emoji} <a href="{link}" style="color:#3b82f6; text-decoration:none">{title}</a></li>'
            else:
                news_items += f"<li>{emoji} {title}</li>"
        if not news_items:
            news_items = '<li style="color:#999">אין חדשות זמינות</li>'

        next_e = row.get("next_earnings", "")
        next_e_html = f"📅 דוח הבא: {next_e}" if next_e else ""
        price_str = fmt_price(row["price"], row["symbol"], row.get("currency", ""))

        rows_html += f"""
        <tr style="border-bottom: 1px solid #e5e7eb">
          <td style="padding:14px 8px; vertical-align:top; width:40px">
            <strong style="font-size:20px; color:#888">#{i}</strong>
          </td>
          <td style="padding:14px 8px; vertical-align:top; width:200px">
            <div style="font-size:18px; font-weight:bold">{html_lib.escape(row['symbol'])}</div>
            <div style="color:#444; font-size:12px">{html_lib.escape(row.get('name', '')[:50])}</div>
            <div style="color:#888; font-size:11px; margin-top:4px">{html_lib.escape(row.get('sector', ''))}</div>
            <div style="color:#888; font-size:11px">{next_e_html}</div>
          </td>
          <td style="padding:14px 8px; vertical-align:top; text-align:center; width:90px">
            <div style="font-size:26px; font-weight:bold; color:{color}">{score:.0f}</div>
            <div style="color:#888; font-size:10px">/ 100</div>
            <div style="background:#e5e7eb; height:5px; border-radius:3px; margin-top:4px">
              <div style="background:{color}; height:5px; width:{bar_w}%; border-radius:3px"></div>
            </div>
          </td>
          <td style="padding:14px 8px; vertical-align:top; font-size:13px">
            <div style="margin-bottom:8px"><b>תובנה:</b> {html_lib.escape(row.get('insight', ''))}</div>
            <div style="color:#222">
              💰 {price_str} • P/E {fmt_num(row.get('pe_ratio'), 1)} • {html_lib.escape(row.get('market_cap_display', ''))}
            </div>
            <div style="margin-top:4px; color:#666; font-size:12px">
              EPS YoY: {fmt_pct(row.get('earnings_growth'))} • Rev YoY: {fmt_pct(row.get('revenue_growth'))} •
              Op Margin: {fmt_pct(row.get('operating_margin'))} • ROE: {fmt_pct(row.get('roe'))}
            </div>
            {_build_management_html(row.get('management'))}
            <ul style="margin:8px 0 0 0; padding-right:20px; font-size:11px; color:#444">{news_items}</ul>
          </td>
        </tr>
        """

    avg_score = sum(r.get("score", 0) for r in all_valid) / max(1, len(all_valid))

    return f"""
    <html dir="rtl">
    <body style="font-family: -apple-system, 'Segoe UI', Arial, sans-serif; max-width:920px; margin:24px auto; color:#222; background:#f9fafb">
      <div style="background:white; padding:24px; border-radius:8px; box-shadow:0 1px 3px rgba(0,0,0,0.05)">
        <h1 style="border-bottom: 3px solid #3b82f6; padding-bottom:8px; margin-top:0">📊 דוח גילוי מניות — {today}</h1>
        <p style="color:#444; font-size:14px">
          סרקנו <b>{len(all_valid)}</b> מניות מתוך {len(TICKERS)} ברשימה.
          ציון ממוצע: <b>{avg_score:.1f}</b>.
        </p>
        <h2 style="color:#3b82f6; margin-top:24px">🎯 Top 10</h2>
        <table style="width:100%; border-collapse:collapse; font-size:13px">
          {rows_html}
        </table>
        {_build_macro_html(macro)}
        <p style="color:#999; font-size:11px; margin-top:24px; border-top:1px solid #e5e7eb; padding-top:12px">
          ⚠️ ניתוח אוטומטי המבוסס על נתוני yfinance ו-NewsAPI. סנטימנט החדשות מבוסס על מילות מפתח (לא AI אמיתי).
          אינו מהווה ייעוץ השקעות.
        </p>
      </div>
    </body>
    </html>
    """


# ============================================================
# SENDING
# ============================================================

def send_email(subject, html_body):
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        return False, "פרטי מייל חסרים"
    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = GMAIL_USER
        msg["To"] = GMAIL_USER
        msg["Subject"] = subject
        msg.attach(MIMEText(html_body, "html", "utf-8"))
        server = smtplib.SMTP_SSL("smtp.gmail.com", 465)
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.send_message(msg)
        server.quit()
        return True, f"נשלח ל-{GMAIL_USER}"
    except Exception as e:
        return False, f"שגיאה: {e}"


def send_telegram(content):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False, "פרטי טלגרם חסרים"
    try:
        escaped = html_lib.escape(content)
        formatted = f"<pre>{escaped}</pre>"
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = urllib.parse.urlencode({
            "chat_id": TELEGRAM_CHAT_ID,
            "text": formatted,
            "parse_mode": "HTML",
        }).encode("utf-8")
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        if result.get("ok"):
            return True, "נשלח"
        return False, result.get("description", "שגיאה")
    except Exception as e:
        return False, f"שגיאה: {e}"


# ============================================================
# CSV HISTORY
# ============================================================

def save_history(rows):
    fieldnames = [
        "scan_date", "symbol", "name", "price", "currency", "sector", "industry",
        "market_cap", "pe_ratio", "forward_pe", "peg_ratio",
        "earnings_growth", "revenue_growth",
        "operating_margin", "profit_margin", "roe",
        "debt_to_equity", "current_ratio",
        "day_change", "fifty_two_week_high", "fifty_two_week_low",
        "next_earnings", "score", "ceo_name", "cfo_name", "error",
    ]
    new_file = not HISTORY_CSV.exists()
    with open(HISTORY_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        if new_file:
            writer.writeheader()
        for row in rows:
            writer.writerow(row)


# ============================================================
# DISCOVERY ORCHESTRATION
# ============================================================

def run_full_discovery(weights, progress_callback=None):
    """weights = (growth, profitability, valuation) — סך הכל אמור להיות 100."""
    w_g, w_p, w_v = weights

    rows = []
    n = len(TICKERS)
    for i, symbol in enumerate(TICKERS, 1):
        if progress_callback:
            progress_callback(i, n, f"סורק {symbol} ({i}/{n})")
        rows.append(fetch_deep(symbol))

    valid = [r for r in rows if has_min_data(r)]
    for row in valid:
        row["score_growth"] = score_growth(row, w_g)
        row["score_profitability"] = score_profitability(row, w_p)
        row["score_valuation"] = score_valuation(row, w_v)
        row["score"] = row["score_growth"] + row["score_profitability"] + row["score_valuation"]

    valid.sort(key=lambda r: r["score"], reverse=True)
    top10 = valid[:10]

    # תובנה לכל מניה תקינה
    for row in valid:
        row["insight"] = generate_insight(row)

    if progress_callback:
        progress_callback(n, n, "מעשיר את ה-Top 10 בחדשות והנהלה...")
    for row in top10:
        row["news"] = fetch_news_for_stock(row["symbol"], row.get("name", ""), n=2)
        row["management"] = fetch_management(row["symbol"])
        row["price_history_summary"] = _fetch_price_history_summary(row["symbol"])
        row["quarterly"] = _fetch_quarterly_financials(row["symbol"])
        mgmt = row.get("management") or {}
        row["ceo_name"] = (mgmt.get("ceo") or {}).get("name", "")
        row["cfo_name"] = (mgmt.get("cfo") or {}).get("name", "")

    if progress_callback:
        progress_callback(n, n, "מביא כותרות מאקרו...")
    macro = fetch_macro_headlines()

    save_history(rows)

    return {
        "all_rows": rows,
        "valid": valid,
        "top10": top10,
        "macro": macro,
        "weights": weights,
    }


def analyze_single_stock(symbol, weights, openai_key=None):
    """פונקציה מודולרית — ניתוח מלא של מניה אחת.
    משמשת גם את הסריקה הקבועה (דרך הקריאות הפנימיות) וגם את שדה
    הקלט החופשי. מחזירה row dict עם כל השדות. אם נכשל, יש שדה 'error'.

    weights = (growth, profitability, valuation)
    """
    if not symbol:
        return {"symbol": "", "error": "לא הוזן סימול"}

    symbol = symbol.strip().upper()
    w_g, w_p, w_v = weights

    # שלב 1 — נתוני בסיס
    row = fetch_deep(symbol)
    if row.get("error"):
        return row

    # שלב 2 — ציון משוקלל
    row["score_growth"] = score_growth(row, w_g)
    row["score_profitability"] = score_profitability(row, w_p)
    row["score_valuation"] = score_valuation(row, w_v)
    row["score"] = row["score_growth"] + row["score_profitability"] + row["score_valuation"]

    # שלב 3 — תובנה אוטומטית (לפי המדדים)
    row["insight"] = generate_insight(row)

    # שלב 4 — העשרה: חדשות, הנהלה, היסטוריית מחיר
    row["news"] = fetch_news_for_stock(row["symbol"], row.get("name", ""), n=2)
    row["management"] = fetch_management(row["symbol"])
    row["price_history_summary"] = _fetch_price_history_summary(row["symbol"])
    row["quarterly"] = _fetch_quarterly_financials(row["symbol"])
    mgmt = row.get("management") or {}
    row["ceo_name"] = (mgmt.get("ceo") or {}).get("name", "")
    row["cfo_name"] = (mgmt.get("cfo") or {}).get("name", "")

    # שלב 5 — AI Insight (אם יש מפתח)
    if openai_key:
        ai_text, ai_err = get_ai_insights(row, row.get("news", []), openai_key)
        row["ai_insight"] = ai_text if ai_text else f"_שגיאה: {ai_err}_"

    return row


# ============================================================
# STREAMLIT UI
# ============================================================

st.set_page_config(
    page_title="Discovery Agent",
    page_icon="📊",
    layout="wide",
)

# === Custom CSS — Modern Fintech Light Theme ===
st.markdown("""
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
    /* ===== GLOBAL LIGHT THEME ===== */
    .stApp {
        background-color: #f8fafc !important;
        color: #0f172a !important;
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
    }
    h1, h2, h3, h4, h5 {
        color: #0f172a !important;
        font-weight: 700 !important;
        letter-spacing: -0.02em !important;
    }
    h1 { font-size: 2.4em !important; }

    /* ===== SIDEBAR ===== */
    [data-testid="stSidebar"] {
        background-color: #ffffff !important;
        border-right: 1px solid #e2e8f0 !important;
    }
    [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 {
        color: #0f172a !important;
    }

    /* ===== BUTTONS ===== */
    .stButton > button {
        border-radius: 12px !important;
        font-weight: 600 !important;
        font-family: 'Inter', sans-serif !important;
        transition: all 0.2s ease !important;
        border: 1px solid #e2e8f0 !important;
        background: #ffffff !important;
        color: #0f172a !important;
    }
    .stButton > button:hover {
        transform: translateY(-1px);
        border-color: #22c55e !important;
        box-shadow: 0 4px 12px rgba(34,197,94,0.15);
    }
    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #22c55e 0%, #16a34a 100%) !important;
        color: white !important;
        border: none !important;
        box-shadow: 0 4px 14px rgba(34,197,94,0.25);
    }
    .stButton > button[kind="primary"]:hover {
        box-shadow: 0 6px 20px rgba(34,197,94,0.35);
    }

    /* ===== METRIC CARDS ===== */
    [data-testid="stMetric"] {
        background: #ffffff;
        padding: 16px 18px;
        border-radius: 14px;
        border: 1px solid #e2e8f0;
        transition: all 0.2s ease;
        box-shadow: 0 1px 3px rgba(0,0,0,0.04);
    }
    [data-testid="stMetric"]:hover {
        border-color: #cbd5e1;
        transform: translateY(-1px);
        box-shadow: 0 4px 12px rgba(0,0,0,0.06);
    }
    [data-testid="stMetricValue"] {
        color: #0f172a !important;
        font-weight: 700 !important;
        font-size: 1.7em !important;
    }
    [data-testid="stMetricLabel"] {
        color: #64748b !important;
        font-weight: 500 !important;
        font-size: 0.85em !important;
        letter-spacing: 0.02em;
    }

    /* ===== EXPANDERS ===== */
    div[data-testid="stExpander"] {
        background: #ffffff !important;
        border: 1px solid #e2e8f0 !important;
        border-radius: 14px !important;
        margin-bottom: 8px !important;
        transition: border-color 0.2s ease;
        box-shadow: 0 1px 2px rgba(0,0,0,0.03);
    }
    div[data-testid="stExpander"]:hover {
        border-color: #cbd5e1 !important;
    }
    div[data-testid="stExpander"] summary {
        color: #0f172a !important;
        font-weight: 600 !important;
        font-family: 'Inter', sans-serif !important;
    }

    /* ===== TABLES ===== */
    .stDataFrame {
        border-radius: 14px !important;
        overflow: hidden !important;
        border: 1px solid #e2e8f0 !important;
    }
    .stDataFrame thead tr th {
        background-color: #f1f5f9 !important;
        color: #0f172a !important;
        font-weight: 700 !important;
        text-transform: uppercase;
        font-size: 11px !important;
        letter-spacing: 0.06em;
        border-bottom: 2px solid #cbd5e1 !important;
    }

    /* ===== INPUTS ===== */
    .stTextInput input, .stSelectbox > div > div, .stTextArea textarea {
        background-color: #ffffff !important;
        color: #0f172a !important;
        border: 1px solid #e2e8f0 !important;
        border-radius: 10px !important;
    }
    .stTextInput input:focus, .stSelectbox > div > div:focus-within {
        border-color: #22c55e !important;
        box-shadow: 0 0 0 3px rgba(34,197,94,0.12) !important;
    }

    /* ===== ALERT BOXES ===== */
    [data-testid="stAlert"] {
        border-radius: 12px !important;
        border: 1px solid #e2e8f0 !important;
    }

    /* ===== STOCK CARDS ===== */
    .stock-card {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 16px;
        padding: 18px;
        margin-bottom: 14px;
        position: relative;
        transition: all 0.3s ease;
        box-shadow: 0 1px 3px rgba(0,0,0,0.04);
    }
    .stock-card:hover {
        border-color: #cbd5e1;
        transform: translateY(-3px);
        box-shadow: 0 12px 28px rgba(0,0,0,0.08);
    }
    .stock-card-rank {
        position: absolute;
        top: 14px;
        left: 16px;
        font-size: 0.72em;
        font-weight: 700;
        color: #94a3b8;
        letter-spacing: 0.06em;
    }
    .stock-card-head {
        display: flex;
        gap: 14px;
        align-items: center;
        margin-bottom: 16px;
        margin-top: 10px;
    }
    .stock-logo-wrap {
        position: relative;
        width: 52px;
        height: 52px;
        border-radius: 12px;
        overflow: hidden;
        flex-shrink: 0;
        box-shadow: 0 2px 6px rgba(0,0,0,0.08);
        border: 1px solid #e2e8f0;
    }
    .stock-logo-fallback {
        position: absolute;
        inset: 0;
        display: flex;
        align-items: center;
        justify-content: center;
        color: white;
        font-weight: 800;
        font-size: 22px;
        font-family: 'Inter', sans-serif;
    }
    .stock-logo {
        position: absolute;
        inset: 0;
        width: 100%;
        height: 100%;
        object-fit: contain;
        background: white;
        padding: 7px;
    }
    .stock-card-meta {
        flex-grow: 1;
        min-width: 0;
    }
    .stock-card-symbol {
        font-size: 1.2em;
        font-weight: 800;
        color: #0f172a;
        line-height: 1.1;
    }
    .stock-card-name {
        font-size: 0.85em;
        color: #64748b;
        line-height: 1.2;
        margin-top: 2px;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    .stock-card-sector {
        font-size: 0.7em;
        color: #94a3b8;
        margin-top: 4px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }
    .stock-card-score {
        text-align: center;
        flex-shrink: 0;
        padding: 0 6px;
    }
    .stock-card-score .score-num {
        font-size: 1.9em;
        font-weight: 800;
        line-height: 1;
        font-family: 'Inter', sans-serif;
    }
    .stock-card-score .score-label {
        font-size: 0.7em;
        color: #94a3b8;
        font-weight: 500;
        margin-top: 2px;
    }
    .stock-card-price-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 14px;
        padding-bottom: 14px;
        border-bottom: 1px solid #e2e8f0;
    }
    .stock-card-price {
        font-size: 1.5em;
        font-weight: 700;
        color: #0f172a;
    }
    .day-pill {
        padding: 5px 12px;
        border-radius: 8px;
        font-size: 0.85em;
        font-weight: 700;
        letter-spacing: 0.02em;
    }
    .stock-card-stats {
        display: grid;
        grid-template-columns: 1fr 1fr 1fr;
        gap: 8px;
    }
    .stock-card-stats .stat {
        background: #f8fafc;
        padding: 10px 12px;
        border-radius: 10px;
        border: 1px solid #f1f5f9;
    }
    .stat-label {
        font-size: 0.68em;
        color: #94a3b8;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }
    .stat-value {
        font-size: 0.95em;
        font-weight: 700;
        color: #0f172a;
        margin-top: 3px;
    }
</style>
""", unsafe_allow_html=True)

# === Header ===
st.title("📊 Discovery Agent")
st.caption("סורק מניות אמריקאיות וישראליות, מדרג Top 10 לפי ציון משוקלל")

# === Sidebar (controls) ===
with st.sidebar:
    st.subheader("⚙️ משקלי הציון")
    st.caption("התאם, ולחץ Run Discovery כדי לחשב מחדש לפי המשקלים החדשים.")

    w_growth = st.slider("📈 צמיחה (%)", 0, 100, DEFAULT_WEIGHT_GROWTH, key="w_growth")
    w_prof = st.slider("💰 רווחיות (%)", 0, 100, DEFAULT_WEIGHT_PROFITABILITY, key="w_prof")
    w_val = st.slider("⚖️ תמחור (%)", 0, 100, DEFAULT_WEIGHT_VALUATION, key="w_val")

    total_w = w_growth + w_prof + w_val
    if total_w == 100:
        st.success(f"סך משקלים: {total_w} ✓")
    else:
        st.warning(f"סך משקלים: {total_w} (רצוי 100)")

    st.divider()
    st.subheader("📋 רשימת המעקב")
    st.write(f"**{len(TICKERS)}** מניות ברשימה")

    st.divider()
    st.subheader("🔌 סטטוס חיבורים")
    st.write(f"📧 Gmail: {'✅' if GMAIL_USER and GMAIL_APP_PASSWORD else '❌'}")
    st.write(f"📱 Telegram: {'✅' if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID else '❌'}")
    st.write(f"📰 NewsAPI: {'✅' if NEWSAPI_KEY else '⚠️ ללא'}")
    st.caption("מפתחות מוגדרים כמשתני סביבה.")

    if not all([GMAIL_USER, GMAIL_APP_PASSWORD, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID]):
        st.warning("חיבור חסר. הגדר משתני סביבה לפני הרצה.")

    st.divider()
    st.subheader("🤖 AI Analyst (אופציונלי)")
    st.caption(
        "הזן מפתח OpenAI כדי להפעיל ניתוח GPT-4o-mini ל-Top 10. "
        "עלות: ~$0.001-0.002 לסריקה. לא יישמר; פג כשתסגור."
    )
    openai_key_input = st.text_input(
        "OpenAI API Key",
        type="password",
        value="",
        placeholder="sk-...",
        key="openai_key_input",
        help="או הגדר משתנה סביבה OPENAI_API_KEY כדי שיישמר בין הפעלות.",
    )
    effective_openai_key = openai_key_input or OPENAI_API_KEY
    if effective_openai_key:
        st.success("AI מוכן ✓")
    elif OPENAI_API_KEY:
        st.info("מפתח טעון מ-env var.")
    else:
        st.caption("ללא מפתח — סקציית AI Insight תהיה ריקה.")

    st.divider()
    st.caption("⚠️ ניתוח אוטומטי בלבד. אינו ייעוץ השקעות.")


# === Run button ===
if "results" not in st.session_state:
    st.session_state["results"] = None
    st.session_state["last_run"] = None
    st.session_state["email_status"] = None
    st.session_state["telegram_status"] = None
    st.session_state["telegram_macro_status"] = None
    st.session_state["ai_insights"] = {}
    st.session_state["last_custom_result"] = None

col_btn, col_meta = st.columns([1, 3])
with col_btn:
    run_clicked = st.button("🚀 Run Discovery", type="primary", use_container_width=True)
with col_meta:
    if st.session_state["last_run"]:
        st.caption(f"סריקה אחרונה: {st.session_state['last_run']}")


# === Run scan ===
if run_clicked:
    # נקה תובנות AI ישנות (כי הטופ 10 עתיד להשתנות)
    st.session_state["ai_insights"] = {}
    progress_bar = st.progress(0, text="מתחיל...")

    def update_progress(i, n, label):
        progress_bar.progress(min(i / n, 1.0), text=label)

    weights = (w_growth, w_prof, w_val)

    with st.spinner("מבצע סריקה (3-5 דקות)..."):
        results = run_full_discovery(weights=weights, progress_callback=update_progress)
        st.session_state["results"] = results
        st.session_state["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M")

        top10 = results["top10"]
        valid = results["valid"]
        macro = results["macro"]

        if top10:
            subject = f"📊 דוח גילוי - Top 10 - {datetime.now().strftime('%d/%m/%Y')}"
            ok, msg = send_email(subject, build_html_email(top10, valid, macro))
            st.session_state["email_status"] = (ok, msg)
            ok_t, msg_t = send_telegram(build_telegram_message(top10))
            st.session_state["telegram_status"] = (ok_t, msg_t)
            macro_msg = build_macro_telegram_message(macro)
            if macro_msg:
                ok_m, msg_m = send_telegram(macro_msg)
                st.session_state["telegram_macro_status"] = (ok_m, msg_m)

    progress_bar.empty()


# === Display results ===
results = st.session_state.get("results")
if results:
    top10 = results["top10"]
    valid = results["valid"]
    macro = results["macro"]
    all_rows = results["all_rows"]

    # --- Send statuses ---
    es = st.session_state.get("email_status")
    ts = st.session_state.get("telegram_status")
    tms = st.session_state.get("telegram_macro_status")
    if es or ts:
        st_cols = st.columns(3)
        if es:
            ok, msg = es
            (st_cols[0].success if ok else st_cols[0].error)(f"📧 מייל: {msg}")
        if ts:
            ok, msg = ts
            (st_cols[1].success if ok else st_cols[1].error)(f"📱 טלגרם: {msg}")
        if tms:
            ok, msg = tms
            (st_cols[2].success if ok else st_cols[2].error)(f"🌍 מאקרו: {msg}")

    # --- Top metrics row ---
    avg_score = sum(r.get("score", 0) for r in valid) / max(1, len(valid))
    green_count = sum(1 for r in valid if r.get("score", 0) >= 60)
    yellow_count = sum(1 for r in valid if 40 <= r.get("score", 0) < 60)
    red_count = sum(1 for r in valid if r.get("score", 0) < 40)
    leader = top10[0] if top10 else None

    st.subheader("📊 סקירת שוק כללית")
    mc = st.columns(5)
    with mc[0]:
        st.metric("נסרקו", f"{len(valid)}/{len(all_rows)}")
    with mc[1]:
        st.metric("ציון ממוצע", f"{avg_score:.1f}")
    with mc[2]:
        st.metric("🟢 חזקות (60+)", green_count)
    with mc[3]:
        st.metric("🟡 בינוניות (40-60)", yellow_count)
    with mc[4]:
        if leader:
            st.metric("🏆 מוביל", leader["symbol"], delta=f"{leader.get('score', 0):.0f}")

    st.divider()

    # --- Top 10 table ---
    st.subheader("🎯 Top 10")
    table_rows = []
    for i, row in enumerate(top10, 1):
        table_rows.append({
            "#": i,
            "Symbol": row["symbol"],
            "Day %": fmt_day_pct(row.get("day_change")),
            "Name": (row.get("name") or "")[:36],
            "Sector": row.get("sector", ""),
            "Score": round(row.get("score", 0), 1),
            "Price": fmt_price(row["price"], row["symbol"], row.get("currency", "")),
            "P/E": fmt_num(row.get("pe_ratio"), 1),
            "EPS YoY": fmt_pct(row.get("earnings_growth")),
            "Rev YoY": fmt_pct(row.get("revenue_growth")),
            "Op Margin": fmt_pct(row.get("operating_margin")),
            "ROE": fmt_pct(row.get("roe")),
            "Mkt Cap": row.get("market_cap_display", ""),
            "Next Earnings": row.get("next_earnings", ""),
        })
    df = pd.DataFrame(table_rows)
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Score": st.column_config.ProgressColumn(
                "Score",
                help="ציון משוקלל 0-100",
                format="%.1f",
                min_value=0,
                max_value=100,
            ),
        },
    )

    # --- Candlestick chart ---
    st.divider()
    st.subheader("📈 גרף נר יומי - 30 יום אחרון")
    chart_options = {row["symbol"]: f"{row['symbol']} — {(row.get('name') or '')[:35]}" for row in top10}
    selected = st.selectbox(
        "בחר מניה מ-Top 10",
        options=list(chart_options.keys()),
        format_func=lambda s: chart_options[s],
        key="candlestick_select",
    )
    if selected:
        with st.spinner(f"טוען נתוני מחיר ל-{selected}..."):
            try:
                t = yf.Ticker(selected)
                hist = t.history(period="1mo")
                if hist.empty:
                    st.warning(f"אין נתוני מחיר זמינים ל-{selected}.")
                else:
                    fig = go.Figure(data=[go.Candlestick(
                        x=hist.index,
                        open=hist["Open"],
                        high=hist["High"],
                        low=hist["Low"],
                        close=hist["Close"],
                        increasing_line_color="#22c55e",
                        decreasing_line_color="#ef4444",
                        increasing_fillcolor="#22c55e",
                        decreasing_fillcolor="#ef4444",
                    )])
                    fig.update_layout(
                        title=f"{selected} — 30 ימים אחרונים",
                        xaxis_rangeslider_visible=False,
                        height=440,
                        margin=dict(l=20, r=20, t=50, b=20),
                        template="plotly_white",
                        yaxis_title="מחיר",
                    )
                    st.plotly_chart(fig, use_container_width=True)
            except Exception as e:
                st.error(f"שגיאה בטעינת הגרף: {e}")

    # --- AI Insights button (cost-controlled) ---
    if effective_openai_key:
        st.divider()
        col_ai_btn, col_ai_meta = st.columns([1, 3])
        with col_ai_btn:
            ai_clicked = st.button(
                "🤖 Generate AI Insights",
                type="secondary",
                use_container_width=True,
            )
        with col_ai_meta:
            existing = sum(
                1 for v in st.session_state.get("ai_insights", {}).values()
                if v and not v.startswith("_")
            )
            if existing:
                st.caption(f"קיימות תובנות AI עבור {existing} מניות (פתח אקורדיון לראות).")
            else:
                st.caption("AI ייצור תובנה תיאורית קצרה לכל מניה ב-Top 10. עלות: ~$0.001-0.002.")

        if ai_clicked:
            ai_progress = st.progress(0, text="מנתח...")
            new_insights = {}
            for idx, ai_row in enumerate(top10):
                ai_progress.progress(
                    (idx + 1) / len(top10),
                    text=f"AI מנתח את {ai_row['symbol']} ({idx + 1}/{len(top10)})",
                )
                insight, err = get_ai_insights(
                    ai_row, ai_row.get("news", []), effective_openai_key
                )
                if insight:
                    new_insights[ai_row["symbol"]] = insight
                else:
                    new_insights[ai_row["symbol"]] = f"_שגיאה: {err}_"
            st.session_state["ai_insights"] = new_insights
            ai_progress.empty()
            successful = sum(1 for v in new_insights.values() if not v.startswith("_"))
            st.success(
                f"AI חישב תובנות עבור {successful}/{len(top10)} מניות. "
                "פתח את האקורדיונים מטה כדי לראות."
            )
            st.rerun()

    # --- Top 10 expanders (rich) ---
    st.divider()
    st.subheader("🔎 פירוט מורחב — Top 10")
    for i, row in enumerate(top10, 1):
        score = row.get("score", 0)
        score_emoji = "🟢" if score >= 60 else ("🟡" if score >= 40 else "🔴")
        day_color_md = fmt_day_pct_color(row.get("day_change"))
        day_part = f" {day_color_md}" if day_color_md else ""
        title = (
            f"{score_emoji} #{i} — {row['symbol']}{day_part} • "
            f"{row.get('sector', '?')} • Score {score:.0f}/100"
        )
        with st.expander(title):
            c1, c2 = st.columns([1, 2])

            with c1:
                st.markdown(f"**{row.get('name', '')}**")
                st.metric("מחיר", fmt_price(row["price"], row["symbol"], row.get("currency", "")))
                st.metric("P/E", fmt_num(row.get("pe_ratio"), 1))
                st.metric("שווי שוק", row.get("market_cap_display", "N/A"))
                if row.get("next_earnings"):
                    st.write(f"📅 **דוח הבא:** {row['next_earnings']}")

            with c2:
                st.markdown(f"**💡 תובנה:** {row.get('insight', '')}")

                st.markdown("**📊 מדדים:**")
                st.write(f"- EPS YoY: {fmt_pct(row.get('earnings_growth'))}")
                st.write(f"- Revenue YoY: {fmt_pct(row.get('revenue_growth'))}")
                st.write(f"- Operating Margin: {fmt_pct(row.get('operating_margin'))}")
                st.write(f"- ROE: {fmt_pct(row.get('roe'))}")
                if row.get("debt_to_equity") is not None:
                    st.write(f"- Debt/Equity: {fmt_num(row.get('debt_to_equity'), 0)}")

                # === מספרים נטו (TTM + רבעון אחרון) ===
                fc = row.get("financial_currency") or "USD"
                quarterly = row.get("quarterly") or {}
                has_numbers = any([
                    row.get("total_revenue"),
                    row.get("net_income_ttm"),
                    row.get("op_income_ttm"),
                    row.get("ebitda"),
                    quarterly.get("q_revenue"),
                ])
                if has_numbers:
                    st.markdown("**💵 מספרים נטו:**")
                    if row.get("total_revenue") is not None:
                        st.write(f"- הכנסות (12 חודשים אחרונים): {fmt_big_money(row['total_revenue'], fc)}")
                    if quarterly.get("q_revenue") is not None:
                        q_date = quarterly.get("q_date", "")
                        date_str = f" (לרבעון שהסתיים {q_date})" if q_date else ""
                        st.write(f"- הכנסות רבעון אחרון{date_str}: {fmt_big_money(quarterly['q_revenue'], fc)}")
                    if row.get("op_income_ttm") is not None:
                        st.write(f"- רווח תפעולי (TTM): {fmt_big_money(row['op_income_ttm'], fc)}")
                    if quarterly.get("q_operating_income") is not None:
                        st.write(f"- רווח תפעולי רבעון אחרון: {fmt_big_money(quarterly['q_operating_income'], fc)}")
                    if row.get("net_income_ttm") is not None:
                        st.write(f"- רווח נקי (TTM): {fmt_big_money(row['net_income_ttm'], fc)}")
                    if quarterly.get("q_net_income") is not None:
                        st.write(f"- רווח נקי רבעון אחרון: {fmt_big_money(quarterly['q_net_income'], fc)}")
                    if row.get("ebitda") is not None:
                        st.write(f"- EBITDA (TTM): {fmt_big_money(row['ebitda'], fc)}")

                # === תחזיות אנליסטים ===
                target_mean = row.get("target_mean_price")
                if target_mean is not None:
                    st.markdown("**🎯 תחזיות אנליסטים (12 חודשים)** *— דעות חיצוניות, לא ייעוץ:*")
                    cur_price = row.get("price") or 0
                    upside = ((target_mean - cur_price) / cur_price * 100) if cur_price else None
                    upside_str = f"  ({upside:+.1f}% מהמחיר הנוכחי)" if upside is not None else ""
                    st.write(f"- יעד מחיר ממוצע: {fmt_price(target_mean, row['symbol'], row.get('currency',''))}{upside_str}")
                    if row.get("target_low_price") and row.get("target_high_price"):
                        low_p = fmt_price(row['target_low_price'], row['symbol'], row.get('currency',''))
                        high_p = fmt_price(row['target_high_price'], row['symbol'], row.get('currency',''))
                        st.write(f"- טווח אנליסטים: {low_p} – {high_p}")
                    if row.get("num_analysts"):
                        st.write(f"- מספר אנליסטים בכיסוי: {row['num_analysts']}")
                    if row.get("recommendation_key"):
                        st.write(f"- המלצה כוללת: **{fmt_recommendation(row['recommendation_key'])}**")

                mgmt = row.get("management") or {}
                if mgmt.get("ceo") or mgmt.get("cfo"):
                    st.markdown("**👥 הנהלה:**")
                    if mgmt.get("ceo"):
                        ceo = mgmt["ceo"]
                        age_str = f", בן {ceo['age']}" if ceo.get("age") else ""
                        st.write(f"- CEO: {ceo['name']} ({ceo.get('title', '')}{age_str})")
                    if mgmt.get("cfo"):
                        cfo = mgmt["cfo"]
                        age_str = f", בן {cfo['age']}" if cfo.get("age") else ""
                        st.write(f"- CFO: {cfo['name']} ({cfo.get('title', '')}{age_str})")

                if row.get("news"):
                    st.markdown("**📰 חדשות אחרונות** *(סיווג נאיבי לפי מילות מפתח, לא AI)*:")
                    for n in row["news"]:
                        _, sentiment_emoji = label_sentiment(n["title"])
                        meta = ""
                        if n.get("source") or n.get("published"):
                            meta = f" — *{n.get('source', '')}* {n.get('published', '')}"
                        if n.get("link"):
                            st.markdown(f"- {sentiment_emoji} [{n['title']}]({n['link']}){meta}")
                        else:
                            st.markdown(f"- {sentiment_emoji} {n['title']}{meta}")

                # AI Insight — מוצג רק אם נוצר באמצעות הכפתור
                ai_insight_text = st.session_state.get("ai_insights", {}).get(row["symbol"])
                if ai_insight_text:
                    st.markdown("**🤖 AI Insight** *(GPT-4o-mini — תיאורי, לא ייעוץ)*")
                    if ai_insight_text.startswith("_"):
                        st.warning(ai_insight_text.strip("_"))
                    else:
                        st.info(ai_insight_text)

    # --- Rest of stocks ---
    rest = valid[10:]
    if rest:
        st.divider()
        st.subheader(f"📚 שאר המניות שנסרקו ({len(rest)})")
        st.caption(
            "מדדי בסיס + תובנה אוטומטית. ללא חדשות והנהלה (חיסכון בזמן וב-NewsAPI quota)."
        )
        for rank, row in enumerate(rest, 11):
            score = row.get("score", 0)
            score_emoji = "🟢" if score >= 60 else ("🟡" if score >= 40 else "🔴")
            day_color_md = fmt_day_pct_color(row.get("day_change"))
            day_part = f" {day_color_md}" if day_color_md else ""
            title = (
                f"{score_emoji} #{rank} — {row['symbol']}{day_part} • "
                f"{row.get('sector', '?')} • Score {score:.0f}/100"
            )
            with st.expander(title):
                c1, c2 = st.columns([1, 2])
                with c1:
                    st.markdown(f"**{row.get('name', '')}**")
                    st.metric("מחיר", fmt_price(row["price"], row["symbol"], row.get("currency", "")))
                    st.metric("P/E", fmt_num(row.get("pe_ratio"), 1))
                    st.metric("שווי שוק", row.get("market_cap_display", "N/A"))
                    if row.get("next_earnings"):
                        st.write(f"📅 **דוח הבא:** {row['next_earnings']}")
                with c2:
                    st.markdown(f"**💡 תובנה:** {row.get('insight', '')}")
                    st.markdown("**📊 מדדים:**")
                    st.write(f"- EPS YoY: {fmt_pct(row.get('earnings_growth'))}")
                    st.write(f"- Revenue YoY: {fmt_pct(row.get('revenue_growth'))}")
                    st.write(f"- Operating Margin: {fmt_pct(row.get('operating_margin'))}")
                    st.write(f"- ROE: {fmt_pct(row.get('roe'))}")
                    if row.get("debt_to_equity") is not None:
                        st.write(f"- Debt/Equity: {fmt_num(row.get('debt_to_equity'), 0)}")
                    if row.get("forward_pe") is not None:
                        st.write(f"- Forward P/E: {fmt_num(row.get('forward_pe'), 1)}")

                    # מספרים נטו TTM (רק TTM — לא מביאים רבעוני לשאר המניות)
                    fc = row.get("financial_currency") or "USD"
                    if any([row.get("total_revenue"), row.get("net_income_ttm"), row.get("op_income_ttm")]):
                        st.markdown("**💵 מספרים נטו (TTM):**")
                        if row.get("total_revenue") is not None:
                            st.write(f"- הכנסות: {fmt_big_money(row['total_revenue'], fc)}")
                        if row.get("op_income_ttm") is not None:
                            st.write(f"- רווח תפעולי: {fmt_big_money(row['op_income_ttm'], fc)}")
                        if row.get("net_income_ttm") is not None:
                            st.write(f"- רווח נקי: {fmt_big_money(row['net_income_ttm'], fc)}")

                    # תחזיות אנליסטים
                    target_mean = row.get("target_mean_price")
                    if target_mean is not None:
                        cur_price = row.get("price") or 0
                        upside = ((target_mean - cur_price) / cur_price * 100) if cur_price else None
                        upside_str = f"  ({upside:+.1f}%)" if upside is not None else ""
                        rec = fmt_recommendation(row.get("recommendation_key"))
                        n_an = row.get("num_analysts") or "?"
                        st.markdown(f"**🎯 יעד אנליסטים:** {fmt_price(target_mean, row['symbol'], row.get('currency',''))}{upside_str} • המלצה: {rec} • {n_an} אנליסטים")

                    if row.get("industry"):
                        st.caption(f"תעשייה: {row['industry']}")

    # --- Full table (collapsed) ---
    st.divider()
    with st.expander(f"📋 טבלה מלאה - כל {len(valid)} המניות שנסרקו"):
        full_rows = []
        for rank, row in enumerate(valid, 1):
            full_rows.append({
                "Rank": rank,
                "Symbol": row["symbol"],
                "Name": (row.get("name") or "")[:36],
                "Sector": row.get("sector", ""),
                "Score": round(row.get("score", 0), 1),
                "Price": fmt_price(row["price"], row["symbol"], row.get("currency", "")),
                "P/E": fmt_num(row.get("pe_ratio"), 1),
                "EPS YoY": fmt_pct(row.get("earnings_growth")),
                "Rev YoY": fmt_pct(row.get("revenue_growth")),
                "Op Margin": fmt_pct(row.get("operating_margin")),
                "ROE": fmt_pct(row.get("roe")),
                "Mkt Cap": row.get("market_cap_display", ""),
            })
        full_df = pd.DataFrame(full_rows)
        st.dataframe(
            full_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Score": st.column_config.ProgressColumn(
                    "Score", format="%.1f", min_value=0, max_value=100,
                ),
            },
        )

    # --- Macro ---
    if macro and (macro.get("monetary") or macro.get("geopolitical")):
        st.divider()
        st.subheader("🌍 כותרות מאקרו עולמיות")
        st.caption("עם סיווג סנטימנט נאיבי לפי מילות מפתח")
        mc1, mc2 = st.columns(2)
        with mc1:
            st.markdown("### 💵 מוניטרי / כלכלה")
            for a in macro.get("monetary", []):
                _, emoji = label_sentiment(a["title"])
                meta = f" — *{a.get('source', '')}* {a.get('published', '')}"
                if a.get("link"):
                    st.markdown(f"- {emoji} [{a['title']}]({a['link']}){meta}")
                else:
                    st.markdown(f"- {emoji} {a['title']}{meta}")
        with mc2:
            st.markdown("### 🌐 גיאופוליטי")
            for a in macro.get("geopolitical", []):
                _, emoji = label_sentiment(a["title"])
                meta = f" — *{a.get('source', '')}* {a.get('published', '')}"
                if a.get("link"):
                    st.markdown(f"- {emoji} [{a['title']}]({a['link']}){meta}")
                else:
                    st.markdown(f"- {emoji} {a['title']}{meta}")

    # --- ניתוח מניה חופשית ---
    st.divider()
    st.subheader("🔍 ניתוח מניה חופשית")
    st.caption(
        "הזן סימול מניה כדי לקבל אותו ניתוח שמקבלות מניות ב-Top 10 — "
        "נתוני בסיס, ציון משוקלל, חדשות עם סנטימנט, הנהלה, ו-AI Insight אם הוגדר מפתח OpenAI. "
        "לחיצה על Enter בתוך השדה תפעיל את הניתוח, או לחץ על הכפתור."
    )

    with st.form("custom_stock_form", clear_on_submit=False):
        col_input, col_btn = st.columns([3, 1])
        with col_input:
            custom_symbol_raw = st.text_input(
                "סימול מניה",
                value="",
                placeholder="לדוגמה: AAPL, NVDA, TEVA, POLI.TA",
                key="custom_symbol_input",
                label_visibility="collapsed",
            )
        with col_btn:
            custom_analyze = st.form_submit_button(
                "🔬 נתח", type="primary", use_container_width=True
            )

    custom_symbol = (custom_symbol_raw or "").strip().upper()

    if custom_analyze and custom_symbol:
        with st.spinner(f"מנתח {custom_symbol}... (כולל AI אם מוגדר)"):
            weights = (w_growth, w_prof, w_val)
            st.session_state["last_custom_result"] = analyze_single_stock(
                custom_symbol, weights, effective_openai_key
            )
    elif custom_analyze and not custom_symbol:
        st.warning("הזן סימול לפני שתלחץ נתח.")

    # תצוגת התוצאה האחרונה
    custom_result = st.session_state.get("last_custom_result")
    if custom_result:
        cs = custom_result.get("symbol", "?")
        if custom_result.get("error"):
            st.error(f"לא ניתן לנתח את {cs}: {custom_result['error']}")
        else:
            cscore = custom_result.get("score", 0)
            cemoji = "🟢" if cscore >= 60 else ("🟡" if cscore >= 40 else "🔴")
            cday_color_md = fmt_day_pct_color(custom_result.get("day_change"))
            cday_part = f"  {cday_color_md}" if cday_color_md else ""
            st.markdown(f"### {cemoji} {cs}{cday_part} — {custom_result.get('name', '')}")
            sec_ind = " • ".join(filter(None, [custom_result.get("sector"), custom_result.get("industry")]))
            if sec_ind:
                st.caption(sec_ind)

            c_cols = st.columns(4)
            with c_cols[0]:
                st.metric("Score", f"{cscore:.0f}/100")
            with c_cols[1]:
                st.metric("מחיר", fmt_price(custom_result["price"], cs, custom_result.get("currency", "")))
            with c_cols[2]:
                st.metric("P/E", fmt_num(custom_result.get("pe_ratio"), 1))
            with c_cols[3]:
                st.metric("שווי שוק", custom_result.get("market_cap_display", "N/A"))

            st.markdown(f"**💡 תובנה:** {custom_result.get('insight', '')}")

            with st.expander("📊 כל המדדים"):
                st.write(f"- EPS YoY: {fmt_pct(custom_result.get('earnings_growth'))}")
                st.write(f"- Revenue YoY: {fmt_pct(custom_result.get('revenue_growth'))}")
                st.write(f"- Operating Margin: {fmt_pct(custom_result.get('operating_margin'))}")
                st.write(f"- ROE: {fmt_pct(custom_result.get('roe'))}")
                if custom_result.get("debt_to_equity") is not None:
                    st.write(f"- Debt/Equity: {fmt_num(custom_result.get('debt_to_equity'), 0)}")
                if custom_result.get("forward_pe") is not None:
                    st.write(f"- Forward P/E: {fmt_num(custom_result.get('forward_pe'), 1)}")
                if custom_result.get("next_earnings"):
                    st.write(f"- 📅 דוח הבא: {custom_result['next_earnings']}")

            # === מספרים נטו ===
            cfc = custom_result.get("financial_currency") or "USD"
            cquarterly = custom_result.get("quarterly") or {}
            chas_numbers = any([
                custom_result.get("total_revenue"),
                custom_result.get("net_income_ttm"),
                custom_result.get("op_income_ttm"),
                custom_result.get("ebitda"),
                cquarterly.get("q_revenue"),
            ])
            if chas_numbers:
                st.markdown("**💵 מספרים נטו:**")
                if custom_result.get("total_revenue") is not None:
                    st.write(f"- הכנסות (12 חודשים אחרונים): {fmt_big_money(custom_result['total_revenue'], cfc)}")
                if cquarterly.get("q_revenue") is not None:
                    q_date = cquarterly.get("q_date", "")
                    date_str = f" (לרבעון שהסתיים {q_date})" if q_date else ""
                    st.write(f"- הכנסות רבעון אחרון{date_str}: {fmt_big_money(cquarterly['q_revenue'], cfc)}")
                if custom_result.get("op_income_ttm") is not None:
                    st.write(f"- רווח תפעולי (TTM): {fmt_big_money(custom_result['op_income_ttm'], cfc)}")
                if cquarterly.get("q_operating_income") is not None:
                    st.write(f"- רווח תפעולי רבעון אחרון: {fmt_big_money(cquarterly['q_operating_income'], cfc)}")
                if custom_result.get("net_income_ttm") is not None:
                    st.write(f"- רווח נקי (TTM): {fmt_big_money(custom_result['net_income_ttm'], cfc)}")
                if cquarterly.get("q_net_income") is not None:
                    st.write(f"- רווח נקי רבעון אחרון: {fmt_big_money(cquarterly['q_net_income'], cfc)}")
                if custom_result.get("ebitda") is not None:
                    st.write(f"- EBITDA (TTM): {fmt_big_money(custom_result['ebitda'], cfc)}")

            # === תחזיות אנליסטים ===
            ctarget_mean = custom_result.get("target_mean_price")
            if ctarget_mean is not None:
                st.markdown("**🎯 תחזיות אנליסטים (12 חודשים)** *— דעות חיצוניות, לא ייעוץ:*")
                ccur_price = custom_result.get("price") or 0
                cupside = ((ctarget_mean - ccur_price) / ccur_price * 100) if ccur_price else None
                cupside_str = f"  ({cupside:+.1f}% מהמחיר הנוכחי)" if cupside is not None else ""
                st.write(f"- יעד מחיר ממוצע: {fmt_price(ctarget_mean, cs, custom_result.get('currency',''))}{cupside_str}")
                if custom_result.get("target_low_price") and custom_result.get("target_high_price"):
                    low_p = fmt_price(custom_result['target_low_price'], cs, custom_result.get('currency',''))
                    high_p = fmt_price(custom_result['target_high_price'], cs, custom_result.get('currency',''))
                    st.write(f"- טווח אנליסטים: {low_p} – {high_p}")
                if custom_result.get("num_analysts"):
                    st.write(f"- מספר אנליסטים בכיסוי: {custom_result['num_analysts']}")
                if custom_result.get("recommendation_key"):
                    st.write(f"- המלצה כוללת: **{fmt_recommendation(custom_result['recommendation_key'])}**")

            cmgmt = custom_result.get("management") or {}
            if cmgmt.get("ceo") or cmgmt.get("cfo"):
                st.markdown("**👥 הנהלה:**")
                if cmgmt.get("ceo"):
                    ceo = cmgmt["ceo"]
                    age_str = f", בן {ceo['age']}" if ceo.get("age") else ""
                    st.write(f"- CEO: {ceo['name']} ({ceo.get('title', '')}{age_str})")
                if cmgmt.get("cfo"):
                    cfo = cmgmt["cfo"]
                    age_str = f", בן {cfo['age']}" if cfo.get("age") else ""
                    st.write(f"- CFO: {cfo['name']} ({cfo.get('title', '')}{age_str})")

            if custom_result.get("news"):
                st.markdown("**📰 חדשות אחרונות:**")
                for n in custom_result["news"]:
                    _, sentiment_emoji = label_sentiment(n["title"])
                    meta = ""
                    if n.get("source") or n.get("published"):
                        meta = f" — *{n.get('source', '')}* {n.get('published', '')}"
                    if n.get("link"):
                        st.markdown(f"- {sentiment_emoji} [{n['title']}]({n['link']}){meta}")
                    else:
                        st.markdown(f"- {sentiment_emoji} {n['title']}{meta}")

            if custom_result.get("ai_insight"):
                st.markdown("**🤖 AI Insight** *(GPT-4o-mini — תיאורי, לא ייעוץ)*")
                ai_text = custom_result["ai_insight"]
                if ai_text.startswith("_"):
                    st.warning(ai_text.strip("_"))
                else:
                    st.info(ai_text)
            elif not effective_openai_key:
                st.caption("💡 להפעלת AI Insight למניה הזאת — הזן מפתח OpenAI בסרגל הצד.")

    # --- CSV Download ---
    st.divider()
    if HISTORY_CSV.exists():
        with open(HISTORY_CSV, "rb") as f:
            st.download_button(
                "⬇️ הורדת history.csv",
                data=f.read(),
                file_name="history.csv",
                mime="text/csv",
            )
else:
    st.info("לחץ על **🚀 Run Discovery** כדי להתחיל סריקה. הפעולה תיקח 3-5 דקות.")
