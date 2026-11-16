import re
from urllib.parse import quote  # 解決搜尋關鍵字包含空白字元導致的 URL 錯誤
import feedparser
from fredapi import Fred
import google.generativeai as genai
import pandas as pd
import plotly.express as px
import streamlit as st
import yfinance as yf

st.set_page_config(
    page_title="全球總經、美日利差與 NLP 市場情緒儀表板", layout="wide"
)
st.title("🌐 總體經濟、美日利差與 AI 輿論情緒即時儀表板")

# ==========================================
# 1. 側邊欄：安全讀取 Secrets 金鑰（完全沿用課堂結構）
# ==========================================
st.sidebar.header("⚙️ 設定與金鑰")
fred_key = (
    st.secrets["FRED_API_KEY"]
    if "FRED_API_KEY" in st.secrets
    else st.sidebar.text_input("請輸入 FRED API Key:", type="password")
)

gemini_key = None
if "GEMINI_API_KEY" in st.secrets:
    gemini_key = st.secrets["GEMINI_API_KEY"]
    genai.configure(api_key=gemini_key)
else:
    gemini_input = st.sidebar.text_input(
        "請輸入 Gemini API Key:", type="password"
    )
    if gemini_input:
        gemini_key = gemini_input
        genai.configure(api_key=gemini_key)


# ==========================================
# 2. 資料抓取函式（加入快取保護 API 配額）
# ==========================================
@st.cache_data(ttl=1800)
def fetch_google_news(keyword="Bank of Japan rate hike Yen carry trade"):
    safe_keyword = quote(keyword)
    url = f"https://news.google.com/rss/search?q={safe_keyword}&hl=en-US"
    feed = feedparser.parse(url)
    return [entry.title for entry in feed.entries[:8]]


@st.cache_data(ttl=1800)
def fetch_market_series(ticker, period="3mo"):
    df = yf.download(ticker, period=period, progress=False)
    if df.empty:
        return pd.Series(dtype=float)
    if isinstance(df.columns, pd.MultiIndex):
        return df["Close"][ticker].dropna()
    return df["Close"].dropna()


@st.cache_data(ttl=3600)
def fetch_fred_macro(api_key):
    fred = Fred(api_key=api_key)
    us_10y = fred.get_series("GS10", observation_start="2020-01-01")
    us_2y = fred.get_series("GS2", observation_start="2020-01-01")
    jp_10y = fred.get_series(
        "IRLTLT01JPM156N", observation_start="2020-01-01"
    )
    df = pd.DataFrame(
        {"US_10Y": us_10y, "US_2Y": us_2y, "JP_10Y": jp_10y}
    ).dropna()
    df["US_10Y_2Y_Spread"] = df["US_10Y"] - df["US_2Y"]  # 美債 10Y-2Y 利差
    df["US_JP_Spread"] = df["US_10Y"] - df["JP_10Y"]  # 美日 10Y 利差
    return df


# ==========================================
# 3. 延伸區塊 A：全球五大核心指標 KPI（融合原有儀表板特色）
# ==========================================
st.subheader("📊 一、全球金融市場五大核心指標總覽")
kpi_list = [
    ("🇺🇸 標普 500 (^GSPC)", "^GSPC", ",.2f"),
    ("🇹🇼 台灣加權 (^TWII)", "^TWII", ",.2f"),
    ("🥇 黃金現貨 (GC=F)", "GC=F", ",.2f"),
    ("💴 美元/日圓 (JPY=X)", "JPY=X", ".2f"),
    ("💱 美元/台幣 (TWD=X)", "TWD=X", ".2f"),
]

kpi_cols = st.columns(5)
market_data_dict = {}

for col, (label, ticker, fmt) in zip(kpi_cols, kpi_list):
    series = fetch_market_series(ticker, period="3mo")
    market_data_dict[ticker] = series
    if len(series) >= 2:
        now_val = float(series.iloc[-1])
        prev_val = float(series.iloc[-2])
        chg = ((now_val - prev_val) / prev_val) * 100
        col.metric(label, f"{now_val:{fmt}}", f"{chg:+.2f}%")
    else:
        col.metric(label, "N/A", "0.00%")

