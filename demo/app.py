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
st.set_page_config(
    page_title="美日利差、匯率與 AI 情緒決策儀表板",
    layout="wide",
    page_icon="💴"
)

# 2. 自訂極簡專業視覺 CSS
st.markdown("""
<style>
    .block-container {
        padding-top: 2rem;
        padding-bottom: 2.5rem;
        max-width: 1200px;
    }
    div[data-testid="stMetric"] {
        background-color: #F8F9FA;
        border: 1px solid #E2E8F0;
        border-radius: 10px;
        padding: 16px 20px;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
    }
    div[data-testid="stMetricLabel"] {
        font-size: 0.95rem;
        font-weight: 600;
        color: #475569;
    }
    div[data-testid="stMetricValue"] {
        font-size: 1.85rem;
        font-weight: 700;
        color: #0F172A;
    }
    button[data-baseweb="tab"] {
        font-size: 1rem;
        font-weight: 600;
        padding: 10px 18px;
    }
</style>
""", unsafe_allow_html=True)

# 標題區
st.title("💴 美日利差、USD/JPY 匯率與 AI 市場情緒分析儀表板")
st.markdown(
    "<p style='color: #64748B; font-size: 1.05rem; margin-top: -10px;'>"
    "整合 FRED 總體經濟殖利率、yfinance 即時匯率數據與 Gemini NLP 市場背離偵測系統"
    "</p>",
    unsafe_allow_html=True
)

# 3. 側邊欄：安全讀取 Secrets 金鑰
st.sidebar.header("⚙️ 系統參數與金鑰設定")
fred_key = st.secrets["FRED_API_KEY"] if "FRED_API_KEY" in st.secrets else st.sidebar.text_input("FRED API Key:", type="password")

gemini_key = None
if "GEMINI_API_KEY" in st.secrets:
    gemini_key = st.secrets["GEMINI_API_KEY"]
else:
    gemini_input = st.sidebar.text_input("Gemini API Key:", type="password")
    if gemini_input:
        gemini_key = gemini_input

st.sidebar.divider()
st.sidebar.subheader("📡 市場背離監控狀態")
sidebar_alert_placeholder = st.sidebar.empty
