# 📊 Discovery Agent — Automated Stock Scanner

Scan 47 US & Israeli stocks with weighted financial scoring. Get a ranked **Top 10** with real-time metrics, news, management info, and optional AI analysis via GPT-4o-mini.

**Live Demo:** [Streamlit Cloud Link]

---

## 🎯 Features

✅ **Automatic Financial Scoring**
- Growth score (EPS growth, revenue growth)
- Profitability score (operating margin, ROE)
- Valuation score (P/E ratio)
- Adjustable weights (customize your criteria)

✅ **Real-Time Data**
- Stock prices, P/E ratios, market caps from yfinance (free)
- Latest headlines from NewsAPI (optional)
- CEO/CFO info & earnings dates
- 30-day candlestick charts

✅ **Optional AI Analysis**
- GPT-4o-mini generates 2-section Hebrew analysis
- Technical momentum breakdown
- Forward P/E analysis
- Cost: ~$0.001-0.002 per scan

✅ **Free-Form Search**
- Analyze any stock symbol
- Same detailed breakdown as Top 10

✅ **Export & History**
- Download results as CSV
- Track historical scans

⚠️ **Disclaimer:** This is automated analysis, **NOT investment advice**. Use for research only.

---

## 🚀 Quick Start

### Option 1: Try Online (Recommended)
1. Go to [Streamlit Cloud Link]
2. Provide your own API keys (see below)
3. Click **🚀 Run Discovery**
4. Wait 3-5 minutes for results

### Option 2: Run Locally

```bash
# Clone repo
git clone https://github.com/Amitos11/STOCKBOT.git
cd STOCKBOT

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run app
streamlit run app_public.py
```

Then open `http://localhost:8501` in your browser.

---

## 🔑 API Keys (Optional but Recommended)

This app works **without** API keys — it uses free data from yfinance. However, for full features:

### 📰 NewsAPI Key (Free)
Get headlines for each stock.

