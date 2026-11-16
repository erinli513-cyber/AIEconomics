import re
from urllib.parse import quote
import feedparser
from fredapi import Fred
import google.generativeai as genai
import pandas as pd
import plotly.express as px
import streamlit as st
import yfinance as yf

# ==========================================
# 1. 頁面設定與標題
# ==========================================
st.set_page_config(
    page_title="全球總經、美日利差與 AI 輿論情緒儀表板",
    page_icon="🌐",
    layout="wide",
)
st.title("🌐 全球總體經濟、美日利差與 AI 市場情緒背離儀表板")
st.caption(
    "整合 FRED 總經資料庫、yfinance 即時行情與 Google News RSS + Gemini 2.5 Flash 情緒量化分析"
)

# ==========================================
# 2. 側邊欄：安全讀取 Secrets 金鑰與全域設定
# ==========================================
st.sidebar.header("⚙️ API 金鑰與參數設定")

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

st.sidebar.divider()
st.sidebar.markdown("""
**📌 儀表板設計邏輯：**
1. **全球總經與五大資產**：監控美台股市、避險黃金、通膨原油與台幣匯率，並追蹤美國殖利率曲線是否倒掛。
2. **美日利差與套利傳導**：分析美日 10 年期公債利差收斂對日圓（USD/JPY）與亞幣外溢效應。
3. **NLP 情緒與市場背離**：比對近 30 日實際漲跌幅與 AI 新聞情緒分數，自動偵測「利多不漲」或「利空不跌」。
""")


# ==========================================
# 3. 數據抓取函式庫（附帶快取保護 API 配額）
# ==========================================
@st.cache_data(ttl=1800)
def fetch_yf_close(ticker, period="3mo"):
    data = yf.download(ticker, period=period, progress=False)
    if data.empty:
        return pd.Series(dtype=float)
    if isinstance(data.columns, pd.MultiIndex):
        return data["Close"][ticker].dropna()
    return data["Close"].dropna()


@st.cache_data(ttl=3600)
def fetch_all_fred_data(api_key):
    fred = Fred(api_key=api_key)
    # 抓取原有核心總經指標 + 日本 10 年期公債殖利率
    us_10y = fred.get_series("GS10", observation_start="2020-01-01")
    us_2y = fred.get_series("GS2", observation_start="2020-01-01")
    jp_10y = fred.get_series(
        "IRLTLT01JPM156N", observation_start="2020-01-01"
    )
    fed_rate = fred.get_series("FEDFUNDS", observation_start="2020-01-01")
    unrate = fred.get_series("UNRATE", observation_start="2020-01-01")
    cpi = fred.get_series("CPIAUCSL", observation_start="2019-01-01")

    df = pd.DataFrame({
        "US_10Y": us_10y,
        "US_2Y": us_2y,
        "JP_10Y": jp_10y,
        "FED_FUNDS": fed_rate,
        "UNRATE": unrate,
        "CPI": cpi,
    })
    # 計算 CPI 年增率 (%)
    df["CPI_YoY"] = df["CPI"].pct_change(12) * 100
    # 計算美債 10Y-2Y 利差（景氣衰退指標）
    df["US_10Y_2Y_Spread"] = df["US_10Y"] - df["US_2Y"]
    # 計算美日 10Y 利差（日圓套利交易指標）
    df["US_JP_10Y_Spread"] = df["US_10Y"] - df["JP_10Y"]
    return df.dropna(subset=["US_10Y", "US_2Y", "JP_10Y"])


@st.cache_data(ttl=1800)
def fetch_google_news(keyword):
    safe_keyword = quote(keyword)
    url = f"https://news.google.com/rss/search?q={safe_keyword}&hl=en-US"
    feed = feedparser.parse(url)
    return [entry.title for entry in feed.entries[:8]]


def calc_period_return(series, days=22):
    if len(series) < 2:
        return 0.0, 0.0
    latest = float(series.iloc[-1])
    idx = -days if len(series) >= days else 0
    past = float(series.iloc[idx])
    pct = ((latest - past) / past) * 100
    return latest, pct


# ==========================================
# 4. 頂部常駐區：原有 5 欄核心金融市場 KPI 總覽
# ==========================================
st.subheader("📈 全球五大核心資產即時行情總覽")

kpi_assets = [
    ("🇺🇸 標普 500 (^GSPC)", "^GSPC", ",.2f"),
    ("🇹🇼 台灣加權 (^TWII)", "^TWII", ",.2f"),
    ("🥇 黃金現貨 (GC=F)", "GC=F", ",.2f"),
    ("🛢️ 布蘭特原油 (BZ=F)", "BZ=F", ",.2f"),
    ("💱 美元/台幣 (USD/TWD)", "TWD=X", ".2f"),
]

