"""
Discovery Agent — Stock Scanner & Analyzer
For Streamlit Community Cloud (public deployment)

Features:
- Scan 47 US & Israeli stocks with weighted scoring
- Automatic extraction of financial metrics from yfinance
- NewsAPI integration (user-provided key, optional)
- OpenAI AI analysis (user-provided key, optional)
- HTML email export & CSV history

⚠️ Disclaimer: This is automated analysis, NOT investment advice.
"""

import csv
import datetime
import html as html_lib
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

# ============================================================
# CONFIGURATION
# ============================================================

TICKERS = [
    "AAPL", "MSFT", "NVDA", "TSLA", "META", "GOOGL", "AMZN", "NFLX", "ADBE", "PYPL",
    "INTC", "AMD", "QCOM", "CSCO", "CRM", "ORCL", "IBM", "AVGO", "MCHP", "INTU",
    "ASML", "LRCX", "MRVL", "CDNS", "SNPS", "TTM", "KLAC", "NXPI", "TXN", "AMAT",
    "TEVA", "POLI", "ICL", "EQNR.TA", "BEZQ.TA", "SHIL.TA", "TASE", "CMPR", "CYBE.TA", "NICE",
]

DEFAULT_WEIGHT_GROWTH = 33
DEFAULT_WEIGHT_PROFITABILITY = 33
DEFAULT_WEIGHT_VALUATION = 34

HISTORY_CSV = Path("stock_history.csv")

# ============================================================
# LOAD SECRETS (Streamlit Cloud safe)
# ============================================================

# For LOCAL dev: set these in .streamlit/secrets.toml
# For STREAMLIT CLOUD: set these in Settings → Secrets
NEWSAPI_KEY = st.secrets.get("newsapi_key", "")
OPENAI_API_KEY = st.secrets.get("openai_api_key", "")

# ============================================================
# FORMATTING HELPERS
# ============================================================

def safe_float(val):
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None


def fmt_price(price, symbol="", currency=""):
    if price is None:
        return "N/A"
    curr = currency or ("₪" if ".TA" in symbol else "$")
    return f"{curr}{price:.2f}"


def fmt_pct(val):
    if val is None:
        return "—"
    return f"{val * 100:+.1f}%"


def fmt_num(val, decimals=0):
    if val is None:
        return "—"
    return f"{val:.{decimals}f}"


def fmt_market_cap(mc, symbol):
    if not mc:
        return "—"
    if mc >= 1e12:
        return f"${mc / 1e12:.1f}T"
    elif mc >= 1e9:
        return f"${mc / 1e9:.1f}B"
    elif mc >= 1e6:
        return f"${mc / 1e6:.1f}M"
    return f"${mc:.0f}"


def fmt_day_pct(val):
    """Daily % change with colored dot. val is already in % (1.23 = 1.23%)."""
    f = safe_float(val)
    if f is None:
        return "—"
    emoji = "🟢" if f >= 0 else "🔴"
    sign = "+" if f >= 0 else ""
    return f"{emoji} {sign}{f:.2f}%"


def fmt_day_pct_color(val):
    """Same as fmt_day_pct but with Streamlit :green[]/:red[] color tags."""
    f = safe_float(val)
    if f is None:
        return ""
    color = "green" if f >= 0 else "red"
    arrow = "▲" if f >= 0 else "▼"
    sign = "+" if f >= 0 else ""
    return f":{color}[{arrow} {sign}{f:.2f}%]"


def fmt_big_money(value, currency="USD"):
    """Format large dollar/shekel numbers — $1.5B, ₪50M, etc."""
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


def label_sentiment(text):
    """Naive keyword-based sentiment (not AI)"""
    text_lower = (text or "").lower()
    positive = ["surge", "jump", "rally", "beat", "gain", "profit", "growth", "strong"]
    negative = ["crash", "drop", "fall", "miss", "loss", "decline", "weak", "slump"]
    pos_count = sum(1 for w in positive if w in text_lower)
    neg_count = sum(1 for w in negative if w in text_lower)
    if pos_count > neg_count:
        return "positive", "🟢"
    elif neg_count > pos_count:
        return "negative", "🔴"
    return "neutral", "⚪"


# ============================================================
# DATA FETCHING
# ============================================================

