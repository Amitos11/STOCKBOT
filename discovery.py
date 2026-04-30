"""
Discovery Agent v3 — Deep Financial Scanner
=============================================
סורק רחב של מניות אמריקאיות וישראליות, מחשב ציון משוקלל
(צמיחה 40% + רווחיות 30% + תמחור 30%), ומפיק Top 10 מנותח.

הרצה:
    pip install yfinance         # פעם אחת
    python discovery.py          # סריקה

משתני סביבה (PowerShell):
    $env:GMAIL_USER, $env:GMAIL_APP_PASSWORD
    $env:TELEGRAM_BOT_TOKEN, $env:TELEGRAM_CHAT_ID
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
import yfinance as yf

# ============================================================
# CONFIG
# ============================================================

# פרטי גישה (מוגדרים כמשתני סביבה)
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
# NewsAPI (אופציונלי). אם מוגדר — מחליף את yfinance.news לכותרות איכותיות יותר.
# מוטב להגדיר כ-env var. הערך כברירת מחדל הוא לנוחות בלבד.
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "4328fe6014ea4ec9b2e638f1c6489c1c")

# רשימת סריקה — כ-75 מניות במגוון סקטורים וגדלים
TICKERS = [
    # Mega-caps (US)
    "NVDA", "AAPL", "MSFT", "GOOG", "META", "AMZN", "TSLA", "AVGO", "ORCL", "NFLX",
    # Semis & hardware
    "AMD", "MU", "QCOM", "INTC", "SMCI", "AMAT", "LRCX", "MRVL", "ASML",
    # Software / Cloud
    "PLTR", "CRWD", "NET", "DDOG", "SNOW", "MDB", "ZS", "OKTA", "S", "ESTC",
    # Healthcare / Biotech
    "JNJ", "UNH", "MRK", "ABBV", "LLY", "ISRG", "REGN", "VRTX",
    # Consumer / Retail
    "COST", "WMT", "HD", "LULU", "ULTA", "ELF", "CMG",
    # Financials
    "JPM", "V", "MA", "BAC", "GS", "HOOD", "SOFI", "COIN",
    # Industrials / Energy
    "LMT", "RTX", "GE", "CAT", "XOM", "CVX",
    # Israeli on NASDAQ
    "TEVA", "CHKP", "NICE", "MNDY", "WIX", "MBLY", "GLBE", "ESLT",
    "CYBR", "INMD", "NVMI", "AUDC", "GILT",
    # TASE-only
    "POLI.TA", "LUMI.TA", "DSCT.TA", "MZTF.TA", "FIBI.TA",
    "ICL.TA", "AZRG.TA",
]

# משקלי הציון (סך הכל 100)
WEIGHT_GROWTH = 40
WEIGHT_PROFITABILITY = 30
WEIGHT_VALUATION = 30

OUTPUT_DIR = Path(__file__).resolve().parent
HISTORY_CSV = OUTPUT_DIR / "history.csv"


# ============================================================
# UTILITIES
# ============================================================

def safe_float(v):
    """החזרה של float או None — מטפל גם ב-NaN וב-None."""
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


def fmt_num(val, decimals=2):
    f = safe_float(val)
    if f is None:
        return "N/A"
    return f"{f:.{decimals}f}"


def fmt_market_cap(mkt_cap, symbol):
    """תיקון מטבע ויחידות לשווי שוק. מניות .TA → ₪ + שווי ערך בדולרים."""
    f = safe_float(mkt_cap)
    if f is None:
        return "N/A"
    if symbol.endswith(".TA"):
        # yfinance מחזיר את ה-marketCap לתל אביב בשקלים
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
    """מחיר עם סימן מטבע. מניות .TA במחיר אגורות → ממירים לשקלים."""
    f = safe_float(price)
    if f is None:
        return "N/A"
    if symbol.endswith(".TA") or currency == "ILA":
        return f"₪{f / 100:.2f}"
    if currency == "ILS":
        return f"₪{f:.2f}"
    return f"${f:.2f}"


# ============================================================
# DATA FETCHING
# ============================================================

def fetch_deep(symbol):
    """משוך נתונים מעמיקים על מניה אחת."""
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
    row["market_cap"] = safe_float(info.get("marketCap"))
    row["market_cap_display"] = fmt_market_cap(row["market_cap"], symbol)

    # תמחור
    row["pe_ratio"] = safe_float(info.get("trailingPE"))
    row["forward_pe"] = safe_float(info.get("forwardPE"))
    row["peg_ratio"] = safe_float(info.get("pegRatio"))

    # צמיחה (yfinance מחזיר עשרוני: 0.25 = 25%)
    row["earnings_growth"] = safe_float(info.get("earningsQuarterlyGrowth"))
    row["revenue_growth"] = safe_float(info.get("revenueGrowth"))

    # רווחיות
    row["operating_margin"] = safe_float(info.get("operatingMargins"))
    row["profit_margin"] = safe_float(info.get("profitMargins"))
    row["roe"] = safe_float(info.get("returnOnEquity"))

    # יציבות פיננסית
    row["debt_to_equity"] = safe_float(info.get("debtToEquity"))
    row["current_ratio"] = safe_float(info.get("currentRatio"))

    # מומנטום
    row["day_change"] = safe_float(info.get("regularMarketChangePercent"))
    row["fifty_two_week_high"] = safe_float(info.get("fiftyTwoWeekHigh"))
    row["fifty_two_week_low"] = safe_float(info.get("fiftyTwoWeekLow"))

    # תאריך דוח הבא
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
    """fallback: כותרות מ-yfinance (פחות איכותיות, אבל בלי API key)."""
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
    """משוך n כותרות מ-NewsAPI לפי שאילתה. מחזיר רשימת dicts."""
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
    """כותרות למניה — מעדיף NewsAPI, נופל ל-yfinance אם אין מפתח או אין תוצאות."""
    if NEWSAPI_KEY:
        # שאילתה לפי שם החברה (יותר ייחודי מהסימול)
        clean_name = (name or "").replace(",", "").replace(".", "").strip()
        if clean_name:
            query = f'"{clean_name}"'
        else:
            query = symbol.replace(".TA", "")
        articles = fetch_newsapi(query, n=n)
        if articles:
            return articles
    return fetch_news_yfinance(symbol, n=n)


def fetch_macro_headlines():
    """כותרות מאקרו: מוניטרי + גיאופוליטי. שתי קריאות נפרדות לכיסוי טוב."""
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


def fetch_management(symbol):
    """משוך CEO ו-CFO מתוך companyOfficers. yfinance לא חושף ותק מדויק,
    רק שם/תפקיד/גיל/שכר. החזרה: dict עם שני מפתחות, או None."""
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
            "total_pay": o.get("totalPay"),
        }
        if not ceo and ("ceo" in title or "chief executive" in title):
            ceo = rec
        elif not cfo and ("cfo" in title or "chief financial" in title):
            cfo = rec
    return {"ceo": ceo, "cfo": cfo}


# ============================================================
# SCORING
# ============================================================

def score_growth(row):
    """ציון צמיחה (0 עד WEIGHT_GROWTH)."""
    eps = row.get("earnings_growth")
    rev = row.get("revenue_growth")
    eps_norm = max(0, min(1, eps / 0.5)) if eps is not None else None  # 50% = max
    rev_norm = max(0, min(1, rev / 0.3)) if rev is not None else None  # 30% = max
    available = [s for s in (eps_norm, rev_norm) if s is not None]
    if not available:
        return 0
    return (sum(available) / len(available)) * WEIGHT_GROWTH


def score_profitability(row):
    """ציון רווחיות (0 עד WEIGHT_PROFITABILITY)."""
    om = row.get("operating_margin")
    roe = row.get("roe")
    om_norm = max(0, min(1, om / 0.25)) if om is not None else None  # 25% = max
    roe_norm = max(0, min(1, roe / 0.25)) if roe is not None else None  # 25% = max
    available = [s for s in (om_norm, roe_norm) if s is not None]
    if not available:
        return 0
    return (sum(available) / len(available)) * WEIGHT_PROFITABILITY


def score_valuation(row):
    """ציון תמחור לפי P/E (0 עד WEIGHT_VALUATION). P/E נמוך = ציון גבוה."""
    pe = row.get("pe_ratio")
    if pe is None or pe <= 0:
        return 0
    # פונקצית הירידה: P/E עד 10 = מקס; דעיכה לינארית עד P/E 40; אחרי זה כמעט אפס.
    if pe <= 10:
        norm = 1.0
    elif pe <= 20:
        norm = 1.0 - (pe - 10) * 0.05  # 1.0 → 0.5
    elif pe <= 40:
        norm = 0.5 - (pe - 20) * 0.0225  # 0.5 → 0.05
    else:
        norm = max(0, 0.05 - (pe - 40) * 0.001)
    return norm * WEIGHT_VALUATION


def composite_score(row):
    return score_growth(row) + score_profitability(row) + score_valuation(row)


def has_min_data(row):
    """דורש לפחות P/E ולפחות מדד צמיחה אחד."""
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
    """תובנה קצרה (עד 3 פיסות) על המניה, בעברית."""
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
# OUTPUT BUILDERS
# ============================================================

def build_console_table(top10):
    lines = []
    header = (
        f"{'#':<3}{'Symbol':<10}{'Sector':<22}{'Score':>7}"
        f"{'P/E':>7}{'EPS':>9}{'Rev':>9}{'OM':>7}{'Mkt Cap':>18}"
    )
    lines.append(header)
    lines.append("-" * len(header))
    for i, row in enumerate(top10, 1):
        sector = (row.get("sector") or "")[:20]
        lines.append(
            f"{i:<3}{row['symbol']:<10}{sector:<22}"
            f"{row.get('score', 0):>6.1f}"
            f"{fmt_num(row.get('pe_ratio'), 1):>7}"
            f"{fmt_pct(row.get('earnings_growth'), 0):>9}"
            f"{fmt_pct(row.get('revenue_growth'), 0):>9}"
            f"{fmt_pct(row.get('operating_margin'), 0):>7}"
            f"{(row.get('market_cap_display') or 'N/A'):>18}"
        )
    return "\n".join(lines)


def _fmt_management_line(mgmt):
    """שורת הנהלה קצרה לתצוגה. None = ללא מידע."""
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
    """הודעת טלגרם נפרדת לכותרות מאקרו (כדי לא לחרוג ממגבלת 4096 תווים)."""
    if not macro or (not macro.get("monetary") and not macro.get("geopolitical")):
        return ""
    lines = ["🌍 כותרות מאקרו עולמיות"]
    if macro.get("monetary"):
        lines.append("\n💵 מוניטרי / כלכלה:")
        for a in macro["monetary"]:
            src = f" ({a['source']})" if a.get("source") else ""
            date = f" {a['published']}" if a.get("published") else ""
            lines.append(f"  • {a['title'][:120]}{src}{date}")
    if macro.get("geopolitical"):
        lines.append("\n🌐 גיאופוליטי:")
        for a in macro["geopolitical"]:
            src = f" ({a['source']})" if a.get("source") else ""
            date = f" {a['published']}" if a.get("published") else ""
            lines.append(f"  • {a['title'][:120]}{src}{date}")
    return "\n".join(lines)


def _build_management_html(mgmt):
    """HTML קצר עם CEO/CFO לתוך תא הטבלה."""
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
    """סקציית כותרות מאקרו לתחתית המייל."""
    if not macro or (not macro.get("monetary") and not macro.get("geopolitical")):
        return ""

    def headlines_block(label, articles):
        if not articles:
            return ""
        items = ""
        for a in articles:
            title = html_lib.escape(a["title"][:140])
            link = html_lib.escape(a.get("link", ""))
            src = html_lib.escape(a.get("source", ""))
            date = html_lib.escape(a.get("published", ""))
            meta = f' <span style="color:#999; font-size:11px">— {src} {date}</span>' if src else ""
            if link:
                items += f'<li><a href="{link}" style="color:#3b82f6; text-decoration:none">{title}</a>{meta}</li>'
            else:
                items += f"<li>{title}{meta}</li>"
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
            title = html_lib.escape(n["title"][:90])
            link = html_lib.escape(n["link"])
            if link:
                news_items += f'<li><a href="{link}" style="color:#3b82f6; text-decoration:none">{title}</a></li>'
            else:
                news_items += f"<li>{title}</li>"
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
    <body style="font-family: Arial, 'Segoe UI', sans-serif; max-width:920px; margin:24px auto; color:#222; background:#f9fafb">
      <div style="background:white; padding:24px; border-radius:8px; box-shadow:0 1px 3px rgba(0,0,0,0.05)">
        <h1 style="border-bottom: 3px solid #3b82f6; padding-bottom:8px; margin-top:0">📊 דוח גילוי מניות — {today}</h1>
        <p style="color:#444; font-size:14px">
          סרקנו <b>{len(all_valid)}</b> מניות מתוך {len(TICKERS)} ברשימה.
          ציון ממוצע: <b>{avg_score:.1f}</b>.<br>
          <span style="color:#666; font-size:12px">
            ציון = צמיחה ({WEIGHT_GROWTH}%) + רווחיות ({WEIGHT_PROFITABILITY}%) + תמחור ({WEIGHT_VALUATION}%)
          </span>
        </p>
        <h2 style="color:#3b82f6; margin-top:24px">🎯 Top 10</h2>
        <table style="width:100%; border-collapse:collapse; font-size:13px">
          {rows_html}
        </table>
        {_build_macro_html(macro)}
        <p style="color:#999; font-size:11px; margin-top:24px; border-top:1px solid #e5e7eb; padding-top:12px">
          ⚠️ ניתוח אוטומטי המבוסס על נתוני yfinance ו-NewsAPI. אינו מהווה ייעוץ השקעות —
          הנתונים והכותרות מוצגים כדי שתוכל לקבל החלטות מושכלות בעצמך.
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
        print("[email] פרטי מייל חסרים, מדלג על שליחה.")
        return
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
        print(f"[email] המייל נשלח בהצלחה ל-{GMAIL_USER}!")
    except Exception as e:
        print(f"[email] שגיאה בשליחה: {e}")


def send_telegram(content):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[telegram] פרטי טלגרם חסרים, מדלג על שליחה.")
        return
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
            print("[telegram] ההודעה נשלחה בהצלחה!")
        else:
            print(f"[telegram] שגיאה: {result.get('description', 'לא ידועה')}")
    except Exception as e:
        print(f"[telegram] שליחה נכשלה: {e}")


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
# MAIN
# ============================================================

def main():
    started = datetime.now()
    print(f"\n📊 Discovery Scan — {started.strftime('%Y-%m-%d %H:%M')}")
    print(f"סורק {len(TICKERS)} מניות (יקח 3-5 דקות)...\n")

    rows = []
    for i, symbol in enumerate(TICKERS, 1):
        print(f"  [{i:>3}/{len(TICKERS)}] {symbol:<10}", end="", flush=True)
        row = fetch_deep(symbol)
        rows.append(row)
        print(f"  {row.get('error', 'ok')}")

    valid = [r for r in rows if has_min_data(r)]
    print(f"\nסיכום: {len(valid)} מניות עם נתונים תקינים מתוך {len(rows)}")

    if not valid:
        print("לא נמצאו מניות עם נתונים מספיקים. בדוק חיבור לרשת או רשימת ה-TICKERS.")
        save_history(rows)
        return

    for row in valid:
        row["score_growth"] = score_growth(row)
        row["score_profitability"] = score_profitability(row)
        row["score_valuation"] = score_valuation(row)
        row["score"] = composite_score(row)

    valid.sort(key=lambda r: r["score"], reverse=True)
    top10 = valid[:10]

    print("\nמעשיר את ה-Top 10 בחדשות והנהלה...")
    for row in top10:
        row["news"] = fetch_news_for_stock(row["symbol"], row.get("name", ""), n=2)
        row["management"] = fetch_management(row["symbol"])
        row["insight"] = generate_insight(row)
        # שטוח את שמות ההנהלה לתוך השורה לטובת CSV
        mgmt = row.get("management") or {}
        row["ceo_name"] = (mgmt.get("ceo") or {}).get("name", "")
        row["cfo_name"] = (mgmt.get("cfo") or {}).get("name", "")

    print("מביא כותרות מאקרו עולמיות...")
    macro = fetch_macro_headlines()

    print("\n=== Top 10 ===")
    print(build_console_table(top10))

    save_history(rows)
    print(f"\nנשמר ל-{HISTORY_CSV.name}")

    subject = f"📊 דוח גילוי - Top 10 - {started.strftime('%d/%m/%Y')}"
    send_email(subject, build_html_email(top10, valid, macro))
    send_telegram(build_telegram_message(top10))
    # מאקרו כהודעה נפרדת בטלגרם (לא לחרוג ממגבלת 4096 תווים)
    macro_msg = build_macro_telegram_message(macro)
    if macro_msg:
        send_telegram(macro_msg)

    elapsed = (datetime.now() - started).total_seconds()
    print(f"\n✓ הסתיים תוך {elapsed:.0f} שניות.")


if __name__ == "__main__":
    main()