kpi_cols = st.columns(5)
market_cache = {}

for col, (label, ticker, fmt) in zip(kpi_cols, kpi_assets):
    s = fetch_yf_close(ticker, period="3mo")
    market_cache[ticker] = s
    if not s.empty:
        latest_val = float(s.iloc[-1])
        prev_val = float(s.iloc[-2]) if len(s) >= 2 else latest_val
        daily_pct = ((latest_val - prev_val) / prev_val) * 100
        col.metric(
            label=label, value=f"{latest_val:{fmt}}", delta=f"{daily_pct:+.2f}%"
        )
    else:
        col.metric(label=label, value="N/A", delta="無法載入")

st.divider()

# ==========================================
# 5. 三分頁主體架構：融合原有總經 + 美日利差 + NLP 背離分析
# ==========================================
tab1, tab2, tab3 = st.tabs([
    "🏛️ 美國總經與殖利率曲線 (原有核心)",
    "💴 美日利差與套利交易傳導 (延伸主軸)",
    "🤖 AI 新聞情緒與市場背離偵測 (NLP 亮點)",
])

# 預先載入 FRED 資料供 Tab 1 與 Tab 2 共用
fred_df = None
if fred_key:
    try:
        fred_df = fetch_all_fred_data(fred_key)
    except Exception as e:
        st.error(f"FRED API 讀取失敗，請檢查金鑰是否正確：{e}")

# ------------------------------------------
# TAB 1：保留原有美國總經指標與 10Y-2Y 倒掛警告
# ------------------------------------------
with tab1:
    if fred_df is not None and not fred_df.empty:
        latest_row = fred_df.iloc[-1]
        spread_10_2 = latest_row["US_10Y_2Y_Spread"]

        # 保留原有的殖利率倒掛警示功能
        if spread_10_2 < 0:
            st.error(
                f"🚨 **美債殖利率曲線倒掛警報**：目前 10Y - 2Y 利差為 **{spread_10_2:.2f}%**（負值），歷史經驗顯示為經濟衰退領先訊號。"
            )
        else:
            st.success(
                f"✅ **美債殖利率曲線恢復正斜率**：目前 10Y - 2Y 利差為 **{spread_10_2:+.2f}%**。"
            )

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("聯邦基準利率 (FEDFUNDS)", f"{latest_row['FED_FUNDS']:.2f}%")
        m2.metric("美國 CPI 年增率", f"{latest_row['CPI_YoY']:.2f}%")
        m3.metric("美國失業率 (UNRATE)", f"{latest_row['UNRATE']:.1f}%")
        m4.metric("美債 10Y - 2Y 利差", f"{spread_10_2:+.2f}%")

        c_left, c_right = st.columns(2)
        with c_left:
            fig_us_yield = px.line(
                fred_df,
                y=["US_10Y", "US_2Y", "FED_FUNDS"],
                title="美國長短期公債殖利率與基準利率走勢 (%)",
                labels={"value": "利率 (%)", "index": "日期"},
            )
            st.plotly_chart(fig_us_yield, use_container_width=True)

        with c_right:
            selected_asset_t1 = st.selectbox(
                "選擇下方走勢圖檢視之全球資產：",
                ["^GSPC", "^TWII", "GC=F", "BZ=F", "TWD=X"],
                key="tab1_asset_select",
            )
            s_t1 = market_cache.get(selected_asset_t1, pd.Series(dtype=float))
            if not s_t1.empty:
                fig_asset = px.line(
                    x=s_t1.index,
                    y=s_t1.values,
                    title=f"{selected_asset_t1} 近三個月價格走勢",
                    labels={"x": "日期", "y": "價格 / 匯率"},
                )
                st.plotly_chart(fig_asset, use_container_width=True)
    else:
        st.info(
            "👈 請在左側邊欄輸入您的 `FRED_API_KEY` 以載入美國總體經濟數據。"
        )

