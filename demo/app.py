import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import yfinance as yf
from fredapi import Fred
import feedparser
import google.generativeai as genai
from urllib.parse import quote
import re
from datetime import datetime, timedelta

# 1. 頁面基本設定
st.set_page_config(page_title="美日利差、匯率與 AI 情緒決策儀表板", layout="wide", page_icon="💴")
st.title("💴 美日利差、USD/JPY 匯率與 AI 輿論情緒決策儀表板")
st.caption("整合 FRED 總經殖利率、yfinance 即時匯率與 Gemini NLP 市場背離偵測系統")

# 2. 側邊欄：安全讀取 Secrets 金鑰與狀態區
st.sidebar.header("⚙️ 設定與金鑰")
fred_key = st.secrets["FRED_API_KEY"] if "FRED_API_KEY" in st.secrets else st.sidebar.text_input("請輸入 FRED API Key:", type="password")

gemini_key = None
if "GEMINI_API_KEY" in st.secrets:
    gemini_key = st.secrets["GEMINI_API_KEY"]
    genai.configure(api_key=gemini_key)
else:
    gemini_input = st.sidebar.text_input("請輸入 Gemini API Key:", type="password")
    if gemini_input:
        gemini_key = gemini_input
        genai.configure(api_key=gemini_key)

st.sidebar.divider()
st.sidebar.subheader("📡 系統自動判讀狀態")
sidebar_alert_placeholder = st.sidebar.empty()
sidebar_alert_placeholder.info("尚未執行 AI 情緒分析，請點擊右側按鈕啟動背離偵測。")

# 3. 數據抓取函式庫 (加入快取提升載入速度)
@st.cache_data(ttl=3600)
def fetch_usdjpy_data():
    """抓取近 60 天 USD/JPY 匯率以計算精準的 30 個交易日漲跌幅"""
    ticker = yf.Ticker("JPY=X")
    df = ticker.history(period="60d")
    if df.empty:
        return None, 0.0, 0.0
    
    # 取最近 30 筆資料作為觀察區間
    df_30 = df.tail(30).copy()
    current_price = df_30['Close'].iloc[-1]
    start_price = df_30['Close'].iloc[0]
    pct_change_30d = ((current_price - start_price) / start_price) * 100
    return df_30, current_price, pct_change_30d

@st.cache_data(ttl=3600)
def fetch_yield_spread(api_key):
    """從 FRED 抓取美日 10 年期公債殖利率並計算利差"""
    if not api_key:
        return None, None, None
    try:
        fred = Fred(api_key=api_key)
        # DGS10: 美國10年期公債殖利率 (日頻率)
        us_10y = fred.get_series('DGS10').dropna()
        # IRLTLT01JPM156N: 日本10年期公債殖利率 (月頻率)
        jp_10y = fred.get_series('IRLTLT01JPM156N').dropna()
        
        latest_us = us_10y.iloc[-1]
        latest_jp = jp_10y.iloc[-1]
        spread = latest_us - latest_jp
        
        # 整理近一年利差走勢圖資料
        df_us = us_10y.tail(250).rename("US 10Y")
        df_jp = jp_10y.reindex(df_us.index, method='ffill').rename("JP 10Y")
        df_spread = pd.concat([df_us, df_jp], axis=1).dropna()
        df_spread['Spread (美日利差)'] = df_spread['US 10Y'] - df_spread['JP 10Y']
        return df_spread, latest_us, latest_jp
    except Exception as e:
        st.sidebar.error(f"FRED 讀取失敗: {e}")
        return None, None, None

@st.cache_data(ttl=1800)
def fetch_google_news(keyword="USD JPY Bank of Japan Fed"):
    safe_keyword = quote(keyword)
    url = f"https://news.google.com/rss/search?q={safe_keyword}&hl=en-US&gl=US&ceid=US:en"
    feed = feedparser.parse(url)
    return [entry.title for entry in feed.entries[:8]]

# 4. 載入市場與總經數據
df_fx, fx_now, fx_chg_30d = fetch_usdjpy_data()
df_spread, us_yield, jp_yield = fetch_yield_spread(fred_key)

# 5. 第一區塊：總經利差與匯率核心指標看板
st.subheader("📊 總體經濟利差與匯率即時監控")
m1, m2, m3, m4 = st.columns(4)

with m1:
    st.metric(
        label="USD/JPY 即時匯率 (30日漲跌)",
        value=f"{fx_now:.2f} 円" if fx_now else "讀取失敗",
        delta=f"{fx_chg_30d:+.2f}% (30D)",
        delta_color="normal" # 數字上升代表美元升值/日圓貶值
    )

with m2:
    if us_yield is not None and jp_yield is not None:
        spread_val = us_yield - jp_yield
        st.metric(label="美日 10Y 公債利差", value=f"{spread_val:.2f}%", delta=f"美 {us_yield:.2f}% / 日 {jp_yield:.2f}%", delta_color="off")
    else:
        st.metric(label="美日 10Y 公債利差", value="需輸入 FRED Key", delta="請於左側欄設定", delta_color="off")

with m3:
    # 預留給 AI 情緒分數的動態佔位符
    ai_score_metric = st.empty()
    ai_score_metric.metric(label="今日 AI 美元/利差情緒分數", value="待分析", delta="點擊下方按鈕啟動", delta_color="off")

with m4:
    # 預留給市場背離狀態的動態佔位符
    divergence_metric = st.empty()
    divergence_metric.metric(label="市場與輿論背離狀態", value="監控中", delta="等待 AI 評分", delta_color="off")

# 6. 第二區塊：雙軸走勢視覺化圖表
chart_col1, chart_col2 = st.columns(2)

with chart_col1:
    if df_fx is not None:
        fig_fx = px.line(
            df_fx, x=df_fx.index, y="Close",
            title="📈 USD/JPY 近 30 個交易日走勢圖",
            labels={"Close": "匯
