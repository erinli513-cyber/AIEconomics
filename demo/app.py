import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import yfinance as yf
from fredapi import Fred
from google import genai
from google.genai import types
import time

# -------------------------------------------------------------
# 頁面基本配置
# -------------------------------------------------------------
st.set_page_config(page_title="全球總體經濟與金融指標即時儀表板", layout="wide")
st.title("🌐 全球總體經濟與金融指標即時儀表板")

# -------------------------------------------------------------
# 側邊欄：API 金鑰與控制
# -------------------------------------------------------------
st.sidebar.header("⚙️ 設定與金鑰")

# 1. FRED 金鑰讀取
if "FRED_API_KEY" in st.secrets:
    fred_key = st.secrets["FRED_API_KEY"]
    st.sidebar.success("已自動讀取 FRED API Key")
else:
    fred_key = st.sidebar.text_input("請輸入 FRED API Key:", type="password")

# 2. Gemini 金鑰讀取 (原生支援 AQ. 新版授權金鑰)
if "GEMINI_API_KEY" in st.secrets:
    gemini_key = st.secrets["GEMINI_API_KEY"]
    st.sidebar.success("已自動讀取 Gemini API Key")
else:
    gemini_key = st.sidebar.text_input("請輸入 Gemini API Key:", type="password")

if st.sidebar.button("手動刷新所有數據"):
    st.cache_data.clear()

# -------------------------------------------------------------
# 資料抓取函數 (擴充豐富指標)
# -------------------------------------------------------------
@st.cache_data(ttl=3600)
def get_fred_data(api_key):
    fred = Fred(api_key=api_key)
    data = {
        "CPI 物價指數": fred.get_series("CPIAUCSL"),
        "核心 CPI 指數": fred.get_series("CPILFESL"),
        "3個月期美債殖利率": fred.get_series("DGS3MO"),
        "2年期美債殖利率": fred.get_series("DGS2"),
        "5年期美債殖利率": fred.get_series("DGS5"),
        "10年期美債殖利率": fred.get_series("DGS10"),
        "30年期美債殖利率": fred.get_series("DGS30"),
        "日本10年期國債殖利率": fred.get_series("IRLTLT01JPM156N"),
        "美國失業率": fred.get_series("UNRATE"),
        "聯邦基金利率": fred.get_series("FEDFUNDS")
    }
    df = pd.DataFrame(data).ffill().tail(365)
    
    # 計算衍生利差指標
    df["10Y-2Y 美債利差"] = df["10年期美債殖利率"] - df["2年期美債殖利率"]
    df["10Y-3M 美債利差"] = df["10年期美債殖利率"] - df["3個月期美債殖利率"]
    df["美日10Y國債利差"] = df["10年期美債殖利率"] - df["日本10年期國債殖利率"]
    return df

@st.cache_data(ttl=600)
def get_market_data():
    tickers = {
        "標普 500 (S&P 500)": "^GSPC",
        "那斯達克 (Nasdaq)": "^IXIC",
        "道瓊工業指數 (DJI)": "^DJI",
        "台灣加權指數 (TWII)": "^TWII",
        "黃金現貨 (Gold GC=F)": "GC=F",
        "布蘭特原油 (Brent Crude)": "BZ=F",
        "比特幣 (BTC/USD)": "BTC-USD",
        "美元/新台幣匯率": "TWD=X"
    }
    raw_df = yf.download(list(tickers.values()), period="1y")["Close"]
    
    # 處理 yfinance 多層欄位索引
    if isinstance(raw_df.columns, pd.MultiIndex):
        raw_df.columns = raw_df.columns.get_level_values(-1)
        
    df = raw_df.rename(columns={v: k for k, v in tickers.items()})
    return df

# -------------------------------------------------------------
# 主畫面邏輯
# -------------------------------------------------------------
if fred_key:
    try:
        macro_df = get_fred_data(fred_key)
        market_df = get_market_data()

        # 最新數據與前期值擷取
        latest_cpi = macro_df["CPI 物價指數"].dropna().iloc[-1]
        cpi_prev = macro_df["CPI 物價指數"].dropna().iloc[-2]

        latest_core_cpi = macro_df["核心 CPI 指數"].dropna().iloc[-1]
        
        latest_10y = macro_df["10年期美債殖利率"].dropna().iloc[-1]
        prev_10y = macro_df["10年期美債殖利率"].dropna().iloc[-2]

        latest_2y = macro_df["2年期美債殖利率"].dropna().iloc[-1]
        prev_2y = macro_df["2年期美債殖利率"].dropna().iloc[-2]

        spread_series = macro_df["10Y-2Y 美債利差"].dropna()
        latest_spread = spread_series.iloc[-1]
        spread_prev = spread_series.iloc[-2] if len(spread_series) > 1 else latest_spread

        jp_series = macro_df["日本10年期國債殖利率"].dropna()
        latest_jp = jp_series.iloc[-1]
        jp_prev = jp_series.iloc[-2] if len(jp_series) > 1 else latest_jp

        latest_unemp = macro_df["美國失業率"].dropna().iloc[-1]
        latest_fed = macro_df["聯邦基金利率"].dropna().iloc[-1]

        # 殖利率曲線倒掛警示
        if latest_spread < 0:
            st.error(
                f"🚨 **殖利率曲線倒掛警示 (Yield Curve Inverted)**：當前 10Y-2Y 利差為 **{latest_spread:+.2f}%**（低於 0），請留意經濟衰退訊號。"
            )
        else:
            st.info(
                f"💡 **殖利率曲線維持正斜率**：當前 10Y-