# ------------------------------------------
# TAB 2：延伸主軸 — 美日 10Y 公債利差與亞洲匯率聯動
# ------------------------------------------
with tab2:
    st.markdown("""
    **經濟傳導機制說明：** 當美國聯準會（Fed）啟動降息、而日本央行（BOJ）走向升息時，**美日 10 年期公債利差收斂**，
    將削弱借低息日圓買高息美元資產的「日圓套利交易（Yen Carry Trade）」誘因，引發日圓急升並外溢影響台幣匯率與亞股外資流向。
    """)

    jpy_series = fetch_yf_close("JPY=X", period="3mo")
    twd_series = market_cache.get("TWD=X", pd.Series(dtype=float))
    n225_series = fetch_yf_close("^N225", period="3mo")

    col_jp1, col_jp2 = st.columns(2)

    with col_jp1:
        if fred_df is not None and not fred_df.empty:
            cur_jp_spread = fred_df["US_JP_10Y_Spread"].iloc[-1]
            prev_jp_spread = fred_df["US_JP_10Y_Spread"].iloc[-2]
            diff_jp_spread = cur_jp_spread - prev_jp_spread

            st.metric(
                label="🇺🇸-🇯🇵 美日 10 年期公債利差 (US 10Y - JP 10Y)",
                value=f"{cur_jp_spread:.2f}%",
                delta=f"{diff_jp_spread:+.2f}% (較上月)",
                delta_color="inverse",
            )
            fig_jp_spread = px.line(
                fred_df,
                y=["US_10Y", "JP_10Y", "US_JP_10Y_Spread"],
                title="美日 10 年期公債殖利率與利差變化 (%)",
                labels={"value": "殖利率 / 利差 (%)", "index": "日期"},
            )
            st.plotly_chart(fig_jp_spread, use_container_width=True)
        else:
            st.info("👈 請在左側輸入 FRED API Key 以檢視美日公債利差圖表。")

    with col_jp2:
        fx_choice = st.selectbox(
            "選擇觀察的亞洲匯率 / 指數連動標的：",
            ["美元兌日圓 (JPY=X)", "美元兌台幣 (TWD=X)", "日經 225 指數 (^N225)"],
            key="tab2_fx_select",
        )
        fx_map = {
            "美元兌日圓 (JPY=X)": jpy_series,
            "美元兌台幣 (TWD=X)": twd_series,
            "日經 225 指數 (^N225)": n225_series,
        }
        chosen_fx_series = fx_map[fx_choice]
        if not chosen_fx_series.empty:
            fx_now, fx_30d = calc_period_return(chosen_fx_series, days=22)
            st.metric(
                label=f"{fx_choice} 最新報價",
                value=f"{fx_now:,.2f}",
                delta=f"{fx_30d:+.2f}% (近 30 個交易日)",
            )
            fig_fx = px.line(
                x=chosen_fx_series.index,
                y=chosen_fx_series.values,
                title=f"{fx_choice} 近三個月走勢",
                labels={"x": "日期", "y": "匯率 / 點數"},
            )
            st.plotly_chart(fig_fx, use_container_width=True)