# ==========================================
# 4. 延伸區塊 B：美日利差（套利交易風向）與殖利率曲線監控
# ==========================================
st.subheader("💴 二、美日 10 年期公債利差與殖利率曲線傳導")
fred_df = None

if fred_key:
    try:
        fred_df = fetch_fred_macro(fred_key)
        latest_m = fred_df.iloc[-1]
        prev_m = fred_df.iloc[-2]

        jp_spread_now = latest_m["US_JP_Spread"]
        jp_spread_diff = jp_spread_now - prev_m["US_JP_Spread"]
        us_curve_now = latest_m["US_10Y_2Y_Spread"]

        c_macro1, c_macro2 = st.columns([1, 2])
        with c_macro1:
            st.metric(
                label="🇺🇸-🇯🇵 美日 10 年期公債利差",
                value=f"{jp_spread_now:.2f}%",
                delta=f"{jp_spread_diff:+.2f}% (較上月)",
                delta_color="inverse",
            )
            st.metric(
                label="🇺🇸 美債 10Y - 2Y 利差",
                value=f"{us_curve_now:+.2f}%",
                delta="倒掛警報" if us_curve_now < 0 else "正斜率正常",
                delta_color="inverse" if us_curve_now < 0 else "normal",
            )
            st.info(
                "💡 **經濟邏輯**：美日利差若持續收斂，日圓套利交易（Yen Carry Trade）平倉壓力升高，易帶動日圓升值並影響亞股外資流向。"
            )

        with c_macro2:
            fig_spread = px.line(
                fred_df,
                y=["US_10Y", "JP_10Y", "US_JP_Spread"],
                title="美日 10 年期公債殖利率與利差走勢 (%)",
                labels={"value": "殖利率 / 利差 (%)", "index": "日期"},
            )
            st.plotly_chart(fig_spread, use_container_width=True)
    except Exception as e:
        st.error(f"FRED 數據讀取失敗：{e}")
else:
    st.info(
        "👈 請在左側邊欄輸入 `FRED_API_KEY` 以載入美日 10 年期公債利差與殖利率曲線。"
    )

st.divider()

# ==========================================
# 5. NLP 市場新聞情緒分析介面設計（保留課堂結構 + 加上市場背離自動判讀）
# ==========================================
st.subheader("📰 三、即時財經新聞與 LLM 鷹鴿派情緒／背離分析")

col_target, col_kw, col_role = st.columns([1, 1.2, 1])

with col_target:
    target_map = {
        "美元兌日圓 (JPY=X)": "JPY=X",
        "美元兌台幣 (TWD=X)": "TWD=X",
        "台灣加權指數 (^TWII)": "^TWII",
        "標普 500 指數 (^GSPC)": "^GSPC",
        "黃金現貨 (GC=F)": "GC=F",
    }
    selected_target_name = st.selectbox(
        "🎯 選擇比對背離的市場標的:", list(target_map.keys())
    )
    selected_ticker = target_map[selected_target_name]

    # 計算近 30 個交易日（約 22 根日 K）漲跌幅
    target_series = market_data_dict.get(
        selected_ticker, pd.Series(dtype=float)
    )
    if len(target_series) >= 22:
        pct_30d = (
            (float(target_series.iloc[-1]) - float(target_series.iloc[-22]))
            / float(target_series.iloc[-22])
        ) * 100
    else:
        pct_30d = 0.0

with col_kw:
    search_kw = st.text_input(
        "🔍 輸入關注關鍵字 (例: Bank of Japan rate hike, TSMC):",
        value="Bank of Japan rate hike Yen carry trade",
    )

with col_role:
    analyst_role = st.selectbox(
        "🎭 選擇 AI 分析師視角:",
        ["外匯與美日利差交易員", "專業總體經濟分析師", "風險控管經理人"],
    )

custom_prompt = st.text_input(
    "✍️ 自訂額外分析指令 (選填):",
    placeholder="例如：請特別評估美日利差收斂對台灣科技股與台幣匯率的潛在衝擊...",
)

news_titles = fetch_google_news(search_kw)
c1, c2 = st.columns([1, 1.2])

with c1:
    st.markdown("### 📌 最新相關新聞標題 (RSS)")
    for i, title in enumerate(news_titles, 1):
        st.write(f"**{i}.** {title}")