def fetch_deep(symbol):
    """Fetch comprehensive stock data from yfinance"""
    row = {"symbol": symbol}
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

    # === Financial numbers (TTM) ===
    row["financial_currency"] = info.get("financialCurrency") or info.get("currency") or "USD"
    row["total_revenue"] = safe_float(info.get("totalRevenue"))
    row["gross_profits"] = safe_float(info.get("grossProfits"))
    row["ebitda"] = safe_float(info.get("ebitda"))
    row["net_income_ttm"] = safe_float(info.get("netIncomeToCommon"))
    _om = safe_float(info.get("operatingMargins"))
    _tr = safe_float(info.get("totalRevenue"))
    row["op_income_ttm"] = (_om * _tr) if (_om is not None and _tr is not None) else None

    # === Analyst forecasts (12-month) — external opinions, not advice ===
    row["target_mean_price"] = safe_float(info.get("targetMeanPrice"))
    row["target_high_price"] = safe_float(info.get("targetHighPrice"))
    row["target_low_price"] = safe_float(info.get("targetLowPrice"))
    row["num_analysts"] = info.get("numberOfAnalystOpinions")
    row["recommendation_key"] = info.get("recommendationKey", "")
    row["recommendation_mean"] = safe_float(info.get("recommendationMean"))

    # === Daily % change — computed for accuracy ===
    # Using ((current - prev_close) / prev_close) * 100 to avoid yfinance's
    # inconsistent regularMarketChangePercent units across versions.
    prev_close = safe_float(info.get("regularMarketPreviousClose")) or safe_float(info.get("previousClose"))
    if prev_close and prev_close > 0 and price:
        row["day_change"] = (price - prev_close) / prev_close * 100
    else:
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
    """Fallback news source (free, no key needed)"""
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
    """Fetch from NewsAPI (user-provided key)"""
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
    """Try NewsAPI first, fallback to yfinance"""
    if NEWSAPI_KEY:
        clean_name = (name or "").replace(",", "").replace(".", "").strip()
        query = f'"{clean_name}"' if clean_name else symbol.replace(".TA", "")
        articles = fetch_newsapi(query, n=n)
        if articles:
            return articles
    return fetch_news_yfinance(symbol, n=n)


def fetch_macro_headlines():
    """Fetch macro news if NewsAPI key available"""
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
    """Fetch latest quarter: revenue, operating income, net income.
    Extra yfinance call; used only for Top 10 enrichment + custom analysis."""
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
    """30-day price summary for AI context"""
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="1mo")
        if hist.empty:
            return ""
        closes = [float(c) for c in hist["Close"].tolist() if c == c]
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
    """Send to GPT-4o-mini for analysis (user-provided key)"""
    if not api_key:
        return None, "No OpenAI API key provided"

    try:
        from openai import OpenAI
    except ImportError:
        return None, "Install: pip install openai"

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
            "You are a financial data analyst writing concise stock analyses.\n"
            "Output MUST use this EXACT three-section structure with the emoji headers:\n\n"
            "📈 Technical / Momentum:\n"
            "<2 sentences describing the 30-day price trend (upward/downward/sideways), "
            "approximate range, where current price sits within that range, and momentum "
            "direction. Use observational language only — describe what the data SHOWS.>\n\n"
            "📊 Forward Valuation:\n"
            "<2 sentences comparing Trailing P/E to Forward P/E. If Forward < Trailing, "
            "explain analysts expect earnings growth (so the company looks 'cheaper' on a "
            "forward basis). If Forward > Trailing, the opposite. If similar, note stability. "
            "Connect to news context if relevant.>\n\n"
            "🔥 Hot Themes / Growth Drivers:\n"
            "<2 sentences identifying sector tailwinds or industry trends the company is "
            "currently positioned within (e.g., 'AI infrastructure demand', 'energy "
            "transition', 'aging population', 'cloud migration'). Describe POSITIONING, "
            "not predictions. If no obvious trends, write 'No notable sector tailwinds "
            "beyond core business'.>\n\n"
            "STRICT RULES — VIOLATIONS WILL BREAK THE OUTPUT:\n"
            "- NEVER use 'buy', 'sell', 'should', 'recommend', 'target price'\n"
            "- NEVER call price levels 'entry zones', 'exit zones', 'support to buy at', "
            "'resistance to sell at'\n"
            "- NEVER predict future prices or specific revenue numbers\n"
            "- Use observational/descriptive language only ('the data shows', "
            "'the trend has been', 'the company is positioned in', 'metrics suggest')\n"
            "- Maximum 2 sentences per section\n"
            "- English output\n"
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
        return None, f"Error: {str(e)[:120]}"


