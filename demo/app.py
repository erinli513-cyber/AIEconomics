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

# 3. 數據抓取函式庫
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
    client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=15000))
    cfg = types.GenerateContentConfig(temperature=0.2, max_output_tokens=200)
    for m in ["gemini-3.8-flash", "gemini-3.5-flash"]:
        try:
            res = client.models.generate_content(model=m, contents=prompt, config=cfg)
            return res.text
        except Exception as e:
            last_err = e
    raise last_err

# 4. 載入市場與總經數據
df_fx, fx_now, fx_chg_30d, usd_twd_now, df_nikkei = fetch_market_data()
df_spread, us_yield, jp_yield = fetch_yield_spread(fred_key)

# 5. 頂部常駐核心指標看板
m1, m2, m3, m4 = st.columns(4)

with m1:
    st.metric(
        label="USD/JPY 即時匯率 (30日漲跌)",
        value=f"{fx_now:.2f} 円" if fx_now else "讀取失敗",
        delta=f"{fx_chg_30d:+.2f}% (30D)",
        delta_color="normal"
    )

with m2:
    if us_yield is not None and jp_yield is not None:
        spread_val = us_yield - jp_yield
        st.metric(
            label="美日 10Y 公債利差",
            value=f"{spread_val:.2f}%",
            delta=f"美 {us_yield:.2f}% / 日 {jp_yield:.2f}%",
            delta_color="off"
        )
    else:
        st.metric(
            label="美日 10Y 公債利差",
            value="需輸入 FRED Key",
            delta="請於左側欄設定",
            delta_color="off"
        )

with m3:
    ai_score_metric = st.empty()
    ai_score_metric.metric(
        label="今日 AI 美元情緒分數",
        value="待分析",
        delta="請至分頁 2 啟動",
        delta_color="off"
    )

with m4:
    divergence_metric = st.empty()
    divergence_metric.metric(
        label="市場與輿論背離狀態",
        value="監控中",
        delta="等待 AI 評分",
        delta_color="off"
    )

st.divider()

# 6. 三大分頁設計
tab1, tab2, tab3 = st.tabs([
    "📊 1. 總經利差與匯率走勢",
    "🤖 2. AI 快速情緒評分與背離判讀",
    "💱 3. 日圓換匯與日股連動"
])

# ==================== 分頁 1：總經利差與匯率走勢 ====================
with tab1:
    st.subheader("📈 市場價格與總體經濟殖利率利差")
    chart_col1, chart_col2 = st.columns(2)

    with chart_col1:
        if df_fx is not None:
            fig_fx = px.line(
                df_fx,
                x=df_fx.index,
                y="Close",
                title="USD/JPY 近 30 個交易日走勢圖 (yfinance)",
                labels={"Close": "匯率 (JPY)", "Date": "日期"}
            )
            fig_fx.update_traces(line_color="#FF4B4B", line_width=2.5)
            fig_fx.update_layout(height=380, margin=dict(l=20, r=20, t=50, b=20))
            st.plotly_chart(fig_fx, use_container_width=True)
        else:
            st.warning("無法取得 USD/JPY 歷史資料。")

    with chart_col2:
        if df_spread is not None:
            fig_sp = px.area(
                df_spread,
                x=df_spread.index,
                y="Spread (美日利差)",
                title="美日 10 年期公債殖利率利差趨勢 (FRED)",
                labels={"Spread (美日利差)": "利差 (%)", "index": "日期"}
            )
            fig_sp.update_traces(line_color="#1f77b4")
            fig_sp.update_layout(height=380, margin=dict(l=20, r=20, t=50, b=20))
            st.plotly_chart(fig_sp, use_container_width=True)
        else:
            st.info("💡 在左側輸入 FRED_API_KEY 即可顯示「美日 10 年期公債利差」歷史趨勢圖。")