with c2:
    st.markdown("### 🤖 Gemini AI 情緒評分與背離診斷")
    if gemini_key and st.button("🚀 開始分析市場情緒", type="primary"):
        with st.spinner("AI 正在閱讀新聞並進行鷹鴿派與市場背離評估..."):
            news_text = "\n".join([f"- {t}" for t in news_titles])

            # 帶入最新的美日利差數據，讓 AI 報告有所本
            macro_note = ""
            if fred_df is not None and not fred_df.empty:
                macro_note = (
                    f"目前美日 10 年期公債利差為 {fred_df['US_JP_Spread'].iloc[-1]:.2f}%，"
                    f"美債 10Y-2Y 利差為 {fred_df['US_10Y_2Y_Spread'].iloc[-1]:+.2f}%。"
                )

            prompt = (
                f"你是一位【{analyst_role}】。請針對以下 8 條關於「{search_kw}」的新聞標題進行剖析：\n{news_text}\n\n"
                f"背景數據：{macro_note} 觀察標的「{selected_target_name}」近 30 日實際漲跌幅為 {pct_30d:+.2f}%。\n"
                f"額外分析要求：{custom_prompt if custom_prompt else '無'}\n\n"
                f"【重要格式指令】請務必在輸出內容的第一行單獨列出整體情緒分數（0~100整數），格式嚴格為：\n"
                f"SCORE: 75\n\n"
                f"從第二行開始以繁體中文輸出結構化報告：\n"
                f"1. **整體市場情緒分數**（0~100分，並說明多空/鷹鴿含義）\n"
                f"2. **政策或市場立場判定**（聯準會/日銀 鷹派 / 鴿派 / 樂觀 / 悲觀，並結合美日利差說明匯率傳導）\n"
                f"3. **逐條新聞情緒評分與簡評**（以 Markdown 表格呈現）"
            )

            model = genai.GenerativeModel("gemini-2.5-flash")
            response = model.generate_content(prompt)
            raw_reply = response.text

            # 解析第一行的 SCORE 分數
            score_match = re.search(r"SCORE:\s*(\d+)", raw_reply)
            ai_score = int(score_match.group(1)) if score_match else 50
            clean_reply = re.sub(r"^SCORE:\s*\d+\s*\n*", "", raw_reply)

            # 並列顯示「近 30 天標的漲跌幅」與「今日 AI 新聞情緒分數」
            st.markdown("#### 🔍 市場實際走勢 vs. AI 新聞情緒交叉比對")
            m_left, m_right = st.columns(2)
            m_left.metric(
                f"{selected_target_name} 近 30 日漲跌幅", f"{pct_30d:+.2f}%"
            )
            m_right.metric("今日 AI 新聞情緒分數", f"{ai_score} / 100 分")

            # 自動判斷是否出現情緒與市場背離
            if pct_30d < -1.0 and ai_score >= 75:
                st.error(
                    f"⚠️ **市場與輿論出現背離（利多不漲警訊）**：\n\n"
                    f"新聞情緒分數高達 **{ai_score} 分**（極度樂觀），但 **{selected_target_name}** 近 30 日卻下跌 **{pct_30d:.2f}%**，須留意利多出盡或機構趁勢平倉風險！"
                )
            elif pct_30d > 1.0 and ai_score <= 30:
                st.warning(
                    f"💡 **市場與輿論出現背離（利空不跌訊號）**：\n\n"
                    f"新聞情緒僅 **{ai_score} 分**（極度悲觀），但 **{selected_target_name}** 近 30 日卻逆勢上漲 **{pct_30d:+.2f}%**，顯示下檔買盤強勁！"
                )
            else:
                st.success(
                    f"✅ **市場與輿論方向一致**：**{selected_target_name}** 近 30 日漲跌幅（**{pct_30d:+.2f}%**）與新聞情緒（**{ai_score} 分**）未出現明顯背離。"
                )

            st.markdown("---")
            st.markdown(clean_reply)
    elif not gemini_key:
        st.info("👈 請先在左側邊欄輸入 `GEMINI_API_KEY` 以啟用 AI 分析功能。")