def fetch_management(symbol):
    """Extract CEO/CFO info"""
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
# SCORING
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
        parts.append(f"Earnings +{eps * 100:.0f}% YoY")
    elif eps is not None and eps > 0.2:
        parts.append(f"Stable earnings growth ({eps * 100:.0f}%)")

    if rev is not None and rev > 0.3:
        parts.append(f"Revenue +{rev * 100:.0f}% YoY")
    elif rev is not None and rev > 0.15:
        parts.append(f"Growing revenue ({rev * 100:.0f}%)")

    if om is not None and om > 0.30:
        parts.append(f"High op margin ({om * 100:.0f}%) — pricing power")
    elif om is not None and om > 0.20:
        parts.append(f"Solid profitability ({om * 100:.0f}%)")

    if pe is not None and 0 < pe < 12:
        parts.append(f"Low P/E ({pe:.1f}) — modest valuation")
    elif pe is not None and 0 < pe < 20:
        parts.append(f"Fair P/E ({pe:.1f})")

    if de is not None and de < 50:
        parts.append("Clean balance sheet")

    if not parts:
        parts.append("Balanced profile")

    return " • ".join(parts[:3])


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
    """Scan all tickers with weighted scoring"""
    w_g, w_p, w_v = weights

    rows = []
    n = len(TICKERS)
    for i, symbol in enumerate(TICKERS, 1):
        if progress_callback:
            progress_callback(i, n, f"Scanning {symbol} ({i}/{n})")
        rows.append(fetch_deep(symbol))

    valid = [r for r in rows if has_min_data(r)]
    for row in valid:
        row["score_growth"] = score_growth(row, w_g)
        row["score_profitability"] = score_profitability(row, w_p)
        row["score_valuation"] = score_valuation(row, w_v)
        row["score"] = row["score_growth"] + row["score_profitability"] + row["score_valuation"]

    valid.sort(key=lambda r: r["score"], reverse=True)
    top10 = valid[:10]

    for row in valid:
        row["insight"] = generate_insight(row)

    if progress_callback:
        progress_callback(n, n, "Enriching Top 10 with news & management...")
    for row in top10:
        row["news"] = fetch_news_for_stock(row["symbol"], row.get("name", ""), n=2)
        row["management"] = fetch_management(row["symbol"])
        row["price_history_summary"] = _fetch_price_history_summary(row["symbol"])
        row["quarterly"] = _fetch_quarterly_financials(row["symbol"])
        mgmt = row.get("management") or {}
        row["ceo_name"] = (mgmt.get("ceo") or {}).get("name", "")
        row["cfo_name"] = (mgmt.get("cfo") or {}).get("name", "")

    if progress_callback:
        progress_callback(n, n, "Fetching macro headlines...")
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
    """Analyze a single stock (for free-form search)"""
    if not symbol:
        return {"symbol": "", "error": "No symbol entered"}

    symbol = symbol.strip().upper()
    w_g, w_p, w_v = weights

    row = fetch_deep(symbol)
    if row.get("error"):
        return row

    row["score_growth"] = score_growth(row, w_g)
    row["score_profitability"] = score_profitability(row, w_p)
    row["score_valuation"] = score_valuation(row, w_v)
    row["score"] = row["score_growth"] + row["score_profitability"] + row["score_valuation"]

    row["insight"] = generate_insight(row)

    row["news"] = fetch_news_for_stock(row["symbol"], row.get("name", ""), n=2)
    row["management"] = fetch_management(row["symbol"])
    row["price_history_summary"] = _fetch_price_history_summary(row["symbol"])
    row["quarterly"] = _fetch_quarterly_financials(row["symbol"])
    mgmt = row.get("management") or {}
    row["ceo_name"] = (mgmt.get("ceo") or {}).get("name", "")
    row["cfo_name"] = (mgmt.get("cfo") or {}).get("name", "")

    if openai_key:
        ai_text, ai_err = get_ai_insights(row, row.get("news", []), openai_key)
        row["ai_insight"] = ai_text if ai_text else f"_Error: {ai_err}_"

    return row


# ============================================================
# STREAMLIT UI
# ============================================================

st.set_page_config(
    page_title="Discovery Agent",
    page_icon="📊",
    layout="wide",
)

st.markdown("""
<style>
    .stApp {
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Inter', sans-serif;
    }
    h1, h2, h3 {
        font-weight: 700 !important;
        letter-spacing: -0.015em;
    }
    h1 { font-size: 2.2em !important; }
    [data-testid="stMetricValue"] {
        font-size: 1.9em !important;
        font-weight: 700 !important;
    }
    [data-testid="stMetricLabel"] {
        font-weight: 500 !important;
        color: #475569 !important;
    }
    [data-testid="stSidebar"] {
        background-color: #f8fafc;
    }
    .stDataFrame thead tr th {
        background-color: #f1f5f9 !important;
        font-weight: 700 !important;
        color: #0f172a !important;
        text-transform: uppercase;
        font-size: 11px !important;
        letter-spacing: 0.05em;
        border-bottom: 2px solid #cbd5e1 !important;
    }
    div[data-testid="stExpander"] {
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        margin-bottom: 6px;
    }
</style>
""", unsafe_allow_html=True)

