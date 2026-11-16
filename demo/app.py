import streamlit as st
import pandas as pd
import plotly.express as px
import yfinance as yf
from fredapi import Fred
import feedparser
from google import genai
from google.genai import types
from urllib.parse import quote
import re

# 1. 頁面基本設定
st.set_page_config(page_title="美日利差、匯率與 AI 情緒決策儀表板", layout="wide", page_icon="💴")
st.title("💴 美日利差、USD/JPY 匯率與 AI 輿論情緒決策儀表板")
st.caption("整合 FRED 總經殖利率、yfinance 即時匯率與 Gemini NLP 市場背離偵測系統")

# 2. 側邊欄：安全讀取 Secrets 金鑰
st.sidebar.header("⚙️ 設定與金鑰")
fred_key = st.secrets["FRED_API_KEY"] if "FRED_API_KEY" in st.secrets else st.sidebar.text_input("請輸入 FRED API Key:", type="password")

gemini_key = None
if "GEMINI_API_KEY" in st.secrets:
    gemini_key = st.secrets["GEMINI_API_KEY"]
else:
    gemini_input = st.sidebar.text_input("請輸入 Gemini API Key:", type="password")
    if gemini_input:
        gemini_key = gemini_input

st.sidebar.divider()
st.sidebar.subheader("📡 系統自動判讀狀態")
sidebar_alert_placeholder = st.sidebar.empty()
sidebar_alert_placeholder.info("尚未執行 AI 情緒分析，請至第 2 分頁啟動。")

# 3. 數據抓取函式庫 (長時間快取，避免按按鈕時重抓)
@st.cache_data(ttl=7200, show_spinner=False)
def fetch_market_data():
    fx_jpy = yf.Ticker("JPY=X").history(period="60d")
    fx_twd = yf.Ticker("TWD=X").history(period="5d")
    nikkei = yf.Ticker("^N225").history(period="60d")
    
    if fx_jpy.empty:
        return None, 0.0, 0.0, 32.5, None
    
    df_30 = fx_jpy.tail(30).copy()
    current_jpy = float(df_30['Close'].iloc[-1])
    start_jpy = float(df_30['Close'].iloc[0])
    pct_change_30d = ((current_jpy - start_jpy) / start_jpy) * 100
    
    current_twd = float(fx_twd['Close'].iloc[-1]) if not fx_twd.empty else 32.5
    df_nikkei_30 = nikkei.tail(30).copy() if not nikkei.empty else None
    
    return df_30, current_jpy, pct_change_30d, current_twd, df_nikkei_30

@st.cache_data(ttl=7200, show_spinner=False)
def fetch_yield_spread(api_key):
    if not api_key:
        return None, None, None
    try:
        fred = Fred(api_key=api_key)
        us_10y = fred.get_series('DGS10').dropna()
        jp_10y = fred.get_series('IRLTLT01JPM156N').dropna()
        
        latest_us = float(us_10y.iloc[-1])
        latest_jp = float(jp_10y.iloc[-1])
        
        df_us = us_10y.tail(250).rename("US 10Y")
        df_jp = jp_10y.reindex(df_us.index, method='ffill').rename("JP 10Y")
        df_spread = pd.concat([df_us, df_jp], axis=1).dropna()
        df_spread['Spread (美日利差)'] = df_spread['US 10Y'] - df_spread['JP 10Y']
        return df_spread, latest_us, latest_jp
    except Exception as e:
        st.sidebar.error(f"FRED 讀取失敗: {e}")
        return None, None, None

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_google_news(keyword="USD JPY Bank of Japan Fed"):
    safe_keyword = quote(keyword)
    url = f"https://news.google.com/rss/search?q={safe_keyword}&hl=en-US&gl=US&ceid=US:en"
    feed = feedparser.parse(url)
    return [entry.title for entry in feed.entries[:5]]

def call_gemini_instant(api_key, prompt):
    """關閉 Thinking 深度思考並設定短超時，確保 1~2 秒內完成回應"""
    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions
