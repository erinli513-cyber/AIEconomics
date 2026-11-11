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
            st.error(f"🚨 **殖利率曲線倒掛警示 (Yield Curve Inverted)**：當前 10Y-2Y 利差為 **{latest_spread:+.2f}%**（低於 0），請留意經濟衰退訊號。")
        else:
            st.info(f"💡 **殖利率曲線維持正斜率**：當前 10Y-2Y 利差為 **{latest_spread:+.2f}%**。")

        # 核心 KPI 卡片 (第一排：債券與利率)
        st.subheader("📊 關鍵公債與利率指標 (FRED)")
        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("10年期美債", f"{latest_10y:.2f}%", f"{latest_10y - prev_10y:+.2f}%")
        col2.metric("2年期美債", f"{latest_2y:.2f}%", f"{latest_2y - prev_2y:+.2f}%")
        col3.metric("10Y-2Y 利差", f"{latest_spread:.2f}%", f"{latest_spread - spread_prev:+.2f}%")
        col4.metric("日本10Y國債", f"{latest_jp:.3f}%", f"{latest_jp - jp_prev:+.3f}%")
        col5.metric("聯邦基金利率", f"{latest_fed:.2f}%")

        # 核心 KPI 卡片 (第二排：通膨與就業)
        st.subheader("📈 關鍵通膨、就業與資產現價")
        kpi_col1, kpi_col2, kpi_col3, kpi_col4, kpi_col5 = st.columns(5)
        kpi_col1.metric("CPI 物價指數", f"{latest_cpi:.1f}", f"{latest_cpi - cpi_prev:+.1f}")
        kpi_col2.metric("核心 CPI 指數", f"{latest_core_cpi:.1f}")
        kpi_col3.metric("美國失業率", f"{latest_unemp:.1f}%")
        
        gold_val = market_df["黃金現貨 (Gold GC=F)"].dropna().iloc[-1] if "黃金現貨 (Gold GC=F)" in market_df else 0.0
        oil_val = market_df["布蘭特原油 (Brent Crude)"].dropna().iloc[-1] if "布蘭特原油 (Brent Crude)" in market_df else 0.0
        kpi_col4.metric("黃金現貨 (GC=F)", f"${gold_val:.1f}")
        kpi_col5.metric("布蘭特原油", f"${oil_val:.1f}")

        # -------------------------------------------------------------
        # 市場走勢圖分析專區
        # -------------------------------------------------------------
        st.write("---")
        st.subheader("📈 市場走勢與總體指標互動折線圖")

        tab1, tab2 = st.tabs(["🏛️ 金融市場資產走勢 (yfinance)", "📊 總體經濟與利率走勢 (FRED)"])

        with tab1:
            st.caption("即時追蹤美股、台股、大宗商品（黃金/原油）、加密貨幣與匯率走勢")
            market_choice = st.selectbox(
                "選擇金融市場標的：", 
                options=market_df.columns.tolist(), 
                key="market_select"
            )
            fig1 = px.line(
                market_df, 
                y=market_choice, 
                title=f"【{market_choice}】近一年價格歷史走勢"
            )
            fig1.update_layout(
                hovermode="x unified", 
                xaxis_title="日期", 
                yaxis_title="價格 / 點數 / 匯率",
                margin=dict(l=20, r=20, t=40, b=20)
            )
            st.plotly_chart(fig1, use_container_width=True)

        with tab2:
            st.caption("即時追蹤美債各天期殖利率、日本國債、利差倒掛走勢與通膨/失業率")
            macro_choice = st.selectbox(
                "選擇總體經濟指標：", 
                options=macro_df.columns.tolist(), 
                key="macro_select"
            )
            fig2 = px.line(
                macro_df, 
                y=macro_choice, 
                title=f"【{macro_choice}】近一年歷史走勢"
            )
            fig2.update_layout(
                hovermode="x unified", 
                xaxis_title="日期", 
                yaxis_title="數值 / %",
                margin=dict(l=20, r=20, t=40, b=20)
            )
            st.plotly_chart(fig2, use_container_width=True)

        # -------------------------------------------------------------
        # AI 總體經濟即時短評 (鎖定官方指定 gemini-3.8-flash)
        # -------------------------------------------------------------
        st.write("---")
        st.subheader("🤖 AI 總體經濟即時觀點")
        st.caption("點擊按鈕調用 Gemini 依據當前最新總經與金融指標生成約 200 字精闢短評。")

        if st.button("產生 AI 總體經濟摘要", type="primary"):
            active_key = gemini_key.strip().replace('"', '').replace("'", "") if gemini_key else ""
            
            if not active_key:
                st.warning("⚠️ 請先在側邊欄輸入 Gemini API Key，或於 secrets.toml 中配置 GEMINI_API_KEY。")
            else:
                with st.spinner("AI 正在分析總經指標並撰寫短評..."):
                    try:
                        client = genai.Client(api_key=active_key)

                        prompt = f"""
你是一位資深總體經濟策略師。請依據以下最新多項總經與金融指標，以正體中文撰寫一份約 200 字以內的精準短評，不要客套寒暄，直接依序列出 3 點結論：

【當前即時指標監控】
- 美國 CPI 物價指數：{latest_cpi:.1f}（核心 CPI：{latest_core_cpi:.1f}）
- 美國失業率：{latest_unemp:.1f}%、聯邦基金利率：{latest_fed:.2f}%
- 10 年期美債：{latest_10y:.2f}%、2 年期美債：{latest_2y:.2f}%
- 10Y-2Y 美債利差：{latest_spread:+.2f}%（{'倒掛狀態' if latest_spread < 0 else '正斜率擴張'}）
- 日本 10 年期國債殖利率：{latest_jp:.3f}%
- 黃金現貨：${gold_val:.1f}、布蘭特原油：${oil_val:.1f}

【撰寫格式要求】
請提供清晰的 3 點 bullet points：
1. 通膨與勞動市場景氣現況評估
2. 利率路徑與美日利差對資金流向的影響
3. 殖利率曲線與黃金/原油對跨資產配置的一句話建議
"""

                        full_report = None
                        last_error = None

                        # 鎖定官方指定模型 gemini-3.8-flash，針對 503 重試最多 3 次
                        for attempt in range(3):
                            try:
                                response = client.models.generate_content(
                                    model="gemini-3.8-flash",
                                    contents=prompt,
                                    config=types.GenerateContentConfig(
                                        temperature=0.2,
                                        max_output_tokens=600,
                                    )
                                )
                                if response and response.text:
                                    full_report = response.text
                                    break
                            except Exception as err:
                                last_error = err
                                time.sleep(1.5)
                                continue

                        if full_report:
                            st.success("✅ AI 總經短評生成完畢：")
                            st.markdown(full_report)
                        else:
                            st.error(f"⚠️ 伺服器尖峰繁忙，生成失敗：{last_error}")

                    except Exception as ai_err:
                        st.error(f"調用 Gemini 生成失敗，錯誤訊息：{ai_err}")

    except Exception as e:
        st.error(f"數據讀取失敗，請確認 FRED API Key 是否正確。錯誤訊息: {e}")
else:
    st.info("👈 請在左側輸入您的 FRED API Key 以開啟儀表板。")
