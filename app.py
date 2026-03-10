import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
from datetime import datetime, timedelta

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Stock Analysis Dashboard",
    page_icon="📈",
    layout="wide",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .main { background-color: #0e1117; }
    .metric-card {
        background: #1c1f26;
        border-radius: 10px;
        padding: 16px 20px;
        border: 1px solid #2d3139;
        margin-bottom: 8px;
    }
    .metric-label { color: #8b949e; font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }
    .metric-value { color: #e6edf3; font-size: 24px; font-weight: 700; margin-top: 4px; }
    .metric-delta-pos { color: #3fb950; font-size: 13px; }
    .metric-delta-neg { color: #f85149; font-size: 13px; }
    .section-title { color: #e6edf3; font-size: 18px; font-weight: 700; margin: 24px 0 12px; border-bottom: 1px solid #2d3139; padding-bottom: 8px; }
    .company-name { color: #e6edf3; font-size: 32px; font-weight: 800; }
    .ticker-badge { background: #1f6feb; color: white; padding: 4px 12px; border-radius: 20px; font-size: 14px; font-weight: 600; display: inline-block; margin-left: 10px; }
    .tag { background: #21262d; color: #8b949e; padding: 3px 10px; border-radius: 12px; font-size: 12px; margin-right: 6px; display: inline-block; }
    .stAlert { background: #1c1f26; border: 1px solid #2d3139; }
    div[data-testid="stMetric"] { background: #1c1f26; border-radius: 10px; padding: 12px 16px; border: 1px solid #2d3139; }
</style>
""", unsafe_allow_html=True)

# ── Helper functions ──────────────────────────────────────────────────────────

def safe_get(obj, *keys, default="N/A", fmt=None):
    """Safely extract nested values from a dict."""
    val = obj
    for key in keys:
        if isinstance(val, dict):
            val = val.get(key, None)
        else:
            return default
        if val is None:
            return default
    if fmt and val != default:
        try:
            return fmt(val)
        except:
            return default
    return val

def fmt_large(n):
    """Format large numbers into readable B/M/K strings."""
    if n is None or n == "N/A":
        return "N/A"
    try:
        n = float(n)
        if abs(n) >= 1e12: return f"${n/1e12:.2f}T"
        if abs(n) >= 1e9:  return f"${n/1e9:.2f}B"
        if abs(n) >= 1e6:  return f"${n/1e6:.2f}M"
        return f"${n:,.0f}"
    except:
        return "N/A"

def fmt_pct(n):
    """Format as percentage."""
    if n is None or n == "N/A":
        return "N/A"
    try:
        return f"{float(n)*100:.1f}%"
    except:
        return "N/A"

def fmt_ratio(n, decimals=2):
    """Format as ratio."""
    if n is None or n == "N/A":
        return "N/A"
    try:
        return f"{float(n):.{decimals}f}x"
    except:
        return "N/A"

@st.cache_data(ttl=300)
def load_ticker(ticker: str):
    """Load all yfinance data for a ticker (cached 5 min)."""
    t = yf.Ticker(ticker)
    info = t.info
    hist_1y  = t.history(period="1y")
    hist_5y  = t.history(period="5y")
    financials = t.financials          # annual income statement
    balance    = t.balance_sheet
    cashflow   = t.cashflow
    return info, hist_1y, hist_5y, financials, balance, cashflow

def simple_dcf(info):
    """
    Simple 5-year DCF:
      - Uses Free Cash Flow (Operating CF - CapEx) as base
      - Projects with estimated growth rate
      - Discounts at WACC approximation
      - Terminal value via perpetuity growth model
    """
    try:
        fcf         = info.get("freeCashflow")
        growth_rate = info.get("earningsGrowth") or 0.10
        shares      = info.get("sharesOutstanding")
        beta        = info.get("beta") or 1.0
        price       = info.get("currentPrice")

        if not all([fcf, shares, price]):
            return None

        # Cap growth rate for realism
        growth_rate = min(max(growth_rate, 0.02), 0.30)
        wacc        = 0.04 + beta * 0.05          # risk-free + beta * equity premium
        terminal_g  = 0.025                        # long-run terminal growth

        # Project 5 years of FCF
        projected = []
        cf = fcf
        for yr in range(1, 6):
            cf = cf * (1 + growth_rate)
            pv = cf / ((1 + wacc) ** yr)
            projected.append({"Year": f"Year {yr}", "FCF ($M)": cf / 1e6, "PV ($M)": pv / 1e6})

        # Terminal value
        terminal_fcf = projected[-1]["FCF ($M)"] * 1e6 * (1 + terminal_g)
        terminal_val = terminal_fcf / (wacc - terminal_g)
        terminal_pv  = terminal_val / ((1 + wacc) ** 5)

        total_equity_value = sum(p["PV ($M)"] for p in projected) * 1e6 + terminal_pv
        intrinsic_price    = total_equity_value / shares

        return {
            "projected":        projected,
            "terminal_pv":      terminal_pv / 1e6,
            "total_equity":     total_equity_value / 1e9,
            "intrinsic_price":  intrinsic_price,
            "current_price":    price,
            "upside":           (intrinsic_price - price) / price,
            "wacc":             wacc,
            "growth_rate":      growth_rate,
        }
    except Exception as e:
        return None

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 📈 Stock Analyzer")
    st.markdown("---")
    ticker_input = st.text_input("Enter Ticker Symbol", value="AAPL", max_chars=10).upper().strip()
    period       = st.selectbox("Chart Period", ["1y", "5y"], index=0)
    chart_type   = st.selectbox("Chart Type", ["Candlestick", "Line"], index=0)
    show_ma      = st.checkbox("Show Moving Averages (20d / 50d)", value=True)
    st.markdown("---")
    st.markdown("##### About")
    st.markdown("Built with Python, yfinance, Plotly & Streamlit. Pulls live market data and computes ratios, trends, and a DCF valuation model.")
    st.markdown("---")
    st.caption("Data via Yahoo Finance. Not financial advice.")

# ── Load data ─────────────────────────────────────────────────────────────────
if not ticker_input:
    st.warning("Enter a ticker in the sidebar to get started.")
    st.stop()

with st.spinner(f"Loading data for {ticker_input}..."):
    try:
        info, hist_1y, hist_5y, financials, balance, cashflow = load_ticker(ticker_input)
    except Exception as e:
        st.error(f"Could not load data for **{ticker_input}**. Check the ticker and try again.")
        st.stop()

if not info or info.get("regularMarketPrice") is None and info.get("currentPrice") is None:
    st.error(f"No data found for **{ticker_input}**. Make sure it's a valid ticker symbol.")
    st.stop()

hist = hist_1y if period == "1y" else hist_5y

# ── Company Header ─────────────────────────────────────────────────────────────
name     = info.get("longName", ticker_input)
sector   = info.get("sector", "")
industry = info.get("industry", "")
exchange = info.get("exchange", "")
price    = info.get("currentPrice") or info.get("regularMarketPrice", 0)
prev     = info.get("previousClose", price)
change   = price - prev
change_p = (change / prev * 100) if prev else 0
color    = "#3fb950" if change >= 0 else "#f85149"
arrow    = "▲" if change >= 0 else "▼"

st.markdown(f"""
<div style="margin-bottom: 4px">
    <span class="company-name">{name}</span>
    <span class="ticker-badge">{ticker_input}</span>
</div>
<div style="margin-bottom: 16px">
    <span class="tag">{exchange}</span>
    <span class="tag">{sector}</span>
    <span class="tag">{industry}</span>
</div>
<div style="font-size: 38px; font-weight: 800; color: #e6edf3; margin-bottom: 4px">
    ${price:,.2f}
    <span style="font-size: 20px; color: {color}; margin-left: 10px">{arrow} {abs(change):.2f} ({abs(change_p):.2f}%) today</span>
</div>
""", unsafe_allow_html=True)

st.markdown("---")

# ── Key Metrics Row ───────────────────────────────────────────────────────────
st.markdown('<div class="section-title">Key Metrics</div>', unsafe_allow_html=True)

col1, col2, col3, col4, col5, col6, col7 = st.columns(7)
metrics = [
    ("Market Cap",    fmt_large(info.get("marketCap"))),
    ("P/E Ratio",     fmt_ratio(info.get("trailingPE"))),
    ("Fwd P/E",       fmt_ratio(info.get("forwardPE"))),
    ("EV/EBITDA",     fmt_ratio(info.get("enterpriseToEbitda"))),
    ("P/B Ratio",     fmt_ratio(info.get("priceToBook"))),
    ("P/S Ratio",     fmt_ratio(info.get("priceToSalesTrailing12Months"))),
    ("52W High",      f"${info.get('fiftyTwoWeekHigh', 'N/A'):,.2f}" if info.get('fiftyTwoWeekHigh') else "N/A"),
]
for col, (label, val) in zip([col1,col2,col3,col4,col5,col6,col7], metrics):
    col.metric(label, val)

col1, col2, col3, col4, col5, col6, col7 = st.columns(7)
metrics2 = [
    ("Revenue (TTM)", fmt_large(info.get("totalRevenue"))),
    ("Gross Margin",  fmt_pct(info.get("grossMargins"))),
    ("Op. Margin",    fmt_pct(info.get("operatingMargins"))),
    ("Net Margin",    fmt_pct(info.get("profitMargins"))),
    ("ROE",           fmt_pct(info.get("returnOnEquity"))),
    ("ROA",           fmt_pct(info.get("returnOnAssets"))),
    ("Debt/Equity",   fmt_ratio(info.get("debtToEquity"), 1) if info.get("debtToEquity") else "N/A"),
]
for col, (label, val) in zip([col1,col2,col3,col4,col5,col6,col7], metrics2):
    col.metric(label, val)

st.markdown("---")

# ── Price Chart ───────────────────────────────────────────────────────────────
st.markdown('<div class="section-title">Price Chart</div>', unsafe_allow_html=True)

fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                    vertical_spacing=0.03,
                    row_heights=[0.75, 0.25])

if chart_type == "Candlestick":
    fig.add_trace(go.Candlestick(
        x=hist.index, open=hist["Open"], high=hist["High"],
        low=hist["Low"], close=hist["Close"],
        name="Price",
        increasing_line_color="#3fb950", decreasing_line_color="#f85149"
    ), row=1, col=1)
else:
    fig.add_trace(go.Scatter(
        x=hist.index, y=hist["Close"],
        line=dict(color="#1f6feb", width=2), name="Close Price",
        fill="tozeroy", fillcolor="rgba(31,111,235,0.08)"
    ), row=1, col=1)

if show_ma and len(hist) >= 20:
    ma20 = hist["Close"].rolling(20).mean()
    ma50 = hist["Close"].rolling(50).mean()
    fig.add_trace(go.Scatter(x=hist.index, y=ma20, line=dict(color="#e3b341", width=1.2, dash="dot"), name="20d MA"), row=1, col=1)
    if len(hist) >= 50:
        fig.add_trace(go.Scatter(x=hist.index, y=ma50, line=dict(color="#bc8cff", width=1.2, dash="dot"), name="50d MA"), row=1, col=1)

fig.add_trace(go.Bar(
    x=hist.index, y=hist["Volume"],
    marker_color=["#3fb950" if c >= o else "#f85149" for c, o in zip(hist["Close"], hist["Open"])],
    name="Volume", opacity=0.6
), row=2, col=1)

fig.update_layout(
    template="plotly_dark", height=520,
    plot_bgcolor="#0e1117", paper_bgcolor="#0e1117",
    margin=dict(l=0, r=0, t=10, b=0),
    legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0),
    xaxis_rangeslider_visible=False,
)
fig.update_xaxes(showgrid=False)
fig.update_yaxes(showgrid=True, gridcolor="#2d3139", gridwidth=0.5)
st.plotly_chart(fig, use_container_width=True)

st.markdown("---")

# ── Financials Charts ─────────────────────────────────────────────────────────
st.markdown('<div class="section-title">Financial Performance</div>', unsafe_allow_html=True)

c1, c2 = st.columns(2)

# Revenue & Net Income trend
with c1:
    try:
        rev_row = financials.loc["Total Revenue"] if "Total Revenue" in financials.index else None
        inc_row = financials.loc["Net Income"]    if "Net Income"    in financials.index else None

        if rev_row is not None and inc_row is not None:
            years   = [str(d.year) for d in rev_row.index[::-1]]
            rev_vals = (rev_row.values[::-1] / 1e9).tolist()
            inc_vals = (inc_row.values[::-1] / 1e9).tolist()

            fig2 = go.Figure()
            fig2.add_trace(go.Bar(x=years, y=rev_vals, name="Revenue ($B)", marker_color="#1f6feb", opacity=0.85))
            fig2.add_trace(go.Bar(x=years, y=inc_vals, name="Net Income ($B)", marker_color="#3fb950", opacity=0.85))
            fig2.update_layout(
                template="plotly_dark", barmode="group", height=300,
                plot_bgcolor="#0e1117", paper_bgcolor="#0e1117",
                title=dict(text="Revenue vs. Net Income (Annual)", font=dict(size=14)),
                margin=dict(l=0, r=0, t=40, b=0),
                legend=dict(orientation="h", yanchor="bottom", y=1.01),
            )
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("Revenue/Net Income data not available.")
    except Exception:
        st.info("Financial statement data unavailable.")

# Margin trend
with c2:
    try:
        if rev_row is not None and inc_row is not None:
            gross_row = financials.loc["Gross Profit"] if "Gross Profit" in financials.index else None
            op_row    = financials.loc["Operating Income"] if "Operating Income" in financials.index else None

            fig3 = go.Figure()
            if gross_row is not None:
                gm = [(g / r * 100) for g, r in zip(gross_row.values[::-1], rev_row.values[::-1])]
                fig3.add_trace(go.Scatter(x=years, y=gm, mode="lines+markers", name="Gross Margin %", line=dict(color="#1f6feb", width=2)))
            if op_row is not None:
                om = [(o / r * 100) for o, r in zip(op_row.values[::-1], rev_row.values[::-1])]
                fig3.add_trace(go.Scatter(x=years, y=om, mode="lines+markers", name="Op. Margin %", line=dict(color="#e3b341", width=2)))
            nm = [(i / r * 100) for i, r in zip(inc_row.values[::-1], rev_row.values[::-1])]
            fig3.add_trace(go.Scatter(x=years, y=nm, mode="lines+markers", name="Net Margin %", line=dict(color="#3fb950", width=2)))

            fig3.update_layout(
                template="plotly_dark", height=300,
                plot_bgcolor="#0e1117", paper_bgcolor="#0e1117",
                title=dict(text="Margin Trends (%)", font=dict(size=14)),
                margin=dict(l=0, r=0, t=40, b=0),
                legend=dict(orientation="h", yanchor="bottom", y=1.01),
            )
            st.plotly_chart(fig3, use_container_width=True)
        else:
            st.info("Margin data not available.")
    except Exception:
        st.info("Margin data unavailable.")

st.markdown("---")

# ── DCF Valuation ─────────────────────────────────────────────────────────────
st.markdown('<div class="section-title">DCF Valuation Model</div>', unsafe_allow_html=True)

dcf = simple_dcf(info)

if dcf:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Intrinsic Value (DCF)", f"${dcf['intrinsic_price']:,.2f}")
    col2.metric("Current Price",         f"${dcf['current_price']:,.2f}")
    upside_str = f"{dcf['upside']*100:+.1f}%"
    col3.metric("Implied Upside/Downside", upside_str, delta=upside_str)
    col4.metric("Total Equity Value",    f"{dcf['total_equity']:.2f}B")

    col5, col6 = st.columns(2)
    col5.metric("WACC Used",        f"{dcf['wacc']*100:.1f}%")
    col6.metric("Growth Rate Used", f"{dcf['growth_rate']*100:.1f}%")

    df_proj = pd.DataFrame(dcf["projected"])
    df_proj["FCF ($M)"] = df_proj["FCF ($M)"].map(lambda x: f"${x:,.1f}M")
    df_proj["PV ($M)"]  = df_proj["PV ($M)"].map(lambda x: f"${x:,.1f}M")
    df_proj = pd.concat([
        df_proj,
        pd.DataFrame([{"Year": "Terminal Value (PV)", "FCF ($M)": "—", "PV ($M)": f"${dcf['terminal_pv']:,.1f}M"}])
    ], ignore_index=True)

    st.dataframe(df_proj.set_index("Year"), use_container_width=True)
    st.caption("⚠️ DCF is based on trailing FCF and consensus growth estimates. Use as one input among many — not a buy/sell signal.")
else:
    st.info("DCF model requires Free Cash Flow data. Not all tickers support this (e.g. banks, ETFs).")

st.markdown("---")

# ── Analyst Info ──────────────────────────────────────────────────────────────
st.markdown('<div class="section-title">Analyst Consensus</div>', unsafe_allow_html=True)

col1, col2, col3, col4 = st.columns(4)
col1.metric("Analyst Rating",    info.get("recommendationKey", "N/A").upper())
col2.metric("Target Price",      f"${info.get('targetMeanPrice', 'N/A'):,.2f}" if info.get("targetMeanPrice") else "N/A")
col3.metric("Target Low",        f"${info.get('targetLowPrice', 'N/A'):,.2f}"  if info.get("targetLowPrice")  else "N/A")
col4.metric("Target High",       f"${info.get('targetHighPrice', 'N/A'):,.2f}" if info.get("targetHighPrice") else "N/A")

st.markdown("---")
st.caption(f"Last updated: {datetime.now().strftime('%b %d, %Y %H:%M')}  •  Data via Yahoo Finance  •  Built by Dhruv Patel")