st.title("📊 Discovery Agent")
st.caption("Scan US & Israeli stocks, rank Top 10 by weighted score")

with st.sidebar:
    st.subheader("⚙️ Scoring Weights")
    st.caption("Adjust weights and click Run Discovery to recalculate.")

    w_growth = st.slider("📈 Growth (%)", 0, 100, DEFAULT_WEIGHT_GROWTH, key="w_growth")
    w_prof = st.slider("💰 Profitability (%)", 0, 100, DEFAULT_WEIGHT_PROFITABILITY, key="w_prof")
    w_val = st.slider("⚖️ Valuation (%)", 0, 100, DEFAULT_WEIGHT_VALUATION, key="w_val")

    total_w = w_growth + w_prof + w_val
    if total_w == 100:
        st.success(f"Total weights: {total_w} ✓")
    else:
        st.warning(f"Total weights: {total_w} (ideally 100)")

    st.divider()
    st.subheader("📋 Watchlist")
    st.write(f"**{len(TICKERS)}** stocks in scan")

    st.divider()
    st.subheader("🔌 API Status")
    st.write(f"📰 NewsAPI: {'✅ configured' if NEWSAPI_KEY else '⚠️ optional'}")
    st.write(f"🤖 OpenAI: {'✅ configured' if OPENAI_API_KEY else '⚠️ optional'}")
    st.caption("Provide keys below for enhanced features.")

    st.divider()
    st.subheader("🔑 API Keys (Optional)")
    st.caption(
        "Enter your own API keys below. They are NOT saved — session-only.\n\n"
        "- **NewsAPI**: Get headlines for each stock\n"
        "- **OpenAI**: Enable GPT-4o-mini analysis"
    )

    newsapi_input = st.text_input(
        "NewsAPI Key",
        type="password",
        value="",
        placeholder="news_xxxxx",
        key="newsapi_key_input",
        help="Get free key at newsapi.org",
    )
    effective_newsapi_key = newsapi_input or NEWSAPI_KEY

    openai_input = st.text_input(
        "OpenAI API Key",
        type="password",
        value="",
        placeholder="sk-...",
        key="openai_key_input",
        help="Get key at platform.openai.com",
    )
    effective_openai_key = openai_input or OPENAI_API_KEY

    if effective_openai_key:
        st.success("AI ready ✓")
    else:
        st.caption("No OpenAI key — AI analysis disabled")

    st.divider()
    st.caption("⚠️ Automated analysis only. NOT investment advice.")


if "results" not in st.session_state:
    st.session_state["results"] = None
    st.session_state["last_run"] = None
    st.session_state["ai_insights"] = {}
    st.session_state["last_custom_result"] = None

col_btn, col_meta = st.columns([1, 3])
with col_btn:
    run_clicked = st.button("🚀 Run Discovery", type="primary", use_container_width=True)
with col_meta:
    if st.session_state["last_run"]:
        st.caption(f"Last scan: {st.session_state['last_run']}")

if run_clicked:
    st.session_state["ai_insights"] = {}
    progress_bar = st.progress(0, text="Starting...")

    def update_progress(i, n, label):
        progress_bar.progress(min(i / n, 1.0), text=label)

    weights = (w_growth, w_prof, w_val)

    with st.spinner("Scanning (3-5 minutes)..."):
        # Override global NEWSAPI_KEY for this session
        import sys
        old_newsapi = globals()["NEWSAPI_KEY"]
        globals()["NEWSAPI_KEY"] = effective_newsapi_key

        results = run_full_discovery(weights=weights, progress_callback=update_progress)
        st.session_state["results"] = results
        st.session_state["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M")

        globals()["NEWSAPI_KEY"] = old_newsapi

    progress_bar.empty()