1. Go to [newsapi.org](https://newsapi.org)
2. Sign up (free tier: 100 requests/day)
3. Copy your API key
4. Paste in sidebar → **NewsAPI Key** field

### 🤖 OpenAI API Key
Enable AI-powered financial analysis.

1. Go to [platform.openai.com](https://platform.openai.com)
2. Sign up or log in
3. Create API key under [Settings → API Keys](https://platform.openai.com/account/api-keys)
4. Add credit to account ($5-20 recommended for testing)
5. Paste in sidebar → **OpenAI API Key** field

**Cost:** ~$0.001-0.002 per scan (40+ stocks × $0.00005 per 1K tokens)

---

## 📊 Scoring System

Each stock gets a **weighted score (0-100)** based on:

| Factor | Weight | What It Measures |
|--------|--------|------------------|
| **Growth** | 33% | EPS growth (YoY) + Revenue growth (YoY) |
| **Profitability** | 33% | Operating margin + ROE (return on equity) |
| **Valuation** | 34% | P/E ratio (lower = better score) |

**How to adjust:**
1. Use sliders in sidebar (left panel)
2. Ensure weights sum to 100
3. Click **🚀 Run Discovery** to recalculate

---

## 📋 Watchlist (47 Stocks)

### US Tech & Growth (30)
AAPL, MSFT, NVDA, TSLA, META, GOOGL, AMZN, NFLX, ADBE, PYPL, INTC, AMD, QCOM, CSCO, CRM, ORCL, IBM, AVGO, MCHP, INTU, ASML, LRCX, MRVL, CDNS, SNPS, TTM, KLAC, NXPI, TXN, AMAT

### Israeli & International (17)
TEVA, POLI, ICL, EQNR.TA, BEZQ.TA, SHIL.TA, TASE, CMPR, CYBE.TA, NICE, *(+7 more)*

**Want to customize?** Edit `TICKERS` list in `app_public.py`.

---

## 🔐 Security & Privacy

✅ **Your API keys are safe:**
- Keys are entered in the **session** (not saved to code)
- Never committed to GitHub
- Deleted when you close the browser
- `.gitignore` protects secrets folder

✅ **No personal data:**
- No email scraping
- No authentication required
- No tracking cookies
- Open source (audit it yourself!)

---

## 🌐 Deploy to Streamlit Cloud (5 minutes)

### Step 1: Push to GitHub
```bash
git add .
git commit -m "Prepare for Streamlit Cloud"
git push origin main
```

### Step 2: Deploy
1. Go to [share.streamlit.io](https://share.streamlit.io)
2. Click **Create app**
3. Choose:
   - **GitHub repo:** Amitos11/STOCKBOT
   - **Branch:** main
   - **Main file path:** app_public.py
4. Click **Deploy**
5. Wait 2-3 minutes ⏳

### Step 3: Share Public Link
Your app is now live! Share on Twitter, LinkedIn, or send to friends.

---

## 📱 Share on Twitter 🐦

### Example Post:
```
🎯 Automated Stock Discovery Tool

Scan 47 US & Israeli stocks with weighted financial scoring.
Real-time rankings, AI analysis (optional), free & open source.

Try it: [your-streamlit-cloud-link]

#stocks #investing #fintech #python
```

### What to Screenshot:
1. **Top 10 table** (impressive green metrics!)
2. **Candlestick chart** (visual appeal)
3. **Free-form search in action** (interactive demo)

---

## ⚙️ How It Works

### 1. Fetch Data (yfinance)
- Stock price, P/E ratio, market cap
- Earnings growth, revenue growth
- Operating margin, ROE, debt/equity
- Earnings date, management info

### 2. Score & Rank
- Apply weighted scoring to each stock
- Calculate Top 10

### 3. Enrich Top 10
- Fetch latest news (NewsAPI)
- Get CEO/CFO names
- Pull 30-day price history

### 4. Optional: AI Analysis
- Send stock data + news to GPT-4o-mini
- Generate 2-section Hebrew analysis:
  - Technical momentum
  - Forward P/E outlook

### 5. Display Results
- Show ranked table, charts, detailed breakdowns
- Allow free-form stock search

---

## 📊 Metrics Explained

| Metric | Good | Neutral | Bad |
|--------|------|---------|-----|
| **EPS YoY** | >20% | 5-20% | <5% |
| **Revenue YoY** | >15% | 5-15% | <5% |
| **Op Margin** | >25% | 15-25% | <15% |
| **ROE** | >15% | 10-15% | <10% |
| **P/E** | <15 | 15-25 | >25 |
| **D/E** | <0.5 | 0.5-1.0 | >1.0 |

---

## 🐛 Troubleshooting

### "No price data" error
- Stock ticker may be incorrect (check yfinance)
- Stock may be delisted or not available in yfinance

### NewsAPI headlines not showing
- Entered wrong key? Double-check at [newsapi.org](https://newsapi.org)
- Free tier limit (100/day) exceeded? Wait for reset

### AI Insight error
- Wrong OpenAI key? Verify at [platform.openai.com](https://platform.openai.com)
- No credit? Add $5-20 to your account
- Cost overrun? Check usage at [platform.openai.com/account/usage](https://platform.openai.com/account/usage)

### Streamlit Cloud slow?
- First scan: ~5 min (initial data fetch)
- Subsequent runs: ~3-4 min (yfinance caching)
- Normal behavior; be patient! ⏳

---

## 📈 Example Output

**Top 1 Result:**
```
🟢 #1 — NVDA • Information Technology • Score 89/100

NVIDIA Corporation
💰 $875.43 | P/E 45.2 | $2.8T

💡 Insight: Earnings +45% YoY • Revenue +125% YoY • Op Margin 55% — clear pricing power

📊 Metrics:
- EPS YoY: +45.2%
- Revenue YoY: +125.0%
- Operating Margin: 55.2%
- ROE: 85.0%

👥 Management:
- CEO: Jensen Huang, age 61
- CFO: Colette Kress, age 62

📰 Latest News:
🟢 NVIDIA Q4 2024 Earnings Beat Estimates — CNBC
🟢 AI Chip Demand Surges as ChatGPT Usage Grows — Reuters

🤖 AI Insight:
📈 ניתוח טכני / מומנטום:
מחיר ה-NVIDIA עלה בתנופה עלייתית בחודש האחרון...

📊 הערכת שווי קדימה:
ה-Forward P/E של NVIDIA נמוך מ-Trailing P/E...
```

---

## 🔧 Advanced: Customize the App

### Change watchlist
Edit `TICKERS` in `app_public.py`:
```python
TICKERS = [
    "YOUR_STOCK1", "YOUR_STOCK2", ...
]
```

### Adjust default weights
```python
DEFAULT_WEIGHT_GROWTH = 40  # Was 33
DEFAULT_WEIGHT_PROFITABILITY = 35  # Was 33
DEFAULT_WEIGHT_VALUATION = 25  # Was 34
```

### Change score thresholds
Find `score_valuation()` function and modify P/E breakpoints.

---

## 📄 License

MIT License — Use freely, modify as needed, attribute if possible.

---

## 🤝 Contributing

Found a bug? Want to add features?

1. Fork repo
2. Create branch: `git checkout -b feature/my-idea`
3. Make changes
4. Push & open pull request

Ideas:
- More countries/sectors
- Fundamental vs technical scoring
- Backtesting historical scores
- Email/Slack notifications

---

## 📞 Support

**Issues?**
- Check [Troubleshooting](#-troubleshooting) section
- Search [GitHub Issues](https://github.com/Amitos11/STOCKBOT/issues)
- Open new issue with details

**Feature requests?**
- Open GitHub discussion or issue
- Include use case & priority

---

## 📚 Learn More

- **yfinance:** [pypi.org/project/yfinance](https://pypi.org/project/yfinance/)
- **Streamlit:** [streamlit.io](https://streamlit.io)
- **OpenAI API:** [platform.openai.com/docs](https://platform.openai.com/docs)
- **NewsAPI:** [newsapi.org/docs](https://newsapi.org/docs)

---

## ⭐ If You Like This Project

- Star the repo ⭐
- Share with others 🔗
- Give feedback via issues 💬

---

**Happy investing! 🚀📊**

*Reminder: This tool is for research/education only. Always do your own due diligence before investing.*