# ------------------------------------------
# TAB 3：NLP 新聞情緒分析 + 情緒與市場背離自動判讀
# ------------------------------------------
with tab3:
    st.subheader("📰 即時財經新聞抓取與「情緒 vs. 市場背離」自動診斷")

    col_target, col_kw, col_role = st.columns([1.1, 1.2, 1])

    with col_target:
        diverge_options = {
            "美元兌日圓 (JPY=X)": ("JPY=X", jpy_series),
            "美元兌台幣 (TWD=X)": ("TWD=X", twd_series),
            "台灣加權指數 (^TWII)": (
                "^TWII",
                market_cache.get("^TWII", pd.Series(dtype=float)),
            ),
            "標普 500 指數 (^GSPC)": (
                "^GSPC",
                market_cache.get("^GSPC", pd.Series(dtype=float)),
            ),
            "黃金現貨 (GC=F)": (
                "GC=F",
                market_cache.get("GC=F", pd.Series(dtype=float)),
            ),
        }
        selected_div_label = st.selectbox(
            "🎯 1. 選擇要與新聞比對的市場標的：",
            list(diverge_options.keys()),
            key="tab3_target_select",
        )
        div_ticker, div_series = diverge_options[selected_div_label]
        _, target_pct_30d = calc_period_return(div_series, days=22)

    with col_kw:
        search_kw = st.text_input(
            "🔍 2. 輸入 Google News 搜尋關鍵字：",
            value="Bank of Japan rate hike Yen carry trade",
        )

    with col_role:
        analyst_role = st.selectbox(
            "🎭 3. 選擇 AI 分析師視角：",
            ["外匯與利差交易員", "總體經濟學家", "亞股外資風控長"],
            key="tab3_role_select",
        )

    custom_prompt = st.text_input(
        "✍️ 自訂額外分析指令 (選填)：",
        placeholder="例如：請評估美日利差變化對台幣匯率及台股科技股外資資金流向的衝擊...",
    )

    news_titles = fetch_google_news(search_kw)
    c_news, c_ai = st.columns([1, 1.3])

    with c_news:
        st.markdown("### 📌 最新相關新聞標題 (RSS)")
        if news_titles:
            for i, title in enumerate(news_titles, 1):
                st.write(f"**{i}.** {title}")
        else:
            st.warning("找不到相關新聞，請嘗試更改關鍵字。")

    with c_ai:
        st.markdown("### 🤖 Gemini AI 情緒評分與背離診斷")
        if gemini_key and st.button(
            "🚀 開始執行情緒與市場背離分析", type="primary"
        ):
            with st.spinner(
                "Gemini 2.5 Flash 正在分析新聞鷹鴿立場並計算背離指標..."
            ):
                news_text = "\n".join([f"- {t}" for t in news_titles])

                # 抓取最新總經數據作為背景上下文餵給 AI，讓報告「有所本」
                macro_context = "目前無 FRED 總經數據。"
                if fred_df is not None and not fred_df.empty:
                    r = fred_df.iloc[-1]
                    macro_context = (
                        f"美國10Y殖利率: {r['US_10Y']:.2f}%, 日本10Y殖利率: {r['JP_10Y']:.2f}%, "
                        f"美日10Y利差: {r['US_JP_10Y_Spread']:.2f}%, 美債10Y-2Y利差: {r['US_10Y_2Y_Spread']:+.2f}%"
                    )

                prompt = f"""
你是一位【{analyst_role}】。請結合以下真實總經背景與最新新聞標題，進行深度市場評估：
【當前總經環境數據】：{macro_context}
【觀察市場標的】：{selected_div_label}（近 30 個交易日實際漲跌幅為 {target_pct_30d:+.2f}%）
【關於「{search_kw}」的最新 8 條新聞標題】：
{news_text}

額外分析要求：{custom_prompt if custom_prompt else '無'}

【強制格式要求】
請在回答的**第一行**固定輸出整體新聞情緒分數（0 到 100 的整數，0 為極度悲觀/利空，50 為中性，100 為極度樂觀/利多），格式必須完全如下：
SCORE: 75

接著從第二行開始，以繁體中文輸出結構化報告：
1. **央行立場與市場情緒總評**：（判讀聯準會與日本銀行的鷹鴿風向，以及整體風險偏好）
2. **總經利差與匯率/資產傳導推演**：（結合上方的美日利差與實際漲跌幅，分析資金流向與後續風險）
3. **逐條新聞情緒評分與簡評**：（以 Markdown 表格呈現：新聞編號與摘要、情緒分數 0-100、鷹鴿/多空解讀）
"""
                try:
                    model = genai.GenerativeModel("gemini-2.5-flash")
                    response = model.generate_content(prompt)
                    raw_text = response.text

                    match = re.search(r"SCORE:\s*(\d+)", raw_text)
                    ai_score = int(match.group(1)) if match else 50
                    clean_report = re.sub(
                        r"^SCORE:\s*\d+\s*\n*", "", raw_text
                    )

                    # 並列顯示「近 30 天標的漲跌幅」與「今日 AI 新聞情緒分數」
                    st.markdown("#### 🔍 市場表現 vs. 輿論情緒交叉比對")
                    k1, k2 = st.columns(2)
                    k1.metric(
                        f"{selected_div_label} (近 30 日漲跌幅)",
                        f"{target_pct_30d:+.2f}%",
                    )
                    k2.metric("今日 AI 新聞情緒分數", f"{ai_score} / 100 分")

                    # 背離自動判讀邏輯
                    if target_pct_30d < -1.0 and ai_score >= 75:
                        st.error(
                            f"⚠️ **市場與輿論出現背離（利多不漲警訊）**：\n\n"
                            f"新聞輿論高度樂觀（**{ai_score} 分**），但 **{selected_div_label}** 近 30 日實際下跌 **{target_pct_30d:.2f}%**。"
                            f"代表市場可能已提前反應利多（Price-in），或機構正趁利多平倉出貨，請警惕追高風險！"
                        )
                    elif target_pct_30d > 1.0 and ai_score <= 30:
                        st.warning(
                            f"💡 **市場與輿論出現背離（利空不跌／軋空訊號）**：\n\n"
                            f"新聞面極度悲觀（僅 **{ai_score} 分**），但 **{selected_div_label}** 近 30 日卻逆勢上漲 **{target_pct_30d:+.2f}%**。"
                            f"顯示底部買盤強勁、利空測試不破，可能正在醞釀空頭回補行情。"
                        )
                    else:
                        st.success(
                            f"✅ **市場與輿論方向一致（趨勢共振）**：\n\n"
                            f"**{selected_div_label}** 近 30 日表現（**{target_pct_30d:+.2f}%**）與 AI 新聞情緒（**{ai_score} 分**）方向相符，無明顯背離。"
                        )

                    st.markdown("---")
                    st.markdown(clean_report)

                except Exception as e:
                    st.error(f"AI 分析執行失敗：{e}")
        elif not gemini_key:
            st.info(
                "👈 請在左側邊欄輸入您的 `GEMINI_API_KEY` 以啟動 AI 情緒與背離分析。"
            )
