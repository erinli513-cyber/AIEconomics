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

# 2. 自訂極簡專業視覺 CSS（優化卡片邊框、間距與字體層次）
st.markdown("""
<style>
    /* 整體背景與字體微調 */
    .block-container {
        padding-top: 2rem;
        padding-bottom: 2.5rem;
        max-width: 1200px;
    }
    /* Metric 指標卡片美化 */
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
    /* 分頁標籤樣式優化 */
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
sidebar_alert_placeholder = st.sidebar.empty()
sidebar_alert_placeholder.info("待執行：請切換至第 2 分頁啟動新聞情緒評估。")

# 4. 數據抓取函式庫
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
        st.sidebar.error(f"FRED 數據讀取異常：{e}")
        return None, None, None

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_google_news(keyword="USD JPY Bank of Japan Fed"):
    safe_keyword = quote(keyword)
    url = f"https://news.google.com/rss/search?q={safe_keyword}&hl=en-US&gl=US&ceid=US:en"
    feed = feedparser.parse(url)
    return [entry.title for entry in feed.entries[:6]]

def generate_formal_report(api_key, prompt):
    client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=20000))
    cfg = types.GenerateContentConfig(temperature=0.2, max_output_tokens=300)
    last_err = None
    for m in ["gemini-3.8-flash", "gemini-3.5-flash"]:
        try:
            res = client.models.generate_content(model=m, contents=prompt, config=cfg)
            return res.text
        except Exception as e:
            last_err = e
    raise last_err

# 5. 載入市場與總經數據
df_fx, fx_now, fx_chg_30d, usd_twd_now, df_nikkei = fetch_market_data()
df_spread, us_yield, jp_yield = fetch_yield_spread(fred_key)

# 6. 頂部核心指標看板（精簡為 2 張核心卡片）
st.write("")
m1, m2 = st.columns(2, gap="large")

with m1:
    st.metric(
        label="USD/JPY 即時匯率（近 30 個交易日變動）",
        value=f"{fx_now:.2f} JPY" if fx_now else "數據讀取異常",
        delta=f"{fx_chg_30d:+.2f}% (30D)",
        delta_color="normal"
    )

with m2:
    if us_yield is not None and jp_yield is not None:
        spread_val = us_yield - jp_yield
        st.metric(
            label="美日 10 年期公債殖利率利差 (US 10Y - JP 10Y)",
            value=f"{spread_val:.2f}%",
            delta=f"美國 {us_yield:.2f}% ｜ 日本 {jp_yield:.2f}%",
            delta_color="off"
        )
    else:
        st.metric(
            label="美日 10 年期公債殖利率利差 (US 10Y - JP 10Y)",
            value="未連線 FRED",
            delta="請於左側欄設定 FRED API Key",
            delta_color="off"
        )

st.write("")

# 7. 三大分頁設計
tab1, tab2, tab3 = st.tabs([
    "📊 總體經濟利差與匯率走勢",
    "🤖 AI 市場情緒評估與背離判讀",
    "💱 日圓換匯與日股連動分析"
])

# ==================== 分頁 1：總體經濟利差與匯率走勢 ====================
with tab1:
    st.subheader("📈 市場匯率價格與公債殖利率利差趨勢")
    chart_col1, chart_col2 = st.columns(2, gap="medium")

    with chart_col1:
        with st.container(border=True):
            if df_fx is not None:
                fig_fx = px.line(
                    df_fx,
                    x=df_fx.index,
                    y="Close",
                    title="USD/JPY 近 30 個交易日匯率走勢 (yfinance)",
                    labels={"Close": "匯率 (JPY)", "Date": "日期"}
                )
                fig_fx.update_traces(line_color="#334155", line_width=2.5)
                fig_fx.update_layout(
                    height=360,
                    margin=dict(l=20, r=20, t=45, b=20),
                    plot_bgcolor="rgba(0,0,0,0)",
                    paper_bgcolor="rgba(0,0,0,0)"
                )
                st.plotly_chart(fig_fx, use_container_width=True)
            else:
                st.warning("無法取得 USD/JPY 歷史數據。")

    with chart_col2:
        with st.container(border=True):
            if df_spread is not None:
                fig_sp = px.area(
                    df_spread,
                    x=df_spread.index,
                    y="Spread (美日利差)",
                    title="美日 10 年期公債殖利率利差趨勢 (FRED)",
                    labels={"Spread (美日利差)": "利差 (%)", "index": "日期"}
                )
                fig_sp.update_traces(line_color="#475569", fillcolor="rgba(71, 85, 105, 0.15)")
                fig_sp.update_layout(
                    height=360,
                    margin=dict(l=20, r=20, t=45, b=20),
                    plot_bgcolor="rgba(0,0,0,0)",
                    paper_bgcolor="rgba(0,0,0,0)"
                )
                st.plotly_chart(fig_sp, use_container_width=True)
            else:
                st.info("💡 於左側設定 `FRED_API_KEY` 後，即可載入美日 10 年期公債利差歷史走勢圖。")

# ==================== 分頁 2：AI 市場情緒評估與背離判讀 ====================
with tab2:
    st.subheader("📰 國際財經新聞輿論與 AI 情緒指標評估")
    
    col_kw, col_focus = st.columns([1, 1], gap="medium")
    with col_kw:
        search_kw = st.text_input("🔍 新聞檢索關鍵字：", value="USD JPY Bank of Japan Fed")
    with col_focus:
        analysis_goal = st.selectbox(
            "🎯 核心評估維度：",
            [
                "美日央行貨幣政策立場與美元多空方向",
                "日本央行升息預期與 160 關口干預風險",
                "美日實質利差對美元匯率的支撐力道"
            ]
        )

    news_titles = fetch_google_news(search_kw)
    st.write("")
    c1, c2 = st.columns([1, 1.2], gap="large")

    with c1:
        with st.container(border=True):
            st.markdown("#### 📌 即時財經新聞摘要 (Google News RSS)")
            st.divider()
            for i, title in enumerate(news_titles, 1):
                st.markdown(f"**{i}.** {title}")

    with c2:
        with st.container(border=True):
            st.markdown("#### 🤖 AI 情緒評分與背離診斷報告")
            st.divider()
            if not gemini_key:
                st.warning("⚠️ 請先於左側邊欄輸入 `GEMINI_API_KEY` 以啟用模型分析。")
            elif st.button("📊 執行市場情緒與背離評估", type="primary", use_container_width=True):
                with st.spinner("AI 正在彙整央行政策立場與市場情緒指標..."):
                    news_text = "\n".join([f"- {t}" for t in news_titles])
                    
                    prompt = (
                        f"請以專業總體經濟分析師視角，針對以下 6 則國際外匯新聞，聚焦「{analysis_goal}」進行評估（參考數據：USD/JPY 近 30 日變動幅度為 {fx_chg_30d:+.2f}%）：\n"
                        f"{news_text}\n\n"
                        f"請嚴格依照下列格式輸出繁體中文報告（總字數控制在 150 字內，語氣客觀精煉）：\n"
                        f"[SCORE: 整數0到100]\n"
                        f"- **政策立場**：（說明利多美元或利多日圓，約 25 字）\n"
                        f"- **核心驅動**：（點出新聞反映的關鍵經濟因素，約 30 字）\n"
                        f"- **背離診斷**：（比對新聞情緒與近 30 日匯率變動 {fx_chg_30d:+.2f}% 是否一致，約 30 字）"
                    )
                    
                    try:
                        report_text = generate_formal_report(gemini_key, prompt)
                        
                        score_match = re.search(r"\[SCORE:\s*(\d+)\]", report_text)
                        ai_score = int(score_match.group(1)) if score_match else 50
                        clean_report = re.sub(r"\[SCORE:\s*\d+\]\s*", "", report_text).strip()
                        
                        if ai_score >= 65:
                            sentiment_label = "偏多美元（鷹派預期強）"
                        elif ai_score >= 55:
                            sentiment_label = "溫和偏多美元"
                        elif ai_score <= 35:
                            sentiment_label = "偏空美元（日圓看升）"
                        elif ai_score <= 45:
                            sentiment_label = "溫和偏空美元"
                        else:
                            sentiment_label = "多空均衡（中性觀望）"

                        # 醒目分數與進度條
                        sc1, sc2 = st.columns([1, 1.4])
                        with sc1:
                            st.metric(label="AI 美元情緒指標", value=f"{ai_score} / 100")
                        with sc2:
                            st.markdown(f"**綜合市場風向：{sentiment_label}**")
                            st.progress(ai_score / 100.0)
                        
                        st.write("")
                        
                        # 市場與輿論背離自動判讀
                        if ai_score >= 70 and fx_chg_30d < -0.5:
                            alert_msg = f"⚠️ **背離警訊（利多不漲）**：新聞情緒分數達 **{ai_score} 分**，但 USD/JPY 近 30 日逆勢下跌 **{fx_chg_30d:.2f}%**，顯示市場可能提前定價政策轉向或干預風險。"
                            st.error(alert_msg)
                            sidebar_alert_placeholder.error(alert_msg)
                        elif ai_score <= 30 and fx_chg_30d > 0.5:
                            alert_msg = f"⚠️ **背離警訊（利空不跌）**：新聞情緒分數僅 **{ai_score} 分**，但 USD/JPY 近 30 日逆勢上漲 **{fx_chg_30d:+.2f}%**，顯示實質利差買盤仍具支撐。"
                            st.warning(alert_msg)
                            sidebar_alert_placeholder.warning(alert_msg)
                        else:
                            sync_msg = f"✅ **輿論與價格走勢一致**：AI 情緒分數 **{ai_score} 分** 與近 30 日匯率變動（**{fx_chg_30d:+.2f}%**）方向相符。"
                            st.success(sync_msg)
                            sidebar_alert_placeholder.success(sync_msg)
                        
                        st.markdown(clean_report)
                        
                    except Exception as e:
                        st.error(f"模型評估執行異常，請確認 API Key 或連線狀態：{e}")

# ==================== 分頁 3：日圓換匯與日股連動分析 ====================
with tab3:
    st.subheader("💱 台幣兌日圓實務試算與日股連動觀察")
    
    col_calc, col_stock = st.columns([1, 1.2], gap="large")
    
    with col_calc:
        with st.container(border=True):
            st.markdown("#### 🧮 台幣換匯購買力試算")
            st.divider()
            twd_amount = st.number_input("擬兌換新台幣金額 (TWD)：", min_value=1000, max_value=10000000, value=50000, step=5000)
            
            if fx_now > 0:
                jpy_to_twd = usd_twd_now / fx_now
                jpy_received = twd_amount / jpy_to_twd
                
                start_jpy = df_fx['Close'].iloc[0] if df_fx is not None else fx_now
                jpy_30d_ago = twd_amount / (usd_twd_now / start_jpy)
                diff_jpy = jpy_received - jpy_30d_ago
                
                st.metric(
                    label="參考交叉匯率 (1 JPY 兌 TWD)",
                    value=f"{jpy_to_twd:.4f} 元",
                    delta=f"30 日前同額可換 {jpy_30d_ago:,.0f} JPY",
                    delta_color="off"
                )
                st.info(f"💰 **{twd_amount:,} TWD** 約可兌換 **{jpy_received:,.0f} JPY**（較 30 日前{'增加' if diff_jpy >= 0 else '減少'} **{abs(diff_jpy):,.0f} JPY**）")
            else:
                st.warning("匯率數據載入中，暫無法計算。")

    with col_stock:
        with st.container(border=True):
            st.markdown("#### 📈 日圓匯率與日經 225 指數連動")
            st.divider()
            if df_nikkei is not None:
                fig_nk = px.line(
                    df_nikkei,
                    x=df_nikkei.index,
                    y="Close",
                    title="日經 225 指數 (^N225) 近 30 個交易日走勢",
                    labels={"Close": "指數點位", "Date": "日期"}
                )
                fig_nk.update_traces(line_color="#0F766E", line_width=2.5)
                fig_nk.update_layout(
                    height=300,
                    margin=dict(l=20, r=20, t=45, b=20),
                    plot_bgcolor="rgba(0,0,0,0)",
                    paper_bgcolor="rgba(0,0,0,0)"
                )
                st.plotly_chart(fig_nk, use_container_width=True)
                st.caption("💡 總體經濟傳導機制：日本大型權值股多為出口導向企業，當日圓貶值（USD/JPY 走升）時，有助提升其海外營收換算利益，通常與日經指數呈現正相關。")
            else:
                st.info("暫無日經指數歷史數據。")