results = st.session_state.get("results")
if results:
    top10 = results["top10"]
    valid = results["valid"]
    macro = results["macro"]
    all_rows = results["all_rows"]

    avg_score = sum(r.get("score", 0) for r in valid) / max(1, len(valid))
    green_count = sum(1 for r in valid if r.get("score", 0) >= 60)
    yellow_count = sum(1 for r in valid if 40 <= r.get("score", 0) < 60)
    red_count = sum(1 for r in valid if r.get("score", 0) < 40)
    leader = top10[0] if top10 else None

    st.subheader("📊 Market Overview")
    mc = st.columns(5)
    with mc[0]:
        st.metric("Scanned", f"{len(valid)}/{len(all_rows)}")
    with mc[1]:
        st.metric("Avg Score", f"{avg_score:.1f}")
    with mc[2]:
        st.metric("🟢 Strong (60+)", green_count)
    with mc[3]:
        st.metric("🟡 Medium (40-60)", yellow_count)
    with mc[4]:
        if leader:
            st.metric("🏆 Leader", leader["symbol"], delta=f"{leader.get('score', 0):.0f}")

    st.divider()

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
                help="Weighted score 0-100",
                format="%.1f",
                min_value=0,
                max_value=100,
            ),
        },
    )

    st.divider()
    st.subheader("📈 Candlestick Chart — Last 30 Days")
    chart_options = {row["symbol"]: f"{row['symbol']} — {(row.get('name') or '')[:35]}" for row in top10}
    selected = st.selectbox(
        "Select stock from Top 10",
        options=list(chart_options.keys()),
        format_func=lambda s: chart_options[s],
        key="candlestick_select",
    )
    if selected:
        with st.spinner(f"Loading price data for {selected}..."):
            try:
                t = yf.Ticker(selected)
                hist = t.history(period="1mo")
                if hist.empty:
                    st.warning(f"No price data for {selected}")
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
                        title=f"{selected} — Last 30 days",
                        xaxis_rangeslider_visible=False,
                        height=440,
                        margin=dict(l=20, r=20, t=50, b=20),
                        template="plotly_white",
                        yaxis_title="Price",
                    )
                    st.plotly_chart(fig, use_container_width=True)
            except Exception as e:
                st.error(f"Chart error: {e}")

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
                st.caption(f"AI insights generated for {existing} stocks (expand to view)")
            else:
                st.caption("AI generates 2-section Hebrew analysis per stock. Cost: ~$0.001-0.002")

        if ai_clicked:
            ai_progress = st.progress(0, text="Analyzing...")
            new_insights = {}
            for idx, ai_row in enumerate(top10):
                ai_progress.progress(
                    (idx + 1) / len(top10),
                    text=f"AI analyzing {ai_row['symbol']} ({idx + 1}/{len(top10)})",
                )
                insight, err = get_ai_insights(
                    ai_row, ai_row.get("news", []), effective_openai_key
                )
                if insight:
                    new_insights[ai_row["symbol"]] = insight
                else:
                    new_insights[ai_row["symbol"]] = f"_Error: {err}_"
            st.session_state["ai_insights"] = new_insights
            ai_progress.empty()
            successful = sum(1 for v in new_insights.values() if not v.startswith("_"))
            st.success(
                f"AI generated insights for {successful}/{len(top10)} stocks. "
                "Expand sections below to view."
            )
            st.rerun()

    st.divider()
    st.subheader("🔎 Detailed Breakdown — Top 10")
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
                st.metric("Price", fmt_price(row["price"], row["symbol"], row.get("currency", "")))
                st.metric("P/E", fmt_num(row.get("pe_ratio"), 1))
                st.metric("Market Cap", row.get("market_cap_display", "N/A"))
                if row.get("next_earnings"):
                    st.write(f"📅 **Next Report:** {row['next_earnings']}")

            with c2:
                st.markdown(f"**💡 Insight:** {row.get('insight', '')}")

                st.markdown("**📊 Metrics:**")
                st.write(f"- EPS YoY: {fmt_pct(row.get('earnings_growth'))}")
                st.write(f"- Revenue YoY: {fmt_pct(row.get('revenue_growth'))}")
                st.write(f"- Operating Margin: {fmt_pct(row.get('operating_margin'))}")
                st.write(f"- ROE: {fmt_pct(row.get('roe'))}")
                if row.get("debt_to_equity") is not None:
                    st.write(f"- Debt/Equity: {fmt_num(row.get('debt_to_equity'), 0)}")

                # === Financial numbers (TTM + last quarter) ===
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
                    st.markdown("**💵 Financial Numbers:**")
                    if row.get("total_revenue") is not None:
                        st.write(f"- Revenue (TTM): {fmt_big_money(row['total_revenue'], fc)}")
                    if quarterly.get("q_revenue") is not None:
                        q_date = quarterly.get("q_date", "")
                        date_str = f" (quarter ending {q_date})" if q_date else ""
                        st.write(f"- Revenue last quarter{date_str}: {fmt_big_money(quarterly['q_revenue'], fc)}")
                    if row.get("op_income_ttm") is not None:
                        st.write(f"- Operating Income (TTM): {fmt_big_money(row['op_income_ttm'], fc)}")
                    if quarterly.get("q_operating_income") is not None:
                        st.write(f"- Operating Income last quarter: {fmt_big_money(quarterly['q_operating_income'], fc)}")
                    if row.get("net_income_ttm") is not None:
                        st.write(f"- Net Income (TTM): {fmt_big_money(row['net_income_ttm'], fc)}")
                    if quarterly.get("q_net_income") is not None:
                        st.write(f"- Net Income last quarter: {fmt_big_money(quarterly['q_net_income'], fc)}")
                    if row.get("ebitda") is not None:
                        st.write(f"- EBITDA (TTM): {fmt_big_money(row['ebitda'], fc)}")

                # === Analyst targets ===
                target_mean = row.get("target_mean_price")
                if target_mean is not None:
                    st.markdown("**🎯 Analyst Targets (12-month)** *— external opinions, not advice:*")
                    cur_price = row.get("price") or 0
                    upside = ((target_mean - cur_price) / cur_price * 100) if cur_price else None
                    upside_str = f"  ({upside:+.1f}% from current)" if upside is not None else ""
                    st.write(f"- Mean target: {fmt_price(target_mean, row['symbol'], row.get('currency',''))}{upside_str}")
                    if row.get("target_low_price") and row.get("target_high_price"):
                        low_p = fmt_price(row['target_low_price'], row['symbol'], row.get('currency',''))
                        high_p = fmt_price(row['target_high_price'], row['symbol'], row.get('currency',''))
                        st.write(f"- Range: {low_p} – {high_p}")
                    if row.get("num_analysts"):
                        st.write(f"- Analysts covering: {row['num_analysts']}")
                    if row.get("recommendation_key"):
                        st.write(f"- Consensus: **{fmt_recommendation(row['recommendation_key'])}**")

                mgmt = row.get("management") or {}
                if mgmt.get("ceo") or mgmt.get("cfo"):
                    st.markdown("**👥 Management:**")
                    if mgmt.get("ceo"):
                        ceo = mgmt["ceo"]
                        age_str = f", age {ceo['age']}" if ceo.get("age") else ""
                        st.write(f"- CEO: {ceo['name']}{age_str}")
                    if mgmt.get("cfo"):
                        cfo = mgmt["cfo"]
                        age_str = f", age {cfo['age']}" if cfo.get("age") else ""
                        st.write(f"- CFO: {cfo['name']}{age_str}")

                if row.get("news"):
                    st.markdown("**📰 Latest News** *(naive keyword-based sentiment)*:")
                    for n in row["news"]:
                        _, sentiment_emoji = label_sentiment(n["title"])
                        meta = ""
                        if n.get("source") or n.get("published"):
                            meta = f" — *{n.get('source', '')}* {n.get('published', '')}"
                        if n.get("link"):
                            st.markdown(f"- {sentiment_emoji} [{n['title']}]({n['link']}){meta}")
                        else:
                            st.markdown(f"- {sentiment_emoji} {n['title']}{meta}")

                ai_insight_text = st.session_state.get("ai_insights", {}).get(row["symbol"])
                if ai_insight_text:
                    st.markdown("**🤖 AI Insight** *(GPT-4o-mini — descriptive, not advice)*")
                    if ai_insight_text.startswith("_"):
                        st.warning(ai_insight_text.strip("_"))
                    else:
                        st.info(ai_insight_text)

    rest = valid[10:]
    if rest:
        st.divider()
        st.subheader(f"📚 All Other Stocks ({len(rest)})")
        st.caption("Basic metrics + auto-generated insight (no news/management for speed)")
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
                    st.metric("Price", fmt_price(row["price"], row["symbol"], row.get("currency", "")))
                    st.metric("P/E", fmt_num(row.get("pe_ratio"), 1))
                    st.metric("Market Cap", row.get("market_cap_display", "N/A"))
                    if row.get("next_earnings"):
                        st.write(f"📅 **Next Report:** {row['next_earnings']}")
                with c2:
                    st.markdown(f"**💡 Insight:** {row.get('insight', '')}")
                    st.markdown("**📊 Metrics:**")
                    st.write(f"- EPS YoY: {fmt_pct(row.get('earnings_growth'))}")
                    st.write(f"- Revenue YoY: {fmt_pct(row.get('revenue_growth'))}")
                    st.write(f"- Operating Margin: {fmt_pct(row.get('operating_margin'))}")
                    st.write(f"- ROE: {fmt_pct(row.get('roe'))}")
                    if row.get("debt_to_equity") is not None:
                        st.write(f"- Debt/Equity: {fmt_num(row.get('debt_to_equity'), 0)}")
                    if row.get("forward_pe") is not None:
                        st.write(f"- Forward P/E: {fmt_num(row.get('forward_pe'), 1)}")

                    # Lightweight TTM financials (no quarterly fetch for non-Top-10)
                    fc = row.get("financial_currency") or "USD"
                    if any([row.get("total_revenue"), row.get("net_income_ttm"), row.get("op_income_ttm")]):
                        st.markdown("**💵 Financial Numbers (TTM):**")
                        if row.get("total_revenue") is not None:
                            st.write(f"- Revenue: {fmt_big_money(row['total_revenue'], fc)}")
                        if row.get("op_income_ttm") is not None:
                            st.write(f"- Operating Income: {fmt_big_money(row['op_income_ttm'], fc)}")
                        if row.get("net_income_ttm") is not None:
                            st.write(f"- Net Income: {fmt_big_money(row['net_income_ttm'], fc)}")

                    target_mean = row.get("target_mean_price")
                    if target_mean is not None:
                        cur_price = row.get("price") or 0
                        upside = ((target_mean - cur_price) / cur_price * 100) if cur_price else None
                        upside_str = f"  ({upside:+.1f}%)" if upside is not None else ""
                        rec = fmt_recommendation(row.get("recommendation_key"))
                        n_an = row.get("num_analysts") or "?"
                        st.markdown(f"**🎯 Analyst target:** {fmt_price(target_mean, row['symbol'], row.get('currency',''))}{upside_str} • Consensus: {rec} • {n_an} analysts")

                    if row.get("industry"):
                        st.caption(f"Industry: {row['industry']}")

    st.divider()
    with st.expander(f"📋 Full Table — All {len(valid)} Scanned Stocks"):
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

    if macro and (macro.get("monetary") or macro.get("geopolitical")):
        st.divider()
        st.subheader("🌍 Global Macro Headlines")
        st.caption("With naive keyword-based sentiment classification")
        mc1, mc2 = st.columns(2)
        with mc1:
            st.markdown("### 💵 Monetary / Economics")
            for a in macro.get("monetary", []):
                _, emoji = label_sentiment(a["title"])
                meta = f" — *{a.get('source', '')}* {a.get('published', '')}"
                if a.get("link"):
                    st.markdown(f"- {emoji} [{a['title']}]({a['link']}){meta}")
                else:
                    st.markdown(f"- {emoji} {a['title']}{meta}")
        with mc2:
            st.markdown("### 🌐 Geopolitical")
            for a in macro.get("geopolitical", []):
                _, emoji = label_sentiment(a["title"])
                meta = f" — *{a.get('source', '')}* {a.get('published', '')}"
                if a.get("link"):
                    st.markdown(f"- {emoji} [{a['title']}]({a['link']}){meta}")
                else:
                    st.markdown(f"- {emoji} {a['title']}{meta}")

    st.divider()
    st.subheader("🔍 Free-Form Stock Analysis")
    st.caption(
        "Enter any ticker symbol to get the same analysis as Top 10 stocks — "
        "base data, weighted score, latest news, management, and AI insight (if OpenAI key provided)."
    )

    with st.form("custom_stock_form", clear_on_submit=False):
        col_input, col_btn = st.columns([3, 1])
        with col_input:
            custom_symbol_raw = st.text_input(
                "Stock Symbol",
                value="",
                placeholder="e.g. AAPL, NVDA, TEVA, POLI.TA",
                key="custom_symbol_input",
                label_visibility="collapsed",
            )
        with col_btn:
            custom_analyze = st.form_submit_button(
                "🔬 Analyze", type="primary", use_container_width=True
            )

    custom_symbol = (custom_symbol_raw or "").strip().upper()

    if custom_analyze and custom_symbol:
        with st.spinner(f"Analyzing {custom_symbol}..."):
            weights = (w_growth, w_prof, w_val)

            # Override NEWSAPI_KEY for this session
            old_newsapi = globals()["NEWSAPI_KEY"]
            globals()["NEWSAPI_KEY"] = effective_newsapi_key

            st.session_state["last_custom_result"] = analyze_single_stock(
                custom_symbol, weights, effective_openai_key
            )

            globals()["NEWSAPI_KEY"] = old_newsapi
    elif custom_analyze and not custom_symbol:
        st.warning("Enter a symbol before clicking Analyze")

    custom_result = st.session_state.get("last_custom_result")
    if custom_result:
        cs = custom_result.get("symbol", "?")
        if custom_result.get("error"):
            st.error(f"Cannot analyze {cs}: {custom_result['error']}")
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
                st.metric("Price", fmt_price(custom_result["price"], cs, custom_result.get("currency", "")))
            with c_cols[2]:
                st.metric("P/E", fmt_num(custom_result.get("pe_ratio"), 1))
            with c_cols[3]:
                st.metric("Market Cap", custom_result.get("market_cap_display", "N/A"))

            st.markdown(f"**💡 Insight:** {custom_result.get('insight', '')}")

            with st.expander("📊 All Metrics"):
                st.write(f"- EPS YoY: {fmt_pct(custom_result.get('earnings_growth'))}")
                st.write(f"- Revenue YoY: {fmt_pct(custom_result.get('revenue_growth'))}")
                st.write(f"- Operating Margin: {fmt_pct(custom_result.get('operating_margin'))}")
                st.write(f"- ROE: {fmt_pct(custom_result.get('roe'))}")
                if custom_result.get("debt_to_equity") is not None:
                    st.write(f"- Debt/Equity: {fmt_num(custom_result.get('debt_to_equity'), 0)}")
                if custom_result.get("forward_pe") is not None:
                    st.write(f"- Forward P/E: {fmt_num(custom_result.get('forward_pe'), 1)}")
                if custom_result.get("next_earnings"):
                    st.write(f"- 📅 Next Report: {custom_result['next_earnings']}")

            # === Financial numbers ===
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
                st.markdown("**💵 Financial Numbers:**")
                if custom_result.get("total_revenue") is not None:
                    st.write(f"- Revenue (TTM): {fmt_big_money(custom_result['total_revenue'], cfc)}")
                if cquarterly.get("q_revenue") is not None:
                    q_date = cquarterly.get("q_date", "")
                    date_str = f" (quarter ending {q_date})" if q_date else ""
                    st.write(f"- Revenue last quarter{date_str}: {fmt_big_money(cquarterly['q_revenue'], cfc)}")
                if custom_result.get("op_income_ttm") is not None:
                    st.write(f"- Operating Income (TTM): {fmt_big_money(custom_result['op_income_ttm'], cfc)}")
                if cquarterly.get("q_operating_income") is not None:
                    st.write(f"- Operating Income last quarter: {fmt_big_money(cquarterly['q_operating_income'], cfc)}")
                if custom_result.get("net_income_ttm") is not None:
                    st.write(f"- Net Income (TTM): {fmt_big_money(custom_result['net_income_ttm'], cfc)}")
                if cquarterly.get("q_net_income") is not None:
                    st.write(f"- Net Income last quarter: {fmt_big_money(cquarterly['q_net_income'], cfc)}")
                if custom_result.get("ebitda") is not None:
                    st.write(f"- EBITDA (TTM): {fmt_big_money(custom_result['ebitda'], cfc)}")

            # === Analyst targets ===
            ctarget_mean = custom_result.get("target_mean_price")
            if ctarget_mean is not None:
                st.markdown("**🎯 Analyst Targets (12-month)** *— external opinions, not advice:*")
                ccur_price = custom_result.get("price") or 0
                cupside = ((ctarget_mean - ccur_price) / ccur_price * 100) if ccur_price else None
                cupside_str = f"  ({cupside:+.1f}% from current)" if cupside is not None else ""
                st.write(f"- Mean target: {fmt_price(ctarget_mean, cs, custom_result.get('currency',''))}{cupside_str}")
                if custom_result.get("target_low_price") and custom_result.get("target_high_price"):
                    low_p = fmt_price(custom_result['target_low_price'], cs, custom_result.get('currency',''))
                    high_p = fmt_price(custom_result['target_high_price'], cs, custom_result.get('currency',''))
                    st.write(f"- Range: {low_p} – {high_p}")
                if custom_result.get("num_analysts"):
                    st.write(f"- Analysts covering: {custom_result['num_analysts']}")
                if custom_result.get("recommendation_key"):
                    st.write(f"- Consensus: **{fmt_recommendation(custom_result['recommendation_key'])}**")

            cmgmt = custom_result.get("management") or {}
            if cmgmt.get("ceo") or cmgmt.get("cfo"):
                st.markdown("**👥 Management:**")
                if cmgmt.get("ceo"):
                    ceo = cmgmt["ceo"]
                    age_str = f", age {ceo['age']}" if ceo.get("age") else ""
                    st.write(f"- CEO: {ceo['name']}{age_str}")
                if cmgmt.get("cfo"):
                    cfo = cmgmt["cfo"]
                    age_str = f", age {cfo['age']}" if cfo.get("age") else ""
                    st.write(f"- CFO: {cfo['name']}{age_str}")

            if custom_result.get("news"):
                st.markdown("**📰 Latest News:**")
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
                st.markdown("**🤖 AI Insight** *(GPT-4o-mini — descriptive, not advice)*")
                ai_text = custom_result["ai_insight"]
                if ai_text.startswith("_"):
                    st.warning(ai_text.strip("_"))
                else:
                    st.info(ai_text)
            elif not effective_openai_key:
                st.caption("💡 To enable AI analysis — enter an OpenAI key in the sidebar")

    st.divider()
    if HISTORY_CSV.exists():
        with open(HISTORY_CSV, "rb") as f:
            st.download_button(
                "⬇️ Download history.csv",
                data=f.read(),
                file_name="history.csv",
                mime="text/csv",
            )
else:
    st.info("Click **🚀 Run Discovery** to start scanning. Takes 3-5 minutes.")
