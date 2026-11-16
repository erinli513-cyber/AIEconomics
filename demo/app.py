import streamlit as st
import pandas as pd
import plotly.express as px
import yfinance as yf
from fredapi import Fred
import feedparser
from google import genai
from urllib.parse import quote
import re

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
else:
    gemini_input = st.sidebar.text_input("請輸入 Gemini API Key:", type="password")
    if gemini_input:
        gemini_key = gemini_input

st.sidebar.divider()
st.sidebar.subheader("📡 系統自動判讀狀態")
sidebar_alert_placeholder = st.sidebar.empty()
sidebar_alert_placeholder.info("尚未執行 AI 情緒分析，請切換至第 2 分頁啟動背離偵測。")

# 3. 數據抓取函式庫
@st.cache_data(ttl=3600)
def fetch_market_data():
    """抓取 USD/JPY、USD/TWD 匯率與日經 225 指數近 60 天數據"""
    fx_jpy = yf.Ticker("JPY=X").history(period="60d")
    fx_twd = yf.Ticker("TWD=X").history(period="5d")
    nikkei = yf.Ticker("^N225").history(period="60d")
    
    if fx_jpy.empty:
        return None, 0.0, 0.0, 32.5, None
    
    df_30 = fx_jpy.tail(30).copy()
    current_jpy = df_30['Close'].iloc[-1]
    start_jpy = df_30['Close'].iloc[0]
    pct_change_30d = ((current_jpy - start_jpy) / start_jpy) * 100
    
    current_twd = fx_twd['Close'].iloc[-1] if not fx_twd.empty else 32.5
    df_nikkei_30 = nikkei.tail(30).copy() if not nikkei.empty else None
    
    return df_30, current_jpy, pct_change_30d, current_twd, df_nikkei_30

@st.cache_data(ttl=3600)
def fetch_yield_spread(api_key):
    """從 FRED 抓取美日 10 年期公債殖利率並計算利差"""
    if not api_key:
        return None, None, None
    try:
        fred = Fred(api_key=api_key)
        us_10y = fred.get_series('DGS10').dropna()
        jp_10y = fred.get_series('IRLTLT01JPM156N').dropna()
        
        latest_us = us_10y.iloc[-1]
        latest_jp = jp_10y.iloc[-1]
        
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

def generate_ai_report(api_key, prompt):
    """使用最新 gemini-3.8-flash 模型呼叫 Gemini API"""
    client = genai.Client(api_key=api_key)
    models_to_try = ["gemini-3.8-flash", "gemini-3.5-flash"]
    last_error = None
    for model_name in models_to_try:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt
            )
            return response.text, model_name
        except Exception as e:
            last_error = e
            continue
    raise last_error

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
        label="今日 AI 美元/利差情緒分數",
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
    "🤖 2. AI 新聞情緒與背離判讀",
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

    with st.expander("📋 查看近期匯率與利差原始數據明細"):
        d1, d2 = st.columns(2)
        with d1:
            if df_fx is not None:
                st.write("**USD/JPY 近 10 日收盤數據**")
                st.dataframe(df_fx[['Open', 'High', 'Low', 'Close']].tail(10).round(2), use_container_width=True)
        with d2:
            if df_spread is not None:
                st.write("**美日 10 年期公債殖利率近 10 筆數據**")
                st.dataframe(df_spread.tail(10).round(2), use_container_width=True)