# ==================== 分頁 2：AI 快速情緒評分與背離判讀 ====================
with tab2:
    col_kw, col_focus = st.columns([1, 1])
    with col_kw:
        search_kw = st.text_input("🔍 新聞搜尋關鍵字:", value="USD JPY Bank of Japan Fed")
    with col_focus:
        analysis_goal = st.selectbox(
            "🎯 選擇分析重點:",
            [
                "美日央行誰較強勢？（美元多空方向）",
                "日本央行升息與干預 160 關口風險",
                "美日利差是否足以支撐美元續強？"
            ]
        )

    news_titles = fetch_google_news(search_kw)
    c1, c2 = st.columns([1, 1.2])

    with c1:
        st.markdown("### 📌 最新 5 則焦點新聞")
        for i, title in enumerate(news_titles, 1):
            st.write(f"**{i}.** {title}")

    with c2:
        st.markdown("### ⚡ AI 情緒評分與一句話結論")
        if not gemini_key:
            st.warning("⚠️ 請先在左側邊欄輸入您的 GEMINI_API_KEY 以啟用 AI 分析。")
        elif st.button("⚡ 立即計算情緒分數", type="primary", use_container_width=True):
            with st.spinner("AI 秒速判讀中..."):
                news_text = "\n".join([f"- {t}" for t in news_titles])
                
                prompt = (
                    f"閱讀以下 5 則新聞，針對「{analysis_goal}」給出美元情緒分數（USD/JPY 近30日漲跌 {fx_chg_30d:+.2f}%）：\n"
                    f"{news_text}\n\n"
                    f"請嚴格按照以下格式輸出（總字數100字內）：\n"
                    f"[SCORE: 整數0到100]\n"
                    f"- **方向**：（利多美元 或 利多日圓，20字內）\n"
                    f"- **原因**：（新聞核心重點，25字內）\n"
                    f"- **背離**：（與匯率漲跌 {fx_chg_30d:+.2f}% 是否一致，25字內）"
                )
                
                try:
                    report_text = call_gemini_instant(gemini_key, prompt)
                    
                    score_match = re.search(r"\[SCORE:\s*(\d+)\]", report_text)
                    ai_score = int(score_match.group(1)) if score_match else 50
                    clean_report = re.sub(r"\[SCORE:\s*\d+\]\s*", "", report_text).strip()
                    
                    if ai_score >= 65:
                        sentiment_label = "🔥 極度看多美元 (偏鷹)"
                    elif ai_score >= 55:
                        sentiment_label = "📈 溫和偏多美元"
                    elif ai_score <= 35:
                        sentiment_label = "❄️ 極度看空美元 (日圓看升)"
                    elif ai_score <= 45:
                        sentiment_label = "📉 溫和偏空美元"
                    else:
                        sentiment_label = "⚖️ 多空均衡 / 中性觀望"

                    score_col1, score_col2 = st.columns([1, 1.5])
                    with score_col1:
                        st.metric(label="AI 美元情緒總分", value=f"{ai_score} / 100 分")
                    with score_col2:
                        st.write(f"**市場風向：{sentiment_label}**")
                        st.progress(ai_score / 100.0)
                    
                    ai_score_metric.metric(
                        label="今日 AI 美元情緒分數",
                        value=f"{ai_score} / 100 分",
                        delta=sentiment_label,
                        delta_color="normal" if ai_score >= 55 else ("inverse" if ai_score <= 45 else "off")
                    )
                    
                    if ai_score >= 70 and fx_chg_30d < -0.5:
                        alert_msg = f"⚠️ **背離警訊（利多不漲）**：新聞情緒達 **{ai_score} 分**，但匯率近 30 日下跌 **{fx_chg_30d:.2f}%**。"
                        st.error(alert_msg)
                        sidebar_alert_placeholder.error(alert_msg)
                        divergence_metric.metric(label="市場與輿論背離狀態", value="⚠️ 利多不漲背離", delta="新聞樂觀但匯率走跌", delta_color="inverse")
                    elif ai_score <= 30 and fx_chg_30d > 0.5:
                        alert_msg = f"⚠️ **背離警訊（利空不跌）**：新聞情緒僅 **{ai_score} 分**，但匯率近 30 日上漲 **{fx_chg_30d:+.2f}%**。"
                        st.warning(alert_msg)
                        sidebar_alert_placeholder.warning(alert_msg)
                        divergence_metric.metric(label="市場與輿論背離狀態", value="⚠️ 利空不跌背離", delta="新聞悲觀但匯率走升", delta_color="normal")
                    else:
                        sync_msg = f"✅ **輿論與價格一致**：AI 分數 **{ai_score} 分** 與近 30 日漲跌（**{fx_chg_30d:+.2f}%**）方向相符。"
                        st.success(sync_msg)
                        sidebar_alert_placeholder.success(sync_msg)
                        divergence_metric.metric(label="市場與輿論背離狀態", value="✅ 方向一致", delta="無背離訊號", delta_color="off")
                    
                    st.info(clean_report)
                    
                except Exception as e:
                    st.error(f"AI 呼叫失敗或超時，請檢查 API Key 或稍後再試：{e}")

# ==================== 分頁 3：日圓換匯與日股連動 ====================
with tab3:
    st.subheader("💱 即時台幣換日圓試算 & 日股連動觀察")
    
    col_calc, col_stock = st.columns([1, 1.2])
    
    with col_calc:
        st.markdown("### 🧮 旅遊 / 投資換匯試算機")
        twd_amount = st.number_input("輸入想兌換的新台幣金額 (TWD):", min_value=1000, max_value=10000000, value=50000, step=5000)
        
        if fx_now > 0:
            jpy_to_twd = usd_twd_now / fx_now
            jpy_received = twd_amount / jpy_to_twd
            
            start_jpy = df_fx['Close'].iloc[0] if df_fx is not None else fx_now
            jpy_30d_ago = twd_amount / (usd_twd_now / start_jpy)
            diff_jpy = jpy_received - jpy_30d_ago
            
            st.metric(
                label="目前台幣兌日圓參考匯率 (1 JPY 換 TWD)",
                value=f"{jpy_to_twd:.4f} 元",
                delta=f"30天前可換 {jpy_30d_ago:,.0f} 円",
                delta_color="off"
            )
            st.success(f"💰 **{twd_amount:,} 元台幣** 現在約可換得 **{jpy_received:,.0f} 日圓**（比 30 天前{'多換' if diff_jpy >= 0 else '少換'} **{abs(diff_jpy):,.0f} 日圓**）")
        else:
            st.warning("匯率資料讀取中，暫無法計算。")

    with col_stock:
        st.markdown("### 📈 日圓匯率 vs. 日經 225 指數連動")
        if df_nikkei is not None:
            fig_nk = px.line(
                df_nikkei,
                x=df_nikkei.index,
                y="Close",
                title="日本日經 225 指數 (^N225) 近 30 日走勢",
                labels={"Close": "指數點位", "Date": "日期"}
            )
            fig_nk.update_traces(line_color="#00CC96", line_width=2.5)
            fig_nk.update_layout(height=300, margin=dict(l=20, r=20, t=40, b=20))
            st.plotly_chart(fig_nk, use_container_width=True)
            st.caption("💡 經濟學小知識：日本以出口導向企業（如豐田、Sony）為主，通常「日圓貶值（USD/JPY 上漲）」有利日本出口商獲利，進而帶動日經指數上漲。")
        else:
            st.info("暫無日經指數資料。")