# ==================== 分頁 2：AI 新聞情緒與背離判讀 ====================
with tab2:
    st.subheader("📰 即時外匯新聞與 AI 鷹鴿派情緒分析")
    col_kw, col_role = st.columns([1, 1])
    with col_kw:
        search_kw = st.text_input("🔍 關注關鍵字 (預設美日央行與匯率):", value="USD JPY Bank of Japan Fed")
    with col_role:
        analyst_role = st.selectbox("🎭 選擇 AI 分析師視角:", ["外匯與總體經濟策略師", "日本央行 (BoJ) 政策觀察家", "跨國企業匯率避險經理人"])

    custom_prompt = st.text_input("✍️ 自訂額外分析指令 (選填):", placeholder="例如：請評估日本財務省在 160 關口進場干預匯率 (Intervention) 的風險...")

    news_titles = fetch_google_news(search_kw)
    c1, c2 = st.columns([1, 1.3])

    with c1:
        st.markdown("### 📌 最新相關新聞標題 (Google News RSS)")
        for i, title in enumerate(news_titles, 1):
            st.write(f"**{i}.** {title}")

    with c2:
        st.markdown("### 🤖 Gemini AI 情緒評分與背離判讀報告")
        if not gemini_key:
            st.warning("⚠️ 請先在左側邊欄輸入您的 GEMINI_API_KEY 以啟用 AI 分析。")
        elif st.button("🚀 開始分析市場情緒與背離訊號", type="primary"):
            with st.spinner("AI 正在比對新聞輿論與 USD/JPY 實際走勢..."):
                news_text = "\n".join([f"- {t}" for t in news_titles])
                spread_str = f"{us_yield - jp_yield:.2f}%" if (us_yield and jp_yield) else "未提供"
                extra_str = custom_prompt if custom_prompt else "無"
                
                prompt = (
                    f"你是一位【{analyst_role}】。請針對以下 8 條關於「{search_kw}」的最新財經新聞進行深度剖析：\n"
                    f"{news_text}\n\n"
                    f"【當前客觀市場數據參考】\n"
                    f"- USD/JPY 近 30 日漲跌幅：{fx_chg_30d:+.2f}% （正值代表美元強/日圓貶；負值代表美元弱/日圓升）\n"
                    f"- 美日 10Y 利差：{spread_str}\n"
                    f"- 額外分析要求：{extra_str}\n\n"
                    f"【嚴格輸出格式要求】\n"
                    f"1. 請務必在回覆的第一行輸出情緒分數標籤，格式為 [SCORE: X]，其中 X 為 0 到 100 的整數。\n"
                    f"   - 評分標準（以「美元走強 / 美日利差擴大」為利多方向）：\n"
                    f"     * 75~100：極度看多美元 / Fed極鷹或BoJ極鴿\n"
                    f"     * 55~74：溫和偏多美元\n"
                    f"     * 45~54：中性觀望\n"
                    f"     * 25~44：溫和看空美元 / 日圓看升\n"
                    f"     * 0~24：極度看空美元 / BoJ升息預期強烈或干預風險極高\n"
                    f"2. 接著以繁體中文輸出結構化報告：\n"
                    f"   - **美日央行政策立場判定**（Fed 鷹鴿程度 vs. BoJ 升息/干預壓力）\n"
                    f"   - **市場與輿論背離深度解讀**（結合上方提供的 30 日匯率漲跌幅進行點評）\n"
                    f"   - **逐條新聞情緒評分與簡評**（以 Markdown 表格呈現）"
                )
                
                try:
                    report_text, used_model = generate_ai_report(gemini_key, prompt)
                    
                    score_match = re.search(r"\[SCORE:\s*(\d+)\]", report_text)
                    ai_score = int(score_match.group(1)) if score_match else 50
                    clean_report = re.sub(r"\[SCORE:\s*\d+\]\s*", "", report_text)
                    
                    # 更新頂部 Metric 卡片
                    ai_score_metric.metric(
                        label="今日 AI 美元/利差情緒分數",
                        value=f"{ai_score} / 100 分",
                        delta="偏多美元 (鷹派)" if ai_score >= 60 else ("偏空美元 (日圓升)" if ai_score <= 40 else "中性震盪"),
                        delta_color="normal" if ai_score >= 60 else ("inverse" if ai_score <= 40 else "off")
                    )
                    
                    # 情緒與市場背離自動判讀
                    if ai_score >= 70 and fx_chg_30d < -0.5:
                        alert_msg = (
                            f"⚠️ **市場與輿論出現背離（利多不漲警訊）**\n\n"
                            f"AI 新聞情緒高達 **{ai_score} 分**（極度看多美元），但 USD/JPY 近 30 日卻逆勢下跌 **{fx_chg_30d:.2f}%**。"
                            f"市場可能正在提前定價日本央行升息或忌憚匯率干預，慎防追高風險！"
                        )
                        st.error(alert_msg)
                        sidebar_alert_placeholder.error(alert_msg)
                        divergence_metric.metric(
                            label="市場與輿論背離狀態",
                            value="⚠️ 利多不漲背離",
                            delta="新聞樂觀但匯率走跌",
                            delta_color="inverse"
                        )
                    elif ai_score <= 30 and fx_chg_30d > 0.5:
                        alert_msg = (
                            f"⚠️ **市場與輿論出現背離（利空不跌警訊）**\n\n"
                            f"AI 新聞情緒僅 **{ai_score} 分**（看空美元），但 USD/JPY 近 30 日卻上漲 **{fx_chg_30d:+.2f}%**。"
                            f"顯示美日實際利差買盤依然強勁，日圓空頭尚未退場。"
                        )
                        st.warning(alert_msg)
                        sidebar_alert_placeholder.warning(alert_msg)
                        divergence_metric.metric(
                            label="市場與輿論背離狀態",
                            value="⚠️ 利空不跌背離",
                            delta="新聞悲觀但匯率走升",
                            delta_color="normal"
                        )
                    else:
                        sync_msg = (
                            f"✅ **市場走勢與新聞輿論一致**\n\n"
                            f"AI 情緒分數為 **{ai_score} 分**，與 USD/JPY 近 30 日漲跌幅（**{fx_chg_30d:+.2f}%**）方向相符，無明顯背離訊號。"
                        )
                        st.success(sync_msg)
                        sidebar_alert_placeholder.success(sync_msg)
                        divergence_metric.metric(
                            label="市場與輿論背離狀態",
                            value="✅ 方向一致",
                            delta="無明顯背離訊號",
                            delta_color="off"
                        )
                    
                    st.caption(f"使用模型：`{used_model}`")
                    st.markdown(clean_report)
                    
                except Exception as e:
                    st.error(f"AI 分析呼叫失敗，請確認 GEMINI_API_KEY 是否有效或額度是否已滿。錯誤訊息：{e}")

# ==================== 分頁 3：日圓換匯與日股連動 ====================
with tab3:
    st.subheader("💱 即時台幣換日圓試算 & 日股連動觀察")
    
    col_calc, col_stock = st.columns([1, 1.2])
    
    with col_calc:
        st.markdown("### 🧮 旅遊 / 投資換匯試算機")
        twd_amount = st.number_input("輸入想兌換的新台幣金額 (TWD):", min_value=1000, max_value=10000000, value=50000, step=5000)
        
        if fx_now > 0:
            # 透過 USD/TWD 與 USD/JPY 交叉計算台幣兌日圓即期匯率
            jpy_to_twd = usd_twd_now / fx_now
            jpy_received = twd_amount / jpy_to_twd
            
            # 比較 30 天前的匯率
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
